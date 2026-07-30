from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

from src.monitoring.unwind_structure import (
    FINGERPRINT_HISTORY_COLUMNS,
    UNWIND_SCHEMA_VERSION,
    UNWIND_SCORECARD_METRICS,
    UnwindAssessment,
    UnwindScorecardRow,
    UnwindMonitorConfig,
    average_pairwise_correlation,
    build_constituent_unwind_history,
    build_leg_unwind_history,
    build_unwind_fingerprint_history,
    build_unwind_fingerprint_snapshot,
    classify_unwind_scenario,
    evaluate_historical_rebound,
    prior_only_quantile,
)
from src.risk.concentration import build_constituent_return_history


def _risk_history(periods: int = 20) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=periods)
    long_returns = np.linspace(-0.01, 0.01, periods)
    short_returns = np.linspace(0.008, -0.008, periods)
    return pd.DataFrame(
        {
            "date": dates,
            "formation_date": pd.Timestamp("2023-12-29"),
            "effective_month": pd.Period("2024-01"),
            "long_basket_return": long_returns,
            "short_basket_underlying_return": short_returns,
            "benchmark_return": np.linspace(-0.005, 0.005, periods),
            "long_beta_126d": np.linspace(0.8, 1.2, periods),
        }
    )


def _security_prices() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", "2024-02-15")
    patterns = {
        "L1": np.array([-0.002, -0.004, -0.001, -0.003, -0.005]),
        "L2": np.array([-0.001, -0.002, -0.0005, -0.0015, -0.0025]),
        "S1": np.array([0.002, 0.004, 0.001, 0.003, 0.005]),
        "S2": np.array([0.001, 0.002, 0.0005, 0.0015, 0.0025]),
    }
    records = []
    for symbol, pattern in patterns.items():
        price = 100.0
        for index, date in enumerate(dates):
            daily_return = float(pattern[index % len(pattern)])
            price *= 1.0 + daily_return
            volume = 100.0 if index < len(dates) - 3 else 1_000.0
            records.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "close_total_return_adjusted": price,
                    "volume_as_traded": volume,
                    "dollar_volume": volume * price,
                }
            )
    return pd.DataFrame(records)


def _holdings() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "formation_date": [pd.Timestamp("2024-01-31")] * 4,
            "effective_month": [pd.Period("2024-02")] * 4,
            "symbol": ["L1", "L2", "S1", "S2"],
            "leg": ["long", "long", "short", "short"],
            "weight": [0.5, 0.5, -0.5, -0.5],
        }
    )


def _small_config() -> UnwindMonitorConfig:
    return UnwindMonitorConfig(
        return_window=3,
        correlation_window=3,
        correlation_context_window=2,
        threshold_min_observations=3,
        volume_window=3,
        volume_history_min_observations=2,
        minimum_active_names=2,
        co_decline_gate=1.0,
        liquidity_breadth_gate=1.0,
    )


def test_residual_long_loss_uses_lagged_beta() -> None:
    risk = _risk_history(8)
    result = build_leg_unwind_history(
        risk,
        config=UnwindMonitorConfig(return_window=3),
    )
    selected = result.iloc[3]
    actual = np.prod(1.0 + risk["long_basket_return"].iloc[1:4]) - 1.0
    expected = (
        risk["long_beta_126d"].shift(1).iloc[1:4]
        * risk["benchmark_return"].iloc[1:4]
    ).sum()
    assert np.isclose(selected["long_return_5d"], actual)
    assert np.isclose(selected["beta_expected_long_return_5d"], expected)
    assert np.isclose(
        selected["residual_long_loss_5d"],
        -(actual - expected),
    )


def test_short_underlying_outperformance_has_positive_reversal_sign() -> None:
    risk = _risk_history(8)
    risk["long_basket_return"] = -0.01
    risk["short_basket_underlying_return"] = 0.02
    result = build_leg_unwind_history(
        risk,
        config=UnwindMonitorConfig(return_window=3),
    )
    selected = result.iloc[-1]
    assert selected["short_minus_long_return_5d"] > 0.0
    assert np.isclose(
        selected["short_minus_long_return_5d"],
        -selected["long_minus_short_return_5d"],
    )


