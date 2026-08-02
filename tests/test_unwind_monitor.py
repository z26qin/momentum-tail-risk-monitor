"""Focused tests for the mechanical-unwind / absorption layer."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.monitoring.unwind_monitor import (
    MechanicalUnwindConfig,
    classify_unwind_state,
    compute_cross_sectional_factor_footprint,
    compute_market_absorption_proxy,
    compute_momentum_aligned_turnover,
    expanding_prior_percentile,
    build_mechanical_unwind_assessment,
)


def _prices(periods: int = 320, n_symbols: int = 40) -> pd.DataFrame:
    # ~15 months so monthly 12-1 signals can form inside the fixture.
    dates = pd.bdate_range("2022-01-03", periods=periods)
    records: list[dict[str, object]] = []
    rng = np.random.default_rng(7)
    for symbol_index in range(n_symbols):
        symbol = f"S{symbol_index:02d}"
        price = 50.0 + symbol_index
        for day_index, date in enumerate(dates):
            shock = float(rng.normal(0.0, 0.01))
            # Persistent drift creates cross-sectional momentum dispersion.
            shock += 0.0005 * (symbol_index / max(n_symbols - 1, 1) - 0.5)
            if day_index > periods - 10:
                shock += 0.002 * (symbol_index / max(n_symbols - 1, 1) - 0.5)
            price *= 1.0 + shock
            volume = 1_000.0 + 10.0 * symbol_index
            if day_index > periods - 5 and symbol_index < 5:
                volume *= 5.0
            records.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "close_total_return_adjusted": price,
                    "close_as_traded": price,
                    "volume_as_traded": volume,
                    "dollar_volume": volume * price,
                }
            )
    return pd.DataFrame(records)


def _holdings(symbols: list[str], dates: pd.DatetimeIndex) -> pd.DataFrame:
    long = symbols[:5]
    short = symbols[-5:]
    months = sorted({pd.Timestamp(date).to_period("M") for date in dates})
    rows = []
    for month in months:
        for symbol in long:
            rows.append(
                {
                    "effective_month": month,
                    "symbol": symbol,
                    "leg": "long",
                }
            )
        for symbol in short:
            rows.append(
                {
                    "effective_month": month,
                    "symbol": symbol,
                    "leg": "short",
                }
            )
    return pd.DataFrame(rows)


def _risk(dates: pd.DatetimeIndex) -> pd.DataFrame:
    returns = np.linspace(-0.01, 0.01, len(dates))
    return pd.DataFrame(
        {
            "date": dates,
            "portfolio_return": returns,
            "portfolio_volatility_21d": np.linspace(0.1, 0.4, len(dates)),
            "beta_gap_short_minus_long_126d": np.linspace(-0.2, 1.0, len(dates)),
        }
    )


def test_expanding_prior_percentile_uses_only_history() -> None:
    values = pd.Series([1.0, 2.0, 0.0, 3.0])
    ranks = expanding_prior_percentile(values)
    assert pd.isna(ranks.iloc[0])
    assert ranks.iloc[1] == pytest.approx(1.0)
    assert ranks.iloc[2] == pytest.approx(0.0)
    assert ranks.iloc[3] == pytest.approx(1.0)


def test_factor_footprint_controls_are_lagged() -> None:
    prices = _prices(periods=320, n_symbols=36)
    config = MechanicalUnwindConfig(min_cross_section=20, min_size_coverage=0.99)
    result = compute_cross_sectional_factor_footprint(prices, shares=None, config=config)
    assert not result.empty
    available = result.loc[result["control_spec"].ne("unavailable")]
    assert not available.empty
    assert available["control_spec"].isin(["mom_vol", "mom_only"]).all()
    # Future prices must not change an earlier footprint row.
    cutoff = available["date"].iloc[len(available) // 2]
    early = result.loc[result["date"].le(cutoff)].reset_index(drop=True)
    truncated_prices = prices.loc[prices["date"].le(cutoff)].copy()
    recomputed = compute_cross_sectional_factor_footprint(
        truncated_prices, shares=None, config=config
    )
    merged = early.merge(
        recomputed,
        on="date",
        suffixes=("_full", "_trunc"),
    )
    assert np.allclose(
        merged["cross_sectional_r2_full"],
        merged["cross_sectional_r2_trunc"],
        equal_nan=True,
    )


def test_turnover_uses_lagged_membership_and_avoids_div_zero() -> None:
    prices = _prices(periods=280, n_symbols=30)
    dates = pd.DatetimeIndex(sorted(prices["date"].unique()))
    # Zero median path: constant zero volume should yield NaN abnormal volume.
    prices.loc[prices["symbol"].eq("S00"), "volume_as_traded"] = 0.0
    holdings = _holdings(sorted(prices["symbol"].unique()), dates)
    result = compute_momentum_aligned_turnover(prices, holdings)
    assert {
        "long_leg_abnormal_volume",
        "short_leg_abnormal_volume",
        "extreme_momentum_abnormal_volume",
        "universe_abnormal_volume",
        "extreme_turnover_ratio",
    }.issubset(result.columns)
    assert np.isfinite(result["extreme_turnover_ratio"].dropna()).all()
    assert result["extreme_turnover_ratio"].isna().sum() < len(result)


def test_absorption_proxy_is_defined_from_lagged_extremes() -> None:
    prices = _prices(periods=280, n_symbols=30)
    dates = pd.DatetimeIndex(sorted(prices["date"].unique()))
    holdings = _holdings(sorted(prices["symbol"].unique()), dates)
    result = compute_market_absorption_proxy(prices, holdings)
    assert "short_horizon_reversal" in result
    assert "continuation_pressure" in result
    assert "liquidity_absorption_failure" in result
    valid = result.dropna(subset=["short_horizon_reversal"])
    assert not valid.empty
    assert np.allclose(
        valid["continuation_pressure"],
        -valid["short_horizon_reversal"],
    )
    flagged = result.dropna(subset=["liquidity_absorption_failure"])
    if not flagged.empty:
        assert flagged.loc[
            flagged["liquidity_absorption_failure"].astype(bool),
            "continuation_percentile",
        ].ge(0.8 - 1e-12).all()


def test_empty_cross_section_is_stable() -> None:
    prices = _prices(periods=40, n_symbols=5)
    config = MechanicalUnwindConfig(min_cross_section=30)
    result = compute_cross_sectional_factor_footprint(
        prices, shares=None, config=config
    )
    assert result["control_spec"].eq("unavailable").all()
    assert result["cross_sectional_r2"].isna().all()


def test_classify_unwind_state_is_deterministic() -> None:
    prices = _prices(periods=320, n_symbols=36)
    dates = pd.DatetimeIndex(sorted(prices["date"].unique()))
    holdings = _holdings(sorted(prices["symbol"].unique()), dates)
    risk = _risk(dates)
    config = MechanicalUnwindConfig(
        min_cross_section=20,
        elevated_percentile=0.8,
        fragility_min_signals=2,
    )
    footprint = compute_cross_sectional_factor_footprint(
        prices, shares=None, config=config
    )
    turnover = compute_momentum_aligned_turnover(prices, holdings, config=config)
    absorption = compute_market_absorption_proxy(prices, holdings, config=config)
    first = classify_unwind_state(
        footprint, turnover, absorption, risk, config=config
    )
    second = classify_unwind_state(
        footprint, turnover, absorption, risk, config=config
    )
    pd.testing.assert_frame_equal(first, second)
    assert set(first["unwind_state"]).issubset(
        {"NORMAL", "FRAGILITY_BUILDING", "ACTIVE_UNWIND", "STABILIZING_REVERSAL"}
    )


def test_size_fallback_when_shares_missing() -> None:
    prices = _prices(periods=320, n_symbols=36)
    with_size = compute_cross_sectional_factor_footprint(prices, shares=None)
    assert "mom_vol" in set(with_size["control_spec"]) or "mom_only" in set(
        with_size["control_spec"]
    )


def test_assessment_snapshot_respects_as_of() -> None:
    prices = _prices(periods=320, n_symbols=36)
    dates = pd.DatetimeIndex(sorted(prices["date"].unique()))
    symbols = sorted(prices["symbol"].unique())
    holdings = _holdings(symbols, dates)
    risk = _risk(dates)
    as_of = dates[-5]
    future = prices.copy()
    future.loc[future["date"].gt(as_of), "volume_as_traded"] *= 50.0
    config = MechanicalUnwindConfig(
        min_cross_section=20,
        history_window=120,
        signal_lookback_months=14,
    )
    baseline = build_mechanical_unwind_assessment(
        as_of_date=as_of,
        prices=prices,
        holdings=holdings,
        risk_history=risk,
        shares=None,
        config=config,
    )
    shocked = build_mechanical_unwind_assessment(
        as_of_date=as_of,
        prices=future,
        holdings=holdings,
        risk_history=risk,
        shares=None,
        config=config,
    )
    assert baseline.as_of_date == pd.Timestamp(as_of).strftime("%Y-%m-%d")
    assert baseline.unwind_state == shocked.unwind_state
    assert baseline.factor_footprint_r2 == shocked.factor_footprint_r2
    assert baseline.extreme_turnover_ratio == shocked.extreme_turnover_ratio
