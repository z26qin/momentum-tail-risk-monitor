"""Loser-leg crowding: the structured alternative-data overlay.

Why this shape. Daniel-Moskowitz attribute momentum crashes to the *loser leg*
crashing upward during a market rebound out of a stressed, high-volatility
bear state. The observable precondition for that is a squeezed short leg. This
panel measures how squeezed the proxy loser leg is. It is a direct measurement
of the adopted mechanism, not a generic flow indicator.

Two complementary metrics, deliberately not substitutes:

``days_to_cover``
    Short interest divided by 20-day average daily volume — the standard
    squeeze measure, and a **position** measure. Between semi-monthly prints it
    is a step function.

``short_vol_share``
    Daily short volume divided by total volume in FINRA's daily files, 5-day
    mean — a **flow** measure of shorting activity. Available from 2018-08-01.

The single most important line in this module is the short-interest join. The
naive implementation joins on ``settlement_date`` and looks completely
innocuous while embedding roughly two weeks of look-ahead. Everything here
joins on ``publication_date``; settlement date is carried as metadata only.

Availability conventions, both consistent with the Phase 1 post-close
assessment contract:

* Short interest is treated as observable at the close of its **publication
  date** (FINRA publishes during that day).
* A FINRA daily short-volume file is treated as observable at the close of its
  **trade date**, because FINRA posts it no later than 6:00 p.m. ET that day —
  after the close, in time for a post-close assessment whose earliest action is
  the next session.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.finra import (
    apply_ticker_identity_guard,
    attach_publication_dates,
    detect_entity_changes,
)
from src.data.finra import TICKER_IDENTITY_FROM
from src.data.trading_calendar import build_trading_calendar
from src.utils.io import DEFAULT_OUTPUT_DIR, DEFAULT_PROCESSED_DIR, write_json
from src.utils.pit import ROLLING_WINDOW, rolling_z_pit


PANEL_START = pd.Timestamp("2017-01-01")

FORMATION_SKIP_MONTHS = 2
FORMATION_LOOKBACK_MONTHS = 12
LOSER_DECILE_FRACTION = 0.10
ADV_WINDOW = 20
SHORT_VOL_WINDOW = 5
MINIMUM_MATCH_RATE = 0.70


# --------------------------------------------------------------------------
# Proxy loser leg
# --------------------------------------------------------------------------


def month_end_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """Last observed adjusted close per symbol per calendar month."""

    frame = prices.loc[:, ["date", "symbol", "close_total_return_adjusted"]].copy()
    frame["month"] = frame["date"].dt.to_period("M")
    frame = frame.sort_values(["symbol", "date"])
    return (
        frame.groupby(["symbol", "month"], as_index=False)
        .last()
        .rename(columns={"close_total_return_adjusted": "month_end_close"})
    )


def formation_momentum(monthly: pd.DataFrame) -> pd.DataFrame:
    """12-2 momentum measured at each month end.

    Exactly as specified: the cumulative return from the month end 12 months
    before the rebalance to the month end 2 months before it. The most recent
    month is skipped, so nothing inside the rebalance month can influence the
    ranking.
    """

    frame = monthly.sort_values(["symbol", "month"]).copy()
    grouped = frame.groupby("symbol", sort=False)["month_end_close"]
    start = grouped.shift(FORMATION_LOOKBACK_MONTHS)
    end = grouped.shift(FORMATION_SKIP_MONTHS)
    frame["formation_start_close"] = start
    frame["formation_end_close"] = end
    frame["formation_return"] = np.where(
        (start.notna()) & (end.notna()) & (start > 0),
        end / start - 1.0,
        np.nan,
    )
    return frame


def build_leg_membership(
    prices: pd.DataFrame,
    trading_dates: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Assign each trading date the loser-leg constituents fixed at the prior month end.

    Membership is decided on the last trading day of month ``m`` and applies to
    every trading day of month ``m + 1``, so constituents are constant within a
    month and are never revised using information from inside the month they
    govern.
    """

    monthly = formation_momentum(month_end_prices(prices))
    ranked = monthly.dropna(subset=["formation_return"]).copy()

    records: list[dict[str, Any]] = []
    for month, group in ranked.groupby("month", sort=True):
        eligible = group.sort_values("formation_return")
        count = max(1, int(round(len(eligible) * LOSER_DECILE_FRACTION)))
        losers = eligible.head(count)
        effective_month = month + 1
        for row in losers.itertuples():
            records.append(
                {
                    "formation_month": month.to_timestamp(),
                    "effective_month": effective_month.to_timestamp(),
                    "symbol": row.symbol,
                    "formation_return": row.formation_return,
                    "rankable_universe": int(len(eligible)),
                    "leg_size": count,
                }
            )

    membership = pd.DataFrame.from_records(records)
    if membership.empty:
        return membership

    calendar = pd.DataFrame({"trading_date": trading_dates})
    calendar["effective_month"] = (
        calendar["trading_date"].dt.to_period("M").dt.to_timestamp()
    )
    return calendar.merge(membership, on="effective_month", how="inner")


