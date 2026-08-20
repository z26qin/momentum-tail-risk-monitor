"""Essential safety tests for the Phase 6A Evidence Card integration.

These protect the new integration only. They reuse the real processed Phase 1--4
artifacts and never modify them.
"""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from src.monitoring.scorecard import DEFAULT_CONFIG, SCORECARD_METRICS
from src.mvp.evidence_card import (
    SCHEMA_VERSION,
    THRESHOLD_PROFILES,
    EvidenceCard,
    QuantSignal,
    RetrievedEvidence,
    build_evidence_card,
    resolve_threshold_profile,
)
from src.mvp.llm_synthesis import SynthesisResult
from src.utils.io import DEFAULT_PROCESSED_DIR, DEFAULT_OUTPUT_DIR

# 2024-01-05 has both quantitative history and a date-matched evidence cache.
EVIDENCE_DATE = pd.Timestamp("2024-01-05")
COMPARE_DATE = pd.Timestamp("2023-12-01")


def test_notebook_facing_contract_is_frozen() -> None:
    assert SCHEMA_VERSION == "evidence-card-v1"
    assert {field.name for field in dataclasses.fields(QuantSignal)} == {
        "name",
        "current_value",
        "threshold",
        "status",
        "direction",
        "change_vs_comparison",
        "interpretation",
        "source_component",
    }
    assert {field.name for field in dataclasses.fields(RetrievedEvidence)} == {
        "evidence_id",
        "timestamp",
        "source",
        "headline_or_summary",
        "relevance_reason",
        "stance",
        "citation_or_locator",
    }
    evidence_card_fields = {
        field.name for field in dataclasses.fields(EvidenceCard)
    }
    assert evidence_card_fields == {
        "schema_version",
        "as_of_date",
        "comparison_date",
        "overall_risk_state",
        "deterministic_score",
        "tail_loss_frequency",
        "tail_loss_horizon_days",
        "evidence_quality",
        "triggered_quant_signals",
        "non_triggered_relevant_signals",
        "narrative_state",
        "what_changed",
        "supporting_evidence",
        "contradicting_evidence",
        "contextual_evidence",
        "missing_or_uncertain_evidence",
        "historical_analogs",
        "pm_interpretation",
        "monitoring_questions",
        "invalidation_conditions",
        "threshold_profile",
        "data_version",
        "quant_model_version",
        "data_cutoff",
        "run_id",
        "llm_enabled",
        "synthesis_mode",
        "model_or_prompt_version",
        "warnings",
    }
    assert not {
        "fundamental_alignment",
        "fundamental_ranks",
        "spearman_alignment",
        "alignment_flags",
    }.intersection(evidence_card_fields)


def test_default_is_the_only_approved_threshold_profile() -> None:
    assert THRESHOLD_PROFILES == {"default": DEFAULT_CONFIG}
    assert resolve_threshold_profile("default") is DEFAULT_CONFIG


def test_future_as_of_date_is_rejected() -> None:
    with pytest.raises(ValueError, match="future"):
        build_evidence_card(as_of_date=pd.Timestamp("2099-01-01"))


def test_unsupported_threshold_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported threshold profile"):
        build_evidence_card(as_of_date=EVIDENCE_DATE, threshold_profile="aggressive")
    with pytest.raises(ValueError, match="unsupported threshold profile"):
        resolve_threshold_profile("does-not-exist")


def test_comparison_date_after_as_of_is_rejected() -> None:
    with pytest.raises(ValueError, match="strictly before"):
        build_evidence_card(
            as_of_date=EVIDENCE_DATE,
            compare_to_date=pd.Timestamp("2024-02-01"),
        )


def test_quant_fields_identical_with_and_without_llm() -> None:
    with_llm = build_evidence_card(as_of_date=EVIDENCE_DATE, use_llm=True)
    without_llm = build_evidence_card(as_of_date=EVIDENCE_DATE, use_llm=False)

    assert with_llm.overall_risk_state == without_llm.overall_risk_state
    assert with_llm.tail_loss_frequency == without_llm.tail_loss_frequency
    assert with_llm.run_id == without_llm.run_id
    assert [s.to_dict() for s in with_llm.triggered_quant_signals] == [
        s.to_dict() for s in without_llm.triggered_quant_signals
    ]
    assert [s.to_dict() for s in with_llm.non_triggered_relevant_signals] == [
        s.to_dict() for s in without_llm.non_triggered_relevant_signals
    ]
    # The synthesis mode still records that the LLM path was requested or not.
    assert with_llm.synthesis_mode == "deterministic_fallback"
    assert without_llm.synthesis_mode == "deterministic_no_llm"


