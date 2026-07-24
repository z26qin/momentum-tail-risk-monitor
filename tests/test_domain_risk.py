"""Historical-case and guardrail tests for transparent domain risk."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from src.monitoring.contracts import DomainRiskState
from src.monitoring.domain_risk import build_domain_risk_state
from src.monitoring.market_context import build_structured_market_context
from src.monitoring.risk_state import build_risk_state


def _component_flags(state: DomainRiskState) -> dict[str, bool]:
    return {
        component.component: component.triggered
        for component in state.components
    }


def test_2009_panic_setup_is_stressed_before_reversal_triggers() -> None:
    context = build_structured_market_context(
        as_of_date=pd.Timestamp("2009-03-06"),
    )
    legacy = build_risk_state(
        as_of_date=pd.Timestamp("2009-03-06"),
        horizon=20,
    )
    state = build_domain_risk_state(
        context=context,
        legacy_risk_state=legacy,
    )
    flags = _component_flags(state)

    assert state.state == "stressed_precondition"
    assert flags["severe_prior_market_decline"] is True
    assert flags["high_market_volatility"] is True
    assert flags["sharp_market_rebound"] is False
    assert flags["loser_snapback"] is False
    assert state.legacy_benchmark_probability == pytest.approx(
        legacy.risk_probability
    )
    assert "secondary benchmark" in state.legacy_benchmark_name
    assert DomainRiskState.from_dict(state.to_dict()) == state


def test_2009_rebound_case_activates_both_reversal_triggers() -> None:
    context = build_structured_market_context(
        as_of_date=pd.Timestamp("2009-03-23"),
    )
    state = build_domain_risk_state(context=context)
    flags = _component_flags(state)

    assert state.previous_state == "reversal_watch"
    assert state.state == "active_reversal"
    assert state.state_changed is True
    assert flags["sharp_market_rebound"] is True
    assert flags["loser_snapback"] is True
    assert flags["momentum_drawdown_confirmation"] is True


def test_2024_case_is_normal_and_confirmations_cannot_escalate_it() -> None:
    context = build_structured_market_context(
        as_of_date=pd.Timestamp("2024-01-05"),
    )
    state = build_domain_risk_state(context=context)

    assert state.state == "normal"
    assert state.previous_state == "normal"

    confirmation_only = replace(
        context,
        momentum_drawdown_252d=-0.30,
        beta_change_21d=0.20,
    )
    confirmation_state = build_domain_risk_state(
        context=confirmation_only,
    )
    flags = _component_flags(confirmation_state)

    assert flags["momentum_drawdown_confirmation"] is True
    assert flags["exposure_instability_confirmation"] is True
    assert flags["severe_prior_market_decline"] is False
    assert flags["high_market_volatility"] is False
    assert confirmation_state.state == "normal"