def test_future_risk_rows_do_not_change_earlier_unwind_history() -> None:
    risk = _risk_history(20)
    base = build_leg_unwind_history(risk)
    cutoff = risk["date"].iloc[14]
    changed = risk.copy()
    changed.loc[changed["date"].gt(cutoff), "long_basket_return"] = 0.50
    changed.loc[changed["date"].gt(cutoff), "long_beta_126d"] = 20.0
    rerun = build_leg_unwind_history(changed)
    pdt.assert_frame_equal(
        base.loc[base["date"].le(cutoff)].reset_index(drop=True),
        rerun.loc[rerun["date"].le(cutoff)].reset_index(drop=True),
    )


def test_pairwise_correlation_edge_cases() -> None:
    assert average_pairwise_correlation(pd.DataFrame({"A": [1.0, 2.0]})) is None
    assert (
        average_pairwise_correlation(
            pd.DataFrame({"A": [1.0, 1.0], "B": [2.0, 2.0]})
        )
        is None
    )
    assert (
        average_pairwise_correlation(
            pd.DataFrame({"A": [1.0, np.nan], "B": [2.0, 3.0]})
        )
        is None
    )
    value = average_pairwise_correlation(
        pd.DataFrame({"A": [1.0, 2.0, 3.0], "B": [2.0, 4.0, 6.0]})
    )
    assert np.isclose(value, 1.0)


def test_constituent_unwind_calculates_synchronous_and_liquidity_proxies() -> None:
    prices = _security_prices()
    constituents = build_constituent_return_history(
        prices,
        _holdings(),
        exclude_incomplete_last_month=False,
    )
    result = build_constituent_unwind_history(
        constituents,
        prices,
        config=_small_config(),
    )
    selected = result.iloc[-1]
    assert selected["long_decline_share_5d"] == 1.0
    assert selected["short_rise_share_5d"] == 1.0
    assert np.isclose(
        selected["long_average_pairwise_correlation_21d"],
        1.0,
    )
    assert selected["downside_abnormal_volume_share_5d"] == 1.0
    assert selected["liquidity_eligible_long_count"] == 2
    assert selected["liquidity_proxy_status"] == "available_proxy"
    assert selected["long_median_amihud_5d"] > 0.0


def test_missing_volume_keeps_liquidity_unavailable_without_losing_declines() -> None:
    prices = _security_prices()
    constituents = build_constituent_return_history(
        prices,
        _holdings(),
        exclude_incomplete_last_month=False,
    )
    result = build_constituent_unwind_history(
        constituents,
        prices[["date", "symbol", "close_total_return_adjusted"]],
        config=_small_config(),
    )
    selected = result.iloc[-1]
    assert selected["long_decline_share_5d"] == 1.0
    assert pd.isna(selected["downside_abnormal_volume_share_5d"])
    assert selected["liquidity_proxy_status"] == "unavailable"
    assert pd.isna(selected["long_median_amihud_5d"])


def test_prior_only_threshold_excludes_current_and_future_rows() -> None:
    history = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=6),
            "metric": [1.0, 2.0, 3.0, 4.0, 100.0, 10_000.0],
        }
    )
    threshold = prior_only_quantile(
        history,
        as_of_date=pd.Timestamp("2024-01-05"),
        column="metric",
        quantile=0.80,
        min_observations=4,
    )
    assert np.isclose(threshold.value, 3.4)
    assert threshold.prior_observations == 4
    assert threshold.provenance == "historical_proxy_threshold"

    changed = history.copy()
    changed.loc[changed["date"].ge(pd.Timestamp("2024-01-05")), "metric"] = -999
    rerun = prior_only_quantile(
        changed,
        as_of_date=pd.Timestamp("2024-01-05"),
        column="metric",
        quantile=0.80,
        min_observations=4,
    )
    assert rerun == threshold


