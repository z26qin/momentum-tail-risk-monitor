"""Minimal deterministic scorecard for momentum crash risk.

The scorecard deliberately exposes only four independent risk decisions:

1. a high-volatility recovery macro gate;
2. the short-underlying minus long beta gap;
3. the long-short portfolio drawdown;
4. unusual short-leg losses while the market is in early recovery.

The richer Phase 1 and Phase 3 histories remain diagnostic inputs.  They are
included as row context rather than repeated as additional alert rows.  All
historical thresholds use observations strictly before the assessment date.
Missing inputs remain unavailable and never become a false trigger.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.regime.market_state import build_regime_history
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    REPO_ROOT,
    atomic_write_bytes,
    iso_date,
    parse_as_of_date,
    write_json,
)


SCORECARD_COLUMNS = (
    "as_of_date",
    "monitor_family",
    "metric",
    "current_value",
    "threshold",
    "threshold_provenance",
    "direction",
    "triggered",
    "severity",
    "status",
    "explanation",
    "context",
    "source_module",
)
SCORECARD_METRICS = (
    "high_volatility_recovery",
    "short_minus_long_beta_gap",
    "portfolio_drawdown",
    "short_loss_in_recovery",
)
THRESHOLD_PROVENANCE = frozenset(
    {"literature", "historical_quantile", "demo_threshold"}
)
DIRECTIONS = frozenset({"greater_than_or_equal", "less_than_or_equal"})
SEVERITIES = frozenset({"normal", "high", "unavailable"})
STATUSES = frozenset({"available", "unavailable"})

RISK_REQUIRED_COLUMNS = {
    "date",
    "long_beta_126d",
    "short_underlying_beta_126d",
    "portfolio_beta_126d",
    "beta_gap_short_minus_long_126d",
    "portfolio_return",
    "portfolio_drawdown",
    "short_contribution",
}
REGIME_REQUIRED_COLUMNS = {
    "date",
    "early_recovery_state",
    "high_volatility_recovery_state",
}


@dataclass(frozen=True)
class ScorecardConfig:
    """Published scorecard thresholds and calibration requirements."""

    historical_min_observations: int = 252
    beta_gap_quantile: float = 0.80
    beta_gap_demo_threshold: float = 0.25
    beta_gap_floor: float = 0.0
    drawdown_window: int = 63
    drawdown_quantile: float = 0.20
    drawdown_demo_threshold: float = -0.20
    drawdown_floor: float = -0.20
    drawdown_ceiling: float = -0.05
    short_loss_window: int = 21
    short_loss_quantile: float = 0.80
    short_loss_demo_threshold: float = 0.10

    def __post_init__(self) -> None:
        if self.historical_min_observations < 1:
            raise ValueError("historical_min_observations must be positive")
        if self.short_loss_window < 1:
            raise ValueError("short_loss_window must be positive")
        if self.drawdown_window < 2:
            raise ValueError("drawdown_window must be at least two")
        for name in (
            "beta_gap_quantile",
            "drawdown_quantile",
            "short_loss_quantile",
        ):
            value = getattr(self, name)
            if not 0.0 < value < 1.0:
                raise ValueError(f"{name} must lie strictly between zero and one")
        for name in (
            "beta_gap_demo_threshold",
            "beta_gap_floor",
            "drawdown_demo_threshold",
            "drawdown_floor",
            "drawdown_ceiling",
            "short_loss_demo_threshold",
        ):
            if not np.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if self.beta_gap_demo_threshold < self.beta_gap_floor:
            raise ValueError("beta gap demo threshold cannot be below its floor")
        if self.drawdown_demo_threshold < self.drawdown_floor:
            raise ValueError("drawdown demo threshold cannot be below its floor")
        if self.drawdown_floor >= self.drawdown_ceiling:
            raise ValueError("drawdown floor must be below its ceiling")
        if self.drawdown_demo_threshold > self.drawdown_ceiling:
            raise ValueError("drawdown demo threshold cannot exceed its ceiling")
        if self.drawdown_ceiling >= 0.0:
            raise ValueError("drawdown ceiling must be negative")
        if self.short_loss_demo_threshold < 0.0:
            raise ValueError("short loss demo threshold cannot be negative")


DEFAULT_CONFIG = ScorecardConfig()


def _validate_history(
    frame: pd.DataFrame,
    *,
    required: set[str],
    name: str,
) -> pd.DataFrame:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"{name} missing required columns: {missing}")
    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"]).dt.normalize()
    result = result.sort_values("date").reset_index(drop=True)
    if result.empty:
        raise ValueError(f"{name} cannot be empty")
    if result["date"].duplicated().any():
        raise ValueError(f"{name} contains duplicate dates")
    return result


def _prepare_risk_history(
    risk_history: pd.DataFrame,
    *,
    config: ScorecardConfig,
) -> pd.DataFrame:
    result = _validate_history(
        risk_history,
        required=RISK_REQUIRED_COLUMNS,
        name="risk history",
    )
    numeric_columns = sorted(RISK_REQUIRED_COLUMNS - {"date"})
    for column in numeric_columns:
        result[column] = pd.to_numeric(result[column], errors="raise")
        finite = result[column].dropna()
        if not np.isfinite(finite).all():
            raise ValueError(f"risk history {column} contains non-finite values")
    if result["portfolio_return"].isna().any():
        raise ValueError("risk history portfolio_return cannot be missing")
    if result["portfolio_return"].le(-1.0).any():
        raise ValueError("risk history portfolio_return cannot be <= -1")
    wealth = (1.0 + result["portfolio_return"]).cumprod()
    rolling_peak = wealth.rolling(
        config.drawdown_window,
        min_periods=config.drawdown_window,
    ).max()
    result[f"portfolio_drawdown_{config.drawdown_window}d"] = (
        wealth / rolling_peak - 1.0
    )
    daily_short_loss = (-result["short_contribution"]).clip(lower=0.0)
    result[f"short_loss_magnitude_{config.short_loss_window}d"] = (
        daily_short_loss.rolling(
            config.short_loss_window,
            min_periods=config.short_loss_window,
        ).sum()
    )
    return result


def _prepare_regime_history(regime_history: pd.DataFrame) -> pd.DataFrame:
    result = _validate_history(
        regime_history,
        required=REGIME_REQUIRED_COLUMNS,
        name="regime history",
    )
    for column in (
        "early_recovery_state",
        "high_volatility_recovery_state",
    ):
        invalid = result[column].dropna().map(
            lambda value: not isinstance(value, (bool, np.bool_))
        )
        if invalid.any():
            raise ValueError(f"regime history {column} must be boolean or null")
        result[column] = result[column].astype("boolean")
    return result


def _value(row: pd.Series | None, column: str) -> float | None:
    if row is None or column not in row.index or pd.isna(row[column]):
        return None
    value = float(row[column])
    if not np.isfinite(value):
        raise ValueError(f"{column} is non-finite")
    return value


def _boolean(row: pd.Series | None, column: str) -> bool | None:
    if row is None or column not in row.index or pd.isna(row[column]):
        return None
    return bool(row[column])


def _selected_row(
    frame: pd.DataFrame,
    as_of_date: pd.Timestamp,
) -> pd.Series | None:
    selected = frame.loc[frame["date"].eq(as_of_date)]
    if selected.empty:
        return None
    return selected.iloc[0]


def _threshold(
    frame: pd.DataFrame,
    *,
    as_of_date: pd.Timestamp,
    column: str,
    quantile: float,
    fallback: float,
    min_observations: int,
    floor: float | None = None,
    ceiling: float | None = None,
) -> tuple[float, str, str]:
    """Return a prior-only threshold and an auditable calibration description."""

    prior = frame.loc[frame["date"].lt(as_of_date), column].dropna()
    count = int(len(prior))
    percentile = int(round(quantile * 100))
    if count < min_observations:
        return (
            float(fallback),
            "demo_threshold",
            (
                f"demonstration assumption; {count} prior observations, "
                f"minimum required is {min_observations}"
            ),
        )
    raw_threshold = float(
        prior.quantile(quantile, interpolation="linear")
    )
    threshold = raw_threshold
    bound_details: list[str] = []
    if floor is not None and threshold < floor:
        threshold = float(floor)
        bound_details.append(f"structural floor={floor:g}")
    if ceiling is not None and threshold > ceiling:
        threshold = float(ceiling)
        bound_details.append(f"structural ceiling={ceiling:g}")
    guardrail_applied = bool(bound_details)
    detail = (
        f"prior-only {percentile}th percentile from {count} observations; "
        f"raw historical threshold={raw_threshold:g}"
    )
    if guardrail_applied:
        detail += (
            f"; overridden by {' and '.join(bound_details)}; "
            f"active threshold={threshold:g}"
        )
    return (
        threshold,
        "demo_threshold" if guardrail_applied else "historical_quantile",
        detail,
    )


def _comparison(
    value: float | None,
    threshold: float | None,
    direction: str,
) -> bool | None:
    if value is None or threshold is None:
        return None
    if direction == "greater_than_or_equal":
        return value > threshold or bool(
            np.isclose(value, threshold, rtol=0.0, atol=1e-12)
        )
    if direction == "less_than_or_equal":
        return value < threshold or bool(
            np.isclose(value, threshold, rtol=0.0, atol=1e-12)
        )
    raise ValueError(f"unsupported comparison direction: {direction}")


def _clean_context_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return iso_date(value)
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if pd.isna(value):
        return None
    return value


def _context(**values: Any) -> str:
    payload = {
        key: _clean_context_value(value)
        for key, value in values.items()
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _scorecard_row(
    *,
    as_of_date: pd.Timestamp,
    monitor_family: str,
    metric: str,
    current_value: float | None,
    threshold: float,
    threshold_provenance: str,
    direction: str,
    triggered: bool | None,
    explanation: str,
    context: str,
    source_module: str,
) -> dict[str, Any]:
    available = triggered is not None
    return {
        "as_of_date": iso_date(as_of_date),
        "monitor_family": monitor_family,
        "metric": metric,
        "current_value": current_value,
        "threshold": threshold,
        "threshold_provenance": threshold_provenance,
        "direction": direction,
        "triggered": triggered if available else pd.NA,
        "severity": (
            "unavailable"
            if not available
            else "high" if triggered else "normal"
        ),
        "status": "available" if available else "unavailable",
        "explanation": explanation,
        "context": context,
        "source_module": source_module,
    }


def validate_scorecard(table: pd.DataFrame) -> None:
    """Validate the strict four-row serialized scorecard contract."""

    if tuple(table.columns) != SCORECARD_COLUMNS:
        raise ValueError("scorecard columns do not match the published schema")
    if tuple(table["metric"]) != SCORECARD_METRICS:
        raise ValueError("scorecard must contain the four published metrics in order")
    if table["metric"].duplicated().any():
        raise ValueError("scorecard metrics must be unique")
    if table["as_of_date"].nunique() != 1:
        raise ValueError("all scorecard rows must share one as-of date")
    if not set(table["threshold_provenance"]).issubset(THRESHOLD_PROVENANCE):
        raise ValueError("scorecard contains unsupported threshold provenance")
    if not set(table["direction"]).issubset(DIRECTIONS):
        raise ValueError("scorecard contains unsupported comparison directions")
    if not set(table["severity"]).issubset(SEVERITIES):
        raise ValueError("scorecard contains unsupported severities")
    if not set(table["status"]).issubset(STATUSES):
        raise ValueError("scorecard contains unsupported statuses")

    for _, row in table.iterrows():
        if not np.isfinite(float(row["threshold"])):
            raise ValueError("scorecard threshold must be finite")
        if row["status"] == "unavailable":
            if not pd.isna(row["triggered"]) or row["severity"] != "unavailable":
                raise ValueError("unavailable rows must have a null trigger")
            continue
        if pd.isna(row["current_value"]) or pd.isna(row["triggered"]):
            raise ValueError("available rows require a value and trigger")
        if row["severity"] != ("high" if bool(row["triggered"]) else "normal"):
            raise ValueError("scorecard severity must agree with trigger")


def build_scorecard(
    risk_history: pd.DataFrame,
    regime_history: pd.DataFrame,
    *,
    as_of_date: pd.Timestamp,
    config: ScorecardConfig = DEFAULT_CONFIG,
) -> pd.DataFrame:
    """Build the four-row deterministic scorecard for one exact date."""

    as_of_date = pd.Timestamp(as_of_date).normalize()
    risk = _prepare_risk_history(risk_history, config=config)
    regime = _prepare_regime_history(regime_history)
    risk_row = _selected_row(risk, as_of_date)
    regime_row = _selected_row(regime, as_of_date)
    if risk_row is None and regime_row is None:
        raise ValueError(
            f"neither risk nor regime history contains {iso_date(as_of_date)}"
        )

    high_volatility_recovery = _boolean(
        regime_row,
        "high_volatility_recovery_state",
    )
    hvr_value = (
        None
        if high_volatility_recovery is None
        else float(high_volatility_recovery)
    )
    hvr_triggered = _comparison(
        hvr_value,
        1.0,
        "greater_than_or_equal",
    )

    beta_threshold, beta_provenance, beta_threshold_detail = _threshold(
        risk,
        as_of_date=as_of_date,
        column="beta_gap_short_minus_long_126d",
        quantile=config.beta_gap_quantile,
        fallback=config.beta_gap_demo_threshold,
        min_observations=config.historical_min_observations,
        floor=config.beta_gap_floor,
    )
    beta_gap = _value(risk_row, "beta_gap_short_minus_long_126d")
    beta_triggered = _comparison(
        beta_gap,
        beta_threshold,
        "greater_than_or_equal",
    )

    drawdown_column = f"portfolio_drawdown_{config.drawdown_window}d"
    drawdown_threshold, drawdown_provenance, drawdown_threshold_detail = (
        _threshold(
            risk,
            as_of_date=as_of_date,
            column=drawdown_column,
            quantile=config.drawdown_quantile,
            fallback=config.drawdown_demo_threshold,
            min_observations=config.historical_min_observations,
            floor=config.drawdown_floor,
            ceiling=config.drawdown_ceiling,
        )
    )
    portfolio_drawdown = _value(risk_row, drawdown_column)
    drawdown_triggered = _comparison(
        portfolio_drawdown,
        drawdown_threshold,
        "less_than_or_equal",
    )

    short_loss_column = (
        f"short_loss_magnitude_{config.short_loss_window}d"
    )
    short_loss_threshold, short_loss_provenance, short_loss_threshold_detail = (
        _threshold(
            risk,
            as_of_date=as_of_date,
            column=short_loss_column,
            quantile=config.short_loss_quantile,
            fallback=config.short_loss_demo_threshold,
            min_observations=config.historical_min_observations,
        )
    )
    short_loss = _value(risk_row, short_loss_column)
    early_recovery = _boolean(regime_row, "early_recovery_state")
    short_loss_comparison = _comparison(
        short_loss,
        short_loss_threshold,
        "greater_than_or_equal",
    )
    short_loss_triggered = (
        None
        if early_recovery is None or short_loss_comparison is None
        else bool(early_recovery and short_loss_comparison)
    )

    rows = [
        _scorecard_row(
            as_of_date=as_of_date,
            monitor_family="macro",
            metric="high_volatility_recovery",
            current_value=hvr_value,
            threshold=1.0,
            threshold_provenance="demo_threshold",
            direction="greater_than_or_equal",
            triggered=hvr_triggered,
            explanation=(
                "One composite macro gate replaces separate drawdown, recovery, "
                "and volatility alerts. It requires Phase 1 early recovery and "
                "high realized volatility to be true together."
            ),
            context=_context(
                market_drawdown=_value(regime_row, "market_drawdown"),
                recent_min_drawdown_126d=_value(
                    regime_row,
                    "recent_min_drawdown_126d",
                ),
                recovery_from_trough_126d=_value(
                    regime_row,
                    "recovery_from_trough_126d",
                ),
                realized_volatility_21d=_value(
                    regime_row,
                    "realized_volatility_21d",
                ),
                realized_volatility_threshold_80pct=_value(
                    regime_row,
                    "realized_volatility_threshold_80pct",
                ),
                early_recovery_state=early_recovery,
                high_volatility=_boolean(regime_row, "high_volatility"),
            ),
            source_module="src.regime.market_state",
        ),
        _scorecard_row(
            as_of_date=as_of_date,
            monitor_family="leg_exposure",
            metric="short_minus_long_beta_gap",
            current_value=beta_gap,
            threshold=beta_threshold,
            threshold_provenance=beta_provenance,
            direction="greater_than_or_equal",
            triggered=beta_triggered,
            explanation=(
                "Positive and unusually high short-underlying minus long beta "
                "indicates that a market rebound can squeeze the recent-loser "
                f"leg. Threshold: {beta_threshold_detail}."
            ),
            context=_context(
                long_beta_126d=_value(risk_row, "long_beta_126d"),
                short_underlying_beta_126d=_value(
                    risk_row,
                    "short_underlying_beta_126d",
                ),
                portfolio_beta_126d=_value(risk_row, "portfolio_beta_126d"),
            ),
            source_module="src.risk.leg_decomposition",
        ),
        _scorecard_row(
            as_of_date=as_of_date,
            monitor_family="portfolio_loss",
            metric="portfolio_drawdown",
            current_value=portfolio_drawdown,
            threshold=drawdown_threshold,
            threshold_provenance=drawdown_provenance,
            direction="less_than_or_equal",
            triggered=drawdown_triggered,
            explanation=(
                f"Long-short wealth relative to its highest level in the prior "
                f"{config.drawdown_window} trading days is compared with its "
                "own prior-only left-tail history. The threshold can never be "
                f"looser than {config.drawdown_floor:.0%}, and drawdowns "
                f"shallower than {abs(config.drawdown_ceiling):.0%} are not "
                "material. Threshold: "
                f"{drawdown_threshold_detail}."
            ),
            context=_context(
                drawdown_window_trading_days=config.drawdown_window,
                gross_exposure=2.0,
                since_inception_portfolio_drawdown=_value(
                    risk_row,
                    "portfolio_drawdown",
                ),
                membership_status=(
                    None
                    if risk_row is None
                    else risk_row.get("membership_status")
                ),
                survivorship_bias=(
                    None
                    if risk_row is None
                    else risk_row.get("survivorship_bias")
                ),
            ),
            source_module=(
                "src.monitoring.scorecard + src.risk.leg_decomposition"
            ),
        ),
        _scorecard_row(
            as_of_date=as_of_date,
            monitor_family="recovery_mechanism",
            metric="short_loss_in_recovery",
            current_value=short_loss,
            threshold=short_loss_threshold,
            threshold_provenance=short_loss_provenance,
            direction="greater_than_or_equal",
            triggered=short_loss_triggered,
            explanation=(
                f"Trailing {config.short_loss_window}-day short loss magnitude "
                "is the sum of negative signed short contributions. It triggers "
                "only when Phase 1 early recovery is active and the loss reaches "
                f"the threshold. Threshold: {short_loss_threshold_detail}."
            ),
            context=_context(
                early_recovery_state=early_recovery,
                high_volatility_recovery_state=high_volatility_recovery,
                short_contribution_trailing_window=_value(
                    risk_row,
                    f"short_contribution_{config.short_loss_window}d",
                ),
                window_trading_days=config.short_loss_window,
            ),
            source_module=(
                "src.monitoring.scorecard + src.risk.leg_decomposition + "
                "src.regime.market_state"
            ),
        ),
    ]
    result = pd.DataFrame(rows, columns=SCORECARD_COLUMNS)
    result["triggered"] = result["triggered"].astype("boolean")
    validate_scorecard(result)
    return result


def _audit_record(table: pd.DataFrame) -> dict[str, Any]:
    triggered = table.loc[table["triggered"].fillna(False), "metric"].tolist()
    unavailable = table.loc[table["status"].eq("unavailable"), "metric"].tolist()
    return {
        "as_of_date": table["as_of_date"].iloc[0],
        "rows": int(len(table)),
        "triggered_metrics": triggered,
        "unavailable_metrics": unavailable,
        "thresholds": {
            row["metric"]: {
                "value": float(row["threshold"]),
                "provenance": row["threshold_provenance"],
            }
            for _, row in table.iterrows()
        },
    }


def run_scorecard_assessments(
    *,
    as_of_dates: list[pd.Timestamp],
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR / "scorecard",
    config: ScorecardConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Build, persist, and audit one or more Phase 4 scorecards."""

    if not as_of_dates:
        raise ValueError("at least one as-of date is required")
    risk = pd.read_parquet(processed_dir / "leg_risk_history.parquet")
    factors = pd.read_parquet(
        processed_dir / "french_research_factors_daily.parquet",
        columns=["date", "mkt_total_return", "rf"],
    )
    regime = build_regime_history(factors)

    output_dir.mkdir(parents=True, exist_ok=True)
    assessments: list[dict[str, Any]] = []
    output_paths: list[str] = []
    for raw_date in as_of_dates:
        as_of_date = pd.Timestamp(raw_date).normalize()
        table = build_scorecard(
            risk,
            regime,
            as_of_date=as_of_date,
            config=config,
        )
        path = output_dir / f"scorecard_{iso_date(as_of_date)}.csv"
        atomic_write_bytes(path, table.to_csv(index=False).encode("utf-8"))
        assessments.append(_audit_record(table))
        try:
            output_paths.append(str(path.relative_to(REPO_ROOT)))
        except ValueError:
            output_paths.append(str(path.resolve()))

    audit = {
        "scorecard_metrics": list(SCORECARD_METRICS),
        "scorecard_rows_per_date": len(SCORECARD_METRICS),
        "risk_first_date": iso_date(risk["date"].min()),
        "risk_last_date": iso_date(risk["date"].max()),
        "regime_first_date": iso_date(regime["date"].min()),
        "regime_last_date": iso_date(regime["date"].max()),
        "historical_min_observations": config.historical_min_observations,
        "drawdown_window": config.drawdown_window,
        "drawdown_maximum_tolerance": config.drawdown_floor,
        "drawdown_minimum_material_depth": config.drawdown_ceiling,
        "short_loss_window": config.short_loss_window,
        "assessment_timing": (
            "post-close facts on as-of date; earliest use is next trading session"
        ),
        "no_composite_probability": True,
        "output_paths": output_paths,
        "assessments": assessments,
    }
    write_json(output_dir / "scorecard_audit.json", audit)
    return audit


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of-date",
        action="append",
        required=True,
        metavar="YYYY-MM-DD",
        help="Repeat to build more than one scorecard.",
    )
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "scorecard",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    audit = run_scorecard_assessments(
        as_of_dates=[parse_as_of_date(value) for value in args.as_of_date],
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
