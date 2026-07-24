"""Synthetic tests for purged splitting and fold-local preprocessing."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.modeling.baselines import _pipeline
from src.modeling.validation import PurgedExpandingWalkForward


def _synthetic_label_frame(horizon: int) -> pd.DataFrame:
    dates = pd.bdate_range("2000-01-03", "2020-12-31")
    label_end = pd.Series(dates).shift(-horizon)
    event = pd.Series(
        (np.arange(len(dates)) % 40) < 3,
        dtype=bool,
    )
    episode = pd.Series(
        pd.array(
            np.where(event, np.arange(len(dates)) // 40 + 1, pd.NA),
            dtype="Int64",
        )
    )
    frame = pd.DataFrame(
        {
            "date": dates,
            "label_end_date": label_end,
            "event": event,
            "event_episode_id": episode,
        }
    )
    return frame.loc[frame["label_end_date"].notna()].reset_index(drop=True)


def test_walk_forward_is_strictly_ordered_and_purged() -> None:
    horizon = 20
    frame = _synthetic_label_frame(horizon)
    splitter = PurgedExpandingWalkForward(
        initial_train_years=3,
        test_block_years=2,
        step_years=2,
    )
    splits = list(
        splitter.split(
            frame,
            model_start=pd.Timestamp("2000-01-03"),
            development_end=pd.Timestamp("2017-01-03"),
        )
    )

    assert len(splits) >= 5
    for split in splits:
        train = frame.loc[split.train_index]
        test = frame.loc[split.test_index]
        assert train["date"].max() < test["date"].min()
        assert train["label_end_date"].max() < test["date"].min()
        assert len(split.purged_index) == horizon


def test_preprocessing_statistics_are_fit_separately_by_fold() -> None:
    first_train = pd.DataFrame(
        {
            "feature_a": [0.0, 1.0, 2.0, np.nan, 4.0, 5.0],
            "feature_b": [1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
        }
    )
    second_train = first_train + 100.0
    event = pd.Series([0, 1, 0, 1, 0, 1])

    first_pipeline = _pipeline().fit(first_train, event)
    second_pipeline = _pipeline().fit(second_train, event)

    first_imputer = first_pipeline.named_steps["imputer"]
    second_imputer = second_pipeline.named_steps["imputer"]
    first_scaler = first_pipeline.named_steps["scaler"]
    second_scaler = second_pipeline.named_steps["scaler"]

    assert not np.allclose(
        first_imputer.statistics_,
        second_imputer.statistics_,
    )
    assert not np.allclose(first_scaler.mean_, second_scaler.mean_)
    np.testing.assert_allclose(
        second_scaler.mean_ - first_scaler.mean_,
        np.array([100.0, 100.0]),
    )
