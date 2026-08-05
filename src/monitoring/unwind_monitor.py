"""Mechanical unwind / market-absorption diagnostics (lightweight proxy).

Inspired by Khandani and Lo's August 2007 quant-unwind analysis. The module
infers possible crowding from public market footprints — cross-sectional factor
alignment, momentum-extreme abnormal turnover, and short-horizon absorption —
without observing hedge-fund positions, leverage, or forced liquidation.

The module detects factor-aligned trading footprints, not actual hedge-fund
liquidations. It should be interpreted as a mechanical-unwind proxy rather than
direct positioning evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from src.portfolio.momentum import build_momentum_rank_snapshot
from src.utils.io import DEFAULT_PROCESSED_DIR, iso_date

MECHANICAL_UNWIND_SCHEMA_VERSION = "mechanical-unwind-v1"
UNWIND_STATES = (
    "NORMAL",
    "FRAGILITY_BUILDING",
    "ACTIVE_UNWIND",
    "STABILIZING_REVERSAL",
)
UnwindState = Literal[
    "NORMAL",
    "FRAGILITY_BUILDING",
    "ACTIVE_UNWIND",
    "STABILIZING_REVERSAL",
]
ControlSpec = Literal["mom_vol_size", "mom_vol", "mom_only", "unavailable"]


@dataclass(frozen=True)
class MechanicalUnwindConfig:
    """Windows and percentile gates for the mechanical-unwind layer."""

    volume_median_window: int = 21
    volatility_window: int = 21
    min_cross_section: int = 30
    min_size_coverage: float = 0.50
    percentile_min_observations: int = 60
    elevated_percentile: float = 0.80
    loss_window: int = 5
    rebound_window: int = 5
    active_lookback: int = 10
    fragility_min_signals: int = 2
    absorption_window: int = 1
    # Trailing diagnostic window kept short for a lightweight MVP pass.
    history_window: int = 252
    signal_lookback_months: int = 14


DEFAULT_MECHANICAL_UNWIND_CONFIG = MechanicalUnwindConfig()


@dataclass(frozen=True)
class MechanicalUnwindAssessment:
    """Point-in-time snapshot of the mechanical-unwind layer."""

    schema_version: str
    as_of_date: str
    unwind_state: UnwindState
    control_spec: ControlSpec
    factor_footprint_r2: float | None
    factor_footprint_percentile: float | None
    momentum_beta: float | None
    momentum_beta_abs: float | None
    extreme_turnover_ratio: float | None
    extreme_turnover_percentile: float | None
    short_horizon_reversal: float | None
    continuation_pressure: float | None
    liquidity_absorption_failure: bool | None
    absorption_percentile: float | None
    interpretation: str
    history: pd.DataFrame
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "as_of_date": self.as_of_date,
            "unwind_state": self.unwind_state,
            "control_spec": self.control_spec,
            "factor_footprint_r2": self.factor_footprint_r2,
            "factor_footprint_percentile": self.factor_footprint_percentile,
            "momentum_beta": self.momentum_beta,
            "momentum_beta_abs": self.momentum_beta_abs,
            "extreme_turnover_ratio": self.extreme_turnover_ratio,
            "extreme_turnover_percentile": self.extreme_turnover_percentile,
            "short_horizon_reversal": self.short_horizon_reversal,
            "continuation_pressure": self.continuation_pressure,
            "liquidity_absorption_failure": self.liquidity_absorption_failure,
            "absorption_percentile": self.absorption_percentile,
            "interpretation": self.interpretation,
            "history_rows": int(len(self.history)),
            "warnings": list(self.warnings),
        }


def _optional_float(value: Any) -> float | None:
    if value is None or value is pd.NA or pd.isna(value):
        return None
    result = float(value)
    return result if np.isfinite(result) else None


def _validate_prices(prices: pd.DataFrame) -> pd.DataFrame:
    required = {
        "date",
        "symbol",
        "close_total_return_adjusted",
        "volume_as_traded",
    }
    missing = sorted(required - set(prices.columns))
    if missing:
        raise KeyError(f"prices missing required columns: {missing}")
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str)
    for column in (
        "close_total_return_adjusted",
        "volume_as_traded",
        "close_as_traded",
        "dollar_volume",
    ):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "close_as_traded" not in frame:
        frame["close_as_traded"] = np.nan
    frame = frame.sort_values(["symbol", "date"]).reset_index(drop=True)
    if frame.duplicated(["symbol", "date"]).any():
        raise ValueError("prices contain duplicate symbol/date observations")
    return frame


def _validate_holdings(holdings: pd.DataFrame) -> pd.DataFrame:
    required = {"effective_month", "symbol", "leg"}
    missing = sorted(required - set(holdings.columns))
    if missing:
        raise KeyError(f"holdings missing required columns: {missing}")
    frame = holdings.loc[:, ["effective_month", "symbol", "leg"]].copy()
    frame["symbol"] = frame["symbol"].astype(str)
    frame["leg"] = frame["leg"].astype(str)
    frame["effective_month"] = frame["effective_month"].astype("period[M]")
    if not set(frame["leg"]).issubset({"long", "short"}):
        raise ValueError("holdings legs must be long or short")
    return frame


def expanding_prior_percentile(values: pd.Series) -> pd.Series:
    """Percentile rank of each observation among strictly prior values."""

    series = pd.to_numeric(values, errors="coerce")
    ranks = np.full(len(series), np.nan, dtype=float)
    history: list[float] = []
    for index, value in enumerate(series.to_numpy(dtype=float)):
        if history:
            prior = np.asarray(history, dtype=float)
            if np.isfinite(value):
                ranks[index] = float(np.mean(prior <= value))
            else:
                ranks[index] = np.nan
        if np.isfinite(value):
            history.append(float(value))
    return pd.Series(ranks, index=series.index, dtype=float)


def _daily_security_panel(
    prices: pd.DataFrame,
    *,
    config: MechanicalUnwindConfig = DEFAULT_MECHANICAL_UNWIND_CONFIG,
) -> pd.DataFrame:
    """Build lagged security features used by the three diagnostics."""

    frame = _validate_prices(prices)
    group = frame.groupby("symbol", sort=False)
    frame["asset_return"] = group["close_total_return_adjusted"].pct_change(
        fill_method=None
    )
    vol_window = config.volatility_window
    frame["volatility"] = group["asset_return"].transform(
        lambda values: values.rolling(vol_window, min_periods=vol_window).std(
            ddof=0
        )
        * np.sqrt(252.0)
    )
    median_window = config.volume_median_window
    frame["rolling_median_volume"] = group["volume_as_traded"].transform(
        lambda values: values.rolling(
            median_window, min_periods=max(5, median_window // 2)
        ).median()
    )
    median = frame["rolling_median_volume"]
    volume = frame["volume_as_traded"]
    frame["abnormal_volume"] = np.where(
        median.gt(0) & volume.notna(),
        volume / median,
        np.nan,
    )
    # Explanatory volume/vol features used with membership are same-day levels
    # paired to lagged membership; regression controls are shifted below.
    for column in ("volatility", "close_as_traded"):
        frame[f"{column}_lag1"] = group[column].shift(1)
    return frame


def _momentum_rank_panel(
    prices: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    *,
    rank_snapshot: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Carry the latest known formation rank through its effective month."""

    ranks = (
        build_momentum_rank_snapshot(prices)
        if rank_snapshot is None
        else rank_snapshot.copy()
    )
    if ranks.empty:
        return pd.DataFrame(columns=["date", "symbol", "mom_rank_lag1"])
    required = {"effective_month", "symbol", "momentum_rank"}
    missing = sorted(required - set(ranks.columns))
    if missing:
        raise KeyError(f"momentum rank snapshot missing required columns: {missing}")
    ranks = ranks.loc[:, ["effective_month", "symbol", "momentum_rank"]].copy()
    ranks["symbol"] = ranks["symbol"].astype(str)
    ranks["effective_month"] = ranks["effective_month"].astype("period[M]")
    if ranks.duplicated(["effective_month", "symbol"]).any():
        raise ValueError("momentum rank snapshot contains duplicate month/symbol rows")

    dates = pd.DataFrame({"date": pd.DatetimeIndex(calendar).normalize()})
    dates["effective_month"] = dates["date"].dt.to_period("M")
    daily = dates.merge(ranks, on="effective_month", how="left")
    daily = daily.rename(columns={"momentum_rank": "mom_rank_lag1"})
    return daily.loc[:, ["date", "symbol", "mom_rank_lag1"]]


