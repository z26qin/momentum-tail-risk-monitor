"""Optional, evidence-aware interpretation of deterministic Evidence Card input.

The quantitative input is immutable and remains the source of truth. An
injected provider receives only an allow-listed copy of deterministic signals,
retrieved evidence, historical context, structural/mechanical unwind
summaries, and optional typed public positioning proxies. It may return only
narrative fields plus evidence IDs. The module has no model SDK dependency and
always falls back to calibrated deterministic text when credentials, a provider,
or a valid structured response are unavailable.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.mvp.evidence_card import DeterministicEvidenceInput


INTERPRETATION_SCHEMA_VERSION = "evidence-interpretation-v1"
INTERPRETATION_PROMPT_VERSION = "evidence-interpretation-prompt-v8"
DETERMINISTIC_INTERPRETATION_VERSION = "deterministic-evidence-interpretation-v2"
INTERPRETATION_INSTRUCTIONS = """\
Return only the eight EvidenceInterpretation narrative fields.
Write like a PM morning risk note: concise, conditional, and hierarchy-aware.

Compare these three lenses separately and allow mixed or unresolved results:
1) Daniel-Moskowitz recovery crash
2) Khandani-Lo crowded unwind
3) Fundamental or sector-specific repricing

Use only the supplied quantitative signals, retrieved evidence, historical
context, the structural_unwind and mechanical_unwind summaries, and
public_positioning_proxies when present. Quantitative signal context is
status-only (no raw levels or thresholds); public proxies may include state
labels without z-score magnitudes. Distinguish quantitative scorecard
state from structural and mechanical state. State where structured and textual
evidence agree or conflict. Identify missing evidence for factor propagation or
liquidity failure. Cite evidence by supplied evidence_id only; contextual
evidence may be discussed but cannot be treated as stance-confirmed support.

Critical wording (do not over-infer):
- Untriggered deterministic signals mean only that escalation thresholds are not
  breached. Never translate this into a "low-risk state", "benign risk", or
  "no risk". Prefer: signals remain below their escalation thresholds; the
  setup warrants monitoring but does not indicate an active momentum unwind.
- Do not say "the mechanical unwind is normal". Prefer: there is no evidence of
  a broad mechanical unwind / no broad mechanical unwind is confirmed.