# --------------------------------------------------------------------------
# Point-in-time short interest
# --------------------------------------------------------------------------


def short_interest_step_function(
    short_interest: pd.DataFrame,
    publication_map: pd.DataFrame,
    trading_dates: pd.DatetimeIndex,
    symbols: list[str],
) -> pd.DataFrame:
    """Expand semi-monthly short interest onto trading dates by publication date.

    ``merge_asof`` backwards on ``publication_date`` gives each trading date the
    most recently *published* print. Nothing dated after ``t`` can reach ``t``,
    which is the property the panel-level assertion re-checks directly.
    """

    joined = short_interest.merge(publication_map, on="settlement_date", how="left")
    joined = joined.dropna(subset=["publication_date"])
    joined = joined.sort_values(["publication_date", "symbol"])

    grid = pd.MultiIndex.from_product(
        [trading_dates, symbols], names=["trading_date", "symbol"]
    ).to_frame(index=False)
    grid = grid.sort_values(["trading_date", "symbol"])

    merged = pd.merge_asof(
        grid,
        joined.loc[
            :,
            [
                "publication_date",
                "symbol",
                "short_interest_shares",
                "settlement_date",
                "finra_average_daily_volume",
                "finra_days_to_cover",
                "publication_date_rule",
                "stock_split_flag",
                "revision_flag",
            ],
        ],
        left_on="trading_date",
        right_on="publication_date",
        by="symbol",
        direction="backward",
        allow_exact_matches=True,
    )
    return merged


# --------------------------------------------------------------------------
# Crowding metrics
# --------------------------------------------------------------------------


def average_daily_volume(prices: pd.DataFrame, window: int = ADV_WINDOW) -> pd.DataFrame:
    """Trailing average of as-traded share volume, ending at each date inclusive.

    As-traded rather than split-adjusted volume, because the numerator is a
    FINRA share count reported in the shares that existed on the settlement
    date.
    """

    frame = prices.loc[:, ["date", "symbol", "volume_as_traded"]].sort_values(
        ["symbol", "date"]
    )
    frame["adv_20d"] = (
        frame.groupby("symbol", sort=False)["volume_as_traded"]
        .rolling(window, min_periods=window)
        .mean()
        .reset_index(level=0, drop=True)
    )
    return frame.rename(columns={"date": "trading_date"})


def short_volume_share(daily: pd.DataFrame, window: int = SHORT_VOL_WINDOW) -> pd.DataFrame:
    """Daily short volume divided by total volume, smoothed over ``window`` sessions."""

    frame = daily.loc[
        :, ["trade_date", "symbol", "short_volume", "total_volume"]
    ].copy()
    frame = frame.sort_values(["symbol", "trade_date"])
    frame["short_volume_share_daily"] = np.where(
        frame["total_volume"] > 0,
        frame["short_volume"] / frame["total_volume"],
        np.nan,
    )
    frame["short_volume_share_5d"] = (
        frame.groupby("symbol", sort=False)["short_volume_share_daily"]
        .rolling(window, min_periods=window)
        .mean()
        .reset_index(level=0, drop=True)
    )
    return frame.rename(columns={"trade_date": "trading_date"})


