"""Market-close timestamp helpers shared by active MVP components."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd


NEW_YORK = ZoneInfo("America/New_York")


def assessment_timestamp(as_of_date: pd.Timestamp) -> str:
    """Return the US-close assessment timestamp with its UTC offset."""

    value = datetime.combine(
        pd.Timestamp(as_of_date).date(),
        time(hour=16),
        tzinfo=NEW_YORK,
    )
    return value.isoformat()
