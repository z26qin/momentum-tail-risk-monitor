"""GDELT DOC 2.0 timeline acquisition for the narrative overlay.

What this panel measures, stated once so it is not overclaimed downstream:
**English-language global monitored-news attention to financial-market stress
narratives.** It is not a measure of US financial journalism specifically, and
it is not investor sentiment. GDELT's monitored set is a worldwide crawl, and
`sourcelang:english` selects language, not country.

Query design rules, all of which are enforced by :func:`validate_queries`:

1. Every mechanism term group is ANDed with an equity/market anchor group.
   A bare mechanism word such as ``plunge`` matches aviation and weather
   reporting, so it is never used alone.
2. ``sourcelang:english`` on every query.
3. **Hindsight rule.** Mechanism-level language only: no episode-specific
   tokens, no tickers, no company names, no dated references. This is the one
   constraint that is never relaxed, because an episode-specific token would
   let the panel "know" about an event it should only be able to sense
   generically.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

import pandas as pd

from src.utils.http import cached_fetch
from src.utils.io import DEFAULT_RAW_DIR, write_json


GDELT_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"

#: GDELT rate-limits aggressively; the probe saw HTTP 429 on roughly every
#: second request at 5-6 second spacing.
MIN_REQUEST_INTERVAL_SECONDS = 12.0

TIMELINE_MODES = ("timelinevol", "timelinetone", "timelinevolraw")

PANEL_START = pd.Timestamp("2017-01-01")
PANEL_END = pd.Timestamp("2026-06-30")

# --------------------------------------------------------------------------
# Frozen queries
# --------------------------------------------------------------------------

#: Mandatory equity/market anchor. Every mechanism group is ANDed with this.
MARKET_ANCHOR = '(stock OR stocks OR equity OR equities OR "stock market" OR "financial markets")'

LANGUAGE_FILTER = "sourcelang:english"

# Mechanism: broad equity-market stress. Proxies the "panic state" that
# Daniel-Moskowitz place at the centre of momentum crash risk.
Q_PANIC = (
    '(selloff OR "sell-off" OR plunge OR rout OR turmoil OR panic OR slump) '
    f"{MARKET_ANCHOR} {LANGUAGE_FILTER}"
)

# Mechanism: factor/style rotation and momentum unwind - the narrative
# signature of the crash mechanism itself rather than of market direction.
Q_ROTATION = (
    '("factor rotation" OR "momentum stocks" OR "growth stocks" OR '
    '"value stocks" OR unwind) '
    f"{MARKET_ANCHOR} {LANGUAGE_FILTER}"
)

# Mechanism: central-bank surprise and rate-path repricing, a recurring
# trigger for abrupt cross-sectional reversals.
Q_POLICY = (
    '("central bank" OR "monetary policy" OR "interest rates" OR '
    '"rate hike" OR "rate cut") '
    f"{MARKET_ANCHOR} {LANGUAGE_FILTER}"
)

# Mechanism: crowded-trade deleveraging and short-leg squeeze. This is the
# narrative counterpart of the structured positioning panel.
Q_CROWDING = (
    '("short squeeze" OR "short sellers" OR "crowded trade" OR '
    'deleveraging OR "margin call") '
    f"{MARKET_ANCHOR} {LANGUAGE_FILTER}"
)

# Mechanism: flight to safety. Rises when investors reallocate away from risk
# assets, which precedes the bear state in the adopted risk definition.
Q_RISKOFF = (
    '("risk-off" OR "flight to safety" OR "safe haven" OR "safe-haven") '
    f"{MARKET_ANCHOR} {LANGUAGE_FILTER}"
)

#: Not a mechanism series. The bare anchor is pulled in ``timelinevolraw`` so
#: that its ``norm`` field establishes which UTC calendar days the GDELT
#: archive actually covers. Without it, a day absent from a mechanism query is
#: ambiguous between "zero matching articles" and "archive gap", and the spec
#: forbids reporting an archive gap as a zero.
Q_COVERAGE = f"{MARKET_ANCHOR} {LANGUAGE_FILTER}"

MECHANISM_QUERIES: dict[str, str] = {
    "panic": Q_PANIC,
    "rotation": Q_ROTATION,
    "policy": Q_POLICY,
    "crowding": Q_CROWDING,
    "riskoff": Q_RISKOFF,
}

COVERAGE_KEY = "coverage"
ALL_QUERIES: dict[str, str] = {**MECHANISM_QUERIES, COVERAGE_KEY: Q_COVERAGE}

#: Tokens that would breach the hindsight rule. Deliberately includes the
#: obvious episode vocabulary of the sample period.
FORBIDDEN_TOKENS = (
    "covid", "coronavirus", "pandemic", "vaccine", "lockdown",
    "gamestop", "gme", "amc", "robinhood", "meme",
    "tariff", "trump", "biden", "brexit", "ukraine", "russia",
    "svb", "silicon valley bank", "credit suisse", "lehman",
    "taper tantrum", "yen carry", "deepseek", "nvidia", "tesla",
    "2018", "2020", "2021", "2022", "2023", "2024", "2025", "2026",
)


#: GDELT rejects over-long queries with an HTTP 200 body reading "Your query
#: was too short or too long." Measured against the live API: 202 characters is
#: accepted, 261 is rejected. Every frozen query is held below this ceiling.
MAX_QUERY_CHARACTERS = 220


class QueryConstraintError(ValueError):
    """Raised when a frozen query breaches a query-design constraint."""


def validate_queries(queries: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Assert the anchor, language, and hindsight constraints on every query."""

    queries = ALL_QUERIES if queries is None else queries
    report: dict[str, dict[str, Any]] = {}
    for key, query in queries.items():
        lowered = query.lower()
        if MARKET_ANCHOR not in query:
            raise QueryConstraintError(f"{key}: missing mandatory market anchor group")
        if LANGUAGE_FILTER not in query:
            raise QueryConstraintError(f"{key}: missing {LANGUAGE_FILTER}")
        hits = [token for token in FORBIDDEN_TOKENS if token in lowered]
        if hits:
            raise QueryConstraintError(
                f"{key}: breaches the hindsight rule with episode-specific tokens {hits}"
            )
        if re.search(r"\$[A-Z]{1,5}\b", query):
            raise QueryConstraintError(f"{key}: contains a ticker symbol")
        if len(query) > MAX_QUERY_CHARACTERS:
            raise QueryConstraintError(
                f"{key}: {len(query)} characters exceeds the observed GDELT "
                f"ceiling of {MAX_QUERY_CHARACTERS}; the API would answer HTTP "
                "200 with a plain-text rejection"
            )
        report[key] = {
            "query": query,
            "characters": len(query),
            "has_market_anchor": True,
            "has_language_filter": True,
            "forbidden_tokens_found": [],
        }
    return report


