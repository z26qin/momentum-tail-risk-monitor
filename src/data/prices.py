"""Daily prices and volumes for the proxy universe.

Two different adjustment conventions are needed and they must not be confused:

* **Momentum ranking** needs a total-return series, so it uses the vendor's
  split- and dividend-adjusted close.
* **Days-to-cover** divides a FINRA short-interest *share count* by an average
  daily volume. FINRA reports shares as they traded on the settlement date, so
  the volume must also be as-traded. The vendor returns **split-adjusted**
  volume, which was confirmed by observation: Apple's 2020-08-28 volume is
  reported as 187,630,000, exactly four times the ~46.9M shares that actually
  changed hands the day before the 4:1 split. Dividing a pre-split short
  interest by a post-split-adjusted volume would understate days-to-cover by
  the split factor, so this module un-adjusts volume back to as-traded shares
  using the vendor's own split events.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from src.data.symbols import to_price_vendor
from src.utils.http import cached_fetch
from src.utils.io import DEFAULT_PROCESSED_DIR, DEFAULT_RAW_DIR, write_json


PRIMARY_SOURCE = "Yahoo Finance chart API (query1.finance.yahoo.com/v8/finance/chart)"
FALLBACK_SOURCE = "Stooq daily CSV (stooq.com/q/d/l)"

#: Start early enough that a 12-2 momentum rank exists on the first settlement
#: date of the short-interest history (2017-12-29).
PRICE_START = pd.Timestamp("2016-01-01")


def _chart_url(vendor_symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> str:
    period1 = int(start.timestamp())
    period2 = int(end.timestamp())
    return (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{vendor_symbol}"
        f"?period1={period1}&period2={period2}&interval=1d"
        f"&events=div%2Csplit&includeAdjustedClose=true"
    )


def forward_split_factor(dates: pd.Series, splits: dict[str, float]) -> pd.Series:
    """Cumulative split ratio applied *after* each date.

    A price or volume dated ``t`` in the vendor's split-adjusted series is
    recovered to as-traded units by multiplying (price) or dividing (volume) by
    the product of every split whose effective date is strictly after ``t``.
    """

    factor = pd.Series(1.0, index=dates.index)
    for effective_date, ratio in splits.items():
        effective = pd.Timestamp(effective_date)
        factor = factor * np.where(dates < effective, ratio, 1.0)
    return factor


def parse_chart(payload: dict[str, Any], symbol: str) -> pd.DataFrame:
    """Turn one chart response into a tidy daily frame."""

    chart = payload.get("chart") or {}
    results = chart.get("result")
    if not results:
        return pd.DataFrame()
    result = results[0]
    timestamps = result.get("timestamp")
    if not timestamps:
        return pd.DataFrame()

    quote = result["indicators"]["quote"][0]
    adjusted = result["indicators"].get("adjclose", [{}])[0].get("adjclose")

    exchange_timezone = result["meta"].get("exchangeTimezoneName", "America/New_York")
    session_dates = (
        pd.to_datetime(pd.Series(timestamps), unit="s", utc=True)
        .dt.tz_convert(exchange_timezone)
        .dt.normalize()
        .dt.tz_localize(None)
    )

    frame = pd.DataFrame(
        {
            "date": session_dates,
            "symbol": symbol,
            "close_split_adjusted": pd.Series(quote.get("close"), dtype="float64"),
            "volume_split_adjusted": pd.Series(quote.get("volume"), dtype="float64"),
            "close_total_return_adjusted": pd.Series(
                adjusted if adjusted is not None else quote.get("close"),
                dtype="float64",
            ),
        }
    )

    splits = {}
    for event in (result.get("events") or {}).get("splits", {}).values():
        effective = (
            pd.Timestamp(event["date"], unit="s", tz="UTC")
            .tz_convert(exchange_timezone)
            .normalize()
            .tz_localize(None)
        )
        ratio = float(event["numerator"]) / float(event["denominator"])
        splits[effective.isoformat()] = ratio

    factor = forward_split_factor(frame["date"], splits)
    frame["split_factor_after"] = factor
    frame["volume_as_traded"] = frame["volume_split_adjusted"] / factor
    frame["close_as_traded"] = frame["close_split_adjusted"] * factor
    frame["dollar_volume"] = (
        frame["close_split_adjusted"] * frame["volume_split_adjusted"]
    )

    frame = frame.dropna(subset=["close_total_return_adjusted"])
    frame = frame.drop_duplicates(subset="date", keep="last")
    return frame.sort_values("date").reset_index(drop=True)


def fetch_symbol(
    symbol: str,
    *,
    raw_dir: Path,
    start: pd.Timestamp = PRICE_START,
    end: pd.Timestamp | None = None,
    force: bool = False,
    min_interval_seconds: float = 1.5,
) -> dict[str, Any]:
    """Cache one symbol's daily history."""

    end = end or pd.Timestamp(pd.Timestamp.now("UTC").date()) + pd.Timedelta(days=1)
    vendor_symbol = to_price_vendor(symbol)
    result = cached_fetch(
        cache_path=raw_dir / f"{symbol.replace('/', '_')}.json",
        url=_chart_url(vendor_symbol, start, end),
        source_key=f"price_{symbol}",
        min_interval_seconds=min_interval_seconds,
        backoff_seconds=8.0,
        max_retries=4,
        absent_statuses=(404,),
        force=force,
        tolerate_failure=True,
        extra_metadata={
            "price_source": PRIMARY_SOURCE,
            "canonical_symbol": symbol,
            "vendor_symbol": vendor_symbol,
            "adjustment_convention": (
                "close_split_adjusted and volume_split_adjusted are the vendor's "
                "split-adjusted series; close_total_return_adjusted is split and "
                "dividend adjusted; *_as_traded are recovered to settlement-date "
                "share units using the vendor's split events"
            ),
        },
    )
    if result.transient_failure or result.absent:
        return {"symbol": symbol, "frame": pd.DataFrame(), "status": "unavailable"}
    frame = parse_chart(result.read_json(), symbol)
    return {
        "symbol": symbol,
        "frame": frame,
        "status": "ok" if not frame.empty else "empty",
    }


