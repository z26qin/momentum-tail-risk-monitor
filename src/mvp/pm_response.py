"""Bounded PM decision-support layer for the Evidence Card.

Deterministic scorecard and unwind outputs remain the source of truth. This
module projects those facts into a compact PM readout: current posture, main
vulnerability, what would change the reading, conditional portfolio response,
and why broad action may still be premature.

An optional injected provider may rank and phrase the bounded response
categories. It cannot invent categories, alter triggers, recommend securities,
or issue execution instructions. Missing credentials, missing providers, and
invalid model output all fall back to deterministic text.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.monitoring.unwind_structure import UnwindAssessment
from src.mvp.evidence_card import DeterministicEvidenceInput


PM_RESPONSE_SCHEMA_VERSION = "pm-response-v1"
PM_RESPONSE_PROMPT_VERSION = "pm-response-prompt-v5"
DETERMINISTIC_PM_RESPONSE_VERSION = "deterministic-pm-response-v1"

ALLOWED_RESPONSE_CATEGORIES = frozenset(
    {
        "maintain_and_monitor",
        "review_rebound_sensitive_shorts",
        "review_short_loss_contributors",
        "run_loser_rally_stress",
        "review_short_concentration",
        "review_unintended_beta",
        "consider_temporary_beta_hedge",
        "consider_reducing_short_exposure",
        "consider_reducing_gross_subject_to_pm_review",
        "pause_incremental_risk_subject_to_pm_review",
    }
)

CATEGORY_LABELS: dict[str, str] = {
    "maintain_and_monitor": (
        "Maintain the current posture and monitor the short basket"
    ),
    "review_rebound_sensitive_shorts": (
        "Review rebound-sensitive shorts if a recovery move confirms"
    ),
    "review_short_loss_contributors": (
        "Identify the largest short-side loss contributors"
    ),
    "run_loser_rally_stress": "Run a loser-rally stress scenario",
    "review_short_concentration": (
        "Check whether short concentration is amplifying the move"
    ),
    "review_unintended_beta": "Review unintended beta exposure",
    "consider_temporary_beta_hedge": (
        "Consider a temporary beta hedge if the recovery signal confirms, "
        "subject to PM review"
    ),
    "consider_reducing_short_exposure": (
        "Consider reducing short exposure if losses broaden across the basket, "
        "subject to PM review"
    ),
    "consider_reducing_gross_subject_to_pm_review": (
        "Consider reducing gross if stress moves from one leg to the overall "
        "strategy, subject to PM review"
    ),
    "pause_incremental_risk_subject_to_pm_review": (
        "Pause incremental risk pending PM review"
    ),
}

ALLOWED_POSTURES = frozenset(
    {
        "maintain_and_monitor",
        "monitor_more_closely",
        "investigate_risk_channel",
        "escalate_for_pm_review",
    }
)

POSTURE_LABELS: dict[str, str] = {
    "maintain_and_monitor": (
        "Maintain and monitor. The market backdrop may be soft, but the PM "
        "book is not showing a confirmed unwind."
    ),
    "monitor_more_closely": (
        "Monitor more closely. Watch channels are active, but portfolio stress "
        "is not yet confirmed."
    ),
    "investigate_risk_channel": (
        "Investigate a specific risk channel. Stress is beginning to appear in "
        "the PM book and warrants focused review."
    ),
    "escalate_for_pm_review": (
        "Escalate for PM review. Stress is no longer limited to the market "
        "backdrop and is appearing in the portfolio."
    ),
}

ALLOWED_VULNERABILITIES = frozenset(
    {
        "short_basket",
        "long_side_crowding",
        "unintended_beta",
        "concentration",
        "broader_strategy_drawdown",
        "market_backdrop_only",
    }
)

VULNERABILITY_LABELS: dict[str, str] = {
    "short_basket": (
        "The clearest risk is a sharp rebound in recent losers that "
        "concentrates losses in the short basket."
    ),
    "long_side_crowding": (
        "The clearest risk is long-side crowding or correlated-theme pressure "
        "during a style or recovery move."
    ),
    "unintended_beta": (
        "The clearest risk is unintended beta exposure amplifying portfolio "
        "losses in a recovery regime."
    ),
    "concentration": (
        "The clearest risk is concentration amplifying losses in one leg of "
        "the book."
    ),
    "broader_strategy_drawdown": (
        "The clearest risk is broader strategy drawdown rather than a single "
        "isolated channel."
    ),
    "market_backdrop_only": (
        "Risk is still mainly in the market backdrop; PM-book stress channels "
        "remain unconfirmed."
    ),
}

PM_MODEL_OUTPUT_FIELDS = frozenset(
    {
        "current_state",
        "main_vulnerability",
        "what_would_change_the_reading",
        "conditional_response",
        "why_not_act_yet",
        "selected_categories",
    }
)

PM_RESPONSE_INSTRUCTIONS = """\
Write a short decision-support read as a risk analyst speaking to a portfolio
manager and quant researcher. Return only the six PMResponse fields as JSON.
Sound like a morning risk note, not a taxonomy dump.