def _validate_momentum_snapshot_consistency(
    holdings: pd.DataFrame,
    rank_snapshot: pd.DataFrame,
    *,
    analysis_start: pd.Timestamp,
    as_of: pd.Timestamp,
) -> None:
    """Fail closed when portfolio holdings and regression ranks diverge."""

    required_holdings = {
        "formation_date",
        "formation_month",
        "effective_month",
        "symbol",
        "leg",
        "momentum_return",
        "n_long",
        "n_short",
        "price_momentum_rank",
        "rankable_universe",
    }
    missing = sorted(required_holdings - set(holdings.columns))
    if missing:
        raise KeyError(
            "holdings cannot be reconciled to the momentum snapshot; "
            f"missing columns: {missing}"
        )
    required_ranks = {
        "formation_date",
        "formation_month",
        "effective_month",
        "symbol",
        "momentum_return",
        "price_momentum_rank",
        "rankable_universe",
        "momentum_rank",
    }
    rank_missing = sorted(required_ranks - set(rank_snapshot.columns))
    if rank_missing:
        raise KeyError(f"momentum rank snapshot missing required columns: {rank_missing}")

    book = holdings.loc[:, sorted(required_holdings)].copy()
    snapshot = rank_snapshot.loc[:, sorted(required_ranks)].copy()
    for frame in (book, snapshot):
        frame["formation_date"] = pd.to_datetime(frame["formation_date"]).dt.normalize()
        frame["formation_month"] = frame["formation_month"].astype("period[M]")
        frame["effective_month"] = frame["effective_month"].astype("period[M]")
        frame["symbol"] = frame["symbol"].astype(str)

    first_month = pd.Timestamp(analysis_start).to_period("M")
    last_month = pd.Timestamp(as_of).to_period("M")
    snapshot = snapshot.loc[
        snapshot["effective_month"].between(first_month, last_month)
    ].copy()
    months = set(snapshot["effective_month"])
    book = book.loc[book["effective_month"].isin(months)].copy()
    if snapshot.empty or book.empty:
        raise ValueError("no overlapping momentum snapshot exists for the analysis window")
    if set(book["effective_month"]) != months:
        raise ValueError("holdings are missing an effective month in the analysis window")
    if book.duplicated(["effective_month", "symbol"]).any():
        raise ValueError("holdings contain duplicate effective-month/symbol rows")

    reconciled = book.merge(
        snapshot,
        on=["effective_month", "symbol"],
        how="left",
        suffixes=("_holding", "_snapshot"),
        validate="one_to_one",
        indicator=True,
    )
    if reconciled["_merge"].ne("both").any():
        raise ValueError("holdings contain names absent from the momentum rank snapshot")

    exact_fields = (
        "formation_date",
        "formation_month",
        "price_momentum_rank",
        "rankable_universe",
    )
    for field in exact_fields:
        if not reconciled[f"{field}_holding"].eq(
            reconciled[f"{field}_snapshot"]
        ).all():
            raise ValueError(f"holdings and momentum snapshot disagree on {field}")
    if not np.allclose(
        pd.to_numeric(reconciled["momentum_return_holding"], errors="coerce"),
        pd.to_numeric(reconciled["momentum_return_snapshot"], errors="coerce"),
        rtol=1e-12,
        atol=1e-14,
        equal_nan=False,
    ):
        raise ValueError("holdings and momentum snapshot disagree on momentum_return")

    for effective_month, group in reconciled.groupby("effective_month", sort=True):
        n_long_values = pd.to_numeric(group["n_long"], errors="coerce").unique()
        n_short_values = pd.to_numeric(group["n_short"], errors="coerce").unique()
        if len(n_long_values) != 1 or len(n_short_values) != 1:
            raise ValueError("holdings contain inconsistent portfolio sizes")
        n_long = int(n_long_values[0])
        n_short = int(n_short_values[0])
        if len(group) != n_long + n_short:
            raise ValueError(
                f"holdings are incomplete for effective month {effective_month}"
            )
        rank = pd.to_numeric(group["price_momentum_rank_holding"], errors="coerce")
        rankable = pd.to_numeric(
            group["rankable_universe_holding"], errors="coerce"
        )
        expected_long = rank.le(n_long)
        expected_short = rank.gt(rankable - n_short)
        if not group["leg"].eq("long").equals(expected_long):
            raise ValueError("long holdings do not match the canonical momentum ranks")
        if not group["leg"].eq("short").equals(expected_short):
            raise ValueError("short holdings do not match the canonical momentum ranks")


