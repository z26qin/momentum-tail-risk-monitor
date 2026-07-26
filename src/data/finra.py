"""FINRA positioning inputs: publication schedule, short interest, daily short volume.

Three separate retrieval paths, all established by observation in the Stage 1
probe rather than assumed:

1. **Short interest** — Query API dataset ``otcMarket/consolidatedShortInterest``
   (POST, JSON body, no authentication). 206 settlement dates covering
   2017-12-29 .. 2026-07-15.
2. **Daily short sale volume** — the CDN bulk file
   ``cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt``. ``CNMS`` is
   already consolidated across reporting facilities, so the per-facility files
   (``FNSQ``, ``FNYX``, ``FNRA``, ``FORF``) do not need to be combined.
   Non-trading days answer HTTP 403, which is a legitimate absence and is
   cached as such.
3. **Publication schedule** — FINRA's own *Short Interest Reporting Dates*
   table, which carries an explicit Publication Date column. Historical years
   come from archived snapshots of the same FINRA page.

**What the daily files are and are not.** The FINRA daily short sale volume
files cover only off-exchange trades reported to a FINRA Trade Reporting
Facility, the Alternative Display Facility, or the OTC Reporting Facility for
public dissemination. They are not consolidated with exchange data, and
offsetting buys are not reflected, which inflates apparent short concentration.
FINRA states explicitly that these files do not equate to short interest
position data. ``short_vol_share`` is therefore a **flow** measure of shorting
activity; ``days_to_cover`` is a **position** measure. They are complementary,
not substitutes, and a divergence between them is not automatically an error.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html
import io
import json
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

from src.data.symbols import to_canonical, to_finra_daily, to_finra_short_interest
from src.utils.http import cached_fetch
from src.utils.io import DEFAULT_PROCESSED_DIR, DEFAULT_RAW_DIR, write_json


SHORT_INTEREST_URL = (
    "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
)
DAILY_FILE_TEMPLATE = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{stamp}.txt"
DAILY_FILE_START = pd.Timestamp("2018-08-01")

SCHEDULE_LIVE_URL = (
    "https://www.finra.org/filing-reporting/regulatory-filing-systems/short-interest"
)

#: Archived snapshots of FINRA's own schedule page. Each snapshot carries the
#: schedule for its own year and the next, so the set overlaps deliberately:
#: overlapping years are cross-checked against each other.
SCHEDULE_SNAPSHOTS: tuple[tuple[str, str], ...] = (
    ("20171228211937", "https://www.finra.org/industry/short-interest-reporting"),
    ("20180607124530", "https://www.finra.org/industry/short-interest-reporting"),
    ("20190602173819", "https://www.finra.org/industry/short-interest-reporting"),
    ("20200718232030", SCHEDULE_LIVE_URL),
    ("20210606131123", SCHEDULE_LIVE_URL),
    ("20220603024714", SCHEDULE_LIVE_URL),
    ("20230608091448", SCHEDULE_LIVE_URL),
    ("20240619221819", SCHEDULE_LIVE_URL),
    ("20250612150309", SCHEDULE_LIVE_URL),
)

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

#: Tickers that referred to a **different company** earlier in the sample.
#:
#: The price vendor back-fills a company's whole history under its *current*
#: ticker, while FINRA files use the ticker that was in force on the trade date.
#: Where a ticker was reused, joining on the symbol alone silently attaches one
#: company's short interest to another company's prices.
#:
#: These three were found by reading FINRA's own ``issueName`` field across all
#: 58 universe symbols whose issue name changed during the sample. The other 55
#: are naming-convention changes for the same entity (FINRA restyled its issue
#: names in March 2018, so "Boeing" became "Boeing Company"), and are kept.
#:
#: Each entry is the first settlement date on which the ticker refers to the
#: company the price series describes. Rows before it are dropped.
TICKER_IDENTITY_FROM: dict[str, tuple[str, str]] = {
    # ticker: (first settlement date as the current entity, prior occupant)
    "META": ("2022-06-15", "Roundhill Ball Metaverse ETF"),
    "SPCX": ("2026-06-15", "The SPAC and New Issue ETF"),
    "BNY": ("2026-05-29", "Blackrock New York Muni Tr"),
}

#: Corporate-form words that carry no entity information.
_ENTITY_STOPWORDS = frozenset(
    {
        "inc", "inc.", "corp", "corp.", "corporation", "co", "co.", "company",
        "the", "group", "class", "common", "stock", "ltd", "plc", "lp", "l.p.",
        "holdings", "&", "and", "of", "trust", "tr", "etf", "ordinary",
        "shares", "share", "a", "b", "c", "incorporate", "incorporated",
    }
)


def _entity_tokens(name: str) -> set[str]:
    cleaned = re.sub(r"[^a-z0-9 ]", " ", str(name).lower())
    return {token for token in cleaned.split() if token not in _ENTITY_STOPWORDS}


def detect_entity_changes(short_interest: pd.DataFrame) -> list[dict[str, Any]]:
    """Flag tickers whose issue-name history suggests the entity changed.

    This is a **detector, not an automatic filter**: it reports candidates so a
    human can read the issue names and decide, because renames of the same
    company (General Electric to GE Aerospace, Raytheon Technologies to RTX
    Corporation) share no tokens either and must not be dropped. Its job is to
    make sure a future universe cannot introduce a reused ticker unnoticed.
    """

    candidates: list[dict[str, Any]] = []
    for symbol, group in short_interest.groupby("finra_symbol"):
        ordered = group.sort_values("settlement_date")
        current = _entity_tokens(ordered["issueName"].iloc[-1])
        if not current:
            continue
        disjoint = ordered.loc[
            ordered["issueName"].map(lambda name: not (_entity_tokens(name) & current))
        ]
        if disjoint.empty:
            continue
        candidates.append(
            {
                "symbol": symbol,
                "current_issue_name": ordered["issueName"].iloc[-1],
                "prior_issue_names": sorted(disjoint["issueName"].unique()),
                "prior_last_settlement": disjoint["settlement_date"]
                .max()
                .date()
                .isoformat(),
                "prior_print_count": int(len(disjoint)),
                "handled_by_override": symbol in TICKER_IDENTITY_FROM,
            }
        )
    return candidates


def apply_ticker_identity_guard(
    frame: pd.DataFrame,
    *,
    symbol_column: str,
    date_column: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Drop rows dated before a reused ticker referred to the current company."""

    dropped: dict[str, int] = {}
    keep = pd.Series(True, index=frame.index)
    for symbol, (from_date, _prior) in TICKER_IDENTITY_FROM.items():
        mask = (frame[symbol_column] == symbol) & (
            frame[date_column] < pd.Timestamp(from_date)
        )
        count = int(mask.sum())
        if count:
            dropped[symbol] = count
            keep &= ~mask
    return frame.loc[keep].copy(), dropped