def test_threshold_floor_is_labeled_demo_and_insufficient_history_is_null() -> None:
    history = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=4),
            "metric": [-0.4, -0.3, -0.2, -0.1],
        }
    )
    floored = prior_only_quantile(
        history,
        as_of_date=pd.Timestamp("2024-01-04"),
        column="metric",
        quantile=0.80,
        min_observations=3,
        floor=0.0,
    )
    assert floored.value == 0.0
    assert floored.raw_value < 0.0
    assert floored.provenance == "demo_threshold"
    assert floored.bound_applied

    unavailable = prior_only_quantile(
        history,
        as_of_date=pd.Timestamp("2024-01-03"),
        column="metric",
        quantile=0.80,
        min_observations=3,
    )
    assert unavailable.value is None
    assert unavailable.provenance == "insufficient_history"


def test_snapshot_uses_inclusive_gates_and_proxy_warnings() -> None:
    dates = pd.date_range("2024-01-01", periods=5)
    history = pd.DataFrame(
        {
            column: [np.nan] * 5 for column in FINGERPRINT_HISTORY_COLUMNS
        }
    )
    history["date"] = dates
    history["formation_date"] = pd.Timestamp("2023-12-29")
    history["effective_month"] = pd.Period("2024-01")
    history["residual_long_loss_5d"] = [0.01, 0.02, 0.03, 0.04, 0.04]
    history["short_minus_long_return_5d"] = [
        0.01,
        0.02,
        0.03,
        0.04,
        0.04,
    ]
    history["long_decline_share_5d"] = [0.2, 0.4, 0.6, 0.8, 1.0]
    history["downside_abnormal_volume_share_5d"] = [
        0.0,
        0.2,
        0.4,
        0.6,
        1.0,
    ]
    history["liquidity_proxy_status"] = "available_proxy"
    history["classification_status"] = "current_snapshot_proxy"
    history["survivorship_bias"] = True

    snapshot = build_unwind_fingerprint_snapshot(
        history,
        as_of_date=dates[-1],
        config=_small_config(),
    )
    assert snapshot["triggers"]["synchronous_winner_liquidation"] is True
    assert snapshot["triggers"]["cross_sectional_reversal"] is True
    assert snapshot["triggers"]["liquidity_amplification_proxy"] is True
    assert snapshot["classification_status"] == "current_snapshot_proxy"
    assert any("not direct evidence" in item for item in snapshot["warnings"])


def test_combined_history_has_published_columns_and_proxy_labels() -> None:
    prices = _security_prices()
    constituents = build_constituent_return_history(
        prices,
        _holdings(),
        exclude_incomplete_last_month=False,
    )
    dates = sorted(constituents["date"].unique())
    risk = pd.DataFrame(
        {
            "date": dates,
            "formation_date": pd.Timestamp("2024-01-31"),
            "effective_month": pd.Period("2024-02"),
            "long_basket_return": -0.01,
            "short_basket_underlying_return": 0.01,
            "benchmark_return": -0.005,
            "long_beta_126d": 1.0,
        }
    )
    result = build_unwind_fingerprint_history(
        risk,
        constituents,
        prices,
        config=_small_config(),
    )
    assert tuple(result.columns) == FINGERPRINT_HISTORY_COLUMNS
    assert result["classification_status"].eq("current_snapshot_proxy").all()
    assert result["survivorship_bias"].all()

    rerun = build_unwind_fingerprint_history(
        risk,
        constituents,
        prices,
        config=_small_config(),
    )
    pdt.assert_frame_equal(result, rerun)


def _scenario_rows(
    triggered: set[str],
    *,
    unavailable: set[str] | None = None,
) -> tuple[UnwindScorecardRow, ...]:
    unavailable = unavailable or set()
    rows = []
    for metric in UNWIND_SCORECARD_METRICS:
        is_unavailable = metric in unavailable
        rows.append(
            UnwindScorecardRow(
                as_of_date="2024-01-05",
                monitor_family="test",
                metric=metric,
                current_value=None if is_unavailable else 1.0,
                threshold=None if is_unavailable else 0.5,
                threshold_provenance=(
                    "insufficient_history"
                    if is_unavailable
                    else "demo_threshold"
                ),
                direction=(
                    "rule_based"
                    if metric == "fundamental_anchor"
                    else "greater_than_or_equal"
                ),
                triggered=None if is_unavailable else metric in triggered,
                severity=(
                    "unavailable"
                    if is_unavailable
                    else "high" if metric in triggered else "normal"
                ),
                status=(
                    "insufficient_history" if is_unavailable else "available"
                ),
                explanation="test row",
                context={},
                source_module="test",
                data_quality="test",
            )
        )
    return tuple(rows)


