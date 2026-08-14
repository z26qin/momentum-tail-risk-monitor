"""Thin Hermes POC adapter over the existing deterministic MVP path.

This module does not recalculate signals, thresholds, or mechanisms. It
projects ``run_mvp()`` into a compact JSON assessment, compares discrete
state fields, and formats a short WhatsApp-compatible draft alert.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.mvp.config import HISTORICAL_EXAMPLE_DATE, MVPConfig
from src.mvp.evidence_card import DATA_VERSION_FILES
from src.mvp.monitoring_severity import (
    MECHANISM_KEYS,
    compute_monitoring_severity,
    format_score_value,
    mechanism_label,
    score_label_display,
)
from src.mvp.pipeline import MVPRunResult, run_mvp
from src.mvp.pm_response import POSTURE_LABELS, derive_pm_context
from src.utils.io import DEFAULT_PROCESSED_DIR, REPO_ROOT, read_json, write_json
from src.utils.market_time import NEW_YORK, assessment_timestamp

HERMES_MONITOR_SCHEMA_VERSION = "hermes-monitor-v1"
DEFAULT_ASSESSMENT_PATH = REPO_ROOT / "outputs" / "latest_assessment.json"
DEFAULT_COMPARISON_PATH = REPO_ROOT / "outputs" / "latest_comparison.json"
DEFAULT_PREVIOUS_PATH = REPO_ROOT / "runtime_state" / "previous_assessment.json"
NOTEBOOK_COMPARE_DATES = {
    HISTORICAL_EXAMPLE_DATE: "2026-04-30",
}
FROZEN_CASE_PACKS = {
    "2026-05-29": "outputs/current_semi_unwind",
    "2020-03-24": "outputs/march_2020_reference",
    "2024-01-05": "outputs/quiet_control_2024",
}
MECHANICAL_STATE_LABELS = {
    "FRAGILITY_BUILDING": "potential momentum tail risk",
    "ACTIVE_UNWIND": "active unwind proxy",
    "STABILIZING_REVERSAL": "stabilizing reversal",
    "NORMAL": "no broad mechanical unwind confirmed",
}
POSTURE_SHORT_LABELS = {
    "maintain_and_monitor": "Monitor",
    "monitor_more_closely": "Monitor",
    "investigate_risk_channel": "Investigate",
    "escalate_for_pm_review": "Escalate for review",
}
REQUIRED_ASSESSMENT_FIELDS = (
    "schema_version",
    "as_of_date",
    "evidence_cutoff",
    "overall_risk_state",
    "pm_posture",
    "risk_state",
    "deterministic_trigger_count",
    "triggered_channels",
    "structural_flags",
    "book_read",
    "evidence_needed",
    "supported_mechanisms",
    "unconfirmed_mechanisms",
    "next_checks",
    "monitoring_severity_score",
    "score_label",
    "severity_emoji",
    "primary_driver",
    "mechanism_scores",
    "score_is_probability",
)


class MissingCachedDataError(FileNotFoundError):
    """Raised when bundled processed inputs required by the monitor are absent."""


def require_cached_inputs(processed_dir: Path = DEFAULT_PROCESSED_DIR) -> list[str]:
    """Fail clearly when the frozen/cached processed panels are missing."""

    required = [processed_dir / name for name in DATA_VERSION_FILES]
    required.append(processed_dir / "leg_risk_history.parquet")
    missing = [
        str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)
        for path in required
        if not path.is_file()
    ]
    if missing:
        raise MissingCachedDataError(
            "required cached data is unavailable: " + ", ".join(missing)
        )
    return [
        str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)
        for path in required
    ]


def default_compare_to_date(as_of_date: str) -> str | None:
    """Return the notebook comparison date for the frozen demo case."""

    return NOTEBOOK_COMPARE_DATES.get(as_of_date)


def format_evidence_cutoff(data_cutoff: str) -> str:
    """Render the repository US-close cutoff as ``YYYY-MM-DD HH:MM ET``."""

    parsed = datetime.fromisoformat(data_cutoff)
    if parsed.tzinfo is None:
        raise ValueError("data_cutoff must include a timezone offset")
    local = parsed.astimezone(NEW_YORK)
    return local.strftime("%Y-%m-%d %H:%M ET")


def validate_evidence_cutoff(as_of_date: str, evidence_cutoff: str) -> str:
    """Accept a display cutoff only when it matches the repository 16:00 ET close."""

    expected_iso = assessment_timestamp(pd.Timestamp(as_of_date))
    expected_display = format_evidence_cutoff(expected_iso)
    stripped = evidence_cutoff.strip()
    if stripped in {expected_iso, expected_display}:
        return expected_display
    match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}):(\d{2})(?:\s*(?:ET|America/New_York))?)?",
        stripped,
    )
    if match is None:
        raise ValueError(
            "evidence_cutoff must match the repository US-close timestamp "
            f"({expected_display} or {expected_iso})"
        )
    date_text, hour, minute = match.group(1), match.group(2), match.group(3)
    if date_text != as_of_date:
        raise ValueError("evidence_cutoff date must match as_of_date")
    if hour is not None and (hour, minute) != ("16", "00"):
        raise ValueError("evidence_cutoff time must be 16:00 ET")
    return expected_display


def _finite_or_none(value: Any) -> float | None:
    if value is None or value is pd.NA or pd.isna(value):
        return None
    result = float(value)
    if result != result or result in {float("inf"), float("-inf")}:
        return None
    return result


def _signal_map(result: MVPRunResult) -> dict[str, Any]:
    card = result.deterministic_input
    return {
        signal.name: signal
        for signal in (
            card.triggered_quant_signals + card.non_triggered_relevant_signals
        )
    }


def _book_read(result: MVPRunResult) -> dict[str, float | None]:
    signals = _signal_map(result)
    processed_dir = result.config.processed_dir
    risk_path = processed_dir / "leg_risk_history.parquet"
    if not risk_path.is_file():
        raise MissingCachedDataError(
            "required cached data is unavailable: "
            + (
                str(risk_path.relative_to(REPO_ROOT))
                if risk_path.is_relative_to(REPO_ROOT)
                else str(risk_path)
            )
        )
    frame = pd.read_parquet(
        risk_path,
        columns=["date", "long_beta_126d", "short_underlying_beta_126d"],
    )
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    selected = frame.loc[frame["date"].eq(pd.Timestamp(result.config.as_of_date))]
    long_beta = None
    short_beta = None
    if not selected.empty:
        row = selected.iloc[-1]
        long_beta = _finite_or_none(row["long_beta_126d"])
        short_beta = _finite_or_none(row["short_underlying_beta_126d"])
    return {
        "portfolio_drawdown": _finite_or_none(
            getattr(signals.get("portfolio_drawdown"), "current_value", None)
        ),
        "short_loss_in_recovery": _finite_or_none(
            getattr(signals.get("short_loss_in_recovery"), "current_value", None)
        ),
        "long_beta_126d": long_beta,
        "short_underlying_beta_126d": short_beta,
    }


def _structural_flags(result: MVPRunResult) -> list[str]:
    flags: list[str] = list(result.unwind.active_scenarios)
    for row in result.unwind.scorecard:
        if row.metric == "portfolio_concentration" and row.triggered:
            if "portfolio_concentration" not in flags:
                flags.append("portfolio_concentration")
            break
    return flags


def compact_assessment_from_result(result: MVPRunResult) -> dict[str, Any]:
    """Normalize an existing ``MVPRunResult`` into the Hermes compact schema."""

    card = result.deterministic_input
    unwind = result.unwind
    interpretation = result.interpretation
    pm = result.pm_response
    context = derive_pm_context(card, unwind)
    mechanism_statuses = {
        item.scenario: item.status for item in unwind.mechanism_scenarios
    }
    triggered_channels = [signal.name for signal in card.triggered_quant_signals]
    supported = [
        name for name, status in mechanism_statuses.items() if status == "triggered"
    ]
    unconfirmed = [
        name
        for name, status in mechanism_statuses.items()
        if status in {"watch", "not_confirmed", "unavailable"}
    ]
    evidence_needed = bool(
        triggered_channels
        or _structural_flags(result)
        or context.posture != "maintain_and_monitor"
        or card.retrieved_evidence
    )
    frozen_pack = FROZEN_CASE_PACKS.get(card.as_of_date)
    severity = compute_monitoring_severity(result)
    return {
        "schema_version": HERMES_MONITOR_SCHEMA_VERSION,
        "as_of_date": card.as_of_date,
        "compare_to_date": card.comparison_date,
        "evidence_cutoff": format_evidence_cutoff(card.data_cutoff),
        "data_cutoff": card.data_cutoff,
        "overall_risk_state": card.overall_risk_state,
        "pm_posture": context.posture,
        "risk_state": context.posture,
        "mechanical_unwind_state": result.mechanical_unwind.unwind_state,
        "monitoring_severity_score": severity["monitoring_severity_score"],
        "score_label": severity["score_label"],
        "severity_emoji": severity["severity_emoji"],
        "primary_driver": severity["primary_driver"],
        "mechanism_scores": severity["mechanism_scores"],
        "score_is_probability": False,
        "score_formula": severity["score_formula"],
        "mechanism_score_components": severity["mechanism_score_components"],
        "unavailable_mechanism_reasons": severity["unavailable_mechanism_reasons"],
        "deterministic_trigger_count": len(triggered_channels),
        "triggered_channels": triggered_channels,
        "structural_flags": _structural_flags(result),
        "mechanism_statuses": mechanism_statuses,
        "book_read": _book_read(result),
        "theme_cluster": list(unwind.theme_concentration.cluster_symbols),
        "evidence_needed": evidence_needed,
        "evidence_quality": card.audit_metadata.get("evidence_quality"),
        "supported_mechanisms": supported,
        "unconfirmed_mechanisms": unconfirmed,
        "next_checks": list(interpretation.monitoring_questions),
        "supporting_evidence_ids": list(interpretation.supporting_evidence_ids),
        "contradicting_evidence_ids": list(interpretation.contradicting_evidence_ids),
        "missing_or_uncertain_evidence": [
            item
            for item in interpretation.missing_or_uncertain_evidence
            if item not in set(card.data_warnings)
        ][:4],
        "retrieved_evidence": [
            {
                "evidence_id": item.evidence_id,
                "stance": item.stance,
                "timestamp": item.timestamp,
                "source": item.source,
                "headline_or_summary": item.headline_or_summary,
            }
            for item in card.retrieved_evidence
        ],
        "pm_current_state": pm.current_state,
        "main_vulnerability": pm.main_vulnerability,
        "why_not_act_yet": pm.why_not_act_yet,
        "frozen_case_pack": frozen_pack,
        "run_id": card.run_id,
        "full_run_fingerprint": result.full_run_fingerprint,
    }


def run_compact_assessment(
    *,
    as_of_date: str,
    compare_to_date: str | None = None,
    evidence_cutoff: str | None = None,
    horizon_days: int = 20,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
) -> dict[str, Any]:
    """Run the existing deterministic monitor and return compact JSON."""

    require_cached_inputs(processed_dir)
    if evidence_cutoff is not None:
        validate_evidence_cutoff(as_of_date, evidence_cutoff)
    config = MVPConfig(
        as_of_date=as_of_date,
        compare_to_date=compare_to_date,
        threshold_profile="default",
        horizon_days=horizon_days,
        use_llm=False,
        processed_dir=processed_dir,
    )
    result = run_mvp(config)
    assessment = compact_assessment_from_result(result)
    if evidence_cutoff is not None:
        assessment["evidence_cutoff"] = validate_evidence_cutoff(
            as_of_date, evidence_cutoff
        )
    return assessment


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _list_changes(label: str, before: Any, after: Any) -> list[str]:
    old = set(_as_list(before))
    new = set(_as_list(after))
    changes: list[str] = []
    for item in sorted(new - old):
        changes.append(f"New {label}: {item}")
    for item in sorted(old - new):
        changes.append(f"Removed {label}: {item}")
    return changes


def compare_assessments(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare discrete monitor states. Numeric drift alone is not material.

    Score integers inside the same severity band are ignored. A band change
    or primary-driver change is material.
    """

    if previous is None:
        return {
            "schema_version": HERMES_MONITOR_SCHEMA_VERSION,
            "material_change": False,
            "is_baseline": True,
            "silent": True,
            "as_of_date": current.get("as_of_date"),
            "changes": ["Initial baseline created"],
        }

    changes: list[str] = []
    for field, label in (
        ("risk_state", "risk_state"),
        ("pm_posture", "PM posture"),
        ("overall_risk_state", "UMD/DM state"),
        ("mechanical_unwind_state", "mechanical unwind state"),
    ):
        old = previous.get(field)
        new = current.get(field)
        if old != new:
            changes.append(f"{label} changed: {old} → {new}")

    old_count = previous.get("deterministic_trigger_count")
    new_count = current.get("deterministic_trigger_count")
    if old_count != new_count:
        changes.append(
            f"Deterministic trigger count changed: {old_count} → {new_count}"
        )
    if "score_label" in previous and "score_label" in current:
        old_band = previous.get("score_label")
        new_band = current.get("score_label")
        if old_band != new_band:
            changes.append(f"Severity band changed: {old_band} → {new_band}")
    if "primary_driver" in previous and "primary_driver" in current:
        old_driver = previous.get("primary_driver")
        new_driver = current.get("primary_driver")
        if old_driver != new_driver:
            changes.append(
                f"Primary driver changed: {old_driver} → {new_driver}"
            )
    changes.extend(
        _list_changes(
            "triggered channel",
            previous.get("triggered_channels"),
            current.get("triggered_channels"),
        )
    )
    changes.extend(
        _list_changes(
            "structural flag",
            previous.get("structural_flags"),
            current.get("structural_flags"),
        )
    )
    changes.extend(
        _list_changes(
            "supported mechanism",
            previous.get("supported_mechanisms"),
            current.get("supported_mechanisms"),
        )
    )
    changes.extend(
        _list_changes(
            "unconfirmed mechanism",
            previous.get("unconfirmed_mechanisms"),
            current.get("unconfirmed_mechanisms"),
        )
    )
    old_support = set(_as_list(previous.get("supporting_evidence_ids")))
    new_support = set(_as_list(current.get("supporting_evidence_ids")))
    old_contra = set(_as_list(previous.get("contradicting_evidence_ids")))
    new_contra = set(_as_list(current.get("contradicting_evidence_ids")))
    if old_support != new_support or old_contra != new_contra:
        added_support = sorted(new_support - old_support)
        added_contra = sorted(new_contra - old_contra)
        if added_support:
            changes.append(
                "New supporting evidence: " + ", ".join(added_support)
            )
        if added_contra:
            changes.append(
                "New contradicting evidence: " + ", ".join(added_contra)
            )
        if not added_support and not added_contra:
            changes.append(
                "Evidence IDs changed for the supported/unconfirmed mechanism read"
            )

    material = bool(changes)
    return {
        "schema_version": HERMES_MONITOR_SCHEMA_VERSION,
        "material_change": material,
        "is_baseline": False,
        "silent": not material,
        "as_of_date": current.get("as_of_date"),
        "changes": changes,
    }


