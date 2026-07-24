"""Timestamp, ranking, and deduplication tests for cached retrieval."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from src.evidence.corpus import load_corpus
from src.evidence.query_builder import build_retrieval_request
from src.evidence.retriever import retrieve
from src.monitoring.positioning import build_positioning_state
from src.monitoring.risk_state import build_risk_state


def _result(as_of_date: str):
    timestamp = pd.Timestamp(as_of_date)
    risk_state = build_risk_state(as_of_date=timestamp, horizon=20)
    positioning_state = build_positioning_state(as_of_date=timestamp)
    request = build_retrieval_request(
        risk_state=risk_state,
        positioning_state=positioning_state,
        risk_state_sha256="0" * 64,
        positioning_state_sha256="1" * 64,
    )
    return request, retrieve(
        request=request,
        corpus=load_corpus(),
        request_sha256="2" * 64,
    )


@pytest.mark.parametrize("as_of_date", ["2009-03-06", "2024-01-05"])
def test_retrieval_is_deterministic_and_point_in_time(as_of_date: str) -> None:
    request, result = _result(as_of_date)
    repeated = retrieve(
        request=request,
        corpus=load_corpus(),
        request_sha256="2" * 64,
    )
    cutoff = datetime.fromisoformat(request.timestamp_cutoff).astimezone(
        timezone.utc
    )
    lower_bound = cutoff - timedelta(days=request.lookback_days)

    assert result == repeated
    assert result.returned_document_count <= request.max_documents
    assert result.returned_document_count > 0
    assert all(
        lower_bound
        <= datetime.fromisoformat(
            document.publication_timestamp
        ).astimezone(timezone.utc)
        <= cutoff
        for document in result.documents
    )
    assert all(
        document.timestamp_status != "uncertain_content_version"
        for document in result.documents
    )
    assert [document.retrieval_score for document in result.documents] == (
        sorted(
            (document.retrieval_score for document in result.documents),
            reverse=True,
        )
    )


def test_control_case_excludes_future_uncertain_and_duplicate_documents() -> None:
    _, result = _result("2024-01-05")
    reasons = {
        exclusion.document_id: exclusion.reason
        for exclusion in result.exclusions
    }
    returned_ids = {document.document_id for document in result.documents}

    assert reasons["bls-2024-01-11-cpi-future"] == "future_publication"
    assert (
        reasons["ap-2024-01-05-market-update-uncertain"]
        == "uncertain_content_version"
    )
    duplicate_ids = {
        "reuters-2024-01-05-wall-street",
        "reuters-2024-01-05-wall-street-duplicate",
    }
    assert len(duplicate_ids.intersection(returned_ids)) == 1
    assert "duplicate" in {
        reasons.get(document_id) for document_id in duplicate_ids
    }
