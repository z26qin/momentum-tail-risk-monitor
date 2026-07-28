"""Realized long/short risk decomposition for the monthly momentum portfolio.

The primary benchmark is SPY's split- and dividend-adjusted return.  If that
processed series is unavailable, the existing Ken French broad-US-market
total-return proxy is used and labeled as a fallback.  All statistics are
trailing and end on the current row; same-day values are post-close facts whose
earliest permitted use is the next trading session.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from src.regime.market_state import build_regime_history
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    REPO_ROOT,
    write_json,
    write_parquet,
)


BETA_WINDOW = 126
BETA_MIN_OBSERVATIONS = 63
CONDITIONAL_BETA_MIN_OBSERVATIONS = 30
VOLATILITY_WINDOW = 21
CONTRIBUTION_WINDOW = 21
ANNUALIZATION = 252

PORTFOLIO_REQUIRED = {
    "date",
    "long_basket_return",
    "short_basket_underlying_return",
    "long_contribution",
    "short_contribution",
    "portfolio_return",
    "return_complete",
    "drawdown",
    "membership_status",
    "survivorship_bias",
}
BENCHMARK_REQUIRED = {
    "date",
    "benchmark_return",
    "benchmark_source",
    "benchmark_status",
}
REGIME_COLUMNS = (
    "date",
    "early_recovery_state",
    "high_volatility_recovery_state",
)


def _validate_portfolio(portfolio: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(PORTFOLIO_REQUIRED - set(portfolio.columns))
    if missing:
        raise KeyError(f"portfolio missing required columns: {missing}")
    frame = portfolio.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").reset_index(drop=True)
    if frame.empty or frame["date"].duplicated().any():
        raise ValueError("portfolio must contain sorted unique dates")
    numeric = [
        "long_basket_return",
        "short_basket_underlying_return",
        "long_contribution",
        "short_contribution",
        "portfolio_return",
        "drawdown",
    ]
    if frame[numeric].isna().any().any():
        raise ValueError("portfolio contains missing required returns")
    if not frame["return_complete"].astype(bool).all():
        raise ValueError("risk decomposition requires complete portfolio rows")
    error = (
        frame["portfolio_return"]
        - frame["long_contribution"]
        - frame["short_contribution"]
    ).abs()
    if error.max() > 1e-12:
        raise ValueError("portfolio contributions do not reconcile")
    short_error = (
        frame["short_contribution"]
        + frame["short_basket_underlying_return"]
    ).abs()
    if short_error.max() > 1e-12:
        raise ValueError("short contribution sign does not match short basket")
    return frame


def _validate_benchmark(benchmark: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(BENCHMARK_REQUIRED - set(benchmark.columns))
    if missing:
        raise KeyError(f"benchmark missing required columns: {missing}")
    frame = benchmark.loc[:, sorted(BENCHMARK_REQUIRED)].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").reset_index(drop=True)
    if frame.empty or frame["date"].duplicated().any():
        raise ValueError("benchmark must contain sorted unique dates")
    return frame


def rolling_beta(
    asset_return: pd.Series,
    benchmark_return: pd.Series,
    *,
    window: int = BETA_WINDOW,
    min_observations: int = BETA_MIN_OBSERVATIONS,
) -> pd.Series:
    """Trailing covariance beta with an explicit zero-variance guard."""

    if window <= 1 or not 2 <= min_observations <= window:
        raise ValueError("beta window/minimum observations are invalid")
    covariance = asset_return.rolling(
        window,
        min_periods=min_observations,
    ).cov(benchmark_return, ddof=1)
    variance = benchmark_return.rolling(
        window,
        min_periods=min_observations,
    ).var(ddof=1)
    return covariance / variance.mask(variance.eq(0.0))


def rolling_conditional_beta(
    asset_return: pd.Series,
    benchmark_return: pd.Series,
    *,
    direction: Literal["up", "down"],
    window: int = BETA_WINDOW,
    min_observations: int = CONDITIONAL_BETA_MIN_OBSERVATIONS,
) -> tuple[pd.Series, pd.Series]:
    """Trailing beta after filtering observations by benchmark-return sign."""

    if direction not in {"up", "down"}:
        raise ValueError("direction must be 'up' or 'down'")
    if window <= 1 or not 2 <= min_observations <= window:
        raise ValueError("conditional beta window/minimum are invalid")
    result = pd.Series(np.nan, index=asset_return.index, dtype=float)
    counts = pd.Series(0, index=asset_return.index, dtype="int64")
    for end in range(len(asset_return)):
        start = max(0, end - window + 1)
        asset = asset_return.iloc[start : end + 1]
        benchmark = benchmark_return.iloc[start : end + 1]
        sign = benchmark.gt(0.0) if direction == "up" else benchmark.lt(0.0)
        valid = sign & asset.notna() & benchmark.notna()
        count = int(valid.sum())
        counts.iloc[end] = count
        if count < min_observations:
            continue
        selected_asset = asset.loc[valid]
        selected_benchmark = benchmark.loc[valid]
        variance = selected_benchmark.var(ddof=1)
        if pd.notna(variance) and variance > 0.0:
            result.iloc[end] = selected_asset.cov(selected_benchmark) / variance
    return result, counts


def _drawdown(returns: pd.Series) -> pd.Series:
    if returns.le(-1.0).any():
        raise ValueError("portfolio return cannot be <= -1")
    wealth = (1.0 + returns).cumprod(skipna=False)
    return wealth / wealth.cummax() - 1.0


def build_leg_risk_history(
    portfolio: pd.DataFrame,
    benchmark: pd.DataFrame,
    *,
    regime_history: pd.DataFrame | None = None,
    beta_window: int = BETA_WINDOW,
    beta_min_observations: int = BETA_MIN_OBSERVATIONS,
    conditional_min_observations: int = CONDITIONAL_BETA_MIN_OBSERVATIONS,
    volatility_window: int = VOLATILITY_WINDOW,
    contribution_window: int = CONTRIBUTION_WINDOW,
) -> pd.DataFrame:
    """Build daily realized leg risk using only trailing observations."""

    result = _validate_portfolio(portfolio).merge(
        _validate_benchmark(benchmark),
        on="date",
        how="left",
        validate="one_to_one",
    )
    result["benchmark_available"] = result["benchmark_return"].notna()

    leg_columns = {
        "long": "long_basket_return",
        "short_underlying": "short_basket_underlying_return",
    }
    for label, column in leg_columns.items():
        result[f"{label}_beta_{beta_window}d"] = rolling_beta(
            result[column],
            result["benchmark_return"],
            window=beta_window,
            min_observations=beta_min_observations,
        )
        for direction in ("up", "down"):
            beta, count = rolling_conditional_beta(
                result[column],
                result["benchmark_return"],
                direction=direction,
                window=beta_window,
                min_observations=conditional_min_observations,
            )
            result[f"{label}_{direction}_beta_{beta_window}d"] = beta
            result[
                f"{direction}_market_observations_{beta_window}d"
            ] = count
        result[f"{label}_volatility_{volatility_window}d"] = (
            result[column]
            .rolling(
                volatility_window,
                min_periods=volatility_window,
            )
            .std(ddof=1)
            * np.sqrt(ANNUALIZATION)
        )

    result[f"portfolio_beta_{beta_window}d"] = rolling_beta(
        result["portfolio_return"],
        result["benchmark_return"],
        window=beta_window,
        min_observations=beta_min_observations,
    )
    result[f"beta_gap_short_minus_long_{beta_window}d"] = (
        result[f"short_underlying_beta_{beta_window}d"]
        - result[f"long_beta_{beta_window}d"]
    )
    result[f"portfolio_up_beta_{beta_window}d"] = (
        result[f"long_up_beta_{beta_window}d"]
        - result[f"short_underlying_up_beta_{beta_window}d"]
    )
    result[f"portfolio_down_beta_{beta_window}d"] = (
        result[f"long_down_beta_{beta_window}d"]
        - result[f"short_underlying_down_beta_{beta_window}d"]
    )
    result[f"portfolio_volatility_{volatility_window}d"] = (
        result["portfolio_return"]
        .rolling(
            volatility_window,
            min_periods=volatility_window,
        )
        .std(ddof=1)
        * np.sqrt(ANNUALIZATION)
    )

    direct_identity = (
        result[f"portfolio_beta_{beta_window}d"]
        - result[f"long_beta_{beta_window}d"]
        + result[f"short_underlying_beta_{beta_window}d"]
    ).abs()
    if direct_identity.dropna().max() > 1e-10:
        raise AssertionError("portfolio beta does not equal long beta minus short beta")

    for label in ("long_contribution", "short_contribution", "portfolio_return"):
        result[f"{label}_{contribution_window}d"] = result[label].rolling(
            contribution_window,
            min_periods=contribution_window,
        ).sum()
    result = result.rename(
        columns={
            f"portfolio_return_{contribution_window}d": (
                f"portfolio_contribution_{contribution_window}d"
            )
        }
    )
    contribution_error = (
        result[f"portfolio_contribution_{contribution_window}d"]
        - result[f"long_contribution_{contribution_window}d"]
        - result[f"short_contribution_{contribution_window}d"]
    ).abs()
    if contribution_error.dropna().max() > 1e-12:
        raise AssertionError("rolling contribution does not reconcile")

    computed_drawdown = _drawdown(result["portfolio_return"])
    if (computed_drawdown - result["drawdown"]).abs().max() > 1e-12:
        raise ValueError("stored portfolio drawdown does not match returns")
    result["portfolio_drawdown"] = computed_drawdown

    if regime_history is None:
        result["early_recovery_state"] = pd.Series(
            pd.NA,
            index=result.index,
            dtype="boolean",
        )
        result["high_volatility_recovery_state"] = pd.Series(
            pd.NA,
            index=result.index,
            dtype="boolean",
        )
    else:
        missing = sorted(set(REGIME_COLUMNS) - set(regime_history.columns))
        if missing:
            raise KeyError(f"regime history missing required columns: {missing}")
        regimes = regime_history.loc[:, REGIME_COLUMNS].copy()
        regimes["date"] = pd.to_datetime(regimes["date"])
        result = result.drop(
            columns=[
                "early_recovery_state",
                "high_volatility_recovery_state",
            ],
            errors="ignore",
        ).merge(
            regimes,
            on="date",
            how="left",
            validate="one_to_one",
        )

    result["beta_window"] = beta_window
    result["beta_min_observations"] = beta_min_observations
    result["conditional_beta_min_observations"] = conditional_min_observations
    result["volatility_window"] = volatility_window
    result["contribution_window"] = contribution_window
    result["risk_timing"] = (
        "post-close trailing statistics; earliest use is next trading session"
    )
    return result


RECOVERY_OUTPUT_COLUMNS = (
    "episode_id",
    "start_date",
    "end_date",
    "trading_days",
    "high_volatility_recovery_days",
    "long_net_contribution",
    "short_net_contribution",
    "portfolio_net_contribution",
    "short_loss_magnitude",
    "long_loss_magnitude",
    "short_share_of_gross_leg_losses",
    "minimum_portfolio_drawdown",
    "contribution_reconciliation_error",
    "membership_status",
    "survivorship_bias",
)


def build_recovery_attribution(risk_history: pd.DataFrame) -> pd.DataFrame:
    """Aggregate signed leg P&L over contiguous early-recovery episodes."""

    required = {
        "date",
        "early_recovery_state",
        "high_volatility_recovery_state",
        "long_contribution",
        "short_contribution",
        "portfolio_return",
        "portfolio_drawdown",
        "membership_status",
        "survivorship_bias",
    }
    missing = sorted(required - set(risk_history.columns))
    if missing:
        raise KeyError(f"risk history missing recovery fields: {missing}")
    frame = risk_history.sort_values("date").copy()
    active = frame["early_recovery_state"].fillna(False).astype(bool)
    starts = active & ~active.shift(fill_value=False)
    frame["episode_id"] = starts.cumsum().where(active)

    records: list[dict[str, Any]] = []
    for episode_id, group in frame.loc[active].groupby("episode_id", sort=True):
        long_net = float(group["long_contribution"].sum())
        short_net = float(group["short_contribution"].sum())
        portfolio_net = float(group["portfolio_return"].sum())
        short_loss = float((-group["short_contribution"].clip(upper=0.0)).sum())
        long_loss = float((-group["long_contribution"].clip(upper=0.0)).sum())
        gross_leg_losses = short_loss + long_loss
        records.append(
            {
                "episode_id": int(episode_id),
                "start_date": group["date"].min(),
                "end_date": group["date"].max(),
                "trading_days": int(len(group)),
                "high_volatility_recovery_days": int(
                    group["high_volatility_recovery_state"]
                    .fillna(False)
                    .astype(bool)
                    .sum()
                ),
                "long_net_contribution": long_net,
                "short_net_contribution": short_net,
                "portfolio_net_contribution": portfolio_net,
                "short_loss_magnitude": short_loss,
                "long_loss_magnitude": long_loss,
                "short_share_of_gross_leg_losses": (
                    short_loss / gross_leg_losses
                    if gross_leg_losses > 0.0
                    else np.nan
                ),
                "minimum_portfolio_drawdown": float(
                    group["portfolio_drawdown"].min()
                ),
                "contribution_reconciliation_error": abs(
                    portfolio_net - long_net - short_net
                ),
                "membership_status": group["membership_status"].iloc[-1],
                "survivorship_bias": bool(group["survivorship_bias"].iloc[-1]),
            }
        )
    if not records:
        return pd.DataFrame(columns=RECOVERY_OUTPUT_COLUMNS)
    return pd.DataFrame.from_records(records).loc[:, RECOVERY_OUTPUT_COLUMNS]


def load_benchmark(processed_dir: Path) -> tuple[pd.DataFrame, str]:
    """Load SPY when present, otherwise label the existing broad-market fallback."""

    spy_path = processed_dir / "sp500_benchmark.parquet"
    if spy_path.is_file():
        return pd.read_parquet(spy_path), "primary_spy_total_return_proxy"

    factors = pd.read_parquet(
        processed_dir / "french_research_factors_daily.parquet",
        columns=["date", "mkt_total_return"],
    )
    factors = factors.rename(columns={"mkt_total_return": "benchmark_return"})
    factors["benchmark_source"] = "Ken French broad US market total-return proxy"
    factors["benchmark_status"] = "fallback_broad_us_market_proxy"
    return factors, "fallback_broad_us_market_proxy"


def risk_audit(
    history: pd.DataFrame,
    recovery: pd.DataFrame,
    *,
    benchmark_status: str,
) -> dict[str, Any]:
    beta_column = f"portfolio_beta_{BETA_WINDOW}d"
    contribution_error = (
        history[f"portfolio_contribution_{CONTRIBUTION_WINDOW}d"]
        - history[f"long_contribution_{CONTRIBUTION_WINDOW}d"]
        - history[f"short_contribution_{CONTRIBUTION_WINDOW}d"]
    ).abs()
    return {
        "history_rows": int(len(history)),
        "first_date": history["date"].min().date().isoformat(),
        "last_date": history["date"].max().date().isoformat(),
        "benchmark_status": benchmark_status,
        "benchmark_available_rows": int(history["benchmark_available"].sum()),
        "beta_available_rows": int(history[beta_column].notna().sum()),
        "beta_window": BETA_WINDOW,
        "beta_min_observations": BETA_MIN_OBSERVATIONS,
        "conditional_beta_min_observations": CONDITIONAL_BETA_MIN_OBSERVATIONS,
        "volatility_window": VOLATILITY_WINDOW,
        "contribution_window": CONTRIBUTION_WINDOW,
        "recovery_episodes": int(len(recovery)),
        "maximum_daily_contribution_error": float(
            (
                history["portfolio_return"]
                - history["long_contribution"]
                - history["short_contribution"]
            )
            .abs()
            .max()
        ),
        "maximum_rolling_contribution_error": float(
            contribution_error.dropna().max()
        ),
        "membership_status": history["membership_status"].iloc[-1],
        "survivorship_bias": bool(history["survivorship_bias"].iloc[-1]),
        "benchmark_interpretation": (
            "SPY is an investable total-return proxy, not the official S&P 500 "
            "cash or total-return index"
            if benchmark_status == "primary_spy_total_return_proxy"
            else "Ken French broad US market proxy; not the S&P 500"
        ),
    }


def run_leg_decomposition(
    *,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR / "risk",
) -> dict[str, Any]:
    """Build, persist, and audit Phase 3 risk and recovery outputs."""

    portfolio = pd.read_parquet(
        processed_dir / "momentum_portfolio_returns.parquet"
    )
    benchmark, benchmark_status = load_benchmark(processed_dir)
    factors = pd.read_parquet(
        processed_dir / "french_research_factors_daily.parquet",
        columns=["date", "mkt_total_return", "rf"],
    )
    regimes = build_regime_history(factors)
    history = build_leg_risk_history(
        portfolio,
        benchmark,
        regime_history=regimes,
    )
    recovery = build_recovery_attribution(history)

    write_parquet(history, processed_dir / "leg_risk_history.parquet")
    write_parquet(recovery, processed_dir / "recovery_attribution.parquet")
    output_dir.mkdir(parents=True, exist_ok=True)
    recovery.to_csv(output_dir / "recovery_attribution.csv", index=False)

    sample_dates = [pd.Timestamp("2020-03-24"), history["date"].max()]
    sample_paths: list[str] = []
    for sample_date in sample_dates:
        sample = history.loc[history["date"].eq(sample_date)]
        if sample.empty:
            continue
        path = output_dir / f"leg_risk_{sample_date.date().isoformat()}.csv"
        sample.to_csv(path, index=False)
        sample_paths.append(str(path.relative_to(REPO_ROOT)))

    audit = risk_audit(
        history,
        recovery,
        benchmark_status=benchmark_status,
    )
    audit["sample_outputs"] = sample_paths
    write_json(output_dir / "leg_risk_audit.json", audit)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR / "risk")
    args = parser.parse_args()
    report = run_leg_decomposition(
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