def load_previous_assessment(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"previous assessment is not a JSON object: {path}")
    return payload


def save_assessment(path: Path, assessment: dict[str, Any]) -> Path:
    write_json(path, assessment)
    return path


def format_whatsapp_score_card(assessment: dict[str, Any]) -> str:
    """WhatsApp answer for 'What is the current momentum risk score?'"""

    score = assessment.get("monitoring_severity_score")
    label = score_label_display(assessment.get("score_label"))
    emoji = assessment.get("severity_emoji") or ""
    trigger_count = int(assessment.get("deterministic_trigger_count") or 0)
    scores = assessment.get("mechanism_scores") or {}
    prefix = f"{emoji} " if emoji else ""
    if score is None:
        headline = f"{prefix}Momentum monitoring severity: Not available"
    else:
        headline = (
            f"{prefix}Momentum monitoring severity: {int(score)}/100 — {label}"
        )
    lines = [
        headline,
        f"Primary driver: {mechanism_label(assessment.get('primary_driver'))}",
    ]
    for key in MECHANISM_KEYS:
        lines.append(
            f"{mechanism_label(key)}: {format_score_value(scores.get(key))}"
        )
    lines.append(f"Deterministic Macro State Change triggers: {trigger_count}/4")
    if score is None:
        lines.append(
            "This is a relative monitoring score based on prior-only "
            "percentiles, not a crash probability."
        )
    else:
        lines.append(
            "This is a relative monitoring score based on prior-only "
            f"percentiles, not a {int(score)}% crash probability."
        )
    return "\n".join(lines)


