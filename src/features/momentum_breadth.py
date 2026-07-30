"""Point-in-time breadth diagnostics for the Phase 2 momentum universe."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.portfolio.momentum import build_momentum_signals


BREADTH_HISTORY_COLUMNS = (
    "formation_date",
    "formation_month",
    "eligible_count",
    "positive_momentum_count",
    "universe_positive_12_1_share",
    "breadth_change_vs_previous",
    "breadth_change_vs_prior_3_rebalance_high",
    "momentum_score_median",
    "momentum_score_dispersion",
    "top_decile_median_gap",
    "positive_momentum_leadership_hhi",
    "top10_positive_momentum_share",
    "long_21d_participation_share",
    "long_21d_participation_count",
    "long_21d_available_count",
    "long_entry_count",
    "long_exit_count",
    "long_overlap_share",
    "universe_rank_persistence",
    "membership_status",
    "survivorship_bias",
)


def _finite_or_none(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def summarize_momentum_snapshot(snapshot: pd.DataFrame) -> dict[str, Any]:
    """Summarize one cross-section of valid 12-1 momentum signals."""

    if not {"symbol", "momentum_return"}.issubset(snapshot.columns):
        raise KeyError("snapshot requires symbol and momentum_return columns")
    frame = snapshot.loc[:, ["symbol", "momentum_return"]].copy()
    frame["symbol"] = frame["symbol"].astype(str)
    frame["momentum_return"] = pd.to_numeric(
        frame["momentum_return"],
        errors="coerce",
    )
    frame = frame.dropna(subset=["symbol", "momentum_return"])
    if frame.empty:
        raise ValueError("momentum snapshot has no valid observations")
    if frame["symbol"].duplicated().any():
        raise ValueError("momentum snapshot contains duplicate symbols")
    if not np.isfinite(frame["momentum_return"]).all():
        raise ValueError("momentum snapshot contains non-finite values")

    values = frame["momentum_return"]
    positive = values.clip(lower=0.0)
    positive_total = float(positive.sum())
    leadership_hhi: float | None
    top10_share: float | None
    if positive_total <= 0.0:
        leadership_hhi = None
        top10_share = None
    else:
        normalized = positive / positive_total
        leadership_hhi = float(np.square(normalized).sum())
        top10_share = float(
            positive.nlargest(min(10, len(positive))).sum() / positive_total
        )

    top_decile_count = max(1, int(np.ceil(len(frame) * 0.10)))
    return {
        "eligible_count": int(len(frame)),
        "positive_momentum_count": int(values.gt(0.0).sum()),
        "universe_positive_12_1_share": float(values.gt(0.0).mean()),
        "momentum_score_median": float(values.median()),
        "momentum_score_dispersion": float(values.std(ddof=0)),
        "top_decile_median_gap": float(
            values.nlargest(top_decile_count).median() - values.median()
        ),
        "positive_momentum_leadership_hhi": leadership_hhi,
        "top10_positive_momentum_share": top10_share,
    }


def _ranked_snapshot(group: pd.DataFrame) -> pd.DataFrame:
    ranked = group.sort_values(
        ["momentum_return", "symbol"],
        ascending=[False, True],
    ).copy()
    ranked["price_momentum_rank"] = np.arange(1, len(ranked) + 1)
    return ranked


def _rank_persistence(
    current: pd.DataFrame,
    previous: pd.DataFrame | None,
) -> float | None:
    if previous is None:
        return None
    common = current.loc[:, ["symbol", "price_momentum_rank"]].merge(
        previous.loc[:, ["symbol", "price_momentum_rank"]],
        on="symbol",
        suffixes=("_current", "_previous"),
    )
    if len(common) < 2:
        return None
    return _finite_or_none(
        common["price_momentum_rank_current"].corr(
            common["price_momentum_rank_previous"],
            method="spearman",
        )
    )


def _price_return_21d(prices: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "symbol", "close_total_return_adjusted"}
    missing = sorted(required - set(prices.columns))
    if missing:
        raise KeyError(f"prices missing required columns: {missing}")
    frame = prices.loc[:, sorted(required)].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str)
    frame["close_total_return_adjusted"] = pd.to_numeric(
        frame["close_total_return_adjusted"],
        errors="coerce",
    )
    frame = frame.dropna(subset=["date", "symbol", "close_total_return_adjusted"])
    frame = frame.loc[frame["close_total_return_adjusted"].gt(0)].copy()
    frame = frame.sort_values(["symbol", "date"]).reset_index(drop=True)
    if frame.duplicated(["symbol", "date"]).any():
        raise ValueError("prices contain duplicate symbol/date observations")
    frame["return_21d"] = frame.groupby("symbol", sort=False)[
        "close_total_return_adjusted"
    ].pct_change(21, fill_method=None)
    return frame.loc[:, ["date", "symbol", "return_21d"]]


def _validated_holdings(holdings: pd.DataFrame | None) -> pd.DataFrame | None:
    if holdings is None:
        return None
    required = {"formation_date", "symbol", "leg"}
    missing = sorted(required - set(holdings.columns))
    if missing:
        raise KeyError(f"holdings missing required columns: {missing}")
    frame = holdings.loc[:, sorted(required)].copy()
    frame["formation_date"] = pd.to_datetime(frame["formation_date"]).dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str)
    frame = frame.loc[frame["leg"].eq("long")].copy()
    if frame.duplicated(["formation_date", "symbol"]).any():
        raise ValueError("holdings contain duplicate formation/symbol rows")
    return frame


def build_momentum_breadth_history(
    prices: pd.DataFrame,
    *,
    universe: pd.DataFrame | None = None,
    holdings: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build monthly breadth from the existing Phase 2 12-1 signal.

    Historical values are calculated only from data through each formation
    date. When supplied, long-leg participation uses the selected formation's
    long names and their trailing 21 trading-day price returns.
    """

    filtered_prices = prices
    membership_status = "current_snapshot_proxy"
    survivorship_bias = True
    if universe is not None:
        if "symbol" not in universe.columns:
            raise KeyError("universe missing required column: symbol")
        allowed = set(universe["symbol"].astype(str))
        filtered_prices = prices.loc[
            prices["symbol"].astype(str).isin(allowed)
        ].copy()
        if (
            "membership_status" in universe
            and universe["membership_status"].notna().any()
        ):
            membership_status = str(
                universe["membership_status"].dropna().iloc[0]
            )
        if "survivorship_bias" in universe:
            survivorship_bias = bool(
                universe["survivorship_bias"].fillna(True).all()
            )

    signals = build_momentum_signals(filtered_prices)
    if signals.empty:
        return pd.DataFrame(columns=BREADTH_HISTORY_COLUMNS)
    long_holdings = _validated_holdings(holdings)
    returns_21d = _price_return_21d(filtered_prices)

    records: list[dict[str, Any]] = []
    previous_ranked: pd.DataFrame | None = None
    previous_long_symbols: set[str] | None = None
    prior_breadth: list[float] = []
    for formation_date, group in signals.groupby("formation_date", sort=True):
        formation_date = pd.Timestamp(formation_date).normalize()
        ranked = _ranked_snapshot(group)
        summary = summarize_momentum_snapshot(ranked)
        breadth = float(summary["universe_positive_12_1_share"])
        previous_breadth = prior_breadth[-1] if prior_breadth else None
        prior_three_high = (
            max(prior_breadth[-3:]) if prior_breadth else None
        )

        long_symbols: set[str] = set()
        if long_holdings is not None:
            long_symbols = set(
                long_holdings.loc[
                    long_holdings["formation_date"].eq(formation_date),
                    "symbol",
                ]
            )
        if long_symbols:
            selected_returns = returns_21d.loc[
                returns_21d["date"].eq(formation_date)
                & returns_21d["symbol"].isin(long_symbols),
                "return_21d",
            ].dropna()
            available_long = int(len(selected_returns))
            positive_long = int(selected_returns.gt(0.0).sum())
            participation = (
                None
                if available_long == 0
                else float(positive_long / available_long)
            )
        else:
            available_long = 0
            positive_long = 0
            participation = None

        if previous_long_symbols is None or not long_symbols:
            entries = None
            exits = None
            overlap_share = None
        else:
            entries = len(long_symbols - previous_long_symbols)
            exits = len(previous_long_symbols - long_symbols)
            overlap_share = float(
                len(long_symbols & previous_long_symbols) / len(long_symbols)
            )

        records.append(
            {
                "formation_date": formation_date,
                "formation_month": ranked["formation_month"].iloc[0],
                **summary,
                "breadth_change_vs_previous": (
                    None
                    if previous_breadth is None
                    else breadth - previous_breadth
                ),
                "breadth_change_vs_prior_3_rebalance_high": (
                    None
                    if prior_three_high is None
                    else breadth - prior_three_high
                ),
                "long_21d_participation_share": participation,
                "long_21d_participation_count": (
                    positive_long if long_symbols else None
                ),
                "long_21d_available_count": (
                    available_long if long_symbols else None
                ),
                "long_entry_count": entries,
                "long_exit_count": exits,
                "long_overlap_share": overlap_share,
                "universe_rank_persistence": _rank_persistence(
                    ranked,
                    previous_ranked,
                ),
                "membership_status": membership_status,
                "survivorship_bias": survivorship_bias,
            }
        )
        prior_breadth.append(breadth)
        previous_ranked = ranked
        if long_symbols:
            previous_long_symbols = long_symbols

    result = pd.DataFrame(records)
    return result.loc[:, BREADTH_HISTORY_COLUMNS].sort_values(
        "formation_date"
    ).reset_index(drop=True)
