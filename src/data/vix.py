"""Download FRED VIXCLS and align it to the published momentum calendar."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    DEFAULT_RAW_DIR,
    cache_public_source,
    iso_date,
    parse_as_of_date,
    rebuild_raw_manifest,
    update_raw_metadata,
    write_json,
    write_parquet,
)


FRED_VIX_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS"
RAW_FILENAME = "VIXCLS.csv"
PROCESSED_FILENAME = "vix_aligned.parquet"
SENSITIVITY_FILENAME = "vix_aligned_fill_1d_sensitivity.parquet"


def parse_fred_vix(path: Path) -> pd.DataFrame:
    """Parse the two supported official FRED CSV header variants."""

    raw = pd.read_csv(path, dtype=str)
    if set(("observation_date", "VIXCLS")).issubset(raw.columns):
        date_column, value_column = "observation_date", "VIXCLS"
    elif set(("DATE", "VALUE")).issubset(raw.columns):
        date_column, value_column = "DATE", "VALUE"
    else:
        raise ValueError(
            f"Unexpected FRED VIXCLS columns {list(raw.columns)!r}; "
            "expected observation_date,VIXCLS or DATE,VALUE."
        )

    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(raw[date_column], format="%Y-%m-%d", errors="raise"),
            "vix_close": pd.to_numeric(
                raw[value_column].replace({".": pd.NA, "": pd.NA}),
                errors="coerce",
            ),
        }
    )
    if frame["date"].duplicated().any():
        raise ValueError("Duplicate dates in FRED VIXCLS")
    if not frame["date"].is_monotonic_increasing:
        raise ValueError("FRED VIXCLS dates are not sorted")
    observed = frame["vix_close"].dropna()
    if observed.empty or (observed <= 0).any() or observed.max() >= 200:
        raise ValueError("Implausible VIXCLS magnitude; raw unit must remain index points")
    return frame


def align_vix_to_momentum_calendar(
    vix: pd.DataFrame,
    momentum_calendar: pd.Series,
) -> tuple[pd.DataFrame, list[str], int, int]:
    """Left-align VIX to momentum dates without filling missing observations."""

    calendar = pd.DataFrame(
        {"date": pd.Series(momentum_calendar.drop_duplicates().sort_values())}
    )
    aligned = calendar.merge(vix, on="date", how="left", validate="one_to_one")
    aligned["vix_observation_date_used"] = aligned["date"].where(
        aligned["vix_close"].notna()
    )
    aligned["vix_was_filled"] = False
    aligned["vix_age_trading_days"] = pd.array(
        [0 if observed else pd.NA for observed in aligned["vix_close"].notna()],
        dtype="Int8",
    )
    observed_vix = vix.loc[vix["vix_close"].notna(), "date"]
    if observed_vix.empty:
        raise ValueError("FRED VIXCLS contains no observed values")
    coverage_start = observed_vix.iloc[0]
    coverage_end = observed_vix.iloc[-1]
    within_coverage = aligned["date"].between(coverage_start, coverage_end)
    unexpected_missing_dates = [
        iso_date(value)
        for value in aligned.loc[
            within_coverage & aligned["vix_close"].isna(), "date"
        ]
    ]
    pre_coverage_rows = int((aligned["date"] < coverage_start).sum())
    post_coverage_rows = int((aligned["date"] > coverage_end).sum())
    return (
        aligned,
        unexpected_missing_dates,
        pre_coverage_rows,
        post_coverage_rows,
    )


def one_day_fill_sensitivity(aligned: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Fill only an isolated missing row from the prior observed trading row."""

    result = aligned.copy()
    original_observed = result["vix_close"].notna()
    can_fill = (~original_observed) & original_observed.shift(1, fill_value=False)
    result.loc[can_fill, "vix_close"] = result["vix_close"].shift(1).loc[can_fill]
    result.loc[can_fill, "vix_observation_date_used"] = (
        result["date"].shift(1).loc[can_fill]
    )
    result.loc[can_fill, "vix_was_filled"] = True
    result.loc[can_fill, "vix_age_trading_days"] = 1
    filled_dates = [iso_date(value) for value in result.loc[can_fill, "date"]]
    return result, filled_dates


def _find_offline_source(offline_dir: Path) -> Path:
    candidates = (
        offline_dir / RAW_FILENAME,
        offline_dir / Path(urlparse(FRED_VIX_URL).path).name,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "No offline FRED VIXCLS CSV found. Tried: "
        + ", ".join(str(path) for path in candidates)
    )


