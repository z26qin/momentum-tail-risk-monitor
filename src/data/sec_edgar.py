"""Shares outstanding from SEC EDGAR, for short interest as a fraction of float.

Why this exists. ``short_interest_ratio`` scales each symbol against its own
trailing median print, which is unit-free but says nothing about level: it
reports that a name is unusually shorted *for itself*, not that 20% of its
shares are short. Shares outstanding restores the level, and it is the only
denominator that is both volume-free and comparable across companies.

The concept fetched is ``dei:EntityCommonStockSharesOutstanding`` — the cover
page of every 10-K and 10-Q — rather than a ``us-gaap`` balance-sheet tag, which
is inconsistently applied across filers.

Point-in-time. Each observation carries an ``end`` date (what the count is as
of) and a ``filed`` date (when it became public). Only ``filed`` may be used to
decide visibility; the gap between them runs to weeks, which is exactly the kind
of look-ahead this project exists to avoid.

Access. SEC's fair-access policy requires a declared contact in the User-Agent
and caps traffic at 10 requests/second. This module stays at 5/second. The
contact address is supplied by the operator through the ``SEC_CONTACT_EMAIL``
environment variable and is deliberately not carried in the repository — see
``_user_agent``.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from src.utils.http import FetchResult, cached_fetch
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    DEFAULT_RAW_DIR,
    write_json,
)


#: SEC's fair-access policy requires a real, reachable contact on every request.
#: It is read from the environment rather than defaulted, for two reasons: a
#: personal address does not belong in a public tree, and a placeholder default
#: would send SEC a contact that does not resolve, which is the thing the policy
#: exists to prevent. Unset is therefore an error, not a fallback.
SEC_CONTACT_EMAIL_VAR = "SEC_CONTACT_EMAIL"
USER_AGENT_TEMPLATE = "momentum-crash research {contact}"

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
CONCEPT_URL = (
    "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}"
    "/dei/EntityCommonStockSharesOutstanding.json"
)
#: The concept endpoint answers 404 for a number of filers that do report the
#: tag — XOM returns 404 there while companyfacts holds all 69 of its
#: observations. Mostly multi-class issuers, but XOM is single-class, so the
#: pattern is an endpoint quirk rather than anything about the company. Falling
#: back costs a larger payload, which is why it is a fallback and not the
#: primary route.
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SHARES_CONCEPT = "EntityCommonStockSharesOutstanding"

#: Last resort. Multi-class issuers tag the cover-page count with a share-class
#: axis, and companyfacts drops dimensional facts, so the plain ``dei`` tag is
#: empty for every one of them — Alphabet, Meta, Dell, Palantir, Airbnb,
#: DoorDash, Robinhood, Cloudflare, Datadog, AppLovin, Carvana. Weighted-average
#: basic shares is undimensioned and sums across classes. It is a period average
#: rather than a period-end count and excludes unvested shares, so observations
#: taken this way are labelled in ``shares_source`` and never blended silently.
FALLBACK_CONCEPT = "WeightedAverageNumberOfSharesOutstandingBasic"

#: SEC's ticker file maps to the *current* registrant, which is not always the
#: entity holding the history. XOM maps to CIK 2115436, a financing shell whose
#: only facts are shelf-registration fees (form POSASR); the operating company
#: has filed under 34088 since 1993 and still does. Verified by inspecting both
#: payloads, not assumed.
CIK_OVERRIDES = {"XOM": 34088}

#: SEC permits 10 per second. Half that leaves room for other traffic from the
#: same address and still finishes a 200-symbol universe in about a minute.
MIN_INTERVAL_SECONDS = 0.2

#: A company that has never filed the cover-page tag answers 404. That is a
#: genuine absence and is cached as one, so re-runs stay offline.
ABSENT_STATUSES = (404,)

DEFAULT_SEC_DIR = DEFAULT_RAW_DIR / "sec"


def _user_agent() -> str:
    """The declared contact SEC requires, or a refusal to make the request.

    Read at call time rather than import time so that merely importing this
    module — which every test doing offline work does — never demands a contact
    address. Only an actual outbound request does.
    """

    contact = os.environ.get(SEC_CONTACT_EMAIL_VAR, "").strip()
    if not contact:
        raise RuntimeError(
            f"{SEC_CONTACT_EMAIL_VAR} is not set. SEC's fair-access policy "
            "requires a real contact address in the User-Agent of every "
            "request, so this is not defaulted. Set it to an address you read:\n"
            f"    export {SEC_CONTACT_EMAIL_VAR}='you@example.edu'\n"
            "Already-cached responses are served from disk and need no contact."
        )
    return USER_AGENT_TEMPLATE.format(contact=contact)


def _headers() -> dict[str, str]:
    # Deliberately no gzip: the cache stores raw response bytes, so a compressed
    # body would be written to disk and fail every later JSON read.
    return {"User-Agent": _user_agent(), "Accept-Encoding": "identity"}


def _is_json(payload: bytes) -> bool:
    try:
        json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return False
    return True


def fetch_ticker_map(*, raw_dir: Path = DEFAULT_SEC_DIR) -> dict[str, int]:
    """Map ticker to CIK. SEC publishes current tickers only.

    That matches the universe, which is current membership and already carries
    a survivorship-bias flag for the same reason.
    """

    result = cached_fetch(
        cache_path=raw_dir / "company_tickers.json",
        url=TICKER_MAP_URL,
        source_key="sec_company_tickers",
        headers=_headers,
        max_retries=1,
        backoff_seconds=0.0,
        min_interval_seconds=MIN_INTERVAL_SECONDS,
        tolerate_failure=True,
        validate=_is_json,
    )
    if result.transient_failure:
        raise RuntimeError("SEC ticker map unavailable; nothing else can proceed")

    payload = result.read_json()
    return {
        str(row["ticker"]).upper(): int(row["cik_str"]) for row in payload.values()
    }


def to_sec_ticker(symbol: str) -> str:
    """Canonical symbol to SEC's spelling: share classes use a hyphen."""

    return symbol.replace(".", "-").upper()


