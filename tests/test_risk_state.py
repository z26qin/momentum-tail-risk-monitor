"""Integration and PIT tests for the frozen-model RiskState adapter."""

from __future__ import annotations

import pandas as pd
import pytest

from src.monitoring.contracts import RiskState
from src.monitoring.risk_state import (
    PREDICTION_COLUMNS,
    build_risk_state,
    probability_history_state,
)


def test_risk_state_reconciles_saved_oos_probability() -> None:
    state = build_risk_state(
        as_of_date=pd.Timestamp("2009-03-06"),
        horizon=20,
    )

    assert state.risk_probability == pytest.approx(
        0.7917440160900019,
        abs=1e-14,
    )
    assert state.reconstructed_probability == pytest.approx(
        state.risk_probability,
        abs=1e-9,
    )
    assert state.probability_reconciliation_error <= 1e-9
    assert state.model_scope == "development"
    assert state.model_split_id == "dev_01"
    assert state.prediction_status == "saved_out_of_sample_prediction"
    assert state.earliest_action_date == "2009-03-09"
    assert state.as_of_timestamp == "2009-03-06T16:00:00-05:00"
    assert len(state.primary_market_drivers) == 5
    assert all(
        abs(left.log_odds_contribution)
        >= abs(right.log_odds_contribution)
        for left, right in zip(
            state.primary_market_drivers,
            state.primary_market_drivers[1:],
        )
    )
    assert RiskState.from_dict(state.to_dict()) == state


def test_probability_percentile_is_invariant_to_future_scores() -> None:
    dates = pd.bdate_range("2020-01-02", periods=8)
    history = pd.DataFrame(
        {
            "date": dates,
            "predicted_probability": [0.1, 0.2, 0.3, 0.4, 0.8, 0.9, 0.7, 0.6],
        }
    )
    cutoff = dates[4]
    original = probability_history_state(history, as_of_date=cutoff)
    perturbed = history.copy()
    perturbed.loc[perturbed["date"].gt(cutoff), "predicted_probability"] = [
        0.0,
        1.0,
        0.0,
    ]

    assert probability_history_state(perturbed, as_of_date=cutoff) == original
    assert original[0] == 1.0
    assert original[1] == dates[3]
    assert original[2] == pytest.approx(0.4)


def test_risk_adapter_reads_no_outcome_columns_and_rejects_gap_date() -> None:
    assert set(PREDICTION_COLUMNS).isdisjoint(
        {"event", "event_episode_id", "label_end_date"}
    )
    with pytest.raises(ValueError, match="saved OOS prediction"):
        build_risk_state(
            as_of_date=pd.Timestamp("2019-01-02"),
            horizon=20,
        )
