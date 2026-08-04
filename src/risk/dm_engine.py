"""Literature-anchored, point-in-time momentum tail-risk state.

Daniel and Moskowitz define the ex-ante bear indicator from a negative
cumulative market return over the prior 24 months and interact it with market
variance estimated from the prior 126 daily returns.  Their panic variable is
continuous rather than a published binary alert threshold.

For an operational daily MVP, this module preserves that structure and defines
``panic_elevated`` when the market is in the bear state and its 126-day
variance is at least the expanding mean variance previously observed in bear
states.  The threshold is therefore an explicitly labeled operationalization,
not a threshold claimed by the paper.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.mvp.contracts import (
    SCHEMA_VERSION,
    PrimaryRiskAssessment,
    ProvenanceRef,
)
from src.utils.market_time import assessment_timestamp
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    REPO_ROOT,
    iso_date,
    parse_as_of_date,
    sha256_file,
    write_json,
)


METHOD = "dm_pit_conditional_frequency"
ELEVATION_RULE = (
    "bear_state is true and 126-day market variance is at least the "
    "point-in-time expanding mean variance among bear-state observations"
)
FEATURE_COLUMNS = (
    "date",
    "mkt_return_504d",
    "bear_state",
    "mkt_variance_126d",
)


def _provenance(role: str, path: Path) -> ProvenanceRef:
    try:
        displayed = str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        displayed = str(path.resolve())
    return ProvenanceRef(
        role=role,
        path=displayed,
        sha256=sha256_file(path),
    )


def build_state_history(features: pd.DataFrame) -> pd.DataFrame:
    """Create a daily PIT panic intensity and operational state."""

    required = set(FEATURE_COLUMNS)
    missing = required.difference(features.columns)
    if missing:
        raise ValueError(f"market features missing columns: {sorted(missing)}")
    frame = features.loc[:, FEATURE_COLUMNS].sort_values("date").copy()
    if frame["date"].duplicated().any():
        raise ValueError("market features contain duplicate dates")

    bear = frame["bear_state"].astype("boolean")
    variance = pd.to_numeric(frame["mkt_variance_126d"], errors="coerce")
    bear_variance = variance.where(bear.eq(True))
    expanding_bear_mean = bear_variance.expanding(min_periods=1).mean()
    intensity = variance / expanding_bear_mean
    valid = bear.notna() & variance.notna()

    state = pd.Series(pd.NA, index=frame.index, dtype="string")
    state.loc[valid & bear.eq(False)] = "normal"
    state.loc[valid & bear.eq(True) & intensity.lt(1.0)] = "bear_low_volatility"
    state.loc[valid & bear.eq(True) & intensity.ge(1.0)] = "panic_elevated"

    frame["panic_intensity"] = intensity.where(bear.eq(True))
    frame["primary_state"] = state
    return frame


def _matured_history(
    *,
    labels: pd.DataFrame,
    states: pd.DataFrame,
    as_of_date: pd.Timestamp,
    horizon: int,
) -> pd.DataFrame:
    forward_column = f"fwd_mom_return_{horizon}"
    event_column = f"mom_tail_loss_{horizon}"
    required = {
        "date",
        "label_available_date",
        forward_column,
        event_column,
    }
    missing = required.difference(labels.columns)
    if missing:
        raise ValueError(f"labels missing columns: {sorted(missing)}")
    matured = labels.loc[
        labels["label_available_date"].notna()
        & labels["label_available_date"].le(as_of_date)
        & labels[forward_column].notna()
        & labels[event_column].notna(),
        [
            "date",
            "label_available_date",
            forward_column,
            event_column,
        ],
    ].copy()
    matured = matured.merge(
        states.loc[:, ["date", "primary_state"]],
        on="date",
        how="left",
        validate="one_to_one",
    )
    matured = matured.loc[matured["primary_state"].notna()].copy()
    matured[event_column] = matured[event_column].astype(bool)
    if matured.empty:
        raise ValueError("no matured labels are available through the as-of date")
    return matured


def build_primary_assessment(
    *,
    as_of_date: pd.Timestamp,
    horizon: int = 20,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
) -> PrimaryRiskAssessment:
    """Build one primary assessment without fitting a predictive model."""

    if horizon not in {5, 20}:
        raise ValueError("horizon must be 5 or 20")
    as_of_date = pd.Timestamp(as_of_date).normalize()
    features_path = processed_dir / "market_features.parquet"
    labels_path = processed_dir / f"momentum_labels_h{horizon}.parquet"

    features = pd.read_parquet(
        features_path,
        columns=list(FEATURE_COLUMNS),
        filters=[("date", "<=", as_of_date)],
    )
    states = build_state_history(features)
    current_rows = states.loc[states["date"].eq(as_of_date)]
    if len(current_rows) != 1:
        raise ValueError(
            f"market features must contain exactly one row on {iso_date(as_of_date)}"
        )
    current = current_rows.iloc[0]
    if pd.isna(current["primary_state"]):
        raise ValueError("primary state is unavailable on the selected date")

    labels = pd.read_parquet(
        labels_path,
        filters=[("date", "<=", as_of_date)],
    )
    matured = _matured_history(
        labels=labels,
        states=states,
        as_of_date=as_of_date,
        horizon=horizon,
    )
    state = str(current["primary_state"])
    conditioned = matured.loc[matured["primary_state"].eq(state)]
    if conditioned.empty:
        raise ValueError(f"no matured labels are available for state {state}")

    event_column = f"mom_tail_loss_{horizon}"
    forward_column = f"fwd_mom_return_{horizon}"
    current_bear = bool(current["bear_state"])
    current_intensity = (
        None
        if pd.isna(current["panic_intensity"])
        else float(current["panic_intensity"])
    )
    maturity_cutoff = pd.Timestamp(matured["label_available_date"].max())

    return PrimaryRiskAssessment(
        schema_version=SCHEMA_VERSION,
        method=METHOD,
        as_of_date=iso_date(as_of_date),
        as_of_timestamp=assessment_timestamp(as_of_date),
        horizon_days=horizon,
        state=state,
        elevated=state == "panic_elevated",
        bear_state=current_bear,
        market_return_504d=float(current["mkt_return_504d"]),
        market_variance_126d=float(current["mkt_variance_126d"]),
        panic_intensity=current_intensity,
        elevation_rule=ELEVATION_RULE,
        tail_loss_probability=float(conditioned[event_column].mean()),
        conditioning_sample_size=int(len(conditioned)),
        conditional_mean_forward_return=float(conditioned[forward_column].mean()),
        conditional_fifth_percentile=float(
            conditioned[forward_column].quantile(0.05)
        ),
        unconditional_tail_loss_probability=float(matured[event_column].mean()),
        unconditional_sample_size=int(len(matured)),
        label_maturity_cutoff_date=iso_date(maturity_cutoff),
        limitations=(
            "The paper defines a continuous bear-state-times-variance variable; "
            "the binary elevation boundary is an explicit operationalization.",
            "Daily Ken French and broad-market public proxies replace the paper's "
            "monthly CRSP implementation.",
            "Conditional frequencies are descriptive historical rates, not "
            "calibrated forecasts or trading thresholds.",
        ),
        provenance=(
            _provenance("market_features", features_path),
            _provenance("matured_tail_labels", labels_path),
        ),
    )


def build_insurance_table(
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
) -> pd.DataFrame:
    """Compare unconditional and state-conditional tail-loss frequencies."""

    as_of_date = pd.Timestamp(as_of_date).normalize()
    features_path = processed_dir / "market_features.parquet"
    features = pd.read_parquet(
        features_path,
        columns=list(FEATURE_COLUMNS),
        filters=[("date", "<=", as_of_date)],
    )
    states = build_state_history(features)
    rows: list[dict[str, object]] = []
    for horizon in (5, 20):
        labels = pd.read_parquet(
            processed_dir / f"momentum_labels_h{horizon}.parquet",
            filters=[("date", "<=", as_of_date)],
        )
        matured = _matured_history(
            labels=labels,
            states=states,
            as_of_date=as_of_date,
            horizon=horizon,
        )
        event = f"mom_tail_loss_{horizon}"
        forward = f"fwd_mom_return_{horizon}"
        for state in ("all", "normal", "bear_low_volatility", "panic_elevated"):
            sample = matured if state == "all" else matured.loc[
                matured["primary_state"].eq(state)
            ]
            if sample.empty:
                continue
            rows.append(
                {
                    "as_of_date": iso_date(as_of_date),
                    "horizon_days": horizon,
                    "state": state,
                    "sample_size": int(len(sample)),
                    "tail_loss_frequency": float(sample[event].mean()),
                    "mean_forward_return": float(sample[forward].mean()),
                    "fifth_percentile_forward_return": float(
                        sample[forward].quantile(0.05)
                    ),
                    "latest_label_available_date": iso_date(
                        pd.Timestamp(sample["label_available_date"].max())
                    ),
                }
            )
    return pd.DataFrame(rows)


def run_primary_assessment(
    *,
    as_of_date: pd.Timestamp,
    horizon: int = 20,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[PrimaryRiskAssessment, Path, Path]:
    assessment = build_primary_assessment(
        as_of_date=as_of_date,
        horizon=horizon,
        processed_dir=processed_dir,
    )
    mvp_dir = output_dir / "mvp"
    state_path = mvp_dir / f"risk_state_{assessment.as_of_date}_h{horizon}.json"
    write_json(state_path, assessment.to_dict())
    insurance = build_insurance_table(
        as_of_date=as_of_date,
        processed_dir=processed_dir,
    )
    insurance_path = mvp_dir / f"insurance_table_{assessment.as_of_date}.csv"
    insurance_path.parent.mkdir(parents=True, exist_ok=True)
    insurance.to_csv(insurance_path, index=False)
    return assessment, state_path, insurance_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--horizon", type=int, choices=(5, 20), default=20)
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    assessment, state_path, insurance_path = run_primary_assessment(
        as_of_date=parse_as_of_date(args.as_of_date),
        horizon=args.horizon,
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(assessment.to_dict(), indent=2, sort_keys=True))
    print(f"Wrote {state_path}")
    print(f"Wrote {insurance_path}")


if __name__ == "__main__":
    main()
