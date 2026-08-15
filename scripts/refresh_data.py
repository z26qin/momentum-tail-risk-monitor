"""Download Ken French, VIX, and S&P/SPY prices, then rebuild the 12-1 book.

Default action is a live download (not a vintage listing). Does not invent
UMD or make run_mvp work past the last Ken French date.

Example:

    python scripts/refresh_data.py --as-of-date 2026-07-30
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.refresh import format_refresh_report, refresh_data


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download Ken French, VIX, and S&P/SPY prices, then rebuild the "
            "12-1 book. Default is a live download. If French is still short "
            "of the requested date after download, exit 2. Does not change "
            "run_mvp or invent UMD."
        )
    )
    parser.add_argument(
        "--as-of-date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Target date (default: last completed 16:00 ET close)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect existing panels only; skip download (not the default)",
    )
    parser.add_argument(
        "--cached",
        action="store_true",
        help="Rebuild book panels from disk without downloading",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    vintages = refresh_data(
        as_of_date=args.as_of_date,
        dry_run=args.dry_run,
        cached=args.cached,
    )
    print(format_refresh_report(vintages))
    if vintages.french_stale:
        return 2
    failed = [step for step in vintages.steps if not step.ok]
    if failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
