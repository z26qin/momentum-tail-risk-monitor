"""Lightweight tests for the Hermes monitor adapter (no WhatsApp, no extra pipeline)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.mvp.daily_brief import (
    last_available_session,
    last_completed_us_close,
    persist_and_render,
    render_daily_brief,
    resolve_brief_as_of_date,
)
from src.mvp.hermes_monitor import (
    REQUIRED_ASSESSMENT_FIELDS,
    compare_assessments,
    format_whatsapp_alert,
    format_whatsapp_score_card,
    validate_evidence_cutoff,
)
from src.mvp.monitoring_severity import (
    SCORE_FORMULA,
    format_score_value,
    prior_only_risk_score,
    severity_band,
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
        "monitoring_severity_score": 78,
        "score_label": "elevated",
        "severity_emoji": "🟠",
        "primary_driver": "crowded_unwind",
        "mechanism_scores": {
            "dm_recovery": 25,
            "crowded_unwind": 78,
            "fundamental_repricing": None,
            "book_vulnerability": 55,
        },
        "score_is_probability": False,
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
    previous = _assessment(
        book_read={"portfolio_drawdown": -0.0903},
        monitoring_severity_score=78,
    )
    current = _assessment(
        book_read={"portfolio_drawdown": -0.0911},
        monitoring_severity_score=79,
    )
    result = compare_assessments(current, previous)
    assert result["material_change"] is False


def test_severity_band_change_is_material() -> None:
    previous = _assessment(
        monitoring_severity_score=78,
        score_label="elevated",
        severity_emoji="🟠",
    )
    current = _assessment(
        monitoring_severity_score=81,
        score_label="high",
        severity_emoji="🔴",
    )
    result = compare_assessments(current, previous)
    assert result["material_change"] is True
    assert "Severity band changed: elevated → high" in result["changes"]


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
    assert text.startswith("🟠 MOMENTUM RISK — ELEVATED")
    assert "Severity: 🟠 78/100" in text
    assert "Primary driver: Crowded unwind" in text
    assert "Deterministic Macro State Change triggers: 0/4" in text
    assert "What argues against escalation:" in text
    assert "Next check:" in text
    assert "Not a crash probability." in text
    assert "buy" not in text.lower()
    assert "trade" not in text.lower()


def test_score_card_uses_band_emoji_and_disclaimer() -> None:
    text = format_whatsapp_score_card(_assessment())
    assert text.startswith("🟠 Momentum monitoring severity: 78/100 — Elevated")
    assert "Primary driver: Crowded unwind" in text
    assert "DM recovery: 🟢 25" in text
    assert "Crowded unwind: 🟠 78" in text
    assert "Fundamental repricing: Not available" in text
    assert "Book vulnerability: 🟡 55" in text
    assert "Deterministic Macro State Change triggers: 0/4" in text
    assert "not a 78% crash probability" in text


def test_severity_bands_and_max_null_rules() -> None:
    assert severity_band(0) == ("low", "🟢")
    assert severity_band(39) == ("low", "🟢")
    assert severity_band(40) == ("watch", "🟡")
    assert severity_band(59) == ("watch", "🟡")
    assert severity_band(60) == ("elevated", "🟠")
    assert severity_band(79) == ("elevated", "🟠")
    assert severity_band(80) == ("high", "🔴")
    assert severity_band(100) == ("high", "🔴")
    assert severity_band(None) == (None, None)
    values = pd.Series(
        [1.0, 2.0, 0.0, 3.0],
        index=pd.to_datetime(
            ["2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29"]
        ),
    )
    assert prior_only_risk_score(values, pd.Timestamp("2026-05-29"), invert=False) == 100
    assert prior_only_risk_score(values, pd.Timestamp("2026-05-28"), invert=True) == 100
    assert prior_only_risk_score(values, pd.Timestamp("2026-05-26"), invert=False) is None
    assert "not a crash probability" in SCORE_FORMULA.lower()
    assert format_score_value(25) == "🟢 25"
    assert format_score_value(78, over_100=True) == "🟠 78/100"
    assert format_score_value(None) == "Not available"


def test_compact_schema_fields_are_stable() -> None:
    assert "risk_state" in REQUIRED_ASSESSMENT_FIELDS
    assert "monitoring_severity_score" in REQUIRED_ASSESSMENT_FIELDS
    dumped = json.dumps(_assessment())
    for field in REQUIRED_ASSESSMENT_FIELDS:
        assert field in dumped


def test_cli_scripts_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts" / "run_monitor.py").is_file()
    assert (root / "scripts" / "compare_monitor_state.py").is_file()
    assert (root / "scripts" / "run_daily_brief.py").is_file()
    assert (root / "src" / "mvp" / "daily_brief.py").is_file()
    assert (root / "integrations" / "hermes" / "momentum-risk-monitor" / "SKILL.md").is_file()
    assert (root / "src" / "mvp" / "monitoring_severity.py").is_file()


def test_last_completed_us_close_uses_1600_et() -> None:
    ny = ZoneInfo("America/New_York")
    utc = ZoneInfo("UTC")
    assert last_completed_us_close(datetime(2026, 5, 29, 16, 0, tzinfo=ny)) == "2026-05-29"
    assert last_completed_us_close(datetime(2026, 5, 29, 15, 59, tzinfo=ny)) == "2026-05-28"
    assert last_completed_us_close(datetime(2026, 5, 30, 9, 0, tzinfo=ny)) == "2026-05-29"
    assert last_completed_us_close(datetime(2026, 5, 29, 16, 0)) == "2026-05-29"
    # 2026-05-29 is EDT (UTC-4): 20:00 UTC is the 16:00 ET close.
    assert last_completed_us_close(datetime(2026, 5, 29, 20, 0, tzinfo=utc)) == "2026-05-29"
    assert last_completed_us_close(datetime(2026, 5, 29, 19, 59, tzinfo=utc)) == "2026-05-28"


def test_last_available_session_walks_to_last_data_date(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {"date": pd.to_datetime(["2026-05-27", "2026-05-28", "2026-05-29"])}
    )
    frame.to_parquet(tmp_path / "leg_risk_history.parquet")
    assert last_available_session(tmp_path, "2026-05-31") == "2026-05-29"
    assert last_available_session(tmp_path, "2026-05-28") == "2026-05-28"
    with pytest.raises(ValueError, match="no processed session"):
        last_available_session(tmp_path, "2026-05-01")


def test_resolve_brief_as_of_date_prefers_override_then_demo(tmp_path: Path) -> None:
    frame = pd.DataFrame({"date": pd.to_datetime(["2026-06-30"])})
    frame.to_parquet(tmp_path / "leg_risk_history.parquet")
    ny = ZoneInfo("America/New_York")
    assert (
        resolve_brief_as_of_date(as_of_date="2026-05-29", demo=True) == "2026-05-29"
    )
    assert resolve_brief_as_of_date(demo=True) == "2026-05-29"
    assert (
        resolve_brief_as_of_date(
            now=datetime(2026, 8, 15, 16, 30, tzinfo=ny),
            processed_dir=tmp_path,
        )
        == "2026-06-30"
    )


def test_daily_brief_is_silent_until_band_changes() -> None:
    current = _assessment()
    assert render_daily_brief(current, None) == "[SILENT]"
    assert render_daily_brief(current, current) == "[SILENT]"
    drifted = _assessment(monitoring_severity_score=79)
    assert render_daily_brief(drifted, current) == "[SILENT]"
    upgraded = _assessment(
        monitoring_severity_score=81,
        score_label="high",
        severity_emoji="🔴",
    )
    text = render_daily_brief(upgraded, current)
    assert text != "[SILENT]"
    assert text.startswith("🔴 MOMENTUM RISK — HIGH")
    assert "Severity band changed: elevated → high" in text


def test_persist_and_render_promotes_previous_unless_dry_run(tmp_path: Path) -> None:
    assessment_path = tmp_path / "latest_assessment.json"
    comparison_path = tmp_path / "latest_comparison.json"
    previous_path = tmp_path / "previous_assessment.json"
    first = persist_and_render(
        _assessment(),
        previous_path=previous_path,
        assessment_path=assessment_path,
        comparison_path=comparison_path,
        update_previous=False,
    )
    assert first.silent is True
    assert first.is_baseline is True
    assert first.text == "[SILENT]"
    assert not previous_path.is_file()
    second = persist_and_render(
        _assessment(),
        previous_path=previous_path,
        assessment_path=assessment_path,
        comparison_path=comparison_path,
    )
    assert second.is_baseline is True
    assert previous_path.is_file()
    third = persist_and_render(
        _assessment(),
        previous_path=previous_path,
        assessment_path=assessment_path,
        comparison_path=comparison_path,
    )
    assert third.silent is True
    assert third.is_baseline is False
