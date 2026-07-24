"""Deterministic grounding checks for cached classifier responses."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping

from src.evidence.prompts import (
    CLASSIFIER_MODE,
    PROMPT_VERSION,
    RESPONSE_FIELDS,
    RESPONSE_ITEM_FIELDS,
)
from src.monitoring.contracts import (
    EVIDENCE_CLASSIFICATIONS,
    EVIDENCE_MECHANISMS,
    EVIDENCE_SPECIFICITIES,
    CandidateDocument,
    EvidenceItem,
    RetrievalRequest,
    RetrievalResult,
    RiskState,
    SCHEMA_VERSION,
)


def _require_exact_fields(
    payload: Mapping[str, Any],
    expected: frozenset[str],
    description: str,
) -> None:
    actual = set(payload)
    missing = expected.difference(actual)
    extra = actual.difference(expected)
    if missing or extra:
        raise ValueError(
            f"{description} fields differ; missing={sorted(missing)}, "
            f"extra={sorted(extra)}"
        )


def _allowed_drivers(
    request: RetrievalRequest,
) -> dict[str, frozenset[str]]:
    drivers: dict[str, set[str]] = {}
    for query in request.queries:
        drivers.setdefault(query.mechanism, set()).update(
            query.related_drivers
        )
    return {
        mechanism: frozenset(values)
        for mechanism, values in drivers.items()
    }


def _validate_response_header(
    response: Mapping[str, Any],
    *,
    risk_state: RiskState,
) -> None:
    _require_exact_fields(response, RESPONSE_FIELDS, "Classifier response")
    if response["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Classifier response schema_version is unsupported")
    if response["as_of_date"] != risk_state.as_of_date:
        raise ValueError("Classifier response as_of_date does not match state")
    if response["prompt_version"] != PROMPT_VERSION:
        raise ValueError("Classifier response prompt_version is unsupported")
    if response["classifier_mode"] != CLASSIFIER_MODE:
        raise ValueError("Classifier response mode is unsupported")
    if not str(response["model_identifier"]).strip():
        raise ValueError("Classifier response model_identifier is blank")
    temperature = response["temperature"]
    if temperature is not None:
        if (
            isinstance(temperature, bool)
            or not math.isfinite(float(temperature))
            or float(temperature) < 0.0
        ):
            raise ValueError("Classifier response temperature is invalid")
    if not isinstance(response["items"], list):
        raise ValueError("Classifier response items must be a list")


def _validate_non_irrelevant(
    item: Mapping[str, Any],
    *,
    document: CandidateDocument,
    drivers_by_mechanism: Mapping[str, frozenset[str]],
) -> None:
    mechanism = item["mechanism"]
    if mechanism not in EVIDENCE_MECHANISMS:
        raise ValueError(
            f"Unsupported mechanism for {document.document_id}: {mechanism}"
        )
    if mechanism not in drivers_by_mechanism:
        raise ValueError(
            f"Mechanism was not requested for {document.document_id}: "
            f"{mechanism}"
        )
    related_driver = item["related_driver"]
    if related_driver not in drivers_by_mechanism[mechanism]:
        raise ValueError(
            f"Driver {related_driver!r} is not allowed for mechanism "
            f"{mechanism!r}"
        )
    passage = item["extracted_passage"]
    if not isinstance(passage, str) or not passage.strip():
        raise ValueError(
            f"Non-irrelevant item lacks a passage: {document.document_id}"
        )
    if passage not in document.snippet_or_passage:
        raise ValueError(
            f"Extracted passage is not grounded: {document.document_id}"
        )
    if item["exclusion_reason"] is not None:
        raise ValueError(
            f"Non-irrelevant item has an exclusion: {document.document_id}"
        )
    if item["specificity"] == "momentum_specific" and mechanism == (
        "generic risk-off or risk-on"
    ):
        raise ValueError(
            "Generic market context cannot be marked momentum-specific"
        )
    if (
        item["specificity"] == "generic_context"
        and mechanism != "generic risk-off or risk-on"
    ):
        raise ValueError(
            "Generic context must use the generic market mechanism"
        )


def _validate_irrelevant(
    item: Mapping[str, Any],
    *,
    document: CandidateDocument,
) -> None:
    if item["mechanism"] != "other":
        raise ValueError(
            f"Irrelevant item must use other: {document.document_id}"
        )
    if item["related_driver"] is not None:
        raise ValueError(
            f"Irrelevant item cannot name a driver: {document.document_id}"
        )
    if item["extracted_passage"] is not None:
        raise ValueError(
            f"Irrelevant item cannot extract a passage: "
            f"{document.document_id}"
        )
    if not isinstance(item["exclusion_reason"], str) or not item[
        "exclusion_reason"
    ].strip():
        raise ValueError(
            f"Irrelevant item needs an exclusion reason: "
            f"{document.document_id}"
        )
    if item["specificity"] != "not_applicable":
        raise ValueError(
            f"Irrelevant item requires not_applicable specificity: "
            f"{document.document_id}"
        )


def _citation_is_valid(
    document: CandidateDocument,
    *,
    cutoff: datetime,
) -> bool:
    publication = datetime.fromisoformat(
        document.publication_timestamp
    ).astimezone(timezone.utc)
    return (
        publication <= cutoff
        and document.timestamp_status != "uncertain_content_version"
        and document.availability_status
        == "publicly_available_at_publication_timestamp"
    )


def validate_and_build_evidence_items(
    *,
    response: Mapping[str, Any],
    risk_state: RiskState,
    request: RetrievalRequest,
    retrieval_result: RetrievalResult,
) -> tuple[EvidenceItem, ...]:
    """Reject malformed or ungrounded output and return cited evidence."""

    _validate_response_header(response, risk_state=risk_state)
    candidates = {
        document.document_id: document
        for document in retrieval_result.documents
    }
    response_items = response["items"]
    response_ids = [item.get("document_id") for item in response_items]
    if len(response_ids) != len(set(response_ids)):
        raise ValueError("Classifier response contains duplicate document IDs")
    if set(response_ids) != set(candidates):
        raise ValueError(
            "Classifier response must classify every candidate exactly once"
        )

    drivers_by_mechanism = _allowed_drivers(request)
    cutoff = datetime.fromisoformat(
        retrieval_result.timestamp_cutoff
    ).astimezone(timezone.utc)
    built: list[EvidenceItem] = []
    for raw_item in response_items:
        if not isinstance(raw_item, Mapping):
            raise ValueError("Every classifier item must be an object")
        _require_exact_fields(
            raw_item,
            RESPONSE_ITEM_FIELDS,
            "Classifier item",
        )
        document = candidates[raw_item["document_id"]]
        classification = raw_item["classification"]
        if classification not in EVIDENCE_CLASSIFICATIONS:
            raise ValueError(
                f"Unsupported classification: {classification}"
            )
        confidence = raw_item["confidence"]
        if (
            isinstance(confidence, bool)
            or not math.isfinite(float(confidence))
            or not 0.0 <= float(confidence) <= 1.0
        ):
            raise ValueError(
                f"Invalid confidence for {document.document_id}"
            )
        if raw_item["specificity"] not in EVIDENCE_SPECIFICITIES:
            raise ValueError(
                f"specificity is invalid: {document.document_id}"
            )
        if not isinstance(
            raw_item["classification_rationale"],
            str,
        ) or not raw_item["classification_rationale"].strip():
            raise ValueError(
                f"classification_rationale is blank: "
                f"{document.document_id}"
            )
        if classification == "irrelevant":
            _validate_irrelevant(raw_item, document=document)
        else:
            _validate_non_irrelevant(
                raw_item,
                document=document,
                drivers_by_mechanism=drivers_by_mechanism,
            )

        citation_valid = _citation_is_valid(document, cutoff=cutoff)
        if classification == "supporting" and not citation_valid:
            raise ValueError(
                f"Supporting item lacks a valid citation: "
                f"{document.document_id}"
            )
        built.append(
            EvidenceItem(
                document_id=document.document_id,
                title=document.title,
                source=document.source,
                publication_timestamp=document.publication_timestamp,
                citation_url=document.url_or_source_id,
                classification=classification,
                mechanism=raw_item["mechanism"],
                related_driver=raw_item["related_driver"],
                extracted_passage=raw_item["extracted_passage"],
                confidence=float(confidence),
                specificity=raw_item["specificity"],
                classification_rationale=raw_item[
                    "classification_rationale"
                ],
                citation_valid=citation_valid,
                exclusion_reason=raw_item["exclusion_reason"],
            )
        )
    order = {
        document.document_id: index
        for index, document in enumerate(retrieval_result.documents)
    }
    return tuple(sorted(built, key=lambda item: order[item.document_id]))
