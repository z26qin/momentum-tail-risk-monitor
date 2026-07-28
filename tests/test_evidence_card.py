"""Essential safety tests for the Phase 6A Evidence Card integration.

These protect the new integration only. They reuse the real processed Phase 1--4
artifacts and never modify them.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from src.monitoring.scorecard import SCORECARD_METRICS
from src.mvp.evidence_card import (
    EvidenceCard,
    QuantSignal,
    build_evidence_card,
    resolve_threshold_profile,
)
from src.mvp.llm_synthesis import SynthesisResult
from src.utils.io import DEFAULT_PROCESSED_DIR, DEFAULT_OUTPUT_DIR

# 2024-01-05 has both quantitative history and a date-matched evidence cache.
EVIDENCE_DATE = pd.Timestamp("2024-01-05")
COMPARE_DATE = pd.Timestamp("2023-12-01")
# 2026-05-29 has quantitative history but no evidence cache (fails safe).
CURRENT_DATE = pd.Timestamp("2026-05-29")


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
    assert with_llm.synthesis_mode == "deterministic_template"
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


def test_missing_retrieval_produces_warning_not_crash() -> None:
    card = build_evidence_card(as_of_date=CURRENT_DATE, use_llm=True)
    assert card.evidence_quality == "unavailable"
    assert not card.supporting_evidence
    assert card.missing_or_uncertain_evidence
    assert any("no date-matched evidence" in w for w in card.warnings)


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_build_does_not_modify_existing_artifacts() -> None:
    protected = [
        DEFAULT_PROCESSED_DIR / "market_features.parquet",
        DEFAULT_PROCESSED_DIR / "leg_risk_history.parquet",
        DEFAULT_PROCESSED_DIR / "french_research_factors_daily.parquet",
        DEFAULT_PROCESSED_DIR / "momentum_labels_h20.parquet",
        DEFAULT_OUTPUT_DIR / "debug" / "classified_evidence_2024-01-05.json",
    ]
    before = {path: _sha256(path) for path in protected}
    build_evidence_card(as_of_date=EVIDENCE_DATE, use_llm=True)
    after = {path: _sha256(path) for path in protected}
    assert before == after


def _mutated_card(card: EvidenceCard, **changes) -> EvidenceCard:
    import dataclasses

    return dataclasses.replace(card, **changes)
