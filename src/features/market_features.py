"""Construct the pre-specified point-in-time market feature table."""

from __future__ import annotations

import argparse
import bisect
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    iso_date,
    parse_as_of_date,
    write_json,
    write_parquet,
)


OUTPUT_FILENAME = "market_features.parquet"

MODEL_FEATURES = (
    "mom_return_21d",
    "mom_return_63d",
    "mom_return_126d",
    "mom_drawdown_252d",
    "mom_vol_21d",
    "mom_vol_63d",
    "vix_close",
    "mkt_return_504d",
    "bear_state",
    "mkt_variance_126d",
    "bear_x_mkt_variance_126d",
    "mkt_vol_percentile_126d",
    "mkt_return_1d",
    "mkt_return_5d",
    "mkt_return_20d",
    "stress_rebound",
    "loser_leg_return_5d",
    "loser_leg_return_20d",
    "loser_leg_vol_21d",
    "loser_minus_winner_vol_21d",
    "formation_spread",
    "mom_mkt_beta_126d",
    "mom_mkt_corr_126d",
    "beta_change_21d",
)

FEATURE_MECHANISMS = {
    "mom_return_21d": "momentum_state",
    "mom_return_63d": "momentum_state",
    "mom_return_126d": "momentum_state",
    "mom_drawdown_252d": "momentum_state",
    "mom_vol_21d": "momentum_state",
    "mom_vol_63d": "momentum_state",
    "vix_close": "panic_state",
    "mkt_return_504d": "panic_state",
    "bear_state": "panic_state",
    "mkt_variance_126d": "panic_state",
    "bear_x_mkt_variance_126d": "panic_state",
    "mkt_vol_percentile_126d": "panic_state",
    "mkt_return_1d": "rebound_trigger",
    "mkt_return_5d": "rebound_trigger",
    "mkt_return_20d": "rebound_trigger",
    "stress_rebound": "rebound_trigger",
    "loser_leg_return_5d": "leg_structure",
    "loser_leg_return_20d": "leg_structure",
    "loser_leg_vol_21d": "leg_structure",
    "loser_minus_winner_vol_21d": "leg_structure",
    "formation_spread": "leg_structure",
    "mom_mkt_beta_126d": "beta_instability",
    "mom_mkt_corr_126d": "beta_instability",
    "beta_change_21d": "beta_instability",
}


def rolling_compounded_return(
    returns: pd.Series,
    window: int,
) -> pd.Series:
    """Compound a trailing simple-return window ending at the current row."""

    if window <= 0:
        raise ValueError("window must be positive")
    if (returns.dropna() <= -1.0).any():
        raise ValueError("Cannot compound a return less than or equal to -1")
    return np.expm1(
        np.log1p(returns.astype(float))
        .rolling(window, min_periods=window)
        .sum()
    )


def rolling_drawdown(
    returns: pd.Series,
    window: int,
) -> pd.Series:
    """Current compounded wealth relative to its trailing-window peak."""

    if returns.isna().any():
        raise ValueError("Drawdown input cannot contain missing returns")
    log_wealth = np.log1p(returns.astype(float)).cumsum()
    rolling_peak = log_wealth.rolling(window, min_periods=window).max()
    return np.expm1(log_wealth - rolling_peak)


def expanding_percentile_rank(values: pd.Series) -> pd.Series:
    """Weak percentile rank of each value using only history through that row."""

    result = pd.Series(np.nan, index=values.index, dtype=float)
    sorted_history: list[float] = []
    for index, value in values.items():
        if pd.isna(value):
            continue
        numeric = float(value)
        bisect.insort_right(sorted_history, numeric)
        result.loc[index] = (
            bisect.bisect_right(sorted_history, numeric) / len(sorted_history)
        )
    return result


def _nullable_boolean(condition: pd.Series, valid: pd.Series) -> pd.Series:
    result = pd.Series(pd.NA, index=condition.index, dtype="boolean")
    result.loc[valid] = condition.loc[valid]
    return result


