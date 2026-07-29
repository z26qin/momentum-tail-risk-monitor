"""Focused contract tests for the deterministic Evidence Card adapter."""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pandas as pd
import pytest

from src.monitoring.scorecard import SCORECARD_METRICS
from src.mvp.evidence_card import (
    DETERMINISTIC_INPUT_SCHEMA_VERSION,
    DeterministicEvidenceInput,
    build_deterministic_evidence_input,
)


EVIDENCE_DATE = pd.Timestamp("2024-01-05")
COMPARE_DATE = pd.Timestamp("2023-12-01")
NO_EVIDENCE_DATE = pd.Timestamp("2026-05-29")


def test_future_as_of_date_is_rejected() -> None:
    with pytest.raises(ValueError, match="future"):
        build_deterministic_evidence_input(
            as_of_date=pd.Timestamp("2099-01-01")
        )


def test_comparison_date_must_precede_as_of_date() -> None:
    with pytest.raises(ValueError, match="strictly before"):
        build_deterministic_evidence_input(
            as_of_date=EVIDENCE_DATE,
            compare_to_date=pd.Timestamp("2024-02-01"),
        )


def test_unknown_threshold_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported threshold profile"):
        build_deterministic_evidence_input(
            as_of_date=EVIDENCE_DATE,
            threshold_profile="aggressive",
        )


def test_schema_contains_only_validated_deterministic_inputs() -> None:
    result = build_deterministic_evidence_input(
        as_of_date=EVIDENCE_DATE,
        compare_to_date=COMPARE_DATE,
    )

    assert isinstance(result, DeterministicEvidenceInput)
    assert result.schema_version == DETERMINISTIC_INPUT_SCHEMA_VERSION
    assert result.deterministic_score is None
    assert result.threshold_profile == "default"
    assert result.comparison_date == "2023-12-01"
    assert result.audit_metadata["llm_invoked"] is False
    assert result.audit_metadata["phase_5_alignment_status"] == (
        "unavailable_unapproved"
    )
    assert {
        signal.name
        for signal in (
            result.triggered_quant_signals
            + result.non_triggered_relevant_signals
        )
    } == set(SCORECARD_METRICS)
    assert any(
        "deterministic score" in warning.lower()
        for warning in result.data_warnings
    )
    assert any("Phase 5A" in warning for warning in result.data_warnings)
    assert not {
        "narrative_state",
        "pm_interpretation",
        "monitoring_questions",
        "invalidation_conditions",
    }.intersection(result.to_dict())

    with pytest.raises(ValueError, match="unsupported deterministic"):
        dataclasses.replace(result, schema_version="invalid")


def test_comparison_changes_are_preserved_when_supported() -> None:
    result = build_deterministic_evidence_input(
        as_of_date=EVIDENCE_DATE,
        compare_to_date=COMPARE_DATE,
    )
    signals = (
        result.triggered_quant_signals
        + result.non_triggered_relevant_signals
    )
    assert any(signal.change_vs_comparison is not None for signal in signals)


def test_retrieved_evidence_never_exceeds_cutoff() -> None:
    result = build_deterministic_evidence_input(as_of_date=EVIDENCE_DATE)
    cutoff = datetime.fromisoformat(result.data_cutoff)

    assert result.retrieved_evidence
    assert all(
        datetime.fromisoformat(item.timestamp) <= cutoff
        for item in result.retrieved_evidence
    )
    future_item = dataclasses.replace(
        result.retrieved_evidence[0],
        timestamp="2024-01-06T09:00:00-05:00",
    )
    with pytest.raises(ValueError, match="later than data_cutoff"):
        dataclasses.replace(result, retrieved_evidence=(future_item,))


def test_missing_evidence_is_a_warning_not_a_fabricated_value() -> None:
    result = build_deterministic_evidence_input(as_of_date=NO_EVIDENCE_DATE)

    assert not result.retrieved_evidence
    assert result.audit_metadata["evidence_quality"] == "unavailable"
    assert any(
        "evidence" in warning.lower() and "unavailable" in warning.lower()
        for warning in result.data_warnings
    )


def test_identical_inputs_are_deterministically_reproducible() -> None:
    first = build_deterministic_evidence_input(
        as_of_date=EVIDENCE_DATE,
        compare_to_date=COMPARE_DATE,
    )
    second = build_deterministic_evidence_input(
        as_of_date=EVIDENCE_DATE,
        compare_to_date=COMPARE_DATE,
    )

    assert first == second
    assert first.to_dict() == second.to_dict()
    assert first.run_id == second.run_id
