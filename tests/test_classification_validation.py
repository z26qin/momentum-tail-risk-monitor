"""Grounding and schema guardrails for evidence classification."""

from __future__ import annotations

import copy
import dataclasses
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.evidence.classification_validation import (
    validate_and_build_evidence_items,
)
from src.monitoring.contracts import (
    RetrievalRequest,
    RetrievalResult,
    RiskState,
)
from src.utils.io import read_json


DEBUG = Path("outputs/debug")
FIXTURES = Path("data/fixtures")


def _inputs(day: str = "2009-03-06"):
    risk_state = RiskState.from_dict(
        read_json(DEBUG / f"risk_state_{day}.json")
    )
    request = RetrievalRequest.from_dict(
        read_json(DEBUG / f"retrieval_request_{day}.json")
    )
    result = RetrievalResult.from_dict(
        read_json(DEBUG / f"retrieved_documents_{day}.json")
    )
    response = read_json(FIXTURES / f"classifier_response_{day}.json")
    return risk_state, request, result, response


def test_classifier_rejects_unknown_document_and_ungrounded_passage() -> None:
    risk_state, request, result, response = _inputs()
    unknown = copy.deepcopy(response)
    unknown["items"][0]["document_id"] = "invented-document"

    with pytest.raises(ValueError, match="every candidate exactly once"):
        validate_and_build_evidence_items(
            response=unknown,
            risk_state=risk_state,
            request=request,
            retrieval_result=result,
        )

    ungrounded = copy.deepcopy(response)
    ungrounded["items"][0]["extracted_passage"] = (
        "This sentence was not retrieved."
    )
    with pytest.raises(ValueError, match="not grounded"):
        validate_and_build_evidence_items(
            response=ungrounded,
            risk_state=risk_state,
            request=request,
            retrieval_result=result,
        )


def test_classifier_rejects_missing_passage_and_generic_specificity() -> None:
    risk_state, request, result, response = _inputs()
    missing = copy.deepcopy(response)
    missing["items"][0]["extracted_passage"] = None
    with pytest.raises(ValueError, match="lacks a passage"):
        validate_and_build_evidence_items(
            response=missing,
            risk_state=risk_state,
            request=request,
            retrieval_result=result,
        )

    generic = copy.deepcopy(response)
    generic["items"][2]["specificity"] = "momentum_specific"
    with pytest.raises(ValueError, match="cannot be marked"):
        validate_and_build_evidence_items(
            response=generic,
            risk_state=risk_state,
            request=request,
            retrieval_result=result,
        )


def test_supporting_evidence_requires_timestamp_valid_citation() -> None:
    risk_state, request, result, response = _inputs()
    document = result.documents[0]
    future_timestamp = (
        datetime.fromisoformat(result.timestamp_cutoff) + timedelta(days=1)
    ).isoformat()
    future_document = dataclasses.replace(
        document,
        publication_timestamp=future_timestamp,
    )
    future_result = dataclasses.replace(
        result,
        documents=(future_document, *result.documents[1:]),
    )

    with pytest.raises(ValueError, match="valid citation"):
        validate_and_build_evidence_items(
            response=response,
            risk_state=risk_state,
            request=request,
            retrieval_result=future_result,
        )


def test_classifier_rejects_extra_fields_and_invalid_driver() -> None:
    risk_state, request, result, response = _inputs()
    malformed = copy.deepcopy(response)
    malformed["items"][0]["invented_field"] = "value"
    with pytest.raises(ValueError, match="fields differ"):
        validate_and_build_evidence_items(
            response=malformed,
            risk_state=risk_state,
            request=request,
            retrieval_result=result,
        )

    invalid_driver = copy.deepcopy(response)
    invalid_driver["items"][0]["related_driver"] = "invented_feature"
    with pytest.raises(ValueError, match="not allowed"):
        validate_and_build_evidence_items(
            response=invalid_driver,
            risk_state=risk_state,
            request=request,
            retrieval_result=result,
        )
