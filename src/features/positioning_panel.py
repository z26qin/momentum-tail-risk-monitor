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

``short_interest_ratio`` and ``short_interest_change``
    **Volume-free** crowding. Both of the metrics above carry volume in the
    denominator, so both mechanically fall during the volume spikes that
    accompany stress — the leg mean of ``days_to_cover_z`` was -2.23 in March
    2020, when crowding was not in fact unwinding. A consumer reading a high
    ``days_to_cover_z`` as "crowded" therefore reads the most dangerous moments
    as safe. These two never divide by volume, so they cannot invert for that
    reason. See ``short_interest_intensity``.

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
from src.data.sec_edgar import point_in_time_shares_outstanding
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

#: Prints of short interest forming a symbol's own baseline. FINRA publishes
#: semi-monthly, so 12 prints is roughly six months — long enough to be a
#: stable reference, short enough to track share issuance and buybacks.
SHORT_INTEREST_BASELINE_PRINTS = 12
#: Prints required inside that window before the baseline is usable. An
#: availability rule, not imputation: below this the ratio is NaN.
SHORT_INTEREST_MIN_PRINTS = 6


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

    required = [
        "publication_date",
        "symbol",
        "short_interest_shares",
        "settlement_date",
        "finra_average_daily_volume",
        "finra_days_to_cover",
        "publication_date_rule",
        "stock_split_flag",
        "revision_flag",
    ]
    # Carried when the volume-free metrics have been derived upstream. Optional
    # so this function stays usable on a bare FINRA frame.
    optional = [
        "short_interest_ratio",
        "short_interest_change",
        "short_interest_utilisation",
    ]
    columns = required + [name for name in optional if name in joined.columns]

    merged = pd.merge_asof(
        grid,
        joined.loc[:, columns],
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


def split_consistent_short_interest(
    short_interest: pd.DataFrame, prices: pd.DataFrame
) -> pd.DataFrame:
    """Put every print on one share basis so a split cannot fake a crowding jump.

    FINRA reports short interest in the shares that existed on the settlement
    date. Comparing a print against its own history therefore compares
    pre-split shares with post-split shares: BKNG's 25:1 split in 2026 lifted
    its raw ratio to 37x on a leg whose median was 1.17, and dragged the whole
    leg mean to 3.17. FINRA's ``stock_split_flag`` was **blank** on those
    prints, so the flag cannot be used to catch this; the price vendor's split
    factor can.

    Look-ahead. ``split_factor_after`` encodes splits that happen after a date,
    which is future information — but only its *ratio between two dates inside
    one baseline window* enters the metric, and that ratio reflects splits
    between those two dates, all of which are in the past by the time the
    numerator prints. Any split after ``t`` scales numerator and denominator
    alike and cancels. So the scaled series is not point-in-time, and must not
    be published as a level, while ratios taken from it are.
    """

    factors = prices.loc[:, ["date", "symbol", "split_factor_after"]].dropna(
        subset=["split_factor_after"]
    )
    frame = short_interest.copy()
    # The two sources carry different datetime resolutions (ms and us), which
    # merge_asof refuses to join.
    factors["date"] = factors["date"].astype("datetime64[ns]")
    frame["settlement_date"] = frame["settlement_date"].astype("datetime64[ns]")
    factors = factors.sort_values(["date", "symbol"])
    frame = frame.sort_values(["settlement_date", "symbol"])
    merged = pd.merge_asof(
        frame,
        factors,
        left_on="settlement_date",
        right_on="date",
        by="symbol",
        direction="backward",
        allow_exact_matches=True,
    )
    shares = pd.to_numeric(merged["short_interest_shares"], errors="coerce")
    merged["short_interest_shares_adjusted"] = shares.where(shares > 0) * merged[
        "split_factor_after"
    ].where(merged["split_factor_after"] > 0)
    return merged.drop(columns=["date"])


def short_interest_utilisation(
    short_interest: pd.DataFrame, shares: pd.DataFrame, prices: pd.DataFrame
) -> pd.DataFrame:
    """Short interest as a fraction of shares outstanding — the textbook measure.

    The one crowding number that is both volume-free and comparable across
    companies: 8% of the float being short means the same thing for a mega-cap
    as for a mid-cap, which ``short_interest_ratio`` deliberately cannot say.

    Point-in-time on both sides. Short interest enters on its FINRA publication
    date; shares outstanding enters on its SEC **filing** date, never the
    balance-sheet date it describes — the gap between the two runs to a month.

    Both legs are put on the same split basis before dividing, because the two
    sources are dated up to a quarter apart and a split in between would
    otherwise show up as a step change in float.
    """

    if shares.empty:
        return short_interest.assign(short_interest_utilisation=np.nan)

    factors = prices.loc[:, ["date", "symbol", "split_factor_after"]].dropna(
        subset=["split_factor_after"]
    )
    factors["date"] = factors["date"].astype("datetime64[ns]")
    factors = factors.sort_values(["date", "symbol"])

    outstanding = shares.copy()
    outstanding["filed_date"] = outstanding["filed_date"].astype("datetime64[ns]")
    outstanding["end_date"] = outstanding["end_date"].astype("datetime64[ns]")
    outstanding = outstanding.sort_values(["end_date", "symbol"])
    outstanding = pd.merge_asof(
        outstanding,
        factors,
        left_on="end_date",
        right_on="date",
        by="symbol",
        direction="backward",
        allow_exact_matches=True,
    )
    outstanding["shares_outstanding_adjusted"] = outstanding[
        "shares_outstanding"
    ] * outstanding["split_factor_after"].where(
        outstanding["split_factor_after"] > 0
    )

    frame = short_interest.sort_values(["publication_date", "symbol"]).copy()
    frame["publication_date"] = frame["publication_date"].astype("datetime64[ns]")
    merged = pd.merge_asof(
        frame,
        outstanding.loc[
            :, ["filed_date", "symbol", "shares_outstanding_adjusted", "shares_source"]
        ].sort_values(["filed_date", "symbol"]),
        left_on="publication_date",
        right_on="filed_date",
        by="symbol",
        direction="backward",
        allow_exact_matches=True,
    )
    merged["short_interest_utilisation"] = (
        merged["short_interest_shares_adjusted"]
        / merged["shares_outstanding_adjusted"].where(
            merged["shares_outstanding_adjusted"] > 0
        )
    )
    return merged


def short_interest_intensity(
    short_interest: pd.DataFrame,
    baseline_prints: int = SHORT_INTEREST_BASELINE_PRINTS,
    min_prints: int = SHORT_INTEREST_MIN_PRINTS,
) -> pd.DataFrame:
    """Volume-free crowding: short interest against its own recent baseline.

    ``days_to_cover`` puts volume in the denominator, so it mechanically
    collapses in exactly the volume spikes this panel most needs to describe —
    measured leg-mean ``days_to_cover_z`` was -2.23 in March 2020. Neither
    metric added here touches volume at any point.

    The textbook denominator is shares outstanding. FINRA does not report it
    and the price vendor does not carry it, so each symbol is scaled by its own
    trailing median print instead. That keeps the result unit-free, which is
    what lets it average across a leg of very differently sized companies. What
    it gives up is the cross-sectional level: this says a name is heavily
    shorted *relative to its own history*, not that 20% of its float is short.

    Two series, measuring different things:

    ``short_interest_ratio``
        Level. The current print over the lagged median of the preceding
        ``baseline_prints``. The median is lagged one print, so only short
        interest already published when the numerator printed can enter the
        denominator.

    ``short_interest_change``
        Accumulation. Print-over-print growth on the same adjusted basis.

    Both are computed from ``short_interest_shares_adjusted``, so both are
    immune to splits; see ``split_consistent_short_interest`` for why taking a
    ratio of that series stays point-in-time.
    """

    if "short_interest_shares_adjusted" not in short_interest.columns:
        raise KeyError(
            "short_interest_intensity requires split_consistent_short_interest "
            "to have run first: raw prints change basis across a split."
        )

    frame = short_interest.sort_values(["symbol", "settlement_date"]).copy()
    shares = frame["short_interest_shares_adjusted"]

    baseline = (
        shares.groupby(frame["symbol"], sort=False)
        .shift(1)
        .groupby(frame["symbol"], sort=False)
        .rolling(baseline_prints, min_periods=min_prints)
        .median()
        .reset_index(level=0, drop=True)
    )
    frame["short_interest_baseline"] = baseline.where(baseline > 0)
    frame["short_interest_ratio"] = shares / frame["short_interest_baseline"]

    previous = shares.groupby(frame["symbol"], sort=False).shift(1)
    frame["short_interest_change"] = shares / previous.where(previous > 0) - 1.0

    return frame


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

    # Volume-free crowding is derived here, after the symbol map and the
    # identity guard, so a reused ticker cannot contribute another company's
    # prints to a symbol's own baseline.
    short_interest = short_interest_intensity(
        split_consistent_short_interest(short_interest, prices)
    )

    # --- publication dates -------------------------------------------------
    publication_map = attach_publication_dates(
        short_interest["settlement_date"].unique(), schedule
    )
    rule_counts = (
        publication_map["publication_date_rule"].value_counts().to_dict()
    )

    # --- short interest as a fraction of float -----------------------------
    # Needs publication dates on the FINRA side, so it runs after the map is
    # built rather than beside the other volume-free metrics.
    shares_path = processed_dir / "sec_shares_outstanding.parquet"
    shares = (
        point_in_time_shares_outstanding(pd.read_parquet(shares_path))
        if shares_path.is_file()
        else pd.DataFrame()
    )
    dated = short_interest.merge(
        publication_map.loc[:, ["settlement_date", "publication_date"]],
        on="settlement_date",
        how="left",
    )
    dated = short_interest_utilisation(dated, shares, prices)
    short_interest = short_interest.merge(
        dated.loc[:, ["symbol", "settlement_date", "short_interest_utilisation"]],
        on=["symbol", "settlement_date"],
        how="left",
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
            # Median, not mean. These are ratios — bounded below by zero and
            # unbounded above — so one name can carry the leg mean on its own,
            # which is how the BKNG split surfaced. The mean is kept beside it
            # as a diagnostic; a wide gap between the two means one constituent
            # is doing the talking.
            short_interest_ratio=("short_interest_ratio", "median"),
            short_interest_ratio_mean=("short_interest_ratio", "mean"),
            short_interest_change=("short_interest_change", "median"),
            short_interest_utilisation=("short_interest_utilisation", "median"),
            short_interest_utilisation_matched=("short_interest_utilisation", "count"),
            days_to_cover_matched=("days_to_cover", "count"),
            short_vol_share_matched=("short_volume_share_5d", "count"),
            short_interest_ratio_matched=("short_interest_ratio", "count"),
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
    aggregated["short_interest_ratio_match_rate"] = (
        aggregated["short_interest_ratio_matched"]
        / aggregated["leg_constituent_count"]
    )

    panel = pd.DataFrame({"trading_date": trading_dates}).merge(
        aggregated, on="trading_date", how="left"
    )

    days_to_cover_z, dtc_stats = rolling_z_pit(panel["days_to_cover"], ROLLING_WINDOW)
    short_vol_share_z, svs_stats = rolling_z_pit(
        panel["short_vol_share"], ROLLING_WINDOW
    )
    short_interest_ratio_z, sir_stats = rolling_z_pit(
        panel["short_interest_ratio"], ROLLING_WINDOW
    )
    utilisation_z, util_stats = rolling_z_pit(
        panel["short_interest_utilisation"], ROLLING_WINDOW
    )
    panel["days_to_cover_z"] = days_to_cover_z.to_numpy()
    panel["short_vol_share_z"] = short_vol_share_z.to_numpy()
    panel["short_interest_ratio_z"] = short_interest_ratio_z.to_numpy()
    panel["short_interest_utilisation_z"] = utilisation_z.to_numpy()

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
        "short_interest_ratio_available": int(
            panel["short_interest_ratio"].notna().sum()
        ),
        "short_interest_ratio_z_available": int(
            panel["short_interest_ratio_z"].notna().sum()
        ),
        "short_interest_utilisation_available": int(
            panel["short_interest_utilisation"].notna().sum()
        ),
        "short_interest_utilisation_z_available": int(
            panel["short_interest_utilisation_z"].notna().sum()
        ),
        "rolling_z_diagnostics": {
            "days_to_cover_z": dtc_stats.as_dict(),
            "short_vol_share_z": svs_stats.as_dict(),
            "short_interest_ratio_z": sir_stats.as_dict(),
            "short_interest_utilisation_z": util_stats.as_dict(),
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
