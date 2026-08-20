from __future__ import annotations

import numpy as np
import pandas as pd
import pandas.testing as pdt

from src.features.momentum_breadth import (
    BREADTH_HISTORY_COLUMNS,
    build_momentum_breadth_history,
    summarize_momentum_snapshot,
)
from src.portfolio.momentum import build_momentum_holdings


def _daily_prices(end: str = "2024-06-28") -> pd.DataFrame:
    dates = pd.bdate_range("2022-01-03", end)
    specifications = {
        "AAA": (100.0, 0.0012),
        "BBB": (90.0, 0.0005),
        "CCC": (110.0, -0.0003),
        "DDD": (80.0, -0.0008),
    }
    records = []
    for symbol, (start, daily_return) in specifications.items():
        for index, date in enumerate(dates):
            records.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "close_total_return_adjusted": start
                    * (1.0 + daily_return) ** index,
                }
            )
    return pd.DataFrame(records)


def test_snapshot_breadth_and_leadership_are_distinct() -> None:
    snapshot = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC", "DDD"],
            "momentum_return": [0.4, 0.2, -0.1, -0.2],
        }
    )
    result = summarize_momentum_snapshot(snapshot)
    assert result["eligible_count"] == 4
    assert result["positive_momentum_count"] == 2
    assert result["universe_positive_12_1_share"] == 0.5
    assert np.isclose(
        result["positive_momentum_leadership_hhi"],
        (2 / 3) ** 2 + (1 / 3) ** 2,
    )
    assert result["top10_positive_momentum_share"] == 1.0
    assert result["momentum_score_dispersion"] > 0.0


def test_no_positive_momentum_keeps_leadership_unavailable() -> None:
    result = summarize_momentum_snapshot(
        pd.DataFrame(
            {
                "symbol": ["AAA", "BBB"],
                "momentum_return": [-0.1, -0.2],
            }
        )
    )
    assert result["universe_positive_12_1_share"] == 0.0
    assert result["positive_momentum_leadership_hhi"] is None
    assert result["top10_positive_momentum_share"] is None


def test_breadth_history_reuses_phase2_signal_and_long_holdings() -> None:
    prices = _daily_prices()
    universe = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC", "DDD"],
            "membership_status": ["current_snapshot_proxy"] * 4,
            "survivorship_bias": [True] * 4,
        }
    )
    holdings = build_momentum_holdings(
        prices,
        universe,
        n_long=1,
        n_short=1,
    )
    history = build_momentum_breadth_history(
        prices,
        universe=universe,
        holdings=holdings,
    )
    assert tuple(history.columns) == BREADTH_HISTORY_COLUMNS
    assert len(history) > 6
    assert history["eligible_count"].eq(4).all()
    assert history["universe_positive_12_1_share"].between(0.0, 1.0).all()
    assert history["long_21d_available_count"].dropna().eq(1).all()
    assert history["long_21d_participation_share"].dropna().between(0.0, 1.0).all()
    assert history["membership_status"].eq("current_snapshot_proxy").all()
    assert history["survivorship_bias"].all()


def test_future_prices_do_not_change_earlier_breadth() -> None:
    prices = _daily_prices()
    base = build_momentum_breadth_history(prices)
    cutoff = base["formation_date"].max()

    future_dates = pd.bdate_range("2024-07-01", "2024-08-30")
    last = (
        prices.sort_values("date")
        .groupby("symbol", sort=True)
        .tail(1)
        .set_index("symbol")["close_total_return_adjusted"]
    )
    future_records = []
    for symbol in sorted(last.index):
        multiplier = 1.25 if symbol in {"CCC", "DDD"} else 0.75
        for index, date in enumerate(future_dates, start=1):
            future_records.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "close_total_return_adjusted": float(last[symbol])
                    * multiplier**index,
                }
            )
    changed = build_momentum_breadth_history(
        pd.concat([prices, pd.DataFrame(future_records)], ignore_index=True)
    )
    pdt.assert_frame_equal(
        base.reset_index(drop=True),
        changed.loc[changed["formation_date"].le(cutoff)]
        .reset_index(drop=True),
    )
