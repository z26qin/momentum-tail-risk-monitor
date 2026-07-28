"""Dated S&P 500 constituent snapshot used by the portfolio prototype.

State Street publishes the SPY holdings workbook daily.  It is a transparent
public source for a *current* S&P 500 proxy, but it is not constituent history.
Applying one downloaded snapshot to earlier dates therefore has survivorship
bias.  The status and warning are stored on every row and in the generated
universe document; this module must never present the snapshot as point-in-time
historical membership.

The workbook is parsed with the Python standard library so that acquiring the
universe does not add an Excel dependency to the research environment.
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pandas as pd

from src.data.prices import PRICE_START, fetch_symbol
from src.data.symbols import to_canonical
from src.utils.io import (
    DEFAULT_PROCESSED_DIR,
    DEFAULT_RAW_DIR,
    REPO_ROOT,
    cache_public_source,
    read_json,
    update_raw_metadata,
    write_json,
    write_parquet,
)


SPY_HOLDINGS_URL = (
    "https://www.ssga.com/library-content/products/fund-data/etfs/us/"
    "holdings-daily-us-en-spy.xlsx"
)
SPY_PRODUCT_URL = (
    "https://www.ssga.com/us/en/intermediary/etfs/"
    "state-street-spdr-sp-500-etf-trust-spy"
)
SPY_SOURCE = "State Street SPDR S&P 500 ETF Trust (SPY) daily holdings"
MEMBERSHIP_STATUS = "current_snapshot_proxy"

_CELL_REFERENCE = re.compile(r"([A-Z]+)")
_STANDARD_TICKER = re.compile(r"^[A-Z0-9]+(?:[./-][A-Z])?$")


def _column_number(reference: str) -> int:
    match = _CELL_REFERENCE.match(reference)
    if not match:
        raise ValueError(f"Invalid XLSX cell reference: {reference!r}")
    value = 0
    for character in match.group(1):
        value = value * 26 + ord(character) - ord("A") + 1
    return value - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    path = "xl/sharedStrings.xml"
    if path not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read(path))
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    values: list[str] = []
    for item in root.findall("x:si", namespace):
        values.append("".join(node.text or "" for node in item.findall(".//x:t", namespace)))
    return values


def _worksheet_rows(path: Path) -> list[list[Any]]:
    """Read the first worksheet into a sparse-safe list of row values."""

    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        shared = _shared_strings(archive)
        worksheet_names = sorted(
            name
            for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        if not worksheet_names:
            raise ValueError(f"No worksheet found in {path}")
        root = ElementTree.fromstring(archive.read(worksheet_names[0]))

    rows: list[list[Any]] = []
    for row in root.findall(".//x:sheetData/x:row", namespace):
        sparse: dict[int, Any] = {}
        for cell in row.findall("x:c", namespace):
            reference = cell.attrib.get("r", "")
            column = _column_number(reference)
            cell_type = cell.attrib.get("t")
            value_node = cell.find("x:v", namespace)
            inline_node = cell.find("x:is/x:t", namespace)
            raw = (
                value_node.text
                if value_node is not None
                else inline_node.text
                if inline_node is not None
                else None
            )
            if raw is None:
                value: Any = None
            elif cell_type == "s":
                value = shared[int(raw)]
            elif cell_type in {"inlineStr", "str"}:
                value = raw
            else:
                try:
                    value = float(raw)
                except ValueError:
                    value = raw
            sparse[column] = value
        if sparse:
            dense = [None] * (max(sparse) + 1)
            for column, value in sparse.items():
                dense[column] = value
            rows.append(dense)
    return rows


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def parse_spy_holdings(path: Path) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Parse and filter the official workbook to ordinary equity holdings."""

    rows = _worksheet_rows(path)
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if {_text(value) for value in row}.issuperset(
                {"Name", "Ticker", "Identifier", "Weight"}
            )
        ),
        None,
    )
    if header_index is None:
        raise ValueError("Could not locate the SPY holdings header row")

    as_of_text = next(
        (
            _text(value)
            for row in rows[:header_index]
            for value in row
            if _text(value).startswith(("Holdings As of ", "As of "))
        ),
        "",
    )
    if not as_of_text:
        raise ValueError("Could not locate the holdings as-of date")
    as_of_date = pd.to_datetime(
        as_of_text.removeprefix("Holdings As of ").removeprefix("As of "),
        format="%d-%b-%Y",
    )

    header = [_text(value) for value in rows[header_index]]
    records: list[dict[str, Any]] = []
    for row in rows[header_index + 1 :]:
        padded = row + [None] * max(0, len(header) - len(row))
        record = dict(zip(header, padded, strict=False))
        source_symbol = _text(record.get("Ticker")).upper()
        name = _text(record.get("Name"))
        if not source_symbol or not _STANDARD_TICKER.fullmatch(source_symbol):
            continue
        if source_symbol in {"USD", "CASH"} or name.upper() == "US DOLLAR":
            continue
        if name.upper().startswith("CONTRA "):
            continue
        try:
            weight = float(record.get("Weight"))
        except (TypeError, ValueError):
            continue
        records.append(
            {
                "as_of_date": as_of_date,
                "symbol": to_canonical(source_symbol),
                "source_symbol": source_symbol,
                "name": name,
                "identifier": _text(record.get("Identifier")),
                "sedol": _text(record.get("SEDOL")),
                "source_weight_pct": weight,
            }
        )

    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        raise ValueError("The SPY workbook contained no equity holdings")
    if frame["symbol"].duplicated().any():
        duplicates = sorted(frame.loc[frame["symbol"].duplicated(), "symbol"].unique())
        raise ValueError(f"Duplicate canonical symbols in SPY holdings: {duplicates}")
    return frame.sort_values("symbol").reset_index(drop=True), as_of_date


