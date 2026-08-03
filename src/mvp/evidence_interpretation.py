"""Optional, evidence-aware interpretation of deterministic Evidence Card input.

The quantitative input is immutable and remains the source of truth. An
injected provider receives only an allow-listed copy of deterministic signals,
retrieved evidence, historical context, and compact structural/mechanical
unwind summaries, and may return only narrative fields plus evidence IDs. The
module has no model SDK dependency and always falls back to calibrated
deterministic text when credentials, a provider, or a valid structured
response are unavailable.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.mvp.evidence_card import DeterministicEvidenceInput


INTERPRETATION_SCHEMA_VERSION = "evidence-interpretation-v1"
INTERPRETATION_PROMPT_VERSION = "evidence-interpretation-prompt-v2"
DETERMINISTIC_INTERPRETATION_VERSION = "deterministic-evidence-interpretation-v2"
INTERPRETATION_INSTRUCTIONS = """\
Return only the eight EvidenceInterpretation narrative fields.

Compare these three lenses separately and allow mixed or unresolved results:
1) Daniel-Moskowitz recovery crash
2) Khandani-Lo crowded unwind
3) Fundamental or sector-specific repricing

Use only the supplied quantitative signals, retrieved evidence, historical
context, and the compact structural_unwind and mechanical_unwind summaries.
Distinguish quantitative scorecard state from structural and mechanical state.
State where structured and textual evidence agree or conflict. Identify missing
evidence for factor propagation or liquidity failure. Cite evidence by supplied
evidence_id only; contextual evidence may be discussed but cannot be treated as
stance-confirmed support. Do not invent channels, calculate or restate numbers,
alter values or trigger states, add external facts, assert causality or crash
certainty, estimate probabilities, or give portfolio or trade recommendations.
Return at most three concrete monitoring questions and at most three observable
invalidation conditions. State uncertainty explicitly."""

MODEL_OUTPUT_FIELDS = frozenset(
    {
        "narrative_state",
        "narrative_changes",
        "supporting_evidence_ids",
        "contradicting_evidence_ids",
        "missing_or_uncertain_evidence",
        "pm_interpretation",
        "monitoring_questions",
        "invalidation_conditions",
    }
)
MODEL_CONTEXT_FIELDS = frozenset(
    {
        "as_of_date",
        "comparison_date",
        "overall_risk_state",
        "deterministic_score",
        "quantitative_signals",
        "retrieved_evidence",
        "historical_context",
        "structural_unwind",
        "mechanical_unwind",
    }
)
LLM_CREDENTIAL_ENV_VARS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")

MAX_NARRATIVE_CHARS = 600
MAX_LIST_ITEMS = 8
MAX_LIST_ITEM_CHARS = 300
MAX_MONITORING_QUESTIONS = 3
MAX_INVALIDATION_CONDITIONS = 3
_NUMERIC_LITERAL = re.compile(r"(?<![A-Za-z0-9_])[+-]?\d+(?:\.\d+)?%?")
_NUMERIC_WORD = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
    r"eighty|ninety|hundred|thousand|million|billion|percent|"
    r"percentage)\b",
    re.IGNORECASE,
)
_PROHIBITED_CLAIMS = (
    re.compile(r"\b(?:caused|causes|proves|guarantees)\b", re.IGNORECASE),
    re.compile(r"\b(?:will|must|is certain to)\s+crash\b", re.IGNORECASE),
    re.compile(
        r"\bcrash\s+is\s+(?:certain|guaranteed|inevitable)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:recommend|recommendation|should)\s+"
        r"(?:buy|sell|short|overweight|underweight)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:buy|sell|overweight|underweight|hedge)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:increase|decrease|add|reduce|cut)\s+(?:the\s+)?"
        r"(?:position|exposure|allocation)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:go|stay)\s+(?:long|short)\b", re.IGNORECASE),
)

_EMPTY_STRUCTURAL_UNWIND = {
    "scenario_classification": None,
    "active_scenarios": [],
    "mechanism_statuses": {},
}
_EMPTY_MECHANICAL_UNWIND = {
    "unwind_state": None,
    "liquidity_absorption_failure": None,
    "factor_footprint_status": "unavailable",
    "aligned_turnover_status": "unavailable",
}


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{name} cannot be empty")
    if len(cleaned) > MAX_NARRATIVE_CHARS:
        raise ValueError(f"{name} exceeds {MAX_NARRATIVE_CHARS} characters")
    return cleaned


def _text_tuple(value: Any, name: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be a list of strings")
    items: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise ValueError(f"{name} entries must be strings")
        cleaned = entry.strip()
        if not cleaned:
            raise ValueError(f"{name} entries cannot be empty")
        if len(cleaned) > MAX_LIST_ITEM_CHARS:
            raise ValueError(
                f"{name} entry exceeds {MAX_LIST_ITEM_CHARS} characters"
            )
        items.append(cleaned)
    if len(items) > MAX_LIST_ITEMS:
        raise ValueError(f"{name} exceeds {MAX_LIST_ITEMS} entries")
    return tuple(items)


def _identifier_tuple(value: Any, name: str) -> tuple[str, ...]:
    identifiers = _text_tuple(value, name)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{name} must not contain duplicate evidence IDs")
    return identifiers


@dataclass(frozen=True)
class EvidenceInterpretation:
    """Validated narrative-only result with evidence-ID references."""

    narrative_state: str
    narrative_changes: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...]
    contradicting_evidence_ids: tuple[str, ...]
    missing_or_uncertain_evidence: tuple[str, ...]
    pm_interpretation: str
    monitoring_questions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    use_llm: bool = False
    model_or_prompt_version: str = DETERMINISTIC_INTERPRETATION_VERSION
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "narrative_state", _text(self.narrative_state, "narrative_state")
        )
        object.__setattr__(
            self,
            "narrative_changes",
            _text_tuple(self.narrative_changes, "narrative_changes"),
        )
        object.__setattr__(
            self,
            "supporting_evidence_ids",
            _identifier_tuple(
                self.supporting_evidence_ids, "supporting_evidence_ids"
            ),
        )
        object.__setattr__(
            self,
            "contradicting_evidence_ids",
            _identifier_tuple(
                self.contradicting_evidence_ids, "contradicting_evidence_ids"
            ),
        )
        object.__setattr__(
            self,
            "missing_or_uncertain_evidence",
            _text_tuple(
                self.missing_or_uncertain_evidence,
                "missing_or_uncertain_evidence",
            ),
        )
        object.__setattr__(
            self,
            "pm_interpretation",
            _text(self.pm_interpretation, "pm_interpretation"),
        )
        object.__setattr__(
            self,
            "monitoring_questions",
            _text_tuple(self.monitoring_questions, "monitoring_questions"),
        )
        object.__setattr__(
            self,
            "invalidation_conditions",
            _text_tuple(self.invalidation_conditions, "invalidation_conditions"),
        )
        if not isinstance(self.use_llm, bool):
            raise ValueError("use_llm must be a boolean")
        object.__setattr__(
            self,
            "model_or_prompt_version",
            _text(self.model_or_prompt_version, "model_or_prompt_version"),
        )
        object.__setattr__(
            self, "warnings", _text_tuple(self.warnings, "warnings")
        )

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@runtime_checkable
class EvidenceInterpreter(Protocol):
    """Provider-neutral structured interpretation interface."""

    def interpret(
        self,
        *,
        context: dict[str, Any],
        instructions: str,
    ) -> Mapping[str, Any]: ...


def _elevated_flag_status(value: Any) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, float) and value != value:  # NaN
        return "unavailable"
    return "elevated" if bool(value) else "not_elevated"


def _mechanical_history_row(mechanical: Any) -> Any | None:
    history = getattr(mechanical, "history", None)
    if history is None or not hasattr(history, "empty") or history.empty:
        return None
    as_of = getattr(mechanical, "as_of_date", None)
    if as_of is not None and "date" in getattr(history, "columns", []):
        as_of_text = str(as_of)[:10]
        matched = history.loc[history["date"].astype(str).str[:10] == as_of_text]
        if not matched.empty:
            return matched.iloc[-1]
    return history.iloc[-1]


def compact_structural_unwind_context(unwind: Any) -> dict[str, Any]:
    """Project an UnwindAssessment into the compact interpretation context."""

    return {
        "scenario_classification": getattr(unwind, "scenario_classification", None),
        "active_scenarios": list(getattr(unwind, "active_scenarios", ()) or ()),
        "mechanism_statuses": {
            item.scenario: item.status
            for item in getattr(unwind, "mechanism_scenarios", ()) or ()
        },
    }


def compact_mechanical_unwind_context(mechanical: Any) -> dict[str, Any]:
    """Project a MechanicalUnwindAssessment into compact status fields.

    Copies elevation statuses already computed during mechanical classification.
    Does not re-apply ``DEFAULT_MECHANICAL_UNWIND_CONFIG`` thresholds.
    """

    if isinstance(mechanical, Mapping):
        return {
            "unwind_state": mechanical.get("unwind_state"),
            "liquidity_absorption_failure": mechanical.get(
                "liquidity_absorption_failure"
            ),
            "factor_footprint_status": mechanical.get(
                "factor_footprint_status", "unavailable"
            ),
            "aligned_turnover_status": mechanical.get(
                "aligned_turnover_status", "unavailable"
            ),
        }

    row = _mechanical_history_row(mechanical)
    footprint_status = "unavailable"
    turnover_status = "unavailable"
    if row is not None:
        if "factor_footprint_elevated" in getattr(row, "index", []):
            footprint_status = _elevated_flag_status(row["factor_footprint_elevated"])
        if "aligned_turnover_elevated" in getattr(row, "index", []):
            turnover_status = _elevated_flag_status(row["aligned_turnover_elevated"])

    return {
        "unwind_state": getattr(mechanical, "unwind_state", None),
        "liquidity_absorption_failure": getattr(
            mechanical, "liquidity_absorption_failure", None
        ),
        "factor_footprint_status": footprint_status,
        "aligned_turnover_status": turnover_status,
    }


def _normalize_structural_unwind(
    structural_unwind: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if structural_unwind is None:
        return dict(_EMPTY_STRUCTURAL_UNWIND)
    payload = {
        "scenario_classification": structural_unwind.get("scenario_classification"),
        "active_scenarios": list(structural_unwind.get("active_scenarios") or []),
        "mechanism_statuses": dict(
            structural_unwind.get("mechanism_statuses") or {}
        ),
    }
    return json.loads(json.dumps(payload, sort_keys=True, allow_nan=False))


def _normalize_mechanical_unwind(
    mechanical_unwind: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if mechanical_unwind is None:
        return dict(_EMPTY_MECHANICAL_UNWIND)
    payload = {
        "unwind_state": mechanical_unwind.get("unwind_state"),
        "liquidity_absorption_failure": mechanical_unwind.get(
            "liquidity_absorption_failure"
        ),
        "factor_footprint_status": mechanical_unwind.get(
            "factor_footprint_status", "unavailable"
        ),
        "aligned_turnover_status": mechanical_unwind.get(
            "aligned_turnover_status", "unavailable"
        ),
    }
    return json.loads(json.dumps(payload, sort_keys=True, allow_nan=False))


def _structural_or_mechanical_active(
    structural_unwind: Mapping[str, Any],
    mechanical_unwind: Mapping[str, Any],
) -> bool:
    if structural_unwind.get("active_scenarios"):
        return True
    statuses = structural_unwind.get("mechanism_statuses") or {}
    if any(status in {"watch", "triggered"} for status in statuses.values()):
        return True
    state = mechanical_unwind.get("unwind_state")
    if state not in {None, "NORMAL"}:
        return True
    if mechanical_unwind.get("liquidity_absorption_failure") is True:
        return True
    if mechanical_unwind.get("factor_footprint_status") == "elevated":
        return True
    if mechanical_unwind.get("aligned_turnover_status") == "elevated":
        return True
    return False


def _model_context(
    deterministic_input: DeterministicEvidenceInput,
    *,
    structural_unwind: Mapping[str, Any] | None = None,
    mechanical_unwind: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a detached allow-listed model payload."""

    context = {
        "as_of_date": deterministic_input.as_of_date,
        "comparison_date": deterministic_input.comparison_date,
        "overall_risk_state": deterministic_input.overall_risk_state,
        "deterministic_score": deterministic_input.deterministic_score,
        "quantitative_signals": [
            signal.to_dict()
            for signal in (
                deterministic_input.triggered_quant_signals
                + deterministic_input.non_triggered_relevant_signals
            )
        ],
        "retrieved_evidence": [
            item.to_dict() for item in deterministic_input.retrieved_evidence
        ],
        "historical_context": [
            dict(item) for item in deterministic_input.historical_analogs
        ],
        "structural_unwind": _normalize_structural_unwind(structural_unwind),
        "mechanical_unwind": _normalize_mechanical_unwind(mechanical_unwind),
    }
    if frozenset(context) != MODEL_CONTEXT_FIELDS:
        raise AssertionError("model context allow-list changed unexpectedly")
    return json.loads(json.dumps(context, sort_keys=True, allow_nan=False))


