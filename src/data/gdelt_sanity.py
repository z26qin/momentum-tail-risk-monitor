"""Semantic sanity check: do the frozen queries actually match market coverage?

This is a descriptive check, not a fitted one. Nothing in this project is
trained against labels, so a query may be corrected once if it is plainly
off-target — matching sports, entertainment, or unrelated politics. The
constraint is honest documentation of any change, not freezing.

The share-market-relevant figure below is a keyword heuristic and is reported
as such. The article titles themselves are written out in full so the number
never has to be taken on trust.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from src.data.gdelt import MECHANISM_QUERIES, SANITY_WINDOWS, fetch_article_sample
from src.utils.io import DEFAULT_OUTPUT_DIR, DEFAULT_RAW_DIR, write_json


#: Vocabulary that marks a headline as financial-market coverage. Deliberately
#: broader than the query terms so the check is not circular.
MARKET_VOCABULARY = re.compile(
    r"\b(stock|stocks|share|shares|equit\w*|market|markets|investor\w*|"
    r"trading|trader\w*|wall street|nasdaq|dow|s&p|index|indices|bond\w*|"
    r"yield\w*|fed|federal reserve|central bank|rate|rates|inflation|"
    r"earnings|dividend\w*|portfolio|fund|funds|hedge|sell-?off|rally|"
    r"bull|bear|volatilit\w*|nyse|ftse|nikkei|futures|etf|ipo|"
    r"economy|economic|recession|treasury|currenc\w*|dollar)\b",
    re.IGNORECASE,
)

#: Domains that are plainly off-target for a market query.
OFF_TARGET_HINT = re.compile(
    r"\b(football|soccer|basketball|cricket|nba|nfl|celebrit\w*|movie|film|"
    r"album|singer|actor|actress|recipe|horoscope|wedding|divorce)\b",
    re.IGNORECASE,
)

#: Below this share of market-relevant titles a query is flagged low-precision.
PRECISION_THRESHOLD = 0.60


def assess_titles(titles: list[str]) -> dict[str, Any]:
    """Score one sample of headlines for market relevance."""

    if not titles:
        return {
            "sampled": 0,
            "market_relevant": 0,
            "off_target": 0,
            "market_relevant_share": None,
        }
    relevant = [title for title in titles if MARKET_VOCABULARY.search(title)]
    off_target = [title for title in titles if OFF_TARGET_HINT.search(title)]
    return {
        "sampled": len(titles),
        "market_relevant": len(relevant),
        "off_target": len(off_target),
        "market_relevant_share": round(len(relevant) / len(titles), 3),
    }


def run_sanity_check(
    *,
    raw_dir: Path = DEFAULT_RAW_DIR / "gdelt",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    """Sample article titles per query per window and score them."""

    results: dict[str, Any] = {"windows": [list(window) for window in SANITY_WINDOWS]}
    per_query: dict[str, Any] = {}

    for key, query in MECHANISM_QUERIES.items():
        titles: list[str] = []
        samples: dict[str, list[dict[str, str]]] = {}
        for window in SANITY_WINDOWS:
            articles = fetch_article_sample(
                query_key=key, query=query, window=window, raw_dir=raw_dir
            )
            samples[f"{window[0]}..{window[1]}"] = articles
            titles.extend(article["title"] for article in articles if article["title"])

        assessment = assess_titles(titles)
        share = assessment["market_relevant_share"]
        if share is None:
            flag = "unassessed_no_articles"
        elif share >= PRECISION_THRESHOLD:
            flag = "market_relevant"
        else:
            flag = "low_precision"
        per_query[key] = {
            "query": query,
            "assessment": assessment,
            "precision_flag": flag,
            "samples": samples,
        }

    results["per_query"] = per_query
    results["precision_flags"] = {
        key: value["precision_flag"] for key, value in per_query.items()
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "narrative_sanity_check.json", results)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR / "gdelt")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    results = run_sanity_check(raw_dir=args.raw_dir, output_dir=args.output_dir)
    for key, entry in results["per_query"].items():
        print(f"\n=== {key} ({entry['precision_flag']}) ===")
        print(json.dumps(entry["assessment"], indent=2))
        for window, articles in entry["samples"].items():
            print(f"  -- {window}")
            for article in articles[:20]:
                print(f"     [{article['domain']}] {article['title'][:110]}")


if __name__ == "__main__":
    main()