def classification_snapshot_from_nasdaq(payload: dict[str, Any]) -> pd.DataFrame:
    """Extract current sector and industry without presenting either as PIT."""

    records: list[dict[str, str]] = []
    for row in (payload.get("data") or {}).get("rows") or []:
        symbol = to_canonical(_text(row.get("symbol")))
        sector = _text(row.get("sector"))
        industry = _text(row.get("industry"))
        if symbol:
            records.append(
                {
                    "symbol": symbol,
                    "sector": sector or pd.NA,
                    "industry": industry or pd.NA,
                }
            )
    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "sector", "industry"])
    return frame.drop_duplicates("symbol", keep="first")


def sector_snapshot_from_nasdaq(payload: dict[str, Any]) -> pd.DataFrame:
    """Backward-compatible current sector-only view."""

    return classification_snapshot_from_nasdaq(payload).loc[:, ["symbol", "sector"]]


def attach_current_sectors(
    holdings: pd.DataFrame,
    *,
    nasdaq_screener_path: Path | None,
) -> pd.DataFrame:
    """Attach optional current sectors without disguising them as historical."""

    frame = holdings.copy()
    if nasdaq_screener_path is None or not nasdaq_screener_path.is_file():
        frame["sector"] = pd.NA
        frame["sector_source"] = "unavailable"
        return frame

    sectors = sector_snapshot_from_nasdaq(read_json(nasdaq_screener_path))
    frame = frame.merge(sectors, on="symbol", how="left", validate="one_to_one")
    frame["sector_source"] = frame["sector"].notna().map(
        {
            True: "Nasdaq current screener snapshot; not point-in-time",
            False: "unavailable",
        }
    )
    return frame


