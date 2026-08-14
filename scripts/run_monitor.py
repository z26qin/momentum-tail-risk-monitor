"""CLI adapter: run the existing deterministic momentum monitor as compact JSON.

Example:

    python scripts/run_monitor.py \\
      --as-of-date 2026-05-29 \\
      --evidence-cutoff "2026-05-29 16:00 ET" \\
      --output-json outputs/latest_assessment.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mvp.config import HISTORICAL_EXAMPLE_DATE
from src.mvp.hermes_monitor import (
    DEFAULT_ASSESSMENT_PATH,
    MissingCachedDataError,
    default_compare_to_date,
    dumps,
    require_cached_inputs,
    run_compact_assessment,
    save_assessment,
)
from src.utils.io import REPO_ROOT


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the existing deterministic momentum tail-risk monitor and "
            "write a compact JSON assessment. Does not recalculate signals "
            "or override triggers."
        )
    )
    parser.add_argument(
        "--as-of-date",
        default=HISTORICAL_EXAMPLE_DATE,
        metavar="YYYY-MM-DD",
        help="Assessment date (default: frozen primary case 2026-05-29)",
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
        help='Display cutoff; must match the repository 16:00 ET close, e.g. "2026-05-29 16:00 ET"',
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
    return parser


def _resolve_output(path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def main() -> int:
    args = _build_parser().parse_args()
    try:
        require_cached_inputs()
        compare_to = args.compare_to_date or default_compare_to_date(args.as_of_date)
        assessment = run_compact_assessment(
            as_of_date=args.as_of_date,
            compare_to_date=compare_to,
            evidence_cutoff=args.evidence_cutoff,
            horizon_days=args.horizon_days,
        )
    except MissingCachedDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output_path = _resolve_output(args.output_json)
    save_assessment(output_path, assessment)
    try:
        relative = output_path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        relative = output_path
    print(dumps(assessment), end="")
    print(
        (
            f"# wrote {relative} | as_of={assessment['as_of_date']} "
            f"posture={assessment['pm_posture']} "
            f"score={assessment.get('monitoring_severity_score')}/100 "
            f"{assessment.get('severity_emoji') or ''} "
            f"driver={assessment.get('primary_driver')} "
            f"triggers={assessment['deterministic_trigger_count']} "
            f"flags={assessment['structural_flags']}"
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
