"""Focused tests for the constrained Evidence Card interpretation layer."""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from src.mvp.evidence_card import build_deterministic_evidence_input
from src.mvp.evidence_interpretation import (
    INTERPRETATION_INSTRUCTIONS,
    INTERPRETATION_PROMPT_VERSION,
    MODEL_CONTEXT_FIELDS,
    EvidenceInterpretation,
    compact_public_positioning_proxies,
    interpret_evidence_card,
)


EVIDENCE_DATE = pd.Timestamp("2024-01-05")


@pytest.fixture(scope="module")
def deterministic_input():
    return build_deterministic_evidence_input(
        as_of_date=EVIDENCE_DATE,
        compare_to_date=pd.Timestamp("2023-12-01"),
    )


def _valid_payload(deterministic_input) -> dict:
    supporting = next(
        (
            item.evidence_id
            for item in deterministic_input.retrieved_evidence
            if item.stance == "supporting"
        ),
        None,
    )
    contradicting = next(
        (
            item.evidence_id
            for item in deterministic_input.retrieved_evidence
            if item.stance == "contradicting"
        ),
        None,
    )
    return {
        "narrative_state": (
            "The supplied state warrants monitoring, but it is not a confirmed "
            "crash forecast."
        ),
        "narrative_changes": (
            "Implemented signals changed relative to the supplied comparison.",
        ),
        "supporting_evidence_ids": () if supporting is None else (supporting,),
        "contradicting_evidence_ids": (
            () if contradicting is None else (contradicting,)
        ),
        "missing_or_uncertain_evidence": (
            "Retrieved evidence remains incomplete.",
        ),
        "pm_interpretation": (
            "The evidence is mixed, so this remains a monitoring state rather "
            "than a confirmed forecast."
        ),
        "monitoring_questions": (
            "Do the implemented conditions continue to deteriorate together?",
            "Does retrieved evidence continue to support the monitored mechanism?",
            "Do currently triggered conditions remain beyond their thresholds?",
        ),
        "invalidation_conditions": (
            "Triggered conditions return to non-triggered states.",
            "Supplied contradicting evidence weakens the monitored interpretation.",
        ),
    }


class _FixedInterpreter:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.context = None
        self.instructions = None

    def interpret(self, *, context, instructions):
        self.calls += 1
        self.context = context
        self.instructions = instructions
        return self.payload


def test_deterministic_values_identical_with_llm_on_and_off(
    deterministic_input,
) -> None:
    before = deterministic_input.to_dict()
    provider = _FixedInterpreter(_valid_payload(deterministic_input))

    without_llm = interpret_evidence_card(deterministic_input, use_llm=False)
    with_llm = interpret_evidence_card(
        deterministic_input,
        use_llm=True,
        interpreter=provider,
        environment={"OPENAI_API_KEY": "test-only"},
    )

    assert deterministic_input.to_dict() == before
    assert without_llm.use_llm is False
    assert with_llm.use_llm is True
    assert set(provider.context) == set(MODEL_CONTEXT_FIELDS)
    assert "data_warnings" not in provider.context
    assert provider.context["quantitative_signals"]
    assert {
        "current_value",
        "threshold",
        "status",
        "change_vs_comparison",
    }.issubset(provider.context["quantitative_signals"][0])
    assert not {
        "overall_risk_state",
        "deterministic_score",
        "triggered_quant_signals",
        "threshold_profile",
        "run_id",
    }.intersection(with_llm.to_dict())


def test_unsupported_evidence_ids_are_removed_and_flagged(
    deterministic_input,
) -> None:
    payload = _valid_payload(deterministic_input)
    payload["supporting_evidence_ids"] = (
        *payload["supporting_evidence_ids"],
        "invented-evidence-id",
    )
    result = interpret_evidence_card(
        deterministic_input,
        interpreter=_FixedInterpreter(payload),
        environment={"OPENAI_API_KEY": "test-only"},
    )

    assert result.use_llm is True
    assert "invented-evidence-id" not in result.supporting_evidence_ids
    assert any(
        "Unsupported or stance-inconsistent" in warning
        for warning in result.warnings
    )


def test_no_credential_fallback_is_clear_and_does_not_call_provider(
    deterministic_input,
) -> None:
    provider = _FixedInterpreter(_valid_payload(deterministic_input))
    result = interpret_evidence_card(
        deterministic_input,
        use_llm=True,
        interpreter=provider,
        environment={},
    )

    assert result.use_llm is False
    assert provider.calls == 0
    assert any("no supported API credentials" in warning for warning in result.warnings)
    assert result.pm_interpretation


