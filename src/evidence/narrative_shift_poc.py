"""Isolated exploratory POC: public narrative shift around the frozen case.

This module does not feed the deterministic scorecard, portfolio construction,
market-regime logic, or frozen evidence records. It only prepares a prompt and
optionally calls the DeepSeek Responses API with server-side web search.
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

# Frozen current-semi-unwind dates from
# data/evaluation/current_semi_unwind/evidence_protocol.json and
# structured_snapshot.json. Do not change the repository case cutoff.
FROZEN_CASE_CUTOFF = HISTORICAL_EXAMPLE_DATE  # 2026-05-29
FROZEN_COMPARISON_DATE = "2026-04-30"

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

USER_PROMPT_TEMPLATE = """You are assisting a quantitative researcher evaluating whether the publicly retrievable narrative around a momentum theme changed across two fixed time windows.

Use web search.

This is an exploratory proof of concept, not a validated social-media factor.

CASE

Case name:
{case_name}

Theme:
{theme}

Relevant companies and entities:
{entities}

Baseline window:
{baseline_start} through {baseline_end}

Recent window:
{recent_start} through {recent_end}

Historical case cutoff:
{case_cutoff}

RESEARCH QUESTION

Did the publicly retrievable narrative around this momentum theme materially change between the baseline and recent windows?

Search for evidence from:

- financial media;
- company statements and investor-relations material;
- research commentary;
- publicly indexed Reddit pages;
- publicly indexed X posts;
- StockTwits or investor forums where available.

General web search does not provide complete or representative platform coverage. Treat social-media results only as publicly retrievable narrative evidence.

ANALYTICAL DIMENSIONS

Evaluate changes in:

1. Fundamental optimism
   - demand durability;
   - earnings or guidance strength;
   - capacity constraints;
   - AI or industry capital-expenditure support.

2. Fundamental skepticism
   - demand slowdown;
   - capital-expenditure discipline;
   - return-on-investment concerns;
   - earnings disappointment;
   - reduced spending expectations.

3. Valuation and crowding language
   - stretched valuation;
   - consensus trade;
   - crowded positioning;
   - profit-taking;
   - hedge-fund selling;
   - deleveraging claims.

4. Public investor narrative
   - dominant bullish thesis;
   - dominant bearish thesis;
   - concentration around one shared thesis;
   - disagreement, skepticism, or narrative reversal.

5. Contradicting evidence
   - evidence that challenges the dominant recent interpretation.

METHOD

Search the baseline and recent windows separately before comparing them.

For every important claim:

- provide the source title;
- provide the source URL;
- provide the publication date when available;
- identify the source type;
- distinguish a direct source claim from your own inference;
- exclude evidence clearly published after the historical case cutoff;
- flag uncertain publication dates.

Do not:

- use search-result counts as mention volume;
- claim complete Reddit, X, or StockTwits coverage;
- claim representative investor sentiment;
- infer institutional crowding from public discussion alone;
- describe forced deleveraging as confirmed without direct credible evidence;
- calculate a crash probability;
- make a trade recommendation;
- invent sources, quotes, dates, engagement figures, or statistics.

OUTPUT

# Public Narrative Shift POC

## Executive read

Write a conservative PM-facing assessment in no more than five sentences.

Classify the overall evidence as one of:

- no clear shift;
- limited shift;
- moderate shift;
- meaningful shift;
- mixed or contested shift;
- insufficient evidence.

## Baseline narrative

Summarize the principal narratives in the baseline window.

## Recent narrative

Summarize the principal narratives in the recent window.

## Narrative changes

Use this table:

| Narrative | Baseline state | Recent state | Change | Evidence strength |
|---|---|---|---|---|

Use one of these change classifications:

- emerging;
- strengthening;
- stable;
- weakening;
- reversing;
- contested;
- insufficient evidence.

## Supporting evidence

List the strongest evidence suggesting that the narrative changed.

For every item include:

- title;
- date;
- source type;
- URL;
- direct claim;
- interpretation.

## Contradicting evidence

List evidence that challenges or weakens the shift interpretation.

## What is supported

State only conclusions directly supported by the retrieved evidence.

## What is not supported

Explicitly address whether the evidence fails to establish:

- complete social-media attention;
- representative investor sentiment;
- institutional position overlap;
- forced deleveraging;
- momentum-crash probability;
- causal or predictive value.

## Research interpretation

Explain briefly how this narrative-shift lens could complement:

- market regime;
- portfolio behavior;
- long-versus-short leg attribution;
- positioning evidence.

Treat it as a secondary confirmation layer, not a standalone risk signal.

## Smallest next validation step

