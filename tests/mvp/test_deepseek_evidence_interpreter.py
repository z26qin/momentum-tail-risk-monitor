"""Smoke tests for DeepSeek-backed Evidence Card interpretation."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.mvp.deepseek_evidence_interpreter import DeepSeekEvidenceInterpreter
from src.mvp.evidence_card import build_deterministic_evidence_input
from src.mvp.evidence_interpretation import (
    MODEL_CONTEXT_FIELDS,
    public_positioning_proxy_items,
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
            "Public short-activity proxies are elevated in the loser basket, "
            "increasing the relevance of short-side crowding as a hypothesis; "
            "the data do not identify the underlying investors or establish "
            "active covering. Forced deleveraging remains unconfirmed.",
        ),
        "pm_interpretation": (
            "FINRA public positioning proxies are elevated, which raises short-side "
            "crowding as a contextual hypothesis only; investor identity and active "
            "covering remain unproven."
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


def test_deepseek_interpreter_receives_proxies_without_changing_scorecard(
    deterministic_input,
) -> None:
    elevated_proxies = public_positioning_proxy_items(
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
    payload = _valid_payload(deterministic_input)
    captured: dict[str, object] = {}

    def _transport(*, api_key, model, messages, base_url, temperature):
        captured["api_key"] = api_key
        captured["model"] = model
        captured["messages"] = messages
        captured["base_url"] = base_url
        captured["temperature"] = temperature
        return json.dumps(payload)

    before = deterministic_input.to_dict()
    triggered_before = [
        signal.name for signal in deterministic_input.triggered_quant_signals
    ]
    interpreter = DeepSeekEvidenceInterpreter(
        environment={"DEEPSEEK_API_KEY": "test-only"},
        load_dotenv=False,
        transport=_transport,
    )

    result = interpret_evidence_card(
        deterministic_input,
        use_llm=True,
        interpreter=interpreter,
        environment={"DEEPSEEK_API_KEY": "test-only"},
        public_positioning_proxies=elevated_proxies,
    )

    assert deterministic_input.to_dict() == before
    assert [
        signal.name for signal in deterministic_input.triggered_quant_signals
    ] == triggered_before
    assert result.use_llm is True
    assert interpreter.last_context is not None
    assert set(interpreter.last_context) == set(MODEL_CONTEXT_FIELDS)
    assert interpreter.last_context["public_positioning_proxies"]
    assert all(
        item["evidence_class"] == "structured_public_proxy"
        for item in interpreter.last_context["public_positioning_proxies"]
    )
    assert "short-side crowding as a contextual hypothesis" in result.pm_interpretation
    assert "Forced deleveraging remains unconfirmed" in (
        result.missing_or_uncertain_evidence[0]
    )
    assert captured["messages"]


def test_deepseek_interpreter_missing_key_falls_back(deterministic_input) -> None:
    before = deterministic_input.to_dict()
    result = interpret_evidence_card(
        deterministic_input,
        use_llm=True,
        interpreter=DeepSeekEvidenceInterpreter(load_dotenv=False),
        environment={},
    )
    assert deterministic_input.to_dict() == before
    assert result.use_llm is False
    assert any("no supported API credentials" in warning for warning in result.warnings)