def test_empty_evidence_produces_uncertainty_without_citations(
    deterministic_input,
) -> None:
    empty = dataclasses.replace(deterministic_input, retrieved_evidence=())
    payload = _valid_payload(empty)
    payload["supporting_evidence_ids"] = ("hallucinated-source",)
    result = interpret_evidence_card(
        empty,
        interpreter=_FixedInterpreter(payload),
        environment={"OPENAI_API_KEY": "test-only"},
    )

    assert not result.supporting_evidence_ids
    assert not result.contradicting_evidence_ids
    assert any(
        "No point-in-time evidence was supplied" in item
        for item in result.missing_or_uncertain_evidence
    )
    assert any("hallucinated-source" in warning for warning in result.warnings)


def test_interpretation_schema_validation() -> None:
    minimal = EvidenceInterpretation(
        narrative_state="Calibrated state.",
        narrative_changes=(),
        supporting_evidence_ids=(),
        contradicting_evidence_ids=(),
        missing_or_uncertain_evidence=(),
        pm_interpretation="Calibrated interpretation.",
        monitoring_questions=(),
        invalidation_conditions=(),
    )
    assert minimal.use_llm is False
    assert not minimal.warnings

    with pytest.raises(ValueError, match="narrative_state cannot be empty"):
        EvidenceInterpretation(
            narrative_state="",
            narrative_changes=(),
            supporting_evidence_ids=(),
            contradicting_evidence_ids=(),
            missing_or_uncertain_evidence=(),
            pm_interpretation="Calibrated interpretation.",
            monitoring_questions=(),
            invalidation_conditions=(),
            use_llm=False,
            model_or_prompt_version=INTERPRETATION_PROMPT_VERSION,
            warnings=(),
        )
    with pytest.raises(ValueError, match="duplicate evidence IDs"):
        EvidenceInterpretation(
            narrative_state="Calibrated state.",
            narrative_changes=(),
            supporting_evidence_ids=("same-id", "same-id"),
            contradicting_evidence_ids=(),
            missing_or_uncertain_evidence=(),
            pm_interpretation="Calibrated interpretation.",
            monitoring_questions=(),
            invalidation_conditions=(),
            use_llm=False,
            model_or_prompt_version=INTERPRETATION_PROMPT_VERSION,
            warnings=(),
        )


def test_quantitative_fields_in_provider_output_fail_closed(
    deterministic_input,
) -> None:
    payload = _valid_payload(deterministic_input)
    payload["overall_risk_state"] = "provider-attempted-change"
    result = interpret_evidence_card(
        deterministic_input,
        interpreter=_FixedInterpreter(payload),
        environment={"OPENAI_API_KEY": "test-only"},
    )

    assert result.use_llm is False
    assert any("schema or safety validation" in warning for warning in result.warnings)


def test_provider_list_counts_fail_closed(deterministic_input) -> None:
    payload = _valid_payload(deterministic_input)
    payload["monitoring_questions"] = (
        "Is the state changing?",
        "Does evidence remain mixed?",
        "Do monitored signals deteriorate together?",
        "Does an extra fourth question appear?",
    )
    result = interpret_evidence_card(
        deterministic_input,
        interpreter=_FixedInterpreter(payload),
        environment={"OPENAI_API_KEY": "test-only"},
    )

    assert result.use_llm is False
    assert any("1 to 3 monitoring questions" in warning for warning in result.warnings)


def test_llm_generated_numerical_claims_fail_closed(
    deterministic_input,
) -> None:
    payload = _valid_payload(deterministic_input)
    payload["pm_interpretation"] = "The crash probability is 42 percent."
    result = interpret_evidence_card(
        deterministic_input,
        interpreter=_FixedInterpreter(payload),
        environment={"OPENAI_API_KEY": "test-only"},
    )

    assert result.use_llm is False
    assert any("numerical values" in warning for warning in result.warnings)


def test_llm_generated_number_words_fail_closed(
    deterministic_input,
) -> None:
    payload = _valid_payload(deterministic_input)
    payload["pm_interpretation"] = "Two implemented conditions warrant attention."
    result = interpret_evidence_card(
        deterministic_input,
        interpreter=_FixedInterpreter(payload),
        environment={"OPENAI_API_KEY": "test-only"},
    )

    assert result.use_llm is False
    assert any("numerical values" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    "unsafe_interpretation",
    (
        "The retrieved evidence caused the state change.",
        "The market will crash.",
        "The portfolio should sell the monitored exposure.",
    ),
)
def test_causal_certainty_and_trade_claims_fail_closed(
    deterministic_input,
    unsafe_interpretation: str,
) -> None:
    payload = _valid_payload(deterministic_input)
    payload["pm_interpretation"] = unsafe_interpretation
    result = interpret_evidence_card(
        deterministic_input,
        interpreter=_FixedInterpreter(payload),
        environment={"OPENAI_API_KEY": "test-only"},
    )

    assert result.use_llm is False
    assert any(
        "causal, certainty, or recommendation" in warning
        for warning in result.warnings
    )


