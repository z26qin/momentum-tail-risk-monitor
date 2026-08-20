"""Crowding panel presentation and fail-closed context overlays."""

from __future__ import annotations

from pathlib import Path

from src.mvp.config import default_demo_config
from src.mvp.crowding_context import (
    build_narrative_snapshot,
    build_positioning_snapshot,
)
from src.mvp.pipeline import run_mvp
from src.mvp.presentation import build_crowding_panel_html
from src.utils.io import DEFAULT_PROCESSED_DIR


def test_crowding_panel_html_contains_proxy_spine() -> None:
    result = run_mvp(default_demo_config())
    html = build_crowding_panel_html(
        result.unwind, processed_dir=result.config.processed_dir
    )
    assert "Crowding monitor" in html
    assert "Portfolio concentration" in html
    assert "Momentum breadth" in html
    assert "Correlated-theme unwind" in html
    assert "No aggregate crowding score" in html
    assert "T1 context side notes" in html
    assert "FINRA positioning" in html
    assert "GDELT narrative crowding" in html


def test_crowding_panel_can_skip_overlays() -> None:
    result = run_mvp(default_demo_config())
    html = build_crowding_panel_html(
        result.unwind,
        processed_dir=result.config.processed_dir,
        include_context_overlays=False,
    )
    assert "T1 context side notes" not in html
    assert "Portfolio concentration" in html


def test_positioning_and_narrative_snapshots_for_demo_date() -> None:
    as_of = default_demo_config().as_of_date
    positioning = build_positioning_snapshot(
        as_of_date=as_of, processed_dir=DEFAULT_PROCESSED_DIR
    )
    narrative = build_narrative_snapshot(
        as_of_date=as_of, processed_dir=DEFAULT_PROCESSED_DIR
    )
    assert positioning.as_of_date == as_of
    assert narrative.as_of_date == as_of
    assert positioning.read in {
        "confirm",
        "contradict",
        "neutral",
        "unavailable",
    }
    assert narrative.read in {
        "confirm",
        "contradict",
        "neutral",
        "unavailable",
    }
    if (DEFAULT_PROCESSED_DIR / "positioning_panel.parquet").is_file():
        assert positioning.observation_date is not None
        assert positioning.short_interest_ratio_z is not None
    if (DEFAULT_PROCESSED_DIR / "narrative_panel.parquet").is_file():
        assert narrative.observation_date is not None
        assert narrative.crowding_volume_z is not None


def test_missing_panels_are_unavailable(tmp_path: Path) -> None:
    positioning = build_positioning_snapshot(
        as_of_date="2024-01-05", processed_dir=tmp_path
    )
    narrative = build_narrative_snapshot(
        as_of_date="2024-01-05", processed_dir=tmp_path
    )
    assert positioning.read == "unavailable"
    assert narrative.read == "unavailable"
    assert positioning.observation_date is None
    assert narrative.observation_date is None