def _size_lag_panel(
    prices: pd.DataFrame,
    shares: pd.DataFrame | None,
) -> pd.DataFrame:
    """Point-in-time log market-cap proxy from SEC shares × traded price."""

    frame = _validate_prices(prices)
    if shares is None or shares.empty:
        return pd.DataFrame(columns=["date", "symbol", "size_lag1"])

    required = {"symbol", "filed_date", "shares_outstanding"}
    missing = sorted(required - set(shares.columns))
    if missing:
        raise KeyError(f"shares missing required columns: {missing}")

    filings = shares.loc[:, ["symbol", "filed_date", "shares_outstanding"]].copy()
    filings["symbol"] = filings["symbol"].astype(str)
    filings["shares_outstanding"] = pd.to_numeric(
        filings["shares_outstanding"], errors="coerce"
    )
    filings = filings.dropna(subset=["symbol", "filed_date", "shares_outstanding"])
    filings = filings.loc[filings["shares_outstanding"].gt(0)]

    price_panel = frame.loc[:, ["date", "symbol", "close_as_traded"]].copy()

    def _as_ns(series: pd.Series) -> pd.Series:
        values = pd.to_datetime(series, utc=True).dt.tz_convert(None).dt.normalize()
        return pd.Series(
            values.to_numpy(dtype="datetime64[ns]"),
            index=series.index,
            name=series.name,
        )

    price_panel["date"] = _as_ns(price_panel["date"])
    filings["filed_date"] = _as_ns(filings["filed_date"])

    pieces: list[pd.DataFrame] = []
    filings_by_symbol = {
        symbol: group.sort_values("filed_date")
        for symbol, group in filings.groupby("symbol", sort=False)
    }
    for symbol, price_group in price_panel.groupby("symbol", sort=False):
        share_group = filings_by_symbol.get(symbol)
        if share_group is None or share_group.empty:
            piece = price_group.copy()
            piece["shares_outstanding"] = np.nan
        else:
            left = price_group.sort_values("date").copy()
            right = share_group.loc[:, ["filed_date", "shares_outstanding"]].copy()
            left["_key"] = left["date"].astype("int64")
            right["_key"] = right["filed_date"].astype("int64")
            piece = pd.merge_asof(
                left,
                right.loc[:, ["_key", "shares_outstanding"]],
                on="_key",
                direction="backward",
                allow_exact_matches=True,
            )
        pieces.append(piece)
    if not pieces:
        return pd.DataFrame(columns=["date", "symbol", "size_lag1"])
    merged = pd.concat(pieces, ignore_index=True)
    # Size known at close of t may only enter regressions on t+1.
    merged["size_raw"] = np.where(
        merged["close_as_traded"].gt(0) & merged["shares_outstanding"].gt(0),
        np.log(merged["close_as_traded"] * merged["shares_outstanding"]),
        np.nan,
    )
    merged = merged.sort_values(["symbol", "date"])
    merged["size_lag1"] = merged.groupby("symbol", sort=False)["size_raw"].shift(1)
    return merged.loc[:, ["date", "symbol", "size_lag1"]]


