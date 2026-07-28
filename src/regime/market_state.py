"""Deterministic, point-in-time macro and market-state monitor.

The module extends the existing Daniel--Moskowitz-inspired bear/variance state
with explicit drawdown, recovery, realized-volatility, crash, and rate-policy
dimensions.  Rules are deliberately simple and every threshold is labeled by
provenance.  The resulting table is descriptive research output, not a
probability forecast or trading instruction.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.features.market_features import rolling_compounded_return
from src.risk.dm_engine import build_state_history
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    atomic_write_bytes,
    iso_date,
    parse_as_of_date,
)


SEVERE_DRAWDOWN_THRESHOLD = -0.20
RECENT_DRAWDOWN_WINDOW = 126
RECOVERY_FROM_TROUGH_THRESHOLD = 0.05
EARLY_RECOVERY_MAX_AGE = 63

REALIZED_VOLATILITY_WINDOW = 21
REALIZED_VOLATILITY_ANNUALIZATION = 252
HIGH_VOLATILITY_QUANTILE = 0.80
VOLATILITY_MIN_HISTORY = 252

DM_RETURN_WINDOW = 504
DM_VARIANCE_WINDOW = 126

RATE_LEVEL_WINDOW = 21
RATE_CHANGE_WINDOW = 63
RATE_CHANGE_THRESHOLD = 0.0025

SOURCE_COLUMNS = ("date", "mkt_total_return", "rf")
OUTPUT_COLUMNS = (
    "as_of_date",
    "metric",
    "value",
    "threshold",
    "threshold_provenance",
    "state",
    "triggered",
    "explanation",
    "source_module",
)


def _validate_source(frame: pd.DataFrame) -> pd.DataFrame:
    missing = set(SOURCE_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"research factors missing columns: {sorted(missing)}")
    result = frame.loc[:, SOURCE_COLUMNS].sort_values("date").copy()
    if result.empty:
        raise ValueError("research factors are empty")
    if result["date"].duplicated().any():
        raise ValueError("research factors contain duplicate dates")
    if result[list(SOURCE_COLUMNS)].isna().any().any():
        raise ValueError("research factors contain missing required values")
    for column in ("mkt_total_return", "rf"):
        result[column] = pd.to_numeric(result[column], errors="raise")
        if not np.isfinite(result[column]).all():
            raise ValueError(f"{column} contains non-finite values")
        if result[column].le(-1.0).any():
            raise ValueError(f"{column} contains a return <= -1")
    return result.reset_index(drop=True)


def _nullable_boolean(condition: pd.Series, valid: pd.Series) -> pd.Series:
    result = pd.Series(pd.NA, index=condition.index, dtype="boolean")
    result.loc[valid] = condition.loc[valid].astype(bool)
    return result


def _rolling_trough_age(wealth: pd.Series, window: int) -> pd.Series:
    """Trading observations since the minimum wealth inside each window."""

    return wealth.rolling(window, min_periods=window).apply(
        lambda values: len(values) - 1 - int(np.argmin(values)),
        raw=True,
    )


def _annualized_compounded_rate(rate: pd.Series, window: int) -> pd.Series:
    log_return = np.log1p(rate.astype(float))
    window_return = log_return.rolling(window, min_periods=window).sum()
    return np.expm1(
        window_return * (REALIZED_VOLATILITY_ANNUALIZATION / window)
    )


def build_regime_history(research_factors: pd.DataFrame) -> pd.DataFrame:
    """Build a daily history using only data at or before each row."""

    frame = _validate_source(research_factors)
    market_return = frame["mkt_total_return"]
    market_wealth = np.exp(np.log1p(market_return).cumsum())
    market_peak = market_wealth.cummax()
    recent_trough = market_wealth.rolling(
        RECENT_DRAWDOWN_WINDOW,
        min_periods=RECENT_DRAWDOWN_WINDOW,
    ).min()

    frame["market_wealth"] = market_wealth
    frame["market_drawdown"] = market_wealth / market_peak - 1.0
    frame["recent_min_drawdown_126d"] = frame["market_drawdown"].rolling(
        RECENT_DRAWDOWN_WINDOW,
        min_periods=RECENT_DRAWDOWN_WINDOW,
    ).min()
    frame["recovery_from_trough_126d"] = market_wealth / recent_trough - 1.0
    frame["trough_age_trading_days"] = _rolling_trough_age(
        market_wealth,
        RECENT_DRAWDOWN_WINDOW,
    )

    realized_volatility = market_return.rolling(
        REALIZED_VOLATILITY_WINDOW,
        min_periods=REALIZED_VOLATILITY_WINDOW,
    ).std(ddof=1) * np.sqrt(REALIZED_VOLATILITY_ANNUALIZATION)
    volatility_threshold = realized_volatility.shift(1).expanding(
        min_periods=VOLATILITY_MIN_HISTORY
    ).quantile(HIGH_VOLATILITY_QUANTILE, interpolation="linear")
    frame["realized_volatility_21d"] = realized_volatility
    frame["realized_volatility_threshold_80pct"] = volatility_threshold
    volatility_valid = realized_volatility.notna() & volatility_threshold.notna()
    frame["high_volatility"] = _nullable_boolean(
        realized_volatility.ge(volatility_threshold),
        volatility_valid,
    )

    frame["mkt_return_504d"] = rolling_compounded_return(
        market_return,
        DM_RETURN_WINDOW,
    )
    bear_valid = frame["mkt_return_504d"].notna()
    frame["bear_state"] = _nullable_boolean(
        frame["mkt_return_504d"].lt(0.0),
        bear_valid,
    )
    frame["mkt_variance_126d"] = market_return.rolling(
        DM_VARIANCE_WINDOW,
        min_periods=DM_VARIANCE_WINDOW,
    ).var(ddof=1)
    dm_history = build_state_history(
        frame.loc[
            :,
            [
                "date",
                "mkt_return_504d",
                "bear_state",
                "mkt_variance_126d",
            ],
        ]
    )
    frame["panic_intensity"] = dm_history["panic_intensity"]
    frame["dm_state"] = dm_history["primary_state"]

    recent_drawdown_valid = frame["recent_min_drawdown_126d"].notna()
    recent_severe_drawdown = _nullable_boolean(
        frame["recent_min_drawdown_126d"].le(SEVERE_DRAWDOWN_THRESHOLD),
        recent_drawdown_valid,
    )
    frame["recent_severe_drawdown"] = recent_severe_drawdown

    crash_valid = frame["market_drawdown"].notna() & frame[
        "high_volatility"
    ].notna()
    frame["crash_state"] = _nullable_boolean(
        frame["market_drawdown"].le(SEVERE_DRAWDOWN_THRESHOLD)
        & frame["high_volatility"].fillna(False),
        crash_valid,
    )

    recovery_valid = (
        recent_severe_drawdown.notna()
        & frame["recovery_from_trough_126d"].notna()
        & frame["trough_age_trading_days"].notna()
    )
    early_recovery_condition = (
        recent_severe_drawdown.fillna(False)
        & frame["recovery_from_trough_126d"].ge(
            RECOVERY_FROM_TROUGH_THRESHOLD
        )
        & frame["trough_age_trading_days"].between(
            1,
            EARLY_RECOVERY_MAX_AGE,
            inclusive="both",
        )
    )
    frame["early_recovery_state"] = _nullable_boolean(
        early_recovery_condition,
        recovery_valid,
    )

    high_volatility_recovery_valid = (
        frame["early_recovery_state"].notna()
        & frame["high_volatility"].notna()
    )
    frame["high_volatility_recovery_state"] = _nullable_boolean(
        frame["early_recovery_state"].fillna(False)
        & frame["high_volatility"].fillna(False),
        high_volatility_recovery_valid,
    )

    frame["annualized_rf_21d"] = _annualized_compounded_rate(
        frame["rf"],
        RATE_LEVEL_WINDOW,
    )
    frame["annualized_rf_change_63d"] = (
        frame["annualized_rf_21d"]
        - frame["annualized_rf_21d"].shift(RATE_CHANGE_WINDOW)
    )
    rate_change = frame["annualized_rf_change_63d"]
    rate_regime = pd.Series(pd.NA, index=frame.index, dtype="string")
    rate_regime.loc[rate_change.notna() & rate_change.ge(
        RATE_CHANGE_THRESHOLD
    )] = "tightening"
    rate_regime.loc[rate_change.notna() & rate_change.le(
        -RATE_CHANGE_THRESHOLD
    )] = "easing"
    rate_regime.loc[
        rate_change.notna()
        & rate_change.abs().lt(RATE_CHANGE_THRESHOLD)
    ] = "stable"
    frame["rate_regime"] = rate_regime
    return frame


def _required_value(row: pd.Series, column: str) -> float:
    value = row[column]
    if pd.isna(value):
        raise ValueError(f"{column} is unavailable on the selected date")
    return float(value)


def _required_bool(row: pd.Series, column: str) -> bool:
    value = row[column]
    if pd.isna(value):
        raise ValueError(f"{column} is unavailable on the selected date")
    return bool(value)


def build_regime_table(
    research_factors: pd.DataFrame,
    *,
    as_of_date: pd.Timestamp,
) -> pd.DataFrame:
    """Return the row-oriented regime scorecard for one assessment date."""

    as_of_date = pd.Timestamp(as_of_date).normalize()
    source = research_factors.loc[
        pd.to_datetime(research_factors["date"]).le(as_of_date)
    ].copy()
    history = build_regime_history(source)
    selected = history.loc[history["date"].eq(as_of_date)]
    if len(selected) != 1:
        raise ValueError(
            f"research factors must contain one row on {iso_date(as_of_date)}"
        )
    row = selected.iloc[0]

    drawdown = _required_value(row, "market_drawdown")
    recovery = _required_value(row, "recovery_from_trough_126d")
    trough_age = int(_required_value(row, "trough_age_trading_days"))
    trough_age_label = "day" if trough_age == 1 else "days"
    realized_volatility = _required_value(row, "realized_volatility_21d")
    volatility_threshold = _required_value(
        row,
        "realized_volatility_threshold_80pct",
    )
    high_volatility = _required_bool(row, "high_volatility")
    bear_state = _required_bool(row, "bear_state")
    panic_intensity = (
        np.nan
        if pd.isna(row["panic_intensity"])
        else float(row["panic_intensity"])
    )
    crash_state = _required_bool(row, "crash_state")
    early_recovery = _required_bool(row, "early_recovery_state")
    high_volatility_recovery = _required_bool(
        row,
        "high_volatility_recovery_state",
    )
    rate_change = _required_value(row, "annualized_rf_change_63d")
    rate_regime = str(row["rate_regime"])
    date_value = iso_date(as_of_date)

    rows: list[dict[str, Any]] = [
        {
            "as_of_date": date_value,
            "metric": "market_drawdown",
            "value": drawdown,
            "threshold": SEVERE_DRAWDOWN_THRESHOLD,
            "threshold_provenance": "demo_threshold",
            "state": "severe_drawdown" if drawdown <= SEVERE_DRAWDOWN_THRESHOLD else "normal",
            "triggered": drawdown <= SEVERE_DRAWDOWN_THRESHOLD,
            "explanation": (
                "Broad-market total-return wealth relative to its prior "
                "all-history peak; -20% is an explicit MVP threshold."
            ),
            "source_module": "src.regime.market_state",
        },
        {
            "as_of_date": date_value,
            "metric": "recovery_from_trough",
            "value": recovery,
            "threshold": RECOVERY_FROM_TROUGH_THRESHOLD,
            "threshold_provenance": "demo_threshold",
            "state": (
                "recovery_threshold_met"
                if recovery >= RECOVERY_FROM_TROUGH_THRESHOLD
                else "below_recovery_threshold"
            ),
            "triggered": recovery >= RECOVERY_FROM_TROUGH_THRESHOLD,
            "explanation": (
                "Gain from the lowest broad-market wealth in the prior 126 "
                f"trading days; current trough age is {trough_age} "
                f"{trough_age_label}."
            ),
            "source_module": "src.regime.market_state",
        },
        {
            "as_of_date": date_value,
            "metric": "realized_volatility",
            "value": realized_volatility,
            "threshold": volatility_threshold,
            "threshold_provenance": "pit_historical_80pct_quantile",
            "state": "high_volatility" if high_volatility else "normal_volatility",
            "triggered": high_volatility,
            "explanation": (
                "Annualized 21-day broad-market realized volatility compared "
                "with the 80th percentile of prior observations only."
            ),
            "source_module": "src.regime.market_state",
        },
        {
            "as_of_date": date_value,
            "metric": "dm_bear_state",
            "value": _required_value(row, "mkt_return_504d"),
            "threshold": 0.0,
            "threshold_provenance": "daniel_moskowitz_structure",
            "state": "bear" if bear_state else "normal",
            "triggered": bear_state,
            "explanation": (
                "The trailing 504-trading-day broad-market return is negative."
            ),
            "source_module": "src.risk.dm_engine",
        },
        {
            "as_of_date": date_value,
            "metric": "dm_panic_state",
            "value": panic_intensity,
            "threshold": 1.0,
            "threshold_provenance": "documented_operationalization",
            "state": str(row["dm_state"]),
            "triggered": str(row["dm_state"]) == "panic_elevated",
            "explanation": (
                "DM bear state with 126-day variance at least its expanding "
                "point-in-time mean among bear-state observations."
            ),
            "source_module": "src.risk.dm_engine",
        },
        {
            "as_of_date": date_value,
            "metric": "crash_state",
            "value": float(crash_state),
            "threshold": 1.0,
            "threshold_provenance": "composite_demo_rule",
            "state": "crash" if crash_state else "not_crash",
            "triggered": crash_state,
            "explanation": (
                "Triggered when current drawdown is at most -20% and realized "
                "volatility is above its PIT historical threshold."
            ),
            "source_module": "src.regime.market_state",
        },
        {
            "as_of_date": date_value,
            "metric": "early_recovery_state",
            "value": float(early_recovery),
            "threshold": 1.0,
            "threshold_provenance": "composite_demo_rule",
            "state": "early_recovery" if early_recovery else "not_early_recovery",
            "triggered": early_recovery,
            "explanation": (
                "Requires a -20% recent drawdown, at least a 5% recovery from "
                "the 126-day trough, and a trough age of 1 to 63 trading days."
            ),
            "source_module": "src.regime.market_state",
        },
        {
            "as_of_date": date_value,
            "metric": "high_volatility_recovery_state",
            "value": float(high_volatility_recovery),
            "threshold": 1.0,
            "threshold_provenance": "composite_demo_rule",
            "state": (
                "high_volatility_recovery"
                if high_volatility_recovery
                else "not_high_volatility_recovery"
            ),
            "triggered": high_volatility_recovery,
            "explanation": (
                "Triggered only when early recovery and high realized "
                "volatility are both present."
            ),
            "source_module": "src.regime.market_state",
        },
        {
            "as_of_date": date_value,
            "metric": "rate_policy_proxy",
            "value": rate_change,
            "threshold": RATE_CHANGE_THRESHOLD,
            "threshold_provenance": "demo_threshold",
            "state": rate_regime,
            "triggered": rate_regime != "stable",
            "explanation": (
                "Change over 63 trading days in the annualized 21-day Ken "
                "French risk-free return; +/-25 bp maps to tightening/easing."
            ),
            "source_module": "src.regime.market_state",
        },
        {
            "as_of_date": date_value,
            "metric": "liquidity_proxy",
            "value": np.nan,
            "threshold": np.nan,
            "threshold_provenance": "unavailable",
            "state": "unavailable",
            "triggered": pd.NA,
            "explanation": (
                "No reliable, already-available macro liquidity series exists "
                "in the repository; the MVP does not manufacture a proxy."
            ),
            "source_module": "src.regime.market_state",
        },
    ]
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    result["triggered"] = result["triggered"].astype("boolean")
    return result


def run_regime_assessment(
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[pd.DataFrame, Path]:
    """Build and serialize one deterministic regime table."""

    as_of_date = pd.Timestamp(as_of_date).normalize()
    source_path = processed_dir / "french_research_factors_daily.parquet"
    research_factors = pd.read_parquet(
        source_path,
        columns=list(SOURCE_COLUMNS),
        filters=[("date", "<=", as_of_date)],
    )
    table = build_regime_table(
        research_factors,
        as_of_date=as_of_date,
    )
    path = (
        output_dir
        / "regime"
        / f"regime_state_{iso_date(as_of_date)}.csv"
    )
    atomic_write_bytes(path, table.to_csv(index=False).encode("utf-8"))
    return table, path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    table, path = run_regime_assessment(
        as_of_date=parse_as_of_date(args.as_of_date),
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(table.to_dict(orient="records"), indent=2, default=str))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
