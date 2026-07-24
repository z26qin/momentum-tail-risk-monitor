"""Focused integrity tests for the Phase 2 GDELT ablation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.gdelt import (
    aggregate_query_to_trading_dates,
    assign_completed_buckets,
    prior_only_rolling_zscore,
)
from src.features.market_features import MODEL_FEATURES
from src.modeling.phase2 import (
    PRIMARY_TEXT_FEATURES,
    _paired_prediction_frame,
    build_common_sample,
)
from src.modeling.validation import PurgedSplit


def test_completed_bucket_mapping_weekend_holiday_and_uniqueness() -> None:
    buckets = pd.DataFrame(
        {
            "bucket_date": pd.to_datetime(
                [
                    "2024-01-02",  # ordinary Tuesday -> Wednesday
                    "2024-07-04",  # market holiday -> Friday
                    "2024-07-05",  # Friday -> Monday
                    "2024-07-06",  # Saturday -> Monday
                    "2024-07-07",  # Sunday -> Monday
                ]
            )
        }
    )
    trading_dates = pd.DatetimeIndex(
        pd.to_datetime(
            ["2024-01-02", "2024-01-03", "2024-07-03", "2024-07-05", "2024-07-08"]
        )
    )
    mapped = assign_completed_buckets(buckets, trading_dates)

    assert mapped["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2024-01-03",
        "2024-07-05",
        "2024-07-08",
        "2024-07-08",
        "2024-07-08",
    ]
    assert len(mapped) == len(buckets)
    assert mapped["bucket_date"].is_unique


def test_prior_only_normalization_excludes_current_and_future_rows() -> None:
    values = pd.Series([0.0, 1.0, 2.0, 100.0, 4.0, 5.0])
    zscore = prior_only_rolling_zscore(values, window=3)
    expected = (100.0 - np.mean([0.0, 1.0, 2.0])) / np.std(
        [0.0, 1.0, 2.0], ddof=1
    )
    assert np.isclose(zscore.iloc[3], expected)

    perturbed = values.copy()
    perturbed.iloc[4:] = [-999.0, 999.0]
    perturbed_zscore = prior_only_rolling_zscore(perturbed, window=3)
    assert np.isclose(zscore.iloc[3], perturbed_zscore.iloc[3])


def test_zero_news_is_valid_but_request_failure_is_not_zero() -> None:
    trading_dates = pd.DatetimeIndex(pd.to_datetime(["2024-01-03"]))
    zero = pd.DataFrame(
        {
            "bucket_date": pd.to_datetime(["2024-01-02"]),
            "matched_count": [0],
            "total_news_count": [1000],
            "tone": [np.nan],
            "request_status": ["ok"],
        }
    )
    aggregated = aggregate_query_to_trading_dates(zero, trading_dates)
    assert aggregated.loc[0, "volume"] == 0.0
    assert bool(aggregated.loc[0, "zero_match"])
    assert pd.isna(aggregated.loc[0, "tone"])
    assert not bool(aggregated.loc[0, "api_failure"])

    failed = zero.copy()
    failed["request_status"] = "request_failure"
    failed_result = aggregate_query_to_trading_dates(failed, trading_dates)
    assert bool(failed_result.loc[0, "api_failure"])
    assert pd.isna(failed_result.loc[0, "volume"])
    assert not bool(failed_result.loc[0, "zero_match"])


def test_b2c_and_b3_use_identical_test_dates() -> None:
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2020-01-02", periods=80)
    frame = pd.DataFrame(
        {
            "date": dates,
            "label_end_date": pd.Series(dates).shift(-5),
            "event": (np.arange(len(dates)) % 9 == 0),
            "phase2_episode_id": pd.array(
                np.where(np.arange(len(dates)) % 9 == 0, np.arange(len(dates)), pd.NA),
                dtype="Int64",
            ),
        }
    )
    for feature in MODEL_FEATURES:
        frame[feature] = rng.normal(size=len(frame))
    for feature in PRIMARY_TEXT_FEATURES:
        frame[feature] = rng.normal(size=len(frame))
    frame["narrative_breadth"] = np.arange(len(frame)) % 5
    split = PurgedSplit(
        split_id="test",
        split_kind="development",
        nominal_test_start=dates[60],
        nominal_test_end=dates[-1] + pd.Timedelta(days=1),
        train_index=frame.index[:55],
        test_index=frame.index[60:],
        purged_index=frame.index[55:60],
    )
    paired = _paired_prediction_frame(
        frame=frame,
        split=split,
        scope="development",
        horizon=5,
    )
    assert paired["date"].tolist() == dates[60:].tolist()
    assert paired["paired_test_index_verified"].all()
    assert paired["b2c_probability"].notna().all()
    assert paired["b3_probability"].notna().all()


def test_common_sample_excludes_immature_labels(tmp_path) -> None:
    dates = pd.to_datetime(["2025-06-25", "2025-06-26", "2025-06-27"])
    market = pd.DataFrame({"date": dates})
    for feature in MODEL_FEATURES:
        market[feature] = 1.0
    market.to_parquet(tmp_path / "market_features.parquet", index=False)

    text = pd.DataFrame(
        {
            "date": dates,
            "attention_max": [0.1, 0.2, 0.3],
            "narrative_breadth": pd.Series([0, 1, 2], dtype="Int64"),
            "tone_min": [-0.1, -0.2, -0.3],
            "text_history_ready": [True, True, True],
            "unresolved_api_failure": [False, False, False],
        }
    )
    text.to_parquet(tmp_path / "gdelt_text_panel.parquet", index=False)
    labels = pd.DataFrame(
        {
            "date": dates,
            "label_end_date": pd.to_datetime(
                ["2025-06-29", "2025-06-30", "2025-07-01"]
            ),
            "mom_tail_loss_5": pd.Series([False, True, False], dtype="boolean"),
        }
    )
    labels.to_parquet(tmp_path / "momentum_labels_h5.parquet", index=False)

    common = build_common_sample(
        horizon=5,
        as_of_date=pd.Timestamp("2025-06-30"),
        processed_dir=tmp_path,
    )
    assert common["date"].tolist() == dates[:2].tolist()
    assert common["label_end_date"].max() <= pd.Timestamp("2025-06-30")