def run_vix_pipeline(
    *,
    as_of_date: pd.Timestamp,
    raw_dir: Path = DEFAULT_RAW_DIR,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    offline_dir: Path | None = None,
    force: bool = False,
    write_fill_sensitivity: bool = False,
) -> dict[str, object]:
    """Build the default no-fill VIX table and optional one-day sensitivity."""

    raw_path = raw_dir / RAW_FILENAME
    local_source = (
        _find_offline_source(offline_dir)
        if offline_dir is not None
        else None
    )
    cache_public_source(
        source_key="fred_vixcls",
        source_url=FRED_VIX_URL,
        raw_path=raw_path,
        local_source=local_source,
        force=force,
    )
    full_vix = parse_fred_vix(raw_path)
    vix = full_vix.loc[full_vix["date"] <= as_of_date].copy()

    momentum_path = processed_dir / "french_momentum_factor_daily.parquet"
    if not momentum_path.is_file():
        raise FileNotFoundError(
            f"Momentum calendar missing at {momentum_path}; run src.data.french first."
        )
    momentum = pd.read_parquet(momentum_path, columns=["date"])
    momentum = momentum.loc[momentum["date"] <= as_of_date]
    (
        aligned,
        unexpected_missing_dates,
        pre_coverage_rows,
        post_coverage_rows,
    ) = align_vix_to_momentum_calendar(vix, momentum["date"])

    processed_path = processed_dir / PROCESSED_FILENAME
    write_parquet(aligned, processed_path)

    filled_dates: list[str] = []
    if write_fill_sensitivity:
        sensitivity, filled_dates = one_day_fill_sensitivity(aligned)
        write_parquet(sensitivity, processed_dir / SENSITIVITY_FILENAME)

    raw_metadata = update_raw_metadata(
        raw_path,
        raw_units="VIX index points (not percent; not converted)",
        conversion_applied="none",
        raw_first_observation=iso_date(full_vix["date"].iloc[0]),
        raw_last_observation=iso_date(full_vix["date"].iloc[-1]),
        raw_observation_count=int(len(full_vix)),
        processed_as_of_date=iso_date(as_of_date),
        processed_first_observation=iso_date(aligned["date"].iloc[0]),
        processed_last_observation=iso_date(aligned["date"].iloc[-1]),
        processed_observation_count=int(len(aligned)),
        processed_path=str(processed_path.relative_to(processed_dir.parent.parent)),
        alignment=(
            "left join to momentum trading-date calendar; no weekend/holiday "
            "rows and no fill in the primary output"
        ),
        publication_timing=(
            "FRED labels the series Daily, Close but the current release page "
            "updates the dated close the following morning; exact historical "
            "release timestamps are not supplied in the CSV"
        ),
    )
    manifest = rebuild_raw_manifest(raw_dir)

    report = {
        "as_of_date": iso_date(as_of_date),
        "raw_first_observation": iso_date(full_vix["date"].iloc[0]),
        "raw_last_observation": iso_date(full_vix["date"].iloc[-1]),
        "aligned_first_observation": iso_date(aligned["date"].iloc[0]),
        "aligned_last_observation": iso_date(aligned["date"].iloc[-1]),
        "aligned_rows": int(len(aligned)),
        "observed_rows": int(aligned["vix_close"].notna().sum()),
        "pre_vix_coverage_rows": pre_coverage_rows,
        "post_vix_coverage_rows": post_coverage_rows,
        "unexpected_missing_momentum_dates_within_vix_coverage": (
            unexpected_missing_dates
        ),
        "fill_sensitivity_written": write_fill_sensitivity,
        "filled_dates": filled_dates,
        "sha256": raw_metadata["sha256"],
        "raw_manifest_entries": len(manifest),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "task1_vix_audit.json", report)
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--offline-dir",
        type=Path,
        help="Directory containing the official VIXCLS.csv file.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--write-fill-sensitivity",
        action="store_true",
        help="Also write a separately named max-one-trading-day fill sensitivity.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    report = run_vix_pipeline(
        as_of_date=parse_as_of_date(args.as_of_date),
        raw_dir=args.raw_dir,
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
        offline_dir=args.offline_dir,
        force=args.force,
        write_fill_sensitivity=args.write_fill_sensitivity,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
