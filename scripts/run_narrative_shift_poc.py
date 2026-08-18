"""CLI for the isolated public narrative-shift POC.

Example:

    python scripts/run_narrative_shift_poc.py --dry-run
    python scripts/run_narrative_shift_poc.py --overwrite
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evidence.deepseek_responses import DeepSeekResponsesError
from src.evidence.narrative_shift_poc import (
    DEFAULT_OUTPUT_DIR,
    format_dry_run,
    run_narrative_shift_poc,
)
from src.utils.io import REPO_ROOT


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Exploratory DeepSeek Responses API proof of concept for a public "
            "narrative shift around the frozen 2026-05-29 momentum-unwind case. "
            "Does not update the deterministic scorecard."
        )
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR.relative_to(REPO_ROOT)),
        help="Directory for the Markdown report and metadata JSON",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing narrative_shift_poc.md / metadata JSON",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned call without contacting the API",
    )
    return parser


def _resolve_output_dir(path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _display_path(path: Path) -> Path:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return path


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    output_dir = _resolve_output_dir(args.output_dir)
    try:
        result = run_narrative_shift_poc(
            output_dir=output_dir,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
        )
    except DeepSeekResponsesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if result.get("dry_run"):
        print(format_dry_run(result))
        return 0

    report = _display_path(Path(str(result["report_path"])))
    metadata = _display_path(Path(str(result["metadata_path"])))
    print(f"wrote {report}")
    print(f"wrote {metadata}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
