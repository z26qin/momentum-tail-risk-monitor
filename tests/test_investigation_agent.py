"""Focused tests for the hand-written investigation agent loop."""

from __future__ import annotations

from src.agent import (
    FOLLOWUP_SEARCH,
    SEARCH_DM_RECOVERY,
    SEARCH_KL_CROWDING,
    run_investigation_agent,
)
from src.agent_prompts import MECHANISM_QUERIES, published_by_cutoff


def _quiet_risk(**overrides):
    payload = {
        "as_of_date": "2024-01-05",
        "data_cutoff": "2024-01-05T16:00:00-05:00",
        "overall_risk_state": "bear_low_volatility",
        "deterministic_trigger_count": 0,
        "triggered_channels": [],
        "structural_flags": [],
        "supported_mechanisms": [],
        "mechanism_statuses": {
            "bear_market_recovery_crash": "not_confirmed",
            "short_book_reversal_crash": "not_confirmed",
            "crowded_theme_unwind": "not_confirmed",
        },
        "mechanical_unwind_state": "NORMAL",
        "primary_driver": None,
    }
    payload.update(overrides)
    return payload


def _crowding_risk(**overrides):
    return _quiet_risk(
        as_of_date="2026-05-29",
        data_cutoff="2026-05-29T16:00:00-04:00",
        overall_risk_state="normal",
        deterministic_trigger_count=1,
        triggered_channels=["portfolio_drawdown"],
        structural_flags=["crowded_theme_unwind"],
        supported_mechanisms=["crowded_theme_unwind"],
        mechanism_statuses={"crowded_theme_unwind": "triggered"},
        mechanical_unwind_state="FRAGILITY_BUILDING",
        primary_driver="crowded_unwind",
        **overrides,
    )


def _crowding_and_recovery_risk(**overrides):
    payload = _crowding_risk()
    payload.update(
        {
            "deterministic_trigger_count": 2,
            "structural_flags": ["crowded_theme_unwind", "bear_market_recovery_crash"],
            "supported_mechanisms": ["crowded_theme_unwind", "bear_market_recovery_crash"],
            "mechanism_statuses": {
                "crowded_theme_unwind": "triggered",
                "bear_market_recovery_crash": "triggered",
            },
        }
    )
    payload.update(overrides)
    return payload


def _tech_doc(**overrides):
    payload = {
        "evidence_id": "CSU-013",
        "published_at": "2026-05-04",
        "source": "Goldman Sachs Prime Book",
        "headline": "Tech stocks see largest hedge fund selloff in decade",
        "snippet": (
            "Hedge funds made their largest decade-scale technology reduction, "
            "led by long sales."
        ),
        "channel": "local",
        "query": MECHANISM_QUERIES["kl_crowding"],
    }
    payload.update(overrides)
    return payload


def _dm_doc(**overrides):
    payload = {
        "evidence_id": "DM-001",
        "published_at": "2026-05-20",
        "source": "synthetic",
        "headline": "loser stocks rebound sharply",
        "snippet": "loser stocks rebound sharply",
        "channel": "news",
        "query": MECHANISM_QUERIES["dm_recovery"],
    }
    payload.update(overrides)
    return payload