def format_whatsapp_alert(
    assessment: dict[str, Any],
    comparison: dict[str, Any] | None = None,
) -> str:
    """Draft a two-message PM-facing alert from compact assessment fields."""

    score = assessment.get("monitoring_severity_score")
    label = score_label_display(assessment.get("score_label"))
    emoji = assessment.get("severity_emoji") or ""
    prefix = f"{emoji} " if emoji else ""
    trigger_count = int(assessment.get("deterministic_trigger_count") or 0)
    header = f"{prefix}MOMENTUM RISK — {label.upper()}"
    severity_line = f"Severity: {format_score_value(score, over_100=True)}"

    change_lines = _as_list((comparison or {}).get("changes"))
    flag_changes = [item for item in change_lines if "structural flag" in item]
    band_changes = [item for item in change_lines if "Severity band changed" in item]
    if flag_changes:
        what_changed = (
            "Crowding evidence strengthened, but portfolio-level forced "
            "liquidation remains unconfirmed."
            if any("crowded_theme_unwind" in item for item in flag_changes)
            else flag_changes[0]
        )
    elif band_changes:
        what_changed = band_changes[0]
    elif change_lines:
        what_changed = change_lines[0]
    else:
        what_changed = str(
            assessment.get("pm_current_state")
            or "Deterministic state changed; see structural flags."
        )

    against = (
        "Short-leg behavior and drawdown remain below escalation levels."
        if trigger_count == 0
        else str(assessment.get("why_not_act_yet") or "").strip()
        or "Book-level confirmation is still incomplete."
    )

    next_checks = _as_list(assessment.get("next_checks"))
    if not next_checks:
        next_check = "Watch for loser-leg rebound and broader prime-book deleveraging."
    elif len(next_checks) == 1:
        next_check = next_checks[0]
    else:
        next_check = f"{next_checks[0]} {next_checks[1]}"

    message_1 = "\n".join(
        [
            header,
            severity_line,
            f"Primary driver: {mechanism_label(assessment.get('primary_driver'))}",
            f"Deterministic Macro State Change triggers: {trigger_count}/4",
        ]
    )
    message_2 = "\n".join(
        [
            "What changed:",
            what_changed,
            "",
            "What argues against escalation:",
            against,
            "",
            "Next check:",
            next_check,
            "",
            "Not a crash probability.",
        ]
    )
    return f"{message_1}\n\n{message_2}"


def posture_label(posture: str) -> str:
    return POSTURE_LABELS.get(posture, posture)


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