def build_market_features(
    *,
    momentum: pd.DataFrame,
    research_factors: pd.DataFrame,
    leg_structure: pd.DataFrame,
    vix: pd.DataFrame,
) -> pd.DataFrame:
    """Build every Task 3 feature on the UMD assessment-date calendar."""

    frame = momentum.loc[:, ["date", "umd_return"]].merge(
        research_factors.loc[:, ["date", "mkt_total_return"]],
        on="date",
        how="left",
        validate="one_to_one",
    )
    frame = frame.merge(
        leg_structure.loc[
            :,
            [
                "date",
                "winner_leg_return",
                "loser_leg_return",
                "formation_spread",
            ],
        ],
        on="date",
        how="left",
        validate="one_to_one",
    )
    frame = frame.merge(
        vix.loc[
            :,
            [
                "date",
                "vix_close",
                "vix_was_filled",
                "vix_age_trading_days",
            ],
        ],
        on="date",
        how="left",
        validate="one_to_one",
    )

    if frame["date"].duplicated().any() or not frame["date"].is_monotonic_increasing:
        raise ValueError("Feature calendar must contain sorted unique UMD dates")
    if frame["umd_return"].isna().any():
        raise ValueError("Published UMD contains missing values")
    if frame["mkt_total_return"].isna().any():
        raise ValueError("Broad US market total-return proxy is missing on UMD dates")
    if frame[["winner_leg_return", "loser_leg_return"]].isna().any().any():
        raise ValueError("Winner/loser leg returns are missing on UMD dates")
    if frame["vix_was_filled"].fillna(False).any():
        raise ValueError("Primary feature pipeline cannot use filled VIX values")

    for window in (21, 63, 126):
        frame[f"mom_return_{window}d"] = rolling_compounded_return(
            frame["umd_return"], window
        )
    frame["mom_drawdown_252d"] = rolling_drawdown(frame["umd_return"], 252)
    frame["mom_vol_21d"] = frame["umd_return"].rolling(
        21, min_periods=21
    ).std(ddof=1)
    frame["mom_vol_63d"] = frame["umd_return"].rolling(
        63, min_periods=63
    ).std(ddof=1)

    frame["mkt_return_504d"] = rolling_compounded_return(
        frame["mkt_total_return"], 504
    )
    bear_valid = frame["mkt_return_504d"].notna()
    frame["bear_state"] = _nullable_boolean(
        frame["mkt_return_504d"] < 0.0,
        bear_valid,
    )
    frame["mkt_variance_126d"] = frame["mkt_total_return"].rolling(
        126, min_periods=126
    ).var(ddof=1)
    frame["bear_x_mkt_variance_126d"] = (
        frame["bear_state"].astype("Float64") * frame["mkt_variance_126d"]
    )
    mkt_vol_126d = np.sqrt(frame["mkt_variance_126d"])
    frame["mkt_vol_percentile_126d"] = expanding_percentile_rank(mkt_vol_126d)

    frame["mkt_return_1d"] = frame["mkt_total_return"]
    frame["mkt_return_5d"] = rolling_compounded_return(
        frame["mkt_total_return"], 5
    )
    frame["mkt_return_20d"] = rolling_compounded_return(
        frame["mkt_total_return"], 20
    )
    frame["stress_rebound"] = (
        frame["bear_state"].astype("Float64")
        * frame["mkt_vol_percentile_126d"]
        * frame["mkt_return_5d"].clip(lower=0.0)
    )

    frame["loser_leg_return_5d"] = rolling_compounded_return(
        frame["loser_leg_return"], 5
    )
    frame["loser_leg_return_20d"] = rolling_compounded_return(
        frame["loser_leg_return"], 20
    )
    frame["loser_leg_vol_21d"] = frame["loser_leg_return"].rolling(
        21, min_periods=21
    ).std(ddof=1)
    winner_leg_vol_21d = frame["winner_leg_return"].rolling(
        21, min_periods=21
    ).std(ddof=1)
    frame["loser_minus_winner_vol_21d"] = (
        frame["loser_leg_vol_21d"] - winner_leg_vol_21d
    )

    rolling_covariance = frame["umd_return"].rolling(
        126, min_periods=126
    ).cov(frame["mkt_total_return"], ddof=1)
    nonzero_market_variance = frame["mkt_variance_126d"].mask(
        frame["mkt_variance_126d"].eq(0.0)
    )
    frame["mom_mkt_beta_126d"] = rolling_covariance / nonzero_market_variance
    frame["mom_mkt_corr_126d"] = frame["umd_return"].rolling(
        126, min_periods=126
    ).corr(frame["mkt_total_return"])
    frame["beta_change_21d"] = (
        frame["mom_mkt_beta_126d"] - frame["mom_mkt_beta_126d"].shift(21)
    )

    output_columns = [
        "date",
        *MODEL_FEATURES,
        "vix_was_filled",
        "vix_age_trading_days",
    ]
    return frame.loc[:, output_columns]


