"""Map GDELT UTC calendar buckets onto trading dates and build the narrative panel.

The mapping is the point-in-time heart of this panel, so it is stated exactly.

A GDELT timeline observation labelled calendar day ``D`` covers
``[D 00:00Z, D+1 00:00Z)``. That bucket only *completes* at 00:00 UTC on
``D+1``, which is roughly 19:00-20:00 US Eastern on ``D`` — after the US
close, and containing several hours of post-close publication. A day-``t``
bucket is therefore **not** available at the close of trading day ``t``.

Let ``p(t)`` be the trading day immediately preceding ``t``. The information
set at the close of ``t`` is the set of complete buckets for calendar days

    [ p(t), t - 1 day ]   inclusive

which is the previous trading day's bucket plus any intervening weekend or
holiday buckets, and never calendar day ``t`` itself.

    normal Tuesday            -> {Monday}
    normal Monday             -> {Friday, Saturday, Sunday}
    Tuesday after a Monday holiday -> {Friday, Saturday, Sunday, Monday}

Missing is never imputed. A day the GDELT archive does not cover makes its
whole interval unavailable; a day the archive covers but the query did not
match is a confirmed zero and contributes 0 to volume intensity and weight 0
to tone.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.gdelt import (
    COVERAGE_KEY,
    MECHANISM_QUERIES,
    PANEL_END,
    PANEL_START,
    TIMELINE_MODES,
    build_chunks,
    build_single_chunk,
    load_timeline_frame,
    validate_queries,
)
from src.data.trading_calendar import build_trading_calendar
from src.utils.io import DEFAULT_OUTPUT_DIR, DEFAULT_PROCESSED_DIR, DEFAULT_RAW_DIR, write_json
from src.utils.pit import (
    NARRATIVE_MIN_OBSERVATIONS,
    ROLLING_WINDOW,
    rolling_z_pit,
)


BREADTH_THRESHOLD = 1.0


# --------------------------------------------------------------------------
# Trading-date mapping
# --------------------------------------------------------------------------


def information_intervals(trading_dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Return, for each trading date, the inclusive calendar interval it may use.

    The first trading date in the index has no preceding trading day and
    therefore no interval; its bounds are NaT and every series derived from it
    is missing.
    """

    dates = pd.DatetimeIndex(trading_dates).sort_values()
    previous = dates.to_series().shift(1)
    frame = pd.DataFrame(
        {
            "trading_date": dates,
            "interval_start": pd.DatetimeIndex(previous),
            "interval_end": dates - pd.Timedelta(days=1),
        }
    ).reset_index(drop=True)
    # A trading date's own bucket is excluded by construction: interval_end is
    # strictly the previous calendar day.
    frame.loc[frame["interval_start"].isna(), "interval_end"] = pd.NaT
    return frame


