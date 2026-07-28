from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pandas as pd

from src.evidence.research_preview import build_research_preview


def _facts() -> dict:
    return {
        "metrics": {
            "long_beta_126d": 0.82,
            "short_underlying_beta_126d": 2.04,
        },
        "thresholds": {
            "short_minus_long_beta_gap": 0.25,
        },
        "triggered_states": {
            "high_volatility_recovery": True,
            "short_minus_long_beta_gap": True,
        },
    }


def test_evidence_preview_preserves_deterministic_facts() -> None:
    facts = _facts()
    original = copy.deepcopy(facts)
    expected_hash = hashlib.sha256(
        json.dumps(
            facts,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()

    result = build_research_preview(
        deterministic_summary=facts,
        evidence_case_date=pd.Timestamp("2024-01-05"),
    )

    assert facts == original
    assert result["status"] == "sample_only"
    assert result["deterministic_facts_sha256"] == expected_hash
    assert result["deterministic_facts_unchanged"] is True
    assert "risk_score" not in json.dumps(result, sort_keys=True)
    assert facts["thresholds"] == original["thresholds"]
    assert facts["triggered_states"] == original["triggered_states"]


def test_evidence_preview_fails_safely(tmp_path: Path) -> None:
    facts = _facts()
    result = build_research_preview(
        deterministic_summary=facts,
        evidence_case_date=pd.Timestamp("2023-01-09"),
        classification_dir=tmp_path,
    )

    assert result["status"] == "unavailable"
    assert result["supporting"] == []
    assert result["contradicting"] == []
    assert result["contextual"] == []
    assert "unavailable" in result["limitations"][0].lower()