# --------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    """One request window. Chunk bounds are inclusive of both labelled buckets."""

    key: str
    start: pd.Timestamp
    end: pd.Timestamp

    @property
    def start_stamp(self) -> str:
        return self.start.strftime("%Y%m%d000000")

    @property
    def end_stamp(self) -> str:
        return self.end.strftime("%Y%m%d000000")


def build_single_chunk(
    start: pd.Timestamp = PANEL_START,
    end: pd.Timestamp = PANEL_END,
) -> list[Chunk]:
    """One request spanning the whole range.

    Preferred when GDELT honours it at daily resolution, because it removes
    chunk seams entirely and cuts request volume roughly tenfold against a
    hard-rate-limited API. Validated, never assumed: the caller must confirm
    ``date_resolution == "day"`` before accepting the result.
    """

    return [Chunk(key="full", start=start, end=end)]


def build_chunks(
    start: pd.Timestamp = PANEL_START,
    end: pd.Timestamp = PANEL_END,
) -> list[Chunk]:
    """Split the range into calendar-year chunks with no gap and no overlap.

    The probe established that ``enddatetime`` is inclusive of the bucket it
    labels: a request for 2019-12-20..2019-12-31 returned exactly 12 daily
    buckets ending on 2019-12-31. Year chunks therefore end on 31 December and
    the next chunk starts on 1 January.
    """

    chunks: list[Chunk] = []
    for year in range(start.year, end.year + 1):
        chunk_start = max(start, pd.Timestamp(year=year, month=1, day=1))
        chunk_end = min(end, pd.Timestamp(year=year, month=12, day=31))
        if chunk_start > chunk_end:
            continue
        chunks.append(Chunk(key=str(year), start=chunk_start, end=chunk_end))
    assert_chunks_tile(chunks, start, end)
    return chunks


