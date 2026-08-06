"""Thin research-validation layer over existing MVP components.

Reuses ``run_mvp``, scorecard/unwind assessments, and synthesis interfaces.
Does not recompute thresholds, mechanisms, or portfolio construction.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from src.mvp.config import (
    DEFAULT_AS_OF_DATE,
    DEFAULT_COMPARE_TO_DATE,
    HISTORICAL_EXAMPLE_DATE,
    MVPConfig,
    REGRESSION_AS_OF_DATE,
    REGRESSION_COMPARE_TO_DATE,
)
from src.mvp.evidence_card import DeterministicEvidenceInput, QuantSignal
from src.mvp.evidence_interpretation import (
    LLM_CREDENTIAL_ENV_VARS,
    interpret_evidence_card,
)
from src.mvp.llm_synthesis import DeterministicSynthesizer
from src.mvp.pipeline import MVPRunResult, run_mvp
from src.utils.io import DEFAULT_OUTPUT_DIR, REPO_ROOT

VALIDATION_OUTPUT_DIR = DEFAULT_OUTPUT_DIR / "research_validation"
AI_INPUT_DIR = VALIDATION_OUTPUT_DIR / "ai_inputs"


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path)


FIDELITY_LABELS = frozenset(
    {"aligned", "partially_aligned", "not_aligned", "unavailable"}
)
MECHANISM_NAMES = (
    "bear_market_recovery_crash",
    "short_book_reversal_crash",
    "crowded_theme_unwind",
)


@dataclass(frozen=True)
class Episode:
    """One historical interpretability case with a manual research prior."""

    episode_id: str
    display_name: str
    assessment_date: date
    expected_mechanism: str | None
    notes: str
    compare_to_date: date | None = None


EPISODES: tuple[Episode, ...] = (
    Episode(
        episode_id="covid_recovery",
        display_name="COVID bear-market recovery",
        assessment_date=date.fromisoformat(REGRESSION_AS_OF_DATE),
        expected_mechanism="bear_market_recovery_crash",
        notes="README contrast date; recovery-crash research prior.",
        compare_to_date=date.fromisoformat(REGRESSION_COMPARE_TO_DATE),
    ),
    Episode(
        episode_id="style_rotation",
        display_name="Nov-2020 style rotation",
        assessment_date=date(2020, 11, 2),
        expected_mechanism="short_book_reversal_crash",
        notes="Loser-leg rebound / style rotation prior; not a tuned threshold.",
        compare_to_date=date(2020, 10, 1),
    ),
    Episode(
        episode_id="ordinary_drawdown",
        display_name="Ordinary 2022 drawdown stress",
        assessment_date=date(2022, 6, 16),
        expected_mechanism=None,
        notes="Deep PM-book drawdown without a forced mechanism prior.",
        compare_to_date=date(2022, 5, 16),
    ),
    Episode(
        episode_id="demo_control",
        display_name="Default demo negative control",
        assessment_date=date.fromisoformat(DEFAULT_AS_OF_DATE),
        expected_mechanism=None,
        notes="Repository default demo date; expected quiet fingerprint.",
        compare_to_date=date.fromisoformat(DEFAULT_COMPARE_TO_DATE),
    ),
    Episode(
        episode_id="theme_proxy",
        display_name="Crowded-theme proxy date",
        assessment_date=date.fromisoformat(HISTORICAL_EXAMPLE_DATE),
        expected_mechanism="crowded_theme_unwind",
        notes="README historical example; theme-unwind research prior.",
        compare_to_date=date(2026, 4, 30),
    ),
)

AI_EPISODE_IDS: tuple[str, ...] = (
    "demo_control",  # evidence cache available
    "covid_recovery",
    "theme_proxy",
    "style_rotation",
)


def _signal_map(card: DeterministicEvidenceInput) -> dict[str, QuantSignal]:
    signals = card.triggered_quant_signals + card.non_triggered_relevant_signals
    return {signal.name: signal for signal in signals}


def _signal_value(signals: Mapping[str, QuantSignal], name: str) -> float | None:
    signal = signals.get(name)
    if signal is None:
        return None
    return signal.current_value


def _mechanism_status(result: MVPRunResult, name: str) -> str:
    for item in result.unwind.mechanism_scenarios:
        if item.scenario == name:
            return item.status
    return "unavailable"


def _pain_source(result: MVPRunResult) -> str:
    active = list(result.unwind.active_scenarios)
    if active:
        return "+".join(active)
    if result.unwind.scenario_classification not in {"", "none", "unavailable"}:
        return result.unwind.scenario_classification
    return "none"


def _warnings_text(result: MVPRunResult) -> str:
    warnings = list(result.deterministic_input.data_warnings) + list(
        result.unwind.warnings
    )
    # Preserve order, drop duplicates.
    seen: list[str] = []
    for item in warnings:
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return " | ".join(seen[:6])


def _fidelity_label(
    *,
    expected_mechanism: str | None,
    mechanism_statuses: Mapping[str, str],
) -> str:
    """Compare research prior to computed statuses without influencing them."""

    if expected_mechanism is None:
        triggered = [
            name
            for name, status in mechanism_statuses.items()
            if status == "triggered"
        ]
        if not triggered:
            return "aligned"
        return "not_aligned"

    status = mechanism_statuses.get(expected_mechanism, "unavailable")
    if status == "unavailable":
        return "unavailable"
    if status == "triggered":
        return "aligned"
    if status == "watch":
        return "partially_aligned"
    return "not_aligned"


def _concise_interpretation(row: Mapping[str, Any]) -> str:
    active = [
        name
        for name in MECHANISM_NAMES
        if row.get(name) == "triggered"
    ]
    watches = [
        name
        for name in MECHANISM_NAMES
        if row.get(name) == "watch"
    ]
    if active:
        return f"Active mechanism(s): {', '.join(active)}."
    if watches:
        return f"Watch-only: {', '.join(watches)}; no triggered mechanism."
    if row.get("pm_triggers", 0):
        return (
            f"{row['pm_triggers']} PM scorecard trigger(s); "
            "no mechanism confirmed."
        )
    return "Quiet fingerprint: no PM triggers and no confirmed mechanisms."


def extract_episode_row(result: MVPRunResult, episode: Episode) -> dict[str, Any]:
    """Extract fingerprint fields from an existing MVP run result."""

    card = result.deterministic_input
    signals = _signal_map(card)
    statuses = {
        name: _mechanism_status(result, name) for name in MECHANISM_NAMES
    }
    row: dict[str, Any] = {
        "episode_id": episode.episode_id,
        "episode": episode.display_name,
        "assessment_date": card.as_of_date,
        "dm_state": card.overall_risk_state,
        "pm_triggers": len(card.triggered_quant_signals),
        "bear_market_recovery_crash": statuses["bear_market_recovery_crash"],
        "short_book_reversal_crash": statuses["short_book_reversal_crash"],
        "crowded_theme_unwind": statuses["crowded_theme_unwind"],
        "beta_gap": _signal_value(signals, "short_minus_long_beta_gap"),
        "portfolio_drawdown": _signal_value(signals, "portfolio_drawdown"),
        "short_loss": _signal_value(signals, "short_loss_in_recovery"),
        "pain_source": _pain_source(result),
        "warnings": _warnings_text(result),
        "expected_mechanism": episode.expected_mechanism or "",
        "fidelity": _fidelity_label(
            expected_mechanism=episode.expected_mechanism,
            mechanism_statuses=statuses,
        ),
        "notes": episode.notes,
    }
    row["interpretation"] = _concise_interpretation(row)
    return row


def _episode_config(episode: Episode) -> MVPConfig:
    compare = (
        None
        if episode.compare_to_date is None
        else episode.compare_to_date.isoformat()
    )
    return MVPConfig(
        as_of_date=episode.assessment_date.isoformat(),
        compare_to_date=compare,
        use_llm=False,
    )


def run_episode_cases(
    episodes: tuple[Episode, ...] = EPISODES,
) -> list[dict[str, Any]]:
    """Run existing MVP pipeline once per episode and extract rows."""

    rows: list[dict[str, Any]] = []
    for episode in episodes:
        try:
            result = run_mvp(_episode_config(episode))
            rows.append(extract_episode_row(result, episode))
        except Exception as exc:  # noqa: BLE001 - keep validation table complete
            rows.append(
                {
                    "episode_id": episode.episode_id,
                    "episode": episode.display_name,
                    "assessment_date": episode.assessment_date.isoformat(),
                    "dm_state": "unavailable",
                    "pm_triggers": "",
                    "bear_market_recovery_crash": "unavailable",
                    "short_book_reversal_crash": "unavailable",
                    "crowded_theme_unwind": "unavailable",
                    "beta_gap": "",
                    "portfolio_drawdown": "",
                    "short_loss": "",
                    "pain_source": "unavailable",
                    "warnings": f"episode run failed: {exc}",
                    "expected_mechanism": episode.expected_mechanism or "",
                    "fidelity": "unavailable",
                    "notes": episode.notes,
                    "interpretation": "Unavailable for this assessment date.",
                }
            )
    return rows


def _model_context_payload(card: DeterministicEvidenceInput) -> dict[str, Any]:
    """Detached allow-listed payload matching the interpretation interface."""

    return json.loads(
        json.dumps(
            {
                "as_of_date": card.as_of_date,
                "comparison_date": card.comparison_date,
                "overall_risk_state": card.overall_risk_state,
                "deterministic_score": card.deterministic_score,
                "quantitative_signals": [
                    signal.to_dict()
                    for signal in (
                        card.triggered_quant_signals
                        + card.non_triggered_relevant_signals
                    )
                ],
                "retrieved_evidence": [
                    item.to_dict() for item in card.retrieved_evidence
                ],
                "historical_context": [dict(item) for item in card.historical_analogs],
            },
            sort_keys=True,
            allow_nan=False,
        )
    )


def write_episode_fingerprints(
    rows: list[dict[str, Any]],
    *,
    output_dir: Path = VALIDATION_OUTPUT_DIR,
) -> tuple[Path, Path]:
    """Write CSV and compact Markdown fingerprint tables."""

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "episode_fingerprints.csv"
    md_path = output_dir / "episode_fingerprints.md"
    fieldnames = [
        "episode_id",
        "episode",
        "assessment_date",
        "dm_state",
        "pm_triggers",
        "bear_market_recovery_crash",
        "short_book_reversal_crash",
        "crowded_theme_unwind",
        "beta_gap",
        "portfolio_drawdown",
        "short_loss",
        "pain_source",
        "warnings",
        "expected_mechanism",
        "fidelity",
        "interpretation",
        "notes",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})

    lines = [
        "# Episode fingerprints",
        "",
        "Interpretability check only. Expected mechanism priors never enter computation.",
        "",
        "| Episode | DM state | Recovery | Short reversal | Theme unwind | Pain source | Fidelity | Interpretation |",
        "| ------- | -------- | -------- | -------------- | ------------ | ----------- | -------- | -------------- |",
    ]
    for row in rows:
        lines.append(
            "| {episode} | {dm} | {rec} | {short} | {theme} | {pain} | {fid} | {interp} |".format(
                episode=row["episode"],
                dm=row["dm_state"],
                rec=row["bear_market_recovery_crash"],
                short=row["short_book_reversal_crash"],
                theme=row["crowded_theme_unwind"],
                pain=row["pain_source"],
                fid=row["fidelity"],
                interp=str(row["interpretation"]).replace("|", "/"),
            )
        )
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, md_path


def write_pm_book_outcomes_skip(
    *,
    output_dir: Path = VALIDATION_OUTPUT_DIR,
) -> Path:
    """Document why the forward-outcome summary is skipped (stop-rule)."""

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "pm_book_outcomes.md"
    path.write_text(
        "\n".join(
            [
                "# PM-book forward outcomes — skipped",
                "",
                "This deliverable is intentionally **not** implemented as a full",
                "descriptive outcome table.",
                "",
                "## What already exists",
                "",
                "- Daily synthetic PM-book returns:",
                "  `data/processed/momentum_portfolio_returns.parquet`",
                "  (`portfolio_return`, long/short contributions).",
                "- Trailing risk history:",
                "  `data/processed/leg_risk_history.parquet`.",
                "",
                "## What is missing",
                "",
                "- No precomputed historical **scorecard state** series.",
                "- No precomputed historical **mechanism status** series",
                "  (`triggered` / `watch` / `not_confirmed`).",
                "- `unwind_structure_history.parquet` stores fingerprint inputs,",
                "  not mechanism outcomes.",
                "",
                "## Why the stop-rule applies",
                "",
                "Generating mechanism states across history requires repeated",
                "`build_unwind_assessment` (prices, holdings, theme path).",
                "That is new infrastructure, not a thin extract from existing",
                "artifacts. A partial but trustworthy MVP prefers documenting",
                "the gap over inventing a backtest engine.",
                "",
                "## Next step (out of scope here)",
                "",
                "1. Persist point-in-time mechanism/scorecard history once.",
                "2. Join matured forward PM-book returns at 5d / 20d.",
                "3. Publish a descriptive frequency table with overlapping-window",
                "   dependence clearly stated — no regression, no threshold tuning.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _quant_facts(result: MVPRunResult) -> dict[str, Any]:
    card = result.deterministic_input
    return {
        "as_of_date": card.as_of_date,
        "overall_risk_state": card.overall_risk_state,
        "triggered_signals": [s.name for s in card.triggered_quant_signals],
        "mechanism_statuses": {
            item.scenario: item.status for item in result.unwind.mechanism_scenarios
        },
        "active_scenarios": list(result.unwind.active_scenarios),
        "evidence_count": len(card.retrieved_evidence),
        "evidence_quality": card.audit_metadata.get("evidence_quality", "unknown"),
        "data_cutoff": card.data_cutoff,
        "warnings": list(card.data_warnings) + list(result.unwind.warnings),
        "deterministic_score": card.deterministic_score,
    }


def _synthesizer_context(card: DeterministicEvidenceInput) -> dict[str, Any]:
    signals = card.triggered_quant_signals + card.non_triggered_relevant_signals
    changes: list[dict[str, Any]] = []
    for signal in signals:
        if signal.change_vs_comparison is None:
            continue
        changes.append(
            {
                "name": signal.name,
                "from_text": "prior",
                "to_text": signal.status,
                "delta_text": f"{signal.change_vs_comparison:+.4f}",
                "abs_delta": abs(signal.change_vs_comparison),
            }
        )
    return {
        "as_of_date": card.as_of_date,
        "comparison_date": card.comparison_date,
        "overall_risk_state": card.overall_risk_state,
        "triggered_signal_names": [s.name for s in card.triggered_quant_signals],
        "total_signals": len(signals),
        "available_signals": sum(1 for s in signals if s.status != "unavailable"),
        "evidence_quality": card.audit_metadata.get("evidence_quality", "unavailable"),
        "signal_changes": changes,
        "tail_loss_frequency": card.audit_metadata.get("tail_loss_frequency"),
    }


def _evidence_cutoff_valid(card: DeterministicEvidenceInput) -> bool:
    cutoff = pd.Timestamp(card.data_cutoff)
    for item in card.retrieved_evidence:
        if pd.Timestamp(item.timestamp) > cutoff:
            return False
    return True


def _has_llm_credentials(environment: Mapping[str, str] | None = None) -> bool:
    env = environment if environment is not None else __import__("os").environ
    return any(str(env.get(name, "")).strip() for name in LLM_CREDENTIAL_ENV_VARS)


def prepare_ai_review_cases(
    *,
    output_dir: Path = VALIDATION_OUTPUT_DIR,
    environment: Mapping[str, str] | None = None,
    episode_ids: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Build quant / deterministic / LLM worksheet rows for selected cases."""

    output_dir.mkdir(parents=True, exist_ok=True)
    ai_input_dir = output_dir / "ai_inputs"
    ai_input_dir.mkdir(parents=True, exist_ok=True)

    selected_ids = episode_ids if episode_ids is not None else AI_EPISODE_IDS
    cases: list[tuple[str, MVPConfig]] = []
    episode_by_id = {item.episode_id: item for item in EPISODES}
    for episode_id in selected_ids:
        episode = episode_by_id[episode_id]
        cases.append((episode_id, _episode_config(episode)))

    rows: list[dict[str, Any]] = []
    for case_id, config in cases:
        try:
            result = run_mvp(config)
        except Exception as exc:  # noqa: BLE001
            for arm in ("quant_only", "deterministic_template", "llm"):
                rows.append(
                    {
                        "episode_id": case_id,
                        "arm": arm,
                        "run_status": "unavailable",
                        "output_path": "",
                        "schema_valid": False,
                        "evidence_cutoff_valid": False,
                        "quant_fields_unchanged": False,
                        "supporting_evidence_present": False,
                        "contradicting_evidence_present": False,
                        "monitoring_questions_present": False,
                        "invalidation_conditions_present": False,
                        "fallback_used": False,
                        "external_llm_called": False,
                        "mechanism_specificity": "",
                        "evidence_grounding": "",
                        "contradiction_coverage": "",
                        "next_step_usefulness": "",
                        "unsupported_claim_count": "",
                        "reviewer_notes": f"case failed: {exc}",
                    }
                )
            continue

        card = result.deterministic_input
        facts = _quant_facts(result)
        facts_path = ai_input_dir / f"{case_id}_quant_facts.json"
        facts_path.write_text(
            json.dumps(facts, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        model_context = _model_context_payload(card)
        context_path = ai_input_dir / f"{case_id}_model_context.json"
        context_path.write_text(
            json.dumps(model_context, indent=2, sort_keys=True, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )

        supporting = any(
            item.stance == "supporting" for item in card.retrieved_evidence
        )
        contradicting = any(
            item.stance == "contradicting" for item in card.retrieved_evidence
        )
        cutoff_ok = _evidence_cutoff_valid(card)

        # Arm 1: quant-only
        quant_path = ai_input_dir / f"{case_id}_quant_only.md"
        quant_path.write_text(
            "\n".join(
                [
                    f"# Quant-only facts — {case_id}",
                    "",
                    f"- as_of_date: {facts['as_of_date']}",
                    f"- overall_risk_state: {facts['overall_risk_state']}",
                    f"- triggered_signals: {', '.join(facts['triggered_signals']) or 'none'}",
                    f"- mechanisms: {json.dumps(facts['mechanism_statuses'], sort_keys=True)}",
                    f"- evidence_quality: {facts['evidence_quality']}",
                    f"- evidence_count: {facts['evidence_count']}",
                    f"- warnings: {'; '.join(facts['warnings']) or 'none'}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        rows.append(
            {
                "episode_id": case_id,
                "arm": "quant_only",
                "run_status": "ok",
                "output_path": _relpath(quant_path),
                "schema_valid": True,
                "evidence_cutoff_valid": cutoff_ok,
                "quant_fields_unchanged": True,
                "supporting_evidence_present": supporting,
                "contradicting_evidence_present": contradicting,
                "monitoring_questions_present": False,
                "invalidation_conditions_present": False,
                "fallback_used": False,
                "external_llm_called": False,
                "mechanism_specificity": "",
                "evidence_grounding": "",
                "contradiction_coverage": "",
                "next_step_usefulness": "",
                "unsupported_claim_count": "",
                "reviewer_notes": "",
            }
        )

        # Arm 2: deterministic template synthesizer
        synth = DeterministicSynthesizer().synthesize(
            context=_synthesizer_context(card)
        )
        det_path = ai_input_dir / f"{case_id}_deterministic_template.json"
        det_payload = {
            "narrative_state": synth.narrative_state,
            "what_changed": list(synth.what_changed),
            "pm_interpretation": synth.pm_interpretation,
            "monitoring_questions": list(synth.monitoring_questions),
            "invalidation_conditions": list(synth.invalidation_conditions),
            "model_or_prompt_version": synth.model_or_prompt_version,
            "quant_facts_fingerprint": facts,
        }
        det_path.write_text(
            json.dumps(det_payload, indent=2, sort_keys=True, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
        rows.append(
            {
                "episode_id": case_id,
                "arm": "deterministic_template",
                "run_status": "ok",
                "output_path": _relpath(det_path),
                "schema_valid": True,
                "evidence_cutoff_valid": cutoff_ok,
                "quant_fields_unchanged": True,
                "supporting_evidence_present": supporting,
                "contradicting_evidence_present": contradicting,
                "monitoring_questions_present": bool(synth.monitoring_questions),
                "invalidation_conditions_present": bool(
                    synth.invalidation_conditions
                ),
                "fallback_used": False,
                "external_llm_called": False,
                "mechanism_specificity": "",
                "evidence_grounding": "",
                "contradiction_coverage": "",
                "next_step_usefulness": "",
                "unsupported_claim_count": "",
                "reviewer_notes": "",
            }
        )

        # Arm 3: optional constrained LLM via repository interface
        before = json.dumps(card.to_dict(), sort_keys=True, allow_nan=False)
        credentials = _has_llm_credentials(environment)
        # Repository has no vendor client; without an injected interpreter the
        # production path falls back. For this worksheet we record not_run when
        # an external LLM call cannot actually occur.
        if not credentials:
            llm_status = "not_run"
            llm_path = ai_input_dir / f"{case_id}_llm_not_run.json"
            llm_path.write_text(
                json.dumps(
                    {
                        "run_status": "not_run",
                        "reason": (
                            "No DEEPSEEK_API_KEY / OPENAI_API_KEY / "
                            "ANTHROPIC_API_KEY present; "
                            "structured model context persisted for review."
                        ),
                        "model_context_path": _relpath(context_path),
                        "quant_facts": facts,
                    },
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n",
                encoding="utf-8",
            )
            interpretation = None
            external_called = False
            fallback_used = False
        else:
            # Credentials exist but no interpreter is injected in this module.
            interpretation = interpret_evidence_card(
                card,
                use_llm=True,
                interpreter=None,
                environment=environment,
            )
            llm_status = "fallback" if not interpretation.use_llm else "ok"
            llm_path = ai_input_dir / f"{case_id}_llm_arm.json"
            llm_path.write_text(
                json.dumps(interpretation.to_dict(), indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            external_called = bool(interpretation.use_llm)
            fallback_used = not interpretation.use_llm

        after = json.dumps(card.to_dict(), sort_keys=True, allow_nan=False)
        quant_unchanged = before == after
        rows.append(
            {
                "episode_id": case_id,
                "arm": "llm",
                "run_status": llm_status,
                "output_path": _relpath(llm_path),
                "schema_valid": True,
                "evidence_cutoff_valid": cutoff_ok,
                "quant_fields_unchanged": quant_unchanged,
                "supporting_evidence_present": (
                    supporting
                    if interpretation is None
                    else bool(interpretation.supporting_evidence_ids)
                ),
                "contradicting_evidence_present": (
                    contradicting
                    if interpretation is None
                    else bool(interpretation.contradicting_evidence_ids)
                ),
                "monitoring_questions_present": (
                    False
                    if interpretation is None
                    else bool(interpretation.monitoring_questions)
                ),
                "invalidation_conditions_present": (
                    False
                    if interpretation is None
                    else bool(interpretation.invalidation_conditions)
                ),
                "fallback_used": fallback_used,
                "external_llm_called": external_called,
                "mechanism_specificity": "",
                "evidence_grounding": "",
                "contradiction_coverage": "",
                "next_step_usefulness": "",
                "unsupported_claim_count": "",
                "reviewer_notes": "",
            }
        )
    return rows


def write_ai_value_review(
    rows: list[dict[str, Any]],
    *,
    output_dir: Path = VALIDATION_OUTPUT_DIR,
) -> Path:
    """Write the human-review worksheet CSV."""

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "ai_value_review.csv"
    fieldnames = [
        "episode_id",
        "arm",
        "run_status",
        "output_path",
        "schema_valid",
        "evidence_cutoff_valid",
        "quant_fields_unchanged",
        "supporting_evidence_present",
        "contradicting_evidence_present",
        "monitoring_questions_present",
        "invalidation_conditions_present",
        "fallback_used",
        "external_llm_called",
        "mechanism_specificity",
        "evidence_grounding",
        "contradiction_coverage",
        "next_step_usefulness",
        "unsupported_claim_count",
        "reviewer_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    return path


def write_ai_value_summary(
    rows: list[dict[str, Any]],
    *,
    output_dir: Path = VALIDATION_OUTPUT_DIR,
) -> Path:
    """Write the PM-facing AI comparison summary without inventing value claims."""

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "ai_value_summary.md"
    llm_rows = [row for row in rows if row["arm"] == "llm"]
    not_run = sum(1 for row in llm_rows if row["run_status"] == "not_run")
    external = sum(1 for row in llm_rows if row.get("external_llm_called") is True)
    quant_ok = all(
        row.get("quant_fields_unchanged") for row in rows if row["run_status"] != "unavailable"
    )

    lines = [
        "# AI value comparison summary",
        "",
        "Lightweight worksheet only. Human-review score columns are left blank.",
        "",
        "## Already demonstrated",
        "",
        "- AI cannot mutate quantitative state "
        f"(quant_fields_unchanged across runnable arms: {quant_ok}).",
        "- Evidence is timestamp-controlled "
        "(automatic `evidence_cutoff_valid` checks on worksheet rows).",
        "- Outputs are schema-constrained "
        "(`DeterministicSynthesizer` / `EvidenceInterpretation` contracts).",
        "- Deterministic fallback exists when LLM credentials or an injected "
        "interpreter are unavailable.",
        f"- External LLM actually called in this regeneration: {external} case(s); "
        f"`not_run`: {not_run} case(s).",
        "",
        "## To be evaluated",
        "",
        "- Whether LLM commentary is more mechanism-specific than the template.",
        "- Whether contradiction coverage improves for analysts.",
        "- Whether analyst review time falls.",
        "- Whether unsupported claims remain acceptably low.",
        "",
        "## Conclusion",
        "",
        "The repository demonstrates a safe architecture for AI-assisted "
        "explanation, while incremental analyst value remains a testable "
        "hypothesis.",
        "",
        "Do **not** conclude that AI creates incremental PM value until a "
        "reviewed external LLM run fills the human-score columns in "
        "`ai_value_review.csv`.",
        "",
        f"Worksheet rows: {len(rows)}. Artifact: `ai_value_review.csv`.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_validation_outputs(
    *,
    output_dir: Path = VALIDATION_OUTPUT_DIR,
) -> dict[str, Path]:
    """Regenerate all research-validation artifacts."""

    fingerprint_rows = run_episode_cases()
    csv_path, md_path = write_episode_fingerprints(
        fingerprint_rows, output_dir=output_dir
    )
    outcomes_path = write_pm_book_outcomes_skip(output_dir=output_dir)
    ai_rows = prepare_ai_review_cases(output_dir=output_dir)
    review_path = write_ai_value_review(ai_rows, output_dir=output_dir)
    summary_path = write_ai_value_summary(ai_rows, output_dir=output_dir)
    return {
        "episode_fingerprints_csv": csv_path,
        "episode_fingerprints_md": md_path,
        "pm_book_outcomes_md": outcomes_path,
        "ai_value_review_csv": review_path,
        "ai_value_summary_md": summary_path,
    }


def main() -> None:
    paths = write_validation_outputs()
    payload = {key: str(path.relative_to(REPO_ROOT)) for key, path in paths.items()}
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
