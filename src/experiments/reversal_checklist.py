"""Research-only momentum reversal conditions.

These thresholds preserve the interpretable precondition/trigger structure of
the earlier prototype.  They are not attributed to Daniel and Moskowitz, are
not calibrated probabilities, and cannot set the primary MVP risk state.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.mvp.contracts import ReversalConditions
from src.utils.io import DEFAULT_PROCESSED_DIR


PRIOR_MARKET_DECLINE_THRESHOLD = -0.10
HIGH_VOLATILITY_PERCENTILE_THRESHOLD = 0.80
MARKET_REBOUND_5D_THRESHOLD = 0.03
LOSER_SNAPBACK_5D_THRESHOLD = 0.03
MOMENTUM_DRAWDOWN_THRESHOLD = -0.20
BETA_CHANGE_ABSOLUTE_THRESHOLD = 0.10


def _compounded_return(values: pd.Series) -> float:
    if len(values) != 5 or values.isna().any() or values.le(-1.0).any():
        raise ValueError("five valid leg returns are required")
    return float(np.expm1(np.log1p(values.astype(float)).sum()))


def build_reversal_conditions(
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
) -> ReversalConditions:
    """Evaluate heuristic conditions without producing a risk probability."""

    as_of_date = pd.Timestamp(as_of_date).normalize()
    features = pd.read_parquet(
        processed_dir / "market_features.parquet",
        columns=[
            "date",
            "mkt_return_504d",
            "mkt_vol_percentile_126d",
            "mkt_return_5d",
            "mom_drawdown_252d",
            "beta_change_21d",
        ],
        filters=[("date", "=", as_of_date)],
    )
    if len(features) != 1:
        raise ValueError("market features must contain one selected row")
    row = features.iloc[0]

    legs = pd.read_parquet(
        processed_dir / "momentum_leg_structure.parquet",
        columns=["date", "winner_leg_return", "loser_leg_return"],
        filters=[("date", "<=", as_of_date)],
    ).sort_values("date")
    if legs.empty or pd.Timestamp(legs.iloc[-1]["date"]) != as_of_date:
        raise ValueError("momentum legs do not contain the selected date")
    winner_5d = _compounded_return(legs["winner_leg_return"].tail(5))
    loser_5d = _compounded_return(legs["loser_leg_return"].tail(5))
    loser_snapback = loser_5d - winner_5d

    flags = {
        "severe_prior_market_decline": (
            float(row["mkt_return_504d"]) <= PRIOR_MARKET_DECLINE_THRESHOLD
        ),
        "high_market_volatility": (
            float(row["mkt_vol_percentile_126d"])
            >= HIGH_VOLATILITY_PERCENTILE_THRESHOLD
        ),
        "sharp_market_rebound": (
            float(row["mkt_return_5d"]) >= MARKET_REBOUND_5D_THRESHOLD
        ),
        "loser_snapback": loser_snapback >= LOSER_SNAPBACK_5D_THRESHOLD,
        "momentum_drawdown_confirmation": (
            float(row["mom_drawdown_252d"]) <= MOMENTUM_DRAWDOWN_THRESHOLD
        ),
        "exposure_instability_confirmation": (
            abs(float(row["beta_change_21d"]))
            >= BETA_CHANGE_ABSOLUTE_THRESHOLD
        ),
    }
    panic_precondition = (
        flags["severe_prior_market_decline"]
        and flags["high_market_volatility"]
    )
    trigger_count = int(flags["sharp_market_rebound"]) + int(
        flags["loser_snapback"]
    )
    if panic_precondition and trigger_count == 2:
        status = "active_reversal"
    elif panic_precondition and trigger_count == 1:
        status = "reversal_watch"
    elif panic_precondition:
        status = "stressed_precondition"
    else:
        status = "normal"

    return ReversalConditions(
        status=status,
        triggered_conditions=tuple(
            name for name, triggered in flags.items() if triggered
        ),
        total_conditions=len(flags),
        research_only=True,
        detail=(
            "Research heuristics retained to explain reversal conditions. "
            "Thresholds are not the primary DM rule, are not calibrated, and "
            "cannot change the primary probability."
        ),
    )
