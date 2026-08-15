"""Post-close daily brief: run the monitor and emit [SILENT] or a WhatsApp alert.

This is a delivery wrapper, not a new model. It reuses ``run_compact_assessment``,
``compare_assessments``, and ``format_whatsapp_alert``. Numeric drift inside the
same severity band stays silent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.mvp.config import HISTORICAL_EXAMPLE_DATE
from src.mvp.hermes_monitor import (
    DEFAULT_ASSESSMENT_PATH,
    DEFAULT_COMPARISON_PATH,
    DEFAULT_PREVIOUS_PATH,
    MissingCachedDataError,
    compare_assessments,
    default_compare_to_date,
    format_whatsapp_alert,
    load_previous_assessment,
    run_compact_assessment,
    save_assessment,
)
from src.utils.io import DEFAULT_PROCESSED_DIR
from src.utils.market_time import NEW_YORK

US_CLOSE = time(16, 0)
SILENT_BRIEF = "[SILENT]"


@dataclass(frozen=True)
class DailyBriefResult:
    """Stdout text plus the compact assessment used to produce it."""

    as_of_date: str
    evidence_cutoff: str
    text: str
    silent: bool
    material_change: bool
    is_baseline: bool
    assessment: dict[str, Any]
    comparison: dict[str, Any]


def last_completed_us_close(now: datetime | None = None) -> str:
    """Return ``YYYY-MM-DD`` of the last completed 16:00 ET close.

    If ``now`` is at or after 16:00 America/New_York, use that calendar date.
    Otherwise use the previous calendar day. Naive datetimes are treated as
    New York time. There is no holiday calendar; pair this with
    ``last_available_session`` to walk to the last processed date.
    """

    if now is None:
        current = datetime.now(NEW_YORK)
    elif now.tzinfo is None:
        current = now.replace(tzinfo=NEW_YORK)
    else:
        current = now.astimezone(NEW_YORK)
    if current.time() >= US_CLOSE:
        return current.date().isoformat()
    return (current.date() - timedelta(days=1)).isoformat()


def last_available_session(processed_dir: Path, limit: str) -> str:
    """Return the last ``leg_risk_history`` date on or before ``limit``."""

    path = processed_dir / "leg_risk_history.parquet"
    if not path.is_file():
        raise MissingCachedDataError(
            "required cached data is unavailable: "
            f"{path}"
        )
    frame = pd.read_parquet(path, columns=["date"])
    dates = pd.to_datetime(frame["date"]).dt.normalize()
    available = dates.loc[dates.le(pd.Timestamp(limit).normalize())]
    if available.empty:
        raise ValueError(
            f"no processed session on or before {limit} in {path.name}"
        )
    return pd.Timestamp(available.max()).date().isoformat()


def resolve_brief_as_of_date(
    *,
    as_of_date: str | None = None,
    demo: bool = False,
    now: datetime | None = None,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
) -> str:
    """Choose the assessment date for a daily brief.

    An explicit ``as_of_date`` wins. ``demo`` pins the frozen 2026-05-29 case.
    Otherwise use the last completed US close intersected with available data.
    """

    if as_of_date:
        return as_of_date
    if demo:
        return HISTORICAL_EXAMPLE_DATE
    return last_available_session(processed_dir, last_completed_us_close(now))


def render_daily_brief(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> str:
    """Return ``[SILENT]`` or the two-message WhatsApp alert."""

    text, _comparison = compose_daily_brief(current, previous)
    return text


def compose_daily_brief(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    comparison = compare_assessments(current, previous)
    if comparison.get("silent"):
        return SILENT_BRIEF, comparison
    return format_whatsapp_alert(current, comparison), comparison


def persist_and_render(
    current: dict[str, Any],
    *,
    previous_path: Path = DEFAULT_PREVIOUS_PATH,
    assessment_path: Path = DEFAULT_ASSESSMENT_PATH,
    comparison_path: Path = DEFAULT_COMPARISON_PATH,
    update_previous: bool = True,
) -> DailyBriefResult:
    """Compare, optionally promote runtime state, and render stdout text."""

    previous = load_previous_assessment(previous_path)
    text, comparison = compose_daily_brief(current, previous)
    save_assessment(assessment_path, current)
    save_assessment(comparison_path, comparison)
    if update_previous:
        save_assessment(previous_path, current)
    return DailyBriefResult(
        as_of_date=str(current.get("as_of_date") or ""),
        evidence_cutoff=str(current.get("evidence_cutoff") or ""),
        text=text,
        silent=bool(comparison.get("silent")),
        material_change=bool(comparison.get("material_change")),
        is_baseline=bool(comparison.get("is_baseline")),
        assessment=current,
        comparison=comparison,
    )


def run_daily_brief(
    *,
    as_of_date: str | None = None,
    demo: bool = False,
    now: datetime | None = None,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    previous_path: Path = DEFAULT_PREVIOUS_PATH,
    assessment_path: Path = DEFAULT_ASSESSMENT_PATH,
    comparison_path: Path = DEFAULT_COMPARISON_PATH,
    update_previous: bool = True,
    horizon_days: int = 20,
    evidence_cutoff: str | None = None,
    compare_to_date: str | None = None,
) -> DailyBriefResult:
    """Run the existing monitor and return a silent-or-alert brief."""

    resolved = resolve_brief_as_of_date(
        as_of_date=as_of_date,
        demo=demo,
        now=now,
        processed_dir=processed_dir,
    )
    assessment = run_compact_assessment(
        as_of_date=resolved,
        compare_to_date=compare_to_date or default_compare_to_date(resolved),
        evidence_cutoff=evidence_cutoff,
        horizon_days=horizon_days,
        processed_dir=processed_dir,
    )
    return persist_and_render(
        assessment,
        previous_path=previous_path,
        assessment_path=assessment_path,
        comparison_path=comparison_path,
        update_previous=update_previous,
    )