Suggest the smallest credible study needed to assess whether the signal adds incremental value.
"""


class OutputExistsError(DeepSeekResponsesError):
    """Raised when the POC output files already exist and overwrite is off."""


@dataclass(frozen=True)
class NarrativeShiftCase:
    """Editable case configuration for the narrative-shift POC."""

    case_name: str
    theme: str
    entities: tuple[str, ...]
    baseline_start: str
    baseline_end: str
    recent_start: str
    recent_end: str
    case_cutoff: str


# Dates and names come from the frozen 2026-05-29 current-semi-unwind pack.
# Cluster names: structured_snapshot.json CIEN–COHR–LITE.
# Operating / capex names: candidate_evidence.json.
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


def format_entities(entities: Sequence[str]) -> str:
    """Render entity names as a prompt list using full company names."""

    return "\n".join(f"- {name}" for name in entities)


def prompt_values(case: NarrativeShiftCase) -> dict[str, str]:
    """Return the substitution map used to fill the user prompt."""

    return {
        "case_name": case.case_name,
        "theme": case.theme,
        "entities": format_entities(case.entities),
        "baseline_start": case.baseline_start,
        "baseline_end": case.baseline_end,
        "recent_start": case.recent_start,
        "recent_end": case.recent_end,
        "case_cutoff": case.case_cutoff,
    }


def unresolved_placeholders(text: str) -> list[str]:
    """Return leftover ``{placeholder}`` tokens, if any."""

    return PLACEHOLDER_PATTERN.findall(text)


def render_user_prompt(case: NarrativeShiftCase | None = None) -> str:
    """Fill the narrative-shift prompt from the case configuration."""

    selected = DEFAULT_CASE if case is None else case
    filled = USER_PROMPT_TEMPLATE.format(**prompt_values(selected))
    leftover = unresolved_placeholders(filled)
    if leftover:
        raise ValueError(f"Unresolved prompt placeholders remain: {leftover}")
    return filled


def output_paths(output_dir: Path) -> tuple[Path, Path]:
    """Return the Markdown report path and metadata JSON path."""

    return output_dir / REPORT_FILENAME, output_dir / METADATA_FILENAME


def build_metadata(
    case: NarrativeShiftCase,
    *,
    model: str,
    usage: Mapping[str, Any] | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build the small POC metadata payload."""

    return {
        "case_name": case.case_name,
        "theme": case.theme,
        "baseline_window": {
            "start": case.baseline_start,
            "end": case.baseline_end,
        },
        "recent_window": {
            "start": case.recent_start,
            "end": case.recent_end,
        },
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
    """Describe the planned call without contacting the API."""

    selected = DEFAULT_CASE if case is None else case
    prompt = render_user_prompt(selected)
    model = resolve_responses_model(environment)
    report_path, metadata_path = output_paths(output_dir or DEFAULT_OUTPUT_DIR)
    return {
        "dry_run": True,
        "model": model,
        "case_name": selected.case_name,
        "theme": selected.theme,
        "entities": list(selected.entities),
        "baseline_start": selected.baseline_start,
        "baseline_end": selected.baseline_end,
        "recent_start": selected.recent_start,
        "recent_end": selected.recent_end,
        "case_cutoff": selected.case_cutoff,
        "api_key_present": api_key_is_present(
            environment, load_dotenv=load_dotenv
        ),
        "approximate_prompt_length": len(prompt),
        "output_report": str(report_path),
        "output_metadata": str(metadata_path),
    }


def format_dry_run(summary: Mapping[str, Any]) -> str:
    """Render a dry-run summary for the CLI."""

    entities = ", ".join(str(item) for item in summary["entities"])
    present = "yes" if summary["api_key_present"] else "no"
    return "\n".join(
        [
            "Narrative-shift POC dry run (no API call)",
            f"model: {summary['model']}",
            f"case_name: {summary['case_name']}",
            f"theme: {summary['theme']}",
            f"entities: {entities}",
            (
                f"baseline_window: {summary['baseline_start']} through "
                f"{summary['baseline_end']}"
            ),
            (
                f"recent_window: {summary['recent_start']} through "
                f"{summary['recent_end']}"
            ),
            f"case_cutoff: {summary['case_cutoff']}",
            f"api_key_present: {present}",
            f"approximate_prompt_length: {summary['approximate_prompt_length']}",
        ]
    )


def _ensure_output_available(paths: Sequence[Path], *, overwrite: bool) -> None:
    existing = [path for path in paths if path.exists()]
    if existing and not overwrite:
        relative = ", ".join(str(path) for path in existing)
        raise OutputExistsError(
            "Output already exists: "
            f"{relative}. Pass --overwrite to replace it."
        )


def write_poc_outputs(
    *,
    output_dir: Path,
    markdown: str,
    metadata: Mapping[str, Any],
    overwrite: bool = False,
) -> tuple[Path, Path]:
    """Write the Markdown report and metadata JSON."""

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
    """Run the isolated narrative-shift POC or print a dry-run plan."""

    selected = DEFAULT_CASE if case is None else case
    target_dir = output_dir or DEFAULT_OUTPUT_DIR
    if dry_run:
        return dry_run_summary(
            selected,
            environment=environment,
            load_dotenv=load_dotenv,
            output_dir=target_dir,
        )

    prompt = render_user_prompt(selected)
    report_path, metadata_path = output_paths(target_dir)
    _ensure_output_available((report_path, metadata_path), overwrite=overwrite)
    result = create_web_search_response(
        instructions=SYSTEM_INSTRUCTIONS,
        input_text=prompt,
        environment=environment,
        load_dotenv=load_dotenv,
        client=client,
    )
    metadata = build_metadata(selected, model=result.model, usage=result.usage)
    written_report, written_metadata = write_poc_outputs(
        output_dir=target_dir,
        markdown=result.output_text,
        metadata=metadata,
        overwrite=overwrite,
    )
    return {
        "dry_run": False,
        "report_path": str(written_report),
        "metadata_path": str(written_metadata),
        "model": result.model,
        "status": result.status,
    }
