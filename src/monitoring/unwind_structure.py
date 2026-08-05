"""Deterministic momentum-unwind fingerprint calculations.

This module measures observable public-data symptoms of an unwind. It does not
claim to observe leverage, financing pressure, hedge-fund positioning, or
forced selling directly. Security-level history inherits the repository's
current-membership proxy limitation.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.features.momentum_breadth import build_momentum_breadth_history
from src.regime.market_state import (
    EARLY_RECOVERY_MAX_AGE,
    RECOVERY_FROM_TROUGH_THRESHOLD,
    SEVERE_DRAWDOWN_THRESHOLD,
    build_regime_history,
)
from src.monitoring.fundamental_anchor import (
    FundamentalAnchor,
    build_fundamental_anchor_for_date,
)
from src.risk.concentration import (
    CONSTITUENT_RETURN_COLUMNS,
    build_concentration_history,
    build_constituent_return_history,
    build_rebalance_diagnostics,
)
from src.risk.theme_concentration import (
    DEFAULT_THEME_CONFIG,
    ThemeConcentrationConfig,
    ThemeConcentrationSnapshot,
    build_theme_concentration_snapshot,
)
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    DEFAULT_RAW_DIR,
    atomic_write_bytes,
    iso_date,
    parse_as_of_date,
    write_json,
    write_parquet,
)


FINGERPRINT_HISTORY_COLUMNS = (
    "date",
    "formation_date",
    "effective_month",
    "long_return_5d",
    "short_underlying_return_5d",
    "long_minus_short_return_5d",
    "short_minus_long_return_5d",
    "beta_expected_long_return_5d",
    "beta_adjusted_long_return_5d",
    "residual_long_loss_5d",
    "long_decline_share_5d",
    "short_rise_share_5d",
    "long_downside_breach_share_5d",
    "long_average_pairwise_correlation_21d",
    "long_pairwise_correlation_prior_median_63d",
    "long_pairwise_correlation_change",
    "downside_abnormal_volume_share_5d",
    "liquidity_eligible_long_count",
    "long_median_amihud_5d",
    "liquidity_proxy_status",
    "classification_status",
    "survivorship_bias",
)

LEGACY_UNWIND_SCHEMA_VERSION = "momentum-unwind-assessment-v1"
UNWIND_SCHEMA_VERSION = "momentum-unwind-assessment-v2"
UNWIND_SCORECARD_METRICS = (
    "portfolio_concentration",
    "momentum_breadth_deterioration",
    "synchronous_winner_liquidation",
    "cross_sectional_reversal",
    "liquidity_amplification_proxy",
    "fundamental_anchor",
)
UNWIND_SCENARIOS = frozenset(
    {
        "normal_drawdown",
        "fundamental_repricing",
        "panic_recovery_momentum_crash",
        "crowded_momentum_unwind",
        "mixed_repricing_and_unwind",
        "insufficient_evidence",
    }
)
UNWIND_DIRECTIONS = frozenset(
    {"greater_than_or_equal", "less_than_or_equal", "rule_based"}
)
UNWIND_STATUSES = frozenset(
    {"available", "unavailable", "insufficient_history"}
)
UNWIND_SEVERITIES = frozenset(
    {"normal", "elevated", "high", "unavailable"}
)
UNWIND_THRESHOLD_PROVENANCE = frozenset(
    {
        "literature",
        "historical_quantile",
        "historical_proxy_threshold",
        "demo_threshold",
        "insufficient_history",
    }
)
MECHANISM_SCENARIOS = (
    "bear_market_recovery_crash",
    "short_book_reversal_crash",
    "crowded_theme_unwind",
)
MECHANISM_SCENARIO_STATUSES = frozenset(
    {"triggered", "watch", "not_confirmed", "unavailable"}
)
MECHANISM_CONDITION_DIRECTIONS = frozenset(
    {
        "boolean_true",
        "greater_than_or_equal",
        "less_than_or_equal",
        "context_only",
        "rule_based",
    }
)


@dataclass(frozen=True)
class UnwindMonitorConfig:
    """Windows, quantiles, and explicit demonstration gates."""

    return_window: int = 5
    correlation_window: int = 21
    correlation_context_window: int = 63
    threshold_min_observations: int = 252
    breadth_min_observations: int = 24
    concentration_quantile: float = 0.20
    breadth_quantile: float = 0.20
    residual_loss_quantile: float = 0.80
    reversal_quantile: float = 0.80
    reversal_floor: float = 0.0
    co_decline_gate: float = 0.70
    downside_return_gate: float = -0.02
    volume_window: int = 5
    volume_history_min_observations: int = 63
    volume_quantile: float = 0.80
    liquidity_breadth_gate: float = 0.50
    short_rise_gate: float = 0.70
    short_beta_quantile: float = 0.20
    minimum_active_names: int = 6

    def __post_init__(self) -> None:
        for name in (
            "return_window",
            "correlation_window",
            "correlation_context_window",
            "threshold_min_observations",
            "breadth_min_observations",
            "volume_window",
            "volume_history_min_observations",
            "minimum_active_names",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        for name in (
            "residual_loss_quantile",
            "reversal_quantile",
            "volume_quantile",
            "concentration_quantile",
            "breadth_quantile",
            "short_beta_quantile",
        ):
            if not 0.0 < getattr(self, name) < 1.0:
                raise ValueError(f"{name} must lie strictly between zero and one")
        for name in (
            "co_decline_gate",
            "liquidity_breadth_gate",
            "short_rise_gate",
        ):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must lie between zero and one")
        for name in ("reversal_floor", "downside_return_gate"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if self.downside_return_gate >= 0.0:
            raise ValueError("downside_return_gate must be negative")


DEFAULT_UNWIND_CONFIG = UnwindMonitorConfig()


@dataclass(frozen=True)
class PriorOnlyThreshold:
    """One auditable prior-only threshold result."""

    value: float | None
    raw_value: float | None
    provenance: str
    prior_observations: int
    quantile: float
    bound_applied: bool

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class UnwindScorecardRow:
    """One validated row in the unwind scorecard."""

    as_of_date: str
    monitor_family: str
    metric: str
    current_value: float | str | None
    threshold: float | str | None
    threshold_provenance: str
    direction: str
    triggered: bool | None
    severity: str
    status: str
    explanation: str
    context: dict[str, Any]
    source_module: str
    data_quality: str

    def __post_init__(self) -> None:
        if self.metric not in UNWIND_SCORECARD_METRICS:
            raise ValueError(f"unsupported unwind metric: {self.metric}")
        if self.threshold_provenance not in UNWIND_THRESHOLD_PROVENANCE:
            raise ValueError("unsupported unwind threshold provenance")
        if self.direction not in UNWIND_DIRECTIONS:
            raise ValueError("unsupported unwind comparison direction")
        if self.status not in UNWIND_STATUSES:
            raise ValueError("unsupported unwind row status")
        if self.severity not in UNWIND_SEVERITIES:
            raise ValueError("unsupported unwind row severity")
        for value in (self.current_value, self.threshold):
            if isinstance(value, (float, np.floating)) and not np.isfinite(value):
                raise ValueError("numeric scorecard values must be finite or null")
        if self.status != "available":
            if self.triggered is not None or self.severity != "unavailable":
                raise ValueError("unavailable rows require null trigger/severity")
        elif self.triggered is None:
            raise ValueError("available rows require a trigger decision")
        json.dumps(self.context, sort_keys=True, allow_nan=False)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class ScenarioCondition:
    """One auditable condition inside an independent crash mechanism."""

    name: str
    value: float | bool | str | None
    threshold: float | bool | str | None
    direction: str
    met: bool | None
    required: bool
    source_component: str

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.source_component.strip():
            raise ValueError("scenario condition labels must be non-empty")
        if self.direction not in MECHANISM_CONDITION_DIRECTIONS:
            raise ValueError("unsupported scenario condition direction")
        for value in (self.value, self.threshold):
            if isinstance(value, (float, np.floating)) and not np.isfinite(value):
                raise ValueError("scenario condition values must be finite or null")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class MechanismScenario:
    """One independent, non-probabilistic momentum-crash mechanism."""

    scenario: str
    status: str
    conditions: tuple[ScenarioCondition, ...]
    supporting_evidence: tuple[str, ...]
    contradictory_evidence: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        if self.scenario not in MECHANISM_SCENARIOS:
            raise ValueError("unsupported momentum-crash mechanism")
        if self.status not in MECHANISM_SCENARIO_STATUSES:
            raise ValueError("unsupported momentum-crash mechanism status")
        if not self.conditions:
            raise ValueError("mechanism scenario requires conditions")
        names = tuple(condition.name for condition in self.conditions)
        if len(set(names)) != len(names):
            raise ValueError("mechanism condition names must be unique")
        expected_support = tuple(
            condition.name for condition in self.conditions if condition.met is True
        )
        expected_contradictory = tuple(
            condition.name
            for condition in self.conditions
            if condition.required and condition.met is False
        )
        expected_missing = tuple(
            condition.name
            for condition in self.conditions
            if condition.required and condition.met is None
        )
        if self.supporting_evidence != expected_support:
            raise ValueError("supporting evidence must match met conditions")
        if self.contradictory_evidence != expected_contradictory:
            raise ValueError("contradictory evidence must match required conditions")
        if self.missing_evidence != expected_missing:
            raise ValueError("missing evidence must match required conditions")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class UnwindAssessment:
    """Validated six-row unwind assessment plus independent mechanisms."""

    schema_version: str
    as_of_date: str
    scorecard: tuple[UnwindScorecardRow, ...]
    mechanism_scenarios: tuple[MechanismScenario, ...]
    active_scenarios: tuple[str, ...]
    theme_concentration: ThemeConcentrationSnapshot
    scenario_classification: str
    scenario_rule: str
    completeness_confidence: str
    supporting_evidence: tuple[str, ...]
    contradictory_evidence: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    warnings: tuple[str, ...]
    audit_metadata: dict[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != UNWIND_SCHEMA_VERSION:
            raise ValueError("unsupported unwind assessment schema")
        if tuple(row.metric for row in self.scorecard) != UNWIND_SCORECARD_METRICS:
            raise ValueError("unwind scorecard must contain six ordered rows")
        if len({row.metric for row in self.scorecard}) != len(self.scorecard):
            raise ValueError("unwind scorecard metrics must be unique")
        if any(row.as_of_date != self.as_of_date for row in self.scorecard):
            raise ValueError("all unwind rows must share the assessment date")
        if self.scenario_classification not in UNWIND_SCENARIOS:
            raise ValueError("unsupported unwind scenario classification")
        if tuple(item.scenario for item in self.mechanism_scenarios) != (
            MECHANISM_SCENARIOS
        ):
            raise ValueError("assessment requires three ordered mechanism scenarios")
        expected_active = tuple(
            item.scenario
            for item in self.mechanism_scenarios
            if item.status == "triggered"
        )
        if self.active_scenarios != expected_active:
            raise ValueError("active_scenarios must match triggered mechanisms")
        if self.theme_concentration.as_of_date != self.as_of_date:
            raise ValueError("theme proxy must share the assessment date")
        if self.completeness_confidence not in {
            "high",
            "moderate",
            "insufficient",
        }:
            raise ValueError("unsupported completeness confidence")
        json.dumps(self.to_dict(), sort_keys=True, allow_nan=False)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _validate_daily_history(
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


def _rolling_compounded_return(
    values: pd.Series,
    *,
    window: int,
) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return (1.0 + numeric).rolling(window, min_periods=window).apply(
        np.prod,
        raw=True,
    ) - 1.0


def build_leg_unwind_history(
    risk_history: pd.DataFrame,
    *,
    config: UnwindMonitorConfig = DEFAULT_UNWIND_CONFIG,
) -> pd.DataFrame:
    """Build lagged-beta residual loss and long/short reversal history."""

    required = {
        "date",
        "formation_date",
        "effective_month",
        "long_basket_return",
        "short_basket_underlying_return",
        "benchmark_return",
        "long_beta_126d",
    }
    frame = _validate_daily_history(
        risk_history,
        required=required,
        name="risk history",
    )
    numeric = {
        "long_basket_return",
        "short_basket_underlying_return",
        "benchmark_return",
        "long_beta_126d",
    }
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        finite = frame[column].dropna()
        if not np.isfinite(finite).all():
            raise ValueError(f"risk history {column} contains non-finite values")

    frame["long_return_5d"] = _rolling_compounded_return(
        frame["long_basket_return"],
        window=config.return_window,
    )
    frame["short_underlying_return_5d"] = _rolling_compounded_return(
        frame["short_basket_underlying_return"],
        window=config.return_window,
    )
    frame["long_minus_short_return_5d"] = (
        frame["long_return_5d"] - frame["short_underlying_return_5d"]
    )
    frame["short_minus_long_return_5d"] = (
        -frame["long_minus_short_return_5d"]
    )

    frame["lagged_long_beta_126d"] = frame["long_beta_126d"].shift(1)
    frame["beta_expected_long_return_1d"] = (
        frame["lagged_long_beta_126d"] * frame["benchmark_return"]
    )
    frame["beta_expected_long_return_5d"] = frame[
        "beta_expected_long_return_1d"
    ].rolling(
        config.return_window,
        min_periods=config.return_window,
    ).sum()
    frame["beta_adjusted_long_return_5d"] = (
        frame["long_return_5d"] - frame["beta_expected_long_return_5d"]
    )
    frame["residual_long_loss_5d"] = -frame["beta_adjusted_long_return_5d"]
    return frame.loc[
        :,
        [
            "date",
            "formation_date",
            "effective_month",
            "long_return_5d",
            "short_underlying_return_5d",
            "long_minus_short_return_5d",
            "short_minus_long_return_5d",
            "beta_expected_long_return_5d",
            "beta_adjusted_long_return_5d",
            "residual_long_loss_5d",
        ],
    ]


def average_pairwise_correlation(returns: pd.DataFrame) -> float | None:
    """Return the average finite off-diagonal correlation.

    Incomplete windows, fewer than two securities, and constant series are
    unavailable rather than treated as zero correlation.
    """

    if returns.shape[1] < 2 or len(returns) < 2:
        return None
    numeric = returns.apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        return None
    correlations = numeric.corr().to_numpy(dtype="float64")
    upper = correlations[np.triu_indices_from(correlations, k=1)]
    finite = upper[np.isfinite(upper)]
    if len(finite) == 0:
        return None
    return float(finite.mean())


def _price_liquidity_history(
    prices: pd.DataFrame,
    *,
    config: UnwindMonitorConfig,
) -> pd.DataFrame:
    required = {"date", "symbol"}
    missing = sorted(required - set(prices.columns))
    if missing:
        raise KeyError(f"prices missing required columns: {missing}")
    frame = prices.loc[:, [column for column in prices if column in {
        "date",
        "symbol",
        "close_total_return_adjusted",
        "volume_as_traded",
        "dollar_volume",
    }]].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str)
    frame = frame.sort_values(["symbol", "date"]).reset_index(drop=True)
    if frame.duplicated(["symbol", "date"]).any():
        raise ValueError("prices contain duplicate symbol/date observations")

    optional = (
        "close_total_return_adjusted",
        "volume_as_traded",
        "dollar_volume",
    )
    for column in optional:
        if column not in frame:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    invalid_close = frame["close_total_return_adjusted"].le(0)
    frame.loc[invalid_close, "close_total_return_adjusted"] = np.nan
    frame["price_return"] = frame.groupby("symbol", sort=False)[
        "close_total_return_adjusted"
    ].pct_change(fill_method=None)

    group = frame.groupby("symbol", sort=False)
    frame["asset_return_5d"] = group["price_return"].transform(
        lambda values: _rolling_compounded_return(
            values,
            window=config.return_window,
        )
    )
    frame["volume_5d_average"] = group["volume_as_traded"].transform(
        lambda values: values.rolling(
            config.volume_window,
            min_periods=config.volume_window,
        ).mean()
    )
    frame["volume_5d_prior_80pct"] = group["volume_5d_average"].transform(
        lambda values: values.shift(1)
        .expanding(min_periods=config.volume_history_min_observations)
        .quantile(config.volume_quantile)
    )
    frame["amihud_1d"] = np.where(
        frame["dollar_volume"].gt(0),
        frame["price_return"].abs() / frame["dollar_volume"],
        np.nan,
    )
    frame["amihud_5d"] = group["amihud_1d"].transform(
        lambda values: values.rolling(
            config.volume_window,
            min_periods=config.volume_window,
        ).mean()
    )
    return frame.loc[
        :,
        [
            "date",
            "symbol",
            "price_return",
            "asset_return_5d",
            "volume_5d_average",
            "volume_5d_prior_80pct",
            "amihud_5d",
        ],
    ]


def _constituent_window_history(
    constituent_returns: pd.DataFrame,
) -> pd.DataFrame:
    missing = sorted(
        set(CONSTITUENT_RETURN_COLUMNS) - set(constituent_returns.columns)
    )
    if missing:
        raise KeyError(f"constituent returns missing required columns: {missing}")
    frame = constituent_returns.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["asset_return"] = pd.to_numeric(frame["asset_return"], errors="coerce")
    frame = frame.sort_values(
        ["formation_date", "effective_month", "leg", "symbol", "date"]
    ).reset_index(drop=True)
    return frame


def _pairwise_correlation_history(
    active_constituents: pd.DataFrame,
    price_history: pd.DataFrame,
    *,
    config: UnwindMonitorConfig,
) -> pd.DataFrame:
    long = active_constituents.loc[
        active_constituents["leg"].eq("long")
    ].copy()
    return_panel = price_history.pivot(
        index="date",
        columns="symbol",
        values="price_return",
    ).sort_index()
    records: list[dict[str, Any]] = []
    for date_value, group in long.groupby("date", sort=True):
        symbols = sorted(group["symbol"].unique())
        available_symbols = [
            symbol for symbol in symbols if symbol in return_panel.columns
        ]
        returns = return_panel.loc[
            return_panel.index <= pd.Timestamp(date_value),
            available_symbols,
        ].tail(config.correlation_window)
        value = (
            None
            if len(available_symbols) < config.minimum_active_names
            or len(returns) < config.correlation_window
            else average_pairwise_correlation(returns)
        )
        records.append(
            {
                "date": pd.Timestamp(date_value),
                "long_average_pairwise_correlation_21d": value,
            }
        )
    result = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    if result["date"].duplicated().any():
        raise ValueError("pairwise correlation history contains duplicate dates")
    result["long_pairwise_correlation_prior_median_63d"] = result[
        "long_average_pairwise_correlation_21d"
    ].shift(1).rolling(
        config.correlation_context_window,
        min_periods=config.correlation_context_window,
    ).median()
    result["long_pairwise_correlation_change"] = (
        result["long_average_pairwise_correlation_21d"]
        - result["long_pairwise_correlation_prior_median_63d"]
    )
    return result


def build_constituent_unwind_history(
    constituent_returns: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    config: UnwindMonitorConfig = DEFAULT_UNWIND_CONFIG,
) -> pd.DataFrame:
    """Aggregate co-decline, correlation, and public liquidity proxies."""

    frame = _constituent_window_history(constituent_returns)
    liquidity = _price_liquidity_history(prices, config=config)
    frame = frame.merge(
        liquidity,
        on=["date", "symbol"],
        how="left",
        validate="many_to_one",
    )
    correlations = _pairwise_correlation_history(
        frame,
        liquidity,
        config=config,
    )

    records: list[dict[str, Any]] = []
    for date_value, group in frame.groupby("date", sort=True):
        long = group.loc[group["leg"].eq("long")]
        short = group.loc[group["leg"].eq("short")]
        long_returns = long["asset_return_5d"].dropna()
        short_returns = short["asset_return_5d"].dropna()
        long_available = int(len(long_returns))
        short_available = int(len(short_returns))
        long_sufficient = long_available >= config.minimum_active_names
        short_sufficient = short_available >= config.minimum_active_names

        liquidity_valid = long.loc[
            long[
                [
                    "asset_return_5d",
                    "volume_5d_average",
                    "volume_5d_prior_80pct",
                ]
            ].notna().all(axis=1)
        ]
        liquidity_count = int(len(liquidity_valid))
        liquidity_sufficient = liquidity_count >= config.minimum_active_names
        downside_abnormal_volume_share = (
            None
            if not liquidity_sufficient
            else float(
                (
                    liquidity_valid["asset_return_5d"].lt(0.0)
                    & liquidity_valid["volume_5d_average"].ge(
                        liquidity_valid["volume_5d_prior_80pct"]
                    )
                ).mean()
            )
        )
        amihud = long["amihud_5d"].dropna()
        records.append(
            {
                "date": date_value,
                "formation_date": group["formation_date"].iloc[0],
                "effective_month": group["effective_month"].iloc[0],
                "long_decline_share_5d": (
                    float(long_returns.lt(0.0).mean())
                    if long_sufficient
                    else None
                ),
                "short_rise_share_5d": (
                    float(short_returns.gt(0.0).mean())
                    if short_sufficient
                    else None
                ),
                "long_downside_breach_share_5d": (
                    float(
                        long_returns.le(config.downside_return_gate).mean()
                    )
                    if long_sufficient
                    else None
                ),
                "downside_abnormal_volume_share_5d": (
                    downside_abnormal_volume_share
                ),
                "liquidity_eligible_long_count": liquidity_count,
                "long_median_amihud_5d": (
                    float(amihud.median())
                    if len(amihud) >= config.minimum_active_names
                    else None
                ),
                "liquidity_proxy_status": (
                    "available_proxy"
                    if liquidity_sufficient
                    else "unavailable"
                ),
            }
        )
    result = pd.DataFrame(records)
    return result.merge(
        correlations,
        on="date",
        how="left",
        validate="one_to_one",
    )


def build_unwind_fingerprint_history(
    risk_history: pd.DataFrame,
    constituent_returns: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    config: UnwindMonitorConfig = DEFAULT_UNWIND_CONFIG,
) -> pd.DataFrame:
    """Build the combined daily unwind fingerprint history."""

    legs = build_leg_unwind_history(risk_history, config=config)
    constituents = build_constituent_unwind_history(
        constituent_returns,
        prices,
        config=config,
    )
    result = legs.merge(
        constituents,
        on=["date", "formation_date", "effective_month"],
        how="left",
        validate="one_to_one",
    )
    result["classification_status"] = "current_snapshot_proxy"
    result["survivorship_bias"] = True
    for column in FINGERPRINT_HISTORY_COLUMNS:
        if column not in result:
            result[column] = pd.NA
    return result.loc[:, FINGERPRINT_HISTORY_COLUMNS].sort_values(
        "date"
    ).reset_index(drop=True)


def prior_only_quantile(
    history: pd.DataFrame,
    *,
    as_of_date: pd.Timestamp,
    column: str,
    quantile: float,
    min_observations: int,
    floor: float | None = None,
    ceiling: float | None = None,
) -> PriorOnlyThreshold:
    """Calculate a threshold strictly from observations before ``as_of_date``."""

    if not 0.0 < quantile < 1.0:
        raise ValueError("quantile must lie strictly between zero and one")
    if min_observations < 1:
        raise ValueError("min_observations must be positive")
    if "date" not in history or column not in history:
        raise KeyError(f"history requires date and {column}")
    dates = pd.to_datetime(history["date"]).dt.normalize()
    values = pd.to_numeric(
        history.loc[dates.lt(pd.Timestamp(as_of_date).normalize()), column],
        errors="coerce",
    ).dropna()
    if not np.isfinite(values).all():
        raise ValueError(f"{column} contains non-finite prior observations")
    count = int(len(values))
    if count < min_observations:
        return PriorOnlyThreshold(
            value=None,
            raw_value=None,
            provenance="insufficient_history",
            prior_observations=count,
            quantile=quantile,
            bound_applied=False,
        )
    raw = float(values.quantile(quantile, interpolation="linear"))
    value = raw
    bound_applied = False
    if floor is not None and value < floor:
        value = float(floor)
        bound_applied = True
    if ceiling is not None and value > ceiling:
        value = float(ceiling)
        bound_applied = True
    return PriorOnlyThreshold(
        value=value,
        raw_value=raw,
        provenance=(
            "demo_threshold"
            if bound_applied
            else "historical_proxy_threshold"
        ),
        prior_observations=count,
        quantile=quantile,
        bound_applied=bound_applied,
    )


def _optional_float(value: Any) -> float | None:
    if value is None or value is pd.NA or pd.isna(value):
        return None
    result = float(value)
    return result if np.isfinite(result) else None


def _greater_equal(value: float | None, threshold: float | None) -> bool | None:
    if value is None or threshold is None:
        return None
    return value > threshold or bool(
        np.isclose(value, threshold, rtol=0.0, atol=1e-12)
    )


def build_unwind_fingerprint_snapshot(
    history: pd.DataFrame,
    *,
    as_of_date: pd.Timestamp,
    config: UnwindMonitorConfig = DEFAULT_UNWIND_CONFIG,
) -> dict[str, Any]:
    """Build an auditable snapshot for the three core unwind mechanisms."""

    required = set(FINGERPRINT_HISTORY_COLUMNS)
    missing = sorted(required - set(history.columns))
    if missing:
        raise KeyError(f"fingerprint history missing required columns: {missing}")
    as_of_date = pd.Timestamp(as_of_date).normalize()
    dates = pd.to_datetime(history["date"]).dt.normalize()
    selected = history.loc[dates.eq(as_of_date)]
    if len(selected) != 1:
        raise ValueError(
            f"fingerprint history requires exactly one row for {iso_date(as_of_date)}"
        )
    row = selected.iloc[0]

    residual_threshold = prior_only_quantile(
        history,
        as_of_date=as_of_date,
        column="residual_long_loss_5d",
        quantile=config.residual_loss_quantile,
        min_observations=config.threshold_min_observations,
    )
    reversal_threshold = prior_only_quantile(
        history,
        as_of_date=as_of_date,
        column="short_minus_long_return_5d",
        quantile=config.reversal_quantile,
        min_observations=config.threshold_min_observations,
        floor=config.reversal_floor,
    )
    residual_loss = _optional_float(row["residual_long_loss_5d"])
    co_decline = _optional_float(row["long_decline_share_5d"])
    reversal = _optional_float(row["short_minus_long_return_5d"])
    liquidity_share = _optional_float(
        row["downside_abnormal_volume_share_5d"]
    )

    residual_extreme = _greater_equal(residual_loss, residual_threshold.value)
    co_decline_gate = _greater_equal(co_decline, config.co_decline_gate)
    synchronous_trigger = (
        None
        if residual_extreme is None or co_decline_gate is None
        else bool(residual_extreme and co_decline_gate)
    )
    reversal_trigger = _greater_equal(reversal, reversal_threshold.value)
    liquidity_trigger = _greater_equal(
        liquidity_share,
        config.liquidity_breadth_gate,
    )

    warnings = [
        "Sector-adjusted residual return is unavailable; only lagged-beta "
        "adjustment is implemented.",
        "Security history uses current-membership and current-classification "
        "proxies and is survivorship-biased.",
        "Liquidity fields are public volume and Amihud proxies, not direct "
        "evidence of leverage or forced selling.",
    ]
    if residual_threshold.value is None:
        warnings.append("Residual-loss threshold has insufficient prior history.")
    if reversal_threshold.value is None:
        warnings.append("Reversal threshold has insufficient prior history.")
    if liquidity_share is None:
        warnings.append("Liquidity proxy is unavailable for the selected date.")

    values = {
        column: _optional_float(row[column])
        for column in FINGERPRINT_HISTORY_COLUMNS
        if column
        not in {
            "date",
            "formation_date",
            "effective_month",
            "liquidity_proxy_status",
            "classification_status",
            "survivorship_bias",
        }
    }
    return {
        "as_of_date": iso_date(as_of_date),
        "values": values,
        "thresholds": {
            "residual_long_loss_5d": residual_threshold.to_dict(),
            "short_minus_long_return_5d": reversal_threshold.to_dict(),
            "long_decline_share_5d": {
                "value": config.co_decline_gate,
                "provenance": "demo_threshold",
            },
            "downside_abnormal_volume_share_5d": {
                "value": config.liquidity_breadth_gate,
                "provenance": "demo_threshold",
            },
        },
        "triggers": {
            "synchronous_winner_liquidation": synchronous_trigger,
            "cross_sectional_reversal": reversal_trigger,
            "liquidity_amplification_proxy": liquidity_trigger,
        },
        "liquidity_proxy_status": str(row["liquidity_proxy_status"]),
        "classification_status": str(row["classification_status"]),
        "survivorship_bias": bool(row["survivorship_bias"]),
        "warnings": warnings,
    }


def _less_equal(value: float | None, threshold: float | None) -> bool | None:
    if value is None or threshold is None:
        return None
    return value < threshold or bool(
        np.isclose(value, threshold, rtol=0.0, atol=1e-12)
    )


def _row_status(triggered: bool | None, provenance: str) -> str:
    if triggered is not None:
        return "available"
    return (
        "insufficient_history"
        if provenance == "insufficient_history"
        else "unavailable"
    )


def _row_severity(
    *,
    triggered: bool | None,
    elevated: bool = False,
) -> str:
    if triggered is None:
        return "unavailable"
    if triggered:
        return "high"
    return "elevated" if elevated else "normal"


def _json_clean(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return iso_date(value)
    if isinstance(value, pd.Period):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_clean(item) for item in value]
    if pd.isna(value):
        return None
    return value


def _scorecard_row(
    *,
    as_of_date: pd.Timestamp,
    monitor_family: str,
    metric: str,
    current_value: float | str | None,
    threshold: float | str | None,
    threshold_provenance: str,
    direction: str,
    triggered: bool | None,
    explanation: str,
    context: dict[str, Any],
    source_module: str,
    data_quality: str,
    elevated: bool = False,
) -> UnwindScorecardRow:
    return UnwindScorecardRow(
        as_of_date=iso_date(as_of_date),
        monitor_family=monitor_family,
        metric=metric,
        current_value=current_value,
        threshold=threshold,
        threshold_provenance=threshold_provenance,
        direction=direction,
        triggered=triggered,
        severity=_row_severity(triggered=triggered, elevated=elevated),
        status=_row_status(triggered, threshold_provenance),
        explanation=explanation,
        context=_json_clean(context),
        source_module=source_module,
        data_quality=data_quality,
    )


def classify_unwind_scenario(
    scorecard: tuple[UnwindScorecardRow, ...],
    *,
    high_volatility_recovery: bool | None,
) -> tuple[str, str, str]:
    """Apply the published deterministic scenario rules."""

    rows = {row.metric: row for row in scorecard}
    available_count = sum(row.status == "available" for row in scorecard)
    synchronous_available = (
        rows["synchronous_winner_liquidation"].status == "available"
    )
    reversal_available = rows["cross_sectional_reversal"].status == "available"
    if available_count < 4 or not (
        synchronous_available or reversal_available
    ):
        return (
            "insufficient_evidence",
            "Fewer than four rows are available, or both core unwind rows are unavailable.",
            "insufficient",
        )

    triggered = {
        metric: bool(row.triggered)
        for metric, row in rows.items()
        if row.triggered is not None
    }
    unwind_metrics = (
        "portfolio_concentration",
        "synchronous_winner_liquidation",
        "cross_sectional_reversal",
        "liquidity_amplification_proxy",
    )
    unwind_count = sum(triggered.get(metric, False) for metric in unwind_metrics)
    fundamental_deteriorating = triggered.get("fundamental_anchor", False)
    breadth = triggered.get("momentum_breadth_deterioration", False)

    if fundamental_deteriorating and unwind_count >= 2:
        scenario = "mixed_repricing_and_unwind"
        rule = (
            "Fundamentals are deteriorating and at least two observable unwind "
            "mechanisms are triggered."
        )
    elif (
        triggered.get("portfolio_concentration", False)
        and triggered.get("synchronous_winner_liquidation", False)
        and triggered.get("cross_sectional_reversal", False)
        and (breadth or triggered.get("liquidity_amplification_proxy", False))
    ):
        scenario = "crowded_momentum_unwind"
        rule = (
            "Concentration, synchronous winner liquidation, and reversal are "
            "triggered, with breadth or liquidity providing additional support."
        )
    elif (
        high_volatility_recovery is True
        and triggered.get("cross_sectional_reversal", False)
    ):
        scenario = "panic_recovery_momentum_crash"
        rule = (
            "The existing high-volatility-recovery gate and cross-sectional "
            "reversal are triggered without the crowded-unwind rule."
        )
    elif fundamental_deteriorating and breadth and unwind_count <= 1:
        scenario = "fundamental_repricing"
        rule = (
            "Fundamentals and breadth are deteriorating without broad support "
            "from unwind mechanisms."
        )
    else:
        scenario = "normal_drawdown"
        rule = (
            "Evidence is sufficiently complete, but no repricing, panic-recovery, "
            "or crowded-unwind rule is satisfied."
        )
    confidence = "high" if available_count == 6 else "moderate"
    return scenario, rule, confidence


def _condition(
    *,
    name: str,
    value: float | bool | str | None,
    threshold: float | bool | str | None,
    direction: str,
    met: bool | None,
    required: bool,
    source_component: str,
) -> ScenarioCondition:
    return ScenarioCondition(
        name=name,
        value=value,
        threshold=threshold,
        direction=direction,
        met=met,
        required=required,
        source_component=source_component,
    )


def _nullable_or(left: bool | None, right: bool | None) -> bool | None:
    if left is True or right is True:
        return True
    if left is False and right is False:
        return False
    return None


def _mechanism(
    scenario: str,
    conditions: tuple[ScenarioCondition, ...],
    *,
    triggered_summary: str,
    watch_summary: str,
    normal_summary: str,
) -> MechanismScenario:
    required = tuple(condition.met for condition in conditions if condition.required)
    if all(value is True for value in required):
        status = "triggered"
        summary = triggered_summary
    elif any(value is False for value in required):
        if any(value is True for value in required):
            status = "watch"
            summary = watch_summary
        else:
            status = "not_confirmed"
            summary = normal_summary
    else:
        status = "unavailable"
        summary = "Required point-in-time evidence is unavailable."
    if status == "unavailable" and any(value is True for value in required):
        status = "watch"
        summary = watch_summary
    return MechanismScenario(
        scenario=scenario,
        status=status,
        conditions=conditions,
        supporting_evidence=tuple(
            condition.name for condition in conditions if condition.met is True
        ),
        contradictory_evidence=tuple(
            condition.name
            for condition in conditions
            if condition.required and condition.met is False
        ),
        missing_evidence=tuple(
            condition.name
            for condition in conditions
            if condition.required and condition.met is None
        ),
        summary=summary,
    )


def classify_momentum_crash_scenarios(
    scorecard: tuple[UnwindScorecardRow, ...],
    *,
    regime_context: dict[str, Any],
    signed_short_beta: float | None,
    signed_short_beta_threshold: float | None,
    theme_snapshot: ThemeConcentrationSnapshot,
    config: UnwindMonitorConfig = DEFAULT_UNWIND_CONFIG,
) -> tuple[MechanismScenario, ...]:
    """Evaluate three independent, potentially simultaneous crash mechanisms."""

    rows = {row.metric: row for row in scorecard}
    reversal_row = rows["cross_sectional_reversal"]
    short_rise_share = _optional_float(
        reversal_row.context.get("short_rise_share_5d")
    )
    short_rise_met = _greater_equal(short_rise_share, config.short_rise_gate)
    signed_beta_met = (
        None
        if signed_short_beta is None or signed_short_beta_threshold is None
        else _less_equal(signed_short_beta, signed_short_beta_threshold)
    )

    recent_severe_drawdown = _optional_bool(
        regime_context.get("recent_severe_drawdown")
    )
    recovery_from_trough = _optional_float(
        regime_context.get("recovery_from_trough_126d")
    )
    trough_age = _optional_float(
        regime_context.get("trough_age_trading_days")
    )
    recovery_met = (
        None
        if recovery_from_trough is None or trough_age is None
        else bool(
            recovery_from_trough >= RECOVERY_FROM_TROUGH_THRESHOLD
            and 1 <= trough_age <= EARLY_RECOVERY_MAX_AGE
        )
    )
    high_volatility = _optional_bool(regime_context.get("high_volatility"))
    bear_conditions = (
        _condition(
            name="recent_severe_market_drawdown",
            value=_optional_float(
                regime_context.get("recent_min_drawdown_126d")
            ),
            threshold=SEVERE_DRAWDOWN_THRESHOLD,
            direction="less_than_or_equal",
            met=recent_severe_drawdown,
            required=True,
            source_component="src.regime.market_state",
        ),
        _condition(
            name="rapid_recovery_from_trough",
            value=recovery_from_trough,
            threshold=(
                f">={RECOVERY_FROM_TROUGH_THRESHOLD:.0%} within "
                f"{EARLY_RECOVERY_MAX_AGE} trading days"
            ),
            direction="rule_based",
            met=recovery_met,
            required=True,
            source_component="src.regime.market_state",
        ),
        _condition(
            name="high_realized_market_volatility",
            value=_optional_float(
                regime_context.get("realized_volatility_21d")
            ),
            threshold=_optional_float(
                regime_context.get("realized_volatility_threshold_80pct")
            ),
            direction="greater_than_or_equal",
            met=high_volatility,
            required=True,
            source_component="src.regime.market_state",
        ),
    )
    short_conditions = (
        _condition(
            name="short_minus_long_reversal_extreme",
            value=(
                _optional_float(reversal_row.current_value)
                if not isinstance(reversal_row.current_value, str)
                else None
            ),
            threshold=(
                _optional_float(reversal_row.threshold)
                if not isinstance(reversal_row.threshold, str)
                else None
            ),
            direction="greater_than_or_equal",
            met=reversal_row.triggered,
            required=True,
            source_component="cross_sectional_reversal",
        ),
        _condition(
            name="short_book_rise_breadth",
            value=short_rise_share,
            threshold=config.short_rise_gate,
            direction="greater_than_or_equal",
            met=short_rise_met,
            required=True,
            source_component="src.monitoring.unwind_structure",
        ),
        _condition(
            name="signed_short_beta_tail",
            value=signed_short_beta,
            threshold=signed_short_beta_threshold,
            direction="less_than_or_equal",
            met=signed_beta_met,
            required=False,
            source_component="src.risk.leg_decomposition",
        ),
    )

    pre_event_cluster_met = (
        None
        if theme_snapshot.status != "available"
        else bool(
            theme_snapshot.cluster_size
            >= theme_snapshot.audit_metadata["minimum_cluster_size"]
            and theme_snapshot.cluster_exposure_share is not None
            and theme_snapshot.cluster_exposure_share
            >= theme_snapshot.audit_metadata["cluster_exposure_gate"]
        )
    )
    theme_loss_met = (
        None
        if theme_snapshot.cluster_residual_loss_5d is None
        or theme_snapshot.residual_loss_threshold is None
        else _greater_equal(
            theme_snapshot.cluster_residual_loss_5d,
            theme_snapshot.residual_loss_threshold,
        )
    )
    theme_decline_met = (
        None
        if theme_snapshot.cluster_decline_share_5d is None
        else _greater_equal(
            theme_snapshot.cluster_decline_share_5d,
            theme_snapshot.audit_metadata["decline_share_gate"],
        )
    )
    loss_contribution_met = (
        None
        if theme_snapshot.cluster_loss_contribution_share_5d is None
        else _greater_equal(
            theme_snapshot.cluster_loss_contribution_share_5d,
            theme_snapshot.audit_metadata["loss_contribution_gate"],
        )
    )
    volume_confirmation_met = (
        None
        if theme_snapshot.cluster_abnormal_volume_share_5d is None
        else _greater_equal(
            theme_snapshot.cluster_abnormal_volume_share_5d,
            theme_snapshot.audit_metadata["abnormal_volume_share_gate"],
        )
    )
    liquidation_confirmation = _nullable_or(
        loss_contribution_met,
        volume_confirmation_met,
    )
    if pre_event_cluster_met is False:
        theme_loss_met = False
        theme_decline_met = False
        liquidation_confirmation = False
    theme_conditions = (
        _condition(
            name="pre_event_correlated_cluster_concentration",
            value=theme_snapshot.cluster_exposure_share,
            threshold=theme_snapshot.audit_metadata.get("cluster_exposure_gate"),
            direction="greater_than_or_equal",
            met=pre_event_cluster_met,
            required=True,
            source_component="src.risk.theme_concentration",
        ),
        _condition(
            name="cluster_residual_loss_extreme",
            value=theme_snapshot.cluster_residual_loss_5d,
            threshold=theme_snapshot.residual_loss_threshold,
            direction="greater_than_or_equal",
            met=theme_loss_met,
            required=True,
            source_component="src.risk.theme_concentration",
        ),
        _condition(
            name="cluster_decline_breadth",
            value=theme_snapshot.cluster_decline_share_5d,
            threshold=theme_snapshot.audit_metadata.get("decline_share_gate"),
            direction="greater_than_or_equal",
            met=theme_decline_met,
            required=True,
            source_component="src.risk.theme_concentration",
        ),
        _condition(
            name="cluster_loss_or_volume_confirmation",
            value=(
                "loss_contribution="
                f"{theme_snapshot.cluster_loss_contribution_share_5d};"
                "abnormal_volume="
                f"{theme_snapshot.cluster_abnormal_volume_share_5d}"
            ),
            threshold="loss contribution >= gate OR abnormal volume >= gate",
            direction="rule_based",
            met=liquidation_confirmation,
            required=True,
            source_component="src.risk.theme_concentration",
        ),
    )

    return (
        _mechanism(
            "bear_market_recovery_crash",
            bear_conditions,
            triggered_summary=(
                "A severe bear-market drawdown, rapid recovery, and high "
                "realized volatility are jointly present."
            ),
            watch_summary=(
                "Some bear-market-recovery preconditions are present, but the "
                "three-part mechanism is not confirmed."
            ),
            normal_summary="Bear-market-recovery conditions are not present.",
        ),
        _mechanism(
            "short_book_reversal_crash",
            short_conditions,
            triggered_summary=(
                "Prior losers are reversing broadly and outperforming prior "
                "winners at an extreme rate."
            ),
            watch_summary=(
                "One short-book reversal condition is present, but the "
                "two-part mechanism is not confirmed."
            ),
            normal_summary="Short-book reversal conditions are not present.",
        ),
        _mechanism(
            "crowded_theme_unwind",
            theme_conditions,
            triggered_summary=(
                "A pre-event correlated long cluster is concentrated and is "
                "experiencing broad, extreme, loss- or volume-confirmed selling."
            ),
            watch_summary=(
                "Some correlated-theme conditions are present, but the "
                "liquidation proxy is not fully confirmed."
            ),
            normal_summary="Correlated-theme unwind conditions are not present.",
        ),
    )


def legacy_scenario_from_mechanisms(
    mechanisms: tuple[MechanismScenario, ...],
    scorecard: tuple[UnwindScorecardRow, ...],
    *,
    high_volatility_recovery: bool | None,
) -> tuple[str, str, str]:
    """Map v2 multi-label mechanisms onto the retained v1 single label."""

    active = tuple(
        mechanism.scenario
        for mechanism in mechanisms
        if mechanism.status == "triggered"
    )
    available_count = sum(row.status == "available" for row in scorecard)
    confidence = "high" if available_count == 6 else "moderate"
    if len(active) > 1:
        return (
            "mixed_repricing_and_unwind",
            "Compatibility view: multiple independent v2 mechanisms trigger.",
            confidence,
        )
    if active == ("bear_market_recovery_crash",):
        return (
            "panic_recovery_momentum_crash",
            "Compatibility view of the v2 bear-market-recovery mechanism.",
            confidence,
        )
    if active == ("crowded_theme_unwind",):
        return (
            "crowded_momentum_unwind",
            "Compatibility view of the v2 correlated-theme unwind mechanism.",
            confidence,
        )
    if active == ("short_book_reversal_crash",):
        return (
            "normal_drawdown",
            "Compatibility view has no v1 short-only label; inspect active_scenarios.",
            confidence,
        )
    return classify_unwind_scenario(
        scorecard,
        high_volatility_recovery=high_volatility_recovery,
    )


def _build_monitor_histories(
    *,
    processed_dir: Path,
    config: UnwindMonitorConfig,
) -> dict[str, pd.DataFrame]:
    prices = pd.read_parquet(processed_dir / "sp500_prices.parquet")
    holdings = pd.read_parquet(
        processed_dir / "momentum_portfolio_holdings.parquet"
    )
    risk = pd.read_parquet(processed_dir / "leg_risk_history.parquet")
    universe = pd.read_parquet(processed_dir / "sp500_universe.parquet")
    benchmark = pd.read_parquet(processed_dir / "sp500_benchmark.parquet")
    research_factors = pd.read_parquet(
        processed_dir / "french_research_factors_daily.parquet"
    )
    constituent = build_constituent_return_history(prices, holdings)
    return {
        "prices": prices,
        "holdings": holdings,
        "risk": risk,
        "universe": universe,
        "benchmark": benchmark,
        "regime": build_regime_history(research_factors),
        "constituent": constituent,
        "concentration": build_concentration_history(
            constituent,
            universe.loc[:, ["symbol", "sector"]],
        ),
        "breadth": build_momentum_breadth_history(
            prices,
            universe=universe,
            holdings=holdings,
        ),
        "rebalance": build_rebalance_diagnostics(holdings),
        "fingerprint": build_unwind_fingerprint_history(
            risk,
            constituent,
            prices,
            config=config,
        ),
    }


def _selected_row(
    frame: pd.DataFrame,
    *,
    date_column: str,
    selected_date: pd.Timestamp,
    name: str,
) -> pd.Series:
    dates = pd.to_datetime(frame[date_column]).dt.normalize()
    selected = frame.loc[dates.eq(pd.Timestamp(selected_date).normalize())]
    if len(selected) != 1:
        raise ValueError(
            f"{name} requires exactly one row for {iso_date(selected_date)}"
        )
    return selected.iloc[0]


def _optional_bool(value: Any) -> bool | None:
    if value is None or value is pd.NA or pd.isna(value):
        return None
    return bool(value)


def _assemble_unwind_assessment(
    histories: dict[str, pd.DataFrame],
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path,
    raw_dir: Path,
    company_coverage: pd.DataFrame | None,
    load_fundamentals: bool,
    config: UnwindMonitorConfig,
    theme_config: ThemeConcentrationConfig,
) -> UnwindAssessment:
    as_of_date = pd.Timestamp(as_of_date).normalize()
    risk = histories["risk"].copy()
    risk["date"] = pd.to_datetime(risk["date"]).dt.normalize()
    risk_row = _selected_row(
        risk,
        date_column="date",
        selected_date=as_of_date,
        name="risk history",
    )
    formation_date = pd.Timestamp(risk_row["formation_date"]).normalize()
    theme_snapshot = build_theme_concentration_snapshot(
        histories["prices"],
        histories["holdings"],
        histories["benchmark"],
        as_of_date=as_of_date,
        universe=histories["universe"],
        config=theme_config,
    )
    regime = histories["regime"].copy()
    regime["date"] = pd.to_datetime(regime["date"]).dt.normalize()
    regime_selected = regime.loc[regime["date"].eq(as_of_date)]
    regime_context = (
        regime_selected.iloc[0].to_dict()
        if len(regime_selected) == 1
        else {}
    )
    risk_for_beta = risk.copy()
    risk_for_beta["signed_short_beta_126d"] = -pd.to_numeric(
        risk_for_beta["short_underlying_beta_126d"],
        errors="coerce",
    )
    signed_short_beta = _optional_float(
        -risk_row["short_underlying_beta_126d"]
    )
    signed_short_beta_threshold = prior_only_quantile(
        risk_for_beta,
        as_of_date=as_of_date,
        column="signed_short_beta_126d",
        quantile=config.short_beta_quantile,
        min_observations=config.threshold_min_observations,
    )

    concentration = histories["concentration"]
    concentration_row = _selected_row(
        concentration,
        date_column="date",
        selected_date=as_of_date,
        name="concentration history",
    )
    concentration_threshold = prior_only_quantile(
        concentration,
        as_of_date=as_of_date,
        column="effective_bets_abs_exposure",
        quantile=config.concentration_quantile,
        min_observations=config.threshold_min_observations,
    )
    concentration_value = _optional_float(
        concentration_row["effective_bets_abs_exposure"]
    )
    concentration_trigger = _less_equal(
        concentration_value,
        concentration_threshold.value,
    )
    rebalance_context = histories["rebalance"].loc[
        pd.to_datetime(histories["rebalance"]["formation_date"])
        .dt.normalize()
        .eq(formation_date)
    ]

    breadth = histories["breadth"]
    breadth_row = _selected_row(
        breadth,
        date_column="formation_date",
        selected_date=formation_date,
        name="breadth history",
    )
    breadth_for_threshold = breadth.rename(
        columns={"formation_date": "date"}
    )
    breadth_threshold = prior_only_quantile(
        breadth_for_threshold,
        as_of_date=formation_date,
        column="universe_positive_12_1_share",
        quantile=config.breadth_quantile,
        min_observations=config.breadth_min_observations,
    )
    breadth_value = _optional_float(
        breadth_row["universe_positive_12_1_share"]
    )
    breadth_trigger = _less_equal(breadth_value, breadth_threshold.value)

    fingerprint_snapshot = build_unwind_fingerprint_snapshot(
        histories["fingerprint"],
        as_of_date=as_of_date,
        config=config,
    )
    fingerprint_values = fingerprint_snapshot["values"]
    fingerprint_thresholds = fingerprint_snapshot["thresholds"]
    fingerprint_triggers = fingerprint_snapshot["triggers"]

    supplied_coverage = (
        company_coverage
        if load_fundamentals
        else pd.DataFrame()
    )
    fundamental: FundamentalAnchor = build_fundamental_anchor_for_date(
        as_of_date=as_of_date,
        processed_dir=processed_dir,
        raw_dir=raw_dir,
        company_coverage=(
            supplied_coverage
            if company_coverage is not None or not load_fundamentals
            else None
        ),
    )

    rows = (
        _scorecard_row(
            as_of_date=as_of_date,
            monitor_family="portfolio_structure",
            metric="portfolio_concentration",
            current_value=concentration_value,
            threshold=concentration_threshold.value,
            threshold_provenance=concentration_threshold.provenance,
            direction="less_than_or_equal",
            triggered=concentration_trigger,
            explanation=(
                "Gross-normalized effective bets use drifted beginning-of-day "
                "exposure; lower values indicate greater concentration."
            ),
            context={
                "top3_abs_exposure_share": _optional_float(
                    concentration_row["top3_abs_exposure_share"]
                ),
                "top5_abs_exposure_share": _optional_float(
                    concentration_row["top5_abs_exposure_share"]
                ),
                "top5_abs_contribution_share": _optional_float(
                    concentration_row["top5_abs_contribution_share"]
                ),
                "top5_loss_contribution_share": _optional_float(
                    concentration_row["top5_loss_contribution_share"]
                ),
                "sector_hhi": _optional_float(concentration_row["sector_hhi"]),
                "top_sector_exposure_share": _optional_float(
                    concentration_row["top_sector_exposure_share"]
                ),
                "top5_exposure_loss_overlap_share": _optional_float(
                    concentration_row["top5_exposure_loss_overlap_share"]
                ),
                "rebalance_diagnostics": rebalance_context.to_dict(
                    orient="records"
                ),
            },
            source_module="src.risk.concentration",
            data_quality="current_membership_and_classification_proxy",
        ),
        _scorecard_row(
            as_of_date=as_of_date,
            monitor_family="market_breadth",
            metric="momentum_breadth_deterioration",
            current_value=breadth_value,
            threshold=breadth_threshold.value,
            threshold_provenance=breadth_threshold.provenance,
            direction="less_than_or_equal",
            triggered=breadth_trigger,
            explanation=(
                "The share of the eligible universe with positive 12-1 momentum "
                "is compared with its strictly prior monthly history."
            ),
            context={
                "formation_date": iso_date(formation_date),
                "breadth_change_vs_previous": _optional_float(
                    breadth_row["breadth_change_vs_previous"]
                ),
                "breadth_change_vs_prior_3_rebalance_high": _optional_float(
                    breadth_row["breadth_change_vs_prior_3_rebalance_high"]
                ),
                "long_21d_participation_share": _optional_float(
                    breadth_row["long_21d_participation_share"]
                ),
                "positive_momentum_leadership_hhi": _optional_float(
                    breadth_row["positive_momentum_leadership_hhi"]
                ),
                "top10_positive_momentum_share": _optional_float(
                    breadth_row["top10_positive_momentum_share"]
                ),
                "long_entry_count": _optional_float(
                    breadth_row["long_entry_count"]
                ),
                "long_exit_count": _optional_float(
                    breadth_row["long_exit_count"]
                ),
            },
            source_module="src.features.momentum_breadth",
            data_quality="current_membership_proxy",
        ),
        _scorecard_row(
            as_of_date=as_of_date,
            monitor_family="winner_liquidation",
            metric="synchronous_winner_liquidation",
            current_value=fingerprint_values["residual_long_loss_5d"],
            threshold=fingerprint_thresholds["residual_long_loss_5d"]["value"],
            threshold_provenance=fingerprint_thresholds[
                "residual_long_loss_5d"
            ]["provenance"],
            direction="greater_than_or_equal",
            triggered=fingerprint_triggers[
                "synchronous_winner_liquidation"
            ],
            explanation=(
                "An extreme five-day lagged-beta-adjusted long loss must coincide "
                "with broad active-long declines."
            ),
            context={
                "long_return_5d": fingerprint_values["long_return_5d"],
                "beta_adjusted_long_return_5d": fingerprint_values[
                    "beta_adjusted_long_return_5d"
                ],
                "long_decline_share_5d": fingerprint_values[
                    "long_decline_share_5d"
                ],
                "co_decline_gate": config.co_decline_gate,
                "long_average_pairwise_correlation_21d": fingerprint_values[
                    "long_average_pairwise_correlation_21d"
                ],
                "long_pairwise_correlation_change": fingerprint_values[
                    "long_pairwise_correlation_change"
                ],
                "sector_adjustment": "unavailable",
            },
            source_module="src.monitoring.unwind_structure",
            data_quality="current_membership_proxy",
        ),
        _scorecard_row(
            as_of_date=as_of_date,
            monitor_family="cross_sectional_reversal",
            metric="cross_sectional_reversal",
            current_value=fingerprint_values["short_minus_long_return_5d"],
            threshold=fingerprint_thresholds[
                "short_minus_long_return_5d"
            ]["value"],
            threshold_provenance=fingerprint_thresholds[
                "short_minus_long_return_5d"
            ]["provenance"],
            direction="greater_than_or_equal",
            triggered=fingerprint_triggers["cross_sectional_reversal"],
            explanation=(
                "Positive short-underlying-minus-long return means prior losers "
                "outperformed prior winners over five trading days."
            ),
            context={
                "long_return_5d": fingerprint_values["long_return_5d"],
                "short_underlying_return_5d": fingerprint_values[
                    "short_underlying_return_5d"
                ],
                "long_minus_short_return_5d": fingerprint_values[
                    "long_minus_short_return_5d"
                ],
                "long_decline_share_5d": fingerprint_values[
                    "long_decline_share_5d"
                ],
                "short_rise_share_5d": fingerprint_values[
                    "short_rise_share_5d"
                ],
            },
            source_module="src.monitoring.unwind_structure",
            data_quality="current_membership_proxy",
        ),
        _scorecard_row(
            as_of_date=as_of_date,
            monitor_family="liquidity_proxy",
            metric="liquidity_amplification_proxy",
            current_value=fingerprint_values[
                "downside_abnormal_volume_share_5d"
            ],
            threshold=config.liquidity_breadth_gate,
            threshold_provenance="demo_threshold",
            direction="greater_than_or_equal",
            triggered=fingerprint_triggers["liquidity_amplification_proxy"],
            explanation=(
                "This public-data proxy counts active long names falling while "
                "five-day volume exceeds each name's prior-only threshold."
            ),
            context={
                "liquidity_eligible_long_count": fingerprint_values[
                    "liquidity_eligible_long_count"
                ],
                "long_median_amihud_5d": fingerprint_values[
                    "long_median_amihud_5d"
                ],
                "proxy_status": fingerprint_snapshot[
                    "liquidity_proxy_status"
                ],
            },
            source_module="src.monitoring.unwind_structure",
            data_quality=fingerprint_snapshot["liquidity_proxy_status"],
        ),
        _scorecard_row(
            as_of_date=as_of_date,
            monitor_family="fundamental_context",
            metric="fundamental_anchor",
            current_value=(
                None if fundamental.status == "unavailable" else fundamental.status
            ),
            threshold="coverage-gated sign-vote rule",
            threshold_provenance="demo_threshold",
            direction="rule_based",
            triggered=fundamental.triggered,
            explanation=(
                "Revenue acceleration, applicable operating-margin change, and "
                "optional EPS acceleration provide a lightweight sign-based anchor."
            ),
            context={
                "formation_date": fundamental.formation_date,
                "long_covered_count": fundamental.long_covered_count,
                "short_covered_count": fundamental.short_covered_count,
                "long_support_share": fundamental.long_support_share,
                "short_improving_share": fundamental.short_improving_share,
                "revenue_support_share": fundamental.revenue_support_share,
                "margin_support_share": fundamental.margin_support_share,
                "contradiction_names": list(fundamental.contradiction_names),
                "missing_names": list(fundamental.missing_names),
            },
            source_module=(
                "src.monitoring.fundamental_anchor + "
                "src.data.sec_fundamentals"
            ),
            data_quality=(
                "unavailable"
                if fundamental.status == "unavailable"
                else (
                    f"long={fundamental.long_coverage_status};"
                    f"short={fundamental.short_coverage_status};"
                    "current_classification_proxy"
                )
            ),
            elevated=fundamental.status == "mixed",
        ),
    )
    high_volatility_recovery = _optional_bool(
        risk_row.get("high_volatility_recovery_state")
    )
    mechanisms = classify_momentum_crash_scenarios(
        rows,
        regime_context=regime_context,
        signed_short_beta=signed_short_beta,
        signed_short_beta_threshold=signed_short_beta_threshold.value,
        theme_snapshot=theme_snapshot,
        config=config,
    )
    active_scenarios = tuple(
        mechanism.scenario
        for mechanism in mechanisms
        if mechanism.status == "triggered"
    )
    scenario, rule, confidence = legacy_scenario_from_mechanisms(
        mechanisms,
        rows,
        high_volatility_recovery=high_volatility_recovery,
    )
    supporting = tuple(
        row.metric for row in rows if row.triggered is True
    ) + (
        ("high_volatility_recovery",)
        if high_volatility_recovery is True
        else ()
    )
    contradictory = tuple(
        row.metric
        for row in rows
        if row.status == "available" and row.triggered is False
    )
    missing = tuple(
        row.metric for row in rows if row.status != "available"
    )
    warnings = tuple(
        dict.fromkeys(
            [
                *fingerprint_snapshot["warnings"],
                *fundamental.warnings,
                *theme_snapshot.warnings,
                "No composite probability is calculated from the six rows.",
                "scenario_classification is a lossy v1 compatibility view; "
                "use mechanism_scenarios for the v2 result.",
            ]
        )
    )
    return UnwindAssessment(
        schema_version=UNWIND_SCHEMA_VERSION,
        as_of_date=iso_date(as_of_date),
        scorecard=rows,
        mechanism_scenarios=mechanisms,
        active_scenarios=active_scenarios,
        theme_concentration=theme_snapshot,
        scenario_classification=scenario,
        scenario_rule=rule,
        completeness_confidence=confidence,
        supporting_evidence=supporting,
        contradictory_evidence=contradictory,
        missing_evidence=missing,
        warnings=warnings,
        audit_metadata={
            "formation_date": iso_date(formation_date),
            "available_rows": sum(row.status == "available" for row in rows),
            "scorecard_rows": len(rows),
            "high_volatility_recovery": high_volatility_recovery,
            "signed_short_beta_126d": signed_short_beta,
            "signed_short_beta_prior_20pct": (
                signed_short_beta_threshold.to_dict()
            ),
            "mechanism_scenario_count": len(mechanisms),
            "active_scenario_count": len(active_scenarios),
            "legacy_schema_version": LEGACY_UNWIND_SCHEMA_VERSION,
            "legacy_scenario_is_lossy": True,
            "fundamental_formation_date": fundamental.formation_date,
            "threshold_min_observations": config.threshold_min_observations,
            "breadth_min_observations": config.breadth_min_observations,
            "no_composite_probability": True,
            "forward_rebound_in_live_assessment": False,
        },
    )


def build_unwind_assessment(
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    raw_dir: Path = DEFAULT_RAW_DIR,
    company_coverage: pd.DataFrame | None = None,
    load_fundamentals: bool = False,
    config: UnwindMonitorConfig = DEFAULT_UNWIND_CONFIG,
    theme_config: ThemeConcentrationConfig = DEFAULT_THEME_CONFIG,
) -> UnwindAssessment:
    """Build the complete six-row unwind assessment for one exact date.

    The default path is intentionally read-only and demo-safe: the fundamental
    row is unavailable unless exact-date ``company_coverage`` is supplied.
    Setting ``load_fundamentals=True`` explicitly opts into the slower local
    SEC Company Facts parse when no coverage frame is supplied.
    """

    histories = _build_monitor_histories(
        processed_dir=processed_dir,
        config=config,
    )
    return _assemble_unwind_assessment(
        histories,
        as_of_date=as_of_date,
        processed_dir=processed_dir,
        raw_dir=raw_dir,
        company_coverage=company_coverage,
        load_fundamentals=load_fundamentals,
        config=config,
        theme_config=theme_config,
    )


def evaluate_historical_rebound(
    portfolio_returns: pd.DataFrame,
    *,
    event_date: pd.Timestamp,
) -> tuple[dict[str, Any], ...]:
    """Evaluate forward 1/3/5-day returns for historical analysis only."""

    required = {
        "date",
        "long_basket_return",
        "short_basket_underlying_return",
    }
    missing = sorted(required - set(portfolio_returns.columns))
    if missing:
        raise KeyError(f"portfolio returns missing required columns: {missing}")
    frame = portfolio_returns.loc[:, sorted(required)].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame = frame.sort_values("date").reset_index(drop=True)
    event_date = pd.Timestamp(event_date).normalize()
    matches = frame.index[frame["date"].eq(event_date)]
    if len(matches) != 1:
        raise ValueError("event_date must identify exactly one portfolio row")
    event_index = int(matches[0])
    records: list[dict[str, Any]] = []
    for window in (1, 3, 5):
        forward = frame.iloc[event_index + 1 : event_index + 1 + window]
        if len(forward) != window:
            long_return = None
            short_return = None
            long_minus_short = None
        else:
            long_return = float(
                (1.0 + forward["long_basket_return"]).prod() - 1.0
            )
            short_return = float(
                (1.0 + forward["short_basket_underlying_return"]).prod() - 1.0
            )
            long_minus_short = long_return - short_return
        records.append(
            {
                "evaluation_mode": "historical_post_event",
                "event_date": iso_date(event_date),
                "forward_window": window,
                "long_return": long_return,
                "short_underlying_return": short_return,
                "long_minus_short_return": long_minus_short,
                "data_available_through": iso_date(frame["date"].max()),
            }
        )
    return tuple(records)


def run_unwind_assessment(
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    raw_dir: Path = DEFAULT_RAW_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR / "unwind_structure",
    load_fundamentals: bool = False,
    config: UnwindMonitorConfig = DEFAULT_UNWIND_CONFIG,
    theme_config: ThemeConcentrationConfig = DEFAULT_THEME_CONFIG,
) -> UnwindAssessment:
    """Build and persist histories plus one exact-date assessment."""

    histories = _build_monitor_histories(
        processed_dir=processed_dir,
        config=config,
    )
    assessment = _assemble_unwind_assessment(
        histories,
        as_of_date=as_of_date,
        processed_dir=processed_dir,
        raw_dir=raw_dir,
        company_coverage=None,
        load_fundamentals=load_fundamentals,
        config=config,
        theme_config=theme_config,
    )
    write_parquet(
        histories["breadth"],
        processed_dir / "momentum_breadth_history.parquet",
    )
    write_parquet(
        histories["fingerprint"],
        processed_dir / "unwind_structure_history.parquet",
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    date_label = assessment.as_of_date
    scorecard = pd.DataFrame(
        [
            {
                **row.to_dict(),
                "context": json.dumps(
                    row.context,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
            }
            for row in assessment.scorecard
        ]
    )
    atomic_write_bytes(
        output_dir / f"unwind_scorecard_{date_label}.csv",
        scorecard.to_csv(index=False).encode("utf-8"),
    )
    write_json(
        output_dir / f"unwind_assessment_{date_label}.json",
        assessment.to_dict(),
    )
    write_json(
        output_dir / "unwind_audit.json",
        {
            "schema_version": assessment.schema_version,
            "as_of_date": assessment.as_of_date,
            "breadth_rows": len(histories["breadth"]),
            "fingerprint_rows": len(histories["fingerprint"]),
            "mechanism_statuses": {
                item.scenario: item.status
                for item in assessment.mechanism_scenarios
            },
            "active_scenarios": list(assessment.active_scenarios),
            "theme_proxy_schema": (
                assessment.theme_concentration.schema_version
            ),
            "theme_cluster_definition_cutoff": (
                assessment.theme_concentration.cluster_definition_cutoff
            ),
            "assessment": assessment.audit_metadata,
        },
    )
    return assessment


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "unwind_structure",
    )
    parser.add_argument(
        "--parse-fundamentals",
        action="store_true",
        help=(
            "Opt into the slower exact-date local SEC Company Facts parse. "
            "Without this flag, the fundamental row is explicitly unavailable."
        ),
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    assessment = run_unwind_assessment(
        as_of_date=parse_as_of_date(args.as_of_date),
        processed_dir=args.processed_dir,
        raw_dir=args.raw_dir,
        output_dir=args.output_dir,
        load_fundamentals=args.parse_fundamentals,
    )
    print(json.dumps(assessment.to_dict(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