def _lagged_extreme_membership(
    holdings: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Daily long/short membership lagged one session (PM L10∪S10 extremes)."""

    book = _validate_holdings(holdings)
    ordered = pd.DatetimeIndex(calendar).normalize().unique().sort_values()
    dates = pd.DataFrame({"date": ordered})
    dates["effective_month"] = dates["date"].dt.to_period("M")
    daily = dates.merge(book, on="effective_month", how="inner")
    next_date = {
        ordered[index]: ordered[index + 1] for index in range(len(ordered) - 1)
    }
    daily["date"] = daily["date"].map(next_date)
    daily = daily.dropna(subset=["date"])
    return daily.loc[:, ["date", "symbol", "leg"]].reset_index(drop=True)


def _ols_r2_and_mom_beta(
    y: np.ndarray,
    x_cols: list[np.ndarray],
) -> tuple[float, float]:
    """Cross-sectional OLS with intercept; returns R² and momentum coefficient.

    Explanatory columns are cross-sectionally standardized for numerical
    stability; R² is invariant to that rescaling.
    """

    n = len(y)
    if n == 0 or not x_cols:
        return np.nan, np.nan
    if n <= len(x_cols) + 1:
        return np.nan, np.nan
    if not np.isfinite(y).all():
        return np.nan, np.nan
    standardized: list[np.ndarray] = []
    for column in x_cols:
        if not np.isfinite(column).all():
            return np.nan, np.nan
        scale = float(np.std(column))
        if scale <= 0.0 or not np.isfinite(scale):
            return np.nan, np.nan
        standardized.append((column - float(np.mean(column))) / scale)
    x = np.column_stack([np.ones(n), *standardized])
    beta, residuals, rank, _ = np.linalg.lstsq(x, y, rcond=None)
    if rank < x.shape[1]:
        return np.nan, np.nan
    if residuals.size:
        ss_res = float(residuals[0])
    else:
        fitted = x @ beta
        ss_res = float(np.sum((y - fitted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    if ss_tot <= 0.0 or not np.isfinite(ss_res):
        return np.nan, np.nan
    mom_beta = float(beta[1])
    if not np.isfinite(mom_beta):
        return np.nan, np.nan
    return 1.0 - ss_res / ss_tot, mom_beta


def compute_cross_sectional_factor_footprint(
    prices: pd.DataFrame,
    *,
    shares: pd.DataFrame | None = None,
    momentum_ranks: pd.DataFrame | None = None,
    config: MechanicalUnwindConfig = DEFAULT_MECHANICAL_UNWIND_CONFIG,
) -> pd.DataFrame:
    """Estimate daily factor-footprint regressions with lagged controls.

    Preferred specification: return ~ MomRank + Volatility + Size.
    Falls back to MomRank + Volatility, then MomRank-only, when size coverage
    is insufficient.
    """

    panel = _daily_security_panel(prices, config=config)
    calendar = pd.DatetimeIndex(sorted(panel["date"].unique()))
    ranks = _momentum_rank_panel(
        prices,
        calendar,
        rank_snapshot=momentum_ranks,
    )
    sizes = _size_lag_panel(prices, shares)
    frame = panel.merge(ranks, on=["date", "symbol"], how="left")
    if sizes.empty:
        frame["size_lag1"] = np.nan
    else:
        frame = frame.merge(sizes, on=["date", "symbol"], how="left")

    records: list[dict[str, Any]] = []
    for date, group in frame.groupby("date", sort=True):
        y = group["asset_return"]
        mom = group["mom_rank_lag1"]
        vol = group["volatility_lag1"]
        size = group["size_lag1"]
        base = y.notna() & mom.notna()
        n_base = int(base.sum())
        if n_base < config.min_cross_section:
            records.append(
                {
                    "date": date,
                    "cross_sectional_r2": np.nan,
                    "momentum_beta": np.nan,
                    "momentum_beta_abs": np.nan,
                    "control_spec": "unavailable",
                    "cross_section_n": n_base,
                    "size_coverage": float(size.notna().mean()) if len(group) else 0.0,
                }
            )
            continue

        size_coverage = float((base & size.notna()).sum() / n_base)
        vol_ok = base & vol.notna()
        size_ok = vol_ok & size.notna()
        control_spec: ControlSpec
        if (
            size_coverage >= config.min_size_coverage
            and int(size_ok.sum()) >= config.min_cross_section
        ):
            mask = size_ok
            r2, mom_beta = _ols_r2_and_mom_beta(
                y.loc[mask].to_numpy(dtype=float),
                [
                    mom.loc[mask].to_numpy(dtype=float),
                    vol.loc[mask].to_numpy(dtype=float),
                    size.loc[mask].to_numpy(dtype=float),
                ],
            )
            control_spec = "mom_vol_size"
        elif int(vol_ok.sum()) >= config.min_cross_section:
            mask = vol_ok
            r2, mom_beta = _ols_r2_and_mom_beta(
                y.loc[mask].to_numpy(dtype=float),
                [
                    mom.loc[mask].to_numpy(dtype=float),
                    vol.loc[mask].to_numpy(dtype=float),
                ],
            )
            control_spec = "mom_vol"
        else:
            mask = base
            r2, mom_beta = _ols_r2_and_mom_beta(
                y.loc[mask].to_numpy(dtype=float),
                [mom.loc[mask].to_numpy(dtype=float)],
            )
            control_spec = "mom_only"

        records.append(
            {
                "date": date,
                "cross_sectional_r2": r2,
                "momentum_beta": mom_beta,
                "momentum_beta_abs": abs(mom_beta) if np.isfinite(mom_beta) else np.nan,
                "control_spec": control_spec,
                "cross_section_n": int(mask.sum()),
                "size_coverage": size_coverage,
            }
        )

    result = pd.DataFrame.from_records(records)
    if result.empty:
        return result
    result["factor_footprint_percentile"] = expanding_prior_percentile(
        result["cross_sectional_r2"]
    )
    result["momentum_beta_abs_percentile"] = expanding_prior_percentile(
        result["momentum_beta_abs"]
    )
    return result


def compute_momentum_aligned_turnover(
    prices: pd.DataFrame,
    holdings: pd.DataFrame,
    *,
    config: MechanicalUnwindConfig = DEFAULT_MECHANICAL_UNWIND_CONFIG,
) -> pd.DataFrame:
    """Compare abnormal volume in lagged PM extremes versus the universe."""

    panel = _daily_security_panel(prices, config=config)
    calendar = pd.DatetimeIndex(sorted(panel["date"].unique()))
    membership = _lagged_extreme_membership(holdings, calendar)
    frame = panel.merge(membership, on=["date", "symbol"], how="left")

    records: list[dict[str, Any]] = []
    for date, group in frame.groupby("date", sort=True):
        abnormal = group["abnormal_volume"]
        universe = abnormal.mean(skipna=True)
        long_vals = abnormal.loc[group["leg"].eq("long")]
        short_vals = abnormal.loc[group["leg"].eq("short")]
        extreme_vals = abnormal.loc[group["leg"].isin(["long", "short"])]
        long_avg = long_vals.mean(skipna=True)
        short_avg = short_vals.mean(skipna=True)
        extreme_avg = extreme_vals.mean(skipna=True)
        if pd.notna(universe) and float(universe) > 0.0 and pd.notna(extreme_avg):
            ratio = float(extreme_avg) / float(universe)
        else:
            ratio = np.nan
        records.append(
            {
                "date": date,
                "long_leg_abnormal_volume": long_avg,
                "short_leg_abnormal_volume": short_avg,
                "extreme_momentum_abnormal_volume": extreme_avg,
                "universe_abnormal_volume": universe,
                "extreme_turnover_ratio": ratio,
            }
        )
    result = pd.DataFrame.from_records(records)
    if result.empty:
        return result
    result["extreme_turnover_percentile"] = expanding_prior_percentile(
        result["extreme_turnover_ratio"]
    )
    return result


def compute_market_absorption_proxy(
    prices: pd.DataFrame,
    holdings: pd.DataFrame,
    *,
    config: MechanicalUnwindConfig = DEFAULT_MECHANICAL_UNWIND_CONFIG,
) -> pd.DataFrame:
    """Daily absorption proxy from next-day performance of lagged extremes.

    ``short_horizon_reversal`` is the equal-weight short-leg minus long-leg
    return using membership known on t-1. Positive values indicate losers
    outperforming winners (absorption / reversal). Negative values indicate
    continuation pressure.
    """

    panel = _daily_security_panel(prices, config=config)
    calendar = pd.DatetimeIndex(sorted(panel["date"].unique()))
    membership = _lagged_extreme_membership(holdings, calendar)
    frame = panel.merge(membership, on=["date", "symbol"], how="left")

    records: list[dict[str, Any]] = []
    for date, group in frame.groupby("date", sort=True):
        long_ret = group.loc[group["leg"].eq("long"), "asset_return"].mean(skipna=True)
        short_ret = group.loc[
            group["leg"].eq("short"), "asset_return"
        ].mean(skipna=True)
        if pd.isna(long_ret) or pd.isna(short_ret):
            reversal = np.nan
            continuation = np.nan
        else:
            reversal = float(short_ret - long_ret)
            continuation = float(-reversal)
        records.append(
            {
                "date": date,
                "short_horizon_reversal": reversal,
                "continuation_pressure": continuation,
            }
        )
    result = pd.DataFrame.from_records(records)
    if result.empty:
        return result
    result["continuation_percentile"] = expanding_prior_percentile(
        result["continuation_pressure"]
    )
    # Failure = unusually persistent continuation vs prior history, not merely
    # a one-day negative reversal sign.
    result["liquidity_absorption_failure"] = np.where(
        result["continuation_percentile"].isna(),
        np.nan,
        result["continuation_percentile"].ge(config.elevated_percentile),
    )
    return result


def _elevated(percentile: float | None, gate: float) -> bool:
    return percentile is not None and percentile >= gate


def classify_unwind_state(
    footprint: pd.DataFrame,
    turnover: pd.DataFrame,
    absorption: pd.DataFrame,
    risk_history: pd.DataFrame,
    *,
    config: MechanicalUnwindConfig = DEFAULT_MECHANICAL_UNWIND_CONFIG,
) -> pd.DataFrame:
    """Rule-based mechanical-unwind state from rolling historical percentiles."""

    if "date" not in risk_history:
        raise KeyError("risk_history requires date")
    risk = risk_history.copy()
    risk["date"] = pd.to_datetime(risk["date"]).dt.normalize()
    risk = risk.sort_values("date")
    risk["portfolio_return"] = pd.to_numeric(
        risk.get("portfolio_return"), errors="coerce"
    )
    risk["portfolio_volatility_21d"] = pd.to_numeric(
        risk.get("portfolio_volatility_21d"), errors="coerce"
    )
    risk["beta_gap_short_minus_long_126d"] = pd.to_numeric(
        risk.get("beta_gap_short_minus_long_126d"), errors="coerce"
    )
    risk["loss_window_return"] = (
        risk["portfolio_return"]
        .rolling(config.loss_window, min_periods=config.loss_window)
        .apply(lambda values: float(np.prod(1.0 + values) - 1.0), raw=True)
    )
    risk["rebound_window_return"] = (
        risk["portfolio_return"]
        .rolling(config.rebound_window, min_periods=config.rebound_window)
        .apply(lambda values: float(np.prod(1.0 + values) - 1.0), raw=True)
    )
    risk["vol_percentile"] = expanding_prior_percentile(
        risk["portfolio_volatility_21d"]
    )
    risk["beta_gap_abs"] = risk["beta_gap_short_minus_long_126d"].abs()
    risk["beta_gap_percentile"] = expanding_prior_percentile(risk["beta_gap_abs"])
    risk["loss_percentile"] = expanding_prior_percentile(-risk["loss_window_return"])

    merged = risk.loc[
        :,
        [
            "date",
            "portfolio_return",
            "loss_window_return",
            "rebound_window_return",
            "vol_percentile",
            "beta_gap_percentile",
            "loss_percentile",
        ],
    ]
    for frame, cols in (
        (
            footprint,
            [
                "cross_sectional_r2",
                "momentum_beta",
                "momentum_beta_abs",
                "factor_footprint_percentile",
                "momentum_beta_abs_percentile",
                "control_spec",
            ],
        ),
        (
            turnover,
            [
                "long_leg_abnormal_volume",
                "short_leg_abnormal_volume",
                "extreme_momentum_abnormal_volume",
                "universe_abnormal_volume",
                "extreme_turnover_ratio",
                "extreme_turnover_percentile",
            ],
        ),
        (
            absorption,
            [
                "short_horizon_reversal",
                "continuation_pressure",
                "liquidity_absorption_failure",
                "continuation_percentile",
            ],
        ),
    ):
        piece = frame.copy()
        piece["date"] = pd.to_datetime(piece["date"]).dt.normalize()
        keep = ["date"] + [column for column in cols if column in piece]
        merged = merged.merge(piece.loc[:, keep], on="date", how="left")

    gate = config.elevated_percentile
    states: list[str] = []
    footprint_elevated_flags: list[bool | None] = []
    turnover_elevated_flags: list[bool | None] = []
    active_recent = 0
    for row in merged.itertuples(index=False):
        footprint_percentile = _optional_float(
            getattr(row, "factor_footprint_percentile", None)
        )
        turnover_percentile = _optional_float(
            getattr(row, "extreme_turnover_percentile", None)
        )
        footprint_elev = _elevated(footprint_percentile, gate)
        mom_beta_elev = _elevated(
            _optional_float(getattr(row, "momentum_beta_abs_percentile", None)),
            gate,
        )
        turnover_elev = _elevated(turnover_percentile, gate)
        vol_elev = _elevated(_optional_float(row.vol_percentile), gate)
        beta_elev = _elevated(_optional_float(row.beta_gap_percentile), gate)
        continuation_elev = _elevated(
            _optional_float(getattr(row, "continuation_percentile", None)),
            gate,
        )
        absorption_raw = getattr(row, "liquidity_absorption_failure", None)
        if absorption_raw is None or pd.isna(absorption_raw):
            absorption_fail: bool | None = None
        else:
            absorption_fail = bool(absorption_raw)
        loss_elev = _elevated(_optional_float(row.loss_percentile), gate)
        loss_value = _optional_float(row.loss_window_return)
        rebound_value = _optional_float(row.rebound_window_return)

        vulnerability = sum(
            [
                footprint_elev,
                mom_beta_elev,
                turnover_elev,
                vol_elev,
                beta_elev,
            ]
        )
        active = (
            bool(loss_elev and loss_value is not None and loss_value < 0.0)
            and (footprint_elev or mom_beta_elev)
            and turnover_elev
            and (continuation_elev or absorption_fail is True)
        )
        if active:
            active_recent = config.active_lookback
        else:
            active_recent = max(0, active_recent - 1)

        stabilizing = (
            active_recent > 0
            and not active
            and rebound_value is not None
            and rebound_value > 0.0
            and not footprint_elev
            and not turnover_elev
            and absorption_fail is not True
        )
        if active:
            state: UnwindState = "ACTIVE_UNWIND"
        elif stabilizing:
            state = "STABILIZING_REVERSAL"
        elif vulnerability >= config.fragility_min_signals:
            state = "FRAGILITY_BUILDING"
        else:
            state = "NORMAL"
        states.append(state)
        # Persist the elevation decisions already used for state classification
        # so downstream compactors can copy them without re-applying a gate.
        footprint_elevated_flags.append(
            None if footprint_percentile is None else bool(footprint_elev)
        )
        turnover_elevated_flags.append(
            None if turnover_percentile is None else bool(turnover_elev)
        )

    merged["unwind_state"] = states
    merged["factor_footprint_elevated"] = footprint_elevated_flags
    merged["aligned_turnover_elevated"] = turnover_elevated_flags
    return merged


def _state_interpretation(state: UnwindState) -> str:
    mapping = {
        "NORMAL": (
            "Factor footprint and momentum-aligned turnover are not elevated."
        ),
        "FRAGILITY_BUILDING": (
            "Potential momentum tail risk: multiple vulnerability indicators "
            "are elevated; watch for "
            "factor-aligned flow without confirmed portfolio losses."
        ),
        "ACTIVE_UNWIND": (
            "Momentum losses coincide with elevated factor footprint, "
            "momentum-extreme turnover, and continuation / failed absorption."
        ),
        "STABILIZING_REVERSAL": (
            "A recent active-unwind window is followed by rebound with "
            "declining footprint / turnover and improving absorption."
        ),
    }
    return mapping[state]


def build_mechanical_unwind_assessment(
    *,
    as_of_date: pd.Timestamp | str,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    config: MechanicalUnwindConfig = DEFAULT_MECHANICAL_UNWIND_CONFIG,
    prices: pd.DataFrame | None = None,
    holdings: pd.DataFrame | None = None,
    risk_history: pd.DataFrame | None = None,
    shares: pd.DataFrame | None = None,
) -> MechanicalUnwindAssessment:
    """Build the mechanical-unwind history and as-of snapshot."""

    as_of = pd.Timestamp(as_of_date).normalize()
    root = Path(processed_dir)
    load_from_disk = prices is None
    price_frame = (
        prices
        if prices is not None
        else pd.read_parquet(root / "sp500_prices.parquet")
    )
    holdings_frame = (
        holdings
        if holdings is not None
        else pd.read_parquet(root / "momentum_portfolio_holdings.parquet")
    )
    risk_frame = (
        risk_history
        if risk_history is not None
        else pd.read_parquet(root / "leg_risk_history.parquet")
    )
    share_frame = shares
    if share_frame is None and load_from_disk:
        share_path = root / "sec_shares_outstanding.parquet"
        share_frame = pd.read_parquet(share_path) if share_path.exists() else None

    # Restrict to history through as-of for point-in-time safety.
    price_frame = _validate_prices(price_frame)
    price_frame = price_frame.loc[price_frame["date"].le(as_of)].copy()
    risk_frame = risk_frame.copy()
    risk_frame["date"] = pd.to_datetime(risk_frame["date"]).dt.normalize()
    risk_frame = risk_frame.loc[risk_frame["date"].le(as_of)].copy()

    trading_dates = pd.DatetimeIndex(sorted(price_frame["date"].unique()))
    if len(trading_dates) > config.history_window:
        analysis_start = trading_dates[-config.history_window]
    else:
        analysis_start = trading_dates[0] if len(trading_dates) else as_of
    signal_start = analysis_start - pd.DateOffset(months=config.signal_lookback_months)
    price_frame = price_frame.loc[price_frame["date"].ge(signal_start)].copy()
    risk_frame = risk_frame.loc[risk_frame["date"].ge(analysis_start)].copy()

    momentum_ranks = build_momentum_rank_snapshot(price_frame)
    _validate_momentum_snapshot_consistency(
        holdings_frame,
        momentum_ranks,
        analysis_start=analysis_start,
        as_of=as_of,
    )
    footprint = compute_cross_sectional_factor_footprint(
        price_frame,
        shares=share_frame,
        momentum_ranks=momentum_ranks,
        config=config,
    )
    # Turnover / absorption reuse the same trimmed price window; each call is
    # intentionally self-contained for readability of the public API.
    turnover = compute_momentum_aligned_turnover(
        price_frame, holdings_frame, config=config
    )
    absorption = compute_market_absorption_proxy(
        price_frame, holdings_frame, config=config
    )
    footprint = footprint.loc[footprint["date"].ge(analysis_start)].copy()
    turnover = turnover.loc[turnover["date"].ge(analysis_start)].copy()
    absorption = absorption.loc[absorption["date"].ge(analysis_start)].copy()
    # Recompute prior-only percentiles on the trimmed analysis window.
    if not footprint.empty:
        footprint["factor_footprint_percentile"] = expanding_prior_percentile(
            footprint["cross_sectional_r2"]
        )
        footprint["momentum_beta_abs_percentile"] = expanding_prior_percentile(
            footprint["momentum_beta_abs"]
        )
    if not turnover.empty:
        turnover["extreme_turnover_percentile"] = expanding_prior_percentile(
            turnover["extreme_turnover_ratio"]
        )
    if not absorption.empty:
        absorption["continuation_percentile"] = expanding_prior_percentile(
            absorption["continuation_pressure"]
        )

    history = classify_unwind_state(
        footprint, turnover, absorption, risk_frame, config=config
    )
    history = history.loc[history["date"].le(as_of)].reset_index(drop=True)

    warnings: list[str] = [
        "Mechanical-unwind diagnostics are public-data proxies, not observed "
        "hedge-fund liquidations or dealer inventory.",
    ]
    if history.empty:
        return MechanicalUnwindAssessment(
            schema_version=MECHANICAL_UNWIND_SCHEMA_VERSION,
            as_of_date=iso_date(as_of),
            unwind_state="NORMAL",
            control_spec="unavailable",
            factor_footprint_r2=None,
            factor_footprint_percentile=None,
            momentum_beta=None,
            momentum_beta_abs=None,
            extreme_turnover_ratio=None,
            extreme_turnover_percentile=None,
            short_horizon_reversal=None,
            continuation_pressure=None,
            liquidity_absorption_failure=None,
            absorption_percentile=None,
            interpretation="Insufficient history for mechanical-unwind assessment.",
            history=history,
            warnings=tuple(warnings + ["insufficient_history"]),
        )

    row = history.loc[history["date"].eq(as_of)]
    if row.empty:
        row = history.tail(1)
        warnings.append("as_of_date missing from history; using latest available row")
    selected = row.iloc[-1]
    control = selected.get("control_spec", "unavailable")
    if control not in {"mom_vol_size", "mom_vol", "mom_only", "unavailable"}:
        control = "unavailable"
    if control != "mom_vol_size":
        warnings.append(
            f"size control degraded to {control}; SEC×price coverage below gate"
        )

    state = str(selected["unwind_state"])
    if state not in UNWIND_STATES:
        state = "NORMAL"

    return MechanicalUnwindAssessment(
        schema_version=MECHANICAL_UNWIND_SCHEMA_VERSION,
        as_of_date=iso_date(as_of),
        unwind_state=state,  # type: ignore[arg-type]
        control_spec=control,  # type: ignore[arg-type]
        factor_footprint_r2=_optional_float(selected.get("cross_sectional_r2")),
        factor_footprint_percentile=_optional_float(
            selected.get("factor_footprint_percentile")
        ),
        momentum_beta=_optional_float(selected.get("momentum_beta")),
        momentum_beta_abs=_optional_float(selected.get("momentum_beta_abs")),
        extreme_turnover_ratio=_optional_float(selected.get("extreme_turnover_ratio")),
        extreme_turnover_percentile=_optional_float(
            selected.get("extreme_turnover_percentile")
        ),
        short_horizon_reversal=_optional_float(
            selected.get("short_horizon_reversal")
        ),
        continuation_pressure=_optional_float(selected.get("continuation_pressure")),
        liquidity_absorption_failure=(
            None
            if selected.get("liquidity_absorption_failure") is None
            or (
                isinstance(selected.get("liquidity_absorption_failure"), float)
                and np.isnan(selected.get("liquidity_absorption_failure"))
            )
            or pd.isna(selected.get("liquidity_absorption_failure"))
            else bool(selected.get("liquidity_absorption_failure"))
        ),
        absorption_percentile=_optional_float(
            selected.get("continuation_percentile")
        ),
        interpretation=_state_interpretation(state),  # type: ignore[arg-type]
        history=history,
        warnings=tuple(warnings),
    )
