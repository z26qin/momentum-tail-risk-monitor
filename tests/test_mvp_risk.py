"""Tests for the one active DM/PIT primary risk path."""

from __future__ import annotations

import pandas as pd
import pytest

from src.risk.dm_engine import (
    build_insurance_table,
    build_primary_assessment,
    build_state_history,
)


def test_state_history_uses_bear_market_and_pit_bear_variance_mean() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=5),
            "mkt_return_504d": [0.1, -0.1, -0.2, -0.2, 0.1],
            "bear_state": [False, True, True, True, False],
            "mkt_variance_126d": [0.01, 0.02, 0.01, 0.03, 0.04],
        }
    )
    states = build_state_history(frame)

    assert states["primary_state"].tolist() == [
        "normal",
        "panic_elevated",
        "bear_low_volatility",
        "panic_elevated",
        "normal",
    ]
    assert states.loc[1, "panic_intensity"] == pytest.approx(1.0)
    assert states.loc[2, "panic_intensity"] == pytest.approx(2 / 3)
    assert pd.isna(states.loc[4, "panic_intensity"])


def test_primary_assessment_exposes_one_probability_and_matured_sample() -> None:
    state = build_primary_assessment(
        as_of_date=pd.Timestamp("2020-03-24"),
        horizon=20,
    )

    assert state.method == "dm_pit_conditional_frequency"
    assert state.state == "panic_elevated"
    assert state.elevated is True
    assert state.tail_loss_probability > state.unconditional_tail_loss_probability
    assert state.conditioning_sample_size > 1_000
    assert state.label_maturity_cutoff_date <= state.as_of_date


def test_insurance_table_separates_panic_state_for_both_horizons() -> None:
    table = build_insurance_table(as_of_date=pd.Timestamp("2026-05-29"))

    for horizon in (5, 20):
        rows = table.loc[table["horizon_days"].eq(horizon)].set_index("state")
        assert rows.loc["panic_elevated", "tail_loss_frequency"] > rows.loc[
            "all", "tail_loss_frequency"
        ]
        assert rows.loc["panic_elevated", "fifth_percentile_forward_return"] < rows.loc[
            "all", "fifth_percentile_forward_return"
        ]

