"""Query constraints, chunk seams, and response parsing for GDELT."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.data.gdelt import (
    ALL_QUERIES,
    LANGUAGE_FILTER,
    MARKET_ANCHOR,
    MAX_QUERY_CHARACTERS,
    AdaptiveBinError,
    QueryConstraintError,
    assert_chunks_tile,
    assert_daily_resolution,
    build_chunks,
    build_single_chunk,
    is_json_payload,
    load_timeline_frame,
    parse_timeline,
    validate_queries,
)


# --------------------------------------------------------------------------
# Query constraints
# --------------------------------------------------------------------------


def test_every_frozen_query_satisfies_the_design_constraints():
    report = validate_queries()
    assert set(report) == set(ALL_QUERIES)
    for key, entry in report.items():
        assert MARKET_ANCHOR in entry["query"], key
        assert LANGUAGE_FILTER in entry["query"], key
        assert entry["characters"] <= MAX_QUERY_CHARACTERS, key


def test_a_bare_mechanism_query_without_the_market_anchor_is_rejected():
    with pytest.raises(QueryConstraintError, match="market anchor"):
        validate_queries({"bad": f"(plunge OR turmoil) {LANGUAGE_FILTER}"})


def test_the_hindsight_rule_rejects_episode_specific_tokens():
    with pytest.raises(QueryConstraintError, match="hindsight"):
        validate_queries(
            {"bad": f'(pandemic OR lockdown) {MARKET_ANCHOR} {LANGUAGE_FILTER}'}
        )


def test_an_over_long_query_is_rejected_before_it_reaches_the_api():
    padding = " OR ".join(f'"term {index}"' for index in range(40))
    with pytest.raises(QueryConstraintError, match="exceeds"):
        validate_queries({"bad": f"({padding}) {MARKET_ANCHOR} {LANGUAGE_FILTER}"})


def test_non_json_bodies_are_rejected_before_caching():
    assert is_json_payload(b'{"timeline": []}')
    assert not is_json_payload(b"Your query was too short or too long.")


# --------------------------------------------------------------------------
# Chunk seams
# --------------------------------------------------------------------------


def test_year_chunks_tile_the_range_without_gap_or_overlap():
    start, end = pd.Timestamp("2017-01-01"), pd.Timestamp("2026-06-30")
    chunks = build_chunks(start, end)
    assert chunks[0].start == start
    assert chunks[-1].end == end
    for earlier, later in zip(chunks, chunks[1:]):
        assert (later.start - earlier.end).days == 1
    covered = set()
    for chunk in chunks:
        days = set(pd.date_range(chunk.start, chunk.end, freq="D"))
        assert not (covered & days), "chunks overlap"
        covered |= days
    assert covered == set(pd.date_range(start, end, freq="D"))


def test_chunk_tiling_assertion_catches_a_deliberate_gap():
    from src.data.gdelt import Chunk

    broken = [
        Chunk("a", pd.Timestamp("2020-01-01"), pd.Timestamp("2020-06-29")),
        Chunk("b", pd.Timestamp("2020-07-01"), pd.Timestamp("2020-12-31")),
    ]
    with pytest.raises(ValueError, match="gap/overlap"):
        assert_chunks_tile(broken, pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31"))


def test_single_chunk_spans_the_whole_range():
    chunks = build_single_chunk(pd.Timestamp("2017-01-01"), pd.Timestamp("2026-06-30"))
    assert len(chunks) == 1
    assert chunks[0].start_stamp == "20170101000000"
    assert chunks[0].end_stamp == "20260630000000"


def _write_chunk(directory, key, mode, chunk_key, dates, values):
    payload = {
        "query_details": {"date_resolution": "day"},
        "timeline": [
            {
                "series": "Volume Intensity",
                "data": [
                    {"date": f"{date}T000000Z", "value": value}
                    for date, value in zip(dates, values)
                ],
            }
        ],
    }
    path = directory / f"{key}_{mode}_{chunk_key}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_stitching_rejects_overlapping_chunks(tmp_path):
    from src.data.gdelt import Chunk

    chunks = [
        Chunk("2020", pd.Timestamp("2020-12-30"), pd.Timestamp("2020-12-31")),
        Chunk("2021", pd.Timestamp("2021-01-01"), pd.Timestamp("2021-01-02")),
    ]
    _write_chunk(tmp_path, "q", "timelinevol", "2020", ["20201230", "20201231"], [1, 2])
    # Chunk 2021 wrongly repeats 2020-12-31.
    _write_chunk(
        tmp_path, "q", "timelinevol", "2021", ["20201231", "20210101"], [2, 3]
    )
    with pytest.raises(ValueError, match="outside its requested bounds"):
        load_timeline_frame(
            query_key="q", mode="timelinevol", raw_dir=tmp_path, chunks=chunks
        )


def test_stitching_accepts_clean_seams(tmp_path):
    from src.data.gdelt import Chunk

    chunks = [
        Chunk("2020", pd.Timestamp("2020-12-30"), pd.Timestamp("2020-12-31")),
        Chunk("2021", pd.Timestamp("2021-01-01"), pd.Timestamp("2021-01-02")),
    ]
    _write_chunk(tmp_path, "q", "timelinevol", "2020", ["20201230", "20201231"], [1, 2])
    _write_chunk(tmp_path, "q", "timelinevol", "2021", ["20210101", "20210102"], [3, 4])
    frame = load_timeline_frame(
        query_key="q", mode="timelinevol", raw_dir=tmp_path, chunks=chunks
    )
    assert len(frame) == 4
    assert not frame["utc_date"].duplicated().any()
    assert frame["utc_date"].is_monotonic_increasing


# --------------------------------------------------------------------------
# Response parsing and bin resolution
# --------------------------------------------------------------------------


def test_an_empty_response_is_an_empty_frame_not_a_frame_of_zeros():
    frame = parse_timeline({}, "timelinevol")
    assert frame.empty
    assert list(frame.columns) == ["utc_date", "value"]


def test_a_non_midnight_bucket_is_rejected():
    payload = {
        "timeline": [{"data": [{"date": "20200101T120000Z", "value": 1.0}]}]
    }
    with pytest.raises(ValueError, match="non-midnight"):
        parse_timeline(payload, "timelinevol")


def test_adaptive_bins_are_detected():
    payload = {
        "query_details": {"date_resolution": "month"},
        "timeline": [
            {
                "data": [
                    {"date": "20200101T000000Z", "value": 1.0},
                    {"date": "20200201T000000Z", "value": 1.0},
                    {"date": "20200301T000000Z", "value": 1.0},
                ]
            }
        ],
    }
    with pytest.raises(AdaptiveBinError, match="date_resolution"):
        assert_daily_resolution(payload, "test")


def test_an_absent_day_is_not_mistaken_for_an_adaptive_bin():
    payload = {
        "query_details": {"date_resolution": "day"},
        "timeline": [
            {
                "data": [
                    {"date": "20201018T000000Z", "value": 1.0},
                    {"date": "20201019T000000Z", "value": 1.0},
                    # 2020-10-20 is a genuine GDELT archive gap.
                    {"date": "20201021T000000Z", "value": 1.0},
                ]
            }
        ],
    }
    assert_daily_resolution(payload, "test")


def test_volraw_carries_the_norm_column():
    payload = {
        "timeline": [
            {"data": [{"date": "20200101T000000Z", "value": 10.0, "norm": 1000.0}]}
        ]
    }
    frame = parse_timeline(payload, "timelinevolraw")
    assert frame["norm"].iloc[0] == 1000.0