def fetch_company_facts_by_cik(
    cik: int,
    *,
    raw_dir: Path = DEFAULT_SEC_DIR,
) -> FetchResult:
    """Fetch one cache-first Company Facts payload for one distinct issuer.

    Phase 5A deliberately keys this cache by CIK rather than ticker. Multiple
    share classes therefore reuse one SEC response. A real contact address is
    demanded only on a cache miss, through the existing lazy ``_headers``
    callback.
    """

    return cached_fetch(
        cache_path=raw_dir / f"company_facts_CIK{cik:010d}.json",
        url=COMPANY_FACTS_URL.format(cik=cik),
        source_key=f"sec_company_facts_CIK{cik:010d}",
        headers=_headers,
        absent_statuses=ABSENT_STATUSES,
        max_retries=3,
        backoff_seconds=1.0,
        min_interval_seconds=MIN_INTERVAL_SECONDS,
        tolerate_failure=True,
        validate=_is_json,
    )


def fetch_shares_outstanding(
    symbol: str, cik: int, *, raw_dir: Path = DEFAULT_SEC_DIR
) -> pd.DataFrame:
    """One symbol's cover-page share count history, with filing dates."""

    result = cached_fetch(
        cache_path=raw_dir / f"shares_outstanding_{symbol}.json",
        url=CONCEPT_URL.format(cik=cik),
        source_key=f"sec_shares_outstanding_{symbol}",
        headers=_headers,
        absent_statuses=ABSENT_STATUSES,
        max_retries=1,
        backoff_seconds=0.0,
        min_interval_seconds=MIN_INTERVAL_SECONDS,
        tolerate_failure=True,
        validate=_is_json,
    )
    if result.transient_failure:
        raise TransientSECFailure(symbol)
    if result.absent:
        units, source = _units_from_company_facts(symbol, cik, raw_dir=raw_dir)
    else:
        units = result.read_json().get("units", {}).get("shares", [])
        source = SHARES_CONCEPT

    return _frame_from_units(symbol, units, source)


def _units_from_company_facts(
    symbol: str, cik: int, *, raw_dir: Path
) -> tuple[list[dict[str, Any]], str]:
    """Second route for filers the concept endpoint does not serve."""

    result = cached_fetch(
        cache_path=raw_dir / f"company_facts_{symbol}.json",
        url=COMPANY_FACTS_URL.format(cik=cik),
        source_key=f"sec_company_facts_{symbol}",
        headers=_headers,
        absent_statuses=ABSENT_STATUSES,
        max_retries=1,
        backoff_seconds=0.0,
        min_interval_seconds=MIN_INTERVAL_SECONDS,
        tolerate_failure=True,
        validate=_is_json,
    )
    if result.transient_failure:
        raise TransientSECFailure(symbol)
    if result.absent:
        return [], SHARES_CONCEPT

    facts = result.read_json().get("facts", {})
    units = (
        facts.get("dei", {}).get(SHARES_CONCEPT, {}).get("units", {}).get("shares", [])
    )
    if units:
        return units, SHARES_CONCEPT

    fallback = (
        facts.get("us-gaap", {})
        .get(FALLBACK_CONCEPT, {})
        .get("units", {})
        .get("shares", [])
    )
    return fallback, FALLBACK_CONCEPT


def _frame_from_units(
    symbol: str, units: list[dict[str, Any]], source: str
) -> pd.DataFrame:
    if not units:
        return pd.DataFrame()

    frame = pd.DataFrame(units)
    frame["symbol"] = symbol
    frame["shares_source"] = source
    if "start" in frame.columns:
        # Weighted-average facts arrive for several period lengths sharing one
        # end date. Keep the shortest — the quarter, not the year to date.
        start = pd.to_datetime(frame["start"], errors="coerce")
        frame["period_days"] = (pd.to_datetime(frame["end"]) - start).dt.days
    else:
        frame["period_days"] = 0
    frame = frame.rename(columns={"val": "shares_outstanding"})
    frame["end_date"] = pd.to_datetime(frame["end"], errors="coerce")
    frame["filed_date"] = pd.to_datetime(frame["filed"], errors="coerce")
    frame = frame.dropna(subset=["end_date", "filed_date", "shares_outstanding"])
    frame = frame.loc[frame["shares_outstanding"] > 0]
    return frame.loc[
        :,
        [
            "symbol",
            "end_date",
            "filed_date",
            "shares_outstanding",
            "shares_source",
            "period_days",
            "form",
            "accn",
        ],
    ]


