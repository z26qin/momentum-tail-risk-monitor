"""Focused tests for the thin GDELT evidence explanation layer."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.evidence.deepseek_explainer import explain_risk_with_deepseek
from src.evidence.gdelt_evidence import (
    DEFAULT_MAX_RECORDS,
    MAX_RECORDS_RANGE,
    TRIGGER_KEYWORDS,
    active_triggers_from_signals,
    no_active_trigger_message,
    resolve_max_records,
    retrieve_gdelt_evidence,
)


def _sample_gdelt() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2024-01-02T12:00:00Z"),
                "date": date(2024, 1, 2),
                "title": "Credit a short squeeze for the stock market bounce",
                "source": "nbcnewyork.com",
                "url": "https://example.com/a",
                "language": "English",
                "sourcecountry": "United States",
                "gdelt_query": "crowding",
            },
            {
                "timestamp": pd.Timestamp("2024-01-04T09:00:00Z"),
                "date": date(2024, 1, 4),
                "title": "Sector rotation and high beta leadership continue",
                "source": "example.com",
                "url": "https://example.com/b",
                "language": "English",
                "sourcecountry": "United States",
                "gdelt_query": "rotation",
            },
            {
                "timestamp": pd.Timestamp("2023-11-01T09:00:00Z"),
                "date": date(2023, 11, 1),
                "title": "Old short squeeze story outside the window",
                "source": "archive.example",
                "url": "https://example.com/old",
                "language": "English",
                "sourcecountry": "United States",
                "gdelt_query": "crowding",
            },
            {
                "timestamp": pd.Timestamp("2024-01-05T16:00:00Z"),
                "date": date(2024, 1, 5),
                "title": "Duplicate short squeeze headline",
                "source": "dup.example",
                "url": "https://example.com/a",
                "language": "English",
                "sourcecountry": "United States",
                "gdelt_query": "crowding",
            },
            {
                "timestamp": pd.Timestamp("2024-01-03T10:00:00Z"),
                "date": date(2024, 1, 3),
                "title": "Unrelated sports championship parade",
                "source": "sports.example",
                "url": "https://example.com/sports",
                "language": "English",
                "sourcecountry": "United States",
                "gdelt_query": "panic",
            },
        ]
    )


def test_point_in_time_date_filtering() -> None:
    evidence = retrieve_gdelt_evidence(
        _sample_gdelt(),
        as_of_date=date(2024, 1, 5),
        active_triggers=["short_loss_in_recovery"],
        lookback_days=30,
        max_records=15,
        clamp_max_records=False,
    )
    assert not evidence.empty
    assert all(date.fromisoformat(value) <= date(2024, 1, 5) for value in evidence["date"])
    assert all(date.fromisoformat(value) > date(2023, 12, 6) for value in evidence["date"])
    assert "https://example.com/old" not in set(evidence["url"])


def test_trigger_keyword_matching() -> None:
    evidence = retrieve_gdelt_evidence(
        _sample_gdelt(),
        as_of_date="2024-01-05",
        active_triggers=["short_loss_in_recovery", "short_minus_long_beta_gap"],
        lookback_days=30,
        max_records=15,
        clamp_max_records=False,
    )
    titles = set(evidence["title"])
    assert any("short squeeze" in title.lower() for title in titles)
    assert any("high beta" in title.lower() for title in titles)
    assert "Unrelated sports championship parade" not in titles
    assert set(evidence["matched_trigger"]).issubset(TRIGGER_KEYWORDS)


def test_title_deduplication_across_urls() -> None:
    frame = _sample_gdelt()
    frame = pd.concat(
        [
            frame,
            pd.DataFrame(
                [
                    {
                        "timestamp": pd.Timestamp("2024-01-04T11:00:00Z"),
                        "date": date(2024, 1, 4),
                        "title": "Credit a short squeeze for the stock market bounce",
                        "source": "mirror.example",
                        "url": "https://example.com/a-mirror",
                        "language": "English",
                        "sourcecountry": "United States",
                        "gdelt_query": "crowding",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    evidence = retrieve_gdelt_evidence(
        frame,
        as_of_date=date(2024, 1, 5),
        active_triggers=["short_loss_in_recovery"],
        lookback_days=30,
        max_records=15,
        clamp_max_records=False,
    )
    titles = [title.lower().strip() for title in evidence["title"]]
    assert titles.count("credit a short squeeze for the stock market bounce") == 1


def test_maximum_record_count() -> None:
    many = pd.concat([_sample_gdelt()] * 8, ignore_index=True)
    many["url"] = [f"https://example.com/{index}" for index in range(len(many))]
    many["title"] = [
        f"Short squeeze and heavily shorted names bounce {index}" for index in range(len(many))
    ]
    evidence = retrieve_gdelt_evidence(
        many,
        as_of_date=date(2024, 1, 5),
        active_triggers=["short_loss_in_recovery"],
        lookback_days=30,
        max_records=5,
        clamp_max_records=False,
    )
    assert len(evidence) == 5
    assert list(evidence["evidence_id"]) == ["E1", "E2", "E3", "E4", "E5"]
    assert resolve_max_records(5) == MAX_RECORDS_RANGE[0]
    assert resolve_max_records(80) == MAX_RECORDS_RANGE[1]
    assert resolve_max_records(None) == DEFAULT_MAX_RECORDS


def test_partial_trigger_activates_layer() -> None:
    signals = [
        {
            "name": "short_loss_in_recovery",
            "status": "not_triggered",
            "current_value": 0.21,
            "threshold": 0.30,
            "direction": "greater_than_or_equal",
        },
        {
            "name": "portfolio_drawdown",
            "status": "not_triggered",
            "current_value": -0.01,
            "threshold": -0.20,
            "direction": "less_than_or_equal",
        },
    ]
    active = active_triggers_from_signals(signals, include_partial=True, partial_ratio=0.70)
    assert [row["trigger"] for row in active] == ["short_loss_in_recovery"]
    assert active[0]["status"] == "partial"
    assert active_triggers_from_signals(signals, include_partial=False) == []


def test_theme_filter_restricts_gdelt_queries() -> None:
    evidence = retrieve_gdelt_evidence(
        _sample_gdelt(),
        as_of_date=date(2024, 1, 5),
        active_triggers=["short_loss_in_recovery", "short_minus_long_beta_gap"],
        lookback_days=30,
        max_records=20,
        themes=["crowding"],
        clamp_max_records=False,
    )
    assert not evidence.empty
    assert set(evidence["gdelt_query"]) == {"crowding"}
    assert all("short" in title.lower() for title in evidence["title"])


def test_no_active_trigger_behavior() -> None:
    evidence = retrieve_gdelt_evidence(
        _sample_gdelt(),
        as_of_date=date(2024, 1, 5),
        active_triggers=[],
        lookback_days=30,
        max_records=15,
        clamp_max_records=False,
    )
    assert evidence.empty
    assert no_active_trigger_message().startswith("Evidence layer not activated")

    signals = [
        {
            "name": "portfolio_drawdown",
            "status": "not_triggered",
            "current_value": -0.01,
            "threshold": -0.2,
            "direction": "less_than_or_equal",
        }
    ]
    assert active_triggers_from_signals(signals) == []
    result = explain_risk_with_deepseek(
        active_triggers=[],
        evidence=evidence,
        as_of_date=date(2024, 1, 5),
        load_dotenv=False,
        environment={},
    )
    assert result["status"] == "inactive"


def test_missing_api_key_behavior(tmp_path) -> None:
    evidence = retrieve_gdelt_evidence(
        _sample_gdelt(),
        as_of_date=date(2024, 1, 5),
        active_triggers=["short_loss_in_recovery"],
        lookback_days=30,
        max_records=15,
        clamp_max_records=False,
    )
    assert not evidence.empty
    result = explain_risk_with_deepseek(
        active_triggers=[
            {
                "trigger": "short_loss_in_recovery",
                "observed_value": 0.12,
                "threshold": 0.10,
                "status": "triggered",
            }
        ],
        evidence=evidence,
        as_of_date=date(2024, 1, 5),
        cache_dir=tmp_path,
        load_dotenv=False,
        environment={},
    )
    assert result["status"] == "llm_unavailable"
    assert "LLM synthesis was unavailable" in result["message"]
    assert result["trigger_summary"] == ""


def test_deepseek_transport_success_and_cache(tmp_path) -> None:
    evidence = retrieve_gdelt_evidence(
        _sample_gdelt(),
        as_of_date=date(2024, 1, 5),
        active_triggers=["short_loss_in_recovery"],
        lookback_days=30,
        max_records=15,
        clamp_max_records=False,
    )
    calls = {"n": 0}

    def _transport(**_kwargs: object) -> str:
        calls["n"] += 1
        return (
            '{"trigger_summary":"Short-leg losses are active.",'
            '"recent_narrative":"Coverage mentions short squeezes [E1].",'
            '"momentum_mechanism":"Forced covering can pressure short books.",'
            '"key_evidence_ids":["E1"],'
            '"limitations":"Evidence is sparse and non-causal.",'
            '"pm_takeaway":"Monitor short-leg contribution closely."}'
        )

    triggers = [
        {
            "trigger": "short_loss_in_recovery",
            "observed_value": 0.12,
            "threshold": 0.10,
            "status": "triggered",
        }
    ]
    first = explain_risk_with_deepseek(
        active_triggers=triggers,
        evidence=evidence,
        as_of_date=date(2024, 1, 5),
        cache_dir=tmp_path,
        load_dotenv=False,
        environment={"DEEPSEEK_API_KEY": "test-key", "DEEPSEEK_MODEL": "deepseek-chat"},
        transport=_transport,
    )
    second = explain_risk_with_deepseek(
        active_triggers=triggers,
        evidence=evidence,
        as_of_date=date(2024, 1, 5),
        cache_dir=tmp_path,
        load_dotenv=False,
        environment={"DEEPSEEK_API_KEY": "test-key", "DEEPSEEK_MODEL": "deepseek-chat"},
        transport=_transport,
    )
    assert first["status"] == "ok"
    assert first["cached"] is False
    assert second["cached"] is True
    assert calls["n"] == 1
    assert first["key_evidence_ids"] == ["E1"]
