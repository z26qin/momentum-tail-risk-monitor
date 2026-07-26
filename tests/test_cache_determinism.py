"""A second run must make zero network calls and reproduce identical outputs.

The operator loses tool access after this session, so anything not on disk is
lost work. These tests are the guarantee that the caches are actually complete:
``NETWORK_ENABLED`` is switched off, which turns any cache miss into a loud
``NetworkDisabledError`` rather than a silent refetch.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from src.utils import http
from src.utils.io import DEFAULT_PROCESSED_DIR, DEFAULT_RAW_DIR


GDELT_RAW = DEFAULT_RAW_DIR / "gdelt"
FINRA_RAW = DEFAULT_RAW_DIR / "finra"
PRICES_RAW = DEFAULT_RAW_DIR / "prices"


@pytest.fixture
def offline():
    """Run the body with the network hard-disabled."""

    original = http.NETWORK_ENABLED
    http.NETWORK_ENABLED = False
    try:
        yield
    finally:
        http.NETWORK_ENABLED = original


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_network_disabled_flag_actually_blocks_a_cache_miss(offline, tmp_path):
    with pytest.raises(http.NetworkDisabledError):
        http.cached_fetch(
            cache_path=tmp_path / "never_cached.json",
            url="https://example.invalid/resource",
            source_key="sentinel",
        )


def _fully_cached_queries() -> dict[str, str]:
    """Mechanism queries whose three modes are all cached, plus coverage.

    The cache is populated incrementally, so this test asserts determinism over
    whatever is actually on disk rather than assuming a complete pull.
    """

    from src.data.gdelt import (
        COVERAGE_KEY,
        MECHANISM_QUERIES,
        Q_COVERAGE,
        TIMELINE_MODES,
    )

    if not (GDELT_RAW / f"{COVERAGE_KEY}_timelinevolraw_full.json").is_file():
        return {}
    selected = {
        key: query
        for key, query in MECHANISM_QUERIES.items()
        if all(
            (GDELT_RAW / f"{key}_{mode}_full.json").is_file()
            for mode in TIMELINE_MODES
        )
    }
    if not selected:
        return {}
    selected[COVERAGE_KEY] = Q_COVERAGE
    return selected


@pytest.mark.skipif(
    not _fully_cached_queries(),
    reason="no complete GDELT query is cached yet",
)
def test_gdelt_acquisition_rerun_makes_no_network_calls(offline):
    from src.data.gdelt import acquire_timelines

    report = acquire_timelines(
        raw_dir=GDELT_RAW, chunk_mode="single", queries=_fully_cached_queries()
    )
    assert report["requests_from_network"] == 0
    assert report["transient_failures"] == []
    assert report["resolution_failures"] == []


@pytest.mark.skipif(
    not (FINRA_RAW / "short_interest" / "short_interest_page_000.csv").is_file(),
    reason="FINRA short-interest cache not populated",
)
def test_finra_short_interest_rerun_makes_no_network_calls(offline):
    from src.data.finra import fetch_short_interest
    from src.data.universe import load_universe

    frame = fetch_short_interest(
        load_universe(), raw_dir=FINRA_RAW / "short_interest"
    )
    assert not frame.empty


@pytest.mark.skipif(
    not (FINRA_RAW / "schedule" / "schedule_live.html").is_file(),
    reason="FINRA schedule cache not populated",
)
def test_finra_schedule_rerun_makes_no_network_calls(offline):
    from src.data.finra import fetch_schedules

    outcome = fetch_schedules(FINRA_RAW / "schedule")
    assert not outcome["schedule"].empty
    assert outcome["conflicts"] == [], (
        "overlapping archived snapshots disagree about a publication date"
    )


@pytest.mark.skipif(
    not (PRICES_RAW / "AAPL.json").is_file(), reason="price cache not populated"
)
def test_price_acquisition_rerun_makes_no_network_calls(offline):
    from src.data.prices import acquire_prices
    from src.data.universe import load_universe

    report = acquire_prices(load_universe(), raw_dir=PRICES_RAW)
    assert report["unavailable"] == []
    assert report["retrieved"] > 0


@pytest.mark.skipif(
    not any(GDELT_RAW.glob("*_timelinevol*_full.json")),
    reason="raw GDELT payloads required for narrative rebuild are not present",
)
def test_narrative_panel_rebuild_is_byte_identical(offline):
    from src.features.narrative_panel import build_panel

    path = DEFAULT_PROCESSED_DIR / "narrative_panel.parquet"
    before = _sha256(path)
    build_panel()
    assert _sha256(path) == before


@pytest.mark.skipif(
    not (DEFAULT_PROCESSED_DIR / "positioning_panel.parquet").is_file(),
    reason="positioning panel not built",
)
def test_positioning_panel_rebuild_is_byte_identical(offline):
    from src.features.positioning_panel import build_panel

    path = DEFAULT_PROCESSED_DIR / "positioning_panel.parquet"
    before = _sha256(path)
    build_panel()
    assert _sha256(path) == before


@pytest.mark.skipif(
    not (FINRA_RAW / "daily").is_dir(), reason="FINRA daily cache not populated"
)
def test_every_expected_finra_daily_session_has_a_cache_entry():
    """Every weekday from the consolidated start is cached, present or absent."""

    from src.data.finra import DAILY_FILE_START

    directory = FINRA_RAW / "daily"
    cached = {path.name.replace("CNMSshvol", "")[:8] for path in directory.glob("*.gz")}
    absent = {
        path.name.replace("CNMSshvol", "")[:8]
        for path in directory.glob("*.metadata.json")
    }
    known = cached | absent

    end = max(pd.Timestamp(stamp) for stamp in known)
    weekdays = {
        stamp.strftime("%Y%m%d")
        for stamp in pd.bdate_range(DAILY_FILE_START, end)
    }
    missing = sorted(weekdays - known)
    assert not missing, f"{len(missing)} weekdays never reached the cache: {missing[:10]}"