def interval_days(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    """Every calendar day in an inclusive interval."""

    if pd.isna(start) or pd.isna(end):
        return []
    return list(pd.date_range(start, end, freq="D"))


# --------------------------------------------------------------------------
# Per-query daily observations
# --------------------------------------------------------------------------


@dataclass
class QueryObservations:
    """One query's daily observations plus the grid diagnostics they imply."""

    key: str
    volume: pd.Series          # utc_date -> volume intensity (share of monitored)
    tone: pd.Series            # utc_date -> average tone
    raw_count: pd.Series       # utc_date -> matching article count
    inconsistent_dates: set[pd.Timestamp]
    mode_day_counts: dict[str, int]
    modes_present: tuple[str, ...] = ()
    volume_source: str = "timelinevol"
    tone_available: bool = True

    @property
    def observed_dates(self) -> set[pd.Timestamp]:
        return set(self.volume.index)


def derive_volume_intensity(raw: pd.DataFrame) -> pd.Series:
    """Recover volume intensity from ``timelinevolraw`` as ``100 * value / norm``.

    Verified arithmetically against the API in Stage 1: for the anchor query on
    2020-01-01, 4,775 matching of 262,970 monitored = 1.8158%, exactly the
    ``timelinevol`` figure GDELT returned. So ``timelinevol`` carries no
    information that ``timelinevolraw`` does not already contain, and a query
    holding only ``timelinevolraw`` can still contribute a volume series.
    """

    if raw.empty:
        return pd.Series(dtype="float64")
    indexed = raw.set_index("utc_date")
    usable = indexed.loc[indexed["norm"] > 0]
    return 100.0 * usable["value"] / usable["norm"]


def assemble_query_observations(
    key: str,
    frames: dict[str, pd.DataFrame],
) -> QueryObservations:
    """Align whichever of a query's modes are cached onto a common date grid.

    All three modes is the intended case. A partial set is tolerated so a
    proof-of-concept can be built from an incomplete cache, but never by
    inventing data:

    * volume comes from ``timelinevol``, or is derived from ``timelinevolraw``
      when only that is present (the two are arithmetically equivalent);
    * tone requires **both** ``timelinetone`` and ``timelinevolraw``, because
      the weights are raw article counts. With either missing, tone is
      unavailable for every interval rather than weighted by the wrong units.

    Where modes disagree about a date, that date is recorded as inconsistent
    and treated as unavailable: present in one mode but not another is not a
    confirmed zero.
    """

    present = tuple(mode for mode, frame in frames.items() if not frame.empty)
    raw_frame = frames.get("timelinevolraw", pd.DataFrame())
    vol_frame = frames.get("timelinevol", pd.DataFrame())
    tone_frame = frames.get("timelinetone", pd.DataFrame())

    if not vol_frame.empty:
        volume = vol_frame.set_index("utc_date")["value"]
        volume_source = "timelinevol"
    else:
        volume = derive_volume_intensity(raw_frame)
        volume_source = "derived_from_timelinevolraw"

    tone = (
        tone_frame.set_index("utc_date")["value"]
        if not tone_frame.empty
        else pd.Series(dtype="float64")
    )
    raw_count = (
        raw_frame.set_index("utc_date")["value"]
        if not raw_frame.empty
        else pd.Series(dtype="float64")
    )
    tone_available = not tone_frame.empty and not raw_frame.empty

    vol_dates = set(volume.index)
    tone_dates = set(tone.index)
    raw_dates = set(raw_count.index)
    # Consistency is only meaningful across the modes actually held.
    held = [dates for dates in (vol_dates, tone_dates, raw_dates) if dates]
    union = set().union(*held) if held else set()
    intersection = set.intersection(*held) if held else set()
    inconsistent = union - intersection

    return QueryObservations(
        key=key,
        volume=volume,
        tone=tone,
        raw_count=raw_count,
        inconsistent_dates=inconsistent,
        mode_day_counts={
            "timelinevol": len(vol_dates),
            "timelinetone": len(tone_dates),
            "timelinevolraw": len(raw_dates),
            "intersection": len(intersection),
            "inconsistent": len(inconsistent),
        },
        modes_present=present,
        volume_source=volume_source,
        tone_available=tone_available,
    )


# --------------------------------------------------------------------------
# Aggregation over an interval
# --------------------------------------------------------------------------


def aggregate_interval(
    days: list[pd.Timestamp],
    observations: QueryObservations,
    archive_days: set[pd.Timestamp],
) -> tuple[float, float, int]:
    """Aggregate one interval into (volume intensity, tone, confirmed-zero days).

    Volume intensity is the mean across the interval's buckets. Tone is the
    **raw-article-count-weighted** mean, using ``timelinevolraw`` counts as
    weights. Volume intensity is a share of monitored volume and raw counts are
    article counts, so the two are never mixed inside one interval.
    """

    if not days:
        return float("nan"), float("nan"), 0

    volume_values: list[float] = []
    tone_values: list[float] = []
    weights: list[float] = []
    confirmed_zeros = 0

    for day in days:
        if day not in archive_days:
            # The archive does not cover this day. Nothing about the interval
            # can be asserted, and an API/archive gap must never read as zero.
            return float("nan"), float("nan"), 0
        if day in observations.inconsistent_dates:
            # Modes disagree about this day, so neither its volume nor its
            # weight is known.
            return float("nan"), float("nan"), 0

        if day in observations.volume.index:
            volume_values.append(float(observations.volume.loc[day]))
        else:
            volume_values.append(0.0)   # confirmed zero: archive covers the day
            confirmed_zeros += 1

        weight = (
            float(observations.raw_count.loc[day])
            if day in observations.raw_count.index
            else 0.0
        )
        weights.append(weight)
        tone_values.append(
            float(observations.tone.loc[day])
            if day in observations.tone.index
            else float("nan")
        )

    volume_intensity = float(np.mean(volume_values))

    if not observations.tone_available:
        # The tone series or its raw-count weights are not held at all. Tone is
        # unavailable rather than approximated with the wrong weights.
        return volume_intensity, float("nan"), confirmed_zeros

    total_weight = float(np.sum(weights))
    if total_weight <= 0:
        # Zero matching articles across the whole interval. Tone is undefined,
        # and undefined is not neutral.
        return volume_intensity, float("nan"), confirmed_zeros

    weighted_sum = 0.0
    for tone_value, weight in zip(tone_values, weights):
        if weight <= 0:
            continue
        if not np.isfinite(tone_value):
            # A required raw count exists but its tone does not; the interval's
            # tone cannot be formed without inventing a value.
            return volume_intensity, float("nan"), confirmed_zeros
        weighted_sum += tone_value * weight
    return volume_intensity, weighted_sum / total_weight, confirmed_zeros


# --------------------------------------------------------------------------
# Panel construction
# --------------------------------------------------------------------------


def load_all_observations(
    raw_dir: Path,
    chunk_mode: str = "single",
    start: pd.Timestamp = PANEL_START,
    end: pd.Timestamp = PANEL_END,
) -> tuple[dict[str, QueryObservations], set[pd.Timestamp], dict[str, Any]]:
    """Read every cached timeline and derive the archive-availability calendar."""

    chunks = (
        build_single_chunk(start, end)
        if chunk_mode == "single"
        else build_chunks(start, end)
    )

    observations: dict[str, QueryObservations] = {}
    diagnostics: dict[str, Any] = {"modes": {}, "skipped_queries": {}}

    # Build from whatever is cached. A proof-of-concept run may hold only one
    # or two mechanism queries, and a partial panel that is honest about what
    # is missing is more useful than no panel at all. A query is usable only
    # when all three of its modes are present, because tone weighting needs the
    # raw counts and a half-loaded query would silently degrade.
    def cached(query_key: str, mode: str) -> bool:
        return (raw_dir / f"{query_key}_{mode}_{chunks[0].key}.json").is_file()

    for key in MECHANISM_QUERIES:
        # A query is usable when it can yield a volume series: either
        # timelinevol directly, or timelinevolraw to derive it from.
        if not (cached(key, "timelinevol") or cached(key, "timelinevolraw")):
            diagnostics["skipped_queries"][key] = [
                mode for mode in TIMELINE_MODES if not cached(key, mode)
            ]
            continue
        frames = {
            mode: (
                load_timeline_frame(
                    query_key=key, mode=mode, raw_dir=raw_dir, chunks=chunks
                )
                if cached(key, mode)
                else pd.DataFrame()
            )
            for mode in TIMELINE_MODES
        }
        observation = assemble_query_observations(key, frames)
        observations[key] = observation
        diagnostics["modes"][key] = {
            **observation.mode_day_counts,
            "modes_present": list(observation.modes_present),
            "volume_source": observation.volume_source,
            "tone_available": observation.tone_available,
        }

    if not observations:
        raise FileNotFoundError(
            "No mechanism query has a volume series cached. Acquire at least "
            "one, for example: python -m src.data.gdelt --queries panic"
        )

    # Archive availability. The dedicated coverage series is preferred, but any
    # cached timelinevolraw carries the same `norm` field: it counts *all*
    # monitored articles that day and is query-independent. That was verified
    # directly - two entirely different queries returned byte-identical `norm`
    # on all 366 overlapping days of 2020 - so a spare volraw is a sound
    # substitute rather than a convenient guess.
    coverage_source = COVERAGE_KEY
    coverage = (
        load_timeline_frame(
            query_key=COVERAGE_KEY, mode="timelinevolraw", raw_dir=raw_dir, chunks=chunks
        )
        if cached(COVERAGE_KEY, "timelinevolraw")
        else pd.DataFrame()
    )
    if coverage.empty:
        for key in MECHANISM_QUERIES:
            if cached(key, "timelinevolraw"):
                coverage = load_timeline_frame(
                    query_key=key, mode="timelinevolraw", raw_dir=raw_dir, chunks=chunks
                )
                coverage_source = f"{key}_timelinevolraw_substitute"
                break
    if coverage.empty:
        raise FileNotFoundError(
            "No series carrying `norm` is cached, so archive availability "
            "cannot be established and an absent day cannot be told apart from "
            "a confirmed zero. Acquire any timelinevolraw series first."
        )
    diagnostics["coverage_source"] = coverage_source
    # The coverage query's `norm` is the count of *all* monitored articles that
    # day and is query-independent, so its presence is what establishes that
    # the archive covers a date at all.
    archive_days = set(coverage.loc[coverage["norm"] > 0, "utc_date"])
    diagnostics["archive_days"] = len(archive_days)
    if archive_days:
        span = pd.date_range(min(archive_days), max(archive_days), freq="D")
        missing = sorted(set(span) - archive_days)
        diagnostics["archive_missing_days"] = [
            value.date().isoformat() for value in missing
        ]
        diagnostics["archive_missing_count"] = len(missing)
    return observations, archive_days, diagnostics


def build_panel(
    *,
    raw_dir: Path = DEFAULT_RAW_DIR / "gdelt",
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    start: pd.Timestamp = PANEL_START,
    end: pd.Timestamp = PANEL_END,
    chunk_mode: str = "single",
    precision_flags: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build ``narrative_panel.parquet`` and its coverage report."""

    validate_queries()
    observations, archive_days, diagnostics = load_all_observations(
        raw_dir, chunk_mode=chunk_mode, start=start, end=end
    )

    calendar = build_trading_calendar(processed_dir=processed_dir)
    trading_dates = calendar.between(start, end)
    intervals = information_intervals(trading_dates)
    day_lists = [
        interval_days(row.interval_start, row.interval_end)
        for row in intervals.itertuples()
    ]

    panel = pd.DataFrame(
        {
            "trading_date": intervals["trading_date"],
            "information_interval_start": intervals["interval_start"],
            "information_interval_end": intervals["interval_end"],
            "information_interval_days": [len(days) for days in day_lists],
        }
    )

    z_diagnostics: dict[str, Any] = {}
    for key, observation in observations.items():
        aggregated = [
            aggregate_interval(days, observation, archive_days) for days in day_lists
        ]
        volume = pd.Series([item[0] for item in aggregated], dtype="float64")
        tone = pd.Series([item[1] for item in aggregated], dtype="float64")
        zeros = pd.Series([item[2] for item in aggregated], dtype="int64")

        panel[f"{key}_vol_intensity"] = volume.to_numpy()
        panel[f"{key}_tone"] = tone.to_numpy()
        panel[f"{key}_confirmed_zero_days"] = zeros.to_numpy()

        volume_z, volume_stats = rolling_z_pit(
            volume, ROLLING_WINDOW, min_observations=NARRATIVE_MIN_OBSERVATIONS
        )
        tone_z, tone_stats = rolling_z_pit(
            tone, ROLLING_WINDOW, min_observations=NARRATIVE_MIN_OBSERVATIONS
        )
        panel[f"{key}_vol_z"] = volume_z.to_numpy()
        panel[f"{key}_tone_z"] = tone_z.to_numpy()
        z_diagnostics[f"{key}_vol_z"] = volume_stats.as_dict()
        z_diagnostics[f"{key}_tone_z"] = tone_stats.as_dict()

    # narrative_breadth is defined over all five mechanisms. On a partial
    # proof-of-concept cache it is left entirely missing rather than computed
    # over a subset, because a count of exceedances among two queries is not a
    # smaller version of the same statistic - it is a different one.
    complete_panel = set(observations) == set(MECHANISM_QUERIES)
    if complete_panel:
        panel["narrative_breadth"] = narrative_breadth(panel, list(observations))
    else:
        panel["narrative_breadth"] = np.nan
    panel["narrative_breadth_defined"] = complete_panel
    panel["queries_available"] = ",".join(sorted(observations))
    # The availability rule travels with the numbers, so a downstream consumer
    # cannot mistake this panel's relaxed rule for the strict one.
    panel["z_window"] = ROLLING_WINDOW
    panel["z_min_observations"] = NARRATIVE_MIN_OBSERVATIONS

    flags = precision_flags or {}
    for key in observations:
        panel[f"{key}_precision_flag"] = flags.get(key, "unassessed")

    processed_dir.mkdir(parents=True, exist_ok=True)
    panel_path = processed_dir / "narrative_panel.parquet"
    panel.to_parquet(panel_path, index=False, engine="pyarrow")

    report = coverage_report(panel, list(observations))
    report["gdelt_diagnostics"] = diagnostics
    report["rolling_z_diagnostics"] = z_diagnostics
    report["trading_calendar"] = calendar.as_dict()
    report["panel_path"] = str(panel_path)
    report["rows"] = int(len(panel))
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "narrative_panel_coverage.json", report)
    return report


def narrative_breadth(panel: pd.DataFrame, keys: list[str]) -> pd.Series:
    """Count queries exceeding the breadth threshold; NaN unless all are present.

    A missing query is never treated as a non-exceedance, because "we could not
    measure this mechanism" and "this mechanism was quiet" are different
    statements and only the second one is information.
    """

    columns = [f"{key}_vol_z" for key in keys]
    values = panel[columns]
    complete = values.notna().all(axis=1)
    exceedances = (values > BREADTH_THRESHOLD).sum(axis=1).astype("float64")
    return exceedances.where(complete)


def coverage_report(panel: pd.DataFrame, keys: list[str]) -> dict[str, Any]:
    """Summarise availability per query and per year."""

    report: dict[str, Any] = {"per_query": {}, "per_year": {}}
    years = panel["trading_date"].dt.year

    for key in keys:
        volume = panel[f"{key}_vol_intensity"]
        tone = panel[f"{key}_tone"]
        report["per_query"][key] = {
            "rows": int(len(panel)),
            "vol_intensity_available": int(volume.notna().sum()),
            "tone_available": int(tone.notna().sum()),
            "vol_z_available": int(panel[f"{key}_vol_z"].notna().sum()),
            "tone_z_available": int(panel[f"{key}_tone_z"].notna().sum()),
            "confirmed_zero_day_total": int(panel[f"{key}_confirmed_zero_days"].sum()),
            "vol_intensity_min": _finite(volume.min()),
            "vol_intensity_max": _finite(volume.max()),
            "tone_min": _finite(tone.min()),
            "tone_max": _finite(tone.max()),
        }

    for year, group in panel.groupby(years):
        report["per_year"][int(year)] = {
            "trading_days": int(len(group)),
            **{
                f"{key}_vol_available": int(group[f"{key}_vol_intensity"].notna().sum())
                for key in keys
            },
            **{
                f"{key}_tone_available": int(group[f"{key}_tone"].notna().sum())
                for key in keys
            },
            "narrative_breadth_available": int(group["narrative_breadth"].notna().sum()),
        }
    return report


def _finite(value: Any) -> float | None:
    numeric = float(value)
    return numeric if np.isfinite(numeric) else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR / "gdelt")
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--chunk-mode", choices=("single", "year"), default="single")
    args = parser.parse_args()
    report = build_panel(
        raw_dir=args.raw_dir,
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
        chunk_mode=args.chunk_mode,
    )
    print(json.dumps(report, indent=2, sort_keys=True, default=str)[:4000])


if __name__ == "__main__":
    main()
