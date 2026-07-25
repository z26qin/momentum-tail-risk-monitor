"""The volume-free crowding metrics must not contain volume, and must not
mistake a stock split for a crowding jump.

``days_to_cover`` divides by volume, so it collapses in the volume spikes this
panel exists to describe. These metrics were added to give the evidence layer a
crowding reading that cannot invert for that reason, so the property worth
pinning is a negative one: no perturbation of volume, however large, may move
them at all.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data.sec_edgar import point_in_time_shares_outstanding
from src.features.positioning_panel import (
    SHORT_INTEREST_MIN_PRINTS,
    short_interest_intensity,
    short_interest_utilisation,
    split_consistent_short_interest,
)
from src.utils.io import DEFAULT_PROCESSED_DIR


SETTLEMENTS = pd.to_datetime(
    [
        "2024-01-15",
        "2024-01-31",
        "2024-02-15",
        "2024-02-29",
        "2024-03-15",
        "2024-03-29",
        "2024-04-15",
        "2024-04-30",
    ]
)


def _short_interest(shares: list[float] | None = None) -> pd.DataFrame:
    shares = shares if shares is not None else [1_000.0] * len(SETTLEMENTS)
    return pd.DataFrame(
        {
            "settlement_date": SETTLEMENTS,
            "symbol": ["AAA"] * len(SETTLEMENTS),
            "short_interest_shares": shares,
            "previous_short_interest_shares": [np.nan] + shares[:-1],
        }
    )


def _prices(split_factor: list[float] | None = None) -> pd.DataFrame:
    dates = pd.DatetimeIndex(pd.bdate_range("2023-12-01", "2024-05-31"))
    factors = (
        np.ones(len(dates)) if split_factor is None else np.asarray(split_factor)
    )
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": "AAA",
            "split_factor_after": factors,
            "volume_as_traded": 1_000_000.0,
        }
    )


def _ratios(short_interest: pd.DataFrame, prices: pd.DataFrame) -> pd.Series:
    frame = short_interest_intensity(
        split_consistent_short_interest(short_interest, prices),
        min_prints=SHORT_INTEREST_MIN_PRINTS,
    )
    return frame.set_index("settlement_date")["short_interest_ratio"]


def test_volume_cannot_move_the_metric_at_all():
    """The whole point. Volume is absent, so any volume is the same volume."""

    short_interest = _short_interest([1_000, 1_100, 900, 1_050, 1_200, 1_150, 2_400, 1_300])
    quiet = _prices()

    spiked = _prices()
    # A 500x volume explosion of the kind that drove days_to_cover to -2.23
    # sigma in March 2020, applied to the second half of the sample.
    spiked.loc[spiked["date"] >= "2024-03-01", "volume_as_traded"] *= 500.0

    pd.testing.assert_series_equal(
        _ratios(short_interest, quiet), _ratios(short_interest, spiked)
    )


def test_a_stock_split_does_not_look_like_a_crowding_jump():
    """BKNG's 25:1 split produced a raw ratio of 37 on a leg whose median was
    1.17, and FINRA's own stock_split_flag was blank on those prints."""

    unsplit = _short_interest([1_000, 1_100, 900, 1_050, 1_200, 1_150, 1_000, 1_100])

    # Same economic position, but the last two prints are reported in post-split
    # shares after a 25:1 split on 2024-04-01.
    split_shares = [1_000, 1_100, 900, 1_050, 1_200, 1_150, 25_000, 27_500]
    after_split = _short_interest(split_shares)
    factors = _prices()
    factors["split_factor_after"] = np.where(
        factors["date"] < pd.Timestamp("2024-04-01"), 25.0, 1.0
    )

    pd.testing.assert_series_equal(
        _ratios(unsplit, _prices()),
        _ratios(after_split, factors),
        check_names=False,
    )


def test_an_unadjusted_split_would_have_been_caught():
    """Guards the guard: without the adjustment the ratio really does explode,
    so the test above is not passing vacuously."""

    split_shares = [1_000, 1_100, 900, 1_050, 1_200, 1_150, 25_000, 27_500]
    naive = short_interest_intensity(
        _short_interest(split_shares).assign(
            short_interest_shares_adjusted=split_shares
        ),
        min_prints=SHORT_INTEREST_MIN_PRINTS,
    )
    assert naive["short_interest_ratio"].max() > 20.0


def test_a_future_print_cannot_change_todays_ratio():
    base = [1_000, 1_100, 900, 1_050, 1_200, 1_150, 1_000, 1_100]
    mutated = list(base)
    mutated[-1] = 99_000.0

    original = _ratios(_short_interest(base), _prices())
    perturbed = _ratios(_short_interest(mutated), _prices())

    earlier = SETTLEMENTS[:-1]
    pd.testing.assert_series_equal(original.loc[earlier], perturbed.loc[earlier])


def test_the_baseline_excludes_the_current_print():
    """A level compared against a window containing itself understates every
    move, so the median must be lagged one print."""

    shares = [1_000.0] * 7 + [5_000.0]
    ratios = _ratios(_short_interest(shares), _prices())
    # Baseline is a flat 1_000 of prior prints, so the jump reads at full size.
    assert ratios.iloc[-1] == pytest.approx(5.0)


def test_ratio_is_unavailable_until_enough_prints_exist():
    ratios = _ratios(_short_interest(), _prices())
    assert ratios.iloc[: SHORT_INTEREST_MIN_PRINTS].isna().all()
    assert ratios.iloc[SHORT_INTEREST_MIN_PRINTS:].notna().all()


