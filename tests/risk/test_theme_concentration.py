from __future__ import annotations

import numpy as np
import pandas as pd

from src.risk.concentration import effective_bets
from src.risk.theme_concentration import (
    THEME_PROXY_VERSION,
    ThemeConcentrationConfig,
    build_theme_concentration_snapshot,
    largest_correlated_cluster,
)


def _config() -> ThemeConcentrationConfig:
    return ThemeConcentrationConfig(
        correlation_window=40,
        correlation_quantile=0.60,
        correlation_floor=0.75,
        minimum_pair_observations=30,
        minimum_cluster_size=3,
        cluster_exposure_gate=0.40,
        event_window=5,
        loss_quantile=0.80,
        loss_threshold_min_observations=20,
        decline_share_gate=0.70,
        loss_contribution_gate=0.50,
        volume_quantile=0.80,
        volume_min_observations=20,
        abnormal_volume_share_gate=0.50,
    )


def _inputs(*, correlated: bool = True) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.Timestamp,
]:
    dates = pd.bdate_range("2023-09-01", periods=100)
    as_of_date = dates[-1]
    x = np.arange(len(dates), dtype="float64")
    base = 0.008 * np.sin(x / 2.7) + 0.003 * np.cos(x / 7.0)
    patterns = {
        "A": base,
        "B": base * 0.98 + 0.0002 * np.sin(x / 5.0),
        "C": base * 1.02 - 0.0002 * np.cos(x / 4.0),
        "D": 0.008 * np.sin(x / 1.3),
        "E": 0.008 * np.cos(x / 1.7),
        "F": 0.008 * np.sin(x / 4.1 + 1.2),
    }
    if not correlated:
        patterns["B"] = 0.008 * np.sin(x / 1.1 + 0.4)
        patterns["C"] = 0.008 * np.cos(x / 1.4 + 0.8)
    if correlated:
        for symbol in ("A", "B", "C"):
            patterns[symbol] = patterns[symbol].copy()
            patterns[symbol][-5:] = -0.04

    records: list[dict[str, object]] = []
    for symbol, returns in patterns.items():
        price = 100.0
        for index, (date, daily_return) in enumerate(zip(dates, returns)):
            price *= 1.0 + float(daily_return)
            volume = 1_000.0 if index < len(dates) - 5 else 10_000.0
            records.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "close_total_return_adjusted": price,
                    "volume_as_traded": volume,
                    "dollar_volume": volume * price,
                }
            )
    prices = pd.DataFrame(records)
    formation_date = dates[-15]
    prior_formation = formation_date - pd.offsets.BMonthEnd(1)
    holdings = pd.DataFrame(
        [
            {
                "formation_date": formation,
                "effective_month": as_of_date.to_period("M"),
                "symbol": symbol,
                "leg": "long",
                "weight": 1.0 / 6.0,
            }
            for formation in (prior_formation, formation_date)
            for symbol in patterns
        ]
    )
    holdings.loc[
        holdings["formation_date"].eq(prior_formation),
        "effective_month",
    ] = (as_of_date - pd.offsets.MonthEnd(1)).to_period("M")
    benchmark = pd.DataFrame(
        {"date": dates, "benchmark_return": np.zeros(len(dates))}
    )
    universe = pd.DataFrame(
        {
            "symbol": list(patterns),
            "sector": [
                "Technology",
                "Industrials",
                "Communication Services",
                "Financials",
                "Health Care",
                "Utilities",
            ],
        }
    )
    return prices, holdings, benchmark, universe, as_of_date


def test_largest_cluster_requires_all_pairwise_edges() -> None:
    correlations = pd.DataFrame(
        [
            [1.0, 0.9, 0.2, 0.1],
            [0.9, 1.0, 0.9, 0.1],
            [0.2, 0.9, 1.0, 0.1],
            [0.1, 0.1, 0.1, 1.0],
        ],
        columns=list("ABCD"),
        index=list("ABCD"),
    )
    assert largest_correlated_cluster(
        correlations,
        threshold=0.8,
        minimum_size=2,
    ) in {("A", "B"), ("B", "C")}
    assert largest_correlated_cluster(
        correlations,
        threshold=0.8,
        minimum_size=3,
    ) == ()


