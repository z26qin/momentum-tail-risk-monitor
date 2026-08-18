"""Hand-written investigation agent on top of the deterministic monitor.

Invariant 1: The agent cannot modify deterministic risk state.
Invariant 2: No evidence published after assessment_cutoff is admitted.
Invariant 3: Missing evidence remains missing (no hallucination).
Invariant 4: LLM interpretation cannot trigger portfolio actions.
Invariant 5: max_steps prevents runaway loops.

The quantitative engine owns the risk state. This module owns the loop:
observe → decide → act → remember → stop.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from src.agent_prompts import (
    MECHANISM_LABELS,
    MECHANISM_QUERIES,
    as_document,
    crowding_signal_present,
    format_pm_report,
    heuristic_classify,
    llm_classify,
    no_meaningful_risk_signal,
    published_by_cutoff,
    query_from_question,
    recovery_setup_present,
    retrieve_local_evidence,
    search_news,
    search_social,
    want_fundamentals,
)
from src.utils.market_time import assessment_timestamp

FINISH, SEARCH_KL_CROWDING = "FINISH", "SEARCH_KL_CROWDING"
SEARCH_DM_RECOVERY, SEARCH_FUNDAMENTALS = "SEARCH_DM_RECOVERY", "SEARCH_FUNDAMENTALS"
FOLLOWUP_SEARCH, SCORECARD_SIGNAL_COUNT = "FOLLOWUP_SEARCH", 4
ACTION_TO_MECHANISM = {
    SEARCH_KL_CROWDING: "kl_crowding",
    SEARCH_DM_RECOVERY: "dm_recovery",
    SEARCH_FUNDAMENTALS: "fundamentals",
}
ACTION_TO_TOOL = {
    SEARCH_KL_CROWDING: "local_evidence",
    SEARCH_DM_RECOVERY: "search_news",
    SEARCH_FUNDAMENTALS: "local_evidence",
}
PATH_NOTES = {
    SEARCH_KL_CROWDING: ("Detected crowding signal", "Searched positioning evidence"),
    SEARCH_DM_RECOVERY: ("Searched DM recovery evidence",),
    SEARCH_FUNDAMENTALS: ("Searched fundamental / earnings evidence",),
    FOLLOWUP_SEARCH: ("Ran narrower follow-up search",),
}


@dataclass(frozen=True)
class AgentAction:
    name: str
    tool: str | None = None
    query: str | None = None
    reason: str | None = None


@dataclass
class AgentState:
    as_of_date: str
    assessment_cutoff: str
    risk_state: dict[str, Any]
    evidence: list[dict[str, Any]] = field(default_factory=list)
    query_history: list[str] = field(default_factory=list)
    action_history: list[dict[str, Any]] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    investigated_mechanisms: set[str] = field(default_factory=set)
    path: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    last_assessment: dict[str, Any] | None = None
    step: int = 0
    max_steps: int = 4
    status: str = "running"
    stop_reason: str | None = None
    followup_count: int = 0


@dataclass(frozen=True)
class AgentReport:
    as_of_date: str
    stop_reason: str
    report: str
    logs: tuple[str, ...]
    evidence: tuple[dict[str, Any], ...]
    action_history: tuple[dict[str, Any], ...]
    last_assessment: dict[str, Any] | None
    risk_state: dict[str, Any]
    state: AgentState


def default_tool_registry() -> dict[str, Callable[..., list[dict[str, Any]]]]:
    return {"search_news": search_news, "search_social": search_social, "local_evidence": retrieve_local_evidence}


def _log(state: AgentState, message: str, *, verbose: bool) -> None:
    line = f"[Agent {state.step}] {message}"
    state.logs.append(line)
    if verbose:
        print(line)


def _fresh(state: AgentState, query: str) -> bool:
    needle = " ".join(query.lower().split())
    return needle not in {" ".join(item.lower().split()) for item in state.query_history}


def observe(state: AgentState) -> dict[str, Any]:
    return {
        "trigger_count": int(state.risk_state.get("deterministic_trigger_count") or 0),
        "crowding": crowding_signal_present(state),
        "recovery": recovery_setup_present(state),
        "investigated": sorted(state.investigated_mechanisms),
        "evidence_count": len(state.evidence),
        "last_assessment": (state.last_assessment or {}).get("assessment"),
        "open_questions": list(state.open_questions),
        "remaining_steps": state.max_steps - state.step,
        "queries": list(state.query_history),
    }


def decide_next_action(
    state: AgentState, observation: Mapping[str, Any] | None = None
) -> AgentAction:
    """Next action depends on the current observation, memory, and remaining budget."""

    obs = observation or observe(state)
    if obs["remaining_steps"] <= 0:
        return AgentAction(FINISH, reason="MAX_STEPS")
    if no_meaningful_risk_signal(state) and not state.investigated_mechanisms:
        return AgentAction(FINISH, reason="NO_INVESTIGATION_NEEDED")
    planned = (
        (SEARCH_KL_CROWDING, crowding_signal_present(state) and "kl_crowding" not in state.investigated_mechanisms, "kl_crowding"),
        (SEARCH_DM_RECOVERY, recovery_setup_present(state) and "dm_recovery" not in state.investigated_mechanisms, "dm_recovery"),
        (SEARCH_FUNDAMENTALS, want_fundamentals(state), "fundamentals"),
    )
    for name, needed, mechanism in planned:
        query = MECHANISM_QUERIES[mechanism]
        if needed and _fresh(state, query):
            return AgentAction(name, tool=ACTION_TO_TOOL[name], query=query)
    incomplete = (
        state.followup_count < 1
        and bool(state.investigated_mechanisms)
        and (state.last_assessment or {}).get("assessment") in {"insufficient", "mixed", None}
    )
    if incomplete:
        question = (state.last_assessment or {}).get("next_question") or (
            state.open_questions[-1] if state.open_questions else None
        )
        query = query_from_question(question)
        if query and _fresh(state, query):
            last_tool = state.action_history[-1].get("tool") if state.action_history else None
            tool = "search_social" if last_tool == "search_news" else "search_news"
            return AgentAction(FOLLOWUP_SEARCH, tool=tool, query=query)
    if (state.last_assessment or {}).get("assessment") in {"supporting", "contradicting"}:
        return AgentAction(FINISH, reason="EVIDENCE_SUFFICIENT")
    reason = "EVIDENCE_INSUFFICIENT" if state.investigated_mechanisms else "NO_INVESTIGATION_NEEDED"
    return AgentAction(FINISH, reason=reason)


def execute_tool(action: AgentAction, state: AgentState, tools: Mapping[str, Callable[..., list]]) -> dict[str, Any]:
    if action.name == FINISH or not action.tool or not action.query or not _fresh(state, action.query):
        return {"documents": [], "valid": 0, "discarded": 0, "skipped": "duplicate_or_finish"}
    raw = tools[action.tool](action.query, state.assessment_cutoff, as_of_date=state.as_of_date)
    if not isinstance(raw, list):
        raise TypeError(f"{action.tool} must return a list")
    valid = []
    for item in raw:
        doc = item if "published_at" in item else as_document(item, query=action.query, channel=action.tool)
        if published_by_cutoff(doc["published_at"], state.assessment_cutoff, state.as_of_date):
            valid.append(doc)
    return {"documents": valid, "valid": len(valid), "discarded": len(raw) - len(valid)}


def update_memory(state: AgentState, action: AgentAction, result: Mapping[str, Any]) -> AgentState:
    state.action_history.append(
        {"name": action.name, "tool": action.tool, "query": action.query, "retrieved": result.get("valid", 0)}
    )
    if action.query:
        state.query_history.append(action.query)
    if action.name in ACTION_TO_MECHANISM:
        state.investigated_mechanisms.add(ACTION_TO_MECHANISM[action.name])
    if action.name == FOLLOWUP_SEARCH:
        state.followup_count += 1
    seen = {item.get("evidence_id") or item.get("headline") for item in state.evidence}
    for item in result.get("documents") or []:
        key = item.get("evidence_id") or item.get("headline")
        if key not in seen:
            state.evidence.append(item)
            seen.add(key)
    state.path.extend(PATH_NOTES.get(action.name, ()))
    return state


def should_stop(state: AgentState) -> bool:
    return state.status != "running" or state.step >= state.max_steps


def classify_evidence(
    state: AgentState,
    *,
    classify: Callable[[AgentState], dict[str, Any]] | None = None,
    use_llm: bool = False,
) -> dict[str, Any]:
    """Invariant 3/4: classification cannot fill gaps or trigger trades."""

    if classify is not None:
        return classify(state)
    mechanism = ACTION_TO_MECHANISM.get(
        str((state.action_history or [{}])[-1].get("name")),
        next(iter(state.investigated_mechanisms), None),
    )
    if use_llm:
        try:
            parsed = llm_classify(state, mechanism)
            if parsed:
                return parsed
        except Exception:  # noqa: BLE001 - fail closed to heuristic
            pass
    return heuristic_classify(state.evidence, mechanism=mechanism)


def build_pm_report(state: AgentState) -> str:
    primary = "kl_crowding" if crowding_signal_present(state) else next(iter(state.investigated_mechanisms), None)
    return format_pm_report(
        trigger_count=int(state.risk_state.get("deterministic_trigger_count") or 0),
        total_triggers=SCORECARD_SIGNAL_COUNT,
        primary_mechanism=MECHANISM_LABELS.get(primary or "", "None"),
        assessment=state.last_assessment,
        path=state.path,
        stop_reason=state.stop_reason or "MAX_STEPS",
    )


def run_investigation_loop(
    state: AgentState,
    *,
    tools: Mapping[str, Callable[..., list]],
    classify: Callable[[AgentState], dict[str, Any]] | None = None,
    use_llm: bool = False,
    verbose: bool = True,
) -> AgentState:
    """The agent loop.

    It observes the current state, chooses an action, executes a tool,
    updates memory, and decides whether another investigation step is justified.
    """

    fingerprint = json.dumps(state.risk_state, sort_keys=True, default=str)
    while not should_stop(state):
        observation = observe(state)
        action = decide_next_action(state, observation)
        if action.name == FINISH:
            state.status, state.stop_reason = "stopped", action.reason or "EVIDENCE_INSUFFICIENT"
            state.path.append("Stopped")
            _log(state, f"stop={state.stop_reason}", verbose=verbose)
            break
        state.step += 1
        _log(state, f"action={action.name}", verbose=verbose)
        try:
            result = execute_tool(action, state, tools)
        except Exception as exc:  # noqa: BLE001 - fail closed; do not fabricate evidence
            state.action_history.append(
                {"name": action.name, "tool": action.tool, "query": action.query, "error": str(exc)}
            )
            state.status, state.stop_reason = "stopped", "TOOL_FAILURE"
            state.path.extend(("Tool failed; no evidence fabricated", "Stopped"))
            _log(state, "stop=TOOL_FAILURE", verbose=verbose)
            break
        _log(state, f"retrieved={result.get('valid', 0)} valid documents", verbose=verbose)
        update_memory(state, action, result)
        state.last_assessment = classify_evidence(state, classify=classify, use_llm=use_llm)
        _log(state, f"assessment={str(state.last_assessment.get('assessment', 'insufficient')).upper()}", verbose=verbose)
        question = state.last_assessment.get("next_question")
        if question:
            if question not in state.open_questions:
                state.open_questions.append(str(question))
            _log(state, f"next_question={question!r}", verbose=verbose)
        if action.name == SEARCH_KL_CROWDING and (state.last_assessment.get("supported_claims") or []):
            state.path.extend(("Found technology exposure reduction", "Evidence insufficient for forced deleveraging"))
        if action.name == FOLLOWUP_SEARCH and not result.get("valid"):
            state.path.append("No confirming evidence found")
        if should_stop(state) and state.status == "running":
            state.status, state.stop_reason = "stopped", "MAX_STEPS"
            state.path.append("Stopped")
            _log(state, "stop=MAX_STEPS", verbose=verbose)
            break
    assert json.dumps(state.risk_state, sort_keys=True, default=str) == fingerprint  # Invariant 1
    if state.status == "running":
        state.status, state.stop_reason = "stopped", "MAX_STEPS"
        state.path.append("Stopped")
        _log(state, "stop=MAX_STEPS", verbose=verbose)
    return state


def run_investigation_agent(
    as_of_date: str = "2026-05-29",
    max_steps: int = 4,
    verbose: bool = True,
    *,
    risk_state: Mapping[str, Any] | None = None,
    mvp_result: Any | None = None,
    tools: Mapping[str, Callable[..., list]] | None = None,
    classify: Callable[[AgentState], dict[str, Any]] | None = None,
    use_llm: bool = False,
) -> AgentReport:
    """Public entry: load immutable risk state, then run the investigation loop."""

    if risk_state is not None:
        loaded = copy.deepcopy(dict(risk_state))
    elif mvp_result is not None:
        from src.mvp.hermes_monitor import compact_assessment_from_result

        loaded = compact_assessment_from_result(mvp_result)
    else:
        from src.mvp.hermes_monitor import run_compact_assessment

        loaded = run_compact_assessment(as_of_date=as_of_date)
    state = AgentState(
        as_of_date=str(loaded.get("as_of_date") or as_of_date),
        assessment_cutoff=str(loaded.get("data_cutoff") or assessment_timestamp(as_of_date)),
        risk_state=loaded,
        max_steps=max_steps,
    )
    triggers = int(loaded.get("deterministic_trigger_count") or 0)
    _log(state, f"deterministic state loaded: {triggers}/{SCORECARD_SIGNAL_COUNT} triggers", verbose=verbose)
    if no_meaningful_risk_signal(state):
        state.path.append("No meaningful risk signal")
    registry = default_tool_registry()
    if tools:
        registry.update(tools)
    run_investigation_loop(state, tools=registry, classify=classify, use_llm=use_llm, verbose=verbose)
    return AgentReport(
        as_of_date=state.as_of_date,
        stop_reason=state.stop_reason or "MAX_STEPS",
        report=build_pm_report(state),
        logs=tuple(state.logs),
        evidence=tuple(state.evidence),
        action_history=tuple(state.action_history),
        last_assessment=state.last_assessment,
        risk_state=copy.deepcopy(state.risk_state),
        state=state,
    )