def write_sp500_document(frame: pd.DataFrame, path: Path, retrieval: str) -> None:
    """Write the universe contract and a concise constituent audit."""

    as_of = pd.Timestamp(frame["as_of_date"].iloc[0]).date().isoformat()
    missing_sectors = sorted(frame.loc[frame["sector"].isna(), "symbol"].tolist())
    lines = [
        "# S&P 500 proxy universe",
        "",
        f"- **Membership source:** {SPY_SOURCE}",
        f"- **Source page:** {SPY_PRODUCT_URL}",
        f"- **Holdings as of:** {as_of}",
        f"- **Retrieved (UTC):** {retrieval}",
        f"- **Equity holdings retained:** {len(frame)}",
        f"- **Source weights retained:** {frame['source_weight_pct'].sum():.6f}%",
        f"- **Membership status:** `{MEMBERSHIP_STATUS}`",
        "- **Portfolio weighting:** source ETF weights are retained for audit only; "
        "the momentum portfolio is equal weighted within each leg.",
        "",
        "## Historical-use warning",
        "",
        "This is a dated current SPY holdings snapshot, not historical constituent",
        "membership. Applying it before the snapshot date introduces survivorship",
        "and index-membership look-ahead. Historical results are therefore a",
        "**current-constituent proxy**, not a point-in-time S&P 500 backtest.",
        "",
        "Sector labels, where present, come from a separate current Nasdaq screener",
        "snapshot and are also not point-in-time. They are not used by the Phase 2",
        "ranking or returns.",
        f"Missing sector labels: {', '.join(missing_sectors) if missing_sectors else 'none'}.",
        "",
        "## Constituents",
        "",
        "| Symbol | Name | Weight (%) | Sector |",
        "|---|---|---:|---|",
    ]
    for row in frame.itertuples():
        sector = row.sector if pd.notna(row.sector) else "—"
        lines.append(
            f"| `{row.symbol}` | {row.name} | {row.source_weight_pct:.6f} | {sector} |"
        )
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build_sp500_universe(
    *,
    raw_dir: Path = DEFAULT_RAW_DIR / "sp500",
    processed_path: Path = DEFAULT_PROCESSED_DIR / "sp500_universe.parquet",
    docs_path: Path = REPO_ROOT / "docs" / "sp500_universe.md",
    nasdaq_screener_path: Path | None = (
        DEFAULT_RAW_DIR / "positioning" / "nasdaq_screener.json"
    ),
    local_source: Path | None = None,
    force: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Acquire, parse, annotate, persist, and document the frozen snapshot."""

    raw_path = raw_dir / "holdings-daily-us-en-spy.xlsx"
    metadata = cache_public_source(
        source_key="state_street_spy_daily_holdings",
        source_url=SPY_HOLDINGS_URL,
        raw_path=raw_path,
        local_source=local_source,
        force=force,
    )
    holdings, as_of_date = parse_spy_holdings(raw_path)
    holdings = attach_current_sectors(
        holdings,
        nasdaq_screener_path=nasdaq_screener_path,
    )
    holdings["membership_source"] = SPY_SOURCE
    holdings["membership_status"] = MEMBERSHIP_STATUS
    holdings["survivorship_bias"] = True
    holdings["retrieved_at_utc"] = metadata["retrieval_timestamp_utc"]

    write_parquet(holdings, processed_path)
    update_raw_metadata(
        raw_path,
        observation_as_of_date=as_of_date.date().isoformat(),
        retained_equity_holdings=int(len(holdings)),
        retained_source_weight_pct=round(
            float(holdings["source_weight_pct"].sum()), 8
        ),
        membership_status=MEMBERSHIP_STATUS,
        survivorship_bias=True,
    )
    write_sp500_document(
        holdings,
        docs_path,
        retrieval=metadata["retrieval_timestamp_utc"],
    )
    report = {
        "source": SPY_SOURCE,
        "source_url": SPY_HOLDINGS_URL,
        "product_url": SPY_PRODUCT_URL,
        "holdings_as_of": as_of_date.date().isoformat(),
        "retrieval_timestamp_utc": metadata["retrieval_timestamp_utc"],
        "membership_status": MEMBERSHIP_STATUS,
        "survivorship_bias": True,
        "constituents": int(len(holdings)),
        "sector_coverage": int(holdings["sector"].notna().sum()),
        "source_weight_pct": round(float(holdings["source_weight_pct"].sum()), 8),
        "processed_path": str(processed_path.relative_to(REPO_ROOT)),
    }
    write_json(raw_dir / "universe_report.json", report)
    return holdings, report


def build_sp500_prices(
    *,
    universe_path: Path = DEFAULT_PROCESSED_DIR / "sp500_universe.parquet",
    reusable_prices_path: Path = DEFAULT_PROCESSED_DIR / "universe_prices.parquet",
    processed_path: Path = DEFAULT_PROCESSED_DIR / "sp500_prices.parquet",
    raw_dir: Path = DEFAULT_RAW_DIR / "sp500" / "prices",
    start: pd.Timestamp = PRICE_START,
    end: pd.Timestamp | None = None,
    force: bool = False,
    min_interval_seconds: float = 0.25,
) -> dict[str, Any]:
    """Reuse existing histories, fetch only missing symbols, and persist coverage."""

    universe = pd.read_parquet(universe_path)
    symbols = sorted(universe["symbol"].astype(str).unique())
    reusable = (
        pd.read_parquet(reusable_prices_path)
        if reusable_prices_path.is_file()
        else pd.DataFrame()
    )
    if not reusable.empty:
        reusable = reusable.loc[reusable["symbol"].isin(symbols)].copy()
    reusable_symbols = set(reusable["symbol"].unique()) if not reusable.empty else set()
    to_fetch = symbols if force else sorted(set(symbols) - reusable_symbols)

    raw_dir.mkdir(parents=True, exist_ok=True)
    fetched_frames: list[pd.DataFrame] = []
    unavailable: list[str] = []
    empty: list[str] = []
    for symbol in to_fetch:
        outcome = fetch_symbol(
            symbol,
            raw_dir=raw_dir,
            start=start,
            end=end,
            force=force,
            min_interval_seconds=min_interval_seconds,
        )
        if outcome["status"] == "unavailable":
            unavailable.append(symbol)
        elif outcome["status"] == "empty":
            empty.append(symbol)
        else:
            fetched_frames.append(outcome["frame"])

    components = []
    if not reusable.empty and not force:
        components.append(reusable)
    components.extend(fetched_frames)
    prices = (
        pd.concat(components, ignore_index=True)
        .drop_duplicates(["symbol", "date"], keep="last")
        .sort_values(["symbol", "date"])
        .reset_index(drop=True)
        if components
        else pd.DataFrame()
    )
    if not prices.empty:
        write_parquet(prices, processed_path)

    coverage = (
        prices.groupby("symbol")["date"].agg(["min", "max", "count"]).reset_index()
        if not prices.empty
        else pd.DataFrame(columns=["symbol", "min", "max", "count"])
    )
    covered = set(coverage["symbol"])
    report = {
        "requested": len(symbols),
        "reused_symbols": len(reusable_symbols & set(symbols)) if not force else 0,
        "download_requested": len(to_fetch),
        "downloaded_symbols": len(fetched_frames),
        "covered_symbols": len(covered),
        "coverage_rate": round(len(covered) / max(1, len(symbols)), 6),
        "uncovered_symbols": sorted(set(symbols) - covered),
        "unavailable": unavailable,
        "empty": empty,
        "rows": int(len(prices)),
        "first_date": (
            pd.Timestamp(prices["date"].min()).date().isoformat()
            if not prices.empty
            else None
        ),
        "last_date": (
            pd.Timestamp(prices["date"].max()).date().isoformat()
            if not prices.empty
            else None
        ),
        "price_source": (
            "Yahoo Finance chart API; existing top-200 histories reused byte-for-"
            "value and new S&P 500 symbols cached separately"
        ),
        "adjustment": "split- and dividend-adjusted close for momentum and returns",
        "processed_path": str(processed_path.relative_to(REPO_ROOT)),
    }
    write_json(raw_dir.parent / "price_acquisition_report.json", report)
    if not coverage.empty:
        coverage = coverage.rename(
            columns={"min": "first_date", "max": "last_date", "count": "rows"}
        )
        write_parquet(
            coverage,
            processed_path.with_name("sp500_price_coverage.parquet"),
        )
    return report


def build_benchmark_frame(prices: pd.DataFrame) -> pd.DataFrame:
    """Convert one SPY adjusted-close history to an auditable return series."""

    required = {"date", "symbol", "close_total_return_adjusted"}
    missing = sorted(required - set(prices.columns))
    if missing:
        raise KeyError(f"benchmark prices missing required columns: {missing}")
    frame = prices.loc[:, sorted(required)].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date")
    if frame.empty or frame["date"].duplicated().any():
        raise ValueError("benchmark prices must contain sorted unique dates")
    symbols = frame["symbol"].dropna().astype(str).unique()
    if len(symbols) != 1 or symbols[0] != "SPY":
        raise ValueError("benchmark price history must contain only SPY")
    frame["benchmark_return"] = frame["close_total_return_adjusted"].pct_change(
        fill_method=None
    )
    frame["benchmark_symbol"] = "SPY"
    frame["benchmark_source"] = (
        "Yahoo Finance SPY split- and dividend-adjusted close"
    )
    frame["benchmark_status"] = "primary_spy_total_return_proxy"
    return frame.loc[
        :,
        [
            "date",
            "benchmark_symbol",
            "close_total_return_adjusted",
            "benchmark_return",
            "benchmark_source",
            "benchmark_status",
        ],
    ].reset_index(drop=True)


def build_sp500_benchmark(
    *,
    raw_dir: Path = DEFAULT_RAW_DIR / "sp500" / "benchmark",
    processed_path: Path = DEFAULT_PROCESSED_DIR / "sp500_benchmark.parquet",
    start: pd.Timestamp = PRICE_START,
    end: pd.Timestamp | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Acquire and persist the SPY total-return proxy used for Phase 3 beta."""

    outcome = fetch_symbol(
        "SPY",
        raw_dir=raw_dir,
        start=start,
        end=end,
        force=force,
        min_interval_seconds=0.25,
    )
    if outcome["status"] != "ok":
        report = {
            "status": "unavailable",
            "symbol": "SPY",
            "source": "Yahoo Finance chart API",
            "reason": outcome["status"],
        }
        write_json(raw_dir.parent / "benchmark_acquisition_report.json", report)
        return report

    benchmark = build_benchmark_frame(outcome["frame"])
    write_parquet(benchmark, processed_path)
    report = {
        "status": "available",
        "benchmark_status": "primary_spy_total_return_proxy",
        "symbol": "SPY",
        "source": "Yahoo Finance chart API",
        "adjustment": "split- and dividend-adjusted close",
        "rows": int(len(benchmark)),
        "first_date": benchmark["date"].min().date().isoformat(),
        "last_date": benchmark["date"].max().date().isoformat(),
        "processed_path": str(processed_path.relative_to(REPO_ROOT)),
        "interpretation": (
            "investable ETF total-return proxy for the S&P 500; not the cash "
            "index or an official index total-return series"
        ),
    }
    write_json(raw_dir.parent / "benchmark_acquisition_report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR / "sp500")
    parser.add_argument("--processed-path", type=Path, default=DEFAULT_PROCESSED_DIR / "sp500_universe.parquet")
    parser.add_argument("--docs-path", type=Path, default=REPO_ROOT / "docs" / "sp500_universe.md")
    parser.add_argument("--local-source", type=Path)
    parser.add_argument(
        "--prices",
        action="store_true",
        help="After building the snapshot, reuse/fetch its daily price histories.",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Acquire the SPY adjusted-close benchmark used by Phase 3.",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    _, report = build_sp500_universe(
        raw_dir=args.raw_dir,
        processed_path=args.processed_path,
        docs_path=args.docs_path,
        local_source=args.local_source,
        force=args.force,
    )
    if args.prices:
        report["prices"] = build_sp500_prices(
            universe_path=args.processed_path,
            raw_dir=args.raw_dir / "prices",
            force=args.force,
        )
    if args.benchmark:
        report["benchmark"] = build_sp500_benchmark(
            raw_dir=args.raw_dir / "benchmark",
            force=args.force,
        )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