def _unique(items: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    for item in items:
        cleaned = item.strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return tuple(result[:MAX_LIST_ITEMS])


def _deterministic_changes(
    deterministic_input: DeterministicEvidenceInput,
    *,
    structural_unwind: Mapping[str, Any],
    mechanical_unwind: Mapping[str, Any],
) -> tuple[str, ...]:
    changes: list[str] = []
    if deterministic_input.comparison_date is None:
        changes.append(
            "No comparison date was supplied, so comparison changes are unavailable."
        )
    else:
        for signal in (
            deterministic_input.triggered_quant_signals
            + deterministic_input.non_triggered_relevant_signals
        ):
            if signal.change_vs_comparison is None:
                continue
            if abs(signal.change_vs_comparison) <= 1e-12:
                movement = "was unchanged"
            elif signal.change_vs_comparison > 0:
                movement = "increased"
            else:
                movement = "decreased"
            status = signal.status.replace("_", " ")
            changes.append(
                f"{signal.name.replace('_', ' ')} {movement} and is currently {status}."
            )
        if not changes:
            changes.append(
                "No supported comparison changes are available for the monitored signals."
            )

    active = list(structural_unwind.get("active_scenarios") or [])
    if active:
        changes.append(
            "Structural unwind active scenarios: " + ", ".join(active) + "."
        )
    state = mechanical_unwind.get("unwind_state")
    if state not in {None, "NORMAL"}:
        absorption = mechanical_unwind.get("liquidity_absorption_failure")
        absorption_text = (
            "absorption failure present"
            if absorption is True
            else (
                "absorption failure absent"
                if absorption is False
                else "absorption status unavailable"
            )
        )
        changes.append(
            f"Mechanical unwind state is {state}, with "
            f"{mechanical_unwind.get('aligned_turnover_status', 'unavailable')} "
            f"aligned turnover and {absorption_text}."
        )
    return tuple(changes)[:MAX_LIST_ITEMS]


def _deterministic_interpretation(
    deterministic_input: DeterministicEvidenceInput,
    *,
    structural_unwind: Mapping[str, Any] | None = None,
    mechanical_unwind: Mapping[str, Any] | None = None,
    warnings: tuple[str, ...] = (),
) -> EvidenceInterpretation:
    triggered = deterministic_input.triggered_quant_signals
    evidence = deterministic_input.retrieved_evidence
    supporting_ids = tuple(
        item.evidence_id for item in evidence if item.stance == "supporting"
    )
    contradicting_ids = tuple(
        item.evidence_id for item in evidence if item.stance == "contradicting"
    )
    structural = _normalize_structural_unwind(structural_unwind)
    mechanical = _normalize_mechanical_unwind(mechanical_unwind)
    channel_active = _structural_or_mechanical_active(structural, mechanical)
    mechanism_statuses = structural.get("mechanism_statuses") or {}

    if triggered and channel_active:
        narrative_state = (
            "Quantitative scorecard triggers are active, and structural or "
            "mechanical unwind channels are also active. This warrants elevated "
            "monitoring and is not a confirmed crash forecast."
        )
    elif triggered:
        narrative_state = (
            "The deterministic state warrants elevated monitoring because at "
            "least one implemented quantitative fragility condition is "
            "triggered. This is not a confirmed crash forecast."
        )
    elif channel_active:
        narrative_state = (
            "Quantitative scorecard triggers are inactive, but structural or "
            "mechanical unwind channels are active and warrant elevated "
            "monitoring. This is not a confirmed crash forecast."
        )
    else:
        narrative_state = (
            "No quantitative scorecard fragility condition is currently "
            "triggered, and no active structural or mechanical unwind channel "
            "was supplied. This does not rule out risks outside the monitored "
            "set."
        )

    dm_status = mechanism_statuses.get("bear_market_recovery_crash", "unavailable")
    short_status = mechanism_statuses.get("short_book_reversal_crash", "unavailable")
    kl_status = mechanism_statuses.get("crowded_theme_unwind", "unavailable")
    mechanical_state = mechanical.get("unwind_state") or "unavailable"
    absorption = mechanical.get("liquidity_absorption_failure")

    if not evidence:
        evidence_view = (
            "Point-in-time evidence is unavailable, so the quantitative state "
            "cannot be corroborated or contradicted by the retrieval layer."
        )
    elif supporting_ids and contradicting_ids:
        evidence_view = (
            "The supplied point-in-time evidence is mixed and should be treated "
            "as context rather than a causal conclusion."
        )
    elif supporting_ids:
        evidence_view = (
            "Some supplied evidence supports the monitoring interpretation, "
            "but it does not establish causality or certainty."
        )
    elif contradicting_ids:
        evidence_view = (
            "Supplied contradicting evidence moderates the monitoring "
            "interpretation and argues against a confirmed forecast."
        )
    else:
        evidence_view = (
            "The supplied evidence is contextual and does not confirm or "
            "invalidate the deterministic state."
        )

    pm_interpretation = (
        f"{evidence_view} Lens read: DM recovery crash remains "
        f"{dm_status.replace('_', ' ')} on structural channels and "
        f"{short_status.replace('_', ' ')} for short-book reversal; "
        f"Khandani-Lo crowded unwind is {kl_status.replace('_', ' ')}; "
        f"fundamental repricing stays unconfirmed without a structured "
        f"fundamental anchor. Mechanical state is {mechanical_state}, with "
        f"liquidity absorption failure "
        f"{'present' if absorption is True else 'absent' if absorption is False else 'unavailable'}."
    )
    if len(pm_interpretation) > MAX_NARRATIVE_CHARS:
        pm_interpretation = pm_interpretation[: MAX_NARRATIVE_CHARS - 1].rstrip() + "."

    missing = list(deterministic_input.data_warnings)
    if not evidence:
        missing.insert(
            0,
            "No point-in-time evidence was supplied; evidence uncertainty is high.",
        )
    if absorption is not True:
        missing.append(
            "Liquidity-absorption failure is not confirmed; factor propagation remains uncertain."
        )
    if kl_status != "triggered":
        missing.append(
            "Broad crowded-unwind confirmation beyond the supplied structural channel is incomplete."
        )

    if channel_active:
        monitoring_questions = (
            "Does factor footprint or aligned turnover broaden beyond the active structural channel?",
            "Does liquidity absorption fail while losses remain synchronized?",
            "Do retrieved evidence stances shift from contextual or mixed toward clearer support or contradiction?",
        )
        invalidation_conditions = (
            "Active structural mechanisms return to not_confirmed and mechanical state normalizes.",
            "Liquidity absorption remains healthy while breadth stays confined.",
            "Supplied contradicting evidence materially weakens the monitored interpretation.",
        )
    else:
        monitoring_questions = (
            "Do currently triggered conditions remain beyond their thresholds?",
            "Do other monitored signals begin deteriorating together?",
            "Does newly retrieved evidence support or contradict the monitored mechanism?",
        )
        invalidation_conditions = (
            "Triggered conditions return to non-triggered states.",
            "Supplied contradicting evidence materially weakens the monitored interpretation.",
        )

    return EvidenceInterpretation(
        narrative_state=narrative_state,
        narrative_changes=_deterministic_changes(
            deterministic_input,
            structural_unwind=structural,
            mechanical_unwind=mechanical,
        ),
        supporting_evidence_ids=supporting_ids,
        contradicting_evidence_ids=contradicting_ids,
        missing_or_uncertain_evidence=_unique(missing),
        pm_interpretation=pm_interpretation,
        monitoring_questions=monitoring_questions[:MAX_MONITORING_QUESTIONS],
        invalidation_conditions=invalidation_conditions[
            :MAX_INVALIDATION_CONDITIONS
        ],
        use_llm=False,
        model_or_prompt_version=DETERMINISTIC_INTERPRETATION_VERSION,
        warnings=warnings,
    )


def _provider_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, EvidenceInterpretation):
        payload = {
            field: getattr(raw, field) for field in MODEL_OUTPUT_FIELDS
        }
    elif isinstance(raw, Mapping):
        payload = dict(raw)
    else:
        raise ValueError("interpreter output must be a mapping")
    missing = MODEL_OUTPUT_FIELDS.difference(payload)
    extra = set(payload).difference(MODEL_OUTPUT_FIELDS)
    if missing or extra:
        raise ValueError(
            "interpreter output fields do not match the schema "
            f"(missing={sorted(missing)}, extra={sorted(extra)})"
        )
    return payload


