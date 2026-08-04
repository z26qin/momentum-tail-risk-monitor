"""Legacy context adapter retained for historical evidence replay."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from src.monitoring.contracts import (
    SCHEMA_VERSION,
    ArtifactProvenance,
    ContextChange,
    PositioningState,
    StructuredMarketContext,
)
from src.monitoring.positioning import (
    build_positioning_state,
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


FEATURE_COLUMNS = (
    "date",
    "mkt_return_504d",
    "mkt_vol_percentile_126d",
    "vix_close",
    "mkt_return_1d",
    "mkt_return_5d",
    "mkt_return_20d",
    "mom_return_21d",
    "mom_return_63d",
    "mom_drawdown_252d",
    "mom_mkt_beta_126d",
    "mom_mkt_corr_126d",
    "beta_change_21d",
)
CHANGE_METRICS = (
    "market_return_504d",
    "market_volatility_percentile_126d",
    "market_return_5d",
    "momentum_return_21d",
    "momentum_drawdown_252d",
    "loser_minus_winner_return_5d",
    "beta_change_21d",
    "positioning_proxy_percentile",
)


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


def _optional_float(value: object) -> float | None:
    if pd.isna(value):
        return None
    result = float(value)
    if not math.isfinite(result):
        return None
    return result


def _compounded_return(values: pd.Series, window: int) -> float | None:
    trailing = values.tail(window)
    if len(trailing) != window or trailing.isna().any():
        return None
    if trailing.le(-1.0).any():
        raise ValueError("Leg return cannot be less than or equal to -1")
    return float(np.expm1(np.log1p(trailing.astype(float)).sum()))


def _leg_metrics(
    frame: pd.DataFrame,
    *,
    as_of_date: pd.Timestamp,
) -> dict[str, float | None]:
    history = frame.loc[frame["date"].le(as_of_date)].sort_values("date")
    if history.empty or pd.Timestamp(history.iloc[-1]["date"]) != as_of_date:
        raise ValueError(
            f"Momentum legs do not contain {iso_date(as_of_date)}"
        )
    winner = history["winner_leg_return"]
    loser = history["loser_leg_return"]
    winner_5d = _compounded_return(winner, 5)
    winner_20d = _compounded_return(winner, 20)
    loser_5d = _compounded_return(loser, 5)
    loser_20d = _compounded_return(loser, 20)
    winner_vol = (
        float(winner.tail(21).std(ddof=1))
        if len(winner.tail(21)) == 21
        and winner.tail(21).notna().all()
        else None
    )
    loser_vol = (
        float(loser.tail(21).std(ddof=1))
        if len(loser.tail(21)) == 21
        and loser.tail(21).notna().all()
        else None
    )
    return {
        "winner_return_5d": winner_5d,
        "winner_return_20d": winner_20d,
        "loser_return_5d": loser_5d,
        "loser_return_20d": loser_20d,
        "loser_minus_winner_return_5d": (
            None
            if winner_5d is None or loser_5d is None
            else loser_5d - winner_5d
        ),
        "loser_minus_winner_return_20d": (
            None
            if winner_20d is None or loser_20d is None
            else loser_20d - winner_20d
        ),
        "winner_volatility_21d": winner_vol,
        "loser_volatility_21d": loser_vol,
    }


def _feature_metrics(row: pd.Series) -> dict[str, float | None]:
    return {
        "market_return_504d": _optional_float(row["mkt_return_504d"]),
        "market_volatility_percentile_126d": _optional_float(
            row["mkt_vol_percentile_126d"]
        ),
        "vix_close": _optional_float(row["vix_close"]),
        "market_return_1d": _optional_float(row["mkt_return_1d"]),
        "market_return_5d": _optional_float(row["mkt_return_5d"]),
        "market_return_20d": _optional_float(row["mkt_return_20d"]),
        "momentum_return_21d": _optional_float(row["mom_return_21d"]),
        "momentum_return_63d": _optional_float(row["mom_return_63d"]),
        "momentum_drawdown_252d": _optional_float(
            row["mom_drawdown_252d"]
        ),
        "momentum_market_beta_126d": _optional_float(
            row["mom_mkt_beta_126d"]
        ),
        "momentum_market_correlation_126d": _optional_float(
            row["mom_mkt_corr_126d"]
        ),
        "beta_change_21d": _optional_float(row["beta_change_21d"]),
    }


def _context_change(
    metric: str,
    current: float | None,
    previous: float | None,
) -> ContextChange:
    return ContextChange(
        metric=metric,
        current_value=current,
        previous_value=previous,
        delta=(
            None
            if current is None or previous is None
            else current - previous
        ),
    )


def build_structured_market_context(
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    positioning_state: PositioningState | None = None,
    previous_positioning_state: PositioningState | None = None,
) -> StructuredMarketContext:
    """Build current and prior-session facts using only data through the date."""

    as_of_date = pd.Timestamp(as_of_date).normalize()
    features_path = processed_dir / "market_features.parquet"
    legs_path = processed_dir / "momentum_leg_structure.parquet"
    deciles_path = (
        processed_dir / "french_10_momentum_portfolios_daily.parquet"
    )
    features = pd.read_parquet(
        features_path,
        columns=list(FEATURE_COLUMNS),
        filters=[("date", "<=", as_of_date)],
    ).sort_values("date")
    if features.empty or pd.Timestamp(features.iloc[-1]["date"]) != as_of_date:
        raise ValueError(
            f"Market features do not contain {iso_date(as_of_date)}"
        )
    if features["date"].duplicated().any():
        raise ValueError("Market features contain duplicate dates")
    current_row = features.iloc[-1]
    previous_row = features.iloc[-2] if len(features) >= 2 else None
    previous_date = (
        pd.Timestamp(previous_row["date"]) if previous_row is not None else None
    )

    legs = pd.read_parquet(
        legs_path,
        columns=["date", "winner_leg_return", "loser_leg_return"],
        filters=[("date", "<=", as_of_date)],
    ).sort_values("date")
    current_values = {
        **_feature_metrics(current_row),
        **_leg_metrics(legs, as_of_date=as_of_date),
    }
    previous_values: dict[str, float | None] = {}
    if previous_row is not None and previous_date is not None:
        previous_values = {
            **_feature_metrics(previous_row),
            **_leg_metrics(legs, as_of_date=previous_date),
        }

    current_positioning = positioning_state or build_positioning_state(
        as_of_date=as_of_date,
        processed_dir=processed_dir,
    )
    if current_positioning.as_of_date != iso_date(as_of_date):
        raise ValueError("Positioning state does not match the context date")
    previous_positioning = previous_positioning_state
    if previous_positioning is None and previous_date is not None:
        previous_positioning = build_positioning_state(
            as_of_date=previous_date,
            processed_dir=processed_dir,
        )
    current_values["positioning_proxy_percentile"] = (
        current_positioning.historical_percentile
    )
    previous_values["positioning_proxy_percentile"] = (
        None
        if previous_positioning is None
        else previous_positioning.historical_percentile
    )

    changes = tuple(
        _context_change(
            metric,
            current_values.get(metric),
            previous_values.get(metric),
        )
        for metric in CHANGE_METRICS
    )
    return StructuredMarketContext(
        schema_version=SCHEMA_VERSION,
        as_of_date=iso_date(as_of_date),
        as_of_timestamp=assessment_timestamp(as_of_date),
        previous_as_of_date=(
            None if previous_date is None else iso_date(previous_date)
        ),
        market_return_504d=current_values["market_return_504d"],
        market_volatility_percentile_126d=current_values[
            "market_volatility_percentile_126d"
        ],
        vix_close=current_values["vix_close"],
        market_return_1d=current_values["market_return_1d"],
        market_return_5d=current_values["market_return_5d"],
        market_return_20d=current_values["market_return_20d"],
        momentum_return_21d=current_values["momentum_return_21d"],
        momentum_return_63d=current_values["momentum_return_63d"],
        momentum_drawdown_252d=current_values[
            "momentum_drawdown_252d"
        ],
        winner_return_5d=current_values["winner_return_5d"],
        winner_return_20d=current_values["winner_return_20d"],
        loser_return_5d=current_values["loser_return_5d"],
        loser_return_20d=current_values["loser_return_20d"],
        loser_minus_winner_return_5d=current_values[
            "loser_minus_winner_return_5d"
        ],
        loser_minus_winner_return_20d=current_values[
            "loser_minus_winner_return_20d"
        ],
        winner_volatility_21d=current_values["winner_volatility_21d"],
        loser_volatility_21d=current_values["loser_volatility_21d"],
        momentum_market_beta_126d=current_values[
            "momentum_market_beta_126d"
        ],
        momentum_market_correlation_126d=current_values[
            "momentum_market_correlation_126d"
        ],
        beta_change_21d=current_values["beta_change_21d"],
        positioning_proxy_name=current_positioning.proxy_name,
        positioning_proxy_percentile=(
            current_positioning.historical_percentile
        ),
        positioning_is_observed=(
            current_positioning.is_observed_positioning
        ),
        changes=changes,
        data_quality_flags=(
            "structured_context_contains_descriptive_facts_not_a_probability",
            "same_day_market_values_use_post_close_assessment_convention",
            "positioning_value_is_a_return_dispersion_proxy",
            "public_source_snapshots_may_contain_later_vendor_revisions",
        ),
        provenance=(
            _provenance("market_features", features_path),
            _provenance("momentum_leg_structure", legs_path),
            _provenance("momentum_decile_returns", deciles_path),
        ),
    )


def run_market_context(
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[StructuredMarketContext, Path]:
    context = build_structured_market_context(
        as_of_date=as_of_date,
        processed_dir=processed_dir,
    )
    path = (
        output_dir
        / "debug"
        / f"structured_context_{context.as_of_date}.json"
    )
    write_json(path, context.to_dict())
    return context, path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    context, path = run_market_context(
        as_of_date=parse_as_of_date(args.as_of_date),
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(context.to_dict(), indent=2, sort_keys=True))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