def point_in_time_shares_outstanding(frame: pd.DataFrame) -> pd.DataFrame:
    """Reduce filings to what was actually the current share count on each date.

    Two traps, both found in the data rather than anticipated.

    A filing routinely restates *prior* periods: Airbnb's FY2021 10-K carries
    FY2019 weighted-average shares as a comparative, filed 787 days after that
    period ended. Taking the most recently *filed* row would therefore pick a
    three-year-old share count as the current one. The frontier rule instead
    keeps only filings that advance the latest period end, so at any date the
    answer is the most recent period that had been published by then. This
    stays point-in-time — only ``filed_date <= t`` rows are ever considered.

    A handful of pre-2013 cover pages carry an ``end`` date after their own
    filing date, which is impossible; Adobe's 2010 10-K is off by five months.
    Those are dropped as filer tagging errors. All of them predate this panel.
    """

    # Newest period first *within* a filing, so a comparative loses to the
    # current figure it is filed alongside rather than being kept as the first
    # row it happens to precede.
    ordered = frame.sort_values(
        ["symbol", "filed_date", "end_date"], ascending=[True, True, False]
    ).copy()
    lag = (ordered["filed_date"] - ordered["end_date"]).dt.days
    ordered = ordered.loc[lag >= 0]

    frontier = ordered.groupby("symbol", sort=False)["end_date"].cummax()
    return ordered.loc[ordered["end_date"] >= frontier].reset_index(drop=True)


class TransientSECFailure(RuntimeError):
    """Raised on a refused request so acquisition stops rather than looping."""

    def __init__(self, symbol: str) -> None:
        super().__init__(f"SEC refused the request for {symbol}")
        self.symbol = symbol


def acquire(
    symbols: list[str],
    *,
    raw_dir: Path = DEFAULT_SEC_DIR,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    keep_going: bool = False,
) -> dict[str, Any]:
    """Fetch every symbol, stopping on the first refusal unless told otherwise.

    Resumable: cached symbols cost no request, so a stopped run continues from
    where it left off.
    """

    raw_dir.mkdir(parents=True, exist_ok=True)
    ticker_map = fetch_ticker_map(raw_dir=raw_dir)

    frames: list[pd.DataFrame] = []
    unmapped: list[str] = []
    no_concept: list[str] = []
    stopped_at: str | None = None

    for symbol in symbols:
        cik = CIK_OVERRIDES.get(symbol, ticker_map.get(to_sec_ticker(symbol)))
        if cik is None:
            unmapped.append(symbol)
            continue
        try:
            frame = fetch_shares_outstanding(symbol, cik, raw_dir=raw_dir)
        except TransientSECFailure:
            stopped_at = symbol
            if not keep_going:
                break
            continue
        if frame.empty:
            no_concept.append(symbol)
        else:
            frames.append(frame)

    combined = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(
            columns=[
                "symbol",
                "end_date",
                "filed_date",
                "shares_outstanding",
                "form",
                "accn",
            ]
        )
    )
    # One filing can restate an earlier period; the latest filing wins, which is
    # also what a reader at that date would have seen.
    combined = combined.sort_values(
        ["symbol", "end_date", "period_days", "filed_date"]
    )
    combined = combined.drop_duplicates(
        subset=["symbol", "end_date"], keep="first"
    ).reset_index(drop=True)

    processed_dir.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(processed_dir / "sec_shares_outstanding.parquet", index=False)

    report = {
        "symbols_requested": len(symbols),
        "symbols_with_data": int(combined["symbol"].nunique()),
        "observations": int(len(combined)),
        "unmapped_tickers": unmapped,
        "tickers_without_the_concept": no_concept,
        "stopped_early": stopped_at is not None,
        "stopped_at": stopped_at,
        "note": (
            "Stopped on the first refusal by design. Re-run the same command; "
            "cached symbols cost no request."
        )
        if stopped_at
        else "Complete.",
    }
    write_json(DEFAULT_OUTPUT_DIR / "sec_acquisition_report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="continue past a refused request instead of stopping",
    )
    parser.add_argument("--limit", type=int, default=None, help="first N symbols only")
    args = parser.parse_args()

    prices = pd.read_parquet(DEFAULT_PROCESSED_DIR / "universe_prices.parquet")
    symbols = sorted(prices["symbol"].unique())
    if args.limit:
        symbols = symbols[: args.limit]

    report = acquire(symbols, keep_going=args.keep_going)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
