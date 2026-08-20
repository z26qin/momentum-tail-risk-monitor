"""Phase 3 tests for realized leg risk and recovery attribution."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data.sp500 import build_benchmark_frame
from src.risk.leg_decomposition import (
    build_leg_risk_history,
    build_recovery_attribution,
    load_benchmark,
)


def _portfolio(
    benchmark_returns: np.ndarray,
    *,
    long_returns: np.ndarray | None = None,
    short_returns: np.ndarray | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2020-01-02", periods=len(benchmark_returns))
    long = (
        np.asarray(long_returns)
        if long_returns is not None
        else 2.0 * benchmark_returns
    )
    short = (
        np.asarray(short_returns)
        if short_returns is not None
        else 0.5 * benchmark_returns
    )
    portfolio_return = long - short
    wealth = np.cumprod(1.0 + portfolio_return)
    drawdown = wealth / np.maximum.accumulate(wealth) - 1.0
    portfolio = pd.DataFrame(
        {
            "date": dates,
            "long_basket_return": long,
            "short_basket_underlying_return": short,
            "long_contribution": long,
            "short_contribution": -short,
            "portfolio_return": portfolio_return,
            "return_complete": True,
            "drawdown": drawdown,
            "membership_status": "current_snapshot_proxy",
            "survivorship_bias": True,
        }
    )
    benchmark = pd.DataFrame(
        {
            "date": dates,
            "benchmark_return": benchmark_returns,
            "benchmark_source": "synthetic",
            "benchmark_status": "synthetic",
        }
    )
    return portfolio, benchmark


def test_spy_benchmark_frame_uses_total_return_adjusted_close() -> None:
    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
            "symbol": "SPY",
            "close_total_return_adjusted": [100.0, 101.0, 99.99],
        }
    )
    benchmark = build_benchmark_frame(prices)

    assert pd.isna(benchmark.loc[0, "benchmark_return"])
    assert benchmark.loc[1, "benchmark_return"] == pytest.approx(0.01)
    assert benchmark.loc[2, "benchmark_return"] == pytest.approx(-0.01)
    assert benchmark["benchmark_status"].eq(
        "primary_spy_total_return_proxy"
    ).all()


def test_missing_spy_uses_explicit_broad_market_fallback(tmp_path) -> None:
    factors = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "mkt_total_return": [0.01, -0.02],
        }
    )
    factors.to_parquet(
        tmp_path / "french_research_factors_daily.parquet",
        index=False,
    )
    benchmark, status = load_benchmark(tmp_path)

    assert status == "fallback_broad_us_market_proxy"
    assert benchmark["benchmark_return"].tolist() == [0.01, -0.02]
    assert benchmark["benchmark_status"].eq(status).all()


def test_beta_decomposition_and_gap_are_exact() -> None:
    market = np.linspace(-0.02, 0.02, 160)
    portfolio, benchmark = _portfolio(market)
    history = build_leg_risk_history(portfolio, benchmark)
    row = history.iloc[-1]

    assert row["long_beta_126d"] == pytest.approx(2.0)
    assert row["short_underlying_beta_126d"] == pytest.approx(0.5)
    assert row["portfolio_beta_126d"] == pytest.approx(1.5)
    assert row["beta_gap_short_minus_long_126d"] == pytest.approx(-1.5)


def test_conditional_beta_filters_on_benchmark_sign() -> None:
    index = np.arange(160)
    market = np.where(
        index % 2 == 0,
        0.003 + index * 0.00001,
        -0.002 - index * 0.000008,
    )
    long = np.where(market > 0, 2.0 * market, 1.0 * market)
    short = np.where(market > 0, 0.5 * market, 1.5 * market)
    portfolio, benchmark = _portfolio(
        market,
        long_returns=long,
        short_returns=short,
    )
    row = build_leg_risk_history(portfolio, benchmark).iloc[-1]

    assert row["long_up_beta_126d"] == pytest.approx(2.0)
    assert row["long_down_beta_126d"] == pytest.approx(1.0)
    assert row["short_underlying_up_beta_126d"] == pytest.approx(0.5)
    assert row["short_underlying_down_beta_126d"] == pytest.approx(1.5)
    assert row["portfolio_up_beta_126d"] == pytest.approx(1.5)
    assert row["portfolio_down_beta_126d"] == pytest.approx(-0.5)


def test_future_changes_cannot_change_earlier_risk_history() -> None:
    market = np.sin(np.arange(180)) * 0.01
    portfolio, benchmark = _portfolio(market)
    cutoff = portfolio.loc[139, "date"]
    baseline = build_leg_risk_history(portfolio, benchmark)

    changed_portfolio = portfolio.copy()
    future = changed_portfolio["date"].gt(cutoff)
    changed_portfolio.loc[future, "long_basket_return"] = 0.2
    changed_portfolio.loc[future, "short_basket_underlying_return"] = -0.2
    changed_portfolio.loc[future, "long_contribution"] = 0.2
    changed_portfolio.loc[future, "short_contribution"] = 0.2
    changed_portfolio.loc[future, "portfolio_return"] = 0.4
    future_returns = changed_portfolio["portfolio_return"]
    wealth = (1.0 + future_returns).cumprod()
    changed_portfolio["drawdown"] = wealth / wealth.cummax() - 1.0
    changed_benchmark = benchmark.copy()
    changed_benchmark.loc[future, "benchmark_return"] = 0.3
    after = build_leg_risk_history(changed_portfolio, changed_benchmark)

    columns = [
        "date",
        "long_beta_126d",
        "short_underlying_beta_126d",
        "portfolio_beta_126d",
        "long_volatility_21d",
        "short_underlying_volatility_21d",
        "portfolio_volatility_21d",
        "portfolio_drawdown",
    ]
    pd.testing.assert_frame_equal(
        baseline.loc[baseline["date"].le(cutoff), columns].reset_index(drop=True),
        after.loc[after["date"].le(cutoff), columns].reset_index(drop=True),
        check_exact=True,
    )


def test_recovery_attribution_uses_signed_short_losses() -> None:
    dates = pd.bdate_range("2024-01-02", periods=5)
    frame = pd.DataFrame(
        {
            "date": dates,
            "early_recovery_state": [False, True, True, False, True],
            "high_volatility_recovery_state": [False, True, False, False, True],
            "long_contribution": [0.0, 0.02, -0.01, 0.0, 0.03],
            "short_contribution": [0.0, -0.04, 0.01, 0.0, -0.02],
            "portfolio_return": [0.0, -0.02, 0.0, 0.0, 0.01],
            "portfolio_drawdown": [0.0, -0.02, -0.02, -0.02, -0.01],
            "membership_status": "current_snapshot_proxy",
            "survivorship_bias": True,
        }
    )
    episodes = build_recovery_attribution(frame)

    assert len(episodes) == 2
    first = episodes.iloc[0]
    assert first["trading_days"] == 2
    assert first["high_volatility_recovery_days"] == 1
    assert first["long_net_contribution"] == pytest.approx(0.01)
    assert first["short_net_contribution"] == pytest.approx(-0.03)
    assert first["portfolio_net_contribution"] == pytest.approx(-0.02)
    assert first["short_loss_magnitude"] == pytest.approx(0.04)
    assert first["long_loss_magnitude"] == pytest.approx(0.01)
    assert first["short_share_of_gross_leg_losses"] == pytest.approx(0.8)
    assert first["contribution_reconciliation_error"] < 1e-12


def test_conditional_beta_is_missing_when_sign_sample_is_too_small() -> None:
    market = np.linspace(0.001, 0.02, 100)
    portfolio, benchmark = _portfolio(market)
    row = build_leg_risk_history(portfolio, benchmark).iloc[-1]

    assert pd.notna(row["long_up_beta_126d"])
    assert pd.isna(row["long_down_beta_126d"])
    assert row["down_market_observations_126d"] == 0