- narrative_state must be short analyst prose (for example "Normal drawdown;
  no confirmed escalation"), never a bare slug such as normal_drawdown.
- When a short-interest proxy is elevated, say short-side crowding is plausible
  and that the short basket is the first area to review, while stating clearly
  that this does not establish active covering or forced deleveraging.
- If any structural mechanism is triggered (active_scenarios is non-empty),
  narrative_state must lead with that mechanism and must not say "normal
  drawdown", "no confirmed escalation", or describe a triggered mechanism as
  "watch".

public_positioning_proxies are a separate typed field of class
structured_public_proxy (FINRA, CFTC, or similar). Use them only as contextual
evidence. They must not be merged into retrieved_evidence, must not change
deterministic scorecard or mechanism states, and must not be used to infer
investor identity, hedge-fund ownership, common ownership, active short
covering, leverage or financing pressure, forced deleveraging, or causality.
Permitted example: public short-activity proxies are elevated in the loser
basket, increasing the relevance of short-side crowding as a hypothesis; the
data do not identify the underlying investors or establish active covering.
Prohibited example: hedge funds are covering crowded shorts.

When interpreting positioning or unwind-related evidence, answer for each
material item: (1) what was actually observed; (2) whose positioning or flow
the evidence represents, or unknown; (3) how broad the evidence is — name,
theme, sector, factor, or market; (4) what stronger conclusion remains
unproven. Keep these evidence classes separate and do not collapse them:
portfolio concentration or narrow breadth; public positioning proxies such as
short interest or CFTC data; reported investor flows such as Prime Book
commentary; market footprints such as correlated selling, turnover, or weak
liquidity; and hypotheses such as crowding, coordinated unwind, or forced
deleveraging. Do not infer common ownership from correlated selling; hedge-fund
selling from price or volume alone; single-stock momentum positioning from
index-futures data; short covering from loser-stock outperformance alone; or
forced deleveraging without direct evidence of leverage, margin pressure,
financing stress, or compulsory risk reduction. Prefer bounded positioning
states not_supported, crowding_plausible, localized_unwind_evidence, or
broad_unwind_risk; keep forced deleveraging separate and normally report
forced_deleveraging_unconfirmed. Prefer wording such as consistent with,
suggests localized exposure reduction, raises unwind sensitivity, does not establish,
or remains unconfirmed. Avoid claiming that positioning is unwinding, funds are
deleveraging, a quant unwind is confirmed, or that positioning caused the reversal.

Do not invent channels, calculate or restate numbers, alter values or trigger
states, add external facts, assert causality or crash certainty, estimate
probabilities, or give portfolio or trade recommendations. Keep
pm_interpretation to at most 1000 characters. Return at most three concrete
monitoring questions and at most three observable invalidation conditions.
monitoring_questions and invalidation_conditions must not include numbers,
percentages, or threshold literals (for example 0.71 or -20%); describe
signals and mechanisms in words only. State uncertainty explicitly."""

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
        "public_positioning_proxies",
    }
)
LLM_CREDENTIAL_ENV_VARS = (
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)

MAX_NARRATIVE_CHARS = 600
MAX_PM_INTERPRETATION_CHARS = 1000
MAX_LIST_ITEMS = 8
MAX_LIST_ITEM_CHARS = 300
MAX_MONITORING_QUESTIONS = 3
MAX_INVALIDATION_CONDITIONS = 3
_PUBLIC_PROXY_EVIDENCE_CLASS = "structured_public_proxy"
_PUBLIC_PROXY_SCOPE = (
    "Momentum loser / short-basket public-data proxy universe "
    "(not observed book ownership)"
)
_PUBLIC_PROXY_INFERENCE_LIMITS = (
    "Cannot identify underlying investors or hedge-fund ownership.",
    "Cannot establish common ownership, active short covering, leverage, "
    "financing pressure, forced deleveraging, or causality.",
    "Contextual only: cannot change scorecard values, thresholds, or "
    "mechanism triggers.",
)
_FINRA_METRIC_LABELS = (
    ("short_interest_ratio_z", "short_interest_ratio_z"),
    ("short_interest_utilisation_z", "short_interest_utilisation_z"),
    ("short_volume_share_z", "short_volume_share_z"),
)
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


def _text(
    value: Any, name: str, *, max_chars: int = MAX_NARRATIVE_CHARS
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{name} cannot be empty")
    if len(cleaned) > max_chars:
        raise ValueError(f"{name} exceeds {max_chars} characters")
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
            _text(
                self.pm_interpretation,
                "pm_interpretation",
                max_chars=MAX_PM_INTERPRETATION_CHARS,
            ),
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


def structural_unwind_summary(unwind: Any) -> dict[str, Any]:
    """Project an UnwindAssessment into the interpretation summary context."""

    return {
        "scenario_classification": getattr(unwind, "scenario_classification", None),
        "active_scenarios": list(getattr(unwind, "active_scenarios", ()) or ()),
        "mechanism_statuses": {
            item.scenario: item.status
            for item in getattr(unwind, "mechanism_scenarios", ()) or ()
        },
    }


def mechanical_unwind_summary(mechanical: Any) -> dict[str, Any]:
    """Project a MechanicalUnwindAssessment into interpretation status fields.

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


def _proxy_state(value: float | None, overlay_read: str | None) -> str:
    if value is None:
        return "unavailable"
    if value >= 1.0:
        return "elevated"
    if value <= -1.0:
        return "depressed"
    if overlay_read == "confirm":
        return "elevated_context"
    if overlay_read == "contradict":
        return "counter_context"
    return "neutral"


def _normalize_public_proxy_item(item: Mapping[str, Any]) -> dict[str, Any]:
    limitations = item.get("limitations") or ()
    if isinstance(limitations, str):
        limitation_list = [limitations]
    else:
        limitation_list = [str(entry) for entry in limitations if str(entry).strip()]
    if not limitation_list:
        raise ValueError("public_positioning_proxies items require limitations")
    payload = {
        "source": str(item.get("source") or "").strip(),
        "metric": str(item.get("metric") or "").strip(),
        "value": item.get("value"),
        "state": str(item.get("state") or "").strip() or None,
        "relevant_asset_or_portfolio_scope": str(
            item.get("relevant_asset_or_portfolio_scope") or ""
        ).strip(),
        "reporting_lag": str(item.get("reporting_lag") or "").strip(),
        "evidence_class": str(
            item.get("evidence_class") or _PUBLIC_PROXY_EVIDENCE_CLASS
        ).strip(),
        "limitations": limitation_list,
    }
    if not payload["source"] or not payload["metric"]:
        raise ValueError("public_positioning_proxies require source and metric")
    if not payload["relevant_asset_or_portfolio_scope"]:
        raise ValueError(
            "public_positioning_proxies require relevant_asset_or_portfolio_scope"
        )
    if not payload["reporting_lag"]:
        raise ValueError("public_positioning_proxies require reporting_lag")
    if payload["evidence_class"] != _PUBLIC_PROXY_EVIDENCE_CLASS:
        raise ValueError(
            "public_positioning_proxies evidence_class must be "
            f"{_PUBLIC_PROXY_EVIDENCE_CLASS}"
        )
    if payload["value"] is None and not payload["state"]:
        raise ValueError("public_positioning_proxies require value or state")
    return payload


def public_positioning_proxy_items(
    positioning: Any | None = None,
    *,
    items: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build typed public positioning proxies for interpretation context only.

    Accepts an optional FINRA ``PositioningSnapshot`` (or mapping with the same
    fields) and/or already-shaped proxy items such as future CFTC rows. Output
    never merges into ``retrieved_evidence`` and never alters deterministic
    scorecard or mechanism state.
    """

    proxies: list[dict[str, Any]] = []
    if items:
        for item in items:
            proxies.append(_normalize_public_proxy_item(item))

    if positioning is not None:
        if isinstance(positioning, Mapping):
            read = positioning.get("read")
            as_of_date = positioning.get("as_of_date")
            observation_date = positioning.get("observation_date")
            stale = positioning.get("stale_trading_days")
            base_limitations = tuple(positioning.get("limitations") or ())
            metric_values = {
                key: positioning.get(key) for key, _ in _FINRA_METRIC_LABELS
            }
        else:
            read = getattr(positioning, "read", None)
            as_of_date = getattr(positioning, "as_of_date", None)
            observation_date = getattr(positioning, "observation_date", None)
            stale = getattr(positioning, "stale_trading_days", None)
            base_limitations = tuple(getattr(positioning, "limitations", ()) or ())
            metric_values = {
                key: getattr(positioning, key, None) for key, _ in _FINRA_METRIC_LABELS
            }
        if read != "unavailable":
            if stale is None:
                lag = (
                    f"observation {observation_date}; as-of {as_of_date}"
                    if observation_date
                    else f"as-of {as_of_date}"
                )
            elif int(stale) == 0:
                lag = "same trading day as as-of"
            else:
                lag = f"{int(stale)} trading-day reporting lag vs as-of"
            limitations = tuple(base_limitations) + _PUBLIC_PROXY_INFERENCE_LIMITS
            for attr, metric in _FINRA_METRIC_LABELS:
                value = metric_values.get(attr)
                if value is None:
                    continue
                proxies.append(
                    _normalize_public_proxy_item(
                        {
                            "source": "FINRA",
                            "metric": metric,
                            "value": float(value),
                            "state": _proxy_state(float(value), str(read) if read else None),
                            "relevant_asset_or_portfolio_scope": _PUBLIC_PROXY_SCOPE,
                            "reporting_lag": lag,
                            "evidence_class": _PUBLIC_PROXY_EVIDENCE_CLASS,
                            "limitations": limitations,
                        }
                    )
                )

    return json.loads(
        json.dumps(proxies[:MAX_LIST_ITEMS], sort_keys=True, allow_nan=False)
    )


def _normalize_public_positioning_proxies(
    public_positioning_proxies: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not public_positioning_proxies:
        return []
    return public_positioning_proxy_items(items=public_positioning_proxies)


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


def _change_direction_label(change_vs_comparison: Any) -> str | None:
    if change_vs_comparison is None:
        return None
    try:
        value = float(change_vs_comparison)
    except (TypeError, ValueError):
        return None
    if abs(value) <= 1e-12:
        return "unchanged"
    return "increased" if value > 0 else "decreased"


def _sanitize_quantitative_signal(signal: Mapping[str, Any]) -> dict[str, Any]:
    """Drop raw levels/thresholds so the model cannot echo banned numbers."""

    return {
        "name": signal.get("name"),
        "status": signal.get("status"),
        "direction": signal.get("direction"),
        "source_component": signal.get("source_component"),
        "change_vs_comparison": _change_direction_label(
            signal.get("change_vs_comparison")
        ),
    }


def _sanitize_historical_context(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "state": item.get("state"),
        "note": item.get("note"),
        "latest_label_available_date": item.get("latest_label_available_date"),
    }


def _sanitize_public_proxy(item: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(item)
    # Keep elevated/neutral/state labels; omit the z-score magnitude.
    payload.pop("value", None)
    return payload


def _sanitize_retrieved_evidence(item: Mapping[str, Any]) -> dict[str, Any]:
    """Keep stance wiring; strip digit-heavy free text that models tend to copy."""

    return {
        "evidence_id": item.get("evidence_id"),
        "source": item.get("source"),
        "stance": item.get("stance"),
        "relevance_reason": item.get("relevance_reason"),
        "headline_or_summary": _NUMERIC_LITERAL.sub(
            "[n]", str(item.get("headline_or_summary") or "")
        ).strip()
        or None,
        # Locator URLs often embed dates/ids; stance + evidence_id are enough.
        "citation_or_locator": None,
        "timestamp": item.get("timestamp"),
    }


def _model_context(
    deterministic_input: DeterministicEvidenceInput,
    *,
    structural_unwind: Mapping[str, Any] | None = None,
    mechanical_unwind: Mapping[str, Any] | None = None,
    public_positioning_proxies: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a detached allow-listed model payload.

    Prototype priority: stable LLM narrative output. Raw scorecard levels,
    thresholds, proxy z-scores, and analog return stats are omitted so the
    model is less likely to restate banned numeric literals.
    """

    context = {
        "as_of_date": deterministic_input.as_of_date,
        "comparison_date": deterministic_input.comparison_date,
        "overall_risk_state": deterministic_input.overall_risk_state,
        "deterministic_score": deterministic_input.deterministic_score,
        "quantitative_signals": [
            _sanitize_quantitative_signal(signal.to_dict())
            for signal in (
                deterministic_input.triggered_quant_signals
                + deterministic_input.non_triggered_relevant_signals
            )
        ],
        "retrieved_evidence": [
            _sanitize_retrieved_evidence(item.to_dict())
            for item in deterministic_input.retrieved_evidence
        ],
        "historical_context": [
            _sanitize_historical_context(item)
            for item in deterministic_input.historical_analogs
        ],
        "structural_unwind": _normalize_structural_unwind(structural_unwind),
        "mechanical_unwind": _normalize_mechanical_unwind(mechanical_unwind),
        "public_positioning_proxies": [
            _sanitize_public_proxy(item)
            for item in _normalize_public_positioning_proxies(
                public_positioning_proxies
            )
        ],
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
            "least one implemented momentum tail-risk condition is "
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
            "No quantitative scorecard momentum tail-risk condition is currently "
            "triggered, and no active structural or mechanical unwind channel "
            "was supplied. This does not rule out risks outside the monitored "
            "set."
        )

    dm_status = mechanism_statuses.get("bear_market_recovery_crash", "unavailable")
    short_status = mechanism_statuses.get("short_book_reversal_crash", "unavailable")
    kl_status = mechanism_statuses.get("crowded_theme_unwind", "unavailable")
    mechanical_state = mechanical.get("unwind_state") or "unavailable"
    mechanical_state_label = {
        "FRAGILITY_BUILDING": "potential momentum tail risk",
    }.get(mechanical_state, mechanical_state.replace("_", " ").lower())
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
        f"fundamental anchor. Momentum tail-risk state is {mechanical_state_label}, with "
        f"liquidity absorption failure "
        f"{'present' if absorption is True else 'absent' if absorption is False else 'unavailable'}."
    )
    if len(pm_interpretation) > MAX_PM_INTERPRETATION_CHARS:
        pm_interpretation = (
            pm_interpretation[: MAX_PM_INTERPRETATION_CHARS - 1].rstrip() + "."
        )

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


_OVERCLAIM_PHRASES = (
    re.compile(r"\blow[-\s]?risk state\b", re.IGNORECASE),
    re.compile(r"\bmechanical unwind is normal\b", re.IGNORECASE),
    re.compile(r"\bunwind is normal\b", re.IGNORECASE),
)


def _is_slug_like_narrative(text: str) -> bool:
    compact = text.strip().lower().replace("-", "_").replace(" ", "_")
    return bool(re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", compact))


def _validate_llm_text(interpretation: EvidenceInterpretation) -> None:
    if _is_slug_like_narrative(interpretation.narrative_state):
        raise ValueError(
            "narrative_state must be analyst prose, not an enum/slug token"
        )
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
        if any(pattern.search(text) for pattern in _OVERCLAIM_PHRASES):
            raise ValueError(
                "LLM narrative over-infers risk: do not call untriggered signals "
                "a low-risk state or say mechanical unwind is normal"
            )


def _validated_provider_result(
    raw: Any,
    deterministic_input: DeterministicEvidenceInput,
    structural_unwind: Mapping[str, Any] | None = None,
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

    active_scenarios = (
        list((structural_unwind or {}).get("active_scenarios") or [])
        if structural_unwind
        else []
    )
    if active_scenarios:
        narrative = candidate.narrative_state.lower()
        if "normal drawdown" in narrative or "no confirmed escalation" in narrative:
            raise ValueError(
                "LLM narrative_state contradicts an active structural mechanism"
            )
        phrase_map = {
            "bear_market_recovery_crash": [
                "bear market recovery",
                "recovery crash",
            ],
            "short_book_reversal_crash": [
                "short book reversal",
                "short-book reversal",
            ],
            "crowded_theme_unwind": [
                "crowded theme unwind",
                "crowded momentum unwind",
                "crowded unwind",
            ],
        }
        for scenario in active_scenarios:
            for phrase in phrase_map.get(str(scenario), [str(scenario)]):
                phrase_l = phrase.lower()
                if phrase_l in narrative and re.search(
                    re.escape(phrase_l) + r"\s+watch\b", narrative
                ):
                    raise ValueError(
                        "LLM narrative_state describes a triggered mechanism "
                        "as watch"
                    )

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
    public_positioning_proxies: Sequence[Mapping[str, Any]] | None = None,
) -> EvidenceInterpretation:
    """Interpret a deterministic card without exposing writable quant fields.

    A real provider is optional and injected through ``EvidenceInterpreter``.
    The repository intentionally contains no vendor client. Missing credentials,
    missing configuration, provider errors, and schema violations all return a
    deterministic interpretation with ``use_llm=False`` and a clear warning.
    Compact structural/mechanical summaries and typed public positioning
    proxies are optional read-only LLM context and never alter deterministic
    scorecard or mechanism state.
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
    proxies = _normalize_public_positioning_proxies(public_positioning_proxies)
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
                public_positioning_proxies=proxies,
            ),
            instructions=INTERPRETATION_INSTRUCTIONS,
        )
        result = _validated_provider_result(
            raw,
            deterministic_input,
            structural_unwind=structural,
        )
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