Tone and style:
- Use plain analyst prose in complete sentences.
- current_state and main_vulnerability must be human-readable sentences.
  Never return bare enum/slug tokens such as monitor_more_closely,
  escalate_for_pm_review, broader_strategy_drawdown, or short_basket.
- Do not call an untriggered book a "low-risk state". Prefer: no deterministic
  escalation signals are active; maintain posture and monitor.
- Do not say "mechanical unwind is normal". Prefer: no evidence of a broad
  mechanical unwind / no broad momentum unwind is confirmed.
- main_vulnerability must name the concrete book risk, not a vague
  "broader strategy drawdown". When short-side recovery risk or elevated
  short-interest proxies are relevant, point to rebound-sensitive / potentially
  crowded shorts as the first review area, cite the elevated short-interest
  proxy as contextual support for that vulnerability, and state whether that
  path is active today.
- what_would_change_the_reading and why_not_act_yet should be prose. You may
  name mechanisms or signals in words, but do not reply with snake_case
  identifiers alone.
- Prefer category_labels language when discussing actions; selected_categories
  alone may use the allowed machine keys.
- public_positioning_proxies are contextual only (state labels, no magnitudes).
  An elevated short-interest proxy supports a short-basket crowding hypothesis;
  it must not be treated as proof of covering or forced deleveraging.

Content rules:
- Use only the supplied deterministic signals, mechanism statuses, and allowed
  response categories. Select only 2 or 3 categories that change the PM
  decision; do not dump overlapping short-side taxonomy items. Prefer a
  compact set such as: maintain_and_monitor; one short-basket review category
  (review_rebound_sensitive_shorts or review_short_concentration); and
  run_loser_rally_stress only as a conditional next step if recovery signals
  strengthen. Do not invent categories.
- Use conditional PM language (if confirmed, would become relevant, worth
  reviewing, consider, subject to PM review). Distinguish vulnerability from
  active unwind: identify what to watch without implying immediate de-risking.
