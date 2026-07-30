"""Point-in-time correlated-theme proxies for the active momentum long book.

The calculations in this module use only existing public price, benchmark,
volume, holdings, and current-classification data.  They do not observe common
ownership, leverage, financing, or forced sales.  A detected cluster is
therefore labeled a ``correlated_theme_proxy`` rather than an economic theme.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


THEME_PROXY_VERSION = "correlated-theme-proxy-v1"
THEME_PROXY_STATUSES = frozenset(
    {"available", "unavailable", "insufficient_history"}
)


@dataclass(frozen=True)
class ThemeConcentrationConfig:
    """Windows and explicit proxy gates for correlated-theme monitoring."""

    correlation_window: int = 63
    correlation_quantile: float = 0.75
    correlation_floor: float = 0.50
    minimum_pair_observations: int = 42
    minimum_cluster_size: int = 3
    cluster_exposure_gate: float = 0.30
    event_window: int = 5
    loss_quantile: float = 0.80
    loss_threshold_min_observations: int = 63
    decline_share_gate: float = 0.70
    loss_contribution_gate: float = 0.50
    volume_quantile: float = 0.80
    volume_min_observations: int = 63
    abnormal_volume_share_gate: float = 0.50

    def __post_init__(self) -> None:
        for name in (
            "correlation_window",
            "minimum_pair_observations",
            "minimum_cluster_size",
            "event_window",
            "loss_threshold_min_observations",
            "volume_min_observations",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        if self.minimum_cluster_size < 2:
            raise ValueError("minimum_cluster_size must be at least two")
        if self.minimum_pair_observations > self.correlation_window:
            raise ValueError(
                "minimum_pair_observations cannot exceed correlation_window"
            )
        for name in (
            "correlation_quantile",
            "loss_quantile",
            "volume_quantile",
        ):
            if not 0.0 < getattr(self, name) < 1.0:
                raise ValueError(f"{name} must lie strictly between zero and one")
        for name in (
            "correlation_floor",
            "cluster_exposure_gate",
            "decline_share_gate",
            "loss_contribution_gate",
            "abnormal_volume_share_gate",
        ):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must lie between zero and one")


DEFAULT_THEME_CONFIG = ThemeConcentrationConfig()


@dataclass(frozen=True)
class ThemeConcentrationSnapshot:
    """Validated selected-date correlated-theme proxy."""

    schema_version: str
    as_of_date: str
    formation_date: str
    cluster_definition_cutoff: str
    status: str
    proxy_label: str
    active_long_symbols: tuple[str, ...]
    cluster_symbols: tuple[str, ...]
    cluster_size: int
    cluster_exposure_share: float | None
    cluster_average_residual_correlation: float | None
    correlation_threshold: float | None
    sector_count: int | None
    sector_entropy: float | None
    holding_persistence_share: float | None
    cluster_residual_loss_5d: float | None
    residual_loss_threshold: float | None
    residual_loss_prior_observations: int
    cluster_decline_share_5d: float | None
    cluster_loss_contribution_share_5d: float | None
    cluster_abnormal_volume_share_5d: float | None
    cluster_median_amihud_5d: float | None
    trigger: bool | None
    warnings: tuple[str, ...]
    audit_metadata: dict[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != THEME_PROXY_VERSION:
            raise ValueError("unsupported theme proxy schema")
        if self.status not in THEME_PROXY_STATUSES:
            raise ValueError("unsupported theme proxy status")
        if self.proxy_label != "correlated_theme_proxy":
            raise ValueError("theme proxy label must remain explicit")
        if self.cluster_size != len(self.cluster_symbols):
            raise ValueError("cluster_size must equal cluster symbol count")
        if not set(self.cluster_symbols).issubset(self.active_long_symbols):
            raise ValueError("cluster symbols must belong to the active long book")
        for name in (
            "cluster_exposure_share",
            "cluster_average_residual_correlation",
            "correlation_threshold",
            "sector_entropy",
            "holding_persistence_share",
            "cluster_residual_loss_5d",
            "residual_loss_threshold",
            "cluster_decline_share_5d",
            "cluster_loss_contribution_share_5d",
            "cluster_abnormal_volume_share_5d",
            "cluster_median_amihud_5d",
        ):
            value = getattr(self, name)
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite or null")
        for name in (
            "cluster_exposure_share",
            "holding_persistence_share",
            "cluster_decline_share_5d",
            "cluster_loss_contribution_share_5d",
            "cluster_abnormal_volume_share_5d",
        ):
            value = getattr(self, name)
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must lie in [0, 1]")
        if self.status != "available" and self.trigger is not None:
            raise ValueError("unavailable theme proxy cannot have a trigger")
        json.dumps(self.to_dict(), sort_keys=True, allow_nan=False)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _validated_prices(prices: pd.DataFrame) -> pd.DataFrame:
    required = {
        "date",
        "symbol",
        "close_total_return_adjusted",
    }
    missing = sorted(required - set(prices.columns))
    if missing:
        raise KeyError(f"prices missing required columns: {missing}")
    optional = ["volume_as_traded", "dollar_volume"]
    columns = list(required) + [
        column for column in optional if column in prices.columns
    ]
    frame = prices.loc[:, columns].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str)
    for column in ("close_total_return_adjusted", *optional):
        if column not in frame:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.sort_values(["symbol", "date"]).reset_index(drop=True)
    if frame.duplicated(["symbol", "date"]).any():
        raise ValueError("prices contain duplicate symbol/date observations")
    frame.loc[frame["close_total_return_adjusted"].le(0), "close_total_return_adjusted"] = np.nan
    frame["asset_return"] = frame.groupby("symbol", sort=False)[
        "close_total_return_adjusted"
    ].pct_change(fill_method=None)
    return frame


def _validated_benchmark(benchmark: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "benchmark_return"}
    missing = sorted(required - set(benchmark.columns))
    if missing:
        raise KeyError(f"benchmark missing required columns: {missing}")
    frame = benchmark.loc[:, ["date", "benchmark_return"]].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["benchmark_return"] = pd.to_numeric(
        frame["benchmark_return"], errors="coerce"
    )
    frame = frame.sort_values("date").drop_duplicates("date", keep="last")
    finite = frame["benchmark_return"].dropna()
    if not np.isfinite(finite).all():
        raise ValueError("benchmark_return contains non-finite values")
    return frame.reset_index(drop=True)


def _validated_holdings(holdings: pd.DataFrame) -> pd.DataFrame:
    required = {
        "formation_date",
        "effective_month",
        "symbol",
        "leg",
        "weight",
    }
    missing = sorted(required - set(holdings.columns))
    if missing:
        raise KeyError(f"holdings missing required columns: {missing}")
    frame = holdings.loc[:, sorted(required)].copy()
    frame["formation_date"] = pd.to_datetime(frame["formation_date"]).dt.normalize()
    frame["effective_month"] = frame["effective_month"].map(
        lambda value: pd.Period(value, freq="M")
    )
    frame["symbol"] = frame["symbol"].astype(str)
    frame["weight"] = pd.to_numeric(frame["weight"], errors="raise")
    if frame.duplicated(["formation_date", "symbol"]).any():
        raise ValueError("holdings contain duplicate formation/symbol rows")
    return frame.sort_values(["formation_date", "leg", "symbol"]).reset_index(
        drop=True
    )


def benchmark_residual_returns(
    prices: pd.DataFrame,
    benchmark: pd.DataFrame,
) -> pd.DataFrame:
    """Return long-form asset returns net of the same-day benchmark return."""

    price_frame = _validated_prices(prices)
    benchmark_frame = _validated_benchmark(benchmark)
    result = price_frame.merge(
        benchmark_frame,
        on="date",
        how="left",
        validate="many_to_one",
    )
    result["benchmark_residual_return"] = (
        result["asset_return"] - result["benchmark_return"]
    )
    return result


def prior_only_correlation_threshold(
    residual_returns: pd.DataFrame,
    *,
    quantile: float,
    floor: float,
    minimum_pair_observations: int,
) -> float | None:
    """Calculate a cross-sectional cutoff from a pre-event residual window."""

    if residual_returns.shape[1] < 2:
        return None
    correlations = residual_returns.corr(
        min_periods=minimum_pair_observations
    )
    upper = correlations.to_numpy(dtype="float64")[
        np.triu_indices(len(correlations), k=1)
    ]
    finite = upper[np.isfinite(upper)]
    if len(finite) == 0:
        return None
    return float(max(floor, np.quantile(finite, quantile)))


def largest_correlated_cluster(
    correlation_matrix: pd.DataFrame,
    *,
    threshold: float,
    minimum_size: int,
) -> tuple[str, ...]:
    """Return the largest deterministic all-pairs-above-threshold cluster.

    An all-pairs rule avoids the chain-merging behavior of connected
    components.  The active long book has ten names, so exhaustive clique
    selection is small and dependency-free.
    """

    symbols = sorted(str(symbol) for symbol in correlation_matrix.columns)
    if len(symbols) < minimum_size:
        return ()
    best: tuple[str, ...] = ()
    best_mean = -np.inf
    for size in range(len(symbols), minimum_size - 1, -1):
        for candidate in itertools.combinations(symbols, size):
            block = correlation_matrix.loc[candidate, candidate].to_numpy(
                dtype="float64"
            )
            upper = block[np.triu_indices(size, k=1)]
            if (
                len(upper) == 0
                or not np.isfinite(upper).all()
                or not np.all(upper >= threshold)
            ):
                continue
            mean = float(upper.mean())
            if not best or mean > best_mean + 1e-15:
                best = tuple(candidate)
                best_mean = mean
        if best:
            break
    return best


def _compounded_return(values: pd.Series, window: int) -> pd.Series:
    return (1.0 + values).rolling(window, min_periods=window).apply(
        np.prod, raw=True
    ) - 1.0


def _entropy(labels: pd.Series) -> float | None:
    if labels.empty:
        return None
    normalized = labels.fillna("unclassified").astype(str)
    shares = normalized.value_counts(normalize=True).to_numpy(dtype="float64")
    return float(-(shares * np.log(shares)).sum())


def _unavailable_snapshot(
    *,
    as_of_date: pd.Timestamp,
    formation_date: pd.Timestamp | None,
    cutoff: pd.Timestamp | None,
    status: str,
    active_symbols: tuple[str, ...],
    warning: str,
) -> ThemeConcentrationSnapshot:
    return ThemeConcentrationSnapshot(
        schema_version=THEME_PROXY_VERSION,
        as_of_date=as_of_date.date().isoformat(),
        formation_date=(
            formation_date.date().isoformat() if formation_date is not None else ""
        ),
        cluster_definition_cutoff=(
            cutoff.date().isoformat() if cutoff is not None else ""
        ),
        status=status,
        proxy_label="correlated_theme_proxy",
        active_long_symbols=active_symbols,
        cluster_symbols=(),
        cluster_size=0,
        cluster_exposure_share=None,
        cluster_average_residual_correlation=None,
        correlation_threshold=None,
        sector_count=None,
        sector_entropy=None,
        holding_persistence_share=None,
        cluster_residual_loss_5d=None,
        residual_loss_threshold=None,
        residual_loss_prior_observations=0,
        cluster_decline_share_5d=None,
        cluster_loss_contribution_share_5d=None,
        cluster_abnormal_volume_share_5d=None,
        cluster_median_amihud_5d=None,
        trigger=None,
        warnings=(warning,),
        audit_metadata={
            "cluster_uses_as_of_return": False,
            "future_rows_used": False,
        },
    )


def build_theme_concentration_snapshot(
    prices: pd.DataFrame,
    holdings: pd.DataFrame,
    benchmark: pd.DataFrame,
    *,
    as_of_date: pd.Timestamp,
    universe: pd.DataFrame | None = None,
    config: ThemeConcentrationConfig = DEFAULT_THEME_CONFIG,
) -> ThemeConcentrationSnapshot:
    """Build a no-look-ahead correlated-theme snapshot for one exact date."""

    selected_date = pd.Timestamp(as_of_date).normalize()
    holding_frame = _validated_holdings(holdings)
    active = holding_frame.loc[
        holding_frame["effective_month"].eq(selected_date.to_period("M"))
        & holding_frame["formation_date"].le(selected_date)
        & holding_frame["leg"].eq("long")
    ].copy()
    if active.empty:
        return _unavailable_snapshot(
            as_of_date=selected_date,
            formation_date=None,
            cutoff=None,
            status="unavailable",
            active_symbols=(),
            warning="No active momentum long holdings exist for the selected date.",
        )
    formation_dates = active["formation_date"].unique()
    if len(formation_dates) != 1:
        raise ValueError("active long holdings require one formation date")
    formation_date = pd.Timestamp(formation_dates[0]).normalize()
    active = active.sort_values("symbol").reset_index(drop=True)
    symbols = tuple(active["symbol"])

    residual = benchmark_residual_returns(prices, benchmark)
    residual = residual.loc[
        residual["symbol"].isin(symbols) & residual["date"].le(selected_date)
    ].copy()
    available_dates = sorted(
        residual.loc[
            residual["date"].lt(selected_date)
            & residual["benchmark_residual_return"].notna(),
            "date",
        ].unique()
    )
    if not available_dates:
        return _unavailable_snapshot(
            as_of_date=selected_date,
            formation_date=formation_date,
            cutoff=None,
            status="insufficient_history",
            active_symbols=symbols,
            warning="No pre-event residual-return history is available.",
        )
    definition_cutoff = pd.Timestamp(available_dates[-1]).normalize()
    pre_event = residual.loc[
        residual["date"].le(definition_cutoff),
        ["date", "symbol", "benchmark_residual_return"],
    ].pivot(
        index="date",
        columns="symbol",
        values="benchmark_residual_return",
    ).sort_index().tail(config.correlation_window)
    pre_event = pre_event.reindex(columns=list(symbols))
    complete = pre_event.dropna(axis=1, thresh=config.minimum_pair_observations)
    complete = complete.dropna(axis=0, how="all")
    if (
        len(complete) < config.minimum_pair_observations
        or complete.shape[1] < config.minimum_cluster_size
    ):
        return _unavailable_snapshot(
            as_of_date=selected_date,
            formation_date=formation_date,
            cutoff=definition_cutoff,
            status="insufficient_history",
            active_symbols=symbols,
            warning="Insufficient pre-event history for correlated-theme detection.",
        )
    threshold = prior_only_correlation_threshold(
        complete,
        quantile=config.correlation_quantile,
        floor=config.correlation_floor,
        minimum_pair_observations=config.minimum_pair_observations,
    )
    if threshold is None:
        return _unavailable_snapshot(
            as_of_date=selected_date,
            formation_date=formation_date,
            cutoff=definition_cutoff,
            status="insufficient_history",
            active_symbols=symbols,
            warning="No finite pre-event pair correlations are available.",
        )
    correlations = complete.corr(min_periods=config.minimum_pair_observations)
    cluster = largest_correlated_cluster(
        correlations,
        threshold=threshold,
        minimum_size=config.minimum_cluster_size,
    )

    absolute_weights = active.set_index("symbol")["weight"].abs()
    total_weight = float(absolute_weights.sum())
    cluster_exposure = (
        float(absolute_weights.reindex(cluster).sum() / total_weight)
        if cluster and total_weight > 0.0
        else 0.0
    )
    if cluster:
        block = correlations.loc[cluster, cluster].to_numpy(dtype="float64")
        cluster_correlation = float(
            block[np.triu_indices(len(cluster), k=1)].mean()
        )
    else:
        cluster_correlation = None

    previous = holding_frame.loc[
        holding_frame["leg"].eq("long")
        & holding_frame["formation_date"].lt(formation_date)
    ]
    if previous.empty:
        persistence = None
    else:
        prior_date = previous["formation_date"].max()
        prior_symbols = set(
            previous.loc[previous["formation_date"].eq(prior_date), "symbol"]
        )
        persistence = float(len(set(symbols) & prior_symbols) / len(symbols))

    sectors = pd.Series(dtype="object")
    if universe is not None and {"symbol", "sector"}.issubset(universe.columns):
        classifications = (
            universe.loc[:, ["symbol", "sector"]]
            .drop_duplicates("symbol", keep="last")
            .set_index("symbol")
        )
        sectors = classifications.reindex(cluster)["sector"]
    sector_count = (
        int(sectors.fillna("unclassified").astype(str).nunique())
        if cluster and not sectors.empty
        else None
    )
    sector_entropy = _entropy(sectors) if cluster and not sectors.empty else None

    panel = residual.pivot(
        index="date",
        columns="symbol",
        values="benchmark_residual_return",
    ).sort_index().reindex(columns=list(symbols))
    rolling_residual = panel.apply(
        lambda values: _compounded_return(values, config.event_window)
    )
    cluster_history = (
        rolling_residual.loc[:, list(cluster)].mean(axis=1, skipna=False)
        if cluster
        else pd.Series(index=rolling_residual.index, dtype="float64")
    )
    current_cluster_return = (
        float(cluster_history.loc[selected_date])
        if selected_date in cluster_history.index
        and pd.notna(cluster_history.loc[selected_date])
        else None
    )
    cluster_loss = (
        -current_cluster_return if current_cluster_return is not None else None
    )
    prior_losses = (
        -cluster_history.loc[cluster_history.index < selected_date].dropna()
    )
    loss_observations = int(len(prior_losses))
    loss_threshold = (
        float(prior_losses.quantile(config.loss_quantile, interpolation="linear"))
        if loss_observations >= config.loss_threshold_min_observations
        else None
    )

    price_frame = _validated_prices(prices)
    active_prices = price_frame.loc[
        price_frame["symbol"].isin(symbols)
        & price_frame["date"].le(selected_date)
    ].copy()
    active_prices["asset_return_5d"] = active_prices.groupby(
        "symbol", sort=False
    )["asset_return"].transform(
        lambda values: _compounded_return(values, config.event_window)
    )
    active_prices["volume_5d_average"] = active_prices.groupby(
        "symbol", sort=False
    )["volume_as_traded"].transform(
        lambda values: values.rolling(
            config.event_window, min_periods=config.event_window
        ).mean()
    )
    active_prices["amihud_1d"] = np.where(
        active_prices["dollar_volume"].gt(0),
        active_prices["asset_return"].abs() / active_prices["dollar_volume"],
        np.nan,
    )
    active_prices["amihud_5d"] = active_prices.groupby(
        "symbol", sort=False
    )["amihud_1d"].transform(
        lambda values: values.rolling(
            config.event_window, min_periods=config.event_window
        ).mean()
    )
    selected = active_prices.loc[
        active_prices["date"].eq(selected_date)
    ].set_index("symbol")
    active_returns = selected["asset_return_5d"].reindex(symbols)
    cluster_returns = active_returns.reindex(cluster)
    decline_share = (
        float(cluster_returns.lt(0.0).mean())
        if cluster and cluster_returns.notna().all()
        else None
    )
    all_losses = -active_returns.clip(upper=0.0)
    loss_denominator = float(all_losses.sum(skipna=True))
    loss_contribution = (
        float(all_losses.reindex(cluster).sum() / loss_denominator)
        if cluster
        and active_returns.notna().all()
        and loss_denominator > 0.0
        else None
    )

    abnormal_flags: list[bool] = []
    for symbol in cluster:
        symbol_history = active_prices.loc[
            active_prices["symbol"].eq(symbol)
        ].set_index("date")["volume_5d_average"]
        current_volume = symbol_history.get(selected_date, np.nan)
        prior_volume = symbol_history.loc[
            symbol_history.index < selected_date
        ].dropna()
        if (
            pd.notna(current_volume)
            and len(prior_volume) >= config.volume_min_observations
        ):
            cutoff = float(
                prior_volume.quantile(
                    config.volume_quantile, interpolation="linear"
                )
            )
            abnormal_flags.append(bool(float(current_volume) >= cutoff))
    abnormal_volume_share = (
        float(np.mean(abnormal_flags))
        if cluster and len(abnormal_flags) == len(cluster)
        else None
    )
    cluster_amihud = selected["amihud_5d"].reindex(cluster).dropna()
    median_amihud = (
        float(cluster_amihud.median()) if not cluster_amihud.empty else None
    )

    pre_event_concentrated = (
        len(cluster) >= config.minimum_cluster_size
        and cluster_exposure >= config.cluster_exposure_gate
    )
    loss_extreme = (
        cluster_loss is not None
        and loss_threshold is not None
        and cluster_loss >= loss_threshold
    )
    decline_gate = (
        decline_share is not None
        and decline_share >= config.decline_share_gate
    )
    loss_support = (
        loss_contribution is not None
        and loss_contribution >= config.loss_contribution_gate
    )
    volume_support = (
        abnormal_volume_share is not None
        and abnormal_volume_share >= config.abnormal_volume_share_gate
    )
    required_available = (
        not pre_event_concentrated
        or (
            loss_threshold is not None
            and cluster_loss is not None
            and decline_share is not None
            and (
                loss_contribution is not None
                or abnormal_volume_share is not None
            )
        )
    )
    trigger = (
        False
        if not pre_event_concentrated
        else (
            bool(
                loss_extreme
                and decline_gate
                and (loss_support or volume_support)
            )
            if required_available
            else None
        )
    )
    status = "available" if required_available else "insufficient_history"
    warnings = [
        "The cluster is a return-correlation proxy, not observed common ownership.",
        "Security membership and sector labels are current-snapshot proxies.",
        "Industry classification is unavailable in the existing repository data.",
    ]
    if not cluster:
        warnings.append(
            "No all-pairs correlated cluster met the pre-event proxy gates."
        )
    if cluster and loss_threshold is None:
        warnings.append(
            "Cluster-loss threshold has insufficient strictly prior observations."
        )
    if cluster and abnormal_volume_share is None:
        warnings.append("Cluster abnormal-volume confirmation is unavailable.")

    return ThemeConcentrationSnapshot(
        schema_version=THEME_PROXY_VERSION,
        as_of_date=selected_date.date().isoformat(),
        formation_date=formation_date.date().isoformat(),
        cluster_definition_cutoff=definition_cutoff.date().isoformat(),
        status=status,
        proxy_label="correlated_theme_proxy",
        active_long_symbols=symbols,
        cluster_symbols=cluster,
        cluster_size=len(cluster),
        cluster_exposure_share=cluster_exposure,
        cluster_average_residual_correlation=cluster_correlation,
        correlation_threshold=threshold,
        sector_count=sector_count,
        sector_entropy=sector_entropy,
        holding_persistence_share=persistence,
        cluster_residual_loss_5d=cluster_loss,
        residual_loss_threshold=loss_threshold,
        residual_loss_prior_observations=loss_observations,
        cluster_decline_share_5d=decline_share,
        cluster_loss_contribution_share_5d=loss_contribution,
        cluster_abnormal_volume_share_5d=abnormal_volume_share,
        cluster_median_amihud_5d=median_amihud,
        trigger=trigger,
        warnings=tuple(warnings),
        audit_metadata={
            "cluster_uses_as_of_return": False,
            "cluster_window": config.correlation_window,
            "cluster_minimum_pair_observations": (
                config.minimum_pair_observations
            ),
            "minimum_cluster_size": config.minimum_cluster_size,
            "cluster_exposure_gate": config.cluster_exposure_gate,
            "correlation_quantile": config.correlation_quantile,
            "correlation_floor": config.correlation_floor,
            "event_window": config.event_window,
            "decline_share_gate": config.decline_share_gate,
            "loss_contribution_gate": config.loss_contribution_gate,
            "abnormal_volume_share_gate": (
                config.abnormal_volume_share_gate
            ),
            "future_rows_used": False,
        },
    )