def test_cross_sector_correlated_theme_is_detected_and_schema_validates() -> None:
    prices, holdings, benchmark, universe, as_of_date = _inputs()
    result = build_theme_concentration_snapshot(
        prices,
        holdings,
        benchmark,
        as_of_date=as_of_date,
        universe=universe,
        config=_config(),
    )
    assert result.schema_version == THEME_PROXY_VERSION
    assert result.status == "available"
    assert set(("A", "B", "C")).issubset(result.cluster_symbols)
    assert result.cluster_exposure_share >= 0.50
    assert result.sector_count >= 3
    assert result.cluster_decline_share_5d == 1.0
    assert result.cluster_loss_contribution_share_5d >= 0.50
    assert result.trigger is True


def test_theme_proxy_changes_while_name_effective_bets_stay_constant() -> None:
    correlated = _inputs(correlated=True)
    uncorrelated = _inputs(correlated=False)
    first = build_theme_concentration_snapshot(
        correlated[0],
        correlated[1],
        correlated[2],
        as_of_date=correlated[4],
        universe=correlated[3],
        config=_config(),
    )
    second = build_theme_concentration_snapshot(
        uncorrelated[0],
        uncorrelated[1],
        uncorrelated[2],
        as_of_date=uncorrelated[4],
        universe=uncorrelated[3],
        config=_config(),
    )
    weights = correlated[1].loc[
        correlated[1]["formation_date"].eq(
            correlated[1]["formation_date"].max()
        ),
        "weight",
    ]
    assert np.isclose(effective_bets(weights), 6.0)
    assert first.cluster_exposure_share != second.cluster_exposure_share


def test_cluster_definition_excludes_as_of_and_future_returns() -> None:
    prices, holdings, benchmark, universe, as_of_date = _inputs()
    base = build_theme_concentration_snapshot(
        prices,
        holdings,
        benchmark,
        as_of_date=as_of_date,
        universe=universe,
        config=_config(),
    )
    changed = prices.copy()
    changed.loc[changed["date"].ge(as_of_date), "close_total_return_adjusted"] *= (
        changed.loc[changed["date"].ge(as_of_date), "symbol"]
        .map({"A": 10.0, "B": 0.1, "C": 5.0})
        .fillna(2.0)
        .to_numpy()
    )
    future = changed.loc[changed["date"].eq(as_of_date)].copy()
    future["date"] = as_of_date + pd.offsets.BDay(1)
    future["close_total_return_adjusted"] *= 100.0
    changed = pd.concat([changed, future], ignore_index=True)
    rerun = build_theme_concentration_snapshot(
        changed,
        holdings,
        benchmark,
        as_of_date=as_of_date,
        universe=universe,
        config=_config(),
    )
    assert base.cluster_definition_cutoff < base.as_of_date
    assert rerun.cluster_symbols == base.cluster_symbols
    assert rerun.correlation_threshold == base.correlation_threshold
    assert (
        rerun.cluster_average_residual_correlation
        == base.cluster_average_residual_correlation
    )
    assert rerun.audit_metadata["cluster_uses_as_of_return"] is False
    assert rerun.audit_metadata["future_rows_used"] is False


def test_future_rows_do_not_change_any_selected_date_output() -> None:
    prices, holdings, benchmark, universe, as_of_date = _inputs()
    base = build_theme_concentration_snapshot(
        prices,
        holdings,
        benchmark,
        as_of_date=as_of_date,
        universe=universe,
        config=_config(),
    )
    future = prices.loc[prices["date"].eq(as_of_date)].copy()
    future["date"] = as_of_date + pd.offsets.BDay(1)
    future["close_total_return_adjusted"] *= 25.0
    rerun = build_theme_concentration_snapshot(
        pd.concat([prices, future], ignore_index=True),
        holdings,
        benchmark,
        as_of_date=as_of_date,
        universe=universe,
        config=_config(),
    )
    assert rerun.to_dict() == base.to_dict()
