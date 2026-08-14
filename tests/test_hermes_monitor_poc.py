"""Lightweight tests for the Hermes monitor adapter (no WhatsApp, no extra pipeline)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.mvp.hermes_monitor import (
    REQUIRED_ASSESSMENT_FIELDS,
    compare_assessments,
    format_whatsapp_alert,
    validate_evidence_cutoff,
)


def _assessment(**overrides):
    payload = {
        "schema_version": "hermes-monitor-v1",
        "as_of_date": "2026-05-29",
        "evidence_cutoff": "2026-05-29 16:00 ET",
        "overall_risk_state": "normal",
        "pm_posture": "escalate_for_pm_review",
        "risk_state": "escalate_for_pm_review",
        "mechanical_unwind_state": "FRAGILITY_BUILDING",
        "deterministic_trigger_count": 0,
        "triggered_channels": [],
        "structural_flags": ["crowded_theme_unwind", "portfolio_concentration"],
        "book_read": {"portfolio_drawdown": -0.09},
        "evidence_needed": True,
        "supported_mechanisms": ["crowded_theme_unwind"],
        "unconfirmed_mechanisms": [
            "bear_market_recovery_crash",
            "short_book_reversal_crash",
        ],
        "next_checks": ["Watch for a loser-leg rebound."],
        "supporting_evidence_ids": ["csu-2026-05-29-013"],
        "contradicting_evidence_ids": ["csu-2026-05-29-008"],
        "theme_cluster": ["CIEN", "COHR", "LITE"],
        "why_not_act_yet": "Selling is still being absorbed.",
        "pm_current_state": "Escalate for PM review.",
    }
    payload.update(overrides)
    return payload


def test_cutoff_must_match_repository_us_close() -> None:
    assert (
        validate_evidence_cutoff("2026-05-29", "2026-05-29 16:00 ET")
        == "2026-05-29 16:00 ET"
    )
    with pytest.raises(ValueError, match="as_of_date"):
        validate_evidence_cutoff("2026-05-29", "2026-05-28 16:00 ET")
    with pytest.raises(ValueError, match="16:00"):
        validate_evidence_cutoff("2026-05-29", "2026-05-29 09:30 ET")


def test_first_compare_is_baseline_not_an_alert() -> None:
    result = compare_assessments(_assessment(), None)
    assert result["is_baseline"] is True
    assert result["material_change"] is False
    assert result["silent"] is True
    assert result["changes"] == ["Initial baseline created"]


def test_unchanged_compare_is_silent() -> None:
    current = _assessment()
    result = compare_assessments(current, current)
    assert result["material_change"] is False
    assert result["silent"] is True
    assert result["changes"] == []


def test_numeric_drift_is_not_material() -> None:
    previous = _assessment(book_read={"portfolio_drawdown": -0.0903})
    current = _assessment(book_read={"portfolio_drawdown": -0.0911})
    result = compare_assessments(current, previous)
    assert result["material_change"] is False


def test_new_structural_flag_is_material() -> None:
    previous = _assessment(structural_flags=["portfolio_concentration"])
    current = _assessment()
    result = compare_assessments(current, previous)
    assert result["material_change"] is True
    assert "New structural flag: crowded_theme_unwind" in result["changes"]


def test_draft_alert_is_whatsapp_short() -> None:
    comparison = compare_assessments(
        _assessment(),
        _assessment(structural_flags=["portfolio_concentration"]),
    )
    text = format_whatsapp_alert(_assessment(), comparison)
    assert text.startswith("MOMENTUM RISK — STATE CHANGE")
    assert "As of: 2026-05-29 16:00 ET" in text
    assert "Book triggers: 0/4" in text
    assert "Against the hypothesis:" in text
    assert "Next check:" in text
    assert "buy" not in text.lower()
    assert "trade" not in text.lower()


def test_compact_schema_fields_are_stable() -> None:
    assert "risk_state" in REQUIRED_ASSESSMENT_FIELDS
    dumped = json.dumps(_assessment())
    for field in REQUIRED_ASSESSMENT_FIELDS:
        assert field in dumped


def test_cli_scripts_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts" / "run_monitor.py").is_file()
    assert (root / "scripts" / "compare_monitor_state.py").is_file()
    assert (root / "integrations" / "hermes" / "momentum-risk-monitor" / "SKILL.md").is_file()
