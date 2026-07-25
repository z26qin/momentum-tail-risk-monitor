"""Validate and adapt the compact cached evidence corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from src.monitoring.contracts import CandidateDocument, SCHEMA_VERSION
from src.utils.io import REPO_ROOT, read_json


DEFAULT_CORPUS_PATH = (
    REPO_ROOT / "data" / "corpus" / "momentum_evidence_corpus_v1.json"
)
CORPUS_SCHEMA_VERSION = "1.0"
MAX_PASSAGE_CHARACTERS = 800


def content_sha256(record: Mapping[str, Any]) -> str:
    """Hash the immutable content fields used for duplicate detection."""

    canonical = {
        "snippet_or_passage": record["snippet_or_passage"].strip(),
        "title": record["title"].strip(),
        "url_or_source_id": record["url_or_source_id"].strip(),
    }
    payload = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _adapt_document(record: Mapping[str, Any]) -> CandidateDocument:
    required = {
        "document_id",
        "title",
        "source",
        "source_category",
        "publication_timestamp",
        "timestamp_status",
        "availability_status",
        "url_or_source_id",
        "snippet_or_passage",
        "raw_metadata",
    }
    missing = required.difference(record)
    if missing:
        raise ValueError(
            f"Corpus record is missing fields: {sorted(missing)}"
        )
    passage = str(record["snippet_or_passage"])
    if len(passage) > MAX_PASSAGE_CHARACTERS:
        raise ValueError(
            f"Corpus passage exceeds {MAX_PASSAGE_CHARACTERS} characters: "
            f"{record['document_id']}"
        )
    return CandidateDocument(
        schema_version=SCHEMA_VERSION,
        document_id=str(record["document_id"]),
        title=str(record["title"]),
        source=str(record["source"]),
        source_category=str(record["source_category"]),
        publication_timestamp=str(record["publication_timestamp"]),
        timestamp_status=str(record["timestamp_status"]),
        availability_status=str(record["availability_status"]),
        url_or_source_id=str(record["url_or_source_id"]),
        snippet_or_passage=passage,
        retrieval_score=0.0,
        matched_query_ids=(),
        content_sha256=content_sha256(record),
        raw_metadata=dict(record["raw_metadata"]),
    )


def load_corpus(path: Path = DEFAULT_CORPUS_PATH) -> tuple[CandidateDocument, ...]:
    """Load a versioned offline corpus and fail on malformed records."""

    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError("Corpus root must be a JSON object")
    if payload.get("schema_version") != CORPUS_SCHEMA_VERSION:
        raise ValueError(
            f"Corpus schema_version must equal {CORPUS_SCHEMA_VERSION}"
        )
    if not str(payload.get("corpus_version", "")).strip():
        raise ValueError("Corpus version cannot be empty")
    records = payload.get("documents")
    if not isinstance(records, list) or not records:
        raise ValueError("Corpus documents must be a non-empty list")
    documents = tuple(_adapt_document(record) for record in records)
    document_ids = [document.document_id for document in documents]
    if len(document_ids) != len(set(document_ids)):
        raise ValueError("Corpus document IDs must be unique")
    return documents


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    documents = load_corpus(args.corpus)
    summary = {
        "corpus_path": str(args.corpus),
        "document_count": len(documents),
        "source_categories": sorted(
            {document.source_category for document in documents}
        ),
        "timestamp_statuses": sorted(
            {document.timestamp_status for document in documents}
        ),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
