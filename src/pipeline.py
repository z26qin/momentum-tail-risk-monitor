"""Run the single active MVP assessment path and generate a PM brief."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.benchmarks.b2_shadow import build_b2_shadow
from src.evidence.mvp import (
    DEFAULT_ARCHIVED_CORPUS_PATH,
    build_evidence_snapshot,
)
from src.experiments.reversal_checklist import build_reversal_conditions
from src.mvp.contracts import SCHEMA_VERSION, MvpAssessment
from src.overlays.snapshots import (
    build_narrative_snapshot,
    build_positioning_snapshot,
)
from src.reporting.pm_brief import render_pm_brief
from src.risk.dm_engine import run_primary_assessment
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    atomic_write_bytes,
    parse_as_of_date,
    write_json,
)


def run_pipeline(
    *,
    as_of_date: pd.Timestamp,
    horizon: int = 20,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    evidence_provider: str = "fixture",
    archived_corpus_path: Path = DEFAULT_ARCHIVED_CORPUS_PATH,
    classifier_response_path: Path | None = None,
) -> tuple[MvpAssessment, Path, Path]:
    """Build every MVP component while preserving one primary risk number."""

    primary, _, _ = run_primary_assessment(
        as_of_date=as_of_date,
        horizon=horizon,
        processed_dir=processed_dir,
        output_dir=output_dir,
    )
    assessment = MvpAssessment(
        schema_version=SCHEMA_VERSION,
        primary=primary,
        shadow_benchmarks=(
            build_b2_shadow(primary=primary, output_dir=output_dir),
        ),
        experimental_conditions=build_reversal_conditions(
            as_of_date=as_of_date,
            processed_dir=processed_dir,
        ),
        positioning=build_positioning_snapshot(
            primary=primary,
            processed_dir=processed_dir,
        ),
        narrative=build_narrative_snapshot(
            primary=primary,
            processed_dir=processed_dir,
        ),
        evidence=build_evidence_snapshot(
            primary=primary,
            output_dir=output_dir,
            provider_mode=evidence_provider,
            archived_corpus_path=archived_corpus_path,
            classifier_response_path=classifier_response_path,
        ),
    )
    mvp_dir = output_dir / "mvp"
    assessment_path = (
        mvp_dir / f"assessment_{primary.as_of_date}_h{horizon}.json"
    )
    brief_path = mvp_dir / f"pm_brief_{primary.as_of_date}_h{horizon}.md"
    write_json(assessment_path, assessment.to_dict())
    atomic_write_bytes(
        brief_path,
        render_pm_brief(assessment).encode("utf-8"),
    )
    return assessment, assessment_path, brief_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--horizon", type=int, choices=(5, 20), default=20)
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--evidence-provider",
        choices=("fixture", "archived"),
        default="fixture",
    )
    parser.add_argument(
        "--archived-corpus",
        type=Path,
        default=DEFAULT_ARCHIVED_CORPUS_PATH,
    )
    parser.add_argument(
        "--classifier-response",
        type=Path,
        help=(
            "Validated cached response for archived retrieval. Without it, "
            "eligible documents remain retrieved_unclassified."
        ),
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    assessment, assessment_path, brief_path = run_pipeline(
        as_of_date=parse_as_of_date(args.as_of_date),
        horizon=args.horizon,
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
        evidence_provider=args.evidence_provider,
        archived_corpus_path=args.archived_corpus,
        classifier_response_path=args.classifier_response,
    )
    print(json.dumps(assessment.to_dict(), indent=2, sort_keys=True))
    print(f"Wrote {assessment_path}")
    print(f"Wrote {brief_path}")


if __name__ == "__main__":
    main()
