"""Read the real FINRA and GDELT panels into small MVP snapshots."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.mvp.contracts import (
    NarrativeSnapshot,
    PositioningSnapshot,
    PrimaryRiskAssessment,
)
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
    primary_elevated: bool,
) -> str:
    available = [value for value in values if value is not None]
    if not available:
        return "unavailable"
    if primary_elevated:
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
    primary: PrimaryRiskAssessment,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
) -> PositioningSnapshot:
    """Read the latest available real FINRA loser-leg overlay."""

    as_of_date = pd.Timestamp(primary.as_of_date)
    path = processed_dir / "positioning_panel.parquet"
    limitations = (
        "The proxy universe is current membership applied historically and is "
        "therefore survivorship-biased.",
        "FINRA daily short volume is off-exchange flow, not a position, and is "
        "not consolidated with exchange short-sale volume.",
        "The overlay can confirm or contradict context but cannot modify the "
        "primary tail-loss probability.",
    )
    if not path.is_file():
        return PositioningSnapshot(
            as_of_date=primary.as_of_date,
            observation_date=None,
            read="unavailable",
            short_interest_ratio_z=None,
            short_interest_utilisation_z=None,
            short_volume_share_z=None,
            stale_trading_days=None,
            limitations=limitations,
        )

    frame = pd.read_parquet(
        path,
        columns=[
            "trading_date",
            "short_interest_ratio_z",
            "short_interest_utilisation_z",
            "short_vol_share_z",
        ],
        filters=[("trading_date", "<=", as_of_date)],
    ).sort_values("trading_date")
    if frame.empty:
        return PositioningSnapshot(
            as_of_date=primary.as_of_date,
            observation_date=None,
            read="unavailable",
            short_interest_ratio_z=None,
            short_interest_utilisation_z=None,
            short_volume_share_z=None,
            stale_trading_days=None,
            limitations=limitations,
        )
    row = frame.iloc[-1]
    observation_date = pd.Timestamp(row["trading_date"])
    values = (
        _optional_float(row["short_interest_ratio_z"]),
        _optional_float(row["short_interest_utilisation_z"]),
        _optional_float(row["short_vol_share_z"]),
    )
    return PositioningSnapshot(
        as_of_date=primary.as_of_date,
        observation_date=iso_date(observation_date),
        read=_overlay_read(
            values=values,
            primary_elevated=primary.elevated,
        ),
        short_interest_ratio_z=values[0],
        short_interest_utilisation_z=values[1],
        short_volume_share_z=values[2],
        stale_trading_days=_staleness(observation_date, as_of_date),
        limitations=limitations,
    )


def build_narrative_snapshot(
    *,
    primary: PrimaryRiskAssessment,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
) -> NarrativeSnapshot:
    """Read the three available volume-only GDELT mechanisms."""

    as_of_date = pd.Timestamp(primary.as_of_date)
    path = processed_dir / "narrative_panel.parquet"
    limitations = (
        "The current panel contains volume intensity for panic, crowding, and "
        "risk-off only; tone and five-mechanism breadth are unavailable.",
        "The estimand is attention share in GDELT-monitored English-language "
        "global news, not US financial-news sentiment or article counts.",
        "The overlay can confirm or contradict context but cannot modify the "
        "primary tail-loss probability.",
    )
    if not path.is_file():
        return NarrativeSnapshot(
            as_of_date=primary.as_of_date,
            observation_date=None,
            read="unavailable",
            panic_volume_z=None,
            crowding_volume_z=None,
            riskoff_volume_z=None,
            stale_trading_days=None,
            available_mechanisms=(),
            limitations=limitations,
        )

    frame = pd.read_parquet(
        path,
        columns=[
            "trading_date",
            "panic_vol_z",
            "crowding_vol_z",
            "riskoff_vol_z",
            "queries_available",
        ],
        filters=[("trading_date", "<=", as_of_date)],
    ).sort_values("trading_date")
    if frame.empty:
        return NarrativeSnapshot(
            as_of_date=primary.as_of_date,
            observation_date=None,
            read="unavailable",
            panic_volume_z=None,
            crowding_volume_z=None,
            riskoff_volume_z=None,
            stale_trading_days=None,
            available_mechanisms=(),
            limitations=limitations,
        )
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
        as_of_date=primary.as_of_date,
        observation_date=iso_date(observation_date),
        read=_overlay_read(
            values=values,
            primary_elevated=primary.elevated,
        ),
        panic_volume_z=values[0],
        crowding_volume_z=values[1],
        riskoff_volume_z=values[2],
        stale_trading_days=_staleness(observation_date, as_of_date),
        available_mechanisms=mechanisms,
        limitations=limitations,
    )
