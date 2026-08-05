"""Smoke tests for DeepSeek-backed PM response interpretation."""

from __future__ import annotations

import json

import pytest

from src.mvp.config import default_demo_config
from src.mvp.deepseek_pm_response_interpreter import DeepSeekPMResponseInterpreter
from src.mvp.pipeline import run_mvp
from src.mvp.pm_response import (
    PM_RESPONSE_PROMPT_VERSION,
    build_pm_response,
    derive_pm_context,
)


@pytest.fixture(scope="module")
def demo_run():
    return run_mvp(default_demo_config())


def _valid_pm_payload(context) -> dict:
    selected = list(context.allowed_categories[:3]) or ["maintain_and_monitor"]
    return {
        "current_posture": (
            "Maintain and monitor. The setup warrants attention but is not "
            "confirmed."
        ),
        "main_vulnerability": (
            "The clearest risk remains a rebound that would hit the short basket."
        ),
        "what_would_change_the_reading": (
            "The setup would become more fragile if short-leg losses rise "
            "during recovery.",
        ),
        "conditional_response": (
            "If confirmed, consider a temporary beta hedge subject to PM review.",
            "Review rebound-sensitive shorts would become relevant.",
        ),
        "why_not_act_yet": (
            "Broad de-risking would be premature because stress channels remain "
            "unconfirmed."
        ),
        "selected_categories": tuple(selected),
    }


def test_deepseek_pm_interpreter_live_path_with_transport(demo_run) -> None:
    card = demo_run.deterministic_input
    unwind = demo_run.unwind
    before_card = card.to_dict()
    before_unwind = unwind.to_dict()
    context = derive_pm_context(card, unwind)
    payload = _valid_pm_payload(context)
    captured: dict[str, object] = {}

    def _transport(*, api_key, model, messages, base_url, temperature):
        captured["api_key"] = api_key
        captured["model"] = model
        captured["messages"] = messages
        captured["base_url"] = base_url
        captured["temperature"] = temperature
        return json.dumps(payload)

    interpreter = DeepSeekPMResponseInterpreter(
        environment={"DEEPSEEK_API_KEY": "test-only"},
        load_dotenv=False,
        transport=_transport,
    )
    result = build_pm_response(
        card,
        unwind,
        use_llm=True,
        interpreter=interpreter,
        environment={"DEEPSEEK_API_KEY": "test-only"},
    )

    assert card.to_dict() == before_card
    assert unwind.to_dict() == before_unwind
    assert result.use_llm is True
    assert result.model_or_prompt_version == PM_RESPONSE_PROMPT_VERSION
    assert result.warnings == ()
    assert "beta hedge" in " ".join(result.conditional_response).lower()
    assert set(result.response_categories).issubset(context.allowed_categories)
    assert interpreter.last_context is not None
    assert "allowed_response_categories" in interpreter.last_context
    assert captured["api_key"] == "test-only"
    assert captured["temperature"] == 0.2
    assert any(
        msg.get("role") == "system" and "selected_categories" in msg.get("content", "")
        for msg in captured["messages"]  # type: ignore[union-attr]
    )


def test_deepseek_pm_interpreter_missing_key_falls_back(demo_run) -> None:
    card = demo_run.deterministic_input
    unwind = demo_run.unwind
    before_card = card.to_dict()
    before_unwind = unwind.to_dict()

    result = build_pm_response(
        card,
        unwind,
        use_llm=True,
        interpreter=DeepSeekPMResponseInterpreter(load_dotenv=False),
        environment={},
    )

    assert card.to_dict() == before_card
    assert unwind.to_dict() == before_unwind
    assert result.use_llm is False
    assert any("no supported API credentials" in warning for warning in result.warnings)


def test_deepseek_api_key_alone_enables_pm_credential_gate(demo_run) -> None:
    """PM gate must accept DEEPSEEK_API_KEY (same as Evidence Card)."""

    card = demo_run.deterministic_input
    unwind = demo_run.unwind
    context = derive_pm_context(card, unwind)
    payload = _valid_pm_payload(context)

    def _transport(*, api_key, model, messages, base_url, temperature):
        return json.dumps(payload)

    result = build_pm_response(
        card,
        unwind,
        use_llm=True,
        interpreter=DeepSeekPMResponseInterpreter(
            environment={"DEEPSEEK_API_KEY": "test-only"},
            load_dotenv=False,
            transport=_transport,
        ),
        environment={"DEEPSEEK_API_KEY": "test-only"},
    )
    assert result.use_llm is True
