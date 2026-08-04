"""Legacy return-dispersion proxy; active MVP positioning reads the FINRA panel."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.monitoring.contracts import (
    SCHEMA_VERSION,
    ArtifactProvenance,
    PositioningState,
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


PROXY_NAME = "momentum_decile_return_dispersion_21d"
WINDOW = 21
MINIMUM_HISTORY = 252
DECILE_COLUMNS = tuple(f"decile_{number}" for number in range(1, 11))


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


def build_dispersion_history(deciles: pd.DataFrame) -> pd.DataFrame:
    """Calculate trailing decile returns and their cross-sectional dispersion."""

    required = {"date", *DECILE_COLUMNS}
    missing = required.difference(deciles.columns)
    if missing:
        raise ValueError(f"Decile input missing columns: {sorted(missing)}")
    ordered = deciles.loc[:, ["date", *DECILE_COLUMNS]].sort_values("date")
    if ordered["date"].duplicated().any():
        raise ValueError("Decile input contains duplicate dates")
    if ordered.loc[:, DECILE_COLUMNS].le(-1.0).any().any():
        raise ValueError("Decile returns cannot be less than or equal to -1")

    numeric = ordered.loc[:, DECILE_COLUMNS].astype(float)
    compounded = np.expm1(
        np.log1p(numeric).rolling(WINDOW, min_periods=WINDOW).sum()
    )
    complete = compounded.notna().all(axis=1)
    dispersion = compounded.std(axis=1, ddof=0).where(complete)
    return pd.DataFrame(
        {
            "date": ordered["date"].to_numpy(),
            PROXY_NAME: dispersion.to_numpy(),
        }
    )


def _interpretation(percentile: float) -> str:
    if percentile >= 0.90:
        level = "unusually elevated"
    elif percentile >= 0.75:
        level = "elevated"
    elif percentile >= 0.50:
        level = "moderate"
    else:
        level = "subdued"
    return (
        f"Trailing momentum-decile return dispersion is {level} relative to "
        "its point-in-time history. Wider decile separation can indicate a "
        "stretched factor structure vulnerable to rotation, but it does not "
        "measure investor holdings or leverage."
    )


def build_positioning_state(
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
) -> PositioningState:
    """Build the proxy using only decile returns dated through the assessment."""

    as_of_date = pd.Timestamp(as_of_date).normalize()
    source_path = (
        processed_dir / "french_10_momentum_portfolios_daily.parquet"
    )
    deciles = pd.read_parquet(
        source_path,
        columns=["date", *DECILE_COLUMNS],
        filters=[("date", "<=", as_of_date)],
    )
    if deciles.empty or pd.Timestamp(deciles["date"].max()) != as_of_date:
        raise ValueError("Decile data do not contain the selected as-of date")
    history = build_dispersion_history(deciles)
    valid = history.loc[
        history["date"].le(as_of_date) & history[PROXY_NAME].notna()
    ].sort_values("date")
    if len(valid) < MINIMUM_HISTORY:
        raise ValueError(
            f"Proxy requires at least {MINIMUM_HISTORY} valid historical observations"
        )
    current_rows = valid.loc[valid["date"].eq(as_of_date)]
    if len(current_rows) != 1:
        raise ValueError(
            f"Expected one proxy row on {iso_date(as_of_date)}, "
            f"found {len(current_rows)}"
        )
    value = float(current_rows.iloc[0][PROXY_NAME])
    percentile = float(valid[PROXY_NAME].le(value).mean())

    return PositioningState(
        schema_version=SCHEMA_VERSION,
        as_of_date=iso_date(as_of_date),
        as_of_timestamp=assessment_timestamp(as_of_date),
        proxy_name=PROXY_NAME,
        value=value,
        historical_percentile=percentile,
        historical_observation_count=int(len(valid)),
        construction_window_trading_days=WINDOW,
        construction=(
            "Population standard deviation across the ten trailing 21-trading-"
            "day compounded value-weighted momentum-decile returns, followed "
            "by a weak expanding percentile through the assessment date."
        ),
        interpretation=_interpretation(percentile),
        is_observed_positioning=False,
        limitations=(
            "This is return dispersion, not observed investor positioning, "
            "ownership concentration, flow, leverage, or financing data.",
            "High dispersion can reflect broad volatility, sector composition, "
            "or return outliers rather than crowding.",
            "Public portfolio-return histories may be revised after publication.",
        ),
        production_replacements=(
            "prime-broker factor crowding and leverage",
            "institutional holdings and factor exposure",
            "fund flows, short interest, borrow, and financing conditions",
        ),
        data_quality_flags=(
            "calculated_return_proxy_not_observed_positioning",
            "same_day_source_publication_timestamp_not_historically_verified",
            "public_source_snapshot_may_contain_later_vendor_revisions",
        ),
        provenance=(
            _provenance("ten_momentum_decile_returns", source_path),
        ),
    )


def run_positioning_state(
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[PositioningState, Path]:
    state = build_positioning_state(
        as_of_date=as_of_date,
        processed_dir=processed_dir,
    )
    path = (
        output_dir
        / "debug"
        / f"positioning_state_{state.as_of_date}.json"
    )
    write_json(path, state.to_dict())
    return state, path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    state, path = run_positioning_state(
        as_of_date=parse_as_of_date(args.as_of_date),
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(state.to_dict(), indent=2, sort_keys=True))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