def assert_chunks_tile(
    chunks: list[Chunk],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> None:
    """Fail loudly if the chunk seams would drop or duplicate a calendar day."""

    if not chunks:
        raise ValueError("No chunks produced")
    if chunks[0].start != start or chunks[-1].end != end:
        raise ValueError("Chunks do not span the requested range")
    for earlier, later in zip(chunks, chunks[1:]):
        gap = (later.start - earlier.end).days
        if gap != 1:
            raise ValueError(
                f"Chunk seam {earlier.key}->{later.key} leaves a gap/overlap of "
                f"{gap - 1} calendar days"
            )


# --------------------------------------------------------------------------
# Acquisition
# --------------------------------------------------------------------------


def is_json_payload(payload: bytes) -> bool:
    """GDELT answers throttled requests with a plain-text notice and HTTP 200.

    Treating that as a valid response caches a permanent poison pill, so every
    timeline response must parse as JSON before it is allowed into the cache.
    """

    try:
        json.loads(payload.decode("utf-8", errors="strict"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return True


def timeline_url(query: str, mode: str, chunk: Chunk) -> str:
    """Build one fully-specified timeline request URL."""

    params = {
        "query": query,
        "mode": mode,
        "format": "json",
        "startdatetime": chunk.start_stamp,
        "enddatetime": chunk.end_stamp,
        "timelinesmooth": "0",
    }
    return f"{GDELT_ENDPOINT}?{urlencode(params)}"


def fetch_timeline(
    *,
    query_key: str,
    query: str,
    mode: str,
    chunk: Chunk,
    raw_dir: Path,
    force: bool = False,
    min_interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
    max_retries: int = 5,
    backoff_seconds: float = 15.0,
    tolerate_failure: bool = False,
) -> dict[str, Any]:
    """Retrieve and cache one (query, mode, chunk) timeline response."""

    cache_path = raw_dir / f"{query_key}_{mode}_{chunk.key}.json"
    result = cached_fetch(
        cache_path=cache_path,
        url=timeline_url(query, mode, chunk),
        source_key=f"gdelt_{query_key}_{mode}_{chunk.key}",
        min_interval_seconds=min_interval_seconds,
        backoff_seconds=backoff_seconds,
        max_retries=max_retries,
        force=force,
        tolerate_failure=tolerate_failure,
        validate=is_json_payload,
        extra_metadata={
            "gdelt_query": query,
            "gdelt_mode": mode,
            "chunk_key": chunk.key,
            "chunk_start": chunk.start.date().isoformat(),
            "chunk_end": chunk.end.date().isoformat(),
        },
    )
    return {"result": result, "cache_path": cache_path}


def assert_daily_resolution(payload: Any, label: str) -> None:
    """Reject any response whose buckets are not one UTC calendar day each.

    This is the check that stands between the panel and a silently misaligned
    series. GDELT reports its own binning in ``query_details.date_resolution``;
    that is asserted, and then the returned grid is checked directly so the
    assertion does not rest on the vendor's self-description alone.
    """

    if not isinstance(payload, dict) or not payload.get("timeline"):
        return
    resolution = (payload.get("query_details") or {}).get("date_resolution")
    if resolution is not None and resolution != "day":
        raise AdaptiveBinError(
            f"{label}: GDELT reported date_resolution={resolution!r}, not 'day'"
        )
    points = payload["timeline"][0].get("data", [])
    stamps = [point["date"] for point in points]
    non_midnight = [stamp for stamp in stamps if not stamp.endswith("T000000Z")]
    if non_midnight:
        raise AdaptiveBinError(
            f"{label}: {len(non_midnight)} buckets are not midnight-aligned, "
            f"first {non_midnight[0]!r}"
        )
    dates = sorted(pd.Timestamp(stamp[:8]) for stamp in stamps)
    if len(dates) < 3:
        return
    steps = {(later - earlier).days for earlier, later in zip(dates, dates[1:])}
    # A step > 1 is an absent day, not a widened bin, so it is only evidence of
    # adaptive binning when *most* steps exceed one day.
    if steps and min(steps) > 1:
        raise AdaptiveBinError(
            f"{label}: smallest observed spacing is {min(steps)} days; bins are "
            "not daily"
        )


class AdaptiveBinError(RuntimeError):
    """Raised when GDELT returns bins that are not one UTC calendar day."""


def parse_timeline(payload: Any, mode: str) -> pd.DataFrame:
    """Turn one timeline response into tidy rows keyed by UTC calendar date.

    An empty ``{}`` response is GDELT's answer to a query that matched nothing
    at all over the whole window. It is returned as an empty frame, never as a
    frame of zeros.
    """

    columns = {"utc_date": "datetime64[ns]", "value": "float64"}
    if mode == "timelinevolraw":
        columns["norm"] = "float64"

    if not isinstance(payload, dict) or not payload.get("timeline"):
        return pd.DataFrame({name: pd.Series(dtype=kind) for name, kind in columns.items()})

    series = payload["timeline"][0].get("data", [])
    records = []
    for point in series:
        stamp = point["date"]
        if not stamp.endswith("T000000Z"):
            raise ValueError(
                f"GDELT returned a non-midnight bucket {stamp!r}; the daily "
                "calendar-date mapping would be undefined."
            )
        row = {
            "utc_date": pd.Timestamp(stamp[:8]),
            "value": float(point["value"]),
        }
        if mode == "timelinevolraw":
            row["norm"] = float(point["norm"])
        records.append(row)

    frame = pd.DataFrame.from_records(records) if records else pd.DataFrame(
        {name: pd.Series(dtype=kind) for name, kind in columns.items()}
    )
    if not frame.empty:
        if frame["utc_date"].duplicated().any():
            raise ValueError("GDELT returned duplicate calendar-date buckets")
        frame = frame.sort_values("utc_date").reset_index(drop=True)
    return frame


def acquire_timelines(
    *,
    raw_dir: Path = DEFAULT_RAW_DIR / "gdelt",
    queries: dict[str, str] | None = None,
    modes: Iterable[str] = TIMELINE_MODES,
    start: pd.Timestamp = PANEL_START,
    end: pd.Timestamp = PANEL_END,
    chunk_mode: str = "single",
    force: bool = False,
    min_interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
    max_retries: int = 1,
    backoff_seconds: float = 0.0,
    stop_on_rate_limit: bool = True,
) -> dict[str, Any]:
    """Pull every (query, mode, chunk) combination into the raw cache.

    **Fail fast.** GDELT applies a sticky IP penalty, and retrying makes it
    worse rather than better: the observed behaviour is that continued requests
    keep the block alive. So the default is one attempt per request and an
    immediate stop on the first refusal. Nothing is retried and nothing waits.

    Resumable by construction: anything already cached is skipped and a refused
    request is never cached, so simply running the command again later picks up
    exactly where it stopped. Getting the data over several short runs is the
    intended workflow, not a fallback.
    """

    queries = ALL_QUERIES if queries is None else queries
    validate_queries(queries)
    raw_dir.mkdir(parents=True, exist_ok=True)
    chunks = (
        build_single_chunk(start, end)
        if chunk_mode == "single"
        else build_chunks(start, end)
    )

    fetched = 0
    from_cache = 0
    empty_responses: list[str] = []
    failures: list[str] = []
    resolution_failures: list[str] = []

    for query_key, query in queries.items():
        # The coverage series exists only to supply `norm`; the other two
        # modes would be wasted requests against a rate-limited API.
        key_modes = ("timelinevolraw",) if query_key == COVERAGE_KEY else tuple(modes)
        for mode in key_modes:
            for chunk in chunks:
                label = f"{query_key}/{mode}/{chunk.key}"
                handle = fetch_timeline(
                    query_key=query_key,
                    query=query,
                    mode=mode,
                    chunk=chunk,
                    raw_dir=raw_dir,
                    force=force,
                    min_interval_seconds=min_interval_seconds,
                    max_retries=max_retries,
                    backoff_seconds=backoff_seconds,
                    tolerate_failure=True,
                )
                result = handle["result"]
                if result.transient_failure:
                    failures.append(label)
                    if stop_on_rate_limit:
                        return {
                            "chunk_mode": chunk_mode,
                            "chunks": [chunk.key for chunk in chunks],
                            "requests_from_network": fetched,
                            "requests_from_cache": from_cache,
                            "empty_responses": empty_responses,
                            "transient_failures": failures,
                            "resolution_failures": resolution_failures,
                            "complete": False,
                            "stopped_early": True,
                            "stopped_at": label,
                            "raw_dir": str(raw_dir),
                            "note": (
                                "Stopped on the first refusal by design. Re-run "
                                "the same command later; cached chunks are kept "
                                "and only the gaps are requested."
                            ),
                        }
                    continue
                if result.from_cache:
                    from_cache += 1
                else:
                    fetched += 1
                payload = result.read_json()
                try:
                    assert_daily_resolution(payload, label)
                except AdaptiveBinError as error:
                    resolution_failures.append(str(error))
                if not isinstance(payload, dict) or not payload.get("timeline"):
                    empty_responses.append(label)

    return {
        "chunk_mode": chunk_mode,
        "chunks": [chunk.key for chunk in chunks],
        "requests_from_network": fetched,
        "requests_from_cache": from_cache,
        "empty_responses": empty_responses,
        "transient_failures": failures,
        "resolution_failures": resolution_failures,
        "complete": not failures,
        "raw_dir": str(raw_dir),
    }


def load_timeline_frame(
    *,
    query_key: str,
    mode: str,
    raw_dir: Path,
    chunks: list[Chunk],
) -> pd.DataFrame:
    """Stitch every cached chunk for one (query, mode) into one frame.

    Chunk seams are asserted here as well as at build time: the stitched frame
    must contain no duplicate calendar date, which is the observable form of
    "no overlap", and each chunk's observed dates must fall inside its own
    requested bounds, which is the observable form of "no bleed".
    """

    frames = []
    for chunk in chunks:
        path = raw_dir / f"{query_key}_{mode}_{chunk.key}.json"
        if not path.is_file():
            raise FileNotFoundError(f"Missing cached GDELT chunk: {path}")
        frame = parse_timeline(json.loads(path.read_text(encoding="utf-8")), mode)
        if not frame.empty:
            outside = frame.loc[
                (frame["utc_date"] < chunk.start) | (frame["utc_date"] > chunk.end)
            ]
            if not outside.empty:
                raise ValueError(
                    f"{query_key}/{mode}/{chunk.key} returned dates outside its "
                    f"requested bounds: {outside['utc_date'].tolist()[:5]}"
                )
        frames.append(frame)

    stitched = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not stitched.empty:
        if stitched["utc_date"].duplicated().any():
            duplicates = stitched.loc[stitched["utc_date"].duplicated(), "utc_date"]
            raise ValueError(
                f"Chunk seams overlap for {query_key}/{mode}: {duplicates.tolist()[:5]}"
            )
        stitched = stitched.sort_values("utc_date").reset_index(drop=True)
    return stitched


# --------------------------------------------------------------------------
# Semantic sanity check (article titles)
# --------------------------------------------------------------------------

SANITY_WINDOWS = (
    ("2018-02-05", "2018-02-12"),
    ("2022-06-13", "2022-06-20"),
)


def artlist_url(query: str, start: str, end: str, records: int = 20) -> str:
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": str(records),
        "sort": "hybridrel",
        "startdatetime": pd.Timestamp(start).strftime("%Y%m%d000000"),
        "enddatetime": pd.Timestamp(end).strftime("%Y%m%d000000"),
    }
    return f"{GDELT_ENDPOINT}?{urlencode(params)}"


def fetch_article_sample(
    *,
    query_key: str,
    query: str,
    window: tuple[str, str],
    raw_dir: Path,
    force: bool = False,
) -> list[dict[str, str]]:
    """Cache and return a small article sample for the semantic sanity check."""

    start, end = window
    cache_path = raw_dir / "artlist" / f"{query_key}_{start}_{end}.json"
    result = cached_fetch(
        cache_path=cache_path,
        url=artlist_url(query, start, end),
        source_key=f"gdelt_artlist_{query_key}_{start}",
        min_interval_seconds=MIN_REQUEST_INTERVAL_SECONDS,
        backoff_seconds=15.0,
        force=force,
        extra_metadata={"gdelt_query": query, "gdelt_mode": "artlist"},
    )
    payload = result.read_json()
    articles = payload.get("articles", []) if isinstance(payload, dict) else []
    return [
        {
            "title": article.get("title", ""),
            "domain": article.get("domain", ""),
            "seendate": article.get("seendate", ""),
        }
        for article in articles
    ]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR / "gdelt")
    parser.add_argument("--start", default=str(PANEL_START.date()))
    parser.add_argument("--end", default=str(PANEL_END.date()))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--queries",
        default="",
        help=(
            "Comma-separated mechanism query keys to acquire, e.g. 'panic'. "
            "The coverage series is always included because the panel cannot "
            "tell a confirmed zero from an archive gap without it. Default: all."
        ),
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Do not stop on the first rate-limit refusal (not recommended).",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    report = validate_queries()
    if args.validate_only:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    selected = ALL_QUERIES
    if args.queries:
        keys = [key.strip() for key in args.queries.split(",") if key.strip()]
        unknown = [key for key in keys if key not in MECHANISM_QUERIES]
        if unknown:
            raise SystemExit(f"Unknown query keys: {unknown}")
        # Coverage is never optional: without it an absent day cannot be told
        # apart from a day the query genuinely did not match.
        selected = {key: MECHANISM_QUERIES[key] for key in keys}
        selected[COVERAGE_KEY] = Q_COVERAGE

    acquisition = acquire_timelines(
        raw_dir=args.raw_dir,
        queries=selected,
        start=pd.Timestamp(args.start),
        end=pd.Timestamp(args.end),
        force=args.force,
        stop_on_rate_limit=not args.keep_going,
    )
    write_json(args.raw_dir / "acquisition_report.json", acquisition)
    print(json.dumps(acquisition, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
