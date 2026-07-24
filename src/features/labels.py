"""Construct point-in-time momentum tail-loss labels and episode audits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

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


HORIZONS = (5, 20)
PRIMARY_QUANTILE = 0.05
SENSITIVITY_QUANTILES = (0.025, 0.10)
HISTORICAL_MIN_MATURED_OBSERVATIONS = 252
MODEL_MIN_MATURED_OBSERVATIONS = 10 * 252
EPISODE_RESET_NON_EVENT_DAYS = 5
PRIOR_STRENGTH_LOOKBACK = 63


def compounded_forward_return(
    returns: pd.Series,
    horizon: int,
) -> pd.Series:
    """Compound returns over rows ``t+1`` through ``t+horizon``."""

    if horizon <= 0:
        raise ValueError("horizon must be positive")
    if (returns.dropna() <= -1.0).any():
        raise ValueError("Cannot compound a simple return less than or equal to -1")
    log_return = np.log1p(returns.astype(float))
    forward_log_sum = (
        log_return.rolling(horizon, min_periods=horizon).sum().shift(-horizon)
    )
    return np.expm1(forward_log_sum)


def compounded_trailing_return(
    returns: pd.Series,
    lookback: int,
) -> pd.Series:
    """Compound returns over the trailing window ending at ``t``."""

    if lookback <= 0:
        raise ValueError("lookback must be positive")
    if (returns.dropna() <= -1.0).any():
        raise ValueError("Cannot compound a simple return less than or equal to -1")
    return np.expm1(
        np.log1p(returns.astype(float))
        .rolling(lookback, min_periods=lookback)
        .sum()
    )


def matured_expanding_quantile(
    forward_return: pd.Series,
    *,
    horizon: int,
    quantile: float,
    min_matured_observations: int,
) -> tuple[pd.Series, pd.Series]:
    """Estimate a PIT quantile from forward windows matured by each row.

    Shifting by ``horizon`` moves the forward return assessed at row ``s`` to
    row ``s+horizon``, the close when that label window is fully observable.
    The expanding statistic therefore never sees the most recent unmatured
    forward-return rows.
    """

    if not 0.0 < quantile < 1.0:
        raise ValueError("quantile must be strictly between zero and one")
    matured = forward_return.shift(horizon)
    threshold = matured.expanding(
        min_periods=min_matured_observations
    ).quantile(quantile, interpolation="linear")
    matured_count = matured.notna().cumsum().astype("int64")
    return threshold, matured_count


def nullable_less_than(left: pd.Series, right: pd.Series) -> pd.Series:
    """Compare two numeric series while preserving unknown rows as nullable."""

    valid = left.notna() & right.notna()
    result = pd.Series(pd.NA, index=left.index, dtype="boolean")
    result.loc[valid] = left.loc[valid] < right.loc[valid]
    return result


def decluster_events(
    event: pd.Series,
    *,
    reset_after_non_event_days: int = EPISODE_RESET_NON_EVENT_DAYS,
) -> tuple[pd.Series, pd.Series]:
    """Assign event rows to episodes separated by a documented quiet run."""

    if reset_after_non_event_days <= 0:
        raise ValueError("reset_after_non_event_days must be positive")

    episode_id = pd.Series(pd.NA, index=event.index, dtype="Int64")
    event_onset = pd.Series(pd.NA, index=event.index, dtype="boolean")
    current_episode = 0
    non_event_run = reset_after_non_event_days

    for index, value in event.items():
        if pd.isna(value):
            continue
        event_onset.loc[index] = False
        if bool(value):
            starts_new_episode = (
                current_episode == 0
                or non_event_run >= reset_after_non_event_days
            )
            if starts_new_episode:
                current_episode += 1
                event_onset.loc[index] = True
            episode_id.loc[index] = current_episode
            non_event_run = 0
        else:
            non_event_run += 1

    return episode_id, event_onset


def _conditional_event(
    primary_event: pd.Series,
    prior_state: pd.Series,
) -> pd.Series:
    valid = primary_event.notna() & prior_state.notna()
    result = pd.Series(pd.NA, index=primary_event.index, dtype="boolean")
    result.loc[valid] = (
        primary_event.loc[valid].astype(bool)
        & prior_state.loc[valid].astype(bool)
    )
    return result


def build_labels_for_horizon(
    momentum: pd.DataFrame,
    *,
    horizon: int,
    historical_min_matured_observations: int = (
        HISTORICAL_MIN_MATURED_OBSERVATIONS
    ),
) -> pd.DataFrame:
    """Build one fully auditable label-history table for a horizon."""

    required = {"date", "umd_return"}
    missing = required.difference(momentum.columns)
    if missing:
        raise ValueError(f"Momentum input missing columns: {sorted(missing)}")

    frame = momentum.loc[:, ["date", "umd_return"]].copy()
    if frame["date"].duplicated().any():
        raise ValueError("Momentum input contains duplicate dates")
    if not frame["date"].is_monotonic_increasing:
        raise ValueError("Momentum input dates must be sorted")

    forward_column = f"fwd_mom_return_{horizon}"
    primary_label_column = f"mom_tail_loss_{horizon}"
    q025_label_column = f"mom_tail_loss_025_{horizon}"
    q10_label_column = f"mom_tail_loss_10_{horizon}"
    conditioned_label_column = f"mom_tail_loss_prior_strength_{horizon}"
    primary_threshold_column = f"pit_tail_threshold_05_{horizon}"
    q025_threshold_column = f"pit_tail_threshold_025_{horizon}"
    q10_threshold_column = f"pit_tail_threshold_10_{horizon}"
    matured_count_column = f"threshold_matured_observations_{horizon}"

    frame["horizon_days"] = horizon
    frame[forward_column] = compounded_forward_return(
        frame["umd_return"], horizon
    )
    frame["label_start_date"] = frame["date"].shift(-1)
    frame["label_end_date"] = frame["date"].shift(-horizon)
    frame["label_available_date"] = frame["label_end_date"]

    primary_threshold, matured_count = matured_expanding_quantile(
        frame[forward_column],
        horizon=horizon,
        quantile=PRIMARY_QUANTILE,
        min_matured_observations=historical_min_matured_observations,
    )
    q025_threshold, q025_count = matured_expanding_quantile(
        frame[forward_column],
        horizon=horizon,
        quantile=SENSITIVITY_QUANTILES[0],
        min_matured_observations=historical_min_matured_observations,
    )
    q10_threshold, q10_count = matured_expanding_quantile(
        frame[forward_column],
        horizon=horizon,
        quantile=SENSITIVITY_QUANTILES[1],
        min_matured_observations=historical_min_matured_observations,
    )
    if not matured_count.equals(q025_count) or not matured_count.equals(q10_count):
        raise AssertionError("Matured-history counts differ across quantiles")

    frame[primary_threshold_column] = primary_threshold
    frame[q025_threshold_column] = q025_threshold
    frame[q10_threshold_column] = q10_threshold
    frame[matured_count_column] = matured_count
    frame["threshold_latest_source_assessment_date"] = frame["date"].shift(
        horizon
    )

    frame[primary_label_column] = nullable_less_than(
        frame[forward_column], frame[primary_threshold_column]
    )
    frame[q025_label_column] = nullable_less_than(
        frame[forward_column], frame[q025_threshold_column]
    )
    frame[q10_label_column] = nullable_less_than(
        frame[forward_column], frame[q10_threshold_column]
    )

    frame["trailing_umd_return_63d"] = compounded_trailing_return(
        frame["umd_return"], PRIOR_STRENGTH_LOOKBACK
    )
    frame["pit_median_trailing_umd_return_63d"] = (
        frame["trailing_umd_return_63d"]
        .expanding(min_periods=historical_min_matured_observations)
        .median()
    )
    prior_valid = (
        frame["trailing_umd_return_63d"].notna()
        & frame["pit_median_trailing_umd_return_63d"].notna()
    )
    frame["prior_strength_above_pit_median"] = pd.Series(
        pd.NA, index=frame.index, dtype="boolean"
    )
    frame.loc[
        prior_valid, "prior_strength_above_pit_median"
    ] = (
        frame.loc[prior_valid, "trailing_umd_return_63d"]
        > frame.loc[prior_valid, "pit_median_trailing_umd_return_63d"]
    )
    frame[conditioned_label_column] = _conditional_event(
        frame[primary_label_column],
        frame["prior_strength_above_pit_median"],
    )

    episode_id, event_onset = decluster_events(frame[primary_label_column])
    frame["event_episode_id"] = episode_id
    frame["event_onset"] = event_onset

    output_columns = [
        "date",
        "horizon_days",
        forward_column,
        "label_start_date",
        "label_end_date",
        "label_available_date",
        primary_threshold_column,
        q025_threshold_column,
        q10_threshold_column,
        matured_count_column,
        "threshold_latest_source_assessment_date",
        primary_label_column,
        q025_label_column,
        q10_label_column,
        "trailing_umd_return_63d",
        "pit_median_trailing_umd_return_63d",
        "prior_strength_above_pit_median",
        conditioned_label_column,
        "event_episode_id",
        "event_onset",
    ]
    return frame.loc[:, output_columns]


def validate_model_history_rule(
    labels: pd.DataFrame,
    *,
    horizon: int,
    model_sample_start: pd.Timestamp,
) -> dict[str, Any]:
    """Enforce ten years of matured labels before the earliest model date."""

    model_rows = labels.index[labels["date"] >= model_sample_start]
    if len(model_rows) == 0:
        raise ValueError("No label row reaches the model-sample start")
    first_index = model_rows[0]
    first_model_date = labels.loc[first_index, "date"]
    count_column = f"threshold_matured_observations_{horizon}"
    matured_count = int(labels.loc[first_index, count_column])
    if matured_count < MODEL_MIN_MATURED_OBSERVATIONS:
        raise ValueError(
            f"Horizon {horizon} has only {matured_count} matured observations "
            f"at model start {iso_date(first_model_date)}"
        )

    first_available = labels.loc[
        labels["label_available_date"].notna(), "label_available_date"
    ].iloc[0]
    ten_year_cutoff = first_model_date - pd.DateOffset(years=10)
    if first_available > ten_year_cutoff:
        raise ValueError(
            f"Horizon {horizon} lacks ten calendar years of matured history "
            "before model start"
        )

    latest_source_date = labels.loc[
        first_index, "threshold_latest_source_assessment_date"
    ]
    latest_source_end_date = labels.loc[
        labels["date"].eq(latest_source_date), "label_end_date"
    ].iloc[0]
    if latest_source_end_date > first_model_date:
        raise AssertionError("Threshold includes an unmatured forward window")

    return {
        "first_model_sample_date": iso_date(first_model_date),
        "matured_observations_at_model_start": matured_count,
        "earliest_label_available_date": iso_date(first_available),
        "latest_threshold_source_assessment_date": iso_date(latest_source_date),
        "latest_threshold_source_label_end_date": iso_date(
            latest_source_end_date
        ),
        "minimum_required_matured_observations": (
            MODEL_MIN_MATURED_OBSERVATIONS
        ),
    }


def _event_summary(event: pd.Series) -> dict[str, int | float]:
    episode_id, onset = decluster_events(event)
    valid_days = int(event.notna().sum())
    event_days = int(event.fillna(False).sum())
    return {
        "valid_days": valid_days,
        "event_days": event_days,
        "event_rate": event_days / valid_days if valid_days else float("nan"),
        "episodes": int(onset.fillna(False).sum()),
        "event_rows_with_episode_id": int(episode_id.notna().sum()),
    }


def _first_or_none(values: pd.Series) -> float | None:
    clean = values.dropna()
    return float(clean.iloc[0]) if not clean.empty else None


def _last_or_none(values: pd.Series) -> float | None:
    clean = values.dropna()
    return float(clean.iloc[-1]) if not clean.empty else None


def decade_audit(labels: pd.DataFrame, *, horizon: int) -> list[dict[str, Any]]:
    """Report threshold evolution and primary event counts by decade."""

    threshold_column = f"pit_tail_threshold_05_{horizon}"
    label_column = f"mom_tail_loss_{horizon}"
    working = labels.copy()
    working["decade"] = (working["date"].dt.year // 10) * 10

    rows: list[dict[str, Any]] = []
    for decade, group in working.groupby("decade", sort=True):
        rows.append(
            {
                "decade": int(decade),
                "threshold_first": _first_or_none(group[threshold_column]),
                "threshold_last": _last_or_none(group[threshold_column]),
                "threshold_median": (
                    float(group[threshold_column].median())
                    if group[threshold_column].notna().any()
                    else None
                ),
                "valid_label_days": int(group[label_column].notna().sum()),
                "event_days": int(group[label_column].fillna(False).sum()),
                "episodes_started": int(
                    group["event_onset"].fillna(False).sum()
                ),
            }
        )
    return rows


def crash_window_audit(
    labels: pd.DataFrame,
    *,
    horizon: int,
) -> list[dict[str, Any]]:
    """Summarize pre-specified historical reversal windows."""

    windows = (
        ("1932", "1932-01-01", "1932-12-31"),
        ("2009_H1", "2009-01-01", "2009-06-30"),
        ("2020_11", "2020-11-01", "2020-11-30"),
        ("2021_01", "2021-01-01", "2021-01-31"),
    )
    label_column = f"mom_tail_loss_{horizon}"
    forward_column = f"fwd_mom_return_{horizon}"

    result: list[dict[str, Any]] = []
    for name, start, end in windows:
        group = labels.loc[labels["date"].between(start, end)]
        event_rows = group.loc[group[label_column].fillna(False)]
        worst_index = (
            group[forward_column].idxmin()
            if group[forward_column].notna().any()
            else None
        )
        result.append(
            {
                "window": name,
                "start": start,
                "end": end,
                "event_days": int(event_rows.shape[0]),
                "episodes_touched": int(
                    event_rows["event_episode_id"].nunique()
                ),
                "episodes_started": int(
                    group["event_onset"].fillna(False).sum()
                ),
                "worst_forward_return": (
                    float(labels.loc[worst_index, forward_column])
                    if worst_index is not None
                    else None
                ),
                "worst_assessment_date": (
                    iso_date(labels.loc[worst_index, "date"])
                    if worst_index is not None
                    else None
                ),
            }
        )
    return result


def build_horizon_audit(
    labels: pd.DataFrame,
    *,
    horizon: int,
    model_sample_start: pd.Timestamp,
) -> dict[str, Any]:
    """Build all Task 2 diagnostics for one horizon."""

    primary = f"mom_tail_loss_{horizon}"
    sensitivity_columns = {
        "tail_2_5_percent": f"mom_tail_loss_025_{horizon}",
        "tail_10_percent": f"mom_tail_loss_10_{horizon}",
        "tail_and_prior_above_pit_median": (
            f"mom_tail_loss_prior_strength_{horizon}"
        ),
    }
    onset_rows = labels.loc[labels["event_onset"].fillna(False)]
    onset_prior = onset_rows["trailing_umd_return_63d"].dropna()
    positive_prior_share = (
        float((onset_prior > 0).mean()) if not onset_prior.empty else None
    )

    model_subset = labels.loc[labels["date"] >= model_sample_start]
    return {
        "horizon_days": horizon,
        "full_label_history": _event_summary(labels[primary]),
        "model_sample_from_vix_start": _event_summary(model_subset[primary]),
        "model_history_rule": validate_model_history_rule(
            labels,
            horizon=horizon,
            model_sample_start=model_sample_start,
        ),
        "primary_episode_onsets_with_positive_trailing_63d": {
            "episodes_with_observed_prior": int(len(onset_prior)),
            "positive_prior_episodes": int((onset_prior > 0).sum()),
            "share": positive_prior_share,
        },
        "sensitivities": {
            name: _event_summary(labels[column])
            for name, column in sensitivity_columns.items()
        },
        "by_decade": decade_audit(labels, horizon=horizon),
        "crash_windows": crash_window_audit(labels, horizon=horizon),
    }


def _print_audit(audit: dict[str, Any]) -> None:
    for horizon_key, horizon_audit in audit["horizons"].items():
        print(f"\nHorizon {horizon_key} trading days — primary label by decade")
        print(
            pd.DataFrame(horizon_audit["by_decade"])[
                [
                    "decade",
                    "threshold_first",
                    "threshold_last",
                    "event_days",
                    "episodes_started",
                    "valid_label_days",
                ]
            ].to_string(index=False)
        )
        print(f"\nHorizon {horizon_key} — crash-window sanity check")
        print(pd.DataFrame(horizon_audit["crash_windows"]).to_string(index=False))
        print(
            f"\nHorizon {horizon_key} — sensitivities\n"
            + json.dumps(
                horizon_audit["sensitivities"],
                indent=2,
                sort_keys=True,
            )
        )


def run_label_pipeline(
    *,
    as_of_date: pd.Timestamp,
    horizons: Iterable[int] = HORIZONS,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    """Build, serialize, and audit all configured label horizons."""

    momentum_path = processed_dir / "french_momentum_factor_daily.parquet"
    vix_path = processed_dir / "vix_aligned.parquet"
    momentum = pd.read_parquet(momentum_path)
    momentum = momentum.loc[momentum["date"] <= as_of_date].copy()
    if momentum.empty:
        raise ValueError("Momentum input is empty through AS_OF_DATE")

    vix = pd.read_parquet(vix_path, columns=["date", "vix_close"])
    observed_vix = vix.loc[
        (vix["date"] <= as_of_date) & vix["vix_close"].notna(), "date"
    ]
    if observed_vix.empty:
        raise ValueError("Cannot establish the VIX-bounded model-sample start")
    model_sample_start = observed_vix.iloc[0]

    horizon_audits: dict[str, Any] = {}
    for horizon in horizons:
        labels = build_labels_for_horizon(momentum, horizon=horizon)
        output_path = processed_dir / f"momentum_labels_h{horizon}.parquet"
        write_parquet(labels, output_path)
        reloaded = pd.read_parquet(output_path)
        if len(reloaded) != len(labels) or list(reloaded.columns) != list(
            labels.columns
        ):
            raise AssertionError(f"Parquet round-trip failed for horizon {horizon}")
        horizon_audits[str(horizon)] = build_horizon_audit(
            reloaded,
            horizon=horizon,
            model_sample_start=model_sample_start,
        )
        horizon_audits[str(horizon)]["processed_path"] = str(output_path)

    audit: dict[str, Any] = {
        "as_of_date": iso_date(as_of_date),
        "model_sample_start_proxy": iso_date(model_sample_start),
        "historical_threshold_min_matured_observations": (
            HISTORICAL_MIN_MATURED_OBSERVATIONS
        ),
        "model_min_matured_observations": MODEL_MIN_MATURED_OBSERVATIONS,
        "quantile_interpolation": "linear",
        "episode_rule": (
            "new episode only after at least 5 consecutive non-event "
            "assessment days"
        ),
        "horizons": horizon_audits,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "task2_label_audit.json", audit)
    _print_audit(audit)
    return audit


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    run_label_pipeline(
        as_of_date=parse_as_of_date(args.as_of_date),
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()

