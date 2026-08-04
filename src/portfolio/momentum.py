"""Transparent monthly 12-1 S&P 500 momentum portfolio.

At the close of formation month ``m`` the signal is
``P[m-1] / P[m-12] - 1``.  Month ``m`` is deliberately skipped.  The top and
bottom names are then held, at equal signed weights, throughout month ``m+1``.

The universe is a frozen current SPY snapshot.  That makes the historical
portfolio a survivorship-biased demonstration, not a point-in-time S&P 500
backtest.  This module carries that status into every holdings and audit output.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    REPO_ROOT,
    write_json,
    write_parquet,
)


LOOKBACK_MONTHS = 12
SKIP_MONTHS = 1
MEMBERSHIP_STATUS = "current_snapshot_proxy"


def _validate_prices(prices: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "symbol", "close_total_return_adjusted"}
    missing = sorted(required - set(prices.columns))
    if missing:
        raise KeyError(f"prices missing required columns: {missing}")
    frame = prices.loc[:, sorted(required)].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["symbol"] = frame["symbol"].astype(str)
    frame["close_total_return_adjusted"] = pd.to_numeric(
        frame["close_total_return_adjusted"], errors="coerce"
    )
    frame = frame.dropna(subset=["date", "symbol", "close_total_return_adjusted"])
    frame = frame.loc[frame["close_total_return_adjusted"] > 0]
    frame = frame.sort_values(["symbol", "date"])
    if frame.duplicated(["symbol", "date"]).any():
        raise ValueError("prices contain duplicate symbol/date observations")
    return frame


def month_end_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """Last available total-return adjusted close in each calendar month."""

    frame = _validate_prices(prices)
    frame["month"] = frame["date"].dt.to_period("M")
    return (
        frame.groupby(["symbol", "month"], as_index=False)
        .last()
        .rename(
            columns={
                "date": "month_end_date",
                "close_total_return_adjusted": "month_end_close",
            }
        )
    )


def build_momentum_signals(
    prices: pd.DataFrame,
    *,
    exclude_incomplete_last_month: bool = True,
) -> pd.DataFrame:
    """Build exact calendar-month 12-1 signals without row-shift shortcuts."""

    monthly = month_end_prices(prices)
    last_date = monthly["month_end_date"].max()
    if exclude_incomplete_last_month and not _last_month_is_complete(last_date):
        monthly = monthly.loc[monthly["month"].ne(last_date.to_period("M"))].copy()
    calendar = pd.DataFrame(
        {"formation_month": sorted(monthly["month"].unique())}
    )
    symbols = pd.DataFrame({"symbol": sorted(monthly["symbol"].unique())})
    grid = calendar.merge(symbols, how="cross")
    grid["start_month"] = grid["formation_month"] - LOOKBACK_MONTHS
    grid["end_month"] = grid["formation_month"] - SKIP_MONTHS

    start = monthly.rename(
        columns={
            "month": "start_month",
            "month_end_date": "signal_start_date",
            "month_end_close": "signal_start_close",
        }
    )
    end = monthly.rename(
        columns={
            "month": "end_month",
            "month_end_date": "signal_end_date",
            "month_end_close": "signal_end_close",
        }
    )
    signals = grid.merge(
        start,
        on=["symbol", "start_month"],
        how="left",
        validate="many_to_one",
    ).merge(
        end,
        on=["symbol", "end_month"],
        how="left",
        validate="many_to_one",
    )

    formation_dates = (
        monthly.groupby("month")["month_end_date"]
        .max()
        .rename_axis("formation_month")
        .rename("formation_date")
    )
    signals = signals.merge(
        formation_dates,
        on="formation_month",
        how="left",
        validate="many_to_one",
    )
    signals["momentum_return"] = np.where(
        signals["signal_start_close"].gt(0) & signals["signal_end_close"].notna(),
        signals["signal_end_close"] / signals["signal_start_close"] - 1.0,
        np.nan,
    )
    signals["effective_month"] = signals["formation_month"] + 1
    return signals.dropna(subset=["momentum_return"]).sort_values(
        ["formation_month", "symbol"]
    ).reset_index(drop=True)


def build_momentum_rank_snapshot(
    prices: pd.DataFrame,
    *,
    exclude_incomplete_last_month: bool = True,
) -> pd.DataFrame:
    """Build the canonical formation-date momentum rank snapshot.

    ``price_momentum_rank`` preserves the portfolio's deterministic ordinal
    convention (one is the strongest winner). ``momentum_rank`` is the
    winner-high percentile exposure used by cross-sectional diagnostics.
    Both are formed once per calendar month and become effective in month
    ``m+1``.
    """

    signals = build_momentum_signals(
        prices,
        exclude_incomplete_last_month=exclude_incomplete_last_month,
    )
    if signals.empty:
        return signals.assign(
            price_momentum_rank=pd.Series(dtype="int64"),
            momentum_rank=pd.Series(dtype="float64"),
            rankable_universe=pd.Series(dtype="int64"),
        )

    records: list[pd.DataFrame] = []
    for _, group in signals.groupby("formation_month", sort=True):
        ranked = group.sort_values(
            ["momentum_return", "symbol"],
            ascending=[False, True],
        ).copy()
        rankable = len(ranked)
        ranked["price_momentum_rank"] = np.arange(1, rankable + 1)
        ranked["momentum_rank"] = 1.0 - (
            ranked["price_momentum_rank"] / (rankable + 1.0)
        )
        ranked["rankable_universe"] = rankable
        records.append(ranked)
    return pd.concat(records, ignore_index=True).sort_values(
        ["formation_month", "price_momentum_rank", "symbol"]
    ).reset_index(drop=True)


def build_momentum_holdings(
    prices: pd.DataFrame,
    universe: pd.DataFrame | None = None,
    *,
    n_long: int = 10,
    n_short: int = 10,
) -> pd.DataFrame:
    """Rank signals deterministically and return next-month signed holdings."""

    if n_long <= 0 or n_short <= 0:
        raise ValueError("n_long and n_short must both be positive")
    filtered = prices
    if universe is not None:
        if "symbol" not in universe:
            raise KeyError("universe missing required column: symbol")
        allowed = set(universe["symbol"].astype(str))
        filtered = prices.loc[prices["symbol"].astype(str).isin(allowed)].copy()

    signals = build_momentum_rank_snapshot(filtered)
    records: list[pd.DataFrame] = []
    for _, group in signals.groupby("formation_month", sort=True):
        ranked = group.sort_values(["price_momentum_rank", "symbol"]).copy()
        rankable = len(ranked)
        if rankable < n_long + n_short:
            continue
        long = ranked.head(n_long).copy()
        short = ranked.tail(n_short).sort_values(
            ["momentum_return", "symbol"],
            ascending=[True, True],
        ).copy()
        long["leg"] = "long"
        long["weight"] = 1.0 / n_long
        short["leg"] = "short"
        short["weight"] = -1.0 / n_short
        selected = pd.concat([long, short], ignore_index=True)
        selected["n_long"] = n_long
        selected["n_short"] = n_short
        selected["membership_status"] = MEMBERSHIP_STATUS
        selected["survivorship_bias"] = True
        records.append(selected)

    if not records:
        return pd.DataFrame()
    holdings = pd.concat(records, ignore_index=True)
    columns = [
        "formation_date",
        "formation_month",
        "effective_month",
        "symbol",
        "leg",
        "weight",
        "momentum_return",
        "price_momentum_rank",
        "signal_start_date",
        "signal_start_close",
        "signal_end_date",
        "signal_end_close",
        "rankable_universe",
        "n_long",
        "n_short",
        "membership_status",
        "survivorship_bias",
    ]
    return holdings.loc[:, columns].sort_values(
        ["effective_month", "leg", "price_momentum_rank", "symbol"]
    ).reset_index(drop=True)


def _last_month_is_complete(last_date: pd.Timestamp) -> bool:
    normalized = pd.Timestamp(last_date).normalize()
    return bool(
        normalized.is_month_end
        or normalized == normalized + pd.offsets.BMonthEnd(0)
    )


def build_portfolio_returns(
    prices: pd.DataFrame,
    holdings: pd.DataFrame,
    *,
    exclude_incomplete_last_month: bool = True,
) -> pd.DataFrame:
    """Apply month-start equal weights that drift until the next rebalance.

    Each leg is normalized to gross exposure one at the start of its holding
    month.  Thereafter its constituent weights move with relative wealth until
    the next month begins.  This is a monthly-rebalanced portfolio, not the
    daily equal-weighted average that would result from reapplying the target
    weights every session.

    If any selected constituent return is missing, that leg is unavailable
    from that date through month-end because its subsequent drifted weights
    cannot be reconstructed without an imputation.
    """

    if holdings.empty:
        return pd.DataFrame()
    frame = _validate_prices(prices)
    frame["asset_return"] = frame.groupby("symbol", sort=False)[
        "close_total_return_adjusted"
    ].pct_change(fill_method=None)
    frame["effective_month"] = frame["date"].dt.to_period("M")

    active = holdings.loc[
        :, ["formation_date", "effective_month", "symbol", "leg", "weight"]
    ]
    calendar = frame.loc[:, ["date", "effective_month"]].drop_duplicates()
    expected = calendar.merge(
        active,
        on="effective_month",
        how="inner",
        validate="many_to_many",
    ).merge(
        frame.loc[:, ["date", "symbol", "asset_return"]],
        on=["date", "symbol"],
        how="left",
        validate="many_to_one",
    )

    records: list[pd.DataFrame] = []
    grouping = ["formation_date", "effective_month", "leg"]
    for keys, group in expected.groupby(grouping, sort=True):
        formation_date, effective_month, leg = keys
        symbols = sorted(group["symbol"].unique())
        returns = group.pivot(
            index="date",
            columns="symbol",
            values="asset_return",
        ).reindex(columns=symbols)
        target = (
            active.loc[
                active["effective_month"].eq(effective_month)
                & active["leg"].eq(leg),
                ["symbol", "weight"],
            ]
            .drop_duplicates("symbol")
            .set_index("symbol")["weight"]
            .abs()
            .reindex(symbols)
        )
        if target.isna().any() or not np.isclose(target.sum(), 1.0):
            raise ValueError(
                f"{effective_month} {leg} target weights do not sum to one"
            )

        valid_today = returns.notna().all(axis=1)
        valid_through_today = valid_today.cummin()
        prior_relative_wealth = (
            (1.0 + returns).cumprod(skipna=False).shift(1).fillna(1.0)
        )
        beginning_values = prior_relative_wealth.mul(target, axis="columns")
        beginning_weights = beginning_values.div(
            beginning_values.sum(axis=1),
            axis="index",
        )
        underlying_return = (beginning_weights * returns).sum(
            axis=1,
            min_count=len(symbols),
        )
        underlying_return = underlying_return.where(valid_through_today)
        signed_contribution = (
            underlying_return if leg == "long" else -underlying_return
        )
        records.append(
            pd.DataFrame(
                {
                    "date": returns.index,
                    "formation_date": formation_date,
                    "effective_month": effective_month,
                    "leg": leg,
                    "observed_names": returns.notna().sum(axis=1).to_numpy(),
                    "expected_names": len(symbols),
                    "underlying_return": underlying_return.to_numpy(),
                    "signed_contribution": signed_contribution.to_numpy(),
                }
            )
        )

    daily = pd.concat(records, ignore_index=True) if records else pd.DataFrame()

    returns = daily.pivot(
        index=["date", "formation_date", "effective_month"],
        columns="leg",
        values=[
            "underlying_return",
            "signed_contribution",
            "observed_names",
            "expected_names",
        ],
    )
    returns.columns = [f"{measure}_{leg}" for measure, leg in returns.columns]
    returns = returns.reset_index()
    required = {
        "underlying_return_long",
        "underlying_return_short",
        "signed_contribution_long",
        "signed_contribution_short",
    }
    if not required.issubset(returns):
        return pd.DataFrame()

    returns = returns.rename(
        columns={
            "underlying_return_long": "long_basket_return",
            "underlying_return_short": "short_basket_underlying_return",
            "signed_contribution_long": "long_contribution",
            "signed_contribution_short": "short_contribution",
            "observed_names_long": "long_names_observed",
            "observed_names_short": "short_names_observed",
            "expected_names_long": "long_names_expected",
            "expected_names_short": "short_names_expected",
        }
    )
    returns["portfolio_return"] = (
        returns["long_contribution"] + returns["short_contribution"]
    )
    returns["return_complete"] = returns[
        ["long_contribution", "short_contribution"]
    ].notna().all(axis=1)

    if exclude_incomplete_last_month:
        last_date = frame["date"].max()
        if not _last_month_is_complete(last_date):
            returns = returns.loc[
                returns["effective_month"] != last_date.to_period("M")
            ].copy()

    returns = returns.sort_values("date").reset_index(drop=True)
    wealth = (1.0 + returns["portfolio_return"]).cumprod(skipna=False)
    returns["cumulative_return"] = wealth - 1.0
    returns["drawdown"] = wealth / wealth.cummax() - 1.0
    returns["membership_status"] = MEMBERSHIP_STATUS
    returns["survivorship_bias"] = True
    return returns


def portfolio_audit(
    universe: pd.DataFrame,
    prices: pd.DataFrame,
    holdings: pd.DataFrame,
    returns: pd.DataFrame,
    *,
    n_long: int,
    n_short: int,
) -> dict[str, Any]:
    """Summarize coverage, alignment, and known bias for downstream review."""

    universe_symbols = set(universe["symbol"].astype(str))
    priced_symbols = set(prices["symbol"].astype(str))
    formation_dates = (
        holdings["formation_date"].drop_duplicates().sort_values()
        if not holdings.empty
        else pd.Series(dtype="datetime64[ns]")
    )
    return {
        "universe_constituents": int(len(universe_symbols)),
        "priced_constituents": int(len(universe_symbols & priced_symbols)),
        "price_coverage": round(
            len(universe_symbols & priced_symbols) / max(1, len(universe_symbols)), 6
        ),
        "first_price_date": (
            pd.Timestamp(prices["date"].min()).date().isoformat()
            if not prices.empty
            else None
        ),
        "last_price_date": (
            pd.Timestamp(prices["date"].max()).date().isoformat()
            if not prices.empty
            else None
        ),
        "first_formation_date": (
            pd.Timestamp(formation_dates.iloc[0]).date().isoformat()
            if len(formation_dates)
            else None
        ),
        "last_formation_date": (
            pd.Timestamp(formation_dates.iloc[-1]).date().isoformat()
            if len(formation_dates)
            else None
        ),
        "formation_count": int(len(formation_dates)),
        "holding_rows": int(len(holdings)),
        "return_rows": int(len(returns)),
        "complete_return_rows": (
            int(returns["return_complete"].sum()) if not returns.empty else 0
        ),
        "n_long": n_long,
        "n_short": n_short,
        "signal": "P[m-1] / P[m-12] - 1; month m skipped",
        "formation_and_execution": (
            "rank after month-m close; equal weights are set at the start of "
            "month m+1 and drift until the next monthly rebalance"
        ),
        "missing_return_rule": (
            "each leg is unavailable from its first missing constituent return "
            "through month-end; no zero fill and no hidden reweighting"
        ),
        "intra_month_weighting": (
            "equal gross-one leg weights at month start; weights drift with "
            "relative constituent wealth until the next monthly rebalance"
        ),
        "membership_status": MEMBERSHIP_STATUS,
        "survivorship_bias": True,
        "historical_interpretation": (
            "current-constituent proxy; not a point-in-time S&P 500 backtest"
        ),
    }


def run_momentum_portfolio(
    *,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR / "portfolio",
    n_long: int = 10,
    n_short: int = 10,
) -> dict[str, Any]:
    """Build and persist holdings, daily returns, audit, and one 2023 example."""

    universe = pd.read_parquet(processed_dir / "sp500_universe.parquet")
    prices = pd.read_parquet(processed_dir / "sp500_prices.parquet")
    holdings = build_momentum_holdings(
        prices,
        universe,
        n_long=n_long,
        n_short=n_short,
    )
    returns = build_portfolio_returns(prices, holdings)
    if holdings.empty or returns.empty:
        raise ValueError("No momentum portfolio could be built from the supplied data")

    write_parquet(
        holdings,
        processed_dir / "momentum_portfolio_holdings.parquet",
    )
    write_parquet(
        returns,
        processed_dir / "momentum_portfolio_returns.parquet",
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    audit = portfolio_audit(
        universe,
        prices,
        holdings,
        returns,
        n_long=n_long,
        n_short=n_short,
    )
    write_json(output_dir / "portfolio_audit.json", audit)

    example = holdings.loc[
        holdings["formation_date"].dt.year.eq(2023)
    ]
    if not example.empty:
        example_date = example["formation_date"].max()
        example = example.loc[example["formation_date"].eq(example_date)]
    else:
        example_date = holdings["formation_date"].max()
        example = holdings.loc[holdings["formation_date"].eq(example_date)]
    example_path = output_dir / (
        f"momentum_holdings_{pd.Timestamp(example_date).date().isoformat()}.csv"
    )
    example.to_csv(example_path, index=False)
    audit["example_holdings_path"] = str(example_path.relative_to(REPO_ROOT))
    write_json(output_dir / "portfolio_audit.json", audit)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR / "portfolio")
    parser.add_argument("--n-long", type=int, default=10)
    parser.add_argument("--n-short", type=int, default=10)
    args = parser.parse_args()
    report = run_momentum_portfolio(
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
        n_long=args.n_long,
        n_short=args.n_short,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