class _Recorder:
    def __init__(self, batches: list[list[dict]] | None = None, *, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.batches = list(batches or [])
        self.fail = fail

    def __call__(self, query: str, cutoff: str, **kwargs) -> list[dict]:
        self.calls.append(query)
        if self.fail:
            raise RuntimeError("retrieval backend unavailable")
        if not self.batches:
            return []
        return self.batches.pop(0)


def _tools(local, news, positioning):
    return {
        "local_evidence": local,
        "search_news": news,
        "search_positioning_evidence": positioning,
    }


def _insufficient(*, next_question: str = "Is there evidence of broad deleveraging?"):
    def classify(state, **_):
        del state
        return {
            "assessment": "insufficient",
            "supported_claims": [],
            "contradicting_claims": [],
            "missing_evidence": ["Broad forced deleveraging"],
            "next_question": next_question,
            "confidence": "low",
        }

    return classify


def _run(risk, tools, **kwargs):
    return run_investigation_agent(
        as_of_date=risk["as_of_date"],
        max_steps=4,
        verbose=False,
        risk_state=risk,
        tools=tools,
        **kwargs,
    )


def test_quiet_state_finishes_without_search() -> None:
    forbidden = _Recorder(fail=True)
    result = _run(_quiet_risk(), _tools(forbidden, forbidden, forbidden))
    assert result.stop_reason == "NO_INVESTIGATION_NEEDED"
    assert result.action_history == ()
    assert result.evidence == ()
    assert forbidden.calls == []


def test_crowding_signal_searches_then_follows_up_then_finishes() -> None:
    local = _Recorder([[_tech_doc()]])
    news = _Recorder([[]])
    positioning = _Recorder([[]])
    result = _run(_crowding_risk(), _tools(local, news, positioning))
    names = [item["name"] for item in result.action_history]
    assert names[0] == SEARCH_KL_CROWDING
    assert FOLLOWUP_SEARCH in names
    assert result.stop_reason == "EVIDENCE_INSUFFICIENT"
    assert local.calls
    assert news.calls or positioning.calls
    assert "delever" in (positioning.calls[-1] if positioning.calls else news.calls[-1]).lower()
    assert "Agent path" in result.report
    assert result.risk_state["deterministic_trigger_count"] == 1


def test_followup_preserves_mechanism() -> None:
    result = _run(
        _crowding_risk(),
        _tools(_Recorder([[_tech_doc()]]), _Recorder([[]]), _Recorder([[]])),
        classify=_insufficient(),
    )
    assert result.action_history[1]["name"] == FOLLOWUP_SEARCH
    assert result.action_history[1]["mechanism"] == "kl_crowding"
    assert result.action_history[0]["mechanism"] == "kl_crowding"


def test_unresolved_kl_follows_up_before_dm() -> None:
    result = _run(
        _crowding_and_recovery_risk(),
        _tools(
            _Recorder([[_tech_doc(headline="hedge fund technology exposure reduction")]]),
            _Recorder([[_dm_doc()]]),
            _Recorder([[]]),
        ),
        classify=_insufficient(),
    )
    names = [item["name"] for item in result.action_history]
    assert names[:3] == [SEARCH_KL_CROWDING, FOLLOWUP_SEARCH, SEARCH_DM_RECOVERY]
    assert result.action_history[1]["mechanism"] == "kl_crowding"
    assert result.action_history[2]["mechanism"] == "dm_recovery"
    assert names.index(FOLLOWUP_SEARCH) < names.index(SEARCH_DM_RECOVERY)


def test_kl_evidence_cannot_enter_dm_classifier() -> None:
    kl_headline = "hedge fund technology exposure reduction"
    dm_headline = "loser stocks rebound sharply"
    captured: list[tuple[str | None, list[str]]] = []

    def classify(state, *, mechanism=None, evidence=None, **_):
        del state
        captured.append((mechanism, [item.get("headline", "") for item in (evidence or [])]))
        return {
            "assessment": "insufficient",
            "supported_claims": [],
            "contradicting_claims": [],
            "missing_evidence": ["need more"],
            "next_question": f"Need a narrower {mechanism} check?",
            "confidence": "low",
        }

    _run(
        _crowding_and_recovery_risk(),
        _tools(
            _Recorder([[_tech_doc(headline=kl_headline, snippet=kl_headline)]]),
            _Recorder([[_dm_doc(headline=dm_headline, snippet=dm_headline)]]),
            _Recorder([[]]),
        ),
        classify=classify,
    )
    by_mechanism: dict[str | None, list[str]] = {}
    for mechanism, headlines in captured:
        by_mechanism.setdefault(mechanism, [])
        by_mechanism[mechanism].extend(headlines)

    assert kl_headline in by_mechanism["kl_crowding"]
    assert dm_headline not in by_mechanism["kl_crowding"]
    assert dm_headline in by_mechanism["dm_recovery"]
    assert kl_headline not in by_mechanism["dm_recovery"]


def test_cutoff_violation_discards_future_evidence() -> None:
    future = _tech_doc(evidence_id="FUTURE-1", published_at="2026-06-15")
    local = _Recorder([[_tech_doc(), future]])
    news = _Recorder([[future]])
    positioning = _Recorder([[]])
    result = _run(_crowding_risk(), _tools(local, news, positioning))
    ids = {item["evidence_id"] for item in result.evidence}
    assert "CSU-013" in ids
    assert "FUTURE-1" not in ids
    assert published_by_cutoff("2026-06-15", "2026-05-29T16:00:00-04:00", "2026-05-29") is False
    assert published_by_cutoff("2026-05-04", "2026-05-29T16:00:00-04:00", "2026-05-29") is True


def test_dst_safe_cutoff_handling() -> None:
    may_cutoff = "2026-05-29T16:00:00-04:00"
    jan_cutoff = "2024-01-05T16:00:00-05:00"
    assert published_by_cutoff("2026-05-29 16:00 ET", may_cutoff, "2026-05-29") is True
    assert published_by_cutoff("2026-05-29 16:01 ET", may_cutoff, "2026-05-29") is False
    assert published_by_cutoff("2024-01-05 16:00 ET", jan_cutoff, "2024-01-05") is True
    assert published_by_cutoff("2024-01-05 16:01 ET", jan_cutoff, "2024-01-05") is False


def test_tool_failure_fails_closed_without_fabricating_evidence() -> None:
    boom = _Recorder(fail=True)
    original = _crowding_risk()
    result = _run(original, _tools(boom, boom, boom))
    assert result.stop_reason == "TOOL_FAILURE"
    assert result.evidence == ()
    assert result.risk_state["deterministic_trigger_count"] == original["deterministic_trigger_count"]
    assert "No fabricated evidence" in result.report or "failed" in result.report.lower()


def test_repeated_query_is_not_executed_indefinitely() -> None:
    local = _Recorder([[_tech_doc()], [_tech_doc()], [_tech_doc()]])
    news = _Recorder([[_tech_doc()], [_tech_doc()]])
    positioning = _Recorder([[_tech_doc()]])

    def _repeat(state):
        return {
            "assessment": "insufficient",
            "supported_claims": [],
            "contradicting_claims": [],
            "missing_evidence": ["Broad forced deleveraging"],
            "next_question": MECHANISM_QUERIES["kl_crowding"],
            "confidence": "low",
        }

    result = _run(
        _crowding_risk(),
        _tools(local, news, positioning),
        classify=_repeat,
    )
    queries = [item["query"] for item in result.action_history if item.get("query")]
    assert queries.count(MECHANISM_QUERIES["kl_crowding"]) == 1
    assert len(result.action_history) == 1
    assert result.stop_reason == "EVIDENCE_INSUFFICIENT"