def acquire_prices(
    symbols: Sequence[str],
    *,
    raw_dir: Path = DEFAULT_RAW_DIR / "prices",
    start: pd.Timestamp = PRICE_START,
    end: pd.Timestamp | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Pull every universe symbol, then persist one long price frame."""

    raw_dir.mkdir(parents=True, exist_ok=True)
    frames: list[pd.DataFrame] = []
    unavailable: list[str] = []
    empty: list[str] = []

    for symbol in symbols:
        outcome = fetch_symbol(
            symbol, raw_dir=raw_dir, start=start, end=end, force=force
        )
        if outcome["status"] == "unavailable":
            unavailable.append(symbol)
        elif outcome["status"] == "empty":
            empty.append(symbol)
        else:
            frames.append(outcome["frame"])

    combined = (
        pd.concat(frames, ignore_index=True).sort_values(["symbol", "date"])
        if frames
        else pd.DataFrame()
    )
    return {
        "prices": combined.reset_index(drop=True),
        "requested": len(symbols),
        "retrieved": len(frames),
        "unavailable": unavailable,
        "empty": empty,
        "retrieval_rate": round(len(frames) / max(1, len(symbols)), 4),
        "source": PRIMARY_SOURCE,
    }


def build_prices(
    symbols: Iterable[str],
    *,
    raw_dir: Path = DEFAULT_RAW_DIR / "prices",
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    force: bool = False,
) -> dict[str, Any]:
    """Acquire and persist the universe price panel."""

    symbols = list(symbols)
    report = acquire_prices(symbols, raw_dir=raw_dir, force=force)
    prices = report.pop("prices")
    if not prices.empty:
        processed_dir.mkdir(parents=True, exist_ok=True)
        prices.to_parquet(
            processed_dir / "universe_prices.parquet", index=False, engine="pyarrow"
        )
        report["rows"] = int(len(prices))
        report["first_date"] = prices["date"].min().date().isoformat()
        report["last_date"] = prices["date"].max().date().isoformat()
    write_json(raw_dir / "price_acquisition_report.json", report)
    return report


def main() -> None:
    from src.data.universe import load_universe

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR / "prices")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    report = build_prices(load_universe(), raw_dir=args.raw_dir, force=args.force)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
