"""Reconstruct momentum legs and the decile-based formation spread."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    iso_date,
    write_json,
    write_parquet,
)


OUTPUT_FILENAME = "momentum_leg_structure.parquet"


def reconstruct_momentum_legs(
    size_momentum: pd.DataFrame,
    published_momentum: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, float | int | str]]:
    """Reconstruct winner/loser legs and validate against published UMD."""

    required = {"date", "small_lo", "small_hi", "big_lo", "big_hi"}
    missing = required.difference(size_momentum.columns)
    if missing:
        raise ValueError(f"Six-portfolio input missing columns: {sorted(missing)}")
    if not {"date", "umd_return"}.issubset(published_momentum.columns):
        raise ValueError("Published momentum input must contain date and umd_return")

    result = size_momentum.loc[:, sorted(required)].merge(
        published_momentum.loc[:, ["date", "umd_return"]],
        on="date",
        how="inner",
        validate="one_to_one",
    )
    result["winner_leg_return"] = 0.5 * (
        result["small_hi"] + result["big_hi"]
    )
    result["loser_leg_return"] = 0.5 * (
        result["small_lo"] + result["big_lo"]
    )
    result["reconstructed_umd_return"] = (
        result["winner_leg_return"] - result["loser_leg_return"]
    )
    result["umd_reconstruction_residual"] = (
        result["reconstructed_umd_return"] - result["umd_return"]
    )
    result = result[
        [
            "date",
            "winner_leg_return",
            "loser_leg_return",
            "reconstructed_umd_return",
            "umd_return",
            "umd_reconstruction_residual",
        ]
    ]

    complete = result.dropna(
        subset=["reconstructed_umd_return", "umd_return"]
    ).copy()
    residual = complete["umd_reconstruction_residual"]
    stats: dict[str, float | int | str] = {
        "rows": int(len(complete)),
        "first_observation": iso_date(complete["date"].iloc[0]),
        "last_observation": iso_date(complete["date"].iloc[-1]),
        "correlation": float(
            complete["reconstructed_umd_return"].corr(complete["umd_return"])
        ),
        "mean_residual": float(residual.mean()),
        "residual_standard_deviation": float(residual.std(ddof=0)),
        "mean_absolute_residual": float(residual.abs().mean()),
        "root_mean_squared_residual": float(np.sqrt(np.mean(np.square(residual)))),
        "max_absolute_residual": float(residual.abs().max()),
    }
    if stats["correlation"] < 0.9999 or stats["max_absolute_residual"] > 0.00011:
        raise ValueError(
            "UMD reconstruction failed tolerance: "
            f"correlation={stats['correlation']:.8f}, "
            f"max_abs_residual={stats['max_absolute_residual']:.8f}"
        )
    return result, stats


def formation_spread(
    deciles: pd.DataFrame,
    *,
    lookback: int = 252,
    skip: int = 21,
) -> pd.DataFrame:
    """Return D10-minus-D1 compounded trailing performance with a skip."""

    required = {"date", "decile_1", "decile_10"}
    missing = required.difference(deciles.columns)
    if missing:
        raise ValueError(f"Decile input missing columns: {sorted(missing)}")

    ordered = deciles.sort_values("date").copy()
    if ordered["date"].duplicated().any():
        raise ValueError("Duplicate dates in decile input")

    def compound(values: np.ndarray) -> float:
        return float(np.prod(1.0 + values) - 1.0)

    shifted = ordered[["decile_1", "decile_10"]].shift(skip)
    low = shifted["decile_1"].rolling(lookback, min_periods=lookback).apply(
        compound, raw=True
    )
    high = shifted["decile_10"].rolling(lookback, min_periods=lookback).apply(
        compound, raw=True
    )
    return pd.DataFrame(
        {
            "date": ordered["date"],
            "formation_spread": high - low,
        }
    )


def run_leg_pipeline(
    *,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, object]:
    """Build leg structure and formation spread from processed French tables."""

    momentum = pd.read_parquet(
        processed_dir / "french_momentum_factor_daily.parquet"
    )
    portfolios = pd.read_parquet(
        processed_dir / "french_6_size_momentum_portfolios_daily.parquet"
    )
    deciles = pd.read_parquet(
        processed_dir / "french_10_momentum_portfolios_daily.parquet"
    )

    legs, tracking = reconstruct_momentum_legs(portfolios, momentum)
    spread = formation_spread(deciles)
    output = legs.merge(spread, on="date", how="left", validate="one_to_one")
    output_path = processed_dir / OUTPUT_FILENAME
    write_parquet(output, output_path)

    usable_spread = output.loc[output["formation_spread"].notna(), "date"]
    report: dict[str, object] = {
        "tracking": tracking,
        "formation_spread": {
            "formula": (
                "compound(decile_10, 252 trading observations, shifted 21) "
                "- compound(decile_1, same window)"
            ),
            "lookback_trading_days": 252,
            "skip_recent_trading_days": 21,
            "first_usable_date": (
                iso_date(usable_spread.iloc[0]) if not usable_spread.empty else None
            ),
            "usable_rows": int(output["formation_spread"].notna().sum()),
        },
        "processed_path": str(output_path),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "task1_leg_audit.json", report)
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    report = run_leg_pipeline(
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

