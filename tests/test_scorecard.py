"""Phase 4 tests for the minimal deterministic scorecard."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.monitoring.scorecard import (
    SCORECARD_COLUMNS,
    SCORECARD_METRICS,
    ScorecardConfig,
    build_scorecard,
)


def _histories(
    *,
    periods: int = 8,
    selected_beta_gap: float = 0.5,
    selected_drawdown: float = -0.2,
    selected_short_contribution: float = -0.1,
    early_recovery: bool | None = True,
    high_volatility_recovery: bool | None = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    dates = pd.bdate_range("2024-01-02", periods=periods)
    risk = pd.DataFrame(
        {
            "date": dates,
            "long_beta_126d": 1.0,
            "short_underlying_beta_126d": 1.5,
            "portfolio_beta_126d": -0.5,
            "beta_gap_short_minus_long_126d": 0.5,
            "portfolio_return": -0.2,
            "portfolio_drawdown": -0.2,
            "short_contribution": -0.1,
            "short_contribution_1d": -0.1,
            "membership_status": "current_snapshot_proxy",
            "survivorship_bias": True,
        }
    )
    risk.loc[risk.index[-1], "beta_gap_short_minus_long_126d"] = selected_beta_gap
    risk.loc[risk.index[-1], "portfolio_drawdown"] = selected_drawdown
    risk.loc[risk.index[-1], "portfolio_return"] = selected_drawdown
    risk.loc[risk.index[-1], "short_contribution"] = (
        selected_short_contribution
    )
    regime = pd.DataFrame(
        {
            "date": dates,
            "early_recovery_state": False,
            "high_volatility_recovery_state": False,
            "market_drawdown": -0.25,
            "recent_min_drawdown_126d": -0.30,
            "recovery_from_trough_126d": 0.08,
            "realized_volatility_21d": 0.50,
            "realized_volatility_threshold_80pct": 0.30,
            "high_volatility": True,
        }
    )
    regime["early_recovery_state"] = regime[
        "early_recovery_state"
    ].astype("boolean")
    regime["high_volatility_recovery_state"] = regime[
        "high_volatility_recovery_state"
    ].astype("boolean")
    regime.loc[regime.index[-1], "early_recovery_state"] = early_recovery
    regime.loc[
        regime.index[-1],
        "high_volatility_recovery_state",
    ] = high_volatility_recovery
    return risk, regime, dates[-1]


def _config(**overrides: object) -> ScorecardConfig:
    values = {
        "historical_min_observations": 4,
        "drawdown_window": 2,
        "short_loss_window": 1,
    }
    values.update(overrides)
    return ScorecardConfig(**values)


def test_scorecard_has_only_four_nonredundant_alert_rows() -> None:
    risk, regime, as_of_date = _histories()
    table = build_scorecard(
        risk,
        regime,
        as_of_date=as_of_date,
        config=_config(),
    )

    assert tuple(table.columns) == SCORECARD_COLUMNS
    assert tuple(table["metric"]) == SCORECARD_METRICS
    assert len(table) == 4
    assert "long_beta" not in table["metric"].tolist()
    assert "realized_volatility" not in table["metric"].tolist()
    assert "risk_probability" not in table.columns

    beta_context = json.loads(
        table.set_index("metric").loc[
            "short_minus_long_beta_gap",
            "context",
        ]
    )
    assert beta_context["long_beta_126d"] == pytest.approx(1.0)
    assert beta_context["short_underlying_beta_126d"] == pytest.approx(1.5)
    sources = table.set_index("metric")["source_module"]
    assert sources["portfolio_drawdown"] == (
        "src.monitoring.scorecard + src.risk.leg_decomposition"
    )
    assert sources["short_loss_in_recovery"] == (
        "src.monitoring.scorecard + src.risk.leg_decomposition + "
        "src.regime.market_state"
    )


def test_comparisons_are_inclusive_at_every_boundary() -> None:
    risk, regime, as_of_date = _histories()
    table = build_scorecard(
        risk,
        regime,
        as_of_date=as_of_date,
        config=_config(),
    ).set_index("metric")

    assert table["triggered"].astype(bool).all()
    assert table["severity"].eq("high").all()
    assert table.loc["short_minus_long_beta_gap", "threshold"] == pytest.approx(
        0.5
    )
    assert table.loc["portfolio_drawdown", "threshold"] == pytest.approx(-0.2)
    assert table.loc["short_loss_in_recovery", "threshold"] == pytest.approx(
        0.1
    )


def test_comparator_direction_and_recovery_gate() -> None:
    risk, regime, as_of_date = _histories(
        selected_beta_gap=0.49,
        selected_drawdown=-0.19,
        selected_short_contribution=-0.5,
        early_recovery=False,
        high_volatility_recovery=False,
    )
    table = build_scorecard(
        risk,
        regime,
        as_of_date=as_of_date,
        config=_config(),
    ).set_index("metric")

    assert not bool(table.loc["high_volatility_recovery", "triggered"])
    assert not bool(table.loc["short_minus_long_beta_gap", "triggered"])
    assert not bool(table.loc["portfolio_drawdown", "triggered"])
    assert not bool(table.loc["short_loss_in_recovery", "triggered"])
    assert table.loc["short_loss_in_recovery", "current_value"] == pytest.approx(
        0.5
    )


def test_missing_macro_is_unavailable_not_safe() -> None:
    risk, regime, as_of_date = _histories()
    regime = regime.loc[regime["date"].lt(as_of_date)].copy()
    table = build_scorecard(
        risk,
        regime,
        as_of_date=as_of_date,
        config=_config(),
    ).set_index("metric")

    for metric in (
        "high_volatility_recovery",
        "short_loss_in_recovery",
    ):
        assert table.loc[metric, "status"] == "unavailable"
        assert table.loc[metric, "severity"] == "unavailable"
        assert pd.isna(table.loc[metric, "triggered"])
    assert table.loc["short_minus_long_beta_gap", "status"] == "available"
    assert table.loc["portfolio_drawdown", "status"] == "available"


def test_missing_risk_metric_is_unavailable_not_false() -> None:
    risk, regime, as_of_date = _histories()
    risk.loc[
        risk["date"].eq(as_of_date),
        "beta_gap_short_minus_long_126d",
    ] = np.nan
    table = build_scorecard(
        risk,
        regime,
        as_of_date=as_of_date,
        config=_config(),
    ).set_index("metric")

    assert table.loc["short_minus_long_beta_gap", "status"] == "unavailable"
    assert pd.isna(table.loc["short_minus_long_beta_gap", "triggered"])


def test_insufficient_history_uses_labeled_demo_thresholds() -> None:
    risk, regime, as_of_date = _histories(periods=3)
    table = build_scorecard(
        risk,
        regime,
        as_of_date=as_of_date,
        config=_config(historical_min_observations=10),
    ).set_index("metric")

    assert table.loc["short_minus_long_beta_gap", "threshold"] == pytest.approx(
        0.25
    )
    assert table.loc["portfolio_drawdown", "threshold"] == pytest.approx(-0.20)
    assert table.loc["short_loss_in_recovery", "threshold"] == pytest.approx(
        0.10
    )
    assert table.loc[
        [
            "short_minus_long_beta_gap",
            "portfolio_drawdown",
            "short_loss_in_recovery",
        ],
        "threshold_provenance",
    ].eq("demo_threshold").all()


def test_beta_historical_threshold_has_zero_structural_floor() -> None:
    risk, regime, as_of_date = _histories()
    risk.loc[
        risk["date"].lt(as_of_date),
        "beta_gap_short_minus_long_126d",
    ] = -0.4
    risk.loc[
        risk["date"].eq(as_of_date),
        "beta_gap_short_minus_long_126d",
    ] = 0.0
    table = build_scorecard(
        risk,
        regime,
        as_of_date=as_of_date,
        config=_config(),
    ).set_index("metric")

    assert table.loc["short_minus_long_beta_gap", "threshold"] == 0.0
    assert (
        table.loc[
            "short_minus_long_beta_gap",
            "threshold_provenance",
        ]
        == "demo_threshold"
    )
    assert bool(table.loc["short_minus_long_beta_gap", "triggered"])
    assert "raw historical threshold=-0.4" in table.loc[
        "short_minus_long_beta_gap",
        "explanation",
    ]
    assert "structural floor=0" in table.loc[
        "short_minus_long_beta_gap",
        "explanation",
    ]


def test_drawdown_threshold_cannot_be_looser_than_20pct() -> None:
    risk, regime, as_of_date = _histories(
        selected_drawdown=-0.2,
    )
    risk.loc[risk["date"].lt(as_of_date), "portfolio_return"] = -0.5
    table = build_scorecard(
        risk,
        regime,
        as_of_date=as_of_date,
        config=_config(),
    ).set_index("metric")

    assert table.loc["portfolio_drawdown", "current_value"] == pytest.approx(
        -0.2
    )
    assert table.loc["portfolio_drawdown", "threshold"] == pytest.approx(-0.2)
    assert (
        table.loc["portfolio_drawdown", "threshold_provenance"]
        == "demo_threshold"
    )
    assert bool(table.loc["portfolio_drawdown", "triggered"])
    assert "structural floor=-0.2" in table.loc[
        "portfolio_drawdown",
        "explanation",
    ]


def test_drawdown_historical_threshold_without_override_keeps_provenance() -> None:
    risk, regime, as_of_date = _histories(selected_drawdown=-0.1)
    risk["portfolio_return"] = -0.1
    table = build_scorecard(
        risk,
        regime,
        as_of_date=as_of_date,
        config=_config(),
    ).set_index("metric")

    assert table.loc["portfolio_drawdown", "threshold"] == pytest.approx(-0.1)
    assert (
        table.loc["portfolio_drawdown", "threshold_provenance"]
        == "historical_quantile"
    )


def test_drawdown_uses_a_rolling_peak_not_since_inception_level() -> None:
    risk, regime, as_of_date = _histories(
        selected_drawdown=0.0,
    )
    risk["portfolio_return"] = 0.0
    risk["portfolio_drawdown"] = -0.9
    table = build_scorecard(
        risk,
        regime,
        as_of_date=as_of_date,
        config=_config(),
    ).set_index("metric")
    context = json.loads(table.loc["portfolio_drawdown", "context"])

    assert table.loc["portfolio_drawdown", "current_value"] == 0.0
    assert table.loc["portfolio_drawdown", "threshold"] == pytest.approx(-0.05)
    assert (
        table.loc["portfolio_drawdown", "threshold_provenance"]
        == "demo_threshold"
    )
    assert not bool(table.loc["portfolio_drawdown", "triggered"])
    assert "structural ceiling=-0.05" in table.loc[
        "portfolio_drawdown",
        "explanation",
    ]
    assert context["since_inception_portfolio_drawdown"] == pytest.approx(-0.9)
    assert context["drawdown_window_trading_days"] == 2


def test_future_changes_cannot_change_an_earlier_scorecard() -> None:
    risk, regime, _ = _histories(periods=12)
    as_of_date = risk.loc[7, "date"]
    baseline = build_scorecard(
        risk,
        regime,
        as_of_date=as_of_date,
        config=_config(),
    )

    future = risk["date"].gt(as_of_date)
    changed_risk = risk.copy()
    changed_risk.loc[future, "beta_gap_short_minus_long_126d"] = 100.0
    changed_risk.loc[future, "portfolio_return"] = -0.9
    changed_risk.loc[future, "portfolio_drawdown"] = -0.99
    changed_risk.loc[future, "short_contribution"] = -10.0
    changed_regime = regime.copy()
    changed_regime.loc[
        changed_regime["date"].gt(as_of_date),
        ["early_recovery_state", "high_volatility_recovery_state"],
    ] = True
    after = build_scorecard(
        changed_risk,
        changed_regime,
        as_of_date=as_of_date,
        config=_config(),
    )

    pd.testing.assert_frame_equal(baseline, after, check_exact=True)


def test_fixed_inputs_are_exactly_repeatable() -> None:
    risk, regime, as_of_date = _histories()
    first = build_scorecard(
        risk,
        regime,
        as_of_date=as_of_date,
        config=_config(),
    )
    second = build_scorecard(
        risk,
        regime,
        as_of_date=as_of_date,
        config=_config(),
    )

    pd.testing.assert_frame_equal(first, second, check_exact=True)


def test_duplicate_dates_fail_closed() -> None:
    risk, regime, as_of_date = _histories()
    duplicated = pd.concat([risk, risk.iloc[[-1]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate dates"):
        build_scorecard(
            duplicated,
            regime,
            as_of_date=as_of_date,
            config=_config(),
        )
