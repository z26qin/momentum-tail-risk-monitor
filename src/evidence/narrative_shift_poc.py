"""Isolated exploratory POC: public narrative shift around the frozen case.

Does not feed the deterministic scorecard, portfolio construction, market-regime
logic, or frozen evidence records.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.evidence.deepseek_responses import (
    DeepSeekResponsesError,
    api_key_is_present,
    create_web_search_response,
    resolve_responses_model,
)
from src.mvp.config import HISTORICAL_EXAMPLE_DATE
from src.utils.io import REPO_ROOT, atomic_write_bytes, utc_now_iso, write_json

# Frozen current-semi-unwind dates. Do not change the repository case cutoff.
FROZEN_CASE_CUTOFF = HISTORICAL_EXAMPLE_DATE  # 2026-05-29
FROZEN_COMPARISON_DATE = "2026-04-30"
PROMPT_PATH = REPO_ROOT / "prompts" / "narrative_shift_poc.txt"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "narrative_shift_poc"
REPORT_FILENAME = "narrative_shift_poc.md"
METADATA_FILENAME = "narrative_shift_poc_metadata.json"
PLACEHOLDER_PATTERN = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")
POC_LIMITATIONS = [
    "Exploratory POC only",
    "General web search is not a complete social-media dataset",
    "No statistical validation",
    "No inference of institutional positioning",
]
SYSTEM_INSTRUCTIONS = """You are a careful quantitative research assistant.

Use server-side web search to retrieve source-backed evidence.

Prioritize traceability and conservative interpretation over producing a strong conclusion.

Never invent sources, URLs, dates, quotes, statistics, or platform coverage.

Separate retrieved facts, source claims, and your own inference.

