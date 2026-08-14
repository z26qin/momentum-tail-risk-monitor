"""PM-facing 0-100 monitoring severity score over existing signals.

This is a summary layer. It does not change triggers, thresholds, portfolio
construction, or risk-state logic, and it is not a crash probability.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.monitoring.scorecard import _prepare_risk_history
from src.monitoring.unwind_monitor import expanding_prior_percentile
from src.regime.market_state import build_regime_history
from src.risk.theme_concentration import benchmark_residual_returns
from src.utils.io import DEFAULT_PROCESSED_DIR

MECHANISM_KEYS = (
    "dm_recovery",
    "crowded_unwind",
    "fundamental_repricing",
    "book_vulnerability",
)
# Tie-break when two mechanisms share the headline max.
DRIVER_TIE_BREAK = (
    "crowded_unwind",
    "dm_recovery",
    "fundamental_repricing",
    "book_vulnerability",
)
MECHANISM_LABELS = {
    "dm_recovery": "DM recovery",
    "crowded_unwind": "Crowded unwind",
    "fundamental_repricing": "Fundamental repricing",
    "book_vulnerability": "Book vulnerability",
}
SEVERITY_BANDS = (
    (0, 39, "low", "🟢"),
    (40, 59, "watch", "🟡"),
    (60, 79, "elevated", "🟠"),
    (80, 100, "high", "🔴"),
)
SCORE_FORMULA = (
    "Each input is a strictly prior-only empirical percentile: "
    "share of earlier finite observations <= the current value "
    "(src.monitoring.unwind_monitor.expanding_prior_percentile). "
    "Higher-is-worse inputs keep that percentile; lower-is-worse inputs invert it "
    "(1 - p). Scores are 100 * p, rounded to the nearest integer in 0-100. "
    "Each mechanism score is the maximum of its available input scores. "
    "The headline monitoring_severity_score is the maximum available mechanism "
    "score because each mechanism is a distinct crash pathway. "
    "Ties break in order: crowded_unwind, dm_recovery, fundamental_repricing, "
    "book_vulnerability. Missing inputs are omitted; a mechanism with no valid "
    "prior-only percentile is null / not_available and is not imputed. "
    "recovery_from_trough is not ranked: its risk direction is not monotonic "
    "(a bounce is DM-relevant only with a severe hole and young trough age). "
    "This is not a crash probability."
)
FUNDAMENTAL_UNAVAILABLE_REASON = (
    "fundamental_anchor is a coverage-gated categorical sign-vote "
    "(supportive / mixed / deteriorating), not a stored continuous series, "
    "so no prior-only percentile exists. On dates without company coverage "
    "the row is unavailable."
)


def _finite_or_none(value: Any) -> float | None:
    if value is None or value is pd.NA or pd.isna(value):
        return None
    result = float(value)
    if result != result or result in {float("inf"), float("-inf")}:
        return None
    return result


def _as_int_score(rank: float | None) -> int | None:
    value = _finite_or_none(rank)
    if value is None:
        return None
    return max(0, min(100, int(round(100.0 * value))))


def severity_band(score: int | None) -> tuple[str | None, str | None]:
    """Return ``(score_label, severity_emoji)`` for a 0-100 score."""

    if score is None:
        return None, None
    if not 0 <= int(score) <= 100:
        raise ValueError("monitoring severity score must be in 0-100")
    for low, high, label, emoji in SEVERITY_BANDS:
        if low <= int(score) <= high:
            return label, emoji
    raise ValueError("monitoring severity score must be in 0-100")


def prior_only_risk_score(
    values: pd.Series,
    as_of: pd.Timestamp,
    *,
    invert: bool,
) -> int | None:
    """Convert one series into a 0-100 prior-only risk-direction percentile."""

    series = pd.to_numeric(values, errors="coerce")
    if series.empty:
        return None
    dates = pd.DatetimeIndex(pd.to_datetime(series.index)).normalize()
    series = pd.Series(series.to_numpy(dtype=float), index=dates)
    series = series[~series.index.duplicated(keep="last")].sort_index()
    as_of = pd.Timestamp(as_of).normalize()
    series = series.loc[series.index <= as_of]
    if as_of not in series.index:
        return None
    rank = expanding_prior_percentile(series).loc[as_of]
    if isinstance(rank, pd.Series):
        rank = rank.iloc[-1]
    rank_value = _finite_or_none(rank)
    if rank_value is None:
        return None
    if invert:
        rank_value = 1.0 - rank_value
    return _as_int_score(rank_value)


def _max_available(parts: dict[str, int | None]) -> int | None:
    available = [value for value in parts.values() if value is not None]
    if not available:
        return None
    return max(available)


def _component(
    name: str,
    percentile: int | None,
    *,
    current_value: Any = None,
    threshold: Any = None,
    direction: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "percentile": percentile,
        "current_value": _finite_or_none(current_value),
        "threshold": threshold if isinstance(threshold, str) else _finite_or_none(threshold),
        "direction": direction,
    }


def _dm_recovery_parts(result: Any) -> tuple[dict[str, int | None], list[dict[str, Any]], str | None]:
    processed_dir = getattr(getattr(result, "config", None), "processed_dir", DEFAULT_PROCESSED_DIR)
    path = processed_dir / "french_research_factors_daily.parquet"
    if not path.is_file():
        return {}, [], "french_research_factors_daily.parquet is missing"
    as_of = pd.Timestamp(result.config.as_of_date).normalize()
    regime = build_regime_history(pd.read_parquet(path))
    regime["date"] = pd.to_datetime(regime["date"]).dt.normalize()
    frame = regime.loc[regime["date"].le(as_of)].set_index("date")
    if as_of not in frame.index:
        return {}, [], "regime history has no row on the assessment date"
    row = frame.loc[as_of]
    drawdown = prior_only_risk_score(
        frame["recent_min_drawdown_126d"], as_of, invert=True
    )
    vol = prior_only_risk_score(
        frame["realized_volatility_21d"], as_of, invert=False
    )
    parts = {
        "recent_min_drawdown_126d": drawdown,
        "realized_volatility_21d": vol,
    }
    components = [
        _component(
            "recent_min_drawdown_126d",
            drawdown,
            current_value=row.get("recent_min_drawdown_126d"),
            threshold=-0.20,
            direction="lower",
        ),
        _component(
            "realized_volatility_21d",
            vol,
            current_value=row.get("realized_volatility_21d"),
            threshold=row.get("realized_volatility_threshold_80pct"),
            direction="higher",
        ),
    ]
    return parts, components, None


def _existing_percentile(value: Any) -> int | None:
    return _as_int_score(_finite_or_none(value))


def _theme_residual_score(result: Any) -> tuple[int | None, float | None, float | None]:
    theme = result.unwind.theme_concentration
    current = _finite_or_none(theme.cluster_residual_loss_5d)
    threshold = _finite_or_none(theme.residual_loss_threshold)
    cluster = tuple(theme.cluster_symbols)
    if current is None or not cluster:
        return None, current, threshold
    processed_dir = result.config.processed_dir
    prices_path = processed_dir / "sp500_prices.parquet"
    benchmark_path = processed_dir / "sp500_benchmark.parquet"
    if not prices_path.is_file() or not benchmark_path.is_file():
        return None, current, threshold
    as_of = pd.Timestamp(result.config.as_of_date).normalize()
    window = int(result.config.theme_config.event_window)
    try:
        prices = pd.read_parquet(
            prices_path,
            filters=[("symbol", "in", list(cluster))],
        )
    except (TypeError, ValueError, OSError):
        prices = pd.read_parquet(prices_path)
        prices = prices.loc[prices["symbol"].isin(cluster)].copy()
    if prices.empty:
        return None, current, threshold
    residual = benchmark_residual_returns(
        prices, pd.read_parquet(benchmark_path)
    )
    residual = residual.loc[
        residual["symbol"].isin(cluster) & residual["date"].le(as_of)
    ]
    if residual.empty:
        return None, current, threshold
    panel = residual.pivot(
        index="date",
        columns="symbol",
        values="benchmark_residual_return",
    ).sort_index().reindex(columns=list(cluster))
    rolling = (1.0 + panel).rolling(window, min_periods=window).apply(
        np.prod, raw=True
    ) - 1.0
    loss = -rolling.mean(axis=1, skipna=False)
    score = prior_only_risk_score(loss, as_of, invert=False)
    return score, current, threshold


def _crowded_unwind_parts(
    result: Any,
) -> tuple[dict[str, int | None], list[dict[str, Any]], str | None]:
    mechanical = result.mechanical_unwind
    footprint = _existing_percentile(mechanical.factor_footprint_percentile)
    turnover = _existing_percentile(mechanical.extreme_turnover_percentile)
    continuation = _existing_percentile(mechanical.absorption_percentile)
    theme_score, theme_value, theme_threshold = _theme_residual_score(result)
    volume_score = None
    volume_value = None
    processed_dir = result.config.processed_dir
    fingerprint_path = processed_dir / "unwind_structure_history.parquet"
    as_of = pd.Timestamp(result.config.as_of_date).normalize()
    if fingerprint_path.is_file():
        fingerprint = pd.read_parquet(fingerprint_path)
        fingerprint["date"] = pd.to_datetime(fingerprint["date"]).dt.normalize()
        frame = fingerprint.loc[fingerprint["date"].le(as_of)].set_index("date")
        if as_of in frame.index and "downside_abnormal_volume_share_5d" in frame:
            volume_value = frame.loc[as_of, "downside_abnormal_volume_share_5d"]
            volume_score = prior_only_risk_score(
                frame["downside_abnormal_volume_share_5d"], as_of, invert=False
            )
    parts = {
        "factor_footprint_percentile": footprint,
        "extreme_turnover_percentile": turnover,
        "continuation_pressure_percentile": continuation,
        "cluster_residual_loss_5d": theme_score,
        "downside_abnormal_volume_share_5d": volume_score,
    }
    components = [
        _component(
            "factor_footprint_percentile",
            footprint,
            current_value=mechanical.factor_footprint_r2,
            threshold=0.80,
            direction="higher",
        ),
        _component(
            "extreme_turnover_percentile",
            turnover,
            current_value=mechanical.extreme_turnover_ratio,
            threshold=0.80,
            direction="higher",
        ),
        _component(
            "continuation_pressure_percentile",
            continuation,
            current_value=mechanical.continuation_pressure,
            threshold=0.80,
            direction="higher",
        ),
        _component(
            "cluster_residual_loss_5d",
            theme_score,
            current_value=theme_value,
            threshold=theme_threshold,
            direction="higher",
        ),
        _component(
            "downside_abnormal_volume_share_5d",
            volume_score,
            current_value=volume_value,
            threshold=0.50,
            direction="higher",
        ),
    ]
    if _max_available(parts) is None:
        return parts, components, "no prior-only crowded-unwind percentiles are available"
    return parts, components, None


def _book_vulnerability_parts(
    result: Any,
) -> tuple[dict[str, int | None], list[dict[str, Any]], str | None]:
    processed_dir = result.config.processed_dir
    path = processed_dir / "leg_risk_history.parquet"
    if not path.is_file():
        return {}, [], "leg_risk_history.parquet is missing"
    as_of = pd.Timestamp(result.config.as_of_date).normalize()
    config = result.config.scorecard_config
    prepared = _prepare_risk_history(pd.read_parquet(path), config=config)
    prepared["date"] = pd.to_datetime(prepared["date"]).dt.normalize()
    frame = prepared.loc[prepared["date"].le(as_of)].set_index("date")
    if as_of not in frame.index:
        return {}, [], "leg risk history has no row on the assessment date"
    row = frame.loc[as_of]
    drawdown_col = f"portfolio_drawdown_{config.drawdown_window}d"
    short_col = f"short_loss_magnitude_{config.short_loss_window}d"
    beta = prior_only_risk_score(
        frame["beta_gap_short_minus_long_126d"], as_of, invert=False
    )
    drawdown = prior_only_risk_score(frame[drawdown_col], as_of, invert=True)
    short_loss = prior_only_risk_score(frame[short_col], as_of, invert=False)
    parts = {
        "beta_gap_short_minus_long_126d": beta,
        drawdown_col: drawdown,
        short_col: short_loss,
    }
    signals = {
        signal.name: signal
        for signal in (
            result.deterministic_input.triggered_quant_signals
            + result.deterministic_input.non_triggered_relevant_signals
        )
    }
    components = [
        _component(
            "beta_gap_short_minus_long_126d",
            beta,
            current_value=row.get("beta_gap_short_minus_long_126d"),
            threshold=getattr(signals.get("short_minus_long_beta_gap"), "threshold", None),
            direction="higher",
        ),
        _component(
            drawdown_col,
            drawdown,
            current_value=row.get(drawdown_col),
            threshold=getattr(signals.get("portfolio_drawdown"), "threshold", None),
            direction="lower",
        ),
        _component(
            short_col,
            short_loss,
            current_value=row.get(short_col),
            threshold=getattr(signals.get("short_loss_in_recovery"), "threshold", None),
            direction="higher",
        ),
    ]
    return parts, components, None


def _fundamental_reason(result: Any) -> str:
    rows = {row.metric: row for row in result.unwind.scorecard}
    row = rows.get("fundamental_anchor")
    if row is None:
        return FUNDAMENTAL_UNAVAILABLE_REASON
    status = row.status
    current = row.current_value
    extra = ""
    if status != "available" or current in {None, "unavailable"}:
        coverage = row.context.get("long_covered_count")
        extra = f" Scorecard status={status}; long_covered_count={coverage}."
    return FUNDAMENTAL_UNAVAILABLE_REASON + extra


def compute_monitoring_severity(result: Any) -> dict[str, Any]:
    """Build the compact monitoring-severity block from an ``MVPRunResult``."""

    dm_parts, dm_components, dm_reason = _dm_recovery_parts(result)
    crowded_parts, crowded_components, crowded_reason = _crowded_unwind_parts(result)
    book_parts, book_components, book_reason = _book_vulnerability_parts(result)

    mechanism_parts = {
        "dm_recovery": dm_parts,
        "crowded_unwind": crowded_parts,
        "fundamental_repricing": {},
        "book_vulnerability": book_parts,
    }
    mechanism_scores = {
        "dm_recovery": _max_available(dm_parts),
        "crowded_unwind": _max_available(crowded_parts),
        "fundamental_repricing": None,
        "book_vulnerability": _max_available(book_parts),
    }
    unavailable = {
        "fundamental_repricing": _fundamental_reason(result),
    }
    if mechanism_scores["dm_recovery"] is None and dm_reason:
        unavailable["dm_recovery"] = dm_reason
    if mechanism_scores["crowded_unwind"] is None and crowded_reason:
        unavailable["crowded_unwind"] = crowded_reason
    if mechanism_scores["book_vulnerability"] is None and book_reason:
        unavailable["book_vulnerability"] = book_reason

    available_scores = {
        key: value for key, value in mechanism_scores.items() if value is not None
    }
    headline = max(available_scores.values()) if available_scores else None
    primary_driver = None
    if headline is not None:
        tied = [key for key, value in available_scores.items() if value == headline]
        primary_driver = next(
            key for key in DRIVER_TIE_BREAK if key in tied
        )
    label, emoji = severity_band(headline)
    return {
        "monitoring_severity_score": headline,
        "score_label": label,
        "severity_emoji": emoji,
        "primary_driver": primary_driver,
        "mechanism_scores": mechanism_scores,
        "score_is_probability": False,
        "score_formula": SCORE_FORMULA,
        "mechanism_score_components": {
            "dm_recovery": dm_components,
            "crowded_unwind": crowded_components,
            "fundamental_repricing": [],
            "book_vulnerability": book_components,
        },
        "unavailable_mechanism_reasons": unavailable,
        "mechanism_input_percentiles": mechanism_parts,
    }


def mechanism_label(key: str | None) -> str:
    if not key:
        return "Not available"
    return MECHANISM_LABELS.get(key, key.replace("_", " "))


def format_score_value(value: int | None, *, over_100: bool = False) -> str:
    """Render a score as ``Not available`` or ``{emoji} {n}`` / ``{emoji} {n}/100``."""

    if value is None:
        return "Not available"
    _, emoji = severity_band(int(value))
    number = f"{int(value)}/100" if over_100 else str(int(value))
    return f"{emoji} {number}" if emoji else number


def score_label_display(label: str | None) -> str:
    if not label:
        return "Not available"
    return label.replace("_", " ").title()