#: Used only for settlement dates that no retrieved schedule covers.
#:
#: The spec's stated fallback is settlement + 8 plain business days. Measuring
#: FINRA's own published schedule instead gives a sharper rule: across the 197
#: retrieved (settlement, publication) pairs the gap is exactly **7 business
#: days excluding US federal holidays** in 186 cases (6 in 4 cases, 8 in 7 —
#: FINRA's calendar is close to, but not identical with, the federal one).
#: The derived rule is therefore used for uncovered dates and flagged
#: distinctly, and the 10-business-day variant is carried alongside as the
#: sensitivity the spec asks for.
FALLBACK_PUBLICATION_BUSINESS_DAYS = 7
SENSITIVITY_PUBLICATION_BUSINESS_DAYS = 10

_US_FEDERAL_HOLIDAYS = None


def _federal_holidays() -> Any:
    """Cache the federal holiday array used by the derived fallback rule."""

    global _US_FEDERAL_HOLIDAYS
    if _US_FEDERAL_HOLIDAYS is None:
        from pandas.tseries.holiday import USFederalHolidayCalendar

        holidays = USFederalHolidayCalendar().holidays("2015-01-01", "2030-12-31")
        _US_FEDERAL_HOLIDAYS = holidays.values.astype("datetime64[D]")
    return _US_FEDERAL_HOLIDAYS


# --------------------------------------------------------------------------
# Publication schedule
# --------------------------------------------------------------------------


