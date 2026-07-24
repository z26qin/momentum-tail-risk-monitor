"""Read-only integrity audit for completed Task 4 artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import nbformat
import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)

from src.modeling.baselines import specification_hash
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    REPO_ROOT,
    sha256_file,
    write_json,
)


ARTIFACTS = (
    "split_manifest.csv",
    "task4_split_gate.json",
    "development_manifest.csv",
    "holdout_manifest.csv",
    "development_predictions.parquet",
    "holdout_predictions.parquet",
    "baseline_predictions.parquet",
    "development_fold_metrics.csv",
    "baseline_metrics.csv",
    "calibration_table.csv",
    "model_coefficients.csv",
    "preprocessing_statistics.csv",
    "task4_development_audit.json",
    "task4_holdout_audit.json",
)


def _assert_metrics(
    predictions: pd.DataFrame,
    metrics: pd.DataFrame,
) -> int:
    checks = 0
    for (scope, horizon, baseline), group in predictions.groupby(
        ["scope", "horizon_days", "baseline"], sort=True
    ):
        stored = metrics.loc[
            metrics["scope"].eq(scope)
            & metrics["horizon_days"].eq(horizon)
            & metrics["baseline"].eq(baseline)
        ]
        if len(stored) != 1:
            raise AssertionError(
                f"Expected one metric row for {scope}/{horizon}/{baseline}"
            )
        row = stored.iloc[0]
        event = group["event"].astype(int).to_numpy()
        probability = group["predicted_probability"].to_numpy(dtype=float)
        recomputed = {
            "log_loss": log_loss(event, probability),
            "brier_score": brier_score_loss(event, probability),
            "pr_auc": average_precision_score(event, probability),
            "roc_auc": roc_auc_score(event, probability),
        }
        for name, value in recomputed.items():
            if not np.isclose(row[name], value, rtol=1e-10, atol=1e-12):
                raise AssertionError(
                    f"{name} mismatch for {scope}/{horizon}/{baseline}"
                )
            checks += 1
        if int(row["rows"]) != len(group):
            raise AssertionError("Metric row count mismatch")
        if int(row["event_days"]) != int(event.sum()):
            raise AssertionError("Metric event-day count mismatch")
    return checks


def _assert_calibration_totals(
    predictions: pd.DataFrame,
    calibration: pd.DataFrame,
) -> int:
    checks = 0
    for (scope, horizon, baseline), group in predictions.groupby(
        ["scope", "horizon_days", "baseline"], sort=True
    ):
        buckets = calibration.loc[
            calibration["scope"].eq(scope)
            & calibration["horizon_days"].eq(horizon)
            & calibration["baseline"].eq(baseline)
        ]
        if int(buckets["rows"].sum()) != len(group):
            raise AssertionError("Calibration bucket row total mismatch")
        if int(buckets["event_days"].sum()) != int(group["event"].sum()):
            raise AssertionError("Calibration bucket event total mismatch")
        checks += 2
    return checks


def _assert_notebook(notebook_path: Path) -> dict[str, int]:
    notebook = nbformat.read(notebook_path, as_version=4)
    nbformat.validate(notebook)
    if len(notebook.cells) > 15:
        raise AssertionError("Task 4 notebook exceeds 15 cells")
    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    if any(cell.execution_count is None for cell in code_cells):
        raise AssertionError("Notebook contains an unexecuted code cell")
    errors = [
        output
        for cell in code_cells
        for output in cell.outputs
        if output.output_type == "error"
    ]
    if errors:
        raise AssertionError("Notebook contains an execution error")
    return {
        "cells": len(notebook.cells),
        "code_cells": len(code_cells),
        "output_blocks": sum(len(cell.outputs) for cell in code_cells),
    }


def run_task4_audit(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Validate saved outputs without fitting or predicting."""

    development_audit = json.loads(
        (output_dir / "task4_development_audit.json").read_text(
            encoding="utf-8"
        )
    )
    holdout_audit = json.loads(
        (output_dir / "task4_holdout_audit.json").read_text(encoding="utf-8")
    )
    expected_specification_hash = specification_hash()
    if development_audit["specification_hash"] != expected_specification_hash:
        raise AssertionError("Development specification hash changed")
    if holdout_audit["specification_hash"] != expected_specification_hash:
        raise AssertionError("Holdout specification hash changed")
    if not development_audit["specification_frozen_before_holdout"]:
        raise AssertionError("Development specification was not frozen")

    development_manifest = pd.read_csv(
        output_dir / "development_manifest.csv",
        parse_dates=["train_start", "train_end", "test_start", "test_end"],
    )
    holdout_manifest = pd.read_csv(
        output_dir / "holdout_manifest.csv",
        parse_dates=["train_start", "train_end", "test_start", "test_end"],
    )
    manifests = pd.concat(
        [development_manifest, holdout_manifest], ignore_index=True
    )
    if not (manifests["train_end"] < manifests["test_start"]).all():
        raise AssertionError("A split violates strict train/test ordering")
    if not (
        manifests.loc[manifests["horizon_days"].eq(5), "purged_rows"].eq(5)
    ).all():
        raise AssertionError("A 5-day split has the wrong purge count")
    if not (
        manifests.loc[manifests["horizon_days"].eq(20), "purged_rows"].eq(20)
    ).all():
        raise AssertionError("A 20-day split has the wrong purge count")
    if development_manifest["test_episode_count"].min() < 5:
        raise AssertionError("Development episode gate no longer passes")

    predictions = pd.read_parquet(
        output_dir / "baseline_predictions.parquet"
    )
    if predictions.duplicated(
        ["scope", "horizon_days", "baseline", "date"]
    ).any():
        raise AssertionError("Prediction output contains duplicate keys")
    if not predictions["predicted_probability"].between(
        0.0, 1.0, inclusive="neither"
    ).all():
        raise AssertionError("A predicted probability is outside (0, 1)")
    holdout_start = holdout_manifest["test_start"].min()
    if not predictions.loc[
        predictions["scope"].eq("development"), "date"
    ].lt(holdout_start).all():
        raise AssertionError("Development predictions enter the holdout")
    if not predictions.loc[
        predictions["scope"].eq("holdout"), "date"
    ].ge(holdout_start).all():
        raise AssertionError("Holdout predictions precede the holdout")
    for _, group in predictions.loc[
        predictions["baseline"].eq("B0")
    ].groupby(["scope", "horizon_days", "split_id"]):
        if group["predicted_probability"].nunique() != 1:
            raise AssertionError("B0 is not constant within a split")

    metrics = pd.read_csv(output_dir / "baseline_metrics.csv")
    metric_checks = _assert_metrics(predictions, metrics)
    calibration_checks = _assert_calibration_totals(
        predictions,
        pd.read_csv(output_dir / "calibration_table.csv"),
    )

    preprocessing = pd.read_csv(
        output_dir / "development_preprocessing.csv"
    )
    vix_medians = preprocessing.loc[
        preprocessing["baseline"].eq("B2")
        & preprocessing["horizon_days"].eq(5)
        & preprocessing["feature"].eq("vix_close"),
        "imputer_median",
    ]
    if vix_medians.nunique() != len(vix_medians):
        raise AssertionError("Fold-specific VIX medians are not distinct")

    notebook_path = repo_root / "notebooks" / "01_baseline_eda.ipynb"
    notebook_audit = _assert_notebook(notebook_path)
    artifact_hashes = {
        name: sha256_file(output_dir / name) for name in ARTIFACTS
    }
    artifact_hashes["notebooks/01_baseline_eda.ipynb"] = sha256_file(
        notebook_path
    )

    audit = {
        "audit_mode": "read-only: no fit or predict call",
        "specification_hash": expected_specification_hash,
        "development_splits": int(len(development_manifest)),
        "minimum_development_test_episodes": int(
            development_manifest["test_episode_count"].min()
        ),
        "holdout_splits": int(len(holdout_manifest)),
        "prediction_rows": int(len(predictions)),
        "probability_minimum": float(
            predictions["predicted_probability"].min()
        ),
        "probability_maximum": float(
            predictions["predicted_probability"].max()
        ),
        "independently_recomputed_metrics": metric_checks,
        "calibration_total_checks": calibration_checks,
        "fold_specific_vix_medians": [
            float(value) for value in vix_medians
        ],
        "notebook": notebook_audit,
        "artifact_sha256": artifact_hashes,
        "checks_passed": True,
    }
    write_json(output_dir / "task4_validation_audit.json", audit)
    return audit


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    audit = run_task4_audit(
        output_dir=args.output_dir,
        repo_root=args.repo_root,
    )
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
