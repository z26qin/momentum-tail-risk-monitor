"""The 126-row rolling z-score must be point-in-time by construction."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.utils.pit import (
    NARRATIVE_MIN_OBSERVATIONS,
    ROLLING_WINDOW,
    rolling_z_pit,
)


def _series(seed: int = 0, size: int = 400) -> pd.Series:
    generator = np.random.default_rng(seed)
    return pd.Series(generator.normal(size=size))


def test_future_values_cannot_change_an_earlier_z_score():
    values = _series()
    target = 300
    baseline, _ = rolling_z_pit(values)

    mutated = values.copy()
    mutated.iloc[target + 1 :] += 1000.0
    after, _ = rolling_z_pit(mutated)

    assert after.iloc[target] == pytest.approx(baseline.iloc[target])
    pd.testing.assert_series_equal(
        after.iloc[: target + 1], baseline.iloc[: target + 1]
    )


def test_the_current_observation_enters_only_the_numerator():
    values = _series()
    target = 300
    baseline, _ = rolling_z_pit(values)

    mutated = values.copy()
    mutated.iloc[target] += 10.0
    after, _ = rolling_z_pit(mutated)

    # The lagged mean and standard deviation are unchanged, so the z-score must
    # move by exactly the shift divided by the unchanged standard deviation.
    lagged = values.shift(1)
    window = lagged.iloc[target - ROLLING_WINDOW + 1 : target + 1]
    standard_deviation = window.std(ddof=1)
    assert after.iloc[target] - baseline.iloc[target] == pytest.approx(
        10.0 / standard_deviation
    )


def test_a_lagged_value_may_change_the_normalisation_parameters():
    values = _series()
    target = 300
    baseline, _ = rolling_z_pit(values)

    mutated = values.copy()
    mutated.iloc[target - 1] += 50.0
    after, _ = rolling_z_pit(mutated)

    assert after.iloc[target] != pytest.approx(baseline.iloc[target])


def test_window_is_the_126_immediately_preceding_rows_with_no_backward_search():
    values = _series()
    gap = 200
    values.iloc[gap] = np.nan
    result, diagnostics = rolling_z_pit(values)

    # Every row whose 126-row lagged window contains the gap is unavailable.
    for offset in range(1, ROLLING_WINDOW + 1):
        assert np.isnan(result.iloc[gap + offset]), f"offset {offset} should be NaN"
    # The very next row after the window clears is available again: the window
    # did not search further back to make up the missing observation.
    assert np.isfinite(result.iloc[gap + ROLLING_WINDOW + 1])
    assert diagnostics.incomplete_window >= ROLLING_WINDOW


def test_infinite_values_are_treated_as_non_finite():
    values = _series()
    values.iloc[200] = np.inf
    result, _ = rolling_z_pit(values)
    assert np.isnan(result.iloc[201])


def test_first_rows_are_unavailable_until_a_full_window_exists():
    values = _series()
    result, _ = rolling_z_pit(values)
    assert result.iloc[:ROLLING_WINDOW].isna().all()
    assert np.isfinite(result.iloc[ROLLING_WINDOW])


def test_zero_standard_deviation_yields_nan_and_is_counted():
    values = pd.Series([5.0] * (ROLLING_WINDOW + 5))
    result, diagnostics = rolling_z_pit(values)
    assert result.isna().all()
    assert diagnostics.zero_standard_deviation == 5


# --------------------------------------------------------------------------
# Relaxed minimum-observations rule
#
# The narrative panel standardises against 100 finite rows out of the 126
# immediately preceding ones, because the GDELT archive has 21 gap days across
# the sample and the strict rule would destroy the series. The relaxation must
# change *availability only*: the window stays positionally the same 126 rows,
# and no missing observation is ever filled.
# --------------------------------------------------------------------------

RELAXED = NARRATIVE_MIN_OBSERVATIONS


def test_relaxed_rule_recovers_sooner_after_a_gap_than_the_strict_rule():
    values = _series()
    gap = 200
    values.iloc[gap] = np.nan

    strict, _ = rolling_z_pit(values)
    relaxed, _ = rolling_z_pit(values, min_observations=RELAXED)

    # Strict: all 126 rows after the gap are unavailable.
    assert strict.iloc[gap + 1 : gap + 1 + ROLLING_WINDOW].isna().all()
    # Relaxed: the window tolerates the single hole immediately.
    assert np.isfinite(relaxed.iloc[gap + 1])
    assert relaxed.notna().sum() > strict.notna().sum()


def test_relaxed_rule_still_performs_no_backward_search():
    """The window is positional. Only the 126 preceding rows may matter."""

    values = _series()
    target = 300
    baseline, _ = rolling_z_pit(values, min_observations=RELAXED)

    mutated = values.copy()
    # 200 rows back is far outside the 126-row window.
    mutated.iloc[target - 200] += 500.0
    after, _ = rolling_z_pit(mutated, min_observations=RELAXED)

    assert after.iloc[target] == pytest.approx(baseline.iloc[target])


def test_relaxed_rule_still_refuses_a_badly_incomplete_window():
    values = _series()
    start = 200
    # 27 holes leaves 99 finite rows in the window - one short of the minimum.
    values.iloc[start : start + 27] = np.nan
    result, _ = rolling_z_pit(values, min_observations=RELAXED)
    assert np.isnan(result.iloc[start + 27])


def test_relaxed_rule_preserves_the_three_point_in_time_invariants():
    values = _series()
    target = 300
    baseline, _ = rolling_z_pit(values, min_observations=RELAXED)

    # (1) future values cannot change an earlier z-score
    future = values.copy()
    future.iloc[target + 1 :] += 1000.0
    assert rolling_z_pit(future, min_observations=RELAXED)[0].iloc[
        target
    ] == pytest.approx(baseline.iloc[target])

    # (2) the current observation enters only the numerator
    current = values.copy()
    current.iloc[target] += 10.0
    window = values.shift(1).iloc[target - ROLLING_WINDOW + 1 : target + 1]
    shifted = rolling_z_pit(current, min_observations=RELAXED)[0].iloc[target]
    assert shifted - baseline.iloc[target] == pytest.approx(
        10.0 / window.std(ddof=1)
    )

    # (3) a lagged value may change the normalisation parameters
    lagged = values.copy()
    lagged.iloc[target - 1] += 50.0
    assert rolling_z_pit(lagged, min_observations=RELAXED)[0].iloc[
        target
    ] != pytest.approx(baseline.iloc[target])


def test_diagnostics_record_the_rule_actually_used():
    values = _series()
    _, strict = rolling_z_pit(values)
    _, relaxed = rolling_z_pit(values, min_observations=RELAXED)
    assert strict.as_dict()["min_observations"] == ROLLING_WINDOW
    assert relaxed.as_dict()["min_observations"] == RELAXED
    assert relaxed.as_dict()["window"] == ROLLING_WINDOW


@pytest.mark.parametrize("bad", [1, 0, ROLLING_WINDOW + 1])
def test_an_impossible_minimum_is_rejected(bad):
    with pytest.raises(ValueError, match="min_observations"):
        rolling_z_pit(_series(), min_observations=bad)


def test_z_score_matches_an_explicit_reference_computation():
    values = _series(seed=7)
    result, _ = rolling_z_pit(values)
    target = 250
    window = values.iloc[target - ROLLING_WINDOW : target]
    expected = (values.iloc[target] - window.mean()) / window.std(ddof=1)
    assert result.iloc[target] == pytest.approx(expected)
