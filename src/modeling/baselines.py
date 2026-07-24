"""Fit and evaluate the frozen Task 4 baseline ladder."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import warnings
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.features.labels import HORIZONS
from src.features.market_features import MODEL_FEATURES
from src.modeling.validation import (
    HOLDOUT_YEARS,
    INITIAL_TRAIN_YEARS,
    STEP_YEARS,
    TEST_BLOCK_YEARS,
    PurgedExpandingWalkForward,
    PurgedSplit,
    make_purged_holdout,
)
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    iso_date,
    parse_as_of_date,
    sha256_file,
    write_json,
    write_parquet,
)


BASELINE_FEATURES: dict[str, tuple[str, ...]] = {
    "B0": (),
    "B1": (
        "bear_state",
        "mkt_variance_126d",
        "bear_x_mkt_variance_126d",
    ),
    "B2": MODEL_FEATURES,
}
LOGISTIC_C = 1.0
LOGISTIC_MAX_ITER = 2_000
RANDOM_STATE = 0
CALIBRATION_BUCKETS = 10
TOP_RISK_SHARE = 0.10

MODEL_SPECIFICATION: dict[str, Any] = {
    "baselines": {
        name: list(features) for name, features in BASELINE_FEATURES.items()
    },
    "B0": (
        "constant event rate in the purged training rows; every contributing "
        "label is mature before the test begins"
    ),
    "logistic": {
        "class_weight": None,
        "C": LOGISTIC_C,
        "solver": "lbfgs",
        "max_iter": LOGISTIC_MAX_ITER,
        "random_state": RANDOM_STATE,
        "penalty": "L2 through sklearn default",
    },
    "preprocessing": {
        "imputation": "training-fold median",
        "scaling": "training-fold StandardScaler",
        "pipeline_scope": "fit independently inside every split",
    },
    "validation": {
        "initial_train_years": INITIAL_TRAIN_YEARS,
        "test_block_years": TEST_BLOCK_YEARS,
        "step_years": STEP_YEARS,
        "holdout_years": HOLDOUT_YEARS,
        "purge_rule": "drop train row when label_end_date >= test_start",
    },
    "metrics": [
        "log_loss",
        "brier_score",
        "pr_auc",
        "roc_auc",
        "calibration_intercept",
        "calibration_slope",
        "event_capture_top_risk_decile",
    ],
    "probability_buckets": CALIBRATION_BUCKETS,
    "calibration_regression": (
        "unpenalized logistic regression of event on predicted log odds"
    ),
    "top_risk_share": TOP_RISK_SHARE,
    "alert_threshold": None,
}


def specification_hash() -> str:
    """Return a deterministic hash of the complete frozen model specification."""

    payload = json.dumps(
        MODEL_SPECIFICATION, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    frame.to_csv(
        temporary_path,
        index=False,
        lineterminator="\n",
        float_format="%.12g",
    )
    temporary_path.replace(path)


def _model_frame(
    *,
    processed_dir: Path,
    horizon: int,
    model_start: pd.Timestamp,
    end_date: pd.Timestamp,
    end_inclusive: bool,
) -> pd.DataFrame:
    comparator = "<=" if end_inclusive else "<"
    filters = [("date", ">=", model_start), ("date", comparator, end_date)]
    features = pd.read_parquet(
        processed_dir / "market_features.parquet",
        filters=filters,
    )
    labels = pd.read_parquet(
        processed_dir / f"momentum_labels_h{horizon}.parquet",
        filters=filters,
    )
    label_column = f"mom_tail_loss_{horizon}"
    label_columns = [
        "date",
        "label_end_date",
        label_column,
        "event_episode_id",
    ]
    frame = features.loc[:, ["date", *MODEL_FEATURES]].merge(
        labels.loc[:, label_columns],
        on="date",
        how="inner",
        validate="one_to_one",
    )
    frame = frame.loc[frame[label_column].notna()].copy()
    frame.rename(columns={label_column: "event"}, inplace=True)
    frame["event"] = frame["event"].astype(bool)
    frame.sort_values("date", inplace=True)
    frame.reset_index(drop=True, inplace=True)
    if frame.empty:
        raise ValueError(f"No valid model rows for horizon {horizon}")
    return frame


def _pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            (
                "logistic",
                LogisticRegression(
                    C=LOGISTIC_C,
                    solver="lbfgs",
                    max_iter=LOGISTIC_MAX_ITER,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def _numeric_features(
    frame: pd.DataFrame,
    feature_names: Iterable[str],
) -> pd.DataFrame:
    return frame.loc[:, list(feature_names)].astype("float64")


def _fit_predict(
    *,
    train: pd.DataFrame,
    test: pd.DataFrame,
    baseline: str,
) -> tuple[np.ndarray, list[dict[str, Any]], list[dict[str, Any]]]:
    features = BASELINE_FEATURES[baseline]
    if baseline == "B0":
        event_rate = float(train["event"].mean())
        if not 0.0 < event_rate < 1.0:
            raise ValueError("B0 training event rate must lie strictly in (0, 1)")
        predictions = np.full(len(test), event_rate, dtype=float)
        coefficient_rows = [
            {
                "feature": "__intercept_log_odds__",
                "coefficient_standardized": float(
                    math.log(event_rate / (1.0 - event_rate))
                ),
            }
        ]
        return predictions, coefficient_rows, []

    train_x = _numeric_features(train, features)
    test_x = _numeric_features(test, features)
    model = _pipeline()
    model.fit(train_x, train["event"].astype(int))
    predictions = model.predict_proba(test_x)[:, 1]

    imputer = model.named_steps["imputer"]
    scaler = model.named_steps["scaler"]
    logistic = model.named_steps["logistic"]
    coefficient_rows = [
        {
            "feature": feature,
            "coefficient_standardized": float(coefficient),
        }
        for feature, coefficient in zip(
            features, logistic.coef_[0], strict=True
        )
    ]
    coefficient_rows.append(
        {
            "feature": "__intercept__",
            "coefficient_standardized": float(logistic.intercept_[0]),
        }
    )
    preprocessing_rows = [
        {
            "feature": feature,
            "imputer_median": float(imputer.statistics_[position]),
            "scaler_mean_after_imputation": float(scaler.mean_[position]),
            "scaler_scale_after_imputation": float(scaler.scale_[position]),
            "missing_train": int(train_x[feature].isna().sum()),
            "missing_test": int(test_x[feature].isna().sum()),
        }
        for position, feature in enumerate(features)
    ]
    return predictions, coefficient_rows, preprocessing_rows


def _calibration_intercept_slope(
    event: np.ndarray,
    probability: np.ndarray,
) -> tuple[float, float]:
    observed_rate = float(np.mean(event))
    clipped = np.clip(probability, 1e-8, 1.0 - 1e-8)
    logit_probability = np.log(clipped / (1.0 - clipped))
    if np.ptp(logit_probability) < 1e-12:
        predicted_log_odds = float(logit_probability[0])
        observed_log_odds = math.log(
            observed_rate / (1.0 - observed_rate)
        )
        return observed_log_odds - predicted_log_odds, float("nan")

    calibration = LogisticRegression(
        C=np.inf,
        solver="lbfgs",
        max_iter=LOGISTIC_MAX_ITER,
        random_state=RANDOM_STATE,
    )
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Setting penalty=None will ignore the C and l1_ratio parameters",
            category=UserWarning,
        )
        calibration.fit(logit_probability.reshape(-1, 1), event)
    return (
        float(calibration.intercept_[0]),
        float(calibration.coef_[0, 0]),
    )


def _metric_row(
    predictions: pd.DataFrame,
    *,
    scope: str,
    horizon: int,
    baseline: str,
    split_id: str,
) -> dict[str, Any]:
    event = predictions["event"].astype(int).to_numpy()
    probability = predictions["predicted_probability"].to_numpy(dtype=float)
    if len(np.unique(event)) != 2:
        raise ValueError(
            f"{scope}/{horizon}/{baseline}/{split_id} lacks both classes"
        )
    calibration_intercept, calibration_slope = (
        _calibration_intercept_slope(event, probability)
    )

    top_count = max(1, int(math.ceil(TOP_RISK_SHARE * len(predictions))))
    ranked = predictions.sort_values(
        ["predicted_probability", "date"],
        ascending=[False, True],
        kind="mergesort",
    )
    top = ranked.iloc[:top_count]
    event_days = int(event.sum())
    return {
        "scope": scope,
        "horizon_days": horizon,
        "baseline": baseline,
        "split_id": split_id,
        "rows": int(len(predictions)),
        "event_days": event_days,
        "non_event_days": int(len(predictions) - event_days),
        "event_rate": float(event.mean()),
        "event_episodes": int(
            predictions.loc[
                predictions["event"], "event_episode_id"
            ].nunique()
        ),
        "log_loss": float(log_loss(event, probability)),
        "brier_score": float(brier_score_loss(event, probability)),
        "pr_auc": float(average_precision_score(event, probability)),
        "roc_auc": float(roc_auc_score(event, probability)),
        "calibration_intercept": calibration_intercept,
        "calibration_slope": calibration_slope,
        "top_risk_decile_rows": top_count,
        "top_risk_decile_event_days": int(top["event"].sum()),
        "event_capture_top_risk_decile": float(
            top["event"].sum() / event_days
        ),
    }


def _calibration_rows(
    predictions: pd.DataFrame,
    *,
    scope: str,
    horizon: int,
    baseline: str,
) -> list[dict[str, Any]]:
    working = predictions.sort_values(
        ["predicted_probability", "date"],
        kind="mergesort",
    ).copy()
    try:
        bucket = pd.qcut(
            working["predicted_probability"],
            q=CALIBRATION_BUCKETS,
            labels=False,
            duplicates="drop",
        )
    except ValueError:
        bucket = pd.Series(0, index=working.index, dtype=int)
    if bucket.isna().all():
        bucket = pd.Series(0, index=working.index, dtype=int)
    working["bucket"] = bucket.fillna(0).astype(int) + 1

    rows: list[dict[str, Any]] = []
    for bucket_number, group in working.groupby("bucket", sort=True):
        rows.append(
            {
                "scope": scope,
                "horizon_days": horizon,
                "baseline": baseline,
                "probability_bucket": int(bucket_number),
                "rows": int(len(group)),
                "event_days": int(group["event"].sum()),
                "event_episodes": int(
                    group.loc[group["event"], "event_episode_id"].nunique()
                ),
                "predicted_probability_min": float(
                    group["predicted_probability"].min()
                ),
                "predicted_probability_mean": float(
                    group["predicted_probability"].mean()
                ),
                "predicted_probability_max": float(
                    group["predicted_probability"].max()
                ),
                "realized_event_rate": float(group["event"].mean()),
            }
        )
    return rows


def _prediction_rows(
    *,
    test: pd.DataFrame,
    probability: np.ndarray,
    scope: str,
    horizon: int,
    baseline: str,
    split_id: str,
) -> pd.DataFrame:
    result = test.loc[
        :, ["date", "label_end_date", "event", "event_episode_id"]
    ].copy()
    result.insert(0, "scope", scope)
    result.insert(1, "horizon_days", horizon)
    result.insert(2, "baseline", baseline)
    result.insert(3, "split_id", split_id)
    result["predicted_probability"] = probability
    return result


def _split_manifest_row(
    frame: pd.DataFrame,
    split: PurgedSplit,
    *,
    horizon: int,
) -> dict[str, Any]:
    train = frame.loc[split.train_index]
    test = frame.loc[split.test_index]
    return {
        "split_id": split.split_id,
        "split_kind": split.split_kind,
        "horizon_days": horizon,
        "train_start": iso_date(train["date"].min()),
        "train_end": iso_date(train["date"].max()),
        "test_start": iso_date(test["date"].min()),
        "test_end": iso_date(test["date"].max()),
        "train_rows_before_purge": int(
            len(train) + len(split.purged_index)
        ),
        "purged_rows": int(len(split.purged_index)),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "train_event_days": int(train["event"].sum()),
        "test_event_days": int(test["event"].sum()),
        "train_episode_count": int(
            train.loc[train["event"], "event_episode_id"].nunique()
        ),
        "test_episode_count": int(
            test.loc[test["event"], "event_episode_id"].nunique()
        ),
    }


def _evaluate_splits(
    *,
    frames: dict[int, pd.DataFrame],
    splits: dict[int, list[PurgedSplit]],
    scope: str,
) -> dict[str, pd.DataFrame]:
    prediction_parts: list[pd.DataFrame] = []
    fold_metric_rows: list[dict[str, Any]] = []
    coefficient_rows: list[dict[str, Any]] = []
    preprocessing_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []

    for horizon in HORIZONS:
        frame = frames[horizon]
        for split in splits[horizon]:
            train = frame.loc[split.train_index]
            test = frame.loc[split.test_index]
            manifest_rows.append(
                _split_manifest_row(frame, split, horizon=horizon)
            )
            for baseline in BASELINE_FEATURES:
                probability, coefficients, preprocessing = _fit_predict(
                    train=train,
                    test=test,
                    baseline=baseline,
                )
                prediction = _prediction_rows(
                    test=test,
                    probability=probability,
                    scope=scope,
                    horizon=horizon,
                    baseline=baseline,
                    split_id=split.split_id,
                )
                prediction_parts.append(prediction)
                fold_metric_rows.append(
                    _metric_row(
                        prediction,
                        scope=scope,
                        horizon=horizon,
                        baseline=baseline,
                        split_id=split.split_id,
                    )
                )
                for row in coefficients:
                    coefficient_rows.append(
                        {
                            "scope": scope,
                            "horizon_days": horizon,
                            "baseline": baseline,
                            "split_id": split.split_id,
                            **row,
                        }
                    )
                for row in preprocessing:
                    preprocessing_rows.append(
                        {
                            "scope": scope,
                            "horizon_days": horizon,
                            "baseline": baseline,
                            "split_id": split.split_id,
                            **row,
                        }
                    )

    predictions = pd.concat(prediction_parts, ignore_index=True)
    aggregate_metric_rows: list[dict[str, Any]] = []
    calibration_rows: list[dict[str, Any]] = []
    for (horizon, baseline), group in predictions.groupby(
        ["horizon_days", "baseline"], sort=True
    ):
        aggregate_metric_rows.append(
            _metric_row(
                group,
                scope=scope,
                horizon=int(horizon),
                baseline=str(baseline),
                split_id="all",
            )
        )
        calibration_rows.extend(
            _calibration_rows(
                group,
                scope=scope,
                horizon=int(horizon),
                baseline=str(baseline),
            )
        )

    return {
        "predictions": predictions,
        "fold_metrics": pd.DataFrame(fold_metric_rows),
        "metrics": pd.DataFrame(aggregate_metric_rows),
        "calibration": pd.DataFrame(calibration_rows),
        "coefficients": pd.DataFrame(coefficient_rows),
        "preprocessing": pd.DataFrame(preprocessing_rows),
        "manifest": pd.DataFrame(manifest_rows),
    }


def _write_evaluation(
    result: dict[str, pd.DataFrame],
    *,
    scope: str,
    output_dir: Path,
) -> dict[str, str]:
    paths = {
        "predictions": output_dir / f"{scope}_predictions.parquet",
        "fold_metrics": output_dir / f"{scope}_fold_metrics.csv",
        "metrics": output_dir / f"{scope}_metrics.csv",
        "calibration": output_dir / f"{scope}_calibration.csv",
        "coefficients": output_dir / f"{scope}_coefficients.csv",
        "preprocessing": output_dir / f"{scope}_preprocessing.csv",
        "manifest": output_dir / f"{scope}_manifest.csv",
    }
    write_parquet(result["predictions"], paths["predictions"])
    for key in (
        "fold_metrics",
        "metrics",
        "calibration",
        "coefficients",
        "preprocessing",
        "manifest",
    ):
        _write_csv(result[key], paths[key])
    return {name: str(path) for name, path in paths.items()}


def run_development_validation(
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    """Fit all development folds and freeze the specification before holdout."""

    split_gate = json.loads(
        (output_dir / "task4_split_gate.json").read_text(encoding="utf-8")
    )
    if not split_gate["model_fitting_permitted"]:
        raise ValueError("Development episode gate has not passed")
    if (
        split_gate["test_block_years"] != TEST_BLOCK_YEARS
        or split_gate["step_years"] != STEP_YEARS
    ):
        raise ValueError("Split-gate configuration differs from model code")

    model_start = pd.Timestamp(split_gate["model_sample_start"])
    holdout_start = pd.Timestamp(split_gate["holdout_nominal_start"])
    frames = {
        horizon: _model_frame(
            processed_dir=processed_dir,
            horizon=horizon,
            model_start=model_start,
            end_date=holdout_start,
            end_inclusive=False,
        )
        for horizon in HORIZONS
    }
    splitter = PurgedExpandingWalkForward()
    splits = {
        horizon: list(
            splitter.split(
                frame,
                model_start=model_start,
                development_end=holdout_start,
            )
        )
        for horizon, frame in frames.items()
    }
    result = _evaluate_splits(
        frames=frames,
        splits=splits,
        scope="development",
    )
    paths = _write_evaluation(
        result, scope="development", output_dir=output_dir
    )

    audit = {
        "as_of_date": iso_date(as_of_date),
        "scope": "development",
        "specification_hash": specification_hash(),
        "specification_frozen_before_holdout": True,
        "holdout_predictions_generated": False,
        "model_specification": MODEL_SPECIFICATION,
        "split_count_by_horizon": {
            str(horizon): len(splits[horizon]) for horizon in HORIZONS
        },
        "artifacts": paths,
        "artifact_sha256": {
            name: sha256_file(Path(path)) for name, path in paths.items()
        },
    }
    write_json(output_dir / "task4_development_audit.json", audit)
    return audit


def run_holdout_evaluation(
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    """Evaluate the retained holdout once under the frozen specification."""

    development_audit_path = output_dir / "task4_development_audit.json"
    development_audit = json.loads(
        development_audit_path.read_text(encoding="utf-8")
    )
    if not development_audit["specification_frozen_before_holdout"]:
        raise ValueError("Development specification is not frozen")
    if development_audit["specification_hash"] != specification_hash():
        raise ValueError("Current model specification differs from frozen audit")

    split_gate = json.loads(
        (output_dir / "task4_split_gate.json").read_text(encoding="utf-8")
    )
    model_start = pd.Timestamp(split_gate["model_sample_start"])
    holdout_start = pd.Timestamp(split_gate["holdout_nominal_start"])
    frames = {
        horizon: _model_frame(
            processed_dir=processed_dir,
            horizon=horizon,
            model_start=model_start,
            end_date=as_of_date,
            end_inclusive=True,
        )
        for horizon in HORIZONS
    }
    splits = {
        horizon: [
            make_purged_holdout(
                frame,
                model_start=model_start,
                holdout_start=holdout_start,
                as_of_date=as_of_date,
            )
        ]
        for horizon, frame in frames.items()
    }
    result = _evaluate_splits(
        frames=frames,
        splits=splits,
        scope="holdout",
    )
    paths = _write_evaluation(result, scope="holdout", output_dir=output_dir)

    combined_artifacts = _write_combined_outputs(output_dir=output_dir)
    audit = {
        "as_of_date": iso_date(as_of_date),
        "scope": "holdout",
        "specification_hash": specification_hash(),
        "holdout_evaluation_status": (
            "reported once after development specification freeze"
        ),
        "aggregate_only_holdout_contamination_accepted": True,
        "model_specification": MODEL_SPECIFICATION,
        "artifacts": paths,
        "combined_artifacts": combined_artifacts,
        "artifact_sha256": {
            name: sha256_file(Path(path)) for name, path in paths.items()
        },
    }
    write_json(output_dir / "task4_holdout_audit.json", audit)
    return audit


def _write_combined_outputs(*, output_dir: Path) -> dict[str, str]:
    predictions = pd.concat(
        [
            pd.read_parquet(output_dir / "development_predictions.parquet"),
            pd.read_parquet(output_dir / "holdout_predictions.parquet"),
        ],
        ignore_index=True,
    )
    write_parquet(predictions, output_dir / "baseline_predictions.parquet")

    combinations = {
        "baseline_metrics": ("development_metrics.csv", "holdout_metrics.csv"),
        "calibration_table": (
            "development_calibration.csv",
            "holdout_calibration.csv",
        ),
        "model_coefficients": (
            "development_coefficients.csv",
            "holdout_coefficients.csv",
        ),
        "preprocessing_statistics": (
            "development_preprocessing.csv",
            "holdout_preprocessing.csv",
        ),
    }
    paths: dict[str, str] = {
        "baseline_predictions": str(
            output_dir / "baseline_predictions.parquet"
        )
    }
    for output_stem, inputs in combinations.items():
        combined = pd.concat(
            [pd.read_csv(output_dir / name) for name in inputs],
            ignore_index=True,
        )
        path = output_dir / f"{output_stem}.csv"
        _write_csv(combined, path)
        paths[output_stem] = str(path)
    return paths


def _print_metrics(output_dir: Path, scope: str) -> None:
    metrics = pd.read_csv(output_dir / f"{scope}_metrics.csv")
    print(
        metrics[
            [
                "scope",
                "horizon_days",
                "baseline",
                "rows",
                "event_days",
                "event_episodes",
                "log_loss",
                "brier_score",
                "pr_auc",
                "roc_auc",
                "event_capture_top_risk_decile",
            ]
        ].to_string(index=False)
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        required=True,
        choices=("development", "holdout"),
    )
    parser.add_argument("--as-of-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    as_of_date = parse_as_of_date(args.as_of_date)
    if args.stage == "development":
        audit = run_development_validation(
            as_of_date=as_of_date,
            processed_dir=args.processed_dir,
            output_dir=args.output_dir,
        )
    else:
        audit = run_holdout_evaluation(
            as_of_date=as_of_date,
            processed_dir=args.processed_dir,
            output_dir=args.output_dir,
        )
    print(json.dumps(audit, indent=2, sort_keys=True))
    _print_metrics(args.output_dir, args.stage)


if __name__ == "__main__":
    main()
