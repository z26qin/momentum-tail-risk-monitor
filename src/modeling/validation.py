"""Build purged expanding walk-forward splits and enforce episode gates."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from src.features.labels import HORIZONS
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    iso_date,
    parse_as_of_date,
    write_json,
)


INITIAL_TRAIN_YEARS = 10
TEST_BLOCK_YEARS = 6
STEP_YEARS = 6
HOLDOUT_YEARS = 3
MINIMUM_TEST_EPISODES = 5


@dataclass(frozen=True)
class PurgedSplit:
    """Indices and nominal boundaries for one purged validation split."""

    split_id: str
    split_kind: str
    nominal_test_start: pd.Timestamp
    nominal_test_end: pd.Timestamp
    train_index: pd.Index
    test_index: pd.Index
    purged_index: pd.Index


class PurgedExpandingWalkForward:
    """Generate complete, non-overlapping development blocks.

    Training starts at ``model_start`` and expands. Test windows are exactly
    ``test_block_years`` calendar years and advance by ``step_years``. A
    development block is emitted only when its full nominal window ends no
    later than ``development_end``.
    """

    def __init__(
        self,
        *,
        initial_train_years: int = INITIAL_TRAIN_YEARS,
        test_block_years: int = TEST_BLOCK_YEARS,
        step_years: int = STEP_YEARS,
    ) -> None:
        if min(initial_train_years, test_block_years, step_years) <= 0:
            raise ValueError("All split durations must be positive")
        self.initial_train_years = initial_train_years
        self.test_block_years = test_block_years
        self.step_years = step_years

    def split(
        self,
        frame: pd.DataFrame,
        *,
        model_start: pd.Timestamp,
        development_end: pd.Timestamp,
    ) -> Iterator[PurgedSplit]:
        """Yield development splits after purging overlapping label windows."""

        _validate_split_frame(frame)
        nominal_test_start = model_start + pd.DateOffset(
            years=self.initial_train_years
        )
        split_number = 0

        while True:
            nominal_test_end = nominal_test_start + pd.DateOffset(
                years=self.test_block_years
            )
            if nominal_test_end > development_end:
                break

            test_mask = frame["date"].ge(nominal_test_start) & frame["date"].lt(
                nominal_test_end
            )
            test_index = frame.index[test_mask]
            if len(test_index) == 0:
                raise ValueError(
                    f"No observations in nominal test window "
                    f"{iso_date(nominal_test_start)} to "
                    f"{iso_date(nominal_test_end)}"
                )
            actual_test_start = frame.loc[test_index, "date"].min()

            candidate_train_mask = (
                frame["date"].ge(model_start)
                & frame["date"].lt(actual_test_start)
            )
            purge_mask = candidate_train_mask & frame["label_end_date"].ge(
                actual_test_start
            )
            train_mask = candidate_train_mask & ~purge_mask

            split = PurgedSplit(
                split_id=f"dev_{split_number:02d}",
                split_kind="development",
                nominal_test_start=nominal_test_start,
                nominal_test_end=nominal_test_end,
                train_index=frame.index[train_mask],
                test_index=test_index,
                purged_index=frame.index[purge_mask],
            )
            _assert_temporal_separation(frame, split)
            yield split

            nominal_test_start += pd.DateOffset(years=self.step_years)
            split_number += 1


def _validate_split_frame(frame: pd.DataFrame) -> None:
    required = {
        "date",
        "label_end_date",
        "event_episode_id",
        "event",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Split input missing columns: {sorted(missing)}")
    if frame["date"].duplicated().any():
        raise ValueError("Split input contains duplicate assessment dates")
    if not frame["date"].is_monotonic_increasing:
        raise ValueError("Split input dates must be sorted")
    if frame[["date", "label_end_date", "event"]].isna().any().any():
        raise ValueError("Split input must contain only mature, valid labels")


def _assert_temporal_separation(
    frame: pd.DataFrame,
    split: PurgedSplit,
) -> None:
    if len(split.train_index) == 0 or len(split.test_index) == 0:
        raise ValueError(f"{split.split_id} has an empty train or test set")
    train = frame.loc[split.train_index]
    test = frame.loc[split.test_index]
    test_start = test["date"].min()
    if train["date"].max() >= test_start:
        raise AssertionError(f"{split.split_id} has train/test date overlap")
    if train["label_end_date"].max() >= test_start:
        raise AssertionError(f"{split.split_id} has label-window overlap")


def make_purged_holdout(
    frame: pd.DataFrame,
    *,
    model_start: pd.Timestamp,
    holdout_start: pd.Timestamp,
    as_of_date: pd.Timestamp,
) -> PurgedSplit:
    """Construct the final holdout after development choices are frozen."""

    _validate_split_frame(frame)
    test_mask = frame["date"].ge(holdout_start) & frame["date"].le(as_of_date)
    test_index = frame.index[test_mask]
    if len(test_index) == 0:
        raise ValueError("The requested final holdout has no valid labels")
    actual_test_start = frame.loc[test_index, "date"].min()
    candidate_train_mask = (
        frame["date"].ge(model_start) & frame["date"].lt(actual_test_start)
    )
    purge_mask = candidate_train_mask & frame["label_end_date"].ge(
        actual_test_start
    )
    split = PurgedSplit(
        split_id="holdout",
        split_kind="holdout",
        nominal_test_start=holdout_start,
        nominal_test_end=as_of_date + pd.Timedelta(days=1),
        train_index=frame.index[candidate_train_mask & ~purge_mask],
        test_index=test_index,
        purged_index=frame.index[purge_mask],
    )
    _assert_temporal_separation(frame, split)
    return split


def _episode_count(frame: pd.DataFrame) -> int:
    event_rows = frame.loc[frame["event"].astype(bool)]
    return int(event_rows["event_episode_id"].nunique())


def _manifest_row(
    frame: pd.DataFrame,
    split: PurgedSplit,
    *,
    horizon: int,
) -> dict[str, Any]:
    train = frame.loc[split.train_index]
    test = frame.loc[split.test_index]
    purged_rows = len(split.purged_index)
    test_episode_count = _episode_count(test)
    return {
        "split_id": split.split_id,
        "split_kind": split.split_kind,
        "horizon_days": horizon,
        "nominal_test_start": iso_date(split.nominal_test_start),
        "nominal_test_end_exclusive": iso_date(split.nominal_test_end),
        "train_start": iso_date(train["date"].min()),
        "train_end": iso_date(train["date"].max()),
        "test_start": iso_date(test["date"].min()),
        "test_end": iso_date(test["date"].max()),
        "label_cutoff_date": iso_date(test["date"].min()),
        "train_rows_before_purge": int(len(train) + purged_rows),
        "purged_rows": int(purged_rows),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "train_event_days": int(train["event"].sum()),
        "test_event_days": int(test["event"].sum()),
        "train_episode_count": _episode_count(train),
        "test_episode_count": test_episode_count,
        "minimum_test_episodes_required": MINIMUM_TEST_EPISODES,
        "episode_gate_passed": test_episode_count >= MINIMUM_TEST_EPISODES,
    }


def _load_horizon_frame(
    *,
    processed_dir: Path,
    horizon: int,
    model_start: pd.Timestamp,
    development_end: pd.Timestamp,
) -> pd.DataFrame:
    labels = pd.read_parquet(
        processed_dir / f"momentum_labels_h{horizon}.parquet",
        filters=[("date", "<", development_end)],
    )
    label_column = f"mom_tail_loss_{horizon}"
    frame = labels.loc[
        labels["date"].ge(model_start)
        & labels[label_column].notna(),
        [
            "date",
            "label_end_date",
            label_column,
            "event_episode_id",
        ],
    ].copy()
    frame.rename(columns={label_column: "event"}, inplace=True)
    frame["event"] = frame["event"].astype(bool)
    frame.reset_index(drop=True, inplace=True)
    _validate_split_frame(frame)
    return frame


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary_path, index=False, lineterminator="\n")
    temporary_path.replace(path)


def build_split_manifest(
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    """Write the split manifest and return the pre-model episode audit."""

    feature_audit_path = output_dir / "task3_feature_audit.json"
    feature_audit = json.loads(feature_audit_path.read_text(encoding="utf-8"))
    model_start = pd.Timestamp(feature_audit["model_sample_start"])
    holdout_start = as_of_date - pd.DateOffset(years=HOLDOUT_YEARS)

    splitter = PurgedExpandingWalkForward()
    manifest_rows: list[dict[str, Any]] = []

    for horizon in HORIZONS:
        frame = _load_horizon_frame(
            processed_dir=processed_dir,
            horizon=horizon,
            model_start=model_start,
            development_end=holdout_start,
        )
        for split in splitter.split(
            frame,
            model_start=model_start,
            development_end=holdout_start,
        ):
            manifest_rows.append(
                _manifest_row(frame, split, horizon=horizon)
            )

    manifest = pd.DataFrame(manifest_rows)
    manifest_path = output_dir / "split_manifest.csv"
    _write_csv(manifest, manifest_path)

    development = manifest.loc[manifest["split_kind"].eq("development")]
    failures = development.loc[~development["episode_gate_passed"]]
    audit = {
        "as_of_date": iso_date(as_of_date),
        "model_sample_start": iso_date(model_start),
        "holdout_nominal_start": iso_date(holdout_start),
        "holdout_years": HOLDOUT_YEARS,
        "initial_train_years": INITIAL_TRAIN_YEARS,
        "test_block_years": TEST_BLOCK_YEARS,
        "step_years": STEP_YEARS,
        "minimum_test_episodes": MINIMUM_TEST_EPISODES,
        "development_split_count_per_horizon": {
            str(horizon): int(
                (
                    development["horizon_days"].eq(horizon)
                ).sum()
            )
            for horizon in HORIZONS
        },
        "episode_gate_passed": failures.empty,
        "failed_development_splits": failures[
            [
                "split_id",
                "horizon_days",
                "test_start",
                "test_end",
                "test_event_days",
                "test_episode_count",
            ]
        ].to_dict(orient="records"),
        "holdout_status": (
            "quarantined: holdout labels and features are not loaded, "
            "counted, modeled, or scored by this gate"
        ),
        "manifest_path": str(manifest_path),
        "model_fitting_permitted": failures.empty,
    }
    write_json(output_dir / "task4_split_gate.json", audit)
    return audit


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    audit = build_split_manifest(
        as_of_date=parse_as_of_date(args.as_of_date),
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(audit, indent=2, sort_keys=True))
    if not audit["episode_gate_passed"]:
        raise SystemExit(
            "Task 4 halted: at least one development fold has fewer than "
            f"{MINIMUM_TEST_EPISODES} test episodes."
        )


if __name__ == "__main__":
    main()
