"""Post-close daily brief: stdout is only [SILENT], the WhatsApp alert, or a stale-data notice.

Example:

    python scripts/run_daily_brief.py
    python scripts/run_daily_brief.py --demo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mvp.daily_brief import StaleSessionError, run_daily_brief
from src.mvp.hermes_monitor import MissingCachedDataError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "After the 16:00 ET close, run the existing monitor and print "
            "either [SILENT] or the two-message WhatsApp alert. Numeric "
            "drift inside the same severity band is not an alert. Stale "
            "panels are not treated as a quiet day."
        )
    )
    parser.add_argument(
        "--as-of-date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Explicit assessment date (skips the live freshness check)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use the frozen 2026-05-29 case",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not promote the current assessment into runtime state",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        text, assessment, comparison = run_daily_brief(
            as_of_date=args.as_of_date,
            demo=args.demo,
            update_previous=not args.dry_run,
        )
    except StaleSessionError as exc:
        print(str(exc))
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except MissingCachedDataError as exc:
        print("Cached monitor data is missing. Not a daily brief.")
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError) as exc:
        print("Daily brief failed. Not a quiet day.")
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(text)
    print(
        (
            f"# daily_brief as_of={assessment.get('as_of_date')} "
            f"silent={str(comparison.get('silent')).lower()} "
            f"baseline={str(comparison.get('is_baseline')).lower()} "
            f"score={assessment.get('monitoring_severity_score')}/100 "
            f"{assessment.get('severity_emoji') or ''} "
            f"driver={assessment.get('primary_driver')} "
            f"triggers={assessment.get('deterministic_trigger_count')} "
            f"band={assessment.get('score_label')}"
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
