"""Optional, constrained narrative synthesis for the PM Evidence Card.

The default synthesizer is fully deterministic and offline. It never computes,
alters, or invents a quantitative value; it only phrases narrative text from the
structured deterministic facts it is handed. Numbers, thresholds, triggered
states, dates, and scores are populated elsewhere and are never written by a
synthesizer, so even a faulty language-model synthesizer cannot corrupt them.

A real language-model synthesizer can be substituted by passing any object that
exposes a ``synthesize(*, context) -> SynthesisResult`` method. On any exception
or schema violation the caller falls back to the deterministic result and
records a warning; the demo therefore always runs without an API key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


DETERMINISTIC_VERSION = "deterministic-template-v1"

MAX_NARRATIVE_CHARS = 600
MAX_LIST_ITEMS = 8
MAX_LIST_ITEM_CHARS = 300


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
            raise ValueError(f"{name} entry exceeds {MAX_LIST_ITEM_CHARS} characters")
        items.append(cleaned)
    if len(items) > MAX_LIST_ITEMS:
        raise ValueError(f"{name} exceeds {MAX_LIST_ITEMS} entries")
    return tuple(items)


@dataclass(frozen=True)
class SynthesisResult:
    """Narrative-only synthesis output. Holds no quantitative field."""

    narrative_state: str
    what_changed: tuple[str, ...]
    pm_interpretation: str
    monitoring_questions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    model_or_prompt_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "narrative_state", _text(self.narrative_state, "narrative_state"))
        object.__setattr__(self, "pm_interpretation", _text(self.pm_interpretation, "pm_interpretation"))
        object.__setattr__(self, "what_changed", _text_tuple(self.what_changed, "what_changed"))
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
        object.__setattr__(
            self,
            "model_or_prompt_version",
            _text(self.model_or_prompt_version, "model_or_prompt_version"),
        )


@runtime_checkable
class Synthesizer(Protocol):
    """Any object able to phrase narrative fields from structured facts."""

    def synthesize(self, *, context: dict[str, Any]) -> SynthesisResult: ...


def _fallback_narrative_state(context: dict[str, Any]) -> str:
    state = context["overall_risk_state"]
    triggered = context["triggered_signal_names"]
    if triggered:
        return (
            f"The current state is fragile because {len(triggered)} of "
            f"{context['total_signals']} deterministic risk conditions are "
            f"triggered together: {', '.join(triggered)}. The macro state is "
            f"'{state}'. The evidence is not sufficient to classify this as a "
            "confirmed crash regime."
        )
    return (
        f"No deterministic momentum tail-risk warning is active in the '{state}' macro "
        f"state: none of {context['total_signals']} monitored conditions is "
        "triggered. This reading does not rule out risks outside the monitored "
        "signal set."
    )


def _fallback_what_changed(context: dict[str, Any]) -> tuple[str, ...]:
    changes = context.get("signal_changes", [])
    if not context.get("comparison_date"):
        return ("No comparison date was supplied, so no change analysis is available.",)
    if not changes:
        return (
            f"No monitored signal changed measurably versus {context['comparison_date']}.",
        )
    lines: list[str] = []
    for change in changes[:5]:
        if change["abs_delta"] <= 1e-12:
            continue
        lines.append(
            f"{change['name']}: {change['from_text']} -> {change['to_text']} "
            f"(change {change['delta_text']}) versus {context['comparison_date']}."
        )
    return tuple(lines) or (
        f"No monitored signal changed measurably versus {context['comparison_date']}.",
    )


def _fallback_pm_interpretation(context: dict[str, Any]) -> str:
    triggered = context["triggered_signal_names"]
    evidence = context["evidence_quality"]
    if triggered:
        lead = (
            "Treat this as a potential momentum tail-risk watch, not a trade instruction or crash "
            "forecast. The deterministic rules identify conditions under which "
            "a momentum rebound could squeeze the recent-loser leg."
        )
    else:
        lead = (
            "No monitored deterministic warning is active. Keep the reading as "
            "a baseline and watch for several conditions deteriorating together."
        )
    tail = (
        f" Point-in-time evidence is '{evidence}'; it can support, moderate, or "
        "leave the warning unresolved, but cannot create or overturn the signal."
    )
    return lead + tail


def _fallback_monitoring_questions(context: dict[str, Any]) -> tuple[str, ...]:
    return (
        "Does the short-minus-long beta gap stay at or above its prior-only "
        "threshold on the next observation?",
        "Is the long-short drawdown deepening or stabilising relative to its "
        "material threshold?",
        "Do point-in-time sources corroborate a momentum-specific mechanism "
        "rather than a broad macro move?",
    )


def _fallback_invalidation_conditions(context: dict[str, Any]) -> tuple[str, ...]:
    return (
        "The short-minus-long beta gap falls back below its threshold and the "
        "long-short drawdown recovers past its material depth.",
        "The deterministic macro gate exits early-recovery and "
        "high-volatility-recovery on the next observation.",
        "Contemporaneous contradicting evidence at the same cutoff outweighs the "
        "supporting evidence.",
    )


@dataclass(frozen=True)
class DeterministicSynthesizer:
    """Offline synthesizer that phrases narrative from structured facts only."""

    def synthesize(self, *, context: dict[str, Any]) -> SynthesisResult:
        return SynthesisResult(
            narrative_state=_fallback_narrative_state(context),
            what_changed=_fallback_what_changed(context),
            pm_interpretation=_fallback_pm_interpretation(context),
            monitoring_questions=_fallback_monitoring_questions(context),
            invalidation_conditions=_fallback_invalidation_conditions(context),
            model_or_prompt_version=DETERMINISTIC_VERSION,
        )


def deterministic_synthesis(context: dict[str, Any]) -> SynthesisResult:
    """Convenience wrapper returning the deterministic narrative fallback."""

    return DeterministicSynthesizer().synthesize(context=context)
