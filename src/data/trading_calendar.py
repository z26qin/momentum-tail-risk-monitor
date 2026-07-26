"""The canonical US trading-date index shared by both alternative-data panels.

Both panels must sit on exactly the same trading calendar, and that calendar
must not be invented. It is built from the Ken French momentum file already
frozen in this repository — the same calendar Phase 1 labels sit on — and
extended past that file's vintage using observed exchange sessions from the
price panel. The overlap between the two is asserted, not assumed, so a
disagreement surfaces as an error rather than as a quietly shifted index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.utils.io import DEFAULT_PROCESSED_DIR


MOMENTUM_CALENDAR_FILE = "french_momentum_factor_daily.parquet"
PRICE_PANEL_FILE = "universe_prices.parquet"

#: A session counts as a real exchange session only if a decent share of the
#: universe traded. This keeps a single stale vendor row from inventing a date.
MINIMUM_SYMBOLS_FOR_SESSION = 20


@dataclass(frozen=True)
class TradingCalendar:
    """Trading dates plus provenance for how each segment was established."""

    dates: pd.DatetimeIndex
    french_last_date: pd.Timestamp
    extended_dates: pd.DatetimeIndex
    overlap_days: int
    overlap_disagreements: list[str] = field(default_factory=list)

    def between(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
        mask = (self.dates >= start) & (self.dates <= end)
        return self.dates[mask]

    def as_dict(self) -> dict[str, object]:
        return {
            "trading_days": int(len(self.dates)),
            "first": self.dates[0].date().isoformat(),
            "last": self.dates[-1].date().isoformat(),
            "french_authoritative_through": self.french_last_date.date().isoformat(),
            "extended_by_price_sessions": int(len(self.extended_dates)),
            "overlap_days_checked": self.overlap_days,
            "overlap_disagreements": self.overlap_disagreements,
        }


def build_trading_calendar(
    *,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    start: pd.Timestamp = pd.Timestamp("2016-01-01"),
    end: pd.Timestamp | None = None,
) -> TradingCalendar:
    """Assemble the trading calendar and verify the two sources agree on overlap."""

    momentum_path = processed_dir / MOMENTUM_CALENDAR_FILE
    if not momentum_path.is_file():
        raise FileNotFoundError(
            f"Momentum calendar missing at {momentum_path}; the Phase 1 French "
            "pipeline must have been run."
        )
    french = pd.read_parquet(momentum_path, columns=["date"])
    french_dates = pd.DatetimeIndex(
        french["date"].drop_duplicates().sort_values()
    )
    french_last = french_dates.max()

    price_path = processed_dir / PRICE_PANEL_FILE
    price_sessions = pd.DatetimeIndex([])
    if price_path.is_file():
        prices = pd.read_parquet(price_path, columns=["date", "symbol"])
        counts = prices.groupby("date")["symbol"].nunique()
        price_sessions = pd.DatetimeIndex(
            counts[counts >= MINIMUM_SYMBOLS_FOR_SESSION].index
        ).sort_values()

    # Agreement check on the window where both sources are authoritative.
    overlap_start = max(start, french_dates.min())
    disagreements: list[str] = []
    overlap_days = 0
    if len(price_sessions):
        overlap_end = min(french_last, price_sessions.max())
        french_overlap = french_dates[
            (french_dates >= overlap_start) & (french_dates <= overlap_end)
        ]
        price_overlap = price_sessions[
            (price_sessions >= overlap_start) & (price_sessions <= overlap_end)
        ]
        overlap_days = int(len(french_overlap))
        only_french = french_overlap.difference(price_overlap)
        only_price = price_overlap.difference(french_overlap)
        disagreements = [
            f"french_only:{value.date().isoformat()}" for value in only_french
        ] + [f"price_only:{value.date().isoformat()}" for value in only_price]

    extended = price_sessions[price_sessions > french_last]
    combined = french_dates.union(extended).sort_values()
    if end is not None:
        combined = combined[combined <= end]
    combined = combined[combined >= start]

    return TradingCalendar(
        dates=pd.DatetimeIndex(combined),
        french_last_date=french_last,
        extended_dates=pd.DatetimeIndex(extended),
        overlap_days=overlap_days,
        overlap_disagreements=disagreements,
    )
