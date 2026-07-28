"""Validate a named, versioned classifier response against archived retrieval.

This module intentionally does not call a model API.  It defines the boundary
that either a cached response or a future live invocation must satisfy before
the MVP may emit directional evidence claims.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from src.evidence.provider_contracts import EvidenceProviderResult
from src.mvp.contracts import EvidenceSnapshot
from src.utils.io import read_json


CLASSIFIER_SCHEMA_VERSION = "mvp-evidence-classifier-v1"
PROMPT_VERSION = "momentum-evidence-classifier-v2"
SYSTEM_PROMPT = """\
Classify only the supplied archived passages relative to an elevated
Daniel-Moskowitz-inspired momentum panic state.

Allowed classifications are supporting, contradicting, contextual, and
irrelevant. Use only a mechanism supplied for that document. Copy every
relevant extracted passage exactly from the archived passage. Classify each
document exactly once. Irrelevant items use mechanism "other", a null passage,
and an exclusion reason. Do not calculate, infer, copy, or modify any risk
probability. Return only the response-schema JSON.
"""
CLASSIFIER_MODES = frozenset(
    {"deterministic_cached_response", "live_model_response"}
)
CLASSIFICATIONS = frozenset(
    {"supporting", "contradicting", "contextual", "irrelevant"}
)
PLACEHOLDER_MODEL_IDENTIFIERS = frozenset(
    {"unknown", "unspecified", "codex-session-model-unspecified"}
)

ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "as_of_date",
        "timestamp_cutoff",
        "retrieval_sha256",
        "classifier_input_sha256",
        "prompt_version",
        "model_identifier",
        "classifier_mode",
        "temperature",
        "items",
    }
)
ITEM_FIELDS = frozenset(
    {
        "document_id",
        "classification",
        "mechanism",
        "extracted_passage",
        "confidence",
        "rationale",
        "exclusion_reason",
    }
)


def _sha256(payload: object) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_classifier_input(
    retrieval: EvidenceProviderResult,
) -> dict[str, object]:
    """Build the bounded input identified by the approved prompt version."""

    if retrieval.status != "available" or not retrieval.documents:
        raise ValueError("classifier input requires a non-empty retrieval")
    return {
        "prompt_version": PROMPT_VERSION,
        "system_prompt": SYSTEM_PROMPT,
        "task_context": {
            "as_of_date": retrieval.as_of_date,
            "timestamp_cutoff": retrieval.timestamp_cutoff,
            "primary_state": "panic_elevated",
            "risk_probability_supplied": False,
        },
        "candidate_documents": [
            {
                "document_id": item.document.document_id,
                "title": item.document.title,
                "source": item.document.source,
                "publication_timestamp": (
                    item.document.publication_timestamp
                ),
                "discovery_timestamp": item.document.discovery_timestamp,
                "availability_timestamp": (
                    item.document.availability_timestamp
                ),
                "content_version_timestamp": (
                    item.document.content_version_timestamp
                ),
                "url": item.document.url,
                "passage": item.document.passage,
                "allowed_mechanisms": list(item.matched_mechanisms),
            }
            for item in retrieval.documents
        ],
    }


def classifier_input_sha256(retrieval: EvidenceProviderResult) -> str:
    """Hash the immutable prompt and bounded candidate payload."""

    return _sha256(build_classifier_input(retrieval))


def _exact_fields(
    payload: Mapping[str, Any],
    expected: frozenset[str],
    *,
    context: str,
) -> None:
    actual = set(payload)
    if actual != expected:
        raise ValueError(
            f"{context} fields differ; "
            f"missing={sorted(expected.difference(actual))}, "
            f"extra={sorted(actual.difference(expected))}"
        )


def _confidence(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("classifier confidence must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("classifier confidence must be numeric") from exc
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        raise ValueError("classifier confidence must be in [0, 1]")
    return parsed


def validate_classifier_response(
    *,
    retrieval: EvidenceProviderResult,
    response_path: Path,
) -> EvidenceSnapshot:
    """Ground a classifier response or reject it without partial output."""

    if retrieval.status != "available" or not retrieval.documents:
        raise ValueError("classifier requires a non-empty available retrieval")
    payload = read_json(response_path)
    if not isinstance(payload, Mapping):
        raise ValueError("classifier response root must be an object")
    _exact_fields(payload, ROOT_FIELDS, context="classifier response root")
    if payload["schema_version"] != CLASSIFIER_SCHEMA_VERSION:
        raise ValueError("unsupported classifier response schema")
    if payload["as_of_date"] != retrieval.as_of_date:
        raise ValueError("classifier response as_of_date does not match retrieval")
    if payload["timestamp_cutoff"] != retrieval.timestamp_cutoff:
        raise ValueError("classifier timestamp_cutoff does not match retrieval")
    if payload["retrieval_sha256"] != retrieval.retrieval_sha256:
        raise ValueError("classifier response is stale for this retrieval")
    if payload["prompt_version"] != PROMPT_VERSION:
        raise ValueError("classifier response prompt version is not approved")
    input_sha256 = classifier_input_sha256(retrieval)
    if payload["classifier_input_sha256"] != input_sha256:
        raise ValueError("classifier response does not match the approved input")

    model_identifier = str(payload["model_identifier"]).strip()
    if (
        not model_identifier
        or model_identifier.lower() in PLACEHOLDER_MODEL_IDENTIFIERS
        or not any(character.isdigit() for character in model_identifier)
    ):
        raise ValueError(
            "classifier response requires an explicit versioned model identifier"
        )
    classifier_mode = str(payload["classifier_mode"])
    if classifier_mode not in CLASSIFIER_MODES:
        raise ValueError("unsupported classifier mode")
    temperature = payload["temperature"]
    if temperature is not None:
        if isinstance(temperature, bool):
            raise ValueError("temperature must be numeric or null")
        try:
            parsed_temperature = float(temperature)
        except (TypeError, ValueError) as exc:
            raise ValueError("temperature must be numeric or null") from exc
        if not math.isfinite(parsed_temperature) or parsed_temperature < 0:
            raise ValueError("temperature must be finite and non-negative")

    items = payload["items"]
    if not isinstance(items, list):
        raise ValueError("classifier items must be a list")
    retrieved = {
        item.document.document_id: item for item in retrieval.documents
    }
    if len(items) != len(retrieved):
        raise ValueError("classifier must return exactly one item per document")

    seen: set[str] = set()
    counts = {"supporting": 0, "contradicting": 0, "contextual": 0}
    citations: list[dict[str, object]] = []
    for index, raw_item in enumerate(items):
        if not isinstance(raw_item, Mapping):
            raise ValueError(f"classifier item {index} must be an object")
        _exact_fields(
            raw_item,
            ITEM_FIELDS,
            context=f"classifier item {index}",
        )
        document_id = str(raw_item["document_id"])
        if document_id in seen:
            raise ValueError(f"duplicate classifier item: {document_id}")
        seen.add(document_id)
        if document_id not in retrieved:
            raise ValueError(f"classifier returned unknown document: {document_id}")

        classification = str(raw_item["classification"])
        if classification not in CLASSIFICATIONS:
            raise ValueError(f"unsupported classification: {classification}")
        confidence = _confidence(raw_item["confidence"])
        rationale = str(raw_item["rationale"]).strip()
        if not rationale:
            raise ValueError("classifier rationale cannot be blank")
        mechanism = str(raw_item["mechanism"])
        passage = raw_item["extracted_passage"]
        exclusion_reason = raw_item["exclusion_reason"]
        source_item = retrieved[document_id]
        source = source_item.document

        if classification == "irrelevant":
            if mechanism != "other" or passage is not None:
                raise ValueError(
                    "irrelevant items require mechanism=other and null passage"
                )
            if not str(exclusion_reason or "").strip():
                raise ValueError("irrelevant items require an exclusion reason")
            continue

        if mechanism not in source_item.matched_mechanisms:
            raise ValueError(
                f"classifier mechanism was not retrieved for {document_id}"
            )
        if not isinstance(passage, str) or not passage.strip():
            raise ValueError("relevant classifier items require a passage")
        if passage not in source.passage:
            raise ValueError(
                f"classifier passage is not grounded in archive: {document_id}"
            )
        if exclusion_reason is not None:
            raise ValueError("relevant classifier items cannot have exclusion_reason")
        counts[classification] += 1
        citations.append(
            {
                "document_id": document_id,
                "classification": classification,
                "mechanism": mechanism,
                "confidence": confidence,
                "source": source.source,
                "title": source.title,
                "publication_timestamp": source.publication_timestamp,
                "discovery_timestamp": source.discovery_timestamp,
                "availability_timestamp": source.availability_timestamp,
                "content_version_timestamp": source.content_version_timestamp,
                "citation_url": source.url,
                "archive_source": source.archive_source,
                "archive_locator": source.archive_locator,
                "content_sha256": source.content_sha256,
                "extracted_passage": passage,
                "rationale": rationale,
            }
        )
    if seen != set(retrieved):
        raise ValueError("classifier response omitted retrieved documents")

    return EvidenceSnapshot(
        as_of_date=retrieval.as_of_date,
        status="available",
        mode=retrieval.mode,
        provider_name=retrieval.provider_name,
        corpus_version=retrieval.corpus_version,
        corpus_sha256=retrieval.corpus_sha256,
        request_sha256=retrieval.request_sha256,
        retrieved_documents=len(retrieval.documents),
        retrieved_document_ids=tuple(
            item.document.document_id for item in retrieval.documents
        ),
        excluded_documents=len(retrieval.exclusions),
        exclusions=tuple(
            {
                "document_id": item.document_id,
                "reason": item.reason,
                "detail": item.detail,
            }
            for item in retrieval.exclusions
        ),
        retrieval_sha256=retrieval.retrieval_sha256,
        classifier_input_sha256=input_sha256,
        prompt_version=str(payload["prompt_version"]),
        model_identifier=model_identifier,
        classifier_mode=classifier_mode,
        supporting_items=counts["supporting"],
        contradicting_items=counts["contradicting"],
        contextual_items=counts["contextual"],
        citations=tuple(citations),
        detail=(
            "Strict point-in-time archive retrieval with a versioned classifier "
            "response. Every emitted passage was matched to archived content; "
            "evidence remains informational and cannot change primary risk."
        ),
    )
