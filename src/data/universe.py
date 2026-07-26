"""Fix the equity universe used to proxy the momentum loser leg.

The universe is defined once, before any other pull, and written to
``docs/universe.md`` with its source and retrieval date.

**Known bias, restated in every output built on this panel.** The list is
current index-eligible membership applied backwards over the whole sample, so
it carries survivorship bias: companies that were large in 2018 but have since
been acquired, delisted, or shrunk out of the top 200 never appear, and
companies that grew into the top 200 appear from the start. It is a labelled
proxy for the momentum loser leg, not a reconstruction of the true momentum
universe. Production would use CRSP/Compustat point-in-time constituents.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.symbols import to_canonical
from src.utils.http import cached_fetch
from src.utils.io import DEFAULT_RAW_DIR, REPO_ROOT, write_json


SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true"
SCREENER_SOURCE = "Nasdaq stock screener (api.nasdaq.com/api/screener/stocks)"
UNIVERSE_SIZE = 200

#: Minimum notional traded on the screener snapshot date, in USD.
#:
#: The spec asks for *liquid* large/mid caps, and market capitalisation alone
#: does not deliver that. The first build admitted ``CCZ`` (Comcast Holdings
#: ZONES, an exchangeable debenture) on a large notional market cap despite a
#: median daily volume of **zero shares**. With a 20-day average volume of 5
#: shares its days-to-cover was 120 against a leg median near 2.9, and that one
#: name moved the equal-weighted leg average from 2.9 to 8.8 — an 8.5-sigma
#: reading that was entirely an artifact.
#:
#: The threshold is deliberately far below any real constituent: the least
#: liquid genuine name in the universe trades about $60M a day, so a $5M floor
#: removes the artifact with three orders of magnitude of headroom and cannot
#: plausibly exclude a real large cap having a quiet session.
MINIMUM_DAILY_NOTIONAL_USD = 5_000_000.0

#: Instrument types that are not common stock and would corrupt a momentum
#: ranking or a short-interest join.
NON_COMMON_STOCK = re.compile(
    r"(warrant|\bunit(s)?\b|preferred|depositary|\bright(s)?\b|debenture|"
    r"\bnotes?\b|% Series|\bETF\b|\bFund\b|\bTrust\b\s*$)",
    re.IGNORECASE,
)


def _daily_notional(row: dict[str, Any]) -> float:
    """Traded notional on the screener snapshot date, used as a liquidity floor."""

    try:
        volume = float(str(row.get("volume") or 0).replace(",", ""))
        price = float(str(row.get("lastsale") or "0").replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return 0.0
    return volume * price


def _market_cap(row: dict[str, Any]) -> float:
    try:
        return float(row.get("marketCap") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def fetch_screener(raw_dir: Path, force: bool = False) -> dict[str, Any]:
    """Cache one full screener snapshot."""

    result = cached_fetch(
        cache_path=raw_dir / "nasdaq_screener.json",
        url=SCREENER_URL,
        source_key="nasdaq_screener",
        headers={"Accept": "application/json"},
        min_interval_seconds=0.5,
        force=force,
    )
    return {"payload": result.read_json(), "metadata": result.metadata}


def select_universe(payload: dict[str, Any], size: int = UNIVERSE_SIZE) -> pd.DataFrame:
    """Rank US-listed common stocks by market capitalisation and take the top ``size``."""

    rows = payload["data"]["rows"]
    candidates = []
    for row in rows:
        symbol = str(row.get("symbol", "")).strip().upper()
        name = str(row.get("name", ""))
        if not symbol or "^" in symbol:
            continue
        if row.get("country") != "United States":
            continue
        if NON_COMMON_STOCK.search(name):
            continue
        market_cap = _market_cap(row)
        if market_cap <= 0:
            continue
        if _daily_notional(row) < MINIMUM_DAILY_NOTIONAL_USD:
            continue
        candidates.append(
            {
                "symbol": to_canonical(symbol),
                "source_symbol": symbol,
                "name": name,
                "market_cap_usd": market_cap,
                "sector": row.get("sector") or "",
                "ipo_year": row.get("ipoyear") or "",
            }
        )

    frame = pd.DataFrame.from_records(candidates)
    frame = frame.drop_duplicates(subset="symbol", keep="first")
    frame = frame.sort_values("market_cap_usd", ascending=False).head(size)
    frame = frame.sort_values("symbol").reset_index(drop=True)
    frame["universe_rank"] = (
        frame["market_cap_usd"].rank(ascending=False, method="first").astype(int)
    )
    return frame


def write_universe_document(
    frame: pd.DataFrame,
    retrieval_timestamp: str,
    path: Path,
) -> None:
    """Write the human-readable universe definition."""

    ordered = frame.sort_values("universe_rank")
    tickers = ordered["symbol"].tolist()
    lines = [
        "# Proxy universe for the positioning panel",
        "",
        f"- **Source:** {SCREENER_SOURCE}",
        f"- **Retrieved (UTC):** {retrieval_timestamp}",
        f"- **Definition:** the {len(tickers)} largest US-domiciled, US-listed common "
        "stocks by market capitalisation on the retrieval date, after excluding "
        "warrants, units, preferred shares, depositary shares, rights, notes, and "
        "fund/trust vehicles by instrument name, and after requiring at least "
        f"${MINIMUM_DAILY_NOTIONAL_USD:,.0f} of traded notional on the snapshot date.",
        "- **Liquidity floor rationale:** market capitalisation alone admitted an "
        "exchangeable debenture trading zero shares a day, whose days-to-cover of "
        "120 moved the whole leg average. The floor sits three orders of magnitude "
        "below the least liquid genuine constituent.",
        f"- **Smallest member by market capitalisation:** "
        f"${ordered['market_cap_usd'].min() / 1e9:,.1f}B",
        f"- **Largest member:** ${ordered['market_cap_usd'].max() / 1e12:,.2f}T",
        "",
        "## Survivorship warning",
        "",
        "This list is **current membership applied historically**. Every output",
        "derived from it inherits survivorship bias:",
        "",
        "- Companies that were large during the sample but were later acquired,",
        "  delisted, or fell out of the top 200 are absent for the entire sample,",
        "  not just for the period after they left.",
        "- Companies that grew into the top 200 late in the sample are present from",
        "  the beginning, on the strength of information that did not exist then.",
        "- The screen is by market capitalisation, so the universe is large-cap",
        "  dominated. A real momentum loser decile contains far more mid- and",
        "  small-cap names, which are also the names where short-leg crowding is",
        "  most acute. The panel therefore understates crowding relative to a true",
        "  momentum universe.",
        "",
        "It is a labelled proxy for the momentum loser leg, not a reconstruction of",
        "it. Production would use CRSP/Compustat point-in-time index constituents.",
        "",
        "## Constituents",
        "",
        "| Rank | Symbol | Name | Sector | Market cap (USD bn) |",
        "|---:|---|---|---|---:|",
    ]
    for row in ordered.itertuples():
        lines.append(
            f"| {row.universe_rank} | `{row.symbol}` | {row.name} | "
            f"{row.sector or '—'} | {row.market_cap_usd / 1e9:,.1f} |"
        )
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build_universe(
    *,
    raw_dir: Path = DEFAULT_RAW_DIR / "positioning",
    docs_path: Path = REPO_ROOT / "docs" / "universe.md",
    processed_path: Path | None = None,
    size: int = UNIVERSE_SIZE,
    force: bool = False,
) -> pd.DataFrame:
    """Fetch, filter, rank, persist, and document the universe."""

    raw_dir.mkdir(parents=True, exist_ok=True)
    snapshot = fetch_screener(raw_dir, force=force)
    frame = select_universe(snapshot["payload"], size=size)
    retrieval = snapshot["metadata"].get("retrieval_timestamp_utc", "unknown")
    write_universe_document(frame, retrieval, docs_path)

    if processed_path is not None:
        processed_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(processed_path, index=False, engine="pyarrow")

    write_json(
        raw_dir / "universe_selection.json",
        {
            "source": SCREENER_SOURCE,
            "retrieval_timestamp_utc": retrieval,
            "requested_size": size,
            "selected": int(len(frame)),
            "symbols": frame.sort_values("universe_rank")["symbol"].tolist(),
            "screener_sha256": snapshot["metadata"].get("sha256"),
        },
    )
    return frame


def load_universe(raw_dir: Path = DEFAULT_RAW_DIR / "positioning") -> list[str]:
    """Read the frozen universe symbol list from the cache."""

    payload = json.loads((raw_dir / "universe_selection.json").read_text(encoding="utf-8"))
    return list(payload["symbols"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR / "positioning")
    parser.add_argument("--size", type=int, default=UNIVERSE_SIZE)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    frame = build_universe(raw_dir=args.raw_dir, size=args.size, force=args.force)
    print(
        json.dumps(
            {
                "selected": int(len(frame)),
                "first": frame.sort_values("universe_rank")["symbol"].head(10).tolist(),
                "smallest_market_cap_usd_bn": round(
                    float(frame["market_cap_usd"].min()) / 1e9, 1
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
