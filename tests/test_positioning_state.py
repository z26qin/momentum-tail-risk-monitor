"""Formula, future-invariance, and integration tests for the crowding proxy."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.monitoring.contracts import PositioningState
from src.monitoring.positioning import (
    DECILE_COLUMNS,
    PROXY_NAME,
    WINDOW,
    build_dispersion_history,
    build_positioning_state,
)


def _synthetic_deciles(periods: int = 320) -> pd.DataFrame:
    dates = pd.bdate_range("2000-01-03", periods=periods)
    data: dict[str, object] = {"date": dates}
    time_index = np.arange(periods)
    for number, column in enumerate(DECILE_COLUMNS, start=1):
        data[column] = (
            number * 0.0001
            + 0.0005 * np.sin(time_index / (5.0 + number))
        )
    return pd.DataFrame(data)


def test_dispersion_formula_matches_manual_compounding() -> None:
    deciles = _synthetic_deciles()
    result = build_dispersion_history(deciles)

    assert result[PROXY_NAME].iloc[: WINDOW - 1].isna().all()
    position = WINDOW - 1
    trailing_returns = []
    for column in DECILE_COLUMNS:
        values = deciles[column].iloc[:WINDOW].to_numpy(dtype=float)
        trailing_returns.append(float(np.prod(1.0 + values) - 1.0))
    expected = float(np.std(trailing_returns, ddof=0))
    assert result[PROXY_NAME].iloc[position] == pytest.approx(expected)


def test_dispersion_is_invariant_to_future_returns() -> None:
    deciles = _synthetic_deciles()
    cutoff_position = 275
    cutoff = deciles["date"].iloc[cutoff_position]
    original = build_dispersion_history(deciles)
    perturbed = deciles.copy()
    future = perturbed["date"].gt(cutoff)
    perturbed.loc[future, DECILE_COLUMNS] = np.linspace(
        -0.2,
        0.2,
        len(DECILE_COLUMNS),
    )
    changed = build_dispersion_history(perturbed)

    pd.testing.assert_series_equal(
        original.loc[
            original["date"].le(cutoff),
            PROXY_NAME,
        ].reset_index(drop=True),
        changed.loc[
            changed["date"].le(cutoff),
            PROXY_NAME,
        ].reset_index(drop=True),
        check_exact=True,
    )


def test_real_positioning_state_is_explicitly_a_proxy() -> None:
    state = build_positioning_state(
        as_of_date=pd.Timestamp("2009-03-06"),
    )

    assert state.proxy_name == PROXY_NAME
    assert state.value >= 0.0
    assert 0.0 <= state.historical_percentile <= 1.0
    assert state.historical_observation_count >= 252
    assert state.is_observed_positioning is False
    assert PositioningState.from_dict(state.to_dict()) == state
