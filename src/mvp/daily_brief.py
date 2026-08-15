"""Post-close daily brief: [SILENT] or the existing WhatsApp alert.

Delivery wrapper only. Same monitor, same discrete compare. Numeric drift
inside a severity band stays silent. Stale panels are not treated as quiet.
"""

from __future__ import annotations

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
# Weekend / one-holiday slack only. Not a holiday calendar.
MAX_CLOSE_GAP_DAYS = 4


class StaleSessionError(ValueError):
    """Processed data are too old to stand in for the last US close."""

    def __init__(self, close_date: str, available_date: str) -> None:
        self.close_date = close_date
        self.available_date = available_date
        super().__init__(
            f"Data through {available_date}, not the {close_date} close. "
            "Not a daily brief."
        )


def last_completed_us_close(now: datetime | None = None) -> str:
    """Return ``YYYY-MM-DD`` of the last completed 16:00 ET close."""

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
            f"required cached data is unavailable: {path}"
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
    """Choose the assessment date for a live or demo brief.

    ``--as-of-date`` and ``--demo`` are explicit and skip the freshness check.
    Live mode requires data within ``MAX_CLOSE_GAP_DAYS`` of the last close.
    """

    if as_of_date:
        return as_of_date
    if demo:
        return HISTORICAL_EXAMPLE_DATE
    close = last_completed_us_close(now)
    available = last_available_session(processed_dir, close)
    gap = (pd.Timestamp(close) - pd.Timestamp(available)).days
    if gap > MAX_CLOSE_GAP_DAYS:
        raise StaleSessionError(close, available)
    return available


def render_daily_brief(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> str:
    """Return ``[SILENT]`` or the two-message WhatsApp alert."""

    comparison = compare_assessments(current, previous)
    if comparison.get("silent"):
        return SILENT_BRIEF
    return format_whatsapp_alert(current, comparison)


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
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Run the existing monitor and return ``(stdout, assessment, comparison)``."""

    resolved = resolve_brief_as_of_date(
        as_of_date=as_of_date,
        demo=demo,
        now=now,
        processed_dir=processed_dir,
    )
    assessment = run_compact_assessment(
        as_of_date=resolved,
        compare_to_date=default_compare_to_date(resolved),
        processed_dir=processed_dir,
    )
    previous = load_previous_assessment(previous_path)
    text = render_daily_brief(assessment, previous)
    comparison = compare_assessments(assessment, previous)
    save_assessment(assessment_path, assessment)
    save_assessment(comparison_path, comparison)
    if update_previous:
        save_assessment(previous_path, assessment)
    return text, assessment, comparison