This is an exploratory narrative-shift POC, not a validated sentiment model."""


class OutputExistsError(DeepSeekResponsesError):
    """Raised when the POC output files already exist and overwrite is off."""


@dataclass(frozen=True)
class NarrativeShiftCase:
    case_name: str
    theme: str
    entities: tuple[str, ...]
    baseline_start: str
    baseline_end: str
    recent_start: str
    recent_end: str
    case_cutoff: str


# Dates and names from the frozen 2026-05-29 current-semi-unwind pack.
DEFAULT_CASE = NarrativeShiftCase(
    case_name="Frozen 2026-05-29 current-semi-unwind",
    theme="AI infrastructure and semiconductor momentum",
    entities=(
        "NVIDIA Corporation",
        "Taiwan Semiconductor Manufacturing Company (TSMC)",
        "Applied Materials",
        "Lam Research",
        "Ciena Corporation",
        "Coherent Corp.",
        "Lumentum Holdings",
        "Microsoft",
        "Meta Platforms",
        "Amazon.com",
        "Cisco Systems",
        "Arista Networks",
    ),
    baseline_start="2026-04-01",
    baseline_end=FROZEN_COMPARISON_DATE,
    recent_start="2026-05-01",
    recent_end=FROZEN_CASE_CUTOFF,
    case_cutoff=FROZEN_CASE_CUTOFF,
)


def load_user_prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def prompt_values(case: NarrativeShiftCase) -> dict[str, str]:
    return {
        "case_name": case.case_name,
        "theme": case.theme,
        "entities": "\n".join(f"- {name}" for name in case.entities),
        "baseline_start": case.baseline_start,
        "baseline_end": case.baseline_end,
        "recent_start": case.recent_start,
        "recent_end": case.recent_end,
        "case_cutoff": case.case_cutoff,
    }


def unresolved_placeholders(text: str) -> list[str]:
    return PLACEHOLDER_PATTERN.findall(text)


def render_user_prompt(case: NarrativeShiftCase | None = None) -> str:
    selected = DEFAULT_CASE if case is None else case
    filled = load_user_prompt_template().format(**prompt_values(selected))
    leftover = unresolved_placeholders(filled)
    if leftover:
        raise ValueError(f"Unresolved prompt placeholders remain: {leftover}")
    return filled


def output_paths(output_dir: Path) -> tuple[Path, Path]:
    return output_dir / REPORT_FILENAME, output_dir / METADATA_FILENAME


def build_metadata(
    case: NarrativeShiftCase,
    *,
    model: str,
    usage: Mapping[str, Any] | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    return {
        "case_name": case.case_name,
        "theme": case.theme,
        "baseline_window": {"start": case.baseline_start, "end": case.baseline_end},
        "recent_window": {"start": case.recent_start, "end": case.recent_end},
        "case_cutoff": case.case_cutoff,
        "model": model,
        "api": "DeepSeek Responses API",
        "web_search_enabled": True,
        "generated_at_utc": generated_at_utc or utc_now_iso(),
        "usage": dict(usage or {}),
        "limitations": list(POC_LIMITATIONS),
    }


def dry_run_summary(
    case: NarrativeShiftCase | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    load_dotenv: bool = True,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    selected = DEFAULT_CASE if case is None else case
    prompt = render_user_prompt(selected)
    report_path, metadata_path = output_paths(output_dir or DEFAULT_OUTPUT_DIR)
    return {
        "dry_run": True,
        "model": resolve_responses_model(environment),
        "case_name": selected.case_name,
        "theme": selected.theme,
        "entities": list(selected.entities),
        "baseline_start": selected.baseline_start,
        "baseline_end": selected.baseline_end,
        "recent_start": selected.recent_start,
        "recent_end": selected.recent_end,
        "case_cutoff": selected.case_cutoff,
        "api_key_present": api_key_is_present(environment, load_dotenv=load_dotenv),
        "approximate_prompt_length": len(prompt),
        "output_report": str(report_path),
        "output_metadata": str(metadata_path),
    }


def format_dry_run(summary: Mapping[str, Any]) -> str:
    entities = ", ".join(str(item) for item in summary["entities"])
    present = "yes" if summary["api_key_present"] else "no"
    return "\n".join(
        [
            "Narrative-shift POC dry run (no API call)",
            f"model: {summary['model']}",
            f"case_name: {summary['case_name']}",
            f"theme: {summary['theme']}",
            f"entities: {entities}",
            f"baseline_window: {summary['baseline_start']} through {summary['baseline_end']}",
            f"recent_window: {summary['recent_start']} through {summary['recent_end']}",
            f"case_cutoff: {summary['case_cutoff']}",
            f"api_key_present: {present}",
            f"approximate_prompt_length: {summary['approximate_prompt_length']}",
        ]
    )


def _ensure_output_available(paths: Sequence[Path], *, overwrite: bool) -> None:
    existing = [path for path in paths if path.exists()]
    if existing and not overwrite:
        raise OutputExistsError(
            "Output already exists: "
            f"{', '.join(str(path) for path in existing)}. "
            "Pass --overwrite to replace it."
        )


def write_poc_outputs(
    *,
    output_dir: Path,
    markdown: str,
    metadata: Mapping[str, Any],
    overwrite: bool = False,
) -> tuple[Path, Path]:
    report_path, metadata_path = output_paths(output_dir)
    _ensure_output_available((report_path, metadata_path), overwrite=overwrite)
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(report_path, markdown.encode("utf-8"))
    write_json(metadata_path, dict(metadata))
    return report_path, metadata_path


def run_narrative_shift_poc(
    *,
    case: NarrativeShiftCase | None = None,
    output_dir: Path | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
    environment: Mapping[str, str] | None = None,
    load_dotenv: bool = True,
    client: Any | None = None,
) -> dict[str, Any]:
    selected = DEFAULT_CASE if case is None else case
    target_dir = output_dir or DEFAULT_OUTPUT_DIR
    if dry_run:
        return dry_run_summary(
            selected,
            environment=environment,
            load_dotenv=load_dotenv,
            output_dir=target_dir,
        )

    report_path, metadata_path = output_paths(target_dir)
    _ensure_output_available((report_path, metadata_path), overwrite=overwrite)
    result = create_web_search_response(
        instructions=SYSTEM_INSTRUCTIONS,
        input_text=render_user_prompt(selected),
        environment=environment,
        load_dotenv=load_dotenv,
        client=client,
    )
    written_report, written_metadata = write_poc_outputs(
        output_dir=target_dir,
        markdown=result.output_text,
        metadata=build_metadata(selected, model=result.model, usage=result.usage),
        overwrite=overwrite,
    )
    return {
        "dry_run": False,
        "report_path": str(written_report),
        "metadata_path": str(written_metadata),
        "model": result.model,
        "status": result.status,
    }