- Do not recommend securities, position sizes, option strikes, or execution
  instructions. Do not alter trigger states or invent thresholds. Do not
  estimate crash probability."""

LLM_CREDENTIAL_ENV_VARS = (
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)

MAX_NARRATIVE_CHARS = 600
MAX_LIST_ITEMS = 8
MAX_LIST_ITEM_CHARS = 300
MAX_RESPONSE_CATEGORIES = len(ALLOWED_RESPONSE_CATEGORIES)

_NUMERIC_LITERAL = re.compile(r"(?<![A-Za-z0-9_])[+-]?\d+(?:\.\d+)?%?")
_NUMERIC_WORD = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
    r"eighty|ninety|hundred|thousand|million|billion|percent|"
    r"percentage)\b",
    re.IGNORECASE,
)
_TICKER_HINT = re.compile(
    r"\b(?:ticker|symbol|CUSIP|ISIN)\b|\b[A-Z]{1,5}\s+(?:shares?|lots?)\b"
)
_POSITION_SIZE = re.compile(
    r"\b(?:\d+(?:\.\d+)?\s*%|\d+\s*(?:shares?|lots?|contracts?)|"
    r"(?:notional|weight|allocation)\s+of\s+\d+)\b",
    re.IGNORECASE,
)
_EXECUTION_CLAIM = re.compile(
    r"\b(?:execute|fill|send\s+the\s+order|buy\s+now|sell\s+now|"
    r"close\s+the\s+position|enter\s+a\s+trade)\b",
    re.IGNORECASE,
)
_PROHIBITED_PM_CLAIMS = (
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
    re.compile(r"\b(?:go|stay)\s+(?:long|short)\b", re.IGNORECASE),
    # Bare "buy/sell X" as an instruction, not "review short exposure".
    re.compile(
        r"\b(?:buy|sell|overweight|underweight)\s+"
        r"(?:the\s+)?(?:stock|name|security|ticker)\b",
        re.IGNORECASE,
    ),
)


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


def _unique(items: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    for item in items:
        cleaned = item.strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return tuple(result[:MAX_LIST_ITEMS])


def _unique_categories(items: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    for item in items:
        cleaned = item.strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return tuple(result[:MAX_RESPONSE_CATEGORIES])


def _category_tuple(value: Any, name: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be a list of strings")
    items: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise ValueError(f"{name} entries must be strings")
        cleaned = entry.strip()
        if not cleaned:
            raise ValueError(f"{name} entries cannot be empty")
        items.append(cleaned)
    if len(items) > MAX_RESPONSE_CATEGORIES:
        raise ValueError(
            f"{name} exceeds {MAX_RESPONSE_CATEGORIES} entries"
        )
    unknown = [item for item in items if item not in ALLOWED_RESPONSE_CATEGORIES]
    if unknown:
        raise ValueError(
            f"{name} contains unknown response categories: {', '.join(unknown)}"
        )
    if len(items) != len(set(items)):
        raise ValueError(f"{name} must not contain duplicate categories")
    return tuple(items)


@dataclass(frozen=True)
class PMResponse:
    """Validated PM decision-support readout tied to bounded categories."""

    current_state: str
    main_vulnerability: str
    what_would_change_the_reading: tuple[str, ...]
    conditional_response: tuple[str, ...]
    why_not_act_yet: str
    response_categories: tuple[str, ...]
    use_llm: bool = False
    model_or_prompt_version: str = DETERMINISTIC_PM_RESPONSE_VERSION
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "current_state", _text(self.current_state, "current_state")
        )
        object.__setattr__(
            self,
            "main_vulnerability",
            _text(self.main_vulnerability, "main_vulnerability"),
        )
        object.__setattr__(
            self,
            "what_would_change_the_reading",
            _text_tuple(
                self.what_would_change_the_reading,
                "what_would_change_the_reading",
            ),
        )
        object.__setattr__(
            self,
            "conditional_response",
            _text_tuple(self.conditional_response, "conditional_response"),
        )
        object.__setattr__(
            self, "why_not_act_yet", _text(self.why_not_act_yet, "why_not_act_yet")
        )
        object.__setattr__(
            self,
            "response_categories",
            _category_tuple(self.response_categories, "response_categories"),
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


@dataclass(frozen=True)
class PMResponseContext:
    """Deterministic facts used to bound the PM response."""

    posture: str
    vulnerability: str
    allowed_categories: tuple[str, ...]
    immediate_categories: tuple[str, ...]
    conditional_categories: tuple[str, ...]
    change_signals: tuple[str, ...]
    triggered_signal_names: tuple[str, ...]
    watch_or_triggered_mechanisms: tuple[str, ...]
    active_mechanisms: tuple[str, ...]
    confirmed_portfolio_stress: bool

    def __post_init__(self) -> None:
        if self.posture not in ALLOWED_POSTURES:
            raise ValueError(f"unsupported posture: {self.posture}")
        if self.vulnerability not in ALLOWED_VULNERABILITIES:
            raise ValueError(f"unsupported vulnerability: {self.vulnerability}")
        for field_name in (
            "allowed_categories",
            "immediate_categories",
            "conditional_categories",
        ):
            categories = getattr(self, field_name)
            unknown = set(categories).difference(ALLOWED_RESPONSE_CATEGORIES)
            if unknown:
                raise ValueError(
                    f"{field_name} contains unknown categories: "
                    + ", ".join(sorted(unknown))
                )

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@runtime_checkable
class PMResponseInterpreter(Protocol):
    """Provider-neutral structured PM-response interface."""

    def interpret_pm_response(
        self,
        *,
        context: dict[str, Any],
        instructions: str,
    ) -> Mapping[str, Any]: ...


def _signal_triggered(deterministic_input: DeterministicEvidenceInput, name: str) -> bool:
    return any(
        signal.name == name and signal.status == "triggered"
        for signal in deterministic_input.triggered_quant_signals
    )


def _unwind_row_triggered(unwind: UnwindAssessment, metric: str) -> bool:
    for row in unwind.scorecard:
        if row.metric == metric:
            return bool(row.triggered)
    return False


def _mechanism_status(unwind: UnwindAssessment, scenario: str) -> str:
    for item in unwind.mechanism_scenarios:
        if item.scenario == scenario:
            return item.status
    return "not_confirmed"


def derive_pm_context(
    deterministic_input: DeterministicEvidenceInput,
    unwind: UnwindAssessment,
) -> PMResponseContext:
    """Map scorecard and unwind facts onto bounded PM response categories."""

    triggered_names = tuple(
        signal.name for signal in deterministic_input.triggered_quant_signals
    )
    short_loss = _signal_triggered(deterministic_input, "short_loss_in_recovery")
    beta_gap = _signal_triggered(deterministic_input, "short_minus_long_beta_gap")
    drawdown = _signal_triggered(deterministic_input, "portfolio_drawdown")
    recovery = _signal_triggered(deterministic_input, "high_volatility_recovery")

    short_mech = _mechanism_status(unwind, "short_book_reversal_crash")
    bear_mech = _mechanism_status(unwind, "bear_market_recovery_crash")
    crowded_mech = _mechanism_status(unwind, "crowded_theme_unwind")
    active = tuple(unwind.active_scenarios)
    watch_or_triggered = tuple(
        item.scenario
        for item in unwind.mechanism_scenarios
        if item.status in {"watch", "triggered"}
    )

    concentration = _unwind_row_triggered(unwind, "portfolio_concentration")
    reversal = _unwind_row_triggered(unwind, "cross_sectional_reversal")

    confirmed = bool(
        active
        or short_loss
        or drawdown
        or (beta_gap and recovery)
    )

    # Vulnerability priority: confirmed book channels before backdrop-only.
    if short_mech == "triggered" or short_loss or reversal:
        vulnerability = "short_basket"
    elif crowded_mech == "triggered":
        vulnerability = "long_side_crowding"
    elif concentration:
        vulnerability = "concentration"
    elif beta_gap:
        vulnerability = "unintended_beta"
    elif drawdown or bear_mech == "triggered":
        vulnerability = "broader_strategy_drawdown"
    elif short_mech == "watch" or crowded_mech == "watch" or bear_mech == "watch":
        if short_mech == "watch":
            vulnerability = "short_basket"
        elif crowded_mech == "watch":
            vulnerability = "long_side_crowding"
        else:
            vulnerability = "broader_strategy_drawdown"
    else:
        vulnerability = "market_backdrop_only"

    if len(active) >= 2 or (short_mech == "triggered" and drawdown):
        posture = "escalate_for_pm_review"
    elif short_mech == "triggered" or short_loss or crowded_mech == "triggered":
        posture = "escalate_for_pm_review"
    elif triggered_names or any(
        status == "watch"
        for status in (short_mech, bear_mech, crowded_mech)
    ):
        if vulnerability in {"short_basket", "unintended_beta", "concentration"}:
            posture = "investigate_risk_channel"
        else:
            posture = "monitor_more_closely"
    else:
        posture = "maintain_and_monitor"

    immediate: list[str] = []
    conditional: list[str] = []

    if posture == "maintain_and_monitor":
        immediate.append("maintain_and_monitor")
    else:
        conditional.append("maintain_and_monitor")

    # Short-basket channel.
    if short_mech in {"watch", "triggered"} or short_loss or recovery or reversal:
        immediate.append("review_rebound_sensitive_shorts")
        conditional.append("run_loser_rally_stress")
    else:
        conditional.append("review_rebound_sensitive_shorts")
        conditional.append("run_loser_rally_stress")

    if short_loss or short_mech == "triggered":
        immediate.append("review_short_loss_contributors")
    else:
        conditional.append("review_short_loss_contributors")

    if concentration or short_mech in {"watch", "triggered"}:
        immediate.append("review_short_concentration")
    else:
        conditional.append("review_short_concentration")

    if beta_gap or short_mech in {"watch", "triggered"}:
        immediate.append("review_unintended_beta")
    else:
        conditional.append("review_unintended_beta")

    # Action categories stay confirmation-gated even when channels are active.
    conditional.append("consider_temporary_beta_hedge")
    conditional.append("consider_reducing_short_exposure")
    conditional.append("consider_reducing_gross_subject_to_pm_review")

    if posture == "escalate_for_pm_review" or len(active) >= 2:
        immediate.append("pause_incremental_risk_subject_to_pm_review")
    else:
        conditional.append("pause_incremental_risk_subject_to_pm_review")

    immediate_categories = _unique_categories(immediate)
    conditional_categories = _unique_categories(
        [item for item in conditional if item not in immediate_categories]
    )
    # Allowed set is the union, preserving immediate-first order.
    allowed_categories = _unique_categories(
        [*immediate_categories, *conditional_categories]
    )

    change_signals: list[str] = []
    if short_mech != "triggered":
        change_signals.append(
            "short_book_reversal_crash moves from watch/not_confirmed to triggered"
        )
    if not short_loss:
        change_signals.append(
            "short_loss_in_recovery triggers during a recovery regime"
        )
    if not beta_gap:
        change_signals.append(
            "short_minus_long_beta_gap widens into a triggered state"
        )
    if not drawdown:
        change_signals.append(
            "portfolio_drawdown breaches its monitored threshold"
        )
    if concentration is False:
        change_signals.append(
            "portfolio_concentration or cross_sectional_reversal confirms"
        )
    if not change_signals:
        change_signals.append(
            "Additional mechanisms trigger together or losses broaden across legs"
        )

    return PMResponseContext(
        posture=posture,
        vulnerability=vulnerability,
        allowed_categories=allowed_categories,
        immediate_categories=immediate_categories,
        conditional_categories=conditional_categories,
        change_signals=_unique(change_signals),
        triggered_signal_names=triggered_names,
        watch_or_triggered_mechanisms=watch_or_triggered,
        active_mechanisms=active,
        confirmed_portfolio_stress=confirmed,
    )


def _why_not_act_yet(context: PMResponseContext) -> str:
    if not context.confirmed_portfolio_stress:
        return (
            "Broad de-risking would be premature because the relevant PM-book "
            "stress channels remain unconfirmed."
        )
    if context.posture == "escalate_for_pm_review":
        return (
            "A confirmed channel warrants focused review, but broad automatic "
            "de-risking is still premature until the PM selects which response "
            "to evaluate and at what size."
        )
    return (
        "Action remains conditional: watch channels are active, but the setup "
        "is not yet confirmed enough to justify a book-wide response."
    )


def _deterministic_change_lines(context: PMResponseContext) -> tuple[str, ...]:
    if context.confirmed_portfolio_stress:
        return (
            "The setup would become more fragile if losses broaden further "
            "across the short basket, unintended beta worsens, or drawdown "
            "deepens across the strategy.",
            *tuple(
                f"Further confirmation: {item}." for item in context.change_signals[:3]
            ),
        )[:MAX_LIST_ITEMS]
    return (
        "The setup would become more fragile if a recovery regime is "
        "accompanied by rising short-leg losses, adverse beta movement, or "
        "broader portfolio drawdown.",
        *tuple(f"Watch for: {item}." for item in context.change_signals[:3]),
    )[:MAX_LIST_ITEMS]


def _deterministic_conditional_lines(
    context: PMResponseContext,
) -> tuple[str, ...]:
    # Prefer immediate review items, then confirmation-gated action items.
    ordered = _unique(
        [
            *context.immediate_categories,
            *[
                item
                for item in context.conditional_categories
                if item.startswith("consider_") or item.startswith("run_")
            ],
            *context.conditional_categories,
        ]
    )
    # Drop maintain from the conditional list when posture is already maintain;
    # it is expressed in current_state instead.
    display_ids = [
        item
        for item in ordered
        if not (
            item == "maintain_and_monitor"
            and context.posture == "maintain_and_monitor"
        )
    ]
    if not display_ids:
        display_ids = ["maintain_and_monitor"]
    return tuple(
        CATEGORY_LABELS[item] for item in display_ids[:MAX_LIST_ITEMS]
    )


def _deterministic_pm_response(
    context: PMResponseContext,
    *,
    warnings: tuple[str, ...] = (),
) -> PMResponse:
    categories = context.allowed_categories
    if context.posture == "maintain_and_monitor" and "maintain_and_monitor" not in categories:
        categories = ("maintain_and_monitor", *categories)
    return PMResponse(
        current_state=POSTURE_LABELS[context.posture],
        main_vulnerability=VULNERABILITY_LABELS[context.vulnerability],
        what_would_change_the_reading=_deterministic_change_lines(context),
        conditional_response=_deterministic_conditional_lines(context),
        why_not_act_yet=_why_not_act_yet(context),
        response_categories=categories[:MAX_RESPONSE_CATEGORIES],
        use_llm=False,
        model_or_prompt_version=DETERMINISTIC_PM_RESPONSE_VERSION,
        warnings=warnings,
    )


def _model_context(
    deterministic_input: DeterministicEvidenceInput,
    unwind: UnwindAssessment,
    context: PMResponseContext,
    *,
    public_positioning_proxies: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    proxies: list[dict[str, Any]] = []
    for item in public_positioning_proxies or ():
        proxies.append(
            {
                "source": item.get("source"),
                "metric": item.get("metric"),
                "state": item.get("state"),
                "evidence_class": item.get("evidence_class"),
                "relevant_asset_or_portfolio_scope": item.get(
                    "relevant_asset_or_portfolio_scope"
                ),
            }
        )
    payload = {
        "as_of_date": deterministic_input.as_of_date,
        "overall_risk_state": deterministic_input.overall_risk_state,
        "deterministic_score": deterministic_input.deterministic_score,
        "triggered_signals": [
            {
                "name": signal.name,
                "status": signal.status,
                "direction": signal.direction,
            }
            for signal in deterministic_input.triggered_quant_signals
        ],
        "non_triggered_signals": [
            {
                "name": signal.name,
                "status": signal.status,
                "direction": signal.direction,
            }
            for signal in deterministic_input.non_triggered_relevant_signals
        ],
        "mechanism_statuses": {
            item.scenario: item.status for item in unwind.mechanism_scenarios
        },
        "active_mechanisms": list(unwind.active_scenarios),
        "unwind_triggers": [
            {"metric": row.metric, "triggered": row.triggered, "status": row.status}
            for row in unwind.scorecard
        ],
        "public_positioning_proxies": proxies,
        "pm_response_context": context.to_dict(),
        "allowed_response_categories": list(context.allowed_categories),
        "category_labels": {
            key: CATEGORY_LABELS[key] for key in context.allowed_categories
        },
    }
    return json.loads(json.dumps(payload, sort_keys=True, allow_nan=False))


def _is_bare_enum_slug(text: str) -> bool:
    compact = text.strip().lower().replace("-", "_")
    if compact in ALLOWED_POSTURES or compact in ALLOWED_VULNERABILITIES:
        return True
    # Reject snake_case identifier-only replies (e.g. short_book_reversal_crash).
    return bool(re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", compact))


def _validate_pm_llm_text(response: PMResponse) -> None:
    for field_name in ("current_state", "main_vulnerability"):
        value = getattr(response, field_name)
        if _is_bare_enum_slug(value):
            raise ValueError(
                f"{field_name} must be analyst prose, not an enum/slug token"
            )
    narrative_fields = (
        response.current_state,
        response.main_vulnerability,
        *response.what_would_change_the_reading,
        *response.conditional_response,
        response.why_not_act_yet,
    )
    for text in narrative_fields:
        if _is_bare_enum_slug(text):
            raise ValueError(
                "PM narrative fields must be analyst prose, not enum/slug tokens"
            )
        if _NUMERIC_LITERAL.search(text) or _NUMERIC_WORD.search(text):
            raise ValueError("PM response must not introduce numerical values")
        if _TICKER_HINT.search(text) or _POSITION_SIZE.search(text):
            raise ValueError(
                "PM response must not recommend securities or position sizes"
            )
        if _EXECUTION_CLAIM.search(text):
            raise ValueError("PM response must not issue execution instructions")
        if any(pattern.search(text) for pattern in _PROHIBITED_PM_CLAIMS):
            raise ValueError(
                "PM response contains a causal, certainty, or trade claim"
            )


def _provider_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        payload = dict(raw)
    else:
        raise ValueError("PM interpreter output must be a mapping")
    missing = PM_MODEL_OUTPUT_FIELDS.difference(payload)
    extra = set(payload).difference(PM_MODEL_OUTPUT_FIELDS)
    if missing or extra:
        raise ValueError(
            "PM interpreter output fields do not match the schema "
            f"(missing={sorted(missing)}, extra={sorted(extra)})"
        )
    return payload


def _validated_provider_result(
    raw: Any,
    context: PMResponseContext,
) -> PMResponse:
    payload = _provider_payload(raw)
    selected = _category_tuple(payload["selected_categories"], "selected_categories")
    disallowed = [item for item in selected if item not in context.allowed_categories]
    if disallowed:
        raise ValueError(
            "selected_categories outside the deterministic allow-list: "
            + ", ".join(disallowed)
        )
    if not selected:
        raise ValueError("selected_categories cannot be empty")
    if len(selected) > 3:
        raise ValueError(
            "selected_categories must contain at most 3 items for a compact "
            "PM readout"
        )

    candidate = PMResponse(
        current_state=_text(payload["current_state"], "current_state"),
        main_vulnerability=_text(
            payload["main_vulnerability"], "main_vulnerability"
        ),
        what_would_change_the_reading=_text_tuple(
            payload["what_would_change_the_reading"],
            "what_would_change_the_reading",
        ),
        conditional_response=_text_tuple(
            payload["conditional_response"], "conditional_response"
        ),
        why_not_act_yet=_text(payload["why_not_act_yet"], "why_not_act_yet"),
        response_categories=selected,
        use_llm=True,
        model_or_prompt_version=PM_RESPONSE_PROMPT_VERSION,
        warnings=(),
    )
    if not 1 <= len(candidate.what_would_change_the_reading) <= 5:
        raise ValueError("what_would_change_the_reading must contain 1 to 5 items")
    if not 1 <= len(candidate.conditional_response) <= 6:
        raise ValueError("conditional_response must contain 1 to 6 items")
    _validate_pm_llm_text(candidate)
    return candidate


def _has_credentials(environment: Mapping[str, str]) -> bool:
    return any(environment.get(name, "").strip() for name in LLM_CREDENTIAL_ENV_VARS)


def build_pm_response(
    deterministic_input: DeterministicEvidenceInput,
    unwind: UnwindAssessment,
    *,
    use_llm: bool = True,
    interpreter: PMResponseInterpreter | None = None,
    environment: Mapping[str, str] | None = None,
    public_positioning_proxies: Sequence[Mapping[str, Any]] | None = None,
) -> PMResponse:
    """Build a bounded PM response without mutating quant or unwind outputs."""

    if not isinstance(deterministic_input, DeterministicEvidenceInput):
        raise TypeError(
            "deterministic_input must be a DeterministicEvidenceInput"
        )
    if not isinstance(unwind, UnwindAssessment):
        raise TypeError("unwind must be an UnwindAssessment")

    before_input = json.dumps(
        deterministic_input.to_dict(), sort_keys=True, allow_nan=False
    )
    before_unwind = json.dumps(
        unwind.to_dict(), sort_keys=True, allow_nan=False
    )
    context = derive_pm_context(deterministic_input, unwind)

    if not use_llm:
        result = _deterministic_pm_response(context)
    else:
        configured_environment = os.environ if environment is None else environment
        if not _has_credentials(configured_environment):
            result = _deterministic_pm_response(
                context,
                warnings=(
                    "LLM PM response was requested, but no supported API "
                    "credentials are present; use_llm was set to False and the "
                    "deterministic PM response was used.",
                ),
            )
        elif interpreter is None:
            result = _deterministic_pm_response(
                context,
                warnings=(
                    "LLM PM response was requested, but no structured "
                    "interpreter is configured; use_llm was set to False and "
                    "the deterministic PM response was used.",
                ),
            )
        else:
            try:
                raw = interpreter.interpret_pm_response(
                    context=_model_context(
                        deterministic_input,
                        unwind,
                        context,
                        public_positioning_proxies=public_positioning_proxies,
                    ),
                    instructions=PM_RESPONSE_INSTRUCTIONS,
                )
                result = _validated_provider_result(raw, context)
            except Exception as exc:  # noqa: BLE001 - fail closed
                result = _deterministic_pm_response(
                    context,
                    warnings=(
                        "LLM PM response failed schema or safety validation; "
                        f"use_llm was set to False ({exc}).",
                    ),
                )

    after_input = json.dumps(
        deterministic_input.to_dict(), sort_keys=True, allow_nan=False
    )
    after_unwind = json.dumps(unwind.to_dict(), sort_keys=True, allow_nan=False)
    if before_input != after_input or before_unwind != after_unwind:
        raise AssertionError("PM response builder modified deterministic inputs")
    return result
