"""Focused contracts for active GDELT + LLM risk-state interpretation."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.evidence.deepseek_explainer import (
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_OPENAI_MODEL,
    explain_risk_with_deepseek,
    explain_risk_with_llm,
    explain_risk_with_openai,
)
from src.evidence.gdelt_evidence import (
    active_triggers_from_signals,
    retrieve_gdelt_evidence,
)


def _gdelt_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2025-04-23T16:30:00Z"),
                "date": date(2025, 4, 23),
                "title": "Credit a short squeeze for the market bounce",
                "source": "news.example",
                "url": "https://example.com/short-squeeze",
                "gdelt_query": "crowding",
            },
            {
                "timestamp": pd.Timestamp("2025-04-24T16:30:00Z"),
                "date": date(2025, 4, 24),
                "title": "Credit a short squeeze for the market bounce",
                "source": "mirror.example",
                "url": "https://example.com/short-squeeze-mirror",
                "gdelt_query": "crowding",
            },
            {
                "timestamp": pd.Timestamp("2025-04-21T10:30:00Z"),
                "date": date(2025, 4, 21),
                "title": "Will the stock market crash again?",
                "source": "markets.example",
                "url": "https://example.com/crash",
                "gdelt_query": "panic",
            },
            {
                "timestamp": pd.Timestamp("2025-05-02T10:30:00Z"),
                "date": date(2025, 5, 2),
                "title": "Future short squeeze headline",
                "source": "future.example",
                "url": "https://example.com/future",
                "gdelt_query": "crowding",
            },
        ]
    )


def _triggers() -> list[dict[str, object]]:
    return [
        {
            "trigger": "short_loss_in_recovery",
            "observed_value": 0.27,
            "threshold": 0.26,
            "status": "triggered",
            "direction": "greater_than_or_equal",
        }
    ]


def _evidence() -> pd.DataFrame:
    return retrieve_gdelt_evidence(
        _gdelt_rows(),
        as_of_date="2025-05-01",
        active_triggers=_triggers(),
        lookback_days=30,
        max_records=20,
        clamp_max_records=False,
    )


def _valid_response() -> str:
    return (
        '{"trigger_summary":"Short-leg losses are active.",'
        '"recent_narrative":"Coverage mentions a short squeeze [E1].",'
        '"momentum_mechanism":"Short covering may amplify the rebound.",'
        '"key_evidence_ids":["E1"],'
        '"limitations":"Title-only evidence is incomplete.",'
        '"pm_takeaway":"Review the short-leg contribution."}'
    )


def test_retrieval_is_point_in_time_and_deduplicated() -> None:
    evidence = _evidence()

    assert list(evidence["evidence_id"]) == ["E1"]
    assert evidence.iloc[0]["date"] == "2025-04-24"
    assert "future" not in set(evidence["url"])


def test_deterministic_partial_gate_activates_retrieval() -> None:
    active = active_triggers_from_signals(
        [
            {
                "name": "portfolio_drawdown",
                "status": "not_triggered",
                "current_value": -0.17,
                "threshold": -0.20,
                "direction": "less_than_or_equal",
            }
        ],
        include_partial=True,
        partial_ratio=0.70,
    )

    assert active[0]["trigger"] == "portfolio_drawdown"
    assert active[0]["status"] == "partial"


@pytest.mark.parametrize(
    ("runner", "key_name", "expected_provider", "expected_model", "expected_base"),
    [
        (
            explain_risk_with_deepseek,
            "DEEPSEEK_API_KEY",
            "deepseek",
            DEFAULT_DEEPSEEK_MODEL,
            "https://api.deepseek.com",
        ),
        (
            explain_risk_with_openai,
            "OPENAI_API_KEY",
            "openai",
            DEFAULT_OPENAI_MODEL,
            "https://api.openai.com/v1",
        ),
    ],
)
def test_provider_transport_and_validated_json_contract(
    tmp_path,
    runner,
    key_name: str,
    expected_provider: str,
    expected_model: str,
    expected_base: str,
) -> None:
    captured: dict[str, object] = {}

    def transport(**kwargs: object) -> str:
        captured.update(kwargs)
        return _valid_response()

    result = runner(
        _triggers(),
        _evidence(),
        "2025-05-01",
        cache_dir=tmp_path,
        load_dotenv=False,
        environment={key_name: "test-key"},
        transport=transport,
    )

    assert result["status"] == "ok"
    assert result["provider"] == expected_provider
    assert result["model"] == expected_model
    assert result["key_evidence_ids"] == ["E1"]
    assert captured["model"] == expected_model
    assert captured["base_url"] == expected_base
    assert captured["temperature"] == (0.2 if expected_provider == "deepseek" else None)


def test_provider_is_part_of_cache_identity(tmp_path) -> None:
    calls = {"count": 0}

    def transport(**_kwargs: object) -> str:
        calls["count"] += 1
        return _valid_response()

    common = {
        "cache_dir": tmp_path,
        "load_dotenv": False,
        "environment": {
            "DEEPSEEK_API_KEY": "deepseek-key",
            "OPENAI_API_KEY": "openai-key",
        },
        "transport": transport,
    }
    deepseek = explain_risk_with_deepseek(
        _triggers(), _evidence(), "2025-05-01", **common
    )
    openai = explain_risk_with_openai(
        _triggers(), _evidence(), "2025-05-01", **common
    )

    assert deepseek["cached"] is False
    assert openai["cached"] is False
    assert calls["count"] == 2


def test_missing_provider_key_fails_closed(tmp_path) -> None:
    result = explain_risk_with_openai(
        _triggers(),
        _evidence(),
        "2025-05-01",
        cache_dir=tmp_path,
        load_dotenv=False,
        environment={},
    )

    assert result["status"] == "llm_unavailable"
    assert result["provider"] == "openai"
    assert result["trigger_summary"] == ""


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="provider"):
        explain_risk_with_llm(
            _triggers(),
            _evidence(),
            "2025-05-01",
            provider="unknown",
            load_dotenv=False,
            environment={},
        )
