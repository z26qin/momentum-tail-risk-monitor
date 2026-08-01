"""Thin crowding context readers for demo-side notes.

These overlays are presentation-only. They never modify scorecard values,
thresholds, mechanism triggers, or risk state.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.mvp.contracts import NarrativeSnapshot, PositioningSnapshot
from src.utils.io import DEFAULT_PROCESSED_DIR, iso_date


def _optional_float(value: object) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def _staleness(
    observation_date: pd.Timestamp,
    as_of_date: pd.Timestamp,
) -> int:
    if observation_date == as_of_date:
        return 0
    return max(0, len(pd.bdate_range(observation_date, as_of_date)) - 1)


def _overlay_read(
    *,
    values: tuple[float | None, ...],
    context_elevated: bool,
) -> str:
    available = [value for value in values if value is not None]
    if not available:
        return "unavailable"
    if context_elevated:
        if max(available) >= 1.0:
            return "confirm"
        if all(value <= -1.0 for value in available):
            return "contradict"
        return "neutral"
    if max(available) >= 2.0:
        return "contradict"
    return "neutral"


def build_positioning_snapshot(
    *,
    as_of_date: str,
    context_elevated: bool = False,
    processed_dir: Path | None = None,
) -> PositioningSnapshot:
    """Read the latest FINRA loser-leg positioning panel on or before as-of."""

    as_of = pd.Timestamp(as_of_date)
    root = processed_dir or DEFAULT_PROCESSED_DIR
    path = root / "positioning_panel.parquet"
    limitations = (
        "FINRA loser-leg short-interest / utilisation / short-volume z-scores "
        "are public-data proxies on a survivorship-biased membership snapshot.",
        "This overlay is context only and cannot change concentration, theme, "
        "or mechanism triggers.",
    )
    unavailable = PositioningSnapshot(
        as_of_date=as_of_date,
        observation_date=None,
        read="unavailable",
        short_interest_ratio_z=None,
        short_interest_utilisation_z=None,
        short_volume_share_z=None,
        stale_trading_days=None,
        limitations=limitations,
    )
    if not path.is_file():
        return unavailable

    frame = pd.read_parquet(
        path,
        columns=[
            "trading_date",
            "short_interest_ratio_z",
            "short_interest_utilisation_z",
            "short_vol_share_z",
        ],
    )
    frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.normalize()
    frame = frame.loc[frame["trading_date"].le(as_of)].sort_values("trading_date")
    if frame.empty:
        return unavailable

    row = frame.iloc[-1]
    observation_date = pd.Timestamp(row["trading_date"])
    values = (
        _optional_float(row["short_interest_ratio_z"]),
        _optional_float(row["short_interest_utilisation_z"]),
        _optional_float(row["short_vol_share_z"]),
    )
    return PositioningSnapshot(
        as_of_date=as_of_date,
        observation_date=iso_date(observation_date),
        read=_overlay_read(values=values, context_elevated=context_elevated),
        short_interest_ratio_z=values[0],
        short_interest_utilisation_z=values[1],
        short_volume_share_z=values[2],
        stale_trading_days=_staleness(observation_date, as_of),
        limitations=limitations,
    )


def build_narrative_snapshot(
    *,
    as_of_date: str,
    context_elevated: bool = False,
    processed_dir: Path | None = None,
) -> NarrativeSnapshot:
    """Read GDELT volume-intensity narrative z-scores on or before as-of."""

    as_of = pd.Timestamp(as_of_date)
    root = processed_dir or DEFAULT_PROCESSED_DIR
    path = root / "narrative_panel.parquet"
    limitations = (
        "Narrative crowding uses GDELT attention-share intensity, not "
        "ownership, borrow demand, or order-flow positioning.",
        "This overlay is context only and cannot change concentration, theme, "
        "or mechanism triggers.",
    )
    unavailable = NarrativeSnapshot(
        as_of_date=as_of_date,
        observation_date=None,
        read="unavailable",
        panic_volume_z=None,
        crowding_volume_z=None,
        riskoff_volume_z=None,
        stale_trading_days=None,
        available_mechanisms=(),
        limitations=limitations,
    )
    if not path.is_file():
        return unavailable

    frame = pd.read_parquet(
        path,
        columns=[
            "trading_date",
            "panic_vol_z",
            "crowding_vol_z",
            "riskoff_vol_z",
            "queries_available",
        ],
    )
    frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.normalize()
    frame = frame.loc[frame["trading_date"].le(as_of)].sort_values("trading_date")
    if frame.empty:
        return unavailable

    row = frame.iloc[-1]
    observation_date = pd.Timestamp(row["trading_date"])
    values = (
        _optional_float(row["panic_vol_z"]),
        _optional_float(row["crowding_vol_z"]),
        _optional_float(row["riskoff_vol_z"]),
    )
    mechanisms = tuple(
        item.strip()
        for item in str(row["queries_available"]).split(",")
        if item.strip()
    )
    return NarrativeSnapshot(
        as_of_date=as_of_date,
        observation_date=iso_date(observation_date),
        read=_overlay_read(values=values, context_elevated=context_elevated),
        panic_volume_z=values[0],
        crowding_volume_z=values[1],
        riskoff_volume_z=values[2],
        stale_trading_days=_staleness(observation_date, as_of),
        available_mechanisms=mechanisms,
        limitations=limitations,
    )
