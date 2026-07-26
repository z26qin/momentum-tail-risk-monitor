"""End-to-end guardrails for the streamlined MVP."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.benchmarks.b2_shadow import build_b2_shadow
from src.evidence.mvp import build_evidence_snapshot
from src.overlays.snapshots import (
    build_narrative_snapshot,
    build_positioning_snapshot,
)
from src.pipeline import run_pipeline
from src.risk.dm_engine import build_primary_assessment


def test_real_overlays_are_separate_from_primary_probability() -> None:
    primary = build_primary_assessment(
        as_of_date=pd.Timestamp("2020-03-24"),
        horizon=20,
    )
    probability = primary.tail_loss_probability
    positioning = build_positioning_snapshot(primary=primary)
    narrative = build_narrative_snapshot(primary=primary)

    assert positioning.observation_date == "2020-03-24"
    assert narrative.observation_date == "2020-03-24"
    assert narrative.read == "confirm"
    assert primary.tail_loss_probability == probability


def test_b2_is_named_shadow_and_cannot_replace_primary() -> None:
    primary = build_primary_assessment(
        as_of_date=pd.Timestamp("2009-03-06"),
        horizon=20,
    )
    shadow = build_b2_shadow(primary=primary)

    assert shadow.name == "B2_logistic"
    assert shadow.status == "available"
    assert shadow.shadow_probability != primary.tail_loss_probability
    assert primary.method == "dm_pit_conditional_frequency"


def test_evidence_is_gated_and_fixture_citations_respect_cutoff() -> None:
    quiet = build_primary_assessment(
        as_of_date=pd.Timestamp("2024-01-05"),
        horizon=20,
    )
    quiet_evidence = build_evidence_snapshot(primary=quiet)
    assert quiet.elevated is False
    assert quiet_evidence.status == "skipped_quiet_state"

    elevated = build_primary_assessment(
        as_of_date=pd.Timestamp("2009-03-06"),
        horizon=20,
    )
    evidence = build_evidence_snapshot(primary=elevated)
    cutoff = datetime.fromisoformat(elevated.as_of_timestamp)
    assert evidence.status == "available"
    assert evidence.mode == "illustrative_fixture_replay"
    assert all(
        datetime.fromisoformat(item["publication_timestamp"]) <= cutoff
        for item in evidence.citations
    )


def test_pipeline_writes_one_assessment_and_brief(tmp_path) -> None:
    assessment, assessment_path, brief_path = run_pipeline(
        as_of_date=pd.Timestamp("2020-03-24"),
        horizon=20,
        output_dir=tmp_path,
    )

    assert assessment.primary.state == "panic_elevated"
    assert assessment.positioning.as_of_date == assessment.primary.as_of_date
    assert assessment.narrative.as_of_date == assessment.primary.as_of_date
    assert assessment_path.is_file()
    assert brief_path.is_file()
    brief = brief_path.read_text(encoding="utf-8")
    assert "PIT conditional tail-loss probability" in brief
    assert "FINRA positioning overlay" in brief
    assert "GDELT narrative overlay" in brief