def test_one_symbols_history_cannot_leak_into_another():
    two = pd.concat(
        [_short_interest(), _short_interest().assign(symbol="BBB")],
        ignore_index=True,
    )
    prices = pd.concat([_prices(), _prices().assign(symbol="BBB")], ignore_index=True)
    frame = short_interest_intensity(
        split_consistent_short_interest(two, prices),
        min_prints=SHORT_INTEREST_MIN_PRINTS,
    )
    first_by_symbol = frame.groupby("symbol")["short_interest_ratio"].apply(
        lambda s: s.reset_index(drop=True).iloc[0]
    )
    assert first_by_symbol.isna().all()


# --------------------------------------------------------------------------
# The built panel
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    path = DEFAULT_PROCESSED_DIR / "positioning_panel.parquet"
    if not path.is_file():
        pytest.skip("positioning panel has not been built")
    return pd.read_parquet(path)


def test_panel_carries_the_volume_free_columns(panel: pd.DataFrame):
    for column in (
        "short_interest_ratio",
        "short_interest_ratio_mean",
        "short_interest_ratio_z",
        "short_interest_change",
    ):
        assert column in panel.columns
    assert panel["short_interest_ratio"].notna().sum() > 1_500


def test_leg_ratio_stays_in_a_plausible_range(panel: pd.DataFrame):
    """A leg median far above ~2 means a split slipped through again."""

    ratio = panel["short_interest_ratio"].dropna()
    assert ratio.between(0.3, 2.5).all(), ratio.describe()


def test_the_volume_free_metric_does_not_invert_like_days_to_cover(panel: pd.DataFrame):
    """The defect that motivated this work: in volume spikes days_to_cover
    reads 'uncrowded' precisely when crowding matters most."""

    stressed = panel.loc[panel["days_to_cover_z"] < -1.0]
    assert len(stressed) > 100
    assert stressed["days_to_cover_z"].mean() < -1.0
    assert stressed["short_interest_ratio_z"].mean() > -0.5


# --------------------------------------------------------------------------
# Short interest as a fraction of float
# --------------------------------------------------------------------------


def _shares(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": "AAA",
            "end_date": pd.to_datetime([r[0] for r in rows]),
            "filed_date": pd.to_datetime([r[1] for r in rows]),
            "shares_outstanding": [r[2] for r in rows],
            "shares_source": "EntityCommonStockSharesOutstanding",
        }
    )


def test_shares_outstanding_is_visible_only_from_its_filing_date():
    """The balance-sheet date is weeks before the filing date. Using it would
    hand the panel a number nobody could have read yet."""

    shares = _shares([("2024-03-31", "2024-04-25", 1_000_000.0)])
    short_interest = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA"],
            "settlement_date": pd.to_datetime(["2024-04-15", "2024-04-30"]),
            # One publishes between the period end and the filing, one after.
            "publication_date": pd.to_datetime(["2024-04-20", "2024-05-08"]),
            "short_interest_shares_adjusted": [50_000.0, 50_000.0],
        }
    )
    out = short_interest_utilisation(short_interest, shares, _prices())
    by_date = out.set_index("publication_date")["short_interest_utilisation"]

    assert pd.isna(by_date.loc[pd.Timestamp("2024-04-20")])
    assert by_date.loc[pd.Timestamp("2024-05-08")] == pytest.approx(0.05)


def test_a_restated_prior_period_does_not_become_the_current_count():
    """Airbnb's FY2021 10-K carries FY2019 shares as a comparative, filed 787
    days after that period ended. Taking the latest *filing* would make a
    three-year-old count the current one."""

    shares = _shares(
        [
            ("2023-12-31", "2024-02-01", 1_000_000.0),
            ("2021-12-31", "2024-02-01", 400_000.0),  # comparative, same filing
        ]
    )
    kept = point_in_time_shares_outstanding(shares)
    assert list(kept["end_date"].dt.year) == [2023]
    assert kept["shares_outstanding"].tolist() == [1_000_000.0]


def test_a_cover_page_dated_after_its_own_filing_is_dropped():
    """Adobe's 2010 10-K claims a share count as of a date five months after
    it was filed. That is impossible, so it is a tagging error."""

    shares = _shares(
        [
            ("2010-06-15", "2010-01-22", 524_119_635.0),
            ("2023-12-31", "2024-02-01", 1_000_000.0),
        ]
    )
    kept = point_in_time_shares_outstanding(shares)
    assert list(kept["end_date"].dt.year) == [2023]


def test_utilisation_is_absent_rather_than_guessed_when_no_filing_exists():
    short_interest = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "settlement_date": pd.to_datetime(["2024-04-15"]),
            "publication_date": pd.to_datetime(["2024-04-20"]),
            "short_interest_shares_adjusted": [50_000.0],
        }
    )
    out = short_interest_utilisation(short_interest, pd.DataFrame(), _prices())
    assert out["short_interest_utilisation"].isna().all()


def test_panel_utilisation_is_a_plausible_fraction(panel: pd.DataFrame):
    """A leg median outside roughly 0.5%-10% of float means the two sides were
    put on different share bases."""

    util = panel["short_interest_utilisation"].dropna()
    assert len(util) > 1_500
    assert util.between(0.005, 0.10).all(), util.describe()


def test_utilisation_does_not_invert_during_stress(panel: pd.DataFrame):
    stressed = panel.loc[panel["days_to_cover_z"] < -1.0]
    assert stressed["days_to_cover_z"].mean() < -1.0
    assert stressed["short_interest_utilisation_z"].mean() > -0.5
