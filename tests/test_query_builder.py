"""Tests for deterministic mechanism-aware query construction."""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from src.evidence.query_builder import build_retrieval_request
from src.monitoring.positioning import build_positioning_state
from src.monitoring.risk_state import build_risk_state


def _states(as_of_date: str):
    timestamp = pd.Timestamp(as_of_date)
    return (
        build_risk_state(as_of_date=timestamp, horizon=20),
        build_positioning_state(as_of_date=timestamp),
    )


def test_query_builder_is_deterministic_and_mechanism_aware() -> None:
    risk_state, positioning_state = _states("2009-03-06")
    inputs = {
        "risk_state": risk_state,
        "positioning_state": positioning_state,
        "risk_state_sha256": "0" * 64,
        "positioning_state_sha256": "1" * 64,
    }

    first = build_retrieval_request(**inputs)
    second = build_retrieval_request(**inputs)

    assert first == second
    assert first.timestamp_cutoff == "2009-03-06T16:00:00-05:00"
    assert first.max_documents == 8
    assert first.lookback_days == 120
    assert "policy or liquidity shock" in first.mechanisms
    assert "crowding or deleveraging" in first.mechanisms
    assert all(query.related_drivers for query in first.queries)
    assert all(query.search_terms for query in first.queries)


def test_query_builder_rejects_state_date_mismatch() -> None:
    risk_state, positioning_state = _states("2009-03-06")
    mismatched = dataclasses.replace(
        positioning_state,
        as_of_date="2009-03-05",
        as_of_timestamp="2009-03-05T16:00:00-05:00",
    )

    with pytest.raises(ValueError, match="share an as-of date"):
        build_retrieval_request(
            risk_state=risk_state,
            positioning_state=mismatched,
            risk_state_sha256="0" * 64,
            positioning_state_sha256="1" * 64,
        )
