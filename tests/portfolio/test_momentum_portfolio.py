"""Phase 2 tests for the frozen S&P 500 proxy and 12-1 portfolio."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import pandas as pd
import pytest

from src.data.sp500 import parse_spy_holdings
from src.portfolio.momentum import (
    build_momentum_holdings,
    build_momentum_signals,
    build_portfolio_returns,
)


def _write_minimal_spy_workbook(path: Path) -> None:
    shared = [
        "Holdings As of 24-Jul-2026",
        "Name",
        "Ticker",
        "Identifier",
        "SEDOL",
        "Weight",
        "Sector",
        "Shares Held",
        "Local Currency",
        "Apple Inc.",
        "AAPL",
        "037833100",
        "2046251",
        "US DOLLAR",
        "USD",
        "CONTRA HOLOGIC INCORPO",
        "2602335D",
    ]
    shared_xml = "".join(f"<si><t>{value}</t></si>" for value in shared)
    sheet_xml = """
    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <sheetData>
        <row r="1"><c r="A1" t="s"><v>0</v></c></row>
        <row r="5">
          <c r="A5" t="s"><v>1</v></c><c r="B5" t="s"><v>2</v></c>
          <c r="C5" t="s"><v>3</v></c><c r="D5" t="s"><v>4</v></c>
          <c r="E5" t="s"><v>5</v></c><c r="F5" t="s"><v>6</v></c>
          <c r="G5" t="s"><v>7</v></c><c r="H5" t="s"><v>8</v></c>
        </row>
        <row r="6">
          <c r="A6" t="s"><v>9</v></c><c r="B6" t="s"><v>10</v></c>
          <c r="C6" t="s"><v>11</v></c><c r="D6" t="s"><v>12</v></c>
          <c r="E6"><v>7.5</v></c>
        </row>
        <row r="7">
          <c r="A7" t="s"><v>13</v></c><c r="B7" t="s"><v>14</v></c>
          <c r="E7"><v>0.1</v></c>
        </row>
        <row r="8">
          <c r="A8" t="s"><v>15</v></c><c r="B8" t="s"><v>16</v></c>
          <c r="E8"><v>0.0001</v></c>
        </row>
      </sheetData>
    </worksheet>
    """
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            (
                '<sst xmlns="http://schemas.openxmlformats.org/'
                f'spreadsheetml/2006/main">{shared_xml}</sst>'
            ),
        )
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def _monthly_prices(
    symbols: list[str],
    *,
    periods: int = 16,
) -> pd.DataFrame:
    dates = pd.date_range("2022-01-31", periods=periods, freq="ME")
    records = []
    for index, symbol in enumerate(symbols):
        monthly_return = 0.002 * (index + 1)
        for step, date in enumerate(dates):
            records.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "close_total_return_adjusted": 100
                    * (1 + monthly_return) ** step,
                }
            )
    return pd.DataFrame.from_records(records)


def test_spy_parser_filters_cash_and_corporate_action_rows(tmp_path: Path) -> None:
    workbook = tmp_path / "spy.xlsx"
    _write_minimal_spy_workbook(workbook)
    holdings, as_of_date = parse_spy_holdings(workbook)

    assert as_of_date == pd.Timestamp("2026-07-24")
    assert holdings["symbol"].tolist() == ["AAPL"]
    assert holdings["source_weight_pct"].iloc[0] == 7.5


def test_signal_is_exactly_p_m_minus_1_over_p_m_minus_12() -> None:
    prices = _monthly_prices(["AAA"], periods=14)
    signals = build_momentum_signals(prices)
    row = signals.loc[signals["formation_month"] == pd.Period("2023-01")].iloc[0]

    source = prices.set_index("date")["close_total_return_adjusted"]
    expected = source.loc[pd.Timestamp("2022-12-31")] / source.loc[
        pd.Timestamp("2022-01-31")
    ] - 1
    assert row["signal_start_date"] == pd.Timestamp("2022-01-31")
    assert row["signal_end_date"] == pd.Timestamp("2022-12-31")
    assert row["momentum_return"] == expected
    assert row["effective_month"] == pd.Period("2023-02")


def test_future_price_changes_do_not_change_an_earlier_formation() -> None:
    prices = _monthly_prices([f"S{i:02d}" for i in range(24)], periods=16)
    cutoff = pd.Period("2023-01")
    baseline = build_momentum_holdings(prices, n_long=10, n_short=10)
    baseline = baseline.loc[baseline["formation_month"] == cutoff].reset_index(drop=True)

    perturbed = prices.copy()
    perturbed.loc[perturbed["date"] >= "2023-02-01", "close_total_return_adjusted"] *= (
        np.where(
            np.arange((perturbed["date"] >= "2023-02-01").sum()) % 2,
            10.0,
            0.1,
        )
    )
    after = build_momentum_holdings(perturbed, n_long=10, n_short=10)
    after = after.loc[after["formation_month"] == cutoff].reset_index(drop=True)
    pd.testing.assert_frame_equal(baseline, after, check_exact=True)


def test_rank_ties_use_symbol_and_weights_apply_next_month() -> None:
    symbols = [f"S{i:02d}" for i in range(20)]
    prices = _monthly_prices(symbols, periods=14)
    # Force all signals to tie.
    for symbol in symbols:
        mask = prices["symbol"].eq(symbol)
        prices.loc[mask, "close_total_return_adjusted"] = np.arange(mask.sum()) + 100

    first = build_momentum_holdings(prices, n_long=3, n_short=2)
    second = build_momentum_holdings(prices, n_long=3, n_short=2)
    pd.testing.assert_frame_equal(first, second, check_exact=True)
    month = first["formation_month"].min()
    selected = first.loc[first["formation_month"].eq(month)]

    assert selected.loc[selected["leg"].eq("long"), "symbol"].tolist() == [
        "S00",
        "S01",
        "S02",
    ]
    assert set(selected.loc[selected["leg"].eq("short"), "symbol"]) == {
        "S18",
        "S19",
    }
    assert selected.loc[selected["leg"].eq("long"), "weight"].eq(1 / 3).all()
    assert selected.loc[selected["leg"].eq("short"), "weight"].eq(-1 / 2).all()
    assert selected.loc[selected["leg"].eq("long"), "weight"].sum() == 1.0
    assert selected.loc[selected["leg"].eq("short"), "weight"].sum() == -1.0
    assert (
        selected["effective_month"] - selected["formation_month"]
    ).map(lambda offset: offset.n).eq(1).all()


def test_incomplete_latest_month_cannot_become_a_formation_month() -> None:
    symbols = [f"S{i:02d}" for i in range(20)]
    complete = _monthly_prices(symbols, periods=14)
    partial = pd.DataFrame(
        {
            "date": pd.Timestamp("2023-03-15"),
            "symbol": symbols,
            "close_total_return_adjusted": 200.0,
        }
    )
    holdings = build_momentum_holdings(
        pd.concat([complete, partial], ignore_index=True),
        n_long=3,
        n_short=2,
    )

    assert pd.Period("2023-03") not in set(holdings["formation_month"])


def test_daily_returns_reconcile_long_and_short_contributions() -> None:
    dates = pd.bdate_range("2024-01-30", "2024-02-29")
    records = []
    for symbol, daily_return in [("L", 0.01), ("S", -0.02)]:
        for step, date in enumerate(dates):
            records.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "close_total_return_adjusted": 100 * (1 + daily_return) ** step,
                }
            )
    prices = pd.DataFrame.from_records(records)
    holdings = pd.DataFrame(
        {
            "formation_date": [pd.Timestamp("2024-01-31")] * 2,
            "effective_month": [pd.Period("2024-02")] * 2,
            "symbol": ["L", "S"],
            "leg": ["long", "short"],
            "weight": [1.0, -1.0],
        }
    )
    returns = build_portfolio_returns(
        prices,
        holdings,
        exclude_incomplete_last_month=False,
    )
    feb = returns.loc[returns["date"] >= "2024-02-01"]

    assert np.allclose(feb["long_basket_return"], 0.01)
    assert np.allclose(feb["short_basket_underlying_return"], -0.02)
    assert np.allclose(feb["long_contribution"], 0.01)
    assert np.allclose(feb["short_contribution"], 0.02)
    assert np.allclose(feb["portfolio_return"], 0.03)
    assert feb["return_complete"].all()


def test_month_start_equal_weights_drift_without_daily_rebalancing() -> None:
    dates = pd.to_datetime(["2024-01-31", "2024-02-01", "2024-02-02"])
    prices = pd.DataFrame(
        {
            "date": [*dates, *dates, *dates],
            "symbol": ["L1"] * 3 + ["L2"] * 3 + ["S"] * 3,
            "close_total_return_adjusted": [
                100.0,
                110.0,
                121.0,
                100.0,
                90.0,
                81.0,
                100.0,
                100.0,
                100.0,
            ],
        }
    )
    holdings = pd.DataFrame(
        {
            "formation_date": [pd.Timestamp("2024-01-31")] * 3,
            "effective_month": [pd.Period("2024-02")] * 3,
            "symbol": ["L1", "L2", "S"],
            "leg": ["long", "long", "short"],
            "weight": [0.5, 0.5, -1.0],
        }
    )
    returns = build_portfolio_returns(
        prices,
        holdings,
        exclude_incomplete_last_month=False,
    ).set_index("date")

    # Day one is +10% and -10% at equal weights: zero.  The winners then carry
    # 55% of the leg, so the same constituent returns produce +1% on day two.
    assert returns.loc[pd.Timestamp("2024-02-01"), "long_basket_return"] == pytest.approx(0.0)
    assert returns.loc[pd.Timestamp("2024-02-02"), "long_basket_return"] == pytest.approx(0.01)


def test_missing_constituent_return_is_not_zero_filled_or_reweighted() -> None:
    dates = pd.bdate_range("2024-01-31", "2024-02-02")
    prices = pd.DataFrame(
        {
            "date": [*dates, dates[0], dates[2]],
            "symbol": ["L1"] * 3 + ["L2"] * 2,
            "close_total_return_adjusted": [100.0, 101.0, 102.0, 100.0, 102.0],
        }
    )
    holdings = pd.DataFrame(
        {
            "formation_date": [pd.Timestamp("2024-01-31")] * 3,
            "effective_month": [pd.Period("2024-02")] * 3,
            "symbol": ["L1", "L2", "S1"],
            "leg": ["long", "long", "short"],
            "weight": [0.5, 0.5, -1.0],
        }
    )
    # Add a complete short price series.
    short = pd.DataFrame(
        {
            "date": dates,
            "symbol": "S1",
            "close_total_return_adjusted": [100.0, 100.0, 100.0],
        }
    )
    prices = pd.concat([prices, short], ignore_index=True)
    returns = build_portfolio_returns(
        prices,
        holdings,
        exclude_incomplete_last_month=False,
    )
    missing_day = returns.loc[returns["date"].eq(pd.Timestamp("2024-02-01"))].iloc[0]

    assert pd.isna(missing_day["long_basket_return"])
    assert pd.isna(missing_day["long_contribution"])
    assert pd.isna(missing_day["portfolio_return"])
    assert not bool(missing_day["return_complete"])
