"""Focused tests for the bounded PM response layer."""

from __future__ import annotations

import dataclasses

import pytest

from src.mvp.config import default_demo_config
from src.mvp.pipeline import run_mvp
from src.mvp.pm_response import (
    ALLOWED_RESPONSE_CATEGORIES,
    DETERMINISTIC_PM_RESPONSE_VERSION,
    PMResponse,
    build_pm_response,
    derive_pm_context,
)
from src.mvp.presentation import render_pm_card_html, render_pm_risk_markdown


def _force_signal_triggered(card, name: str):
    signals = list(card.triggered_quant_signals + card.non_triggered_relevant_signals)
    triggered = []
    non_triggered = []
    for signal in signals:
        if signal.name == name:
            signal = dataclasses.replace(signal, status="triggered")
            triggered.append(signal)
        elif signal.status == "triggered":
            triggered.append(signal)
        else:
            non_triggered.append(signal)
    return dataclasses.replace(
        card,
        triggered_quant_signals=tuple(triggered),
        non_triggered_relevant_signals=tuple(non_triggered),
    )


def _with_mechanism_status(unwind, scenario: str, status: str):
    mechanisms = []
    for item in unwind.mechanism_scenarios:
        if item.scenario == scenario:
            mechanisms.append(dataclasses.replace(item, status=status))
        else:
            mechanisms.append(item)
    active = tuple(
        item.scenario for item in mechanisms if item.status == "triggered"
    )
    return dataclasses.replace(
        unwind,
        mechanism_scenarios=tuple(mechanisms),
        active_scenarios=active,
    )


@pytest.fixture(scope="module")
def demo_run():
    return run_mvp(default_demo_config())


class _FixedPMInterpreter:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.context = None

    def interpret_pm_response(self, *, context, instructions):
        self.calls += 1
        self.context = context
        return self.payload