def test_scenario_classification_rule_priority() -> None:
    mixed, _, confidence = classify_unwind_scenario(
        _scenario_rows(
            {
                "fundamental_anchor",
                "synchronous_winner_liquidation",
                "cross_sectional_reversal",
            }
        ),
        high_volatility_recovery=True,
    )
    assert mixed == "mixed_repricing_and_unwind"
    assert confidence == "high"

    crowded, _, _ = classify_unwind_scenario(
        _scenario_rows(
            {
                "portfolio_concentration",
                "momentum_breadth_deterioration",
                "synchronous_winner_liquidation",
                "cross_sectional_reversal",
            }
        ),
        high_volatility_recovery=False,
    )
    assert crowded == "crowded_momentum_unwind"

    panic, _, _ = classify_unwind_scenario(
        _scenario_rows({"cross_sectional_reversal"}),
        high_volatility_recovery=True,
    )
    assert panic == "panic_recovery_momentum_crash"

    repricing, _, _ = classify_unwind_scenario(
        _scenario_rows(
            {"fundamental_anchor", "momentum_breadth_deterioration"}
        ),
        high_volatility_recovery=False,
    )
    assert repricing == "fundamental_repricing"


def test_scenario_is_insufficient_when_core_rows_and_coverage_are_missing() -> None:
    scenario, _, confidence = classify_unwind_scenario(
        _scenario_rows(
            set(),
            unavailable={
                "synchronous_winner_liquidation",
                "cross_sectional_reversal",
                "fundamental_anchor",
            },
        ),
        high_volatility_recovery=None,
    )
    assert scenario == "insufficient_evidence"
    assert confidence == "insufficient"


def test_forward_rebound_is_historical_only_and_uses_future_rows() -> None:
    returns = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=8),
            "long_basket_return": [0.0, -0.1, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06],
            "short_basket_underlying_return": [
                0.0,
                0.1,
                -0.01,
                -0.02,
                -0.03,
                -0.04,
                -0.05,
                -0.06,
            ],
        }
    )
    result = evaluate_historical_rebound(
        returns,
        event_date=returns["date"].iloc[1],
    )
    assert [item["forward_window"] for item in result] == [1, 3, 5]
    assert all(
        item["evaluation_mode"] == "historical_post_event" for item in result
    )
    assert np.isclose(result[0]["long_return"], 0.01)
    assert result[0]["long_minus_short_return"] > 0.0


def test_live_assessment_schema_is_six_rows_and_excludes_forward_returns() -> None:
    rows = _scenario_rows({"synchronous_winner_liquidation"})
    assessment = UnwindAssessment(
        schema_version=UNWIND_SCHEMA_VERSION,
        as_of_date="2024-01-05",
        scorecard=rows,
        scenario_classification="normal_drawdown",
        scenario_rule="test rule",
        completeness_confidence="high",
        supporting_evidence=("synchronous_winner_liquidation",),
        contradictory_evidence=(),
        missing_evidence=(),
        warnings=(),
        audit_metadata={},
    )
    serialized = json.dumps(assessment.to_dict(), sort_keys=True)
    assert len(assessment.scorecard) == 6
    assert "forward" not in serialized
    assert "rebound" not in serialized

    with pytest.raises(ValueError, match="six ordered rows"):
        UnwindAssessment(
            schema_version=UNWIND_SCHEMA_VERSION,
            as_of_date="2024-01-05",
            scorecard=tuple(reversed(rows)),
            scenario_classification="normal_drawdown",
            scenario_rule="test rule",
            completeness_confidence="high",
            supporting_evidence=(),
            contradictory_evidence=(),
            missing_evidence=(),
            warnings=(),
            audit_metadata={},
        )
