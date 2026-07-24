"""Synthetic tests for forward labels, maturity, and episode structure."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.labels import (
    build_labels_for_horizon,
    compounded_forward_return,
    decluster_events,
)


def test_forward_return_alignment_with_planted_crash() -> None:
    returns = pd.Series(
        [0.0, 0.0, 0.0, -0.40, -0.30, 0.01, 0.0],
        dtype=float,
    )

    forward = compounded_forward_return(returns, horizon=2)

    assert np.isclose(forward.iloc[2], (1.0 - 0.40) * (1.0 - 0.30) - 1.0)
    assert forward.idxmin() == 2
    assert np.isclose(forward.iloc[3], (1.0 - 0.30) * (1.0 + 0.01) - 1.0)
    assert forward.iloc[-2:].isna().all()


def test_matured_threshold_is_invariant_to_returns_after_assessment() -> None:
    dates = pd.bdate_range("2000-01-03", periods=800)
    base_returns = 0.002 * np.sin(np.arange(len(dates)) / 13.0)
    base_returns[::97] -= 0.04
    momentum = pd.DataFrame(
        {"date": dates, "umd_return": base_returns}
    )
    cutoff_position = 500
    cutoff = dates[cutoff_position]

    perturbed = momentum.copy()
    future = perturbed.index > cutoff_position
    perturbed.loc[future, "umd_return"] = np.where(
        np.arange(future.sum()) % 2 == 0,
        0.25,
        -0.25,
    )

    original_labels = build_labels_for_horizon(
        momentum,
        horizon=5,
        historical_min_matured_observations=50,
    )
    perturbed_labels = build_labels_for_horizon(
        perturbed,
        horizon=5,
        historical_min_matured_observations=50,
    )

    through_cutoff = original_labels["date"] <= cutoff
    pd.testing.assert_series_equal(
        original_labels.loc[
            through_cutoff, "pit_tail_threshold_05_5"
        ].reset_index(drop=True),
        perturbed_labels.loc[
            through_cutoff, "pit_tail_threshold_05_5"
        ].reset_index(drop=True),
        check_names=False,
        check_exact=True,
    )
    pd.testing.assert_series_equal(
        original_labels.loc[
            through_cutoff, "threshold_matured_observations_5"
        ].reset_index(drop=True),
        perturbed_labels.loc[
            through_cutoff, "threshold_matured_observations_5"
        ].reset_index(drop=True),
        check_names=False,
        check_exact=True,
    )
    assert not original_labels.loc[
        original_labels["date"] > cutoff, "fwd_mom_return_5"
    ].equals(
        perturbed_labels.loc[
            perturbed_labels["date"] > cutoff, "fwd_mom_return_5"
        ]
    )


def test_decluster_requires_five_valid_quiet_days() -> None:
    event = pd.Series(
        [
            True,
            True,
            False,
            False,
            False,
            False,
            True,
            False,
            False,
            False,
            False,
            False,
            True,
            pd.NA,
            True,
        ],
        dtype="boolean",
    )

    episode_id, onset = decluster_events(
        event,
        reset_after_non_event_days=5,
    )

    assert episode_id.iloc[0] == 1
    assert episode_id.iloc[1] == 1
    assert episode_id.iloc[6] == 1
    assert episode_id.iloc[12] == 2
    assert pd.isna(episode_id.iloc[13])
    assert episode_id.iloc[14] == 2
    assert onset.fillna(False).to_numpy().nonzero()[0].tolist() == [0, 12]
