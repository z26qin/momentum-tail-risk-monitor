"""Legacy B2 adapter retained for replay; the active MVP uses src.risk."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from src.features.market_features import FEATURE_MECHANISMS, MODEL_FEATURES
from src.monitoring.contracts import (
    SCHEMA_VERSION,
    ArtifactProvenance,
    DriverContribution,
    LegState,
    MarketRegimeState,
    RiskState,
)
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    REPO_ROOT,
    iso_date,
    parse_as_of_date,
    sha256_file,
    write_json,
)


BASELINE = "B2"
TOP_DRIVER_COUNT = 5
RECONCILIATION_TOLERANCE = 1e-9
NEW_YORK = ZoneInfo("America/New_York")
PREDICTION_STATUS = "saved_out_of_sample_prediction"
PREDICTION_COLUMNS = (
    "scope",
    "horizon_days",
    "baseline",
    "split_id",
    "date",
    "predicted_probability",
)


def assessment_timestamp(as_of_date: pd.Timestamp) -> str:
    """Return the approved US-close assessment timestamp with its UTC offset."""

    value = datetime.combine(
        as_of_date.date(),
        time(hour=16),
        tzinfo=NEW_YORK,
    )
    return value.isoformat()


def _provenance(role: str, path: Path) -> ArtifactProvenance:
    try:
        displayed_path = str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        displayed_path = str(path.resolve())
    return ArtifactProvenance(
        role=role,
        path=displayed_path,
        sha256=sha256_file(path),
    )


def _single_row(frame: pd.DataFrame, description: str) -> pd.Series:
    if len(frame) != 1:
        raise ValueError(
            f"Expected one {description} row, found {len(frame)}"
        )
    return frame.iloc[0]


def _optional_float(value: object) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def _optional_bool(value: object) -> bool | None:
    if pd.isna(value):
        return None
    return bool(value)


def _expit(log_odds: float) -> float:
    if log_odds >= 0.0:
        return 1.0 / (1.0 + math.exp(-log_odds))
    exponential = math.exp(log_odds)
    return exponential / (1.0 + exponential)


def _severity(percentile: float) -> str:
    if percentile >= 0.90:
        return "high"
    if percentile >= 0.75:
        return "elevated"
    if percentile >= 0.50:
        return "moderate"
    return "low"


def probability_history_state(
    predictions: pd.DataFrame,
    *,
    as_of_date: pd.Timestamp,
) -> tuple[float, pd.Timestamp | None, float | None]:
    """Compute a weak PIT percentile and prior-score change.

    The caller supplies only one horizon, baseline, scope, and fitted split so
    the score history remains comparable.
    """

    required = {"date", "predicted_probability"}
    missing = required.difference(predictions.columns)
    if missing:
        raise ValueError(
            f"Prediction history missing columns: {sorted(missing)}"
        )
    ordered = predictions.loc[
        predictions["date"].le(as_of_date),
        ["date", "predicted_probability"],
    ].sort_values("date")
    if ordered.empty:
        raise ValueError("No prediction history is available through the date")
    if ordered["date"].duplicated().any():
        raise ValueError("Prediction history contains duplicate dates")
    current_rows = ordered.loc[ordered["date"].eq(as_of_date)]
    current = _single_row(current_rows, "current prediction")
    current_probability = float(current["predicted_probability"])
    percentile = float(
        ordered["predicted_probability"].le(current_probability).mean()
    )
    prior = ordered.loc[ordered["date"].lt(as_of_date)].tail(1)
    if prior.empty:
        return percentile, None, None
    prior_row = prior.iloc[0]
    return (
        percentile,
        pd.Timestamp(prior_row["date"]),
        current_probability - float(prior_row["predicted_probability"]),
    )


def _load_prediction(
    *,
    predictions_path: Path,
    as_of_date: pd.Timestamp,
    horizon: int,
) -> tuple[pd.Series, pd.DataFrame]:
    if horizon not in {5, 20}:
        raise ValueError("horizon must be 5 or 20 trading days")
    predictions = pd.read_parquet(
        predictions_path,
        columns=list(PREDICTION_COLUMNS),
        filters=[
            ("horizon_days", "=", horizon),
            ("baseline", "=", BASELINE),
        ],
    )
    selected = predictions.loc[predictions["date"].eq(as_of_date)]
    row = _single_row(selected, "saved OOS prediction")
    comparable = predictions.loc[
        predictions["scope"].eq(row["scope"])
        & predictions["split_id"].eq(row["split_id"])
    ].copy()
    return row, comparable


def _validate_oos_manifest(
    *,
    output_dir: Path,
    prediction: pd.Series,
    as_of_date: pd.Timestamp,
    horizon: int,
) -> Path:
    scope = str(prediction["scope"])
    manifest_path = output_dir / f"{scope}_manifest.csv"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Missing {scope} split manifest: {manifest_path}"
        )
    manifest = pd.read_csv(
        manifest_path,
        parse_dates=["train_start", "train_end", "test_start", "test_end"],
    )
    match = manifest.loc[
        manifest["horizon_days"].eq(horizon)
        & manifest["split_id"].eq(str(prediction["split_id"]))
    ]
    row = _single_row(match, "split manifest")
    if not (
        pd.Timestamp(row["train_end"]) < pd.Timestamp(row["test_start"])
        <= as_of_date
        <= pd.Timestamp(row["test_end"])
    ):
        raise ValueError(
            "Selected prediction is not inside its strictly later OOS test window"
        )
    return manifest_path


def _model_rows(
    *,
    table_path: Path,
    prediction: pd.Series,
    horizon: int,
) -> pd.DataFrame:
    table = pd.read_csv(table_path)
    return table.loc[
        table["scope"].eq(str(prediction["scope"]))
        & table["horizon_days"].eq(horizon)
        & table["baseline"].eq(BASELINE)
        & table["split_id"].eq(str(prediction["split_id"]))
    ].copy()


def build_driver_contributions(
    *,
    feature_row: pd.Series,
    coefficient_rows: pd.DataFrame,
    preprocessing_rows: pd.DataFrame,
) -> tuple[tuple[DriverContribution, ...], float, float]:
    """Reconstruct every standardized feature contribution and probability."""

    coefficient_by_feature = coefficient_rows.set_index("feature")
    preprocessing_by_feature = preprocessing_rows.set_index("feature")
    expected = set(MODEL_FEATURES)
    actual_coefficients = set(coefficient_by_feature.index).difference(
        {"__intercept__"}
    )
    if actual_coefficients != expected:
        raise ValueError(
            "Coefficient features do not match frozen MODEL_FEATURES"
        )
    if set(preprocessing_by_feature.index) != expected:
        raise ValueError(
            "Preprocessing features do not match frozen MODEL_FEATURES"
        )
    if "__intercept__" not in coefficient_by_feature.index:
        raise ValueError("Frozen B2 coefficients are missing the intercept")

    contributions: list[DriverContribution] = []
    for feature in MODEL_FEATURES:
        raw_value = _optional_float(feature_row[feature])
        preprocessing = preprocessing_by_feature.loc[feature]
        imputed = (
            float(preprocessing["imputer_median"])
            if raw_value is None
            else raw_value
        )
        scale = float(preprocessing["scaler_scale_after_imputation"])
        if not math.isfinite(scale) or scale <= 0.0:
            raise ValueError(f"Invalid frozen scale for {feature}: {scale}")
        standardized = (
            imputed - float(preprocessing["scaler_mean_after_imputation"])
        ) / scale
        coefficient = float(
            coefficient_by_feature.loc[feature, "coefficient_standardized"]
        )
        contribution = standardized * coefficient
        if contribution > 1e-12:
            direction = "increases_risk"
        elif contribution < -1e-12:
            direction = "decreases_risk"
        else:
            direction = "neutral"
        contributions.append(
            DriverContribution(
                feature=feature,
                mechanism=FEATURE_MECHANISMS[feature],
                raw_value=raw_value,
                imputed_value=imputed,
                standardized_value=standardized,
                coefficient=coefficient,
                log_odds_contribution=contribution,
                risk_direction=direction,
            )
        )

    intercept = float(
        coefficient_by_feature.loc[
            "__intercept__", "coefficient_standardized"
        ]
    )
    log_odds = intercept + sum(
        item.log_odds_contribution for item in contributions
    )
    return tuple(contributions), intercept, _expit(log_odds)


def _compounded_return(values: pd.Series) -> float | None:
    if values.empty or values.isna().any():
        return None
    if values.le(-1.0).any():
        raise ValueError("Leg return cannot be less than or equal to -1")
    return float(np.expm1(np.log1p(values.astype(float)).sum()))


def _leg_states(
    *,
    leg_structure_path: Path,
    as_of_date: pd.Timestamp,
) -> tuple[LegState, LegState]:
    frame = pd.read_parquet(
        leg_structure_path,
        columns=["date", "winner_leg_return", "loser_leg_return"],
        filters=[("date", "<=", as_of_date)],
    ).sort_values("date")
    if frame.empty or not frame["date"].iloc[-1] == as_of_date:
        raise ValueError("Momentum leg data do not contain the selected date")
    if frame["date"].duplicated().any():
        raise ValueError("Momentum leg data contain duplicate dates")

    winner = frame["winner_leg_return"].tail(21)
    loser = frame["loser_leg_return"].tail(21)
    winner_volatility = (
        float(winner.std(ddof=1)) if len(winner) == 21 and winner.notna().all() else None
    )
    loser_volatility = (
        float(loser.std(ddof=1)) if len(loser) == 21 and loser.notna().all() else None
    )
    relative = (
        loser_volatility - winner_volatility
        if winner_volatility is not None and loser_volatility is not None
        else None
    )
    winner_state = LegState(
        leg="winner",
        return_1d=_optional_float(winner.iloc[-1]),
        return_5d=_compounded_return(winner.tail(5)),
        return_20d=_compounded_return(winner.tail(20)),
        volatility_21d=winner_volatility,
        relative_to_other_volatility_21d=(
            -relative if relative is not None else None
        ),
    )
    loser_state = LegState(
        leg="loser",
        return_1d=_optional_float(loser.iloc[-1]),
        return_5d=_compounded_return(loser.tail(5)),
        return_20d=_compounded_return(loser.tail(20)),
        volatility_21d=loser_volatility,
        relative_to_other_volatility_21d=relative,
    )
    return winner_state, loser_state


def _market_regime(feature_row: pd.Series) -> MarketRegimeState:
    return MarketRegimeState(
        vix_close=_optional_float(feature_row["vix_close"]),
        bear_state=_optional_bool(feature_row["bear_state"]),
        market_return_1d=_optional_float(feature_row["mkt_return_1d"]),
        market_return_5d=_optional_float(feature_row["mkt_return_5d"]),
        market_return_20d=_optional_float(feature_row["mkt_return_20d"]),
        market_return_504d=_optional_float(feature_row["mkt_return_504d"]),
        market_volatility_percentile_126d=_optional_float(
            feature_row["mkt_vol_percentile_126d"]
        ),
        stress_rebound=_optional_float(feature_row["stress_rebound"]),
        momentum_market_beta_126d=_optional_float(
            feature_row["mom_mkt_beta_126d"]
        ),
        momentum_market_correlation_126d=_optional_float(
            feature_row["mom_mkt_corr_126d"]
        ),
        beta_change_21d=_optional_float(feature_row["beta_change_21d"]),
    )


def build_risk_state(
    *,
    as_of_date: pd.Timestamp,
    horizon: int,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> RiskState:
    """Build a validated RiskState without fitting or loading forward labels."""

    as_of_date = pd.Timestamp(as_of_date).normalize()
    predictions_path = output_dir / "baseline_predictions.parquet"
    coefficients_path = output_dir / "model_coefficients.csv"
    preprocessing_path = output_dir / "preprocessing_statistics.csv"
    validation_audit_path = output_dir / "task4_validation_audit.json"
    feature_audit_path = output_dir / "task3_feature_audit.json"
    features_path = processed_dir / "market_features.parquet"
    leg_structure_path = processed_dir / "momentum_leg_structure.parquet"

    prediction, comparable_history = _load_prediction(
        predictions_path=predictions_path,
        as_of_date=as_of_date,
        horizon=horizon,
    )
    manifest_path = _validate_oos_manifest(
        output_dir=output_dir,
        prediction=prediction,
        as_of_date=as_of_date,
        horizon=horizon,
    )

    feature_frame = pd.read_parquet(
        features_path,
        columns=["date", *MODEL_FEATURES],
        filters=[("date", "=", as_of_date)],
    )
    feature_row = _single_row(feature_frame, "market feature")
    coefficient_rows = _model_rows(
        table_path=coefficients_path,
        prediction=prediction,
        horizon=horizon,
    )
    preprocessing_rows = _model_rows(
        table_path=preprocessing_path,
        prediction=prediction,
        horizon=horizon,
    )
    contributions, intercept, reconstructed = build_driver_contributions(
        feature_row=feature_row,
        coefficient_rows=coefficient_rows,
        preprocessing_rows=preprocessing_rows,
    )
    saved_probability = float(prediction["predicted_probability"])
    reconciliation_error = abs(reconstructed - saved_probability)
    if reconciliation_error > RECONCILIATION_TOLERANCE:
        raise AssertionError(
            "Frozen parameter reconstruction does not match the saved "
            f"probability: error={reconciliation_error:.3g}"
        )
    log_odds = math.log(reconstructed / (1.0 - reconstructed))

    percentile, previous_date, change = probability_history_state(
        comparable_history,
        as_of_date=as_of_date,
    )
    winner_state, loser_state = _leg_states(
        leg_structure_path=leg_structure_path,
        as_of_date=as_of_date,
    )

    future_features = pd.read_parquet(
        features_path,
        columns=["date"],
        filters=[("date", ">", as_of_date)],
    ).sort_values("date")
    earliest_action_date = (
        iso_date(future_features["date"].iloc[0])
        if not future_features.empty
        else None
    )
    validation_audit = json.loads(
        validation_audit_path.read_text(encoding="utf-8")
    )
    feature_audit = json.loads(feature_audit_path.read_text(encoding="utf-8"))

    primary_drivers = tuple(
        sorted(
            contributions,
            key=lambda item: abs(item.log_odds_contribution),
            reverse=True,
        )[:TOP_DRIVER_COUNT]
    )
    state = RiskState(
        schema_version=SCHEMA_VERSION,
        as_of_date=iso_date(as_of_date),
        as_of_timestamp=assessment_timestamp(as_of_date),
        earliest_action_date=earliest_action_date,
        earliest_action_convention=(
            "Post-close assessment; earliest action is the next momentum "
            "trading session."
        ),
        risk_horizon_trading_days=horizon,
        risk_probability=saved_probability,
        reconstructed_probability=reconstructed,
        probability_reconciliation_error=reconciliation_error,
        model_log_odds=log_odds,
        model_intercept=intercept,
        risk_severity=_severity(percentile),
        historical_percentile=percentile,
        percentile_reference=(
            "Weak percentile among B2 OOS probabilities through the as-of "
            "date for the same horizon, evaluation scope, and fitted split."
        ),
        previous_as_of_date=(
            iso_date(previous_date) if previous_date is not None else None
        ),
        change_from_previous=change,
        primary_market_drivers=primary_drivers,
        winner_leg_state=winner_state,
        loser_leg_state=loser_state,
        market_regime_state=_market_regime(feature_row),
        model_baseline=BASELINE,
        model_scope=str(prediction["scope"]),
        model_split_id=str(prediction["split_id"]),
        model_specification_hash=str(validation_audit["specification_hash"]),
        data_vintage=str(feature_audit["as_of_date"]),
        prediction_status=PREDICTION_STATUS,
        calibration_limitations=(
            "B2 development calibration slopes are approximately 0.17 and "
            "development log loss is worse than the constant baseline.",
            "The 20-day holdout contains only one independent event episode.",
            "Severity is a descriptive score percentile, not a validated "
            "alert or trading threshold.",
        ),
        data_quality_flags=(
            "same_day_source_publication_timestamps_not_historically_verified",
            "public_source_snapshots_may_contain_later_vendor_revisions",
            "market_only_model_does_not_observe_flows_holdings_or_leverage",
        ),
        provenance=(
            _provenance("saved_oos_predictions", predictions_path),
            _provenance("fold_coefficients", coefficients_path),
            _provenance("fold_preprocessing", preprocessing_path),
            _provenance("oos_split_manifest", manifest_path),
            _provenance("market_features", features_path),
            _provenance("momentum_leg_structure", leg_structure_path),
            _provenance("model_integrity_audit", validation_audit_path),
            _provenance("feature_audit", feature_audit_path),
        ),
    )
    return state


def run_risk_state(
    *,
    as_of_date: pd.Timestamp,
    horizon: int,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[RiskState, Path]:
    state = build_risk_state(
        as_of_date=as_of_date,
        horizon=horizon,
        processed_dir=processed_dir,
        output_dir=output_dir,
    )
    path = output_dir / "debug" / f"risk_state_{state.as_of_date}.json"
    write_json(path, state.to_dict())
    return state, path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--horizon", type=int, choices=(5, 20), default=20)
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    state, path = run_risk_state(
        as_of_date=parse_as_of_date(args.as_of_date),
        horizon=args.horizon,
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(state.to_dict(), indent=2, sort_keys=True))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
