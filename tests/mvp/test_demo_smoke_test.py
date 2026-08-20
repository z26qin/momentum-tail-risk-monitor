from __future__ import annotations

from src.mvp.demo_smoke_test import run_smoke_test


def test_pre_demo_smoke_test_is_ready_and_date_driven() -> None:
    result = run_smoke_test()

    assert result["status"] == "ready"
    assert result["demo_mode"] is True
    assert result["primary_run_id"] != result["regression_run_id"]
    assert result["primary_state"] != result["regression_state"]
    assert result["evidence_items"] > 0
    assert result["interpretation_use_llm"] is False
    assert result["threshold_profile"] == "default"
    assert result["unwind_scorecard_rows"] == 6
    assert result["unwind_schema_version"] == "momentum-unwind-assessment-v2"
    assert len(result["mechanism_statuses"]) == 3
    assert result["theme_definition_cutoff"] < result["primary_date"]
    assert result["unwind_completeness"] in {"high", "moderate"}
    assert isinstance(result["unwind_scenario"], str)
    assert result["interpretation_version"].startswith(
        "deterministic-evidence-interpretation-"
    )