def decode_page(payload: bytes) -> str:
    """Decode a page, transparently gunzipping archived responses.

    The Wayback ``id_`` endpoint replays the *original* captured bytes, which
    for several FINRA snapshots were gzip-compressed. Without this the page
    decodes to binary noise and the schedule silently parses to zero rows,
    which is exactly how the 2022 and 2024 schedules first went missing.
    """

    if payload[:2] == b"\x1f\x8b":
        payload = gzip.decompress(payload)
    return payload.decode("utf-8", errors="replace")


def html_to_text(markup: str) -> str:
    """Flatten HTML to newline-separated text without a parser dependency."""

    stripped = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", markup)
    stripped = re.sub(r"(?s)<[^>]+>", "\n", stripped)
    text = html.unescape(stripped)
    text = re.sub(r"[   ]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text)


def parse_schedule_text(text: str) -> pd.DataFrame:
    """Extract (settlement, due, publication) triplets from a FINRA schedule page.

    The table renders as a flat run of ``Month Day`` cells in column order, so
    the triplets are recovered positionally. Publication dates that roll into
    the following January are detected by a month decrease relative to their own
    settlement date, which is how FINRA presents the final row of every year.
    """

    records: list[dict[str, Any]] = []
    headers = list(
        re.finditer(r"(20\d{2})\s+Short Interest Reporting Dates", text, re.IGNORECASE)
    )
    for index, header in enumerate(headers):
        year = int(header.group(1))
        start = header.end()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        block = text[start:end]

        month_day = [
            (MONTHS[match.group(1).lower()], int(match.group(2)))
            for match in re.finditer(
                r"\b(January|February|March|April|May|June|July|August|September|"
                r"October|November|December)\s+(\d{1,2})\b",
                block,
                re.IGNORECASE,
            )
        ]
        for position in range(0, len(month_day) - 2, 3):
            settlement_md, due_md, publication_md = month_day[position : position + 3]
            settlement = pd.Timestamp(year=year, month=settlement_md[0], day=settlement_md[1])

            def _resolve(candidate: tuple[int, int]) -> pd.Timestamp:
                candidate_year = year + 1 if candidate[0] < settlement_md[0] else year
                return pd.Timestamp(
                    year=candidate_year, month=candidate[0], day=candidate[1]
                )

            due = _resolve(due_md)
            publication = _resolve(publication_md)
            # Reject stray prose matches. FINRA's own schedule never places a
            # due date more than a handful of days after settlement, nor a
            # publication date more than about three weeks after it. Without
            # these bounds, unrelated dates elsewhere on the page group into
            # plausible-looking triplets with 150-day publication lags.
            if not settlement < due <= publication:
                continue
            if not 1 <= (due - settlement).days <= 10:
                continue
            if not 5 <= (publication - settlement).days <= 25:
                continue
            records.append(
                {
                    "settlement_date": settlement,
                    "due_date": due,
                    "publication_date": publication,
                    "schedule_year": year,
                }
            )
    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        return frame
    return frame.drop_duplicates(subset="settlement_date", keep="first").sort_values(
        "settlement_date"
    ).reset_index(drop=True)


def fetch_schedules(raw_dir: Path, force: bool = False) -> dict[str, Any]:
    """Retrieve the live schedule page plus every archived snapshot."""

    raw_dir.mkdir(parents=True, exist_ok=True)
    frames: list[pd.DataFrame] = []
    sources: list[dict[str, Any]] = []

    live = cached_fetch(
        cache_path=raw_dir / "schedule_live.html",
        url=SCHEDULE_LIVE_URL,
        source_key="finra_schedule_live",
        min_interval_seconds=1.0,
        force=force,
        tolerate_failure=True,
    )
    if not live.transient_failure:
        parsed = parse_schedule_text(html_to_text(decode_page(live.read_bytes())))
        frames.append(parsed.assign(schedule_source="finra_live"))
        sources.append({"source": "finra_live", "rows": int(len(parsed))})

    for stamp, url in SCHEDULE_SNAPSHOTS:
        snapshot_url = f"https://web.archive.org/web/{stamp}id_/{url}"
        result = cached_fetch(
            cache_path=raw_dir / f"schedule_{stamp}.html",
            url=snapshot_url,
            source_key=f"finra_schedule_{stamp}",
            min_interval_seconds=2.0,
            backoff_seconds=10.0,
            max_retries=3,
            force=force,
            tolerate_failure=True,
        )
        if result.transient_failure or result.absent:
            sources.append({"source": stamp, "rows": 0, "status": "unavailable"})
            continue
        parsed = parse_schedule_text(html_to_text(decode_page(result.read_bytes())))
        frames.append(parsed.assign(schedule_source=f"archive_{stamp}"))
        sources.append({"source": f"archive_{stamp}", "rows": int(len(parsed))})

    if not frames:
        return {"schedule": pd.DataFrame(), "sources": sources, "conflicts": []}

    combined = pd.concat(frames, ignore_index=True)

    # Cross-check: overlapping snapshots must agree on a settlement date's
    # publication date. Disagreement is reported, never silently resolved.
    conflicts = []
    for settlement, group in combined.groupby("settlement_date"):
        distinct = group["publication_date"].nunique()
        if distinct > 1:
            conflicts.append(
                {
                    "settlement_date": settlement.date().isoformat(),
                    "publication_dates": sorted(
                        value.date().isoformat()
                        for value in group["publication_date"].unique()
                    ),
                    "sources": sorted(group["schedule_source"].unique()),
                }
            )

    schedule = (
        combined.sort_values(["settlement_date", "schedule_source"])
        .drop_duplicates(subset="settlement_date", keep="first")
        .reset_index(drop=True)
    )
    return {"schedule": schedule, "sources": sources, "conflicts": conflicts}


def business_day_offset(date: pd.Timestamp, days: int) -> pd.Timestamp:
    """Add ``days`` business days, excluding US federal holidays."""

    import numpy as np

    shifted = np.busday_offset(
        np.datetime64(date.date(), "D"),
        days,
        roll="forward",
        holidays=_federal_holidays(),
    )
    return pd.Timestamp(str(shifted))


def attach_publication_dates(
    settlement_dates: Iterable[pd.Timestamp],
    schedule: pd.DataFrame,
) -> pd.DataFrame:
    """Map every settlement date to a publication date and record which rule applied."""

    lookup: dict[pd.Timestamp, pd.Timestamp] = {}
    if not schedule.empty:
        lookup = dict(
            zip(schedule["settlement_date"], schedule["publication_date"])
        )

    records = []
    for settlement in sorted(set(settlement_dates)):
        scheduled = lookup.get(settlement)
        if scheduled is not None:
            records.append(
                {
                    "settlement_date": settlement,
                    "publication_date": scheduled,
                    "publication_date_rule": "finra_published_schedule",
                }
            )
        else:
            records.append(
                {
                    "settlement_date": settlement,
                    "publication_date": business_day_offset(
                        settlement, FALLBACK_PUBLICATION_BUSINESS_DAYS
                    ),
                    "publication_date_rule": "settlement_plus_8_business_days",
                }
            )
        records[-1]["publication_date_sensitivity_10bd"] = business_day_offset(
            settlement, SENSITIVITY_PUBLICATION_BUSINESS_DAYS
        )
    return pd.DataFrame.from_records(records)


# --------------------------------------------------------------------------
# Short interest
# --------------------------------------------------------------------------

SHORT_INTEREST_FIELDS = [
    "settlementDate",
    "symbolCode",
    "issueName",
    "marketClassCode",
    "currentShortPositionQuantity",
    "previousShortPositionQuantity",
    "averageDailyVolumeQuantity",
    "daysToCoverQuantity",
    "stockSplitFlag",
    "revisionFlag",
]

PAGE_LIMIT = 5000


def fetch_short_interest(
    symbols: Sequence[str],
    *,
    raw_dir: Path,
    force: bool = False,
) -> pd.DataFrame:
    """Page the whole short-interest history for the universe into the cache."""

    raw_dir.mkdir(parents=True, exist_ok=True)
    vendor_symbols = sorted({to_finra_short_interest(symbol) for symbol in symbols})
    # The requested symbol set is part of the request body, so it must be part
    # of the cache key. Without this, changing the universe silently reuses the
    # previous universe's cached pages.
    universe_key = hashlib.sha256(
        ",".join(vendor_symbols).encode("utf-8")
    ).hexdigest()[:12]

    frames: list[pd.DataFrame] = []
    offset = 0
    page = 0
    while True:
        body = json.dumps(
            {
                "limit": PAGE_LIMIT,
                "offset": offset,
                "fields": SHORT_INTEREST_FIELDS,
                "domainFilters": [
                    {"fieldName": "symbolCode", "values": vendor_symbols}
                ],
            }
        ).encode("utf-8")
        result = cached_fetch(
            cache_path=raw_dir / f"short_interest_{universe_key}_page_{page:03d}.csv",
            url=SHORT_INTEREST_URL,
            source_key=f"finra_short_interest_{universe_key}_page_{page:03d}",
            method="POST",
            body=body,
            headers={"Content-Type": "application/json", "Accept": "text/plain"},
            min_interval_seconds=1.0,
            force=force,
            extra_metadata={
                "request_offset": offset,
                "request_limit": PAGE_LIMIT,
                "symbol_count": len(vendor_symbols),
            },
        )
        text = result.read_text()
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            break
        frames.append(pd.DataFrame.from_records(rows))
        if len(rows) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
        page += 1

    if not frames:
        return pd.DataFrame()

    frame = pd.concat(frames, ignore_index=True)
    frame["settlement_date"] = pd.to_datetime(frame["settlementDate"])
    frame["finra_symbol"] = frame["symbolCode"].str.strip().str.upper()
    numeric = {
        "short_interest_shares": "currentShortPositionQuantity",
        "previous_short_interest_shares": "previousShortPositionQuantity",
        "finra_average_daily_volume": "averageDailyVolumeQuantity",
        "finra_days_to_cover": "daysToCoverQuantity",
    }
    for target, source in numeric.items():
        frame[target] = pd.to_numeric(frame[source], errors="coerce")
    frame["stock_split_flag"] = frame["stockSplitFlag"].fillna("").str.strip()
    frame["revision_flag"] = frame["revisionFlag"].fillna("").str.strip()
    return frame.drop_duplicates(
        subset=["settlement_date", "finra_symbol"], keep="last"
    ).reset_index(drop=True)


# --------------------------------------------------------------------------
# Daily short sale volume
# --------------------------------------------------------------------------


def fetch_daily_file(
    trade_date: pd.Timestamp,
    *,
    raw_dir: Path,
    force: bool = False,
) -> dict[str, Any]:
    """Cache one CNMS daily short volume file, gzip-compressed on disk."""

    stamp = trade_date.strftime("%Y%m%d")
    result = cached_fetch(
        cache_path=raw_dir / f"CNMSshvol{stamp}.txt",
        url=DAILY_FILE_TEMPLATE.format(stamp=stamp),
        source_key=f"finra_cnms_{stamp}",
        min_interval_seconds=0.2,
        backoff_seconds=5.0,
        max_retries=3,
        absent_statuses=(403, 404),
        force=force,
        tolerate_failure=True,
    )
    return {"date": trade_date, "result": result}


def parse_daily_file(text: str) -> pd.DataFrame:
    """Parse the pipe-delimited CNMS daily file."""

    rows = list(csv.DictReader(io.StringIO(text), delimiter="|"))
    records = []
    for row in rows:
        symbol = (row.get("Symbol") or "").strip()
        if not symbol or not (row.get("Date") or "").strip().isdigit():
            continue
        records.append(
            {
                "trade_date": pd.Timestamp(row["Date"].strip()),
                "finra_daily_symbol": symbol.upper(),
                "short_volume": pd.to_numeric(row.get("ShortVolume"), errors="coerce"),
                "short_exempt_volume": pd.to_numeric(
                    row.get("ShortExemptVolume"), errors="coerce"
                ),
                "total_volume": pd.to_numeric(row.get("TotalVolume"), errors="coerce"),
            }
        )
    return pd.DataFrame.from_records(records)


def acquire_daily_short_volume(
    symbols: Sequence[str],
    *,
    raw_dir: Path,
    start: pd.Timestamp = DAILY_FILE_START,
    end: pd.Timestamp | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Download every daily file in range and keep only the universe rows.

    The raw files total roughly 800 MB across the sample, so each is stored
    gzip-compressed and the git tree keeps only the provenance manifest. The
    compact universe extract is the artifact downstream code reads.
    """

    raw_dir.mkdir(parents=True, exist_ok=True)
    # pandas 3 returns a tz-aware stamp from utcnow(); the file calendar is a
    # naive UTC calendar-date index, so the two must not be mixed.
    end = end or pd.Timestamp(pd.Timestamp.now('UTC').date())
    wanted = {to_finra_daily(symbol): to_canonical(symbol) for symbol in symbols}

    extracts: list[pd.DataFrame] = []
    absent_days: list[str] = []
    failed_days: list[str] = []
    present_days = 0

    for trade_date in pd.date_range(start, end, freq="D"):
        # Weekends never have a file; skipping them avoids ~570 pointless 403s.
        if trade_date.weekday() >= 5:
            continue
        stamp = trade_date.strftime("%Y%m%d")
        compressed = raw_dir / f"CNMSshvol{stamp}.txt.gz"
        sidecar = raw_dir / f"CNMSshvol{stamp}.txt.metadata.json"

        if compressed.is_file() and sidecar.is_file():
            text = gzip.decompress(compressed.read_bytes()).decode("utf-8", "replace")
        else:
            handle = fetch_daily_file(trade_date, raw_dir=raw_dir, force=force)
            result = handle["result"]
            if result.transient_failure:
                failed_days.append(stamp)
                continue
            if result.absent:
                absent_days.append(stamp)
                continue
            text = result.read_text()
            compressed.write_bytes(gzip.compress(text.encode("utf-8"), 6))
            result.path.unlink(missing_ok=True)

        frame = parse_daily_file(text)
        if frame.empty:
            absent_days.append(stamp)
            continue
        present_days += 1
        subset = frame.loc[frame["finra_daily_symbol"].isin(wanted)].copy()
        subset["symbol"] = subset["finra_daily_symbol"].map(wanted)
        extracts.append(subset)

    combined = (
        pd.concat(extracts, ignore_index=True) if extracts else pd.DataFrame()
    )
    return {
        "daily": combined,
        "trading_days_with_file": present_days,
        "absent_days": len(absent_days),
        "failed_days": failed_days,
        "first_absent": absent_days[:5],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR / "finra")
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument(
        "--stage",
        choices=("schedule", "short-interest", "daily", "all"),
        default="all",
    )
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> None:
    from src.data.universe import load_universe

    args = _build_parser().parse_args()
    symbols = load_universe()
    report: dict[str, Any] = {}

    if args.stage in ("schedule", "all"):
        outcome = fetch_schedules(args.raw_dir / "schedule", force=args.force)
        schedule = outcome["schedule"]
        if not schedule.empty:
            schedule.to_parquet(
                args.processed_dir / "finra_publication_schedule.parquet",
                index=False,
                engine="pyarrow",
            )
        report["schedule"] = {
            "rows": int(len(schedule)),
            "sources": outcome["sources"],
            "conflicts": outcome["conflicts"],
            "first": schedule["settlement_date"].min().date().isoformat()
            if not schedule.empty
            else None,
            "last": schedule["settlement_date"].max().date().isoformat()
            if not schedule.empty
            else None,
        }

    if args.stage in ("short-interest", "all"):
        frame = fetch_short_interest(
            symbols, raw_dir=args.raw_dir / "short_interest", force=args.force
        )
        if not frame.empty:
            frame.to_parquet(
                args.processed_dir / "finra_short_interest.parquet",
                index=False,
                engine="pyarrow",
            )
        report["short_interest"] = {
            "rows": int(len(frame)),
            "symbols": int(frame["finra_symbol"].nunique()) if not frame.empty else 0,
            "settlement_dates": int(frame["settlement_date"].nunique())
            if not frame.empty
            else 0,
        }

    if args.stage in ("daily", "all"):
        outcome = acquire_daily_short_volume(
            symbols, raw_dir=args.raw_dir / "daily", force=args.force
        )
        daily = outcome.pop("daily")
        if not daily.empty:
            daily.to_parquet(
                args.processed_dir / "finra_daily_universe.parquet",
                index=False,
                engine="pyarrow",
            )
            outcome["rows"] = int(len(daily))
        report["daily"] = outcome

    write_json(args.raw_dir / "finra_acquisition_report.json", report)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
