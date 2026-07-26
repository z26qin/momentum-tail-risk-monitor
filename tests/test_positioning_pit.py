"""Short interest must never be visible before FINRA published it."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data.finra import attach_publication_dates, business_day_offset
from src.features.positioning_panel import (
    build_leg_membership,
    short_interest_step_function,
)
from src.utils.io import DEFAULT_PROCESSED_DIR


TRADING_DATES = pd.DatetimeIndex(pd.bdate_range("2024-01-02", "2024-03-29"))


def _short_interest() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "settlement_date": pd.to_datetime(
                ["2024-01-15", "2024-01-31", "2024-02-15"]
            ),
            "symbol": ["AAA", "AAA", "AAA"],
            "short_interest_shares": [1_000.0, 2_000.0, 3_000.0],
            "finra_average_daily_volume": [100.0, 100.0, 100.0],
            "finra_days_to_cover": [10.0, 20.0, 30.0],
            "stock_split_flag": ["", "", ""],
            "revision_flag": ["", "", ""],
        }
    )


def _schedule() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "settlement_date": pd.to_datetime(
                ["2024-01-15", "2024-01-31", "2024-02-15"]
            ),
            "due_date": pd.to_datetime(["2024-01-17", "2024-02-02", "2024-02-20"]),
            "publication_date": pd.to_datetime(
                ["2024-01-25", "2024-02-09", "2024-02-27"]
            ),
        }
    )


def test_a_print_is_invisible_before_its_publication_date():
    short_interest = _short_interest()
    publication = attach_publication_dates(
        short_interest["settlement_date"].unique(), _schedule()
    )
    expanded = short_interest_step_function(
        short_interest, publication, TRADING_DATES, ["AAA"]
    )

    observed = expanded.dropna(subset=["short_interest_shares"])
    assert (observed["publication_date"] <= observed["trading_date"]).all()

    # The 2024-01-15 print settles well before it publishes. Joining on the
    # settlement date would make it visible on 2024-01-16; joining on the
    # publication date must not.
    on_jan_16 = expanded.loc[expanded["trading_date"] == pd.Timestamp("2024-01-16")]
    assert on_jan_16["short_interest_shares"].isna().all()

    on_jan_25 = expanded.loc[expanded["trading_date"] == pd.Timestamp("2024-01-25")]
    assert on_jan_25["short_interest_shares"].iloc[0] == 1_000.0


def test_value_is_a_step_function_that_only_updates_on_publication_dates():
    short_interest = _short_interest()
    publication = attach_publication_dates(
        short_interest["settlement_date"].unique(), _schedule()
    )
    expanded = short_interest_step_function(
        short_interest, publication, TRADING_DATES, ["AAA"]
    ).sort_values("trading_date")

    changes = expanded.loc[
        expanded["short_interest_shares"].diff().fillna(0) != 0, "trading_date"
    ]
    publication_dates = set(_schedule()["publication_date"])
    assert set(changes).issubset(publication_dates)


def test_settlement_date_is_carried_as_metadata_only():
    short_interest = _short_interest()
    publication = attach_publication_dates(
        short_interest["settlement_date"].unique(), _schedule()
    )
    expanded = short_interest_step_function(
        short_interest, publication, TRADING_DATES, ["AAA"]
    )
    observed = expanded.dropna(subset=["short_interest_shares"])
    # Present for audit, but always strictly older than the publication date it
    # was gated on, so it can never have driven the join.
    assert (observed["settlement_date"] < observed["publication_date"]).all()


def test_uncovered_settlement_dates_fall_back_and_are_flagged():
    settlements = pd.to_datetime(["2024-01-15", "2024-06-14"])
    publication = attach_publication_dates(settlements, _schedule())
    rules = dict(
        zip(publication["settlement_date"], publication["publication_date_rule"])
    )
    assert rules[pd.Timestamp("2024-01-15")] == "finra_published_schedule"
    assert rules[pd.Timestamp("2024-06-14")] == "settlement_plus_8_business_days"

    fallback_row = publication.loc[
        publication["settlement_date"] == pd.Timestamp("2024-06-14")
    ].iloc[0]
    assert fallback_row["publication_date"] == business_day_offset(
        pd.Timestamp("2024-06-14"), 7
    )
    # The sensitivity variant is carried for every row so the operator can see
    # whether the publication-date choice moves anything.
    assert fallback_row["publication_date_sensitivity_10bd"] > fallback_row[
        "publication_date"
    ]


def test_leg_membership_is_constant_within_a_month_and_lagged_by_one_month():
    dates = pd.DatetimeIndex(pd.bdate_range("2020-01-01", "2022-12-31"))
    generator = np.random.default_rng(11)
    frames = []
    for index, symbol in enumerate(f"S{value:02d}" for value in range(30)):
        drift = 0.0004 * (index - 15)
        returns = generator.normal(drift, 0.02, size=len(dates))
        frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "symbol": symbol,
                    "close_total_return_adjusted": 100 * np.exp(np.cumsum(returns)),
                }
            )
        )
    prices = pd.concat(frames, ignore_index=True)

    membership = build_leg_membership(prices, dates)
    per_month = membership.groupby(
        membership["trading_date"].dt.to_period("M")
    )["symbol"].apply(lambda values: tuple(sorted(set(values))))
    # Constituents are fixed for the whole month.
    for period, symbols in per_month.items():
        rows = membership.loc[membership["trading_date"].dt.to_period("M") == period]
        for _, day in rows.groupby("trading_date"):
            assert tuple(sorted(day["symbol"])) == symbols

    # Membership effective in month m was formed in month m-1.
    assert (
        membership["effective_month"].dt.to_period("M")
        - membership["formation_month"].dt.to_period("M")
    ).map(lambda offset: offset.n).eq(1).all()


# --------------------------------------------------------------------------
# Assertions against the built panel
# --------------------------------------------------------------------------


def _panel_path():
    return DEFAULT_PROCESSED_DIR / "positioning_panel.parquet"


@pytest.mark.skipif(not _panel_path().is_file(), reason="positioning panel not built")
def test_built_panel_has_no_short_interest_before_the_first_publication_date():
    panel = pd.read_parquet(_panel_path())
    schedule = pd.read_parquet(
        DEFAULT_PROCESSED_DIR / "finra_publication_schedule.parquet"
    )
    short_interest = pd.read_parquet(
        DEFAULT_PROCESSED_DIR / "finra_short_interest.parquet"
    )
    publication = attach_publication_dates(
        short_interest["settlement_date"].unique(), schedule
    )
    earliest_publication = publication["publication_date"].min()

    visible = panel.dropna(subset=["days_to_cover"])
    assert visible["trading_date"].min() >= earliest_publication, (
        "days_to_cover is populated before any short-interest print had been "
        "published"
    )


@pytest.mark.skipif(not _panel_path().is_file(), reason="positioning panel not built")
def test_built_panel_records_the_publication_date_branch():
    panel = pd.read_parquet(_panel_path())
    assert "publication_date_rule" in panel.columns
    assert panel["publication_date_rule"].nunique() == 1
    assert panel["publication_date_rule"].iloc[0] == "finra_published_schedule"
