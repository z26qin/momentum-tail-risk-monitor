"""Download, parse, audit, and cache the required Ken French daily datasets."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

import numpy as np
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


FRENCH_BASE_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp"
DATE_PATTERN = re.compile(r"^\d{8}$")
MISSING_SENTINELS = {-99.99, -999.0}


@dataclass(frozen=True)
class FrenchSpec:
    key: str
    archive_stem: str
    raw_filename: str
    processed_filename: str
    expected_headers: tuple[str, ...]
    output_columns: tuple[str, ...]
    table_marker: str | None = None
    expected_first_date: str | None = None

    @property
    def source_url(self) -> str:
        return f"{FRENCH_BASE_URL}/{self.archive_stem}_CSV.zip"


SPECS: tuple[FrenchSpec, ...] = (
    FrenchSpec(
        key="french_momentum_factor_daily",
        archive_stem="F-F_Momentum_Factor_daily",
        raw_filename="F-F_Momentum_Factor_daily.zip",
        processed_filename="french_momentum_factor_daily.parquet",
        expected_headers=("Mom",),
        output_columns=("umd_return",),
        expected_first_date="1926-11-03",
    ),
    FrenchSpec(
        key="french_research_factors_daily",
        archive_stem="F-F_Research_Data_Factors_daily",
        raw_filename="F-F_Research_Data_Factors_daily.zip",
        processed_filename="french_research_factors_daily.parquet",
        expected_headers=("Mkt-RF", "RF"),
        output_columns=("mkt_rf", "smb", "hml", "rf"),
        expected_first_date="1926-07-01",
    ),
    FrenchSpec(
        key="french_6_size_momentum_portfolios_daily",
        archive_stem="6_Portfolios_ME_Prior_12_2_Daily",
        raw_filename="6_Portfolios_ME_Prior_12_2_Daily.zip",
        processed_filename="french_6_size_momentum_portfolios_daily.parquet",
        expected_headers=("SMALL LoPRIOR", "BIG HiPRIOR"),
        output_columns=(
            "small_lo",
            "small_mid",
            "small_hi",
            "big_lo",
            "big_mid",
            "big_hi",
        ),
        table_marker="Average Value Weighted Returns -- Daily",
        expected_first_date="1926-11-03",
    ),
    FrenchSpec(
        key="french_10_momentum_portfolios_daily",
        archive_stem="10_Portfolios_Prior_12_2_Daily",
        raw_filename="10_Portfolios_Prior_12_2_Daily.zip",
        processed_filename="french_10_momentum_portfolios_daily.parquet",
        expected_headers=("Lo PRIOR", "Hi PRIOR"),
        output_columns=tuple(f"decile_{number}" for number in range(1, 11)),
        table_marker="Average Value Weighted Returns -- Daily",
        expected_first_date="1926-11-03",
    ),
)


def _normalize_cell(value: str) -> str:
    return " ".join(value.strip().split())


def _read_single_csv_from_zip(path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as archive:
        members = [
            member
            for member in archive.namelist()
            if not member.endswith("/") and member.lower().endswith(".csv")
        ]
        if len(members) != 1:
            raise ValueError(
                f"Expected exactly one CSV in {path.name}; found {members!r}"
            )
        member = members[0]
        payload = archive.read(member)
    return payload.decode("utf-8-sig"), member


def _locate_header(lines: Sequence[str], spec: FrenchSpec) -> int:
    search_start = 0
    if spec.table_marker is not None:
        marker_indices = [
            index
            for index, line in enumerate(lines)
            if spec.table_marker in line
        ]
        if not marker_indices:
            raise ValueError(
                f"Table marker {spec.table_marker!r} missing in {spec.raw_filename}"
            )
        search_start = marker_indices[0] + 1

    for index in range(search_start, len(lines)):
        row = [_normalize_cell(cell) for cell in next(csv.reader([lines[index]]))]
        if not row or row[0] != "":
            continue
        if all(expected in row for expected in spec.expected_headers):
            return index
    raise ValueError(f"Could not locate required header in {spec.raw_filename}")


def parse_french_archive(path: Path, spec: FrenchSpec) -> pd.DataFrame:
    """Parse the selected daily table and convert source percent to decimals."""

    text, _ = _read_single_csv_from_zip(path)
    lines = text.splitlines()
    header_index = _locate_header(lines, spec)
    header = [
        _normalize_cell(cell)
        for cell in next(csv.reader([lines[header_index]]))
    ]
    source_columns = [cell for cell in header[1:] if cell]

    records: list[list[str]] = []
    data_started = False
    for line in lines[header_index + 1 :]:
        row = next(csv.reader([line]))
        first_cell = row[0].strip() if row else ""
        if not DATE_PATTERN.fullmatch(first_cell):
            if data_started:
                break
            continue
        data_started = True
        values = [cell.strip() for cell in row[1 : 1 + len(source_columns)]]
        if len(values) != len(source_columns):
            raise ValueError(f"Malformed row for {first_cell} in {path.name}")
        records.append([first_cell, *values])

    if not records:
        raise ValueError(f"No daily observations parsed from {path.name}")
    if len(source_columns) != len(spec.output_columns):
        raise ValueError(
            f"{path.name} exposed {len(source_columns)} columns; "
            f"expected {len(spec.output_columns)}"
        )

    frame = pd.DataFrame(records, columns=["date", *spec.output_columns])
    frame["date"] = pd.to_datetime(frame["date"], format="%Y%m%d", errors="raise")
    for column in spec.output_columns:
        numeric = pd.to_numeric(frame[column], errors="raise")
        numeric = numeric.mask(numeric.isin(MISSING_SENTINELS))
        frame[column] = numeric / 100.0

    if frame["date"].duplicated().any():
        raise ValueError(f"Duplicate dates in {path.name}")
    if not frame["date"].is_monotonic_increasing:
        raise ValueError(f"Dates are not sorted in {path.name}")
    if spec.expected_first_date and iso_date(frame["date"].iloc[0]) != spec.expected_first_date:
        raise ValueError(
            f"Unexpected first date in {path.name}: "
            f"{iso_date(frame['date'].iloc[0])}"
        )

    finite_values = frame.loc[:, spec.output_columns].to_numpy(dtype=float)
    finite_values = finite_values[np.isfinite(finite_values)]
    if finite_values.size == 0 or np.max(np.abs(finite_values)) >= 1.0:
        raise ValueError(
            f"Implausible post-conversion magnitude in {path.name}; "
            "check percent-to-decimal handling and missing sentinels."
        )
    return frame


def _find_offline_source(offline_dir: Path, spec: FrenchSpec) -> Path:
    candidates = (
        offline_dir / spec.raw_filename,
        offline_dir / Path(urlparse(spec.source_url).path).name,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"No offline archive found for {spec.key}. Tried: "
        + ", ".join(str(path) for path in candidates)
    )


def run_french_pipeline(
    *,
    as_of_date: pd.Timestamp,
    raw_dir: Path = DEFAULT_RAW_DIR,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    offline_dir: Path | None = None,
    force: bool = False,
) -> dict[str, object]:
    """Build all required French processed tables through ``as_of_date``."""

    summaries: dict[str, object] = {}
    for spec in SPECS:
        raw_path = raw_dir / spec.raw_filename
        local_source = (
            _find_offline_source(offline_dir, spec)
            if offline_dir is not None
            else None
        )
        cache_public_source(
            source_key=spec.key,
            source_url=spec.source_url,
            raw_path=raw_path,
            local_source=local_source,
            force=force,
        )
        full_frame = parse_french_archive(raw_path, spec)
        processed = full_frame.loc[full_frame["date"] <= as_of_date].copy()
        if processed.empty:
            raise ValueError(
                f"AS_OF_DATE {iso_date(as_of_date)} predates {spec.key}"
            )

        if spec.key == "french_research_factors_daily":
            processed["mkt_total_return"] = processed["mkt_rf"] + processed["rf"]

        processed_path = processed_dir / spec.processed_filename
        write_parquet(processed, processed_path)
        raw_metadata = update_raw_metadata(
            raw_path,
            archive_member=_read_single_csv_from_zip(raw_path)[1],
            raw_units="percent return",
            conversion_applied="divide numeric observations by 100 to decimal return",
            selected_table=spec.table_marker or "single daily table",
            raw_first_observation=iso_date(full_frame["date"].iloc[0]),
            raw_last_observation=iso_date(full_frame["date"].iloc[-1]),
            raw_observation_count=int(len(full_frame)),
            processed_as_of_date=iso_date(as_of_date),
            processed_first_observation=iso_date(processed["date"].iloc[0]),
            processed_last_observation=iso_date(processed["date"].iloc[-1]),
            processed_observation_count=int(len(processed)),
            processed_path=str(processed_path.relative_to(processed_dir.parent.parent)),
        )
        value_columns = [column for column in processed if column != "date"]
        summaries[spec.key] = {
            "first_observation": iso_date(processed["date"].iloc[0]),
            "last_observation": iso_date(processed["date"].iloc[-1]),
            "rows": int(len(processed)),
            "missing_values": {
                column: int(processed[column].isna().sum())
                for column in value_columns
            },
            "min_decimal": float(processed[value_columns].min().min()),
            "max_decimal": float(processed[value_columns].max().max()),
            "sha256": raw_metadata["sha256"],
            "processed_path": str(processed_path),
        }

    manifest = rebuild_raw_manifest(raw_dir)
    report = {
        "as_of_date": iso_date(as_of_date),
        "datasets": summaries,
        "raw_manifest_entries": len(manifest),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "task1_french_audit.json", report)
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
        help="Directory containing official ZIP files for a network-restricted run.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace cached raw files and their provenance sidecars.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    report = run_french_pipeline(
        as_of_date=parse_as_of_date(args.as_of_date),
        raw_dir=args.raw_dir,
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
        offline_dir=args.offline_dir,
        force=args.force,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
