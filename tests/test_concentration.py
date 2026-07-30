from __future__ import annotations

import numpy as np
import pandas as pd

from src.portfolio.momentum import build_portfolio_returns
from src.risk.concentration import (
    CONCENTRATION_HISTORY_COLUMNS,
    build_concentration_history,
    build_constituent_return_history,
    build_rebalance_diagnostics,
    effective_bets,
    holding_overlap,
    sector_concentration,
    top_absolute_share,
)


def _prices() -> pd.DataFrame:
    dates = pd.DatetimeIndex(
        [pd.Timestamp("2024-01-31"), *pd.bdate_range("2024-02-01", "2024-02-29")]
    )
    daily_returns = {
        "AAA": 0.010,
        "BBB": -0.005,
        "CCC": 0.020,
        "DDD": -0.010,
    }
    records = []
    for symbol, daily_return in daily_returns.items():
        for index, date in enumerate(dates):
            records.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "close_total_return_adjusted": 100.0
                    * (1.0 + daily_return) ** index,
                }
            )
    return pd.DataFrame(records)


def _holdings() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "formation_date": [pd.Timestamp("2024-01-31")] * 4,
            "effective_month": [pd.Period("2024-02")] * 4,
            "symbol": ["AAA", "BBB", "CCC", "DDD"],
            "leg": ["long", "long", "short", "short"],
            "weight": [0.5, 0.5, -0.5, -0.5],
        }
    )


def test_effective_bets_normalizes_signed_and_non_normalized_input() -> None:
    assert effective_bets([0.5, 0.5, -0.5, -0.5]) == 4.0
    assert effective_bets([5.0, 5.0, -5.0, -5.0]) == 4.0
    assert effective_bets([1.0, 0.0, 0.0]) == 1.0


def test_effective_bets_keeps_missing_and_zero_input_unavailable() -> None:
    assert effective_bets([]) is None
    assert effective_bets([0.0, 0.0]) is None
    assert effective_bets([1.0, np.nan]) is None


def test_top_five_absolute_share_uses_absolute_denominator() -> None:
    assert np.isclose(top_absolute_share([1, -2, 3, -4, 5, -6], top_n=5), 20 / 21)
    assert top_absolute_share([0.0, 0.0], top_n=5) is None


def test_sector_hhi_includes_missing_classification_as_explicit_bucket() -> None:
    result = sector_concentration(
        [0.25, -0.25, 0.25, -0.25],
        ["Technology", "Technology", "Finance", None],
    )
    assert np.isclose(result["sector_hhi"], 0.375)
    assert np.isclose(result["top_sector_exposure_share"], 0.5)
    assert np.isclose(result["top_two_sector_exposure_share"], 0.75)
    assert np.isclose(result["missing_sector_exposure_share"], 0.25)


def test_constituent_contributions_reconcile_exactly_to_phase2_returns() -> None:
    prices = _prices()
    holdings = _holdings()
    constituents = build_constituent_return_history(prices, holdings)
    phase2 = build_portfolio_returns(prices, holdings)
    contributions = (
        constituents.groupby(["date", "leg"])["signed_contribution"]
        .sum(min_count=1)
        .unstack("leg")
        .rename(columns={"long": "long_rebuilt", "short": "short_rebuilt"})
        .reset_index()
    )
    merged = phase2.merge(contributions, on="date", validate="one_to_one")
    np.testing.assert_allclose(
        merged["long_contribution"],
        merged["long_rebuilt"],
        rtol=0.0,
        atol=1e-15,
    )
    np.testing.assert_allclose(
        merged["short_contribution"],
        merged["short_rebuilt"],
        rtol=0.0,
        atol=1e-15,
    )
    np.testing.assert_allclose(
        merged["portfolio_return"],
        merged["long_rebuilt"] + merged["short_rebuilt"],
        rtol=0.0,
        atol=1e-15,
    )


def test_concentration_history_separates_exposure_and_loss_contribution() -> None:
    constituents = build_constituent_return_history(_prices(), _holdings())
    classifications = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC", "DDD"],
            "sector": ["Technology", "Technology", "Finance", "Finance"],
        }
    )
    history = build_concentration_history(constituents, classifications)
    assert tuple(history.columns) == CONCENTRATION_HISTORY_COLUMNS
    first = history.iloc[0]
    assert np.isclose(first["effective_bets_abs_exposure"], 4.0)
    assert np.isclose(first["sector_hhi"], 0.5)
    assert np.isclose(first["top_sector_exposure_share"], 0.5)
    assert first["top5_abs_contribution_share"] == 1.0
    assert first["classification_status"] == "current_snapshot_proxy"
    assert bool(first["survivorship_bias"])


def test_overlap_and_rebalance_diagnostics() -> None:
    count, share = holding_overlap(["AAA", "BBB"], ["BBB", "CCC"])
    assert count == 1
    assert share == 0.5

    holdings = pd.DataFrame(
        [
            ("2024-01-31", "long", "AAA", 1),
            ("2024-01-31", "long", "BBB", 2),
            ("2024-02-29", "long", "AAA", 2),
            ("2024-02-29", "long", "CCC", 1),
            ("2024-03-29", "long", "AAA", 1),
            ("2024-03-29", "long", "CCC", 2),
            ("2024-01-31", "short", "XXX", 99),
            ("2024-01-31", "short", "YYY", 100),
            ("2024-02-29", "short", "XXX", 100),
            ("2024-02-29", "short", "ZZZ", 99),
            ("2024-03-29", "short", "XXX", 99),
            ("2024-03-29", "short", "ZZZ", 100),
        ],
        columns=["formation_date", "leg", "symbol", "price_momentum_rank"],
    )
    diagnostics = build_rebalance_diagnostics(holdings)
    current = diagnostics.loc[
        diagnostics["formation_date"].eq(pd.Timestamp("2024-03-29"))
        & diagnostics["leg"].eq("long")
    ].iloc[0]
    assert current["overlap_count"] == 2
    assert current["overlap_share"] == 1.0
    assert current["turnover_share"] == 0.0
    assert current["average_holding_rebalances"] == 2.5