def _validate_llm_text(interpretation: EvidenceInterpretation) -> None:
    narrative_fields = (
        interpretation.narrative_state,
        *interpretation.narrative_changes,
        *interpretation.missing_or_uncertain_evidence,
        interpretation.pm_interpretation,
        *interpretation.monitoring_questions,
        *interpretation.invalidation_conditions,
    )
    for text in narrative_fields:
        if _NUMERIC_LITERAL.search(text) or _NUMERIC_WORD.search(text):
            raise ValueError("LLM narrative must not introduce numerical values")
        if any(pattern.search(text) for pattern in _PROHIBITED_CLAIMS):
            raise ValueError(
                "LLM narrative contains a causal, certainty, or recommendation claim"
            )


def _validated_provider_result(
    raw: Any,
    deterministic_input: DeterministicEvidenceInput,
) -> EvidenceInterpretation:
    payload = _provider_payload(raw)
    candidate = EvidenceInterpretation(
        **payload,
        use_llm=True,
        model_or_prompt_version=INTERPRETATION_PROMPT_VERSION,
        warnings=(),
    )
    if not 1 <= len(candidate.monitoring_questions) <= MAX_MONITORING_QUESTIONS:
        raise ValueError(
            f"LLM output must contain 1 to {MAX_MONITORING_QUESTIONS} "
            "monitoring questions"
        )
    if not (
        1 <= len(candidate.invalidation_conditions) <= MAX_INVALIDATION_CONDITIONS
    ):
        raise ValueError(
            f"LLM output must contain 1 to {MAX_INVALIDATION_CONDITIONS} "
            "invalidation conditions"
        )
    _validate_llm_text(candidate)

    evidence_by_id = {
        item.evidence_id: item for item in deterministic_input.retrieved_evidence
    }
    valid_supporting = tuple(
        evidence_id
        for evidence_id in candidate.supporting_evidence_ids
        if evidence_id in evidence_by_id
        and evidence_by_id[evidence_id].stance == "supporting"
    )
    valid_contradicting = tuple(
        evidence_id
        for evidence_id in candidate.contradicting_evidence_ids
        if evidence_id in evidence_by_id
        and evidence_by_id[evidence_id].stance == "contradicting"
    )
    removed = (
        set(candidate.supporting_evidence_ids).difference(valid_supporting)
        | set(candidate.contradicting_evidence_ids).difference(valid_contradicting)
    )
    warnings: list[str] = []
    if removed:
        warnings.append(
            "Unsupported or stance-inconsistent evidence IDs were removed: "
            + ", ".join(sorted(removed))
            + "."
        )

    missing = list(candidate.missing_or_uncertain_evidence)
    if not deterministic_input.retrieved_evidence:
        valid_supporting = ()
        valid_contradicting = ()
        missing.append(
            "No point-in-time evidence was supplied; evidence uncertainty is high."
        )
    return dataclasses.replace(
        candidate,
        supporting_evidence_ids=valid_supporting,
        contradicting_evidence_ids=valid_contradicting,
        missing_or_uncertain_evidence=_unique(missing),
        warnings=tuple(warnings),
    )


