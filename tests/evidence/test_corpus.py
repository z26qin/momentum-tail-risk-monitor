"""Validation tests for the compact offline evidence corpus."""

from __future__ import annotations

from datetime import datetime

from src.evidence.corpus import DEFAULT_CORPUS_PATH, load_corpus
from src.monitoring.contracts import CandidateDocument
from src.utils.io import read_json


def test_corpus_contracts_manifest_and_round_trip() -> None:
    documents = load_corpus()
    manifest = read_json(
        DEFAULT_CORPUS_PATH.with_name("source_manifest_v1.json")
    )
    manifest_ids = {
        document_id
        for record in manifest["records"]
        for document_id in record["document_ids"]
    }

    assert {document.document_id for document in documents} == manifest_ids
    assert all(
        CandidateDocument.from_dict(document.to_dict()) == document
        for document in documents
    )
    assert all(
        datetime.fromisoformat(document.publication_timestamp).tzinfo
        is not None
        for document in documents
    )
    assert all(document.source_category for document in documents)


def test_corpus_contains_explicit_pit_control_fixtures() -> None:
    documents = load_corpus()
    by_id = {document.document_id: document for document in documents}

    assert (
        by_id["fed-2009-03-03-bernanke"].timestamp_status
        == "conservative_date_only"
    )
    assert (
        by_id["ap-2024-01-05-market-update-uncertain"].availability_status
        == "content_version_uncertain"
    )
    duplicate = by_id["reuters-2024-01-05-wall-street-duplicate"]
    canonical = by_id["reuters-2024-01-05-wall-street"]
    assert duplicate.content_sha256 == canonical.content_sha256
    assert duplicate.url_or_source_id == canonical.url_or_source_id
