"""Compare the latest monitor assessment with the previous runtime state.

Example:

    python scripts/compare_monitor_state.py \\
      --current outputs/latest_assessment.json \\
      --previous runtime_state/previous_assessment.json \\
      --output-json outputs/latest_comparison.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mvp.hermes_monitor import (
    DEFAULT_ASSESSMENT_PATH,
    DEFAULT_COMPARISON_PATH,
    DEFAULT_PREVIOUS_PATH,
    compare_assessments,
    dumps,
    format_whatsapp_alert,
    load_previous_assessment,
    save_assessment,
)
from src.utils.io import REPO_ROOT, read_json


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare compact monitor JSON with the previous run. Unchanged "
            "discrete state prints [SILENT]. Numeric drift is ignored."
        )
    )
    parser.add_argument(
        "--current",
        default=str(DEFAULT_ASSESSMENT_PATH.relative_to(REPO_ROOT)),
        help="Current compact assessment JSON",
    )
    parser.add_argument(
        "--previous",
        default=str(DEFAULT_PREVIOUS_PATH.relative_to(REPO_ROOT)),
        help="Previous runtime-state JSON",
    )
    parser.add_argument(
        "--output-json",
        default=str(DEFAULT_COMPARISON_PATH.relative_to(REPO_ROOT)),
        help="Path for the comparison JSON",
    )
    parser.add_argument(
        "--no-update-previous",
        action="store_true",
        help="Do not promote the current assessment into runtime state",
    )
    parser.add_argument(
        "--draft-alert",
        action="store_true",
        help="If material, also print a WhatsApp-compatible draft alert",
    )
    return parser


def _resolve(path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def main() -> int:
    args = _build_parser().parse_args()
    current_path = _resolve(args.current)
    previous_path = _resolve(args.previous)
    output_path = _resolve(args.output_json)

    if not current_path.is_file():
        print(f"error: current assessment not found: {current_path}", file=sys.stderr)
        return 2
    current = read_json(current_path)
    if not isinstance(current, dict):
        print("error: current assessment is not a JSON object", file=sys.stderr)
        return 1

    try:
        previous = load_previous_assessment(previous_path)
        comparison = compare_assessments(current, previous)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    save_assessment(output_path, comparison)
    if not args.no_update_previous:
        save_assessment(previous_path, current)

    if comparison.get("silent"):
        print("[SILENT]")
        return 0

    print(dumps(comparison), end="")
    if args.draft_alert:
        print()
        print(format_whatsapp_alert(current, comparison))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
