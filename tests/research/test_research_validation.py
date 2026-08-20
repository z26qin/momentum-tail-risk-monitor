"""Contract tests for the thin research-validation layer."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.mvp.config import MVPConfig
from src.mvp.pipeline import run_mvp
from src.research_validation import (
    EPISODES,
    Episode,
    extract_episode_row,
    prepare_ai_review_cases,
    write_ai_value_review,
    write_episode_fingerprints,
    write_pm_book_outcomes_skip,
)


@pytest.fixture(scope="module")
def demo_result():
    return run_mvp(
        MVPConfig(
            as_of_date="2024-01-05",
            compare_to_date="2023-12-01",
            use_llm=False,
        )
    )


@pytest.fixture(scope="module")
def demo_episode() -> Episode:
    for episode in EPISODES:
        if episode.episode_id == "demo_control":
            return episode
    raise AssertionError("demo_control episode missing")


def test_expected_mechanism_prior_does_not_alter_computed_fields(
    demo_result, demo_episode
):
    baseline = extract_episode_row(demo_result, demo_episode)
    flipped = replace(
        demo_episode,
        expected_mechanism="crowded_theme_unwind",
    )
    altered_prior = extract_episode_row(demo_result, flipped)

    for key in (
        "dm_state",
        "pm_triggers",
        "bear_market_recovery_crash",
        "short_book_reversal_crash",
        "crowded_theme_unwind",
        "beta_gap",
        "portfolio_drawdown",
        "short_loss",
        "pain_source",
    ):
        assert baseline[key] == altered_prior[key]
    assert baseline["fidelity"] != altered_prior["fidelity"]
    assert baseline["expected_mechanism"] != altered_prior["expected_mechanism"]


def test_extracted_values_match_pipeline_result(demo_result, demo_episode):
    row = extract_episode_row(demo_result, demo_episode)
    card = demo_result.deterministic_input
    statuses = {
        item.scenario: item.status for item in demo_result.unwind.mechanism_scenarios
    }

    assert row["assessment_date"] == card.as_of_date
    assert row["dm_state"] == card.overall_risk_state
    assert row["pm_triggers"] == len(card.triggered_quant_signals)
    assert row["bear_market_recovery_crash"] == statuses["bear_market_recovery_crash"]
    assert row["short_book_reversal_crash"] == statuses["short_book_reversal_crash"]
    assert row["crowded_theme_unwind"] == statuses["crowded_theme_unwind"]


def test_ai_arms_share_identical_deterministic_facts(tmp_path: Path):
    rows = prepare_ai_review_cases(
        output_dir=tmp_path,
        environment={},  # force not_run for LLM arm
        episode_ids=("demo_control",),
    )
    assert {row["episode_id"] for row in rows} == {"demo_control"}

    facts_path = tmp_path / "ai_inputs" / "demo_control_quant_facts.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    det = json.loads(
        (tmp_path / "ai_inputs" / "demo_control_deterministic_template.json").read_text(
            encoding="utf-8"
        )
    )
    assert det["quant_facts_fingerprint"] == facts

    llm_row = next(row for row in rows if row["arm"] == "llm")
    assert llm_row["run_status"] == "not_run"
    assert llm_row["external_llm_called"] is False
    assert llm_row["quant_fields_unchanged"] is True


def test_missing_credentials_do_not_fabricate_llm_output(tmp_path: Path):
    rows = prepare_ai_review_cases(
        output_dir=tmp_path,
        environment={},
        episode_ids=("demo_control",),
    )
    llm_rows = [row for row in rows if row["arm"] == "llm"]
    assert llm_rows
    for row in llm_rows:
        assert row["run_status"] == "not_run"
        payload_path = tmp_path / "ai_inputs" / f"{row['episode_id']}_llm_not_run.json"
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        assert payload["run_status"] == "not_run"
        assert "quant_facts" in payload
        assert "narrative_state" not in payload
        assert "pm_interpretation" not in payload


def test_fingerprint_output_ordering_is_deterministic(
    tmp_path: Path, demo_result, demo_episode
):
    # Keep episode list order stable without re-running heavy pipelines.
    episodes = (
        demo_episode,
        replace(demo_episode, episode_id="demo_control_b", display_name="Control B"),
    )
    first = [extract_episode_row(demo_result, episode) for episode in episodes]
    second = [extract_episode_row(demo_result, episode) for episode in episodes]
    assert [row["episode_id"] for row in first] == [
        episode.episode_id for episode in episodes
    ]
    assert [row["episode_id"] for row in first] == [
        row["episode_id"] for row in second
    ]

    csv_a, _ = write_episode_fingerprints(first, output_dir=tmp_path / "a")
    csv_b, _ = write_episode_fingerprints(second, output_dir=tmp_path / "b")
    assert csv_a.read_text(encoding="utf-8") == csv_b.read_text(encoding="utf-8")


def test_write_helpers_and_public_entrypoints(tmp_path: Path, demo_result, demo_episode):
    write_pm_book_outcomes_skip(output_dir=tmp_path)
    rows = [extract_episode_row(demo_result, demo_episode)]
    write_episode_fingerprints(rows, output_dir=tmp_path)
    ai_rows = prepare_ai_review_cases(
        output_dir=tmp_path,
        environment={},
        episode_ids=("demo_control",),
    )
    review = write_ai_value_review(ai_rows, output_dir=tmp_path)
    assert (tmp_path / "pm_book_outcomes.md").is_file()
    assert (tmp_path / "episode_fingerprints.csv").is_file()
    assert review.is_file()