def build_panel(
    *,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    start: pd.Timestamp = PANEL_START,
) -> dict[str, Any]:
    """Assemble ``positioning_panel.parquet`` and its diagnostics."""

    prices = pd.read_parquet(processed_dir / "universe_prices.parquet")
    short_interest = pd.read_parquet(processed_dir / "finra_short_interest.parquet")
    schedule = pd.read_parquet(processed_dir / "finra_publication_schedule.parquet")
    daily_path = processed_dir / "finra_daily_universe.parquet"
    daily = pd.read_parquet(daily_path) if daily_path.is_file() else pd.DataFrame()

    calendar = build_trading_calendar(processed_dir=processed_dir)
    trading_dates = calendar.between(start, calendar.dates.max())

    universe_symbols = sorted(prices["symbol"].unique())

    # --- symbology reconciliation -----------------------------------------
    from src.data.symbols import to_finra_short_interest

    vendor_to_canonical = {
        to_finra_short_interest(symbol): symbol for symbol in universe_symbols
    }
    short_interest = short_interest.copy()
    short_interest["symbol"] = short_interest["finra_symbol"].map(vendor_to_canonical)
    unmatched_short_interest = sorted(
        set(universe_symbols) - set(short_interest["symbol"].dropna().unique())
    )
    short_interest = short_interest.dropna(subset=["symbol"])

    # Reused tickers: drop rows dated before the ticker referred to the company
    # the price series describes. Without this, one company's short interest is
    # silently attached to another company's prices.
    entity_candidates = detect_entity_changes(short_interest)
    short_interest, si_identity_dropped = apply_ticker_identity_guard(
        short_interest, symbol_column="symbol", date_column="settlement_date"
    )

    unmatched_daily: list[str] = []
    daily_identity_dropped: dict[str, int] = {}
    if not daily.empty:
        unmatched_daily = sorted(
            set(universe_symbols) - set(daily["symbol"].dropna().unique())
        )
        daily, daily_identity_dropped = apply_ticker_identity_guard(
            daily, symbol_column="symbol", date_column="trade_date"
        )

    # --- publication dates -------------------------------------------------
    publication_map = attach_publication_dates(
        short_interest["settlement_date"].unique(), schedule
    )
    rule_counts = (
        publication_map["publication_date_rule"].value_counts().to_dict()
    )

    # --- point-in-time expansion ------------------------------------------
    expanded = short_interest_step_function(
        short_interest, publication_map, trading_dates, universe_symbols
    )
    adv = average_daily_volume(prices)
    expanded = expanded.merge(
        adv.loc[:, ["trading_date", "symbol", "adv_20d"]],
        on=["trading_date", "symbol"],
        how="left",
    )
    expanded["days_to_cover"] = np.where(
        (expanded["adv_20d"] > 0) & expanded["short_interest_shares"].notna(),
        expanded["short_interest_shares"] / expanded["adv_20d"],
        np.nan,
    )
    expanded["finra_reported_days_to_cover"] = expanded["finra_days_to_cover"]

    if not daily.empty:
        shares = short_volume_share(daily)
        expanded = expanded.merge(
            shares.loc[:, ["trading_date", "symbol", "short_volume_share_5d"]],
            on=["trading_date", "symbol"],
            how="left",
        )
    else:
        expanded["short_volume_share_5d"] = np.nan

    # --- restrict to the loser leg ----------------------------------------
    membership = build_leg_membership(prices, trading_dates)
    leg = membership.merge(expanded, on=["trading_date", "symbol"], how="left")

    aggregated = (
        leg.groupby("trading_date")
        .agg(
            leg_constituent_count=("symbol", "nunique"),
            days_to_cover=("days_to_cover", "mean"),
            short_vol_share=("short_volume_share_5d", "mean"),
            days_to_cover_matched=("days_to_cover", "count"),
            short_vol_share_matched=("short_volume_share_5d", "count"),
            finra_reported_days_to_cover=("finra_reported_days_to_cover", "mean"),
        )
        .reset_index()
    )
    aggregated["days_to_cover_match_rate"] = (
        aggregated["days_to_cover_matched"] / aggregated["leg_constituent_count"]
    )
    aggregated["short_vol_share_match_rate"] = (
        aggregated["short_vol_share_matched"] / aggregated["leg_constituent_count"]
    )

    panel = pd.DataFrame({"trading_date": trading_dates}).merge(
        aggregated, on="trading_date", how="left"
    )

    days_to_cover_z, dtc_stats = rolling_z_pit(panel["days_to_cover"], ROLLING_WINDOW)
    short_vol_share_z, svs_stats = rolling_z_pit(
        panel["short_vol_share"], ROLLING_WINDOW
    )
    panel["days_to_cover_z"] = days_to_cover_z.to_numpy()
    panel["short_vol_share_z"] = short_vol_share_z.to_numpy()

    dominant_rule = (
        max(rule_counts, key=rule_counts.get) if rule_counts else "none"
    )
    panel["publication_date_rule"] = dominant_rule
    panel["universe_survivorship_bias"] = True
    # This panel keeps the strict all-126 rule. Its inputs have no interior
    # gaps — the diagnostics report zero missing current values — so relaxing
    # it would change nothing here. Stated explicitly rather than left implicit,
    # because the narrative panel deliberately uses a different rule.
    panel["z_window"] = ROLLING_WINDOW
    panel["z_min_observations"] = ROLLING_WINDOW

    processed_dir.mkdir(parents=True, exist_ok=True)
    panel_path = processed_dir / "positioning_panel.parquet"
    panel.to_parquet(panel_path, index=False, engine="pyarrow")
    membership.to_parquet(
        processed_dir / "loser_leg_membership.parquet", index=False, engine="pyarrow"
    )

    reconciliation = reconcile_days_to_cover(expanded)

    report: dict[str, Any] = {
        "panel_path": str(panel_path),
        "rows": int(len(panel)),
        "first_trading_date": trading_dates.min().date().isoformat(),
        "last_trading_date": trading_dates.max().date().isoformat(),
        "universe_symbols": len(universe_symbols),
        "publication_date_rules": rule_counts,
        "dominant_publication_date_rule": dominant_rule,
        "unmatched_short_interest_symbols": unmatched_short_interest,
        "unmatched_daily_symbols": unmatched_daily,
        "short_interest_match_rate": round(
            1 - len(unmatched_short_interest) / max(1, len(universe_symbols)), 4
        ),
        "daily_match_rate": round(
            1 - len(unmatched_daily) / max(1, len(universe_symbols)), 4
        ),
        "days_to_cover_available": int(panel["days_to_cover"].notna().sum()),
        "short_vol_share_available": int(panel["short_vol_share"].notna().sum()),
        "days_to_cover_z_available": int(panel["days_to_cover_z"].notna().sum()),
        "short_vol_share_z_available": int(panel["short_vol_share_z"].notna().sum()),
        "rolling_z_diagnostics": {
            "days_to_cover_z": dtc_stats.as_dict(),
            "short_vol_share_z": svs_stats.as_dict(),
        },
        "leg_size_range": [
            int(membership["leg_size"].min()),
            int(membership["leg_size"].max()),
        ]
        if not membership.empty
        else None,
        "rankable_universe_range": [
            int(membership["rankable_universe"].min()),
            int(membership["rankable_universe"].max()),
        ]
        if not membership.empty
        else None,
        "days_to_cover_reconciliation": reconciliation,
        "ticker_identity_guard": {
            "overrides_applied": {
                symbol: {
                    "current_entity_from": value[0],
                    "prior_occupant": value[1],
                }
                for symbol, value in TICKER_IDENTITY_FROM.items()
            },
            "short_interest_rows_dropped": si_identity_dropped,
            "daily_rows_dropped": daily_identity_dropped,
            "detector_candidates": entity_candidates,
        },
        "trading_calendar": calendar.as_dict(),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "positioning_panel_diagnostics.json", report)
    write_json(
        output_dir / "positioning_unmatched_symbols.json",
        {
            "short_interest": unmatched_short_interest,
            "daily_short_volume": unmatched_daily,
            "note": (
                "Unmatched universe symbols are listed rather than dropped "
                "silently. A symbol may be unmatched because it listed after "
                "the sample start, changed ticker, or uses a share-class "
                "convention the normaliser does not cover."
            ),
        },
    )
    return report


