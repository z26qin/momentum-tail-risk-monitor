"""Build a small point-in-time daily panel from GDELT DOC 2.0 timelines."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

from src.utils.io import (
    DEFAULT_PROCESSED_DIR,
    DEFAULT_RAW_DIR,
    REPO_ROOT,
    atomic_write_bytes,
    iso_date,
    parse_as_of_date,
    utc_now_iso,
    write_json,
    write_parquet,
)


GDELT_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "phase2_queries.yaml"
RAW_SUBDIRECTORY = "gdelt_phase2"
PANEL_FILENAME = "gdelt_text_panel.parquet"
ROLLING_WINDOW = 126
TITLE_SAMPLE_START = "20250401000000"
TITLE_SAMPLE_END = "20250501000000"
TITLE_SAMPLE_SIZE = 15
USER_AGENT = "momentum-tail-risk/0.2 public-research-prototype"
MINIMUM_REQUEST_INTERVAL_SECONDS = 6.0
_LAST_REQUEST_MONOTONIC: float | None = None


def load_phase2_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load the JSON-compatible YAML configuration without another dependency."""

    return json.loads(path.read_text(encoding="utf-8"))


def _request_url(parameters: dict[str, str | int]) -> str:
    return f"{GDELT_ENDPOINT}?{urllib.parse.urlencode(parameters)}"


def _download_json(
    *,
    parameters: dict[str, str | int],
    cache_path: Path,
    force: bool,
    retries: int = 8,
) -> dict[str, Any]:
    """Download one JSON response with conservative rate-limit backoff."""

    url = _request_url(parameters)
    metadata_path = cache_path.with_suffix(".metadata.json")
    if cache_path.exists() and metadata_path.exists() and not force:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("request_url") == url:
            return json.loads(cache_path.read_text(encoding="utf-8"))

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            global _LAST_REQUEST_MONOTONIC
            if _LAST_REQUEST_MONOTONIC is not None:
                elapsed = time.monotonic() - _LAST_REQUEST_MONOTONIC
                if elapsed < MINIMUM_REQUEST_INTERVAL_SECONDS:
                    time.sleep(MINIMUM_REQUEST_INTERVAL_SECONDS - elapsed)
            _LAST_REQUEST_MONOTONIC = time.monotonic()
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = response.read()
            parsed = json.loads(payload)
            atomic_write_bytes(cache_path, payload)
            write_json(
                metadata_path,
                {
                    "retrieval_timestamp_utc": utc_now_iso(),
                    "request_url": url,
                    "bytes": len(payload),
                    "response_kind": parameters["mode"],
                },
            )
            return parsed
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            last_error = exc
            if attempt == retries - 1:
                break
            time.sleep(min(15 * (attempt + 1), 60))
    raise RuntimeError(f"GDELT request failed after {retries} attempts: {url}") from last_error


def _timeline_data(payload: dict[str, Any]) -> list[dict[str, Any]]:
    timeline = payload.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        raise ValueError("GDELT response has no timeline series")
    data = timeline[0].get("data")
    if not isinstance(data, list):
        raise ValueError("GDELT timeline series has no data list")
    return data


def parse_timeline_volume(payload: dict[str, Any]) -> pd.DataFrame:
    """Parse raw matched counts and the corresponding monitored-news norm."""

    rows = _timeline_data(payload)
    frame = pd.DataFrame(rows)
    required = {"date", "value", "norm"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"TimelineVolRaw missing fields: {sorted(missing)}")
    result = pd.DataFrame(
        {
            "bucket_date": pd.to_datetime(frame["date"], utc=True).dt.tz_localize(None).dt.normalize(),
            "matched_count": pd.to_numeric(frame["value"], errors="raise").astype("int64"),
            "total_news_count": pd.to_numeric(frame["norm"], errors="raise").astype("int64"),
        }
    )
    if (result[["matched_count", "total_news_count"]] < 0).any().any():
        raise ValueError("GDELT volume counts cannot be negative")
    if (result["total_news_count"] == 0).any():
        raise ValueError("GDELT total-news denominator cannot be zero")
    return result


def parse_timeline_tone(payload: dict[str, Any]) -> pd.DataFrame:
    """Parse the average tone of matching articles in each calendar bucket."""

    rows = _timeline_data(payload)
    frame = pd.DataFrame(rows)
    required = {"date", "value"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"TimelineTone missing fields: {sorted(missing)}")
    return pd.DataFrame(
        {
            "bucket_date": pd.to_datetime(frame["date"], utc=True).dt.tz_localize(None).dt.normalize(),
            "tone": pd.to_numeric(frame["value"], errors="coerce"),
        }
    )


