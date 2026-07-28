from __future__ import annotations

from src.mvp.demo_smoke_test import run_smoke_test


def test_pre_demo_smoke_test_is_ready_and_date_driven() -> None:
    result = run_smoke_test()

    assert result["status"] == "ready"
    assert result["demo_mode"] is True
    assert result["primary_run_id"] != result["regression_run_id"]
    assert result["primary_state"] != result["regression_state"]
    assert result["evidence_items"] > 0
    assert result["synthesis_mode"] == "deterministic_no_llm"