def _has_credentials(environment: Mapping[str, str]) -> bool:
    return any(environment.get(name, "").strip() for name in LLM_CREDENTIAL_ENV_VARS)


def interpret_evidence_card(
    deterministic_input: DeterministicEvidenceInput,
    *,
    use_llm: bool = True,
    interpreter: EvidenceInterpreter | None = None,
    environment: Mapping[str, str] | None = None,
    structural_unwind: Mapping[str, Any] | None = None,
    mechanical_unwind: Mapping[str, Any] | None = None,
) -> EvidenceInterpretation:
    """Interpret a deterministic card without exposing writable quant fields.

    A real provider is optional and injected through ``EvidenceInterpreter``.
    The repository intentionally contains no vendor client. Missing credentials,
    missing configuration, provider errors, and schema violations all return a
    deterministic interpretation with ``use_llm=False`` and a clear warning.
    Compact structural and mechanical summaries are optional read-only context.
    """

    if not isinstance(deterministic_input, DeterministicEvidenceInput):
        raise TypeError(
            "deterministic_input must be a DeterministicEvidenceInput"
        )
    before = json.dumps(
        deterministic_input.to_dict(), sort_keys=True, allow_nan=False
    )
    structural = _normalize_structural_unwind(structural_unwind)
    mechanical = _normalize_mechanical_unwind(mechanical_unwind)
    if not use_llm:
        return _deterministic_interpretation(
            deterministic_input,
            structural_unwind=structural,
            mechanical_unwind=mechanical,
        )

    configured_environment = os.environ if environment is None else environment
    if not _has_credentials(configured_environment):
        return _deterministic_interpretation(
            deterministic_input,
            structural_unwind=structural,
            mechanical_unwind=mechanical,
            warnings=(
                "LLM interpretation was requested, but no supported API "
                "credentials are present; use_llm was set to False and the "
                "deterministic interpretation was used.",
            ),
        )
    if interpreter is None:
        return _deterministic_interpretation(
            deterministic_input,
            structural_unwind=structural,
            mechanical_unwind=mechanical,
            warnings=(
                "LLM interpretation was requested, but no structured "
                "interpreter is configured; use_llm was set to False and the "
                "deterministic interpretation was used.",
            ),
        )

    try:
        raw = interpreter.interpret(
            context=_model_context(
                deterministic_input,
                structural_unwind=structural,
                mechanical_unwind=mechanical,
            ),
            instructions=INTERPRETATION_INSTRUCTIONS,
        )
        result = _validated_provider_result(raw, deterministic_input)
    except Exception as exc:  # noqa: BLE001 - interpretation must fail closed
        result = _deterministic_interpretation(
            deterministic_input,
            structural_unwind=structural,
            mechanical_unwind=mechanical,
            warnings=(
                "LLM interpretation failed schema or safety validation; "
                f"use_llm was set to False ({exc}).",
            ),
        )

    after = json.dumps(
        deterministic_input.to_dict(), sort_keys=True, allow_nan=False
    )
    if before != after:
        raise AssertionError("interpreter modified the deterministic input")
    return result