def reconcile_days_to_cover(expanded: pd.DataFrame) -> dict[str, Any]:
    """Compare the computed days-to-cover with FINRA's own reported figure.

    FINRA's ``averageDailyVolumeQuantity`` explicitly excludes non-media trades,
    so an exact match is not expected. A large systematic gap would instead
    indicate that the volume series is on the wrong split basis, which is the
    failure this check exists to catch.
    """

    both = expanded.dropna(
        subset=["days_to_cover", "finra_reported_days_to_cover"]
    )
    both = both.loc[both["finra_reported_days_to_cover"] > 0]
    if both.empty:
        return {"comparable_rows": 0}
    ratio = both["days_to_cover"] / both["finra_reported_days_to_cover"]
    return {
        "comparable_rows": int(len(both)),
        "ratio_median": round(float(ratio.median()), 4),
        "ratio_p05": round(float(ratio.quantile(0.05)), 4),
        "ratio_p95": round(float(ratio.quantile(0.95)), 4),
        "share_within_2x": round(float(((ratio > 0.5) & (ratio < 2.0)).mean()), 4),
        "computed_median": round(float(both["days_to_cover"].median()), 4),
        "finra_reported_median": round(
            float(both["finra_reported_days_to_cover"].median()), 4
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    report = build_panel(processed_dir=args.processed_dir, output_dir=args.output_dir)
    print(json.dumps(report, indent=2, sort_keys=True, default=str)[:4000])


if __name__ == "__main__":
    main()