def _valid_pm_payload(context) -> dict:
    selected = list(context.allowed_categories[:3]) or ["maintain_and_monitor"]
    return {
        "current_state": (
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


def test_demo_no_trigger_explains_why_not_act_yet(demo_run) -> None:
    before_card = demo_run.deterministic_input.to_dict()
    before_unwind = demo_run.unwind.to_dict()
    pm = demo_run.pm_response
    context = derive_pm_context(demo_run.deterministic_input, demo_run.unwind)

    assert pm.use_llm is False
    assert pm.model_or_prompt_version == DETERMINISTIC_PM_RESPONSE_VERSION
    assert context.posture == "maintain_and_monitor" or context.posture in {
        "monitor_more_closely",
        "investigate_risk_channel",
    }
    assert "premature" in pm.why_not_act_yet.lower()
    assert "maintain_and_monitor" in pm.response_categories
    assert set(pm.response_categories).issubset(ALLOWED_RESPONSE_CATEGORIES)
    assert demo_run.deterministic_input.to_dict() == before_card
    assert demo_run.unwind.to_dict() == before_unwind


def test_short_side_stress_prioritizes_short_basket(demo_run) -> None:
    card = _force_signal_triggered(
        demo_run.deterministic_input, "short_loss_in_recovery"
    )
    unwind = _with_mechanism_status(
        demo_run.unwind, "short_book_reversal_crash", "triggered"
    )
    before_card = card.to_dict()
    before_unwind = unwind.to_dict()

    context = derive_pm_context(card, unwind)
    pm = build_pm_response(card, unwind, use_llm=False)

    assert context.vulnerability == "short_basket"
    assert context.posture == "escalate_for_pm_review"
    assert "review_short_loss_contributors" in pm.response_categories
    assert "run_loser_rally_stress" in pm.response_categories
    assert "consider_reducing_short_exposure" in pm.response_categories
    assert "short basket" in pm.main_vulnerability.lower()
    assert "escalate" in pm.current_state.lower()
    assert card.to_dict() == before_card
    assert unwind.to_dict() == before_unwind


def test_unknown_response_categories_are_rejected(demo_run) -> None:
    context = derive_pm_context(demo_run.deterministic_input, demo_run.unwind)
    payload = _valid_pm_payload(context)
    payload["selected_categories"] = (
        "maintain_and_monitor",
        "invented_category",
    )
    provider = _FixedPMInterpreter(payload)
    result = build_pm_response(
        demo_run.deterministic_input,
        demo_run.unwind,
        use_llm=True,
        interpreter=provider,
        environment={"OPENAI_API_KEY": "test-only"},
    )

    assert result.use_llm is False
    assert provider.calls == 1
    assert any("schema or safety validation" in warning for warning in result.warnings)
    assert "invented_category" not in result.response_categories


def test_bare_enum_slug_posture_is_rejected(demo_run) -> None:
    context = derive_pm_context(demo_run.deterministic_input, demo_run.unwind)
    payload = _valid_pm_payload(context)
    payload["current_state"] = "monitor_more_closely"
    payload["main_vulnerability"] = "broader_strategy_drawdown"
    result = build_pm_response(
        demo_run.deterministic_input,
        demo_run.unwind,
        use_llm=True,
        interpreter=_FixedPMInterpreter(payload),
        environment={"DEEPSEEK_API_KEY": "test-only"},
    )

    assert result.use_llm is False
    assert any("schema or safety validation" in warning for warning in result.warnings)


def test_security_specific_and_sized_advice_rejected(demo_run) -> None:
    context = derive_pm_context(demo_run.deterministic_input, demo_run.unwind)
    payload = _valid_pm_payload(context)
    payload["conditional_response"] = (
        "Sell 50% of AAPL shares and hedge with 100 contracts.",
    )
    result = build_pm_response(
        demo_run.deterministic_input,
        demo_run.unwind,
        use_llm=True,
        interpreter=_FixedPMInterpreter(payload),
        environment={"OPENAI_API_KEY": "test-only"},
    )

    assert result.use_llm is False
    assert any("schema or safety validation" in warning for warning in result.warnings)


def test_conditional_pm_language_is_accepted(demo_run) -> None:
    context = derive_pm_context(demo_run.deterministic_input, demo_run.unwind)
    payload = _valid_pm_payload(context)
    payload["conditional_response"] = (
        "If confirmed, consider a temporary beta hedge subject to PM review.",
        "Consider reducing short exposure if losses broaden, subject to PM review.",
    )
    provider = _FixedPMInterpreter(payload)
    result = build_pm_response(
        demo_run.deterministic_input,
        demo_run.unwind,
        use_llm=True,
        interpreter=provider,
        environment={"OPENAI_API_KEY": "test-only"},
    )

    assert result.use_llm is True
    assert provider.calls == 1
    assert "beta hedge" in " ".join(result.conditional_response).lower()
    assert set(result.response_categories).issubset(context.allowed_categories)


def test_invalid_model_output_falls_back(demo_run) -> None:
    payload = _valid_pm_payload(
        derive_pm_context(demo_run.deterministic_input, demo_run.unwind)
    )
    payload["extra_field"] = "not allowed"
    result = build_pm_response(
        demo_run.deterministic_input,
        demo_run.unwind,
        use_llm=True,
        interpreter=_FixedPMInterpreter(payload),
        environment={"OPENAI_API_KEY": "test-only"},
    )

    assert result.use_llm is False
    assert result.model_or_prompt_version == DETERMINISTIC_PM_RESPONSE_VERSION
    assert any("schema or safety validation" in warning for warning in result.warnings)


def test_offline_mode_remains_usable(demo_run) -> None:
    provider = _FixedPMInterpreter(
        _valid_pm_payload(
            derive_pm_context(demo_run.deterministic_input, demo_run.unwind)
        )
    )
    offline = build_pm_response(
        demo_run.deterministic_input,
        demo_run.unwind,
        use_llm=False,
        interpreter=provider,
    )
    no_creds = build_pm_response(
        demo_run.deterministic_input,
        demo_run.unwind,
        use_llm=True,
        interpreter=provider,
        environment={},
    )

    assert offline.use_llm is False
    assert no_creds.use_llm is False
    assert provider.calls == 0
    assert offline.current_state
    assert offline.conditional_response
    assert "premature" in offline.why_not_act_yet.lower() or offline.why_not_act_yet


def test_ai_cannot_change_deterministic_states_or_triggers(demo_run) -> None:
    card = demo_run.deterministic_input
    unwind = demo_run.unwind
    before_card = card.to_dict()
    before_unwind = unwind.to_dict()
    context = derive_pm_context(card, unwind)
    payload = _valid_pm_payload(context)
    payload["current_state"] = (
        "Escalate for PM review even though nothing triggered."
    )

    result = build_pm_response(
        card,
        unwind,
        use_llm=True,
        interpreter=_FixedPMInterpreter(payload),
        environment={"OPENAI_API_KEY": "test-only"},
    )

    assert card.to_dict() == before_card
    assert unwind.to_dict() == before_unwind
    assert card.overall_risk_state == before_card["overall_risk_state"]
    assert card.deterministic_score is None
    assert [row["triggered"] for row in before_unwind["scorecard"]] == [
        row.triggered for row in unwind.scorecard
    ]
    assert result.use_llm is True


def test_presentation_includes_pm_response_section(demo_run) -> None:
    html = render_pm_card_html(demo_run)
    markdown = render_pm_risk_markdown(demo_run)

    assert "Current state" in html
    assert "Main vulnerability" in html
    assert "What would change the reading" in html
    assert "Conditional portfolio response" in html
    assert "Why not act yet" in html
    assert "PM response (decision support)" in markdown
    assert "Bounded categories:" in html


def test_pm_response_schema_rejects_unknown_category() -> None:
    with pytest.raises(ValueError, match="unknown response categories"):
        PMResponse(
            current_state="Maintain and monitor.",
            main_vulnerability="Market backdrop only.",
            what_would_change_the_reading=("Watch for confirmation.",),
            conditional_response=("Maintain and monitor.",),
            why_not_act_yet="Broad action would be premature.",
            response_categories=("not_a_real_category",),
        )