def test_signals_come_only_from_the_scorecard() -> None:
    card = build_evidence_card(as_of_date=EVIDENCE_DATE, use_llm=False)
    names = {
        s.name
        for s in card.triggered_quant_signals + card.non_triggered_relevant_signals
    }
    assert names == set(SCORECARD_METRICS)


def test_retrieved_evidence_never_exceeds_cutoff() -> None:
    card = build_evidence_card(as_of_date=EVIDENCE_DATE, use_llm=False)
    assert card.evidence_quality == "available"
    cutoff = datetime.fromisoformat(card.data_cutoff)
    every_item = (
        card.supporting_evidence
        + card.contradicting_evidence
        + card.contextual_evidence
    )
    assert every_item, "expected the cached worked example to return evidence"
    for item in every_item:
        assert datetime.fromisoformat(item.timestamp) <= cutoff


def test_card_validates_and_rejects_bad_input() -> None:
    card = build_evidence_card(as_of_date=EVIDENCE_DATE, use_llm=False)
    assert isinstance(card, EvidenceCard)
    assert card.schema_version == "evidence-card-v1"

    signal = QuantSignal(
        name="beta_gap",
        current_value=0.5,
        threshold=0.25,
        status="triggered",
        direction="greater_than_or_equal",
        change_vs_comparison=None,
        interpretation="example",
        source_component="test",
    )
    # A triggered signal placed in the non-triggered list must be rejected.
    with pytest.raises(ValueError, match="non_triggered"):
        _mutated_card(card, non_triggered_relevant_signals=(signal,))
    # A comparison date on or after the as-of date must be rejected.
    with pytest.raises(ValueError, match="strictly before"):
        _mutated_card(card, comparison_date=card.as_of_date)


def test_deterministic_fallback_when_synthesizer_fails() -> None:
    class _Broken:
        def synthesize(self, *, context):  # noqa: ANN001, ANN201
            raise RuntimeError("synthesis boom")

    card = build_evidence_card(
        as_of_date=EVIDENCE_DATE,
        use_llm=True,
        synthesizer=_Broken(),
    )
    assert card.synthesis_mode == "deterministic_fallback"
    assert any("fell back to deterministic" in w for w in card.warnings)
    assert card.narrative_state  # deterministic narrative still present


def test_missing_api_configuration_triggers_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    card = build_evidence_card(as_of_date=EVIDENCE_DATE, use_llm=True)

    assert card.synthesis_mode == "deterministic_fallback"
    assert any("no external synthesizer or API configuration" in w for w in card.warnings)


def test_injected_synthesizer_only_changes_narrative() -> None:
    class _Fixed:
        def synthesize(self, *, context):  # noqa: ANN001, ANN201
            return SynthesisResult(
                narrative_state="Injected narrative.",
                what_changed=("Injected change.",),
                pm_interpretation="Injected interpretation.",
                monitoring_questions=("Injected question?",),
                invalidation_conditions=("Injected invalidation.",),
                model_or_prompt_version="stub-model-v1",
            )

    baseline = build_evidence_card(as_of_date=EVIDENCE_DATE, use_llm=False)
    injected = build_evidence_card(
        as_of_date=EVIDENCE_DATE, use_llm=True, synthesizer=_Fixed()
    )
    assert injected.synthesis_mode == "external_synthesizer"
    assert injected.narrative_state == "Injected narrative."
    assert injected.model_or_prompt_version == "stub-model-v1"
    # Quantitative content is untouched by the injected synthesizer.
    assert injected.run_id == baseline.run_id
    assert [s.to_dict() for s in injected.triggered_quant_signals] == [
        s.to_dict() for s in baseline.triggered_quant_signals
    ]
    assert injected.tail_loss_frequency == baseline.tail_loss_frequency


def test_missing_retrieval_produces_warning_not_crash(tmp_path: Path) -> None:
    card = build_evidence_card(
        as_of_date=EVIDENCE_DATE,
        use_llm=True,
        output_dir=tmp_path,
    )
    assert card.evidence_quality == "unavailable"
    assert not card.supporting_evidence
    assert card.missing_or_uncertain_evidence
    assert any("no date-matched evidence" in w for w in card.warnings)


def test_retrieval_exception_fails_closed_without_losing_quant_state() -> None:
    def _broken_builder(**kwargs):  # noqa: ANN003, ANN202
        raise RuntimeError("retrieval unavailable")

    baseline = build_evidence_card(as_of_date=EVIDENCE_DATE, use_llm=False)
    card = build_evidence_card(
        as_of_date=EVIDENCE_DATE,
        use_llm=False,
        evidence_builder=_broken_builder,
    )

    assert card.evidence_quality == "unavailable"
    assert card.run_id == baseline.run_id
    assert [s.to_dict() for s in card.triggered_quant_signals] == [
        s.to_dict() for s in baseline.triggered_quant_signals
    ]
    assert any("retrieval failed closed" in w for w in card.warnings)


