"""Strict schema loader for historical point-in-time evidence corpora."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from src.evidence.provider_contracts import (
    ARCHIVE_SCHEMA_VERSION,
    SELECTION_METHODS,
    ArchivedDocument,
)
from src.utils.io import read_json, sha256_file


SELECTION_QUERY_VERSION = "momentum-archive-query-v1"
SELECTION_QUERY_FIELDS = frozenset(
    {
        "query_version",
        "terms",
        "language",
        "start_timestamp",
        "end_timestamp",
    }
)


def _aware(value: object, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a UTC offset")
    return parsed


def archived_content_sha256(record: Mapping[str, Any]) -> str:
    """Hash the content identity used by retrieval and duplicate checks."""

    canonical = {
        "title": str(record["title"]).strip(),
        "url": str(record["url"]).strip(),
        "passage": str(record["passage"]).strip(),
        "content_version_timestamp": str(record["content_version_timestamp"]),
    }
    payload = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ArchivedCorpus:
    corpus_version: str
    selection_method: str
    selection_query: dict[str, Any]
    archive_inventory: str
    documents: tuple[ArchivedDocument, ...]
    path: Path
    sha256: str


def load_archived_corpus(path: Path) -> ArchivedCorpus:
    """Load a strict corpus and reject manual or unproven selection."""

    payload = read_json(path)
    if not isinstance(payload, Mapping):
        raise ValueError("archived corpus root must be an object")
    expected = {
        "schema_version",
        "corpus_version",
        "selection_method",
        "selection_query",
        "archive_inventory",
        "documents",
    }
    if set(payload) != expected:
        raise ValueError(
            "archived corpus root fields differ; "
            f"missing={sorted(expected.difference(payload))}, "
            f"extra={sorted(set(payload).difference(expected))}"
        )
    if payload["schema_version"] != ARCHIVE_SCHEMA_VERSION:
        raise ValueError("unsupported archived corpus schema")
    if payload["selection_method"] not in SELECTION_METHODS:
        raise ValueError(
            "selection_method must identify a deterministic archive inventory"
        )
    if not isinstance(payload["selection_query"], Mapping):
        raise ValueError("selection_query must be an object")
    selection_query = payload["selection_query"]
    if set(selection_query) != SELECTION_QUERY_FIELDS:
        raise ValueError("selection_query fields differ from the strict schema")
    if selection_query["query_version"] != SELECTION_QUERY_VERSION:
        raise ValueError("unsupported archive selection query version")
    terms = selection_query["terms"]
    normalized_terms = [
        term.strip().lower() for term in terms if isinstance(term, str)
    ] if isinstance(terms, list) else []
    if (
        not isinstance(terms, list)
        or not terms
        or any(not isinstance(term, str) or not term.strip() for term in terms)
        or len(normalized_terms) != len(set(normalized_terms))
    ):
        raise ValueError("selection_query terms must be unique non-empty strings")
    if (
        not isinstance(selection_query["language"], str)
        or not selection_query["language"].strip()
    ):
        raise ValueError("selection_query language cannot be blank")
    selection_start = _aware(
        selection_query["start_timestamp"],
        "selection_query.start_timestamp",
    )
    selection_end = _aware(
        selection_query["end_timestamp"],
        "selection_query.end_timestamp",
    )
    if selection_start > selection_end:
        raise ValueError("selection_query start_timestamp exceeds end_timestamp")
    if (
        not isinstance(payload["corpus_version"], str)
        or not payload["corpus_version"].strip()
    ):
        raise ValueError("corpus_version cannot be blank")
    if (
        not isinstance(payload["archive_inventory"], str)
        or not payload["archive_inventory"].strip()
    ):
        raise ValueError("archive_inventory cannot be blank")
    records = payload["documents"]
    if not isinstance(records, list) or not records:
        raise ValueError("archived corpus documents must be non-empty")

    documents: list[ArchivedDocument] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("every archived document must be an object")
        document_fields = {field.name for field in fields(ArchivedDocument)}
        if set(record) != document_fields:
            raise ValueError(
                f"archived document fields differ: {record.get('document_id')}"
            )
        expected_hash = archived_content_sha256(record)
        if record.get("content_sha256") != expected_hash:
            raise ValueError(
                f"content hash mismatch: {record.get('document_id')}"
            )
        documents.append(ArchivedDocument(**dict(record)))
    ids = [document.document_id for document in documents]
    if len(ids) != len(set(ids)):
        raise ValueError("archived document IDs must be unique")
    for document in documents:
        discovery = _aware(
            document.discovery_timestamp,
            f"{document.document_id}.discovery_timestamp",
        )
        if not selection_start <= discovery <= selection_end:
            raise ValueError(
                f"document discovery is outside selection window: "
                f"{document.document_id}"
            )

    return ArchivedCorpus(
        corpus_version=str(payload["corpus_version"]),
        selection_method=str(payload["selection_method"]),
        selection_query=dict(payload["selection_query"]),
        archive_inventory=str(payload["archive_inventory"]),
        documents=tuple(documents),
        path=path,
        sha256=sha256_file(path),
    )
