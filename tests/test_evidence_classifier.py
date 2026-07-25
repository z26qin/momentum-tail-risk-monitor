"""Offline replay and evaluation tests for evidence classification."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.evidence.classifier import (
    build_classification_result,
    evaluate_classifications,
    run_classifier,
)
from src.monitoring.contracts import (
    ClassificationResult,
    RetrievalRequest,
    RetrievalResult,
    RiskState,
)
from src.utils.io import read_json, sha256_file


DEBUG = Path("outputs/debug")
FIXTURES = Path("data/fixtures")
LABELS = Path("data/evaluation/evidence_labels_v1.json")


def _build(day: str) -> ClassificationResult:
    risk_path = DEBUG / f"risk_state_{day}.json"
    request_path = DEBUG / f"retrieval_request_{day}.json"
    retrieval_path = DEBUG / f"retrieved_documents_{day}.json"
    return build_classification_result(
        risk_state=RiskState.from_dict(read_json(risk_path)),
        request=RetrievalRequest.from_dict(read_json(request_path)),
        retrieval_result=RetrievalResult.from_dict(
            read_json(retrieval_path)
        ),
        response=read_json(
            FIXTURES / f"classifier_response_{day}.json"
        ),
        risk_state_sha256=sha256_file(risk_path),
        retrieval_request_sha256=sha256_file(request_path),
        retrieval_result_sha256=sha256_file(retrieval_path),
    )


@pytest.mark.parametrize("day", ["2009-03-06", "2024-01-05"])
def test_cached_classification_replays_and_round_trips(day: str) -> None:
    first = _build(day)
    second = _build(day)

    assert first == second
    assert first.schema_validation_passed
    assert len(first.items) == 8
    assert all(item.citation_valid for item in first.items)
    assert all(
        item.specificity != "momentum_specific"
        for item in first.items
    )
    assert all(item.classification_rationale for item in first.items)
    assert first.coverage_notes
    assert ClassificationResult.from_dict(first.to_dict()) == first


def test_classifier_cli_boundary_writes_only_valid_result(
    tmp_path: Path,
) -> None:
    day = "2009-03-06"
    result, path = run_classifier(
        risk_state_path=DEBUG / f"risk_state_{day}.json",
        request_path=DEBUG / f"retrieval_request_{day}.json",
        retrieval_result_path=(
            DEBUG / f"retrieved_documents_{day}.json"
        ),
        response_fixture_path=(
            FIXTURES / f"classifier_response_{day}.json"
        ),
        output_dir=tmp_path,
    )

    assert path == tmp_path / "debug" / f"classified_evidence_{day}.json"
    assert ClassificationResult.from_dict(read_json(path)) == result


def test_classifier_rejects_broken_provenance_hash() -> None:
    day = "2009-03-06"
    risk_path = DEBUG / f"risk_state_{day}.json"
    request_path = DEBUG / f"retrieval_request_{day}.json"
    retrieval_path = DEBUG / f"retrieved_documents_{day}.json"

    with pytest.raises(ValueError, match="risk-state hash"):
        build_classification_result(
            risk_state=RiskState.from_dict(read_json(risk_path)),
            request=RetrievalRequest.from_dict(read_json(request_path)),
            retrieval_result=RetrievalResult.from_dict(
                read_json(retrieval_path)
            ),
            response=read_json(
                FIXTURES / f"classifier_response_{day}.json"
            ),
            risk_state_sha256="0" * 64,
            retrieval_request_sha256=sha256_file(request_path),
            retrieval_result_sha256=sha256_file(retrieval_path),
        )


def test_manual_evaluation_is_complete_and_exposes_disagreement() -> None:
    rows = evaluate_classifications(
        results=[_build("2009-03-06"), _build("2024-01-05")],
        labels_payload=read_json(LABELS),
    )

    assert len(rows) == 16
    assert all(row["timestamp_valid"] for row in rows)
    assert all(row["citation_complete"] for row in rows)
    assert sum(row["relevance_match"] for row in rows) == 15
    assert sum(row["classification_match"] for row in rows) == 12
    assert sum(row["mechanism_match"] for row in rows) == 15
    assert sum(row["specificity_match"] for row in rows) == 15
    assert all(
        row["reference_label_provenance"]
        == "developer_review_not_independent_ground_truth"
        for row in rows
    )