def feature_audit(
    features: pd.DataFrame,
    *,
    as_of_date: pd.Timestamp,
) -> dict[str, Any]:
    """Summarize first availability, missingness, and numerical ranges."""

    complete = features.loc[:, MODEL_FEATURES].notna().all(axis=1)
    if not complete.any():
        raise ValueError("No row has every mandatory market feature")
    model_sample_start = features.loc[complete, "date"].iloc[0]
    model_rows = features["date"] >= model_sample_start

    by_feature: dict[str, Any] = {}
    for feature in MODEL_FEATURES:
        observed = features.loc[features[feature].notna(), ["date", feature]]
        numeric = pd.to_numeric(observed[feature], errors="raise")
        by_feature[feature] = {
            "mechanism": FEATURE_MECHANISMS[feature],
            "first_usable_date": iso_date(observed["date"].iloc[0]),
            "last_usable_date": iso_date(observed["date"].iloc[-1]),
            "missing_full_history": int(features[feature].isna().sum()),
            "missing_on_or_after_model_start": int(
                features.loc[model_rows, feature].isna().sum()
            ),
            "minimum": float(numeric.min()),
            "maximum": float(numeric.max()),
        }

    percentile = features["mkt_vol_percentile_126d"].dropna()
    if not percentile.between(0.0, 1.0, inclusive="both").all():
        raise AssertionError("Market-volatility percentile left [0, 1]")
    correlation = features["mom_mkt_corr_126d"].dropna()
    if not correlation.between(-1.0, 1.0, inclusive="both").all():
        raise AssertionError("Rolling correlation left [-1, 1]")
    if features["mom_drawdown_252d"].dropna().gt(1e-14).any():
        raise AssertionError("Rolling drawdown must be non-positive")

    return {
        "as_of_date": iso_date(as_of_date),
        "rows": int(len(features)),
        "first_date": iso_date(features["date"].iloc[0]),
        "last_date": iso_date(features["date"].iloc[-1]),
        "mandatory_feature_count": len(MODEL_FEATURES),
        "model_sample_start": iso_date(model_sample_start),
        "complete_rows": int(complete.sum()),
        "rows_on_or_after_model_start": int(model_rows.sum()),
        "all_features_complete_on_or_after_model_start": int(
            features.loc[model_rows, MODEL_FEATURES].notna().all(axis=1).sum()
        ),
        "vix_unexpected_missing_dates_on_or_after_model_start": [
            iso_date(value)
            for value in features.loc[
                model_rows & features["vix_close"].isna(), "date"
            ]
        ],
        "features": by_feature,
    }


def run_market_feature_pipeline(
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    """Build, serialize, re-read, and audit the Task 3 feature table."""

    momentum = pd.read_parquet(
        processed_dir / "french_momentum_factor_daily.parquet"
    )
    research = pd.read_parquet(
        processed_dir / "french_research_factors_daily.parquet"
    )
    legs = pd.read_parquet(processed_dir / "momentum_leg_structure.parquet")
    vix = pd.read_parquet(processed_dir / "vix_aligned.parquet")

    inputs = (momentum, research, legs, vix)
    for frame in inputs:
        frame.drop(frame.loc[frame["date"] > as_of_date].index, inplace=True)

    features = build_market_features(
        momentum=momentum,
        research_factors=research,
        leg_structure=legs,
        vix=vix,
    )
    output_path = processed_dir / OUTPUT_FILENAME
    write_parquet(features, output_path)
    reloaded = pd.read_parquet(output_path)
    if len(reloaded) != len(features) or list(reloaded.columns) != list(
        features.columns
    ):
        raise AssertionError("Market-feature Parquet round-trip failed")

    audit = feature_audit(reloaded, as_of_date=as_of_date)
    audit["processed_path"] = str(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "task3_feature_audit.json", audit)
    print(json.dumps(audit, indent=2, sort_keys=True))
    return audit


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    run_market_feature_pipeline(
        as_of_date=parse_as_of_date(args.as_of_date),
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()

