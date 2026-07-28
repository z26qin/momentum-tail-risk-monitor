"""Focused tests for the March 2020 human retrieval gold-set workflow."""

from __future__ import annotations

import copy
import csv
from pathlib import Path

import pandas as pd
import pytest

from src.evaluation.retrieval_gold import (
    ANNOTATION_CSV_PATH,
    ANNOTATION_FIELDS,
    ARCHIVED_CORPUS_PATH,
    CANDIDATE_PROTOCOL_PATH,
    CORPUS_MANIFEST_PATH,
    EVALUATION_NAME,
    RETRIEVAL_RESULTS_PATH,
    AnnotationValidationError,
    _canonical_sha256,
    _manifest_by_id,
    _objective_timestamp_status,
    _protocol_with_hash,
    _sample_candidate_rows,
    build_retrieval_results,
    candidate_protocol_payload,
    evaluate_annotations,
    read_annotations,
    validate_annotation_rows,
)
from src.evidence.mvp import build_evidence_snapshot
from src.risk.dm_engine import build_primary_assessment
from src.utils.io import read_json


def _completed(
    row: dict[str, str],
    *,
    timestamp: str = "valid",
    relevance: str = "0",
    mechanisms: str = "other",
    direction: str = "irrelevant",
    passage: str = "",
) -> dict[str, str]:
    completed = dict(row)
    completed.update(
        {
            "timestamp_validity": timestamp,
            "relevance_label": relevance,
            "mechanism_labels": mechanisms,
            "evidence_direction": direction,
            "supporting_passage": passage,
            "reviewer_rationale": "Human reviewer rationale for this test.",
            "reviewer_confidence": "high",
            "review_status": "completed",
        }
    )
    return completed


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ANNOTATION_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _queue_by_document() -> dict[str, dict[str, str]]:
    return {
        row["document_id"]: row
        for row in read_annotations(ANNOTATION_CSV_PATH)
    }


def test_candidate_protocol_serialization_is_deterministic() -> None:
    first = _protocol_with_hash(candidate_protocol_payload())
    second = _protocol_with_hash(candidate_protocol_payload())

    assert first == second
    assert first["protocol_hash"] == _canonical_sha256(
        {
            key: value
            for key, value in first.items()
            if key != "protocol_hash"
        }
    )
    assert first["evaluation_name"] == EVALUATION_NAME


def test_candidate_selection_is_stable_for_saved_seed() -> None:
    retrieval = read_json(RETRIEVAL_RESULTS_PATH)

    first = _sample_candidate_rows(retrieval)
    second = _sample_candidate_rows(retrieval)

    assert first == second
    assert len(first) == 45


def test_future_documents_are_marked_invalid() -> None:
    document = _manifest_by_id()[
        "fed-2020-03-23-monetary20200323b"
    ]

    assert (
        _objective_timestamp_status(
            document,
            "2020-03-18T16:00:00-04:00",
        )
        == "invalid_future"
    )


def test_uncertain_timestamps_are_excluded_from_strict_metrics(
    tmp_path: Path,
) -> None:
    queue = _queue_by_document()
    valid = _completed(
        queue["fed-2020-03-23-monetary20200323b"],
        relevance="2",
        mechanisms="policy_or_liquidity_support",
        direction="supporting",
        passage=queue[
            "fed-2020-03-23-monetary20200323b"
        ]["retrieved_passage"],
    )
    uncertain = _completed(
        queue["gdelt-cnbc-2020-03-19-short-sellers"],
        timestamp="uncertain",
    )
    annotations = tmp_path / "annotations.csv"
    _write_rows(annotations, [valid, uncertain])

    result = evaluate_annotations(
        annotations_path=annotations,
        retrieval_results_path=RETRIEVAL_RESULTS_PATH,
        results_path=tmp_path / "results.json",
        report_path=tmp_path / "report.md",
    )

    assert result["status"] == "COMPLETE — HUMAN LABELS EVALUATED"
    assert result["strict_metric_rows"] == 1
    assert result["uncertain_rows_excluded"] == 1


def test_duplicate_annotation_ids_fail() -> None:
    row = _completed(read_annotations(ANNOTATION_CSV_PATH)[0])

    with pytest.raises(AnnotationValidationError, match="duplicate"):
        validate_annotation_rows(
            [row, copy.deepcopy(row)],
            manifest_by_id=_manifest_by_id(),
        )


def test_invalid_mechanism_labels_fail() -> None:
    row = _completed(
        read_annotations(ANNOTATION_CSV_PATH)[0],
        relevance="1",
        mechanisms="invented_mechanism",
        direction="contextual",
    )

    with pytest.raises(AnnotationValidationError, match="invalid mechanisms"):
        validate_annotation_rows([row], manifest_by_id=_manifest_by_id())


def test_relevance_two_requires_a_grounded_passage() -> None:
    row = _completed(
        read_annotations(ANNOTATION_CSV_PATH)[0],
        relevance="2",
        mechanisms="policy_or_liquidity_support",
        direction="supporting",
    )

    with pytest.raises(
        AnnotationValidationError,
        match="requires a grounded passage",
    ):
        validate_annotation_rows([row], manifest_by_id=_manifest_by_id())


def test_grounded_passage_must_be_an_exact_substring() -> None:
    row = _completed(
        read_annotations(ANNOTATION_CSV_PATH)[0],
        relevance="2",
        mechanisms="policy_or_liquidity_support",
        direction="supporting",
        passage="This sentence was invented by the test.",
    )

    with pytest.raises(
        AnnotationValidationError,
        match="exact substring",
    ):
        validate_annotation_rows([row], manifest_by_id=_manifest_by_id())


def test_irrelevant_rows_cannot_be_marked_supporting() -> None:
    row = _completed(
        read_annotations(ANNOTATION_CSV_PATH)[0],
        direction="supporting",
    )

    with pytest.raises(
        AnnotationValidationError,
        match="evidence_direction=irrelevant",
    ):
        validate_annotation_rows([row], manifest_by_id=_manifest_by_id())


def test_metrics_are_not_produced_before_human_labels_are_complete(
    tmp_path: Path,
) -> None:
    result = evaluate_annotations(
        annotations_path=ANNOTATION_CSV_PATH,
        retrieval_results_path=RETRIEVAL_RESULTS_PATH,
        results_path=tmp_path / "results.json",
        report_path=tmp_path / "report.md",
    )

    assert result["status"] == "AWAITING HUMAN ANNOTATION"
    assert all(
        value["status"] == "not_reported"
        for value in result["metrics"].values()
    )


def test_quiet_state_control_skips_retrieval() -> None:
    primary = build_primary_assessment(
        as_of_date=pd.Timestamp("2024-01-05"),
        horizon=20,
    )
    evidence = build_evidence_snapshot(
        primary=primary,
        provider_mode="archived",
        archived_corpus_path=ARCHIVED_CORPUS_PATH,
    )

    assert primary.elevated is False
    assert evidence.status == "skipped_quiet_state"
    assert evidence.retrieved_documents == 0


def test_retrieval_output_is_independent_of_human_gold_labels() -> None:
    manifest = read_json(CORPUS_MANIFEST_PATH)
    protocol = read_json(CANDIDATE_PROTOCOL_PATH)
    fake_human_label = {"relevance_label": 2}

    before = build_retrieval_results(manifest, protocol)
    fake_human_label["relevance_label"] = 0
    after = build_retrieval_results(manifest, protocol)

    assert before == after
    assert before["human_annotations_read"] is False
    assert before["retrieval_results_hash"] == after["retrieval_results_hash"]
