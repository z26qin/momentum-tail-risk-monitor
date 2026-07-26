"""Validate cached AI classifications and evaluate them offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.evidence.classification_validation import (
    validate_and_build_evidence_items,
)
from src.evidence.prompts import build_classifier_input
from src.monitoring.contracts import (
    EVIDENCE_CLASSIFICATIONS,
    EVIDENCE_ITEM_MECHANISMS,
    ClassificationResult,
    RetrievalRequest,
    RetrievalResult,
    RiskState,
    SCHEMA_VERSION,
)
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    atomic_write_bytes,
    read_json,
    sha256_file,
    write_json,
)


DEFAULT_LABELS_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "evaluation"
    / "evidence_labels_v1.json"
)
EVALUATION_COLUMNS = (
    "as_of_date",
    "document_id",
    "source",
    "publication_timestamp",
    "timestamp_valid",
    "citation_complete",
    "predicted_relevant",
    "review_relevant",
    "relevance_match",
    "predicted_classification",
    "review_classification",
    "classification_match",
    "predicted_mechanism",
    "review_mechanism",
    "mechanism_match",
    "predicted_specificity",
    "review_specificity",
    "specificity_match",
    "confidence",
    "classification_rationale",
    "reference_label_provenance",
    "review_note",
)


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_classification_result(
    *,
    risk_state: RiskState,
    request: RetrievalRequest,
    retrieval_result: RetrievalResult,
    response: Mapping[str, Any],
    risk_state_sha256: str,
    retrieval_request_sha256: str,
    retrieval_result_sha256: str,
) -> ClassificationResult:
    """Create one persisted result only after all grounding checks pass."""

    if not (
        risk_state.as_of_date
        == request.as_of_date
        == retrieval_result.as_of_date
    ):
        raise ValueError("Classifier inputs must share an as-of date")
    if not (
        risk_state.as_of_timestamp
        == request.timestamp_cutoff
        == retrieval_result.timestamp_cutoff
    ):
        raise ValueError("Classifier inputs must share a timestamp cutoff")
    if request.risk_state_sha256 != risk_state_sha256:
        raise ValueError("Retrieval request risk-state hash does not match")
    if retrieval_result.request_sha256 != retrieval_request_sha256:
        raise ValueError("Retrieval result request hash does not match")

    classifier_input = build_classifier_input(
        risk_state=risk_state,
        request=request,
        retrieval_result=retrieval_result,
    )
    items = validate_and_build_evidence_items(
        response=response,
        risk_state=risk_state,
        request=request,
        retrieval_result=retrieval_result,
    )
    specificities = {item.specificity for item in items}
    coverage_notes: list[str] = []
    if "momentum_specific" not in specificities:
        coverage_notes.append(
            "No cached passage explicitly identifies the momentum factor or "
            "momentum portfolios."
        )
    if "mechanism_proxy" in specificities:
        coverage_notes.append(
            "Mechanism-proxy items describe liquidity, policy, or rotation "
            "conditions without establishing a momentum-specific link."
        )
    if "generic_context" in specificities:
        coverage_notes.append(
            "Generic-context items should inform market-regime review but "
            "should not be presented as direct momentum evidence."
        )
    return ClassificationResult(
        schema_version=SCHEMA_VERSION,
        as_of_date=risk_state.as_of_date,
        timestamp_cutoff=risk_state.as_of_timestamp,
        prompt_version=str(response["prompt_version"]),
        model_identifier=str(response["model_identifier"]),
        classifier_mode=str(response["classifier_mode"]),
        temperature=(
            None
            if response["temperature"] is None
            else float(response["temperature"])
        ),
        risk_state_sha256=risk_state_sha256,
        retrieval_request_sha256=retrieval_request_sha256,
        retrieval_result_sha256=retrieval_result_sha256,
        classifier_input_sha256=_payload_sha256(classifier_input),
        items=items,
        exclusions=(),
        schema_validation_passed=True,
        coverage_notes=tuple(coverage_notes),
        data_quality_flags=(
            "classification_is_codex_assisted_cached_output",
            "exact_model_build_and_sampling_controls_are_not_exposed",
            "historical_passages_are_short_cached_paraphrases",
            "evidence_specificity_is_explicit",
            "classification_does_not_change_risk_probability",
            "live_model_api_not_required_for_replay",
        ),
    )


def run_classifier(
    *,
    risk_state_path: Path,
    request_path: Path,
    retrieval_result_path: Path,
    response_fixture_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[ClassificationResult, Path]:
    """Replay classification from saved deterministic and AI artifacts."""

    risk_state = RiskState.from_dict(read_json(risk_state_path))
    request = RetrievalRequest.from_dict(read_json(request_path))
    retrieval_result = RetrievalResult.from_dict(
        read_json(retrieval_result_path)
    )
    response = read_json(response_fixture_path)
    if not isinstance(response, Mapping):
        raise ValueError("Classifier response fixture must be an object")
    result = build_classification_result(
        risk_state=risk_state,
        request=request,
        retrieval_result=retrieval_result,
        response=response,
        risk_state_sha256=sha256_file(risk_state_path),
        retrieval_request_sha256=sha256_file(request_path),
        retrieval_result_sha256=sha256_file(retrieval_result_path),
    )
    path = (
        output_dir
        / "debug"
        / f"classified_evidence_{result.as_of_date}.json"
    )
    write_json(path, result.to_dict())
    return result, path


def _validated_review_labels(
    payload: Any,
) -> dict[tuple[str, str], Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        raise ValueError("Evaluation labels root must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Evaluation labels schema_version is unsupported")
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("Evaluation records must be a non-empty list")

    expected = {
        "as_of_date",
        "document_id",
        "review_relevant",
        "review_classification",
        "review_mechanism",
        "review_specificity",
        "review_note",
    }
    labels: dict[tuple[str, str], Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping) or set(record) != expected:
            raise ValueError("Evaluation label fields are malformed")
        key = (record["as_of_date"], record["document_id"])
        if key in labels:
            raise ValueError(f"Duplicate evaluation label: {key}")
        if not isinstance(record["review_relevant"], bool):
            raise ValueError("review_relevant must be boolean")
        if (
            record["review_classification"]
            not in EVIDENCE_CLASSIFICATIONS
        ):
            raise ValueError("Unsupported review classification")
        if record["review_mechanism"] not in EVIDENCE_ITEM_MECHANISMS:
            raise ValueError("Unsupported review mechanism")
        if record["review_specificity"] not in {
            "momentum_specific",
            "mechanism_proxy",
            "generic_context",
            "not_applicable",
        }:
            raise ValueError("review_specificity is unsupported")
        if not str(record["review_note"]).strip():
            raise ValueError("review_note cannot be blank")
        labels[key] = record
    return labels


def evaluate_classifications(
    *,
    results: Sequence[ClassificationResult],
    labels_payload: Any,
) -> list[dict[str, Any]]:
    """Compare cached classifications with a small inspectable review set."""

    labels = _validated_review_labels(labels_payload)
    result_keys = {
        (result.as_of_date, item.document_id)
        for result in results
        for item in result.items
    }
    if result_keys != set(labels):
        raise ValueError(
            "Evaluation labels must cover every classified document exactly"
        )
    rows: list[dict[str, Any]] = []
    for result in sorted(results, key=lambda value: value.as_of_date):
        cutoff = datetime.fromisoformat(
            result.timestamp_cutoff
        ).astimezone(timezone.utc)
        for item in result.items:
            review = labels[(result.as_of_date, item.document_id)]
            publication = datetime.fromisoformat(
                item.publication_timestamp
            ).astimezone(timezone.utc)
            predicted_relevant = item.classification != "irrelevant"
            rows.append(
                {
                    "as_of_date": result.as_of_date,
                    "document_id": item.document_id,
                    "source": item.source,
                    "publication_timestamp": item.publication_timestamp,
                    "timestamp_valid": publication <= cutoff,
                    "citation_complete": (
                        item.citation_valid
                        and (
                            item.classification == "irrelevant"
                            or item.extracted_passage is not None
                        )
                    ),
                    "predicted_relevant": predicted_relevant,
                    "review_relevant": review["review_relevant"],
                    "relevance_match": (
                        predicted_relevant == review["review_relevant"]
                    ),
                    "predicted_classification": item.classification,
                    "review_classification": (
                        review["review_classification"]
                    ),
                    "classification_match": (
                        item.classification
                        == review["review_classification"]
                    ),
                    "predicted_mechanism": item.mechanism,
                    "review_mechanism": review["review_mechanism"],
                    "mechanism_match": (
                        item.mechanism == review["review_mechanism"]
                    ),
                    "predicted_specificity": item.specificity,
                    "review_specificity": (
                        review["review_specificity"]
                    ),
                    "specificity_match": (
                        item.specificity
                        == review["review_specificity"]
                    ),
                    "confidence": item.confidence,
                    "classification_rationale": (
                        item.classification_rationale
                    ),
                    "reference_label_provenance": (
                        "developer_review_not_independent_ground_truth"
                    ),
                    "review_note": review["review_note"],
                }
            )
    return rows


def write_evaluation_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    """Write the deterministic manual-review comparison."""

    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EVALUATION_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_bytes(path, buffer.getvalue().encode("utf-8"))


def run_evaluation(
    *,
    classified_paths: Sequence[Path],
    labels_path: Path = DEFAULT_LABELS_PATH,
    output_path: Path = DEFAULT_OUTPUT_DIR / "retrieval_evaluation.csv",
) -> tuple[list[dict[str, Any]], Path]:
    results = [
        ClassificationResult.from_dict(read_json(path))
        for path in classified_paths
    ]
    rows = evaluate_classifications(
        results=results,
        labels_payload=read_json(labels_path),
    )
    write_evaluation_csv(output_path, rows)
    return rows, output_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    classify = subparsers.add_parser("classify")
    classify.add_argument("--risk-state", type=Path, required=True)
    classify.add_argument("--request", type=Path, required=True)
    classify.add_argument("--retrieval-result", type=Path, required=True)
    classify.add_argument("--response-fixture", type=Path, required=True)
    classify.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)

    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument(
        "--classified",
        type=Path,
        action="append",
        required=True,
    )
    evaluate.add_argument(
        "--labels",
        type=Path,
        default=DEFAULT_LABELS_PATH,
    )
    evaluate.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "retrieval_evaluation.csv",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.command == "classify":
        result, path = run_classifier(
            risk_state_path=args.risk_state,
            request_path=args.request,
            retrieval_result_path=args.retrieval_result,
            response_fixture_path=args.response_fixture,
            output_dir=args.output_dir,
        )
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        print(f"Wrote {path}")
        return

    rows, path = run_evaluation(
        classified_paths=args.classified,
        labels_path=args.labels,
        output_path=args.output,
    )
    metrics = {
        column: sum(bool(row[column]) for row in rows) / len(rows)
        for column in (
            "timestamp_valid",
            "citation_complete",
            "relevance_match",
            "classification_match",
            "mechanism_match",
            "specificity_match",
        )
    }
    print(json.dumps(metrics, indent=2, sort_keys=True))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
