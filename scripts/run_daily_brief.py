"""Post-close daily brief: stdout is only [SILENT] or the WhatsApp alert.

Example:

    python scripts/run_daily_brief.py
    python scripts/run_daily_brief.py --demo
    python scripts/run_daily_brief.py --as-of-date 2026-05-29 --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mvp.daily_brief import run_daily_brief
from src.mvp.hermes_monitor import (
    DEFAULT_ASSESSMENT_PATH,
    DEFAULT_COMPARISON_PATH,
    DEFAULT_PREVIOUS_PATH,
    MissingCachedDataError,
)
from src.utils.io import REPO_ROOT


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "After the 16:00 ET close, run the existing monitor and print "
            "either [SILENT] or the two-message WhatsApp alert. Numeric "
            "drift inside the same severity band is not an alert."
        )
    )
    parser.add_argument(
        "--as-of-date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Override the assessment date (wins over --demo and last close)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use the frozen 2026-05-29 case instead of the last US close",
    )
    parser.add_argument(
        "--compare-to-date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Optional prior date for scorecard deltas",
    )
    parser.add_argument(
        "--evidence-cutoff",
        default=None,
        help='Display cutoff; must match the repository 16:00 ET close',
    )
    parser.add_argument(
        "--horizon-days",
        type=int,
        choices=(5, 20),
        default=20,
    )
    parser.add_argument(
        "--output-json",
        default=str(DEFAULT_ASSESSMENT_PATH.relative_to(REPO_ROOT)),
        help="Path for the compact JSON result",
    )
    parser.add_argument(
        "--previous",
        default=str(DEFAULT_PREVIOUS_PATH.relative_to(REPO_ROOT)),
        help="Previous runtime-state JSON",
    )
    parser.add_argument(
        "--comparison-json",
        default=str(DEFAULT_COMPARISON_PATH.relative_to(REPO_ROOT)),
        help="Path for the comparison JSON",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not promote the current assessment into runtime state",
    )
    return parser


def _resolve(path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def main() -> int:
    args = _build_parser().parse_args()
    try:
        result = run_daily_brief(
            as_of_date=args.as_of_date,
            demo=args.demo,
            evidence_cutoff=args.evidence_cutoff,
            compare_to_date=args.compare_to_date,
            horizon_days=args.horizon_days,
            update_previous=not args.dry_run,
            assessment_path=_resolve(args.output_json),
            previous_path=_resolve(args.previous),
            comparison_path=_resolve(args.comparison_json),
        )
    except MissingCachedDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(result.text)
    print(
        (
            f"# daily_brief as_of={result.as_of_date} "
            f"silent={str(result.silent).lower()} "
            f"baseline={str(result.is_baseline).lower()} "
            f"score={result.assessment.get('monitoring_severity_score')}/100 "
            f"{result.assessment.get('severity_emoji') or ''} "
            f"driver={result.assessment.get('primary_driver')} "
            f"triggers={result.assessment.get('deterministic_trigger_count')} "
            f"band={result.assessment.get('score_label')}"
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
