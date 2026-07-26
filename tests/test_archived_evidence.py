"""Point-in-time and grounding gates for the archived evidence path."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pandas as pd
import pytest

from src.evidence.archived_provider import ArchivedEvidenceProvider
from src.evidence.corpus_schema import (
    archived_content_sha256,
    load_archived_corpus,
)
from src.evidence.mvp import build_evidence_snapshot
from src.evidence.versioned_classifier import (
    CLASSIFIER_SCHEMA_VERSION,
    PROMPT_VERSION,
    classifier_input_sha256,
    validate_classifier_response,
)
from src.risk.dm_engine import build_primary_assessment
from src.utils.io import write_json


def _document(
    document_id: str,
    *,
    title: str = "Federal Reserve expands liquidity support",
    passage: str = (
        "The Federal Reserve announced liquidity support as financial "
        "conditions deteriorated."
    ),
    publication_timestamp: str = "2020-03-23T10:00:00-04:00",
    discovery_timestamp: str = "2020-03-23T10:05:00-04:00",
    availability_timestamp: str = "2020-03-23T10:05:00-04:00",
    content_version_timestamp: str = "2020-03-23T10:05:00-04:00",
    availability_status: str = "verified_archived_content",
    source_category: str = "news",
    url: str | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "document_id": document_id,
        "title": title,
        "source": "Example Newswire",
        "source_category": source_category,
        "publication_timestamp": publication_timestamp,
        "discovery_timestamp": discovery_timestamp,
        "availability_timestamp": availability_timestamp,
        "content_version_timestamp": content_version_timestamp,
        "availability_status": availability_status,
        "url": url or f"https://example.test/{document_id}",
        "passage": passage,
        "archive_source": "test_warc",
        "archive_locator": f"warc:test/{document_id}",
        "acquisition_timestamp": "2026-07-26T12:00:00+00:00",
    }
    record["content_sha256"] = archived_content_sha256(record)
    return record


def _write_corpus(path: Path, documents: list[dict[str, object]]) -> None:
    write_json(
        path,
        {
            "schema_version": "archived-evidence-v1",
            "corpus_version": "test-corpus-2020-v1",
            "selection_method": "gdelt_gkg_inventory",
            "selection_query": {
                "query_version": "momentum-archive-query-v1",
                "terms": ["liquidity", "rebound"],
                "language": "English",
                "start_timestamp": "2020-01-01T00:00:00+00:00",
                "end_timestamp": "2020-03-31T23:59:59+00:00",
            },
            "archive_inventory": "https://data.gdeltproject.org/gkg/index.html",
            "documents": documents,
        },
    )


def _elevated_2020():
    return build_primary_assessment(
        as_of_date=pd.Timestamp("2020-03-24"),
        horizon=20,
    )


def _classifier_payload(retrieval, *, passage: str) -> dict[str, object]:
    document = retrieval.documents[0].document
    mechanism = retrieval.documents[0].matched_mechanisms[0]
    return {
        "schema_version": CLASSIFIER_SCHEMA_VERSION,
        "as_of_date": retrieval.as_of_date,
        "timestamp_cutoff": retrieval.timestamp_cutoff,
        "retrieval_sha256": retrieval.retrieval_sha256,
        "classifier_input_sha256": classifier_input_sha256(retrieval),
        "prompt_version": PROMPT_VERSION,
        "model_identifier": "test-classifier-v1",
        "classifier_mode": "deterministic_cached_response",
        "temperature": 0,
        "items": [
            {
                "document_id": document.document_id,
                "classification": "supporting",
                "mechanism": mechanism,
                "extracted_passage": passage,
                "confidence": 0.91,
                "rationale": "The archived passage supports the liquidity mechanism.",
                "exclusion_reason": None,
            }
        ],
    }


def test_strict_corpus_rejects_manual_selection(tmp_path: Path) -> None:
    path = tmp_path / "manual.json"
    _write_corpus(path, [_document("valid")])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["selection_method"] = "manual_curated"
    write_json(path, payload)

    with pytest.raises(ValueError, match="deterministic archive inventory"):
        load_archived_corpus(path)


def test_provider_enforces_all_cutoffs_dedupe_and_uncertainty(
    tmp_path: Path,
) -> None:
    valid = _document("valid")
    duplicate_title = _document("z-duplicate")
    future_version = _document(
        "future-version",
        content_version_timestamp="2020-03-25T09:00:00-04:00",
    )
    future_publication = _document(
        "future-publication",
        publication_timestamp="2020-03-25T09:00:00-04:00",
    )
    future_discovery = _document(
        "future-discovery",
        discovery_timestamp="2020-03-25T09:00:00-04:00",
    )
    future_availability = _document(
        "future-availability",
        availability_timestamp="2020-03-25T09:00:00-04:00",
    )
    uncertain = _document(
        "uncertain",
        availability_status="content_version_uncertain",
    )
    outside_lookback = _document(
        "old",
        publication_timestamp="2019-01-01T09:00:00-05:00",
    )
    disallowed = _document("blog", source_category="blog")
    no_match = _document(
        "unmatched",
        title="Quarterly corporate update",
        passage="The company published its quarterly operational update.",
    )
    path = tmp_path / "archive.json"
    _write_corpus(
        path,
        [
            valid,
            duplicate_title,
            future_version,
            future_publication,
            future_discovery,
            future_availability,
            uncertain,
            outside_lookback,
            disallowed,
            no_match,
        ],
    )
    primary = _elevated_2020()
    provider = ArchivedEvidenceProvider(corpus_path=path)

    first = provider.retrieve(primary)
    second = provider.retrieve(primary)

    assert first.status == "available"
    assert [item.document.document_id for item in first.documents] == ["valid"]
    assert first.retrieval_sha256 == second.retrieval_sha256
    reasons = {item.reason for item in first.exclusions}
    assert reasons == {
        "duplicate",
        "disallowed_source",
        "future_availability",
        "future_content_version",
        "future_discovery",
        "future_publication",
        "no_query_match",
        "outside_lookback_window",
        "uncertain_content_version",
    }


@pytest.mark.parametrize(
    ("as_of_date", "expected_status"),
    [
        ("2009-03-06", "unavailable"),
        ("2020-03-24", "unavailable"),
        ("2024-01-05", "skipped_quiet_state"),
    ],
)
def test_archive_mode_never_falls_back_to_fixture(
    tmp_path: Path,
    as_of_date: str,
    expected_status: str,
) -> None:
    primary = build_primary_assessment(
        as_of_date=pd.Timestamp(as_of_date),
        horizon=20,
    )
    evidence = build_evidence_snapshot(
        primary=primary,
        provider_mode="archived",
        archived_corpus_path=tmp_path / "missing.json",
    )

    assert evidence.status == expected_status
    assert evidence.mode == "archived_point_in_time"
    assert evidence.provider_name == "archived_evidence_provider_v1"
    if primary.elevated:
        assert "No fixture fallback" in evidence.detail


def test_archive_retrieval_stays_unclassified_without_response(
    tmp_path: Path,
) -> None:
    path = tmp_path / "archive.json"
    _write_corpus(path, [_document("valid")])

    evidence = build_evidence_snapshot(
        primary=_elevated_2020(),
        provider_mode="archived",
        archived_corpus_path=path,
    )

    assert evidence.status == "retrieved_unclassified"
    assert evidence.retrieved_documents == 1
    assert evidence.supporting_items == 0
    assert evidence.citations == ()


def test_versioned_classifier_requires_archive_grounding(tmp_path: Path) -> None:
    path = tmp_path / "archive.json"
    _write_corpus(path, [_document("valid")])
    retrieval = ArchivedEvidenceProvider(corpus_path=path).retrieve(
        _elevated_2020()
    )
    response_path = tmp_path / "response.json"
    write_json(
        response_path,
        _classifier_payload(retrieval, passage="This sentence was invented."),
    )

    with pytest.raises(ValueError, match="not grounded"):
        validate_classifier_response(
            retrieval=retrieval,
            response_path=response_path,
        )


def test_versioned_classifier_rejects_stale_placeholder_and_risk_fields(
    tmp_path: Path,
) -> None:
    corpus_path = tmp_path / "archive.json"
    document = _document("valid")
    _write_corpus(corpus_path, [document])
    retrieval = ArchivedEvidenceProvider(corpus_path=corpus_path).retrieve(
        _elevated_2020()
    )
    valid = _classifier_payload(
        retrieval,
        passage=str(document["passage"]),
    )
    cases: list[tuple[dict[str, object], str]] = []

    stale = copy.deepcopy(valid)
    stale["retrieval_sha256"] = "0" * 64
    cases.append((stale, "stale"))

    wrong_input = copy.deepcopy(valid)
    wrong_input["classifier_input_sha256"] = "0" * 64
    cases.append((wrong_input, "approved input"))

    placeholder = copy.deepcopy(valid)
    placeholder["model_identifier"] = "unspecified"
    cases.append((placeholder, "versioned model identifier"))

    risk_field = copy.deepcopy(valid)
    risk_field["risk_probability"] = 0.99
    cases.append((risk_field, "fields differ"))

    response_path = tmp_path / "response.json"
    for payload, message in cases:
        write_json(response_path, payload)
        with pytest.raises(ValueError, match=message):
            validate_classifier_response(
                retrieval=retrieval,
                response_path=response_path,
            )


def test_versioned_classifier_promotes_only_valid_response(
    tmp_path: Path,
) -> None:
    corpus_path = tmp_path / "archive.json"
    document = _document("valid")
    _write_corpus(corpus_path, [document])
    retrieval = ArchivedEvidenceProvider(corpus_path=corpus_path).retrieve(
        _elevated_2020()
    )
    response_path = tmp_path / "response.json"
    write_json(
        response_path,
        _classifier_payload(
            retrieval,
            passage=str(document["passage"]),
        ),
    )

    evidence = build_evidence_snapshot(
        primary=_elevated_2020(),
        provider_mode="archived",
        archived_corpus_path=corpus_path,
        classifier_response_path=response_path,
    )

    assert evidence.status == "available"
    assert evidence.prompt_version == PROMPT_VERSION
    assert evidence.model_identifier == "test-classifier-v1"
    assert evidence.supporting_items == 1
    assert evidence.citations[0]["archive_locator"] == "warc:test/valid"