def assign_completed_buckets(
    calendar_buckets: pd.DataFrame,
    trading_dates: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Attach each completed UTC calendar bucket to the next US trading close.

    A bucket for calendar date ``d`` is treated as complete at 00:00 UTC on
    ``d+1``. The first US trading close after that instant is therefore the
    first trading date strictly later than ``d``. Friday, Saturday, and Sunday
    buckets all attach to Monday when Monday is a trading day.
    """

    if calendar_buckets["bucket_date"].duplicated().any():
        raise ValueError("Calendar buckets must be unique before mapping")
    dates = pd.DatetimeIndex(pd.to_datetime(trading_dates)).normalize().sort_values()
    if dates.has_duplicates:
        raise ValueError("Trading calendar contains duplicate dates")

    buckets = calendar_buckets.copy()
    normalized = pd.DatetimeIndex(pd.to_datetime(buckets["bucket_date"])).normalize()
    positions = dates.searchsorted(normalized, side="right")
    mapped = pd.Series(pd.NaT, index=buckets.index, dtype="datetime64[ns]")
    valid = positions < len(dates)
    mapped.loc[valid] = dates.take(positions[valid]).to_numpy()
    buckets["date"] = mapped
    return buckets


def aggregate_query_to_trading_dates(
    calendar_frame: pd.DataFrame,
    trading_dates: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Pool counts and count-weight tone after conservative bucket mapping."""

    required = {
        "bucket_date",
        "matched_count",
        "total_news_count",
        "tone",
        "request_status",
    }
    missing = required.difference(calendar_frame.columns)
    if missing:
        raise ValueError(f"Calendar frame missing fields: {sorted(missing)}")
    mapped = assign_completed_buckets(calendar_frame, trading_dates)
    mapped = mapped.loc[mapped["date"].notna()].copy()
    mapped["tone_weighted_count"] = mapped["tone"] * mapped["matched_count"]

    def aggregate(group: pd.DataFrame) -> pd.Series:
        if group["request_status"].ne("ok").any():
            return pd.Series(
                {
                    "matched_count": pd.NA,
                    "total_news_count": pd.NA,
                    "volume": np.nan,
                    "tone": np.nan,
                    "zero_match": False,
                    "api_failure": True,
                    "calendar_bucket_count": len(group),
                }
            )
        matches = int(group["matched_count"].sum())
        denominator = int(group["total_news_count"].sum())
        tone = (
            float(group["tone_weighted_count"].sum() / matches)
            if matches > 0
            else np.nan
        )
        return pd.Series(
            {
                "matched_count": matches,
                "total_news_count": denominator,
                "volume": matches / denominator,
                "tone": tone,
                "zero_match": matches == 0,
                "api_failure": False,
                "calendar_bucket_count": len(group),
            }
        )

    result = mapped.groupby("date", sort=True).apply(aggregate, include_groups=False)
    result.reset_index(inplace=True)
    result["matched_count"] = result["matched_count"].astype("Int64")
    result["total_news_count"] = result["total_news_count"].astype("Int64")
    result["zero_match"] = result["zero_match"].astype(bool)
    result["api_failure"] = result["api_failure"].astype(bool)
    result["calendar_bucket_count"] = result["calendar_bucket_count"].astype("int64")
    return result


def prior_only_rolling_zscore(
    values: pd.Series,
    *,
    window: int = ROLLING_WINDOW,
    minimum_observations: int | None = None,
) -> pd.Series:
    """Normalize a value using only the previous ``window`` rows."""

    if window <= 1:
        raise ValueError("Rolling window must exceed one observation")
    minimum = window if minimum_observations is None else minimum_observations
    if not 2 <= minimum <= window:
        raise ValueError("minimum_observations must lie in [2, window]")
    history = values.astype(float).shift(1)
    rolling = history.rolling(window, min_periods=minimum)
    mean = rolling.mean()
    standard_deviation = rolling.std(ddof=1)
    result = (values.astype(float) - mean) / standard_deviation
    return result.where(standard_deviation > 0)


def _calendar_query_frame(
    *,
    volume_payload: dict[str, Any],
    tone_payload: dict[str, Any],
    shared_denominator: pd.DataFrame,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    volume = parse_timeline_volume(volume_payload)
    tone = parse_timeline_tone(tone_payload)
    expected = pd.DataFrame(
        {"bucket_date": pd.date_range(start_date, end_date, freq="D")}
    )
    frame = expected.merge(volume, on="bucket_date", how="left", validate="one_to_one")
    frame = frame.merge(tone, on="bucket_date", how="left", validate="one_to_one")
    frame = frame.merge(
        shared_denominator,
        on="bucket_date",
        how="left",
        validate="one_to_one",
        suffixes=("", "_shared"),
    )
    omitted_by_timeline = frame["matched_count"].isna()
    frame.loc[omitted_by_timeline, "matched_count"] = 0
    frame["total_news_count"] = frame["total_news_count"].fillna(
        frame["total_news_count_shared"]
    )
    unresolved_gap = frame["total_news_count"].isna()
    inconsistent = (
        frame["total_news_count_shared"].notna()
        & frame["total_news_count"].ne(frame["total_news_count_shared"])
    )
    if inconsistent.any():
        raise ValueError("GDELT total-news denominators disagree across queries")
    frame.drop(columns=["total_news_count_shared"], inplace=True)
    frame["matched_count"] = frame["matched_count"].astype("Int64")
    frame["total_news_count"] = frame["total_news_count"].astype("Int64")
    frame.loc[frame["matched_count"].eq(0), "tone"] = np.nan
    missing_tone_with_articles = frame["matched_count"].gt(0) & frame["tone"].isna()
    if missing_tone_with_articles.any():
        examples = (
            frame.loc[missing_tone_with_articles, "bucket_date"].head().dt.date.tolist()
        )
        raise ValueError(f"GDELT tone response omitted nonzero buckets: {examples}")
    frame["request_status"] = "ok"
    frame.loc[unresolved_gap, "request_status"] = "gdelt_data_gap"
    return frame


def _query_parameters(
    query: str,
    *,
    mode: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> dict[str, str | int]:
    exclusive_end = end_date + pd.Timedelta(days=1)
    return {
        "query": query,
        "mode": mode,
        "format": "json",
        "startdatetime": start_date.strftime("%Y%m%d000000"),
        "enddatetime": exclusive_end.strftime("%Y%m%d000000"),
    }


def fetch_title_samples(
    *,
    config: dict[str, Any],
    raw_dir: Path,
    force: bool,
) -> dict[str, list[str]]:
    """Cache a small label-blind title sample for semantic query review."""

    samples: dict[str, list[str]] = {}
    for query_name, query_spec in config["queries"].items():
        parameters: dict[str, str | int] = {
            "query": query_spec["query"],
            "mode": "artlist",
            "format": "json",
            "maxrecords": TITLE_SAMPLE_SIZE,
            "sort": "hybridrel",
            "startdatetime": TITLE_SAMPLE_START,
            "enddatetime": TITLE_SAMPLE_END,
        }
        payload = _download_json(
            parameters=parameters,
            cache_path=raw_dir / f"{query_name.lower()}_titles.json",
            force=force,
        )
        articles = payload.get("articles", [])
        samples[query_name] = [
            str(article.get("title", "")).strip()
            for article in articles
            if str(article.get("title", "")).strip()
        ]
    return samples


def build_gdelt_text_panel(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    raw_dir: Path = DEFAULT_RAW_DIR / RAW_SUBDIRECTORY,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    force: bool = False,
    fetch_samples: bool = True,
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Fetch, map, normalize, and serialize the compact daily text panel."""

    config = load_phase2_config(config_path)
    start_date = pd.Timestamp(config["source_start_date"])
    as_of_date = pd.Timestamp(config["as_of_date"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    trading_dates = pd.DatetimeIndex(
        pd.read_parquet(processed_dir / "market_features.parquet", columns=["date"])[
            "date"
        ]
    )
    trading_dates = trading_dates[
        (trading_dates >= start_date) & (trading_dates <= as_of_date)
    ]
    if len(trading_dates) == 0:
        raise ValueError("Market-feature trading calendar does not overlap Phase 2")
    if trading_dates.max() < as_of_date:
        # The public French files can lag the research as-of date. Extend only
        # the standalone text calendar; model rows still require market data.
        # For the 2026 extension this removes Juneteenth from weekdays.
        extension = pd.date_range(
            trading_dates.max() + pd.Timedelta(days=1),
            as_of_date,
            freq=CustomBusinessDay(calendar=USFederalHolidayCalendar()),
        )
        trading_dates = trading_dates.append(extension).drop_duplicates().sort_values()

    title_samples = (
        fetch_title_samples(config=config, raw_dir=raw_dir, force=force)
        if fetch_samples
        else {}
    )
    panel = pd.DataFrame({"date": trading_dates})
    payloads: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}

    for query_name, query_spec in config["queries"].items():
        stem = query_name.lower()
        query = str(query_spec["query"])
        volume_payload = _download_json(
            parameters=_query_parameters(
                query,
                mode="timelinevolraw",
                start_date=start_date,
                end_date=as_of_date,
            ),
            cache_path=raw_dir / f"{stem}_volume.json",
            force=force,
        )
        tone_payload = _download_json(
            parameters=_query_parameters(
                query,
                mode="timelinetone",
                start_date=start_date,
                end_date=as_of_date,
            ),
            cache_path=raw_dir / f"{stem}_tone.json",
            force=force,
        )
        payloads[query_name] = (volume_payload, tone_payload)

    denominator_parts = []
    for volume_payload, _ in payloads.values():
        parsed_volume = parse_timeline_volume(volume_payload)
        denominator_parts.append(
            parsed_volume.loc[:, ["bucket_date", "total_news_count"]]
        )
    denominator_observations = pd.concat(denominator_parts, ignore_index=True)
    disagreement = denominator_observations.groupby("bucket_date")[
        "total_news_count"
    ].nunique()
    if disagreement.gt(1).any():
        raise ValueError("GDELT total-news denominator is inconsistent across queries")
    shared_denominator = (
        denominator_observations.drop_duplicates("bucket_date")
        .sort_values("bucket_date")
        .reset_index(drop=True)
    )

    for query_name in config["queries"]:
        stem = query_name.lower()
        volume_payload, tone_payload = payloads[query_name]
        calendar = _calendar_query_frame(
            volume_payload=volume_payload,
            tone_payload=tone_payload,
            shared_denominator=shared_denominator,
            start_date=start_date,
            end_date=as_of_date,
        )
        daily = aggregate_query_to_trading_dates(calendar, trading_dates)
        rename = {
            column: f"{stem}_{column}"
            for column in daily.columns
            if column != "date"
        }
        daily.rename(columns=rename, inplace=True)
        panel = panel.merge(daily, on="date", how="left", validate="one_to_one")

        panel[f"{stem}_vol_z"] = prior_only_rolling_zscore(
            panel[f"{stem}_volume"],
            window=ROLLING_WINDOW,
            minimum_observations=101,
        )
        panel.loc[panel.index < ROLLING_WINDOW, f"{stem}_vol_z"] = np.nan
        panel[f"{stem}_tone_z"] = prior_only_rolling_zscore(
            panel[f"{stem}_tone"],
            window=ROLLING_WINDOW,
            minimum_observations=20,
        )
        # A full 126-row calendar must exist even when a rare zero-match day
        # makes the tone history contain fewer than 126 observed values.
        panel.loc[panel.index < ROLLING_WINDOW, f"{stem}_tone_z"] = np.nan

    volume_z = [f"{name.lower()}_vol_z" for name in config["queries"]]
    tone_z = [f"{name.lower()}_tone_z" for name in config["queries"]]
    panel["attention_max"] = panel[volume_z].max(axis=1, skipna=False)
    panel["narrative_breadth"] = panel[volume_z].gt(1.0).sum(axis=1).astype("int64")
    panel.loc[panel[volume_z].isna().any(axis=1), "narrative_breadth"] = pd.NA
    panel["narrative_breadth"] = panel["narrative_breadth"].astype("Int64")
    panel["tone_min"] = panel[tone_z].min(axis=1, skipna=True)
    panel["text_history_ready"] = panel[volume_z].notna().all(axis=1)
    panel["unresolved_api_failure"] = panel[
        [f"{name.lower()}_api_failure" for name in config["queries"]]
    ].any(axis=1)

    output_path = processed_dir / PANEL_FILENAME
    write_parquet(panel, output_path)
    return panel, title_samples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-title-samples", action="store_true")
    arguments = parser.parse_args()
    requested_as_of = parse_as_of_date(arguments.as_of_date)
    config = load_phase2_config(arguments.config)
    if requested_as_of != pd.Timestamp(config["as_of_date"]):
        raise ValueError(
            f"CLI as-of date {iso_date(requested_as_of)} differs from frozen config "
            f"{config['as_of_date']}"
        )
    panel, samples = build_gdelt_text_panel(
        config_path=arguments.config,
        force=arguments.force,
        fetch_samples=not arguments.skip_title_samples,
    )
    print(
        json.dumps(
            {
                "rows": len(panel),
                "first_date": iso_date(panel["date"].min()),
                "last_date": iso_date(panel["date"].max()),
                "text_history_ready_rows": int(panel["text_history_ready"].sum()),
                "title_sample_counts": {
                    name: len(titles) for name, titles in samples.items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