def test_future_dated_injected_evidence_is_excluded() -> None:
    def _future_builder(**kwargs):  # noqa: ANN003, ANN202
        return {
            "status": "sample_only",
            "supporting": [
                {
                    "document_id": "future-item",
                    "publication_timestamp": "2024-01-06T09:00:00-05:00",
                    "source": "test",
                    "title": "This item was not available at the cutoff",
                    "classification_rationale": "test fixture",
                    "citation_url": "fixture://future-item",
                }
            ],
            "contradicting": [],
            "contextual": [],
            "limitations": [],
        }

    card = build_evidence_card(
        as_of_date=EVIDENCE_DATE,
        use_llm=False,
        evidence_builder=_future_builder,
    )
    assert card.evidence_quality == "unavailable"
    assert not card.supporting_evidence
    assert any("cutoff/schema validation" in w for w in card.warnings)


def test_malformed_retrieval_result_is_excluded_without_crashing() -> None:
    def _malformed_builder(**kwargs):  # noqa: ANN003, ANN202
        return {
            "status": "sample_only",
            "supporting": [{"document_id": "missing-required-fields"}],
            "contradicting": [],
            "contextual": [],
            "limitations": [],
        }

    card = build_evidence_card(
        as_of_date=EVIDENCE_DATE,
        use_llm=False,
        evidence_builder=_malformed_builder,
    )
    assert card.evidence_quality == "unavailable"
    assert not card.supporting_evidence
    assert any("cutoff/schema validation" in w for w in card.warnings)


def test_repeated_runs_are_deterministic() -> None:
    first = build_evidence_card(
        as_of_date=EVIDENCE_DATE, compare_to_date=COMPARE_DATE, use_llm=False
    )
    second = build_evidence_card(
        as_of_date=EVIDENCE_DATE, compare_to_date=COMPARE_DATE, use_llm=False
    )
    assert first.to_dict() == second.to_dict()


def test_comparison_drives_change_analysis() -> None:
    without = build_evidence_card(as_of_date=EVIDENCE_DATE, use_llm=False)
    with_compare = build_evidence_card(
        as_of_date=EVIDENCE_DATE, compare_to_date=COMPARE_DATE, use_llm=False
    )
    assert all(
        s.change_vs_comparison is None
        for s in without.triggered_quant_signals + without.non_triggered_relevant_signals
    )
    changed = [
        s
        for s in with_compare.triggered_quant_signals
        + with_compare.non_triggered_relevant_signals
        if s.change_vs_comparison is not None
    ]
    assert changed, "expected at least one signal change vs the comparison date"
    assert with_compare.comparison_date == "2023-12-01"


def test_run_metadata_records_selected_configuration() -> None:
    card = build_evidence_card(
        as_of_date=EVIDENCE_DATE,
        compare_to_date=COMPARE_DATE,
        threshold_profile="default",
        horizon=20,
        use_llm=False,
    )
    assert card.as_of_date == "2024-01-05"
    assert card.comparison_date == "2023-12-01"
    assert card.threshold_profile == "default"
    assert card.tail_loss_horizon_days == 20
    assert card.llm_enabled is False
    assert card.data_version.startswith("sha256:")
    assert card.quant_model_version.startswith("phase-1-4-deterministic-v1:")


def test_timezone_aware_date_inputs_use_the_stated_calendar_date() -> None:
    card = build_evidence_card(
        as_of_date=pd.Timestamp("2024-01-05T12:00:00Z"),
        compare_to_date=pd.Timestamp("2023-12-01T16:00:00-05:00"),
        use_llm=False,
    )
    assert card.as_of_date == "2024-01-05"
    assert card.comparison_date == "2023-12-01"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_build_does_not_modify_existing_artifacts() -> None:
    protected = [
        DEFAULT_PROCESSED_DIR / "market_features.parquet",
        DEFAULT_PROCESSED_DIR / "leg_risk_history.parquet",
        DEFAULT_PROCESSED_DIR / "french_research_factors_daily.parquet",
        DEFAULT_PROCESSED_DIR / "momentum_labels_h20.parquet",
        DEFAULT_OUTPUT_DIR / "evidence_cache" / "classified_evidence_2024-01-05.json",
    ]
    before = {path: _sha256(path) for path in protected}
    build_evidence_card(as_of_date=EVIDENCE_DATE, use_llm=True)
    after = {path: _sha256(path) for path in protected}
    assert before == after


def _mutated_card(card: EvidenceCard, **changes) -> EvidenceCard:
    return dataclasses.replace(card, **changes)
