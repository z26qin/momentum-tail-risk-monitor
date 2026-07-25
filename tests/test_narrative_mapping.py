"""Trading-date mapping and interval aggregation for the narrative panel."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.narrative_panel import (
    BREADTH_THRESHOLD,
    QueryObservations,
    aggregate_interval,
    information_intervals,
    interval_days,
    narrative_breadth,
)


# 2024-01-11 Thu, 2024-01-12 Fri, 2024-01-15 Mon = MLK holiday (market closed),
# 2024-01-16 Tue, 2024-01-17 Wed. This gives a normal Tuesday, a normal Monday,
# and a Tuesday following a Monday holiday in one calendar.
TRADING_DATES = pd.DatetimeIndex(
    [
        "2024-01-02",  # Tue (Jan 1 holiday)
        "2024-01-03",  # Wed
        "2024-01-04",  # Thu
        "2024-01-05",  # Fri
        "2024-01-08",  # Mon
        "2024-01-09",  # Tue
        "2024-01-10",  # Wed
        "2024-01-11",  # Thu
        "2024-01-12",  # Fri
        "2024-01-16",  # Tue, after the Monday MLK holiday
        "2024-01-17",  # Wed
    ]
)


def _days_for(trading_date: str) -> list[pd.Timestamp]:
    intervals = information_intervals(TRADING_DATES)
    row = intervals.loc[intervals["trading_date"] == pd.Timestamp(trading_date)].iloc[0]
    return interval_days(row["interval_start"], row["interval_end"])


def test_normal_tuesday_uses_only_monday():
    assert _days_for("2024-01-09") == [pd.Timestamp("2024-01-08")]


def test_normal_monday_uses_friday_saturday_sunday():
    assert _days_for("2024-01-08") == [
        pd.Timestamp("2024-01-05"),
        pd.Timestamp("2024-01-06"),
        pd.Timestamp("2024-01-07"),
    ]


def test_tuesday_after_monday_holiday_uses_friday_through_monday():
    assert _days_for("2024-01-16") == [
        pd.Timestamp("2024-01-12"),
        pd.Timestamp("2024-01-13"),
        pd.Timestamp("2024-01-14"),
        pd.Timestamp("2024-01-15"),
    ]


@pytest.mark.parametrize("trading_date", [str(value.date()) for value in TRADING_DATES])
def test_day_t_bucket_is_never_in_its_own_information_set(trading_date):
    assert pd.Timestamp(trading_date) not in _days_for(trading_date)


def test_first_trading_date_has_no_interval():
    intervals = information_intervals(TRADING_DATES)
    first = intervals.iloc[0]
    assert pd.isna(first["interval_start"])
    assert pd.isna(first["interval_end"])
    assert interval_days(first["interval_start"], first["interval_end"]) == []


# --------------------------------------------------------------------------
# Interval aggregation
# --------------------------------------------------------------------------


def _observations(
    volume: dict[str, float],
    tone: dict[str, float],
    raw: dict[str, float],
    inconsistent: set[str] | None = None,
) -> QueryObservations:
    to_series = lambda mapping: pd.Series(  # noqa: E731
        {pd.Timestamp(key): value for key, value in mapping.items()}, dtype="float64"
    )
    return QueryObservations(
        key="test",
        volume=to_series(volume),
        tone=to_series(tone),
        raw_count=to_series(raw),
        inconsistent_dates={pd.Timestamp(value) for value in (inconsistent or set())},
        mode_day_counts={},
    )


DAYS = [pd.Timestamp("2024-01-05"), pd.Timestamp("2024-01-06")]
ARCHIVE = {pd.Timestamp("2024-01-05"), pd.Timestamp("2024-01-06")}


def test_tone_is_raw_count_weighted_not_intensity_weighted():
    observations = _observations(
        volume={"2024-01-05": 5.0, "2024-01-06": 1.0},
        tone={"2024-01-05": -4.0, "2024-01-06": 2.0},
        raw={"2024-01-05": 100.0, "2024-01-06": 300.0},
    )
    volume, tone, _ = aggregate_interval(DAYS, observations, ARCHIVE)
    assert volume == pytest.approx(3.0)
    # Weights are the raw article counts (100, 300), never the intensities.
    assert tone == pytest.approx((-4.0 * 100 + 2.0 * 300) / 400)
    intensity_weighted = (-4.0 * 5.0 + 2.0 * 1.0) / 6.0
    assert tone != pytest.approx(intensity_weighted)


def test_tone_is_nan_when_a_required_raw_count_is_unavailable():
    # 2024-01-06 appears in volume/tone but the modes disagree about it, so its
    # weight is unknown and the whole interval's tone must be unavailable.
    observations = _observations(
        volume={"2024-01-05": 5.0, "2024-01-06": 1.0},
        tone={"2024-01-05": -4.0, "2024-01-06": 2.0},
        raw={"2024-01-05": 100.0},
        inconsistent={"2024-01-06"},
    )
    volume, tone, _ = aggregate_interval(DAYS, observations, ARCHIVE)
    assert np.isnan(tone)
    assert np.isnan(volume)


def test_tone_is_nan_on_a_zero_match_interval_and_volume_is_zero():
    # Both days are covered by the archive but the query matched nothing.
    observations = _observations(volume={}, tone={}, raw={})
    volume, tone, zeros = aggregate_interval(DAYS, observations, ARCHIVE)
    assert volume == 0.0          # confirmed zero, not missing
    assert np.isnan(tone)         # missing is not neutral
    assert zeros == 2


def test_volume_is_nan_not_zero_when_the_archive_is_missing_a_day():
    observations = _observations(
        volume={"2024-01-05": 5.0},
        tone={"2024-01-05": -4.0},
        raw={"2024-01-05": 100.0},
    )
    partial_archive = {pd.Timestamp("2024-01-05")}
    volume, tone, _ = aggregate_interval(DAYS, observations, partial_archive)
    assert np.isnan(volume)
    assert np.isnan(tone)


def test_confirmed_zero_day_contributes_zero_volume_and_no_tone_weight():
    observations = _observations(
        volume={"2024-01-05": 4.0},
        tone={"2024-01-05": -2.0},
        raw={"2024-01-05": 50.0},
    )
    volume, tone, zeros = aggregate_interval(DAYS, observations, ARCHIVE)
    assert volume == pytest.approx(2.0)      # mean of 4.0 and a confirmed 0.0
    assert tone == pytest.approx(-2.0)       # the zero day carries weight 0
    assert zeros == 1


def test_empty_interval_is_nan():
    observations = _observations(volume={}, tone={}, raw={})
    volume, tone, _ = aggregate_interval([], observations, ARCHIVE)
    assert np.isnan(volume) and np.isnan(tone)


# --------------------------------------------------------------------------
# narrative_breadth
# --------------------------------------------------------------------------

KEYS = ["panic", "rotation", "policy", "crowding", "riskoff"]


def _breadth_frame(rows: list[list[float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {f"{key}_vol_z": [row[index] for row in rows] for index, key in enumerate(KEYS)}
    )


def test_narrative_breadth_counts_exceedances_when_all_queries_are_present():
    frame = _breadth_frame([[1.5, 2.0, 0.1, -1.0, 1.01]])
    assert narrative_breadth(frame, KEYS).iloc[0] == 3


def test_narrative_breadth_is_nan_when_any_query_is_missing():
    frame = _breadth_frame([[1.5, 2.0, np.nan, -1.0, 1.01]])
    # A missing query is not evidence that its mechanism was quiet.
    assert np.isnan(narrative_breadth(frame, KEYS).iloc[0])


def test_narrative_breadth_threshold_is_strict():
    frame = _breadth_frame([[BREADTH_THRESHOLD] * 5])
    assert narrative_breadth(frame, KEYS).iloc[0] == 0