class _ProxyAwareInterpreter:
    """Stub that changes narrative only when elevated FINRA proxies are present."""

    def __init__(self, base_payload: dict):
        self.base_payload = base_payload
        self.context = None
        self.instructions = None

    def interpret(self, *, context, instructions):
        self.context = context
        self.instructions = instructions
        payload = dict(self.base_payload)
        proxies = context.get("public_positioning_proxies") or []
        elevated = any(
            str(item.get("state") or "").startswith("elevated")
            or (
                isinstance(item.get("value"), (int, float))
                and float(item["value"]) >= 1.0
            )
            for item in proxies
        )
        if elevated:
            payload["pm_interpretation"] = (
                "Public short-activity proxies are elevated in the loser "
                "basket, increasing the relevance of short-side crowding as a "
                "hypothesis. The data do not identify the underlying investors "
                "or establish active covering."
            )
            payload["missing_or_uncertain_evidence"] = (
                "Forced deleveraging remains unconfirmed.",
                "Investor identity and active short covering remain unproven.",
            )
        else:
            payload["pm_interpretation"] = (
                "No useful public positioning proxy was supplied, so short-side "
                "crowding remains unsupported as a positioning claim."
            )
        return payload


def test_elevated_finra_proxy_changes_context_not_scorecard(
    deterministic_input,
) -> None:
    structural = {
        "scenario_classification": "crowded_theme_unwind",
        "active_scenarios": ["crowded_theme_unwind"],
        "mechanism_statuses": {
            "bear_market_recovery_crash": "watch",
            "crowded_theme_unwind": "triggered",
            "short_book_reversal_crash": "not_confirmed",
        },
    }
    mechanical = {
        "unwind_state": "NORMAL",
        "liquidity_absorption_failure": False,
        "factor_footprint_status": "not_elevated",
        "aligned_turnover_status": "not_elevated",
    }
    elevated_proxies = compact_public_positioning_proxies(
        {
            "as_of_date": deterministic_input.as_of_date,
            "observation_date": deterministic_input.as_of_date,
            "read": "confirm",
            "short_interest_ratio_z": 1.4,
            "short_interest_utilisation_z": 1.1,
            "short_volume_share_z": 0.3,
            "stale_trading_days": 2,
            "limitations": (
                "FINRA loser-leg short-interest proxies are public-data only.",
            ),
        }
    )
    before = deterministic_input.to_dict()
    triggered_before = [
        signal.name for signal in deterministic_input.triggered_quant_signals
    ]
    provider = _ProxyAwareInterpreter(_valid_payload(deterministic_input))

    with_proxy = interpret_evidence_card(
        deterministic_input,
        use_llm=True,
        interpreter=provider,
        environment={"OPENAI_API_KEY": "test-only"},
        structural_unwind=structural,
        mechanical_unwind=mechanical,
        public_positioning_proxies=elevated_proxies,
    )
    without_proxy = interpret_evidence_card(
        deterministic_input,
        use_llm=True,
        interpreter=_ProxyAwareInterpreter(_valid_payload(deterministic_input)),
        environment={"OPENAI_API_KEY": "test-only"},
        structural_unwind=structural,
        mechanical_unwind=mechanical,
        public_positioning_proxies=[],
    )

    assert deterministic_input.to_dict() == before
    assert [
        signal.name for signal in deterministic_input.triggered_quant_signals
    ] == triggered_before
    assert set(provider.context) == set(MODEL_CONTEXT_FIELDS)
    assert "public_positioning_proxies" in provider.context
    assert provider.context["public_positioning_proxies"]
    assert all(
        item["evidence_class"] == "structured_public_proxy"
        and item["source"] == "FINRA"
        for item in provider.context["public_positioning_proxies"]
    )
    assert provider.context["retrieved_evidence"] == [
        item.to_dict() for item in deterministic_input.retrieved_evidence
    ]
    assert provider.context["structural_unwind"] == structural
    assert provider.context["mechanical_unwind"]["unwind_state"] == "NORMAL"
    assert "public_positioning_proxies" in provider.instructions
    assert "structured_public_proxy" in INTERPRETATION_INSTRUCTIONS
    assert INTERPRETATION_PROMPT_VERSION.endswith("v4")
    assert with_proxy.use_llm is True
    assert "short-side crowding as a hypothesis" in with_proxy.pm_interpretation
    assert "do not identify the underlying investors" in with_proxy.pm_interpretation
    assert any(
        "Forced deleveraging remains unconfirmed" in item
        for item in with_proxy.missing_or_uncertain_evidence
    )
    assert without_proxy.pm_interpretation != with_proxy.pm_interpretation
    assert "remains unsupported" in without_proxy.pm_interpretation
