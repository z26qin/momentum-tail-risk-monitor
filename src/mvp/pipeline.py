"""Single orchestration boundary for the momentum tail-risk MVP.

This module composes existing deterministic calculations without reimplementing
them. It does not merge UMD macro context with the named S&P 500 proxy
scorecard into one aggregate risk score.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from src.monitoring.unwind_structure import UnwindAssessment, build_unwind_assessment
from src.mvp.config import MVPConfig
from src.mvp.evidence_card import (
    DeterministicEvidenceInput,
    build_deterministic_evidence_input,
)
from src.mvp.evidence_interpretation import (
    EvidenceInterpretation,
    EvidenceInterpreter,
    interpret_evidence_card,
)

MVP_RUN_SCHEMA_VERSION = "mvp-run-v1"


@dataclass(frozen=True)
class MVPRunResult:
    """Validated output of one full MVP assessment."""

    schema_version: str
    config: MVPConfig
    deterministic_input: DeterministicEvidenceInput
    interpretation: EvidenceInterpretation
    unwind: UnwindAssessment
    full_run_fingerprint: str
    display_labels: dict[str, str]

    def __post_init__(self) -> None:
        if self.schema_version != MVP_RUN_SCHEMA_VERSION:
            raise ValueError("unsupported MVP run schema")
        if self.deterministic_input.as_of_date != self.config.as_of_date:
            raise ValueError("deterministic input date must match config")
        if self.unwind.as_of_date != self.config.as_of_date:
            raise ValueError("unwind assessment date must match config")

    @property
    def card(self) -> DeterministicEvidenceInput:
        return self.deterministic_input

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "config": self.config.to_dict(),
            "deterministic_input": self.deterministic_input.to_dict(),
            "interpretation": self.interpretation.to_dict(),
            "unwind": self.unwind.to_dict(),
            "full_run_fingerprint": self.full_run_fingerprint,
            "display_labels": dict(self.display_labels),
        }


def _full_run_fingerprint(
    *,
    config: MVPConfig,
    deterministic_input: DeterministicEvidenceInput,
    interpretation: EvidenceInterpretation,
    unwind: UnwindAssessment,
) -> str:
    seed = {
        "config": config.to_dict(),
        "card_run_id": deterministic_input.run_id,
        "interpretation_version": interpretation.model_or_prompt_version,
        "unwind": {
            "schema_version": unwind.schema_version,
            "scenario_classification": unwind.scenario_classification,
            "active_scenarios": list(unwind.active_scenarios),
            "scorecard": [
                {
                    "metric": row.metric,
                    "current_value": row.current_value,
                    "status": row.status,
                }
                for row in unwind.scorecard
            ],
            "mechanisms": [
                {"scenario": item.scenario, "status": item.status}
                for item in unwind.mechanism_scenarios
            ],
        },
    }
    payload = json.dumps(seed, sort_keys=True, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def run_mvp(
    config: MVPConfig,
    *,
    interpreter: EvidenceInterpreter | None = None,
) -> MVPRunResult:
    """Run the full deterministic MVP workflow for one configuration."""

    deterministic_input = build_deterministic_evidence_input(
        as_of_date=config.as_of_timestamp,
        compare_to_date=config.compare_to_timestamp,
        threshold_profile=config.threshold_profile,
        horizon=config.horizon_days,
        processed_dir=config.processed_dir,
        output_dir=config.output_dir,
    )
    interpretation = interpret_evidence_card(
        deterministic_input,
        use_llm=config.use_llm,
        interpreter=interpreter,
    )
    unwind = build_unwind_assessment(
        as_of_date=config.as_of_timestamp,
        processed_dir=config.processed_dir,
        config=config.unwind_config,
        theme_config=config.theme_config,
    )
    fingerprint = _full_run_fingerprint(
        config=config,
        deterministic_input=deterministic_input,
        interpretation=interpretation,
        unwind=unwind,
    )
    display_labels = {
        "header_state_label": (
            "UMD comparison benchmark (Ken French / Daniel–Moskowitz context)"
        ),
        "scorecard_label": (
            "PM momentum portfolio scorecard "
            "(default customization: S&P 500 12-1 long 10 / short 10)"
        ),
        "historical_context_label": (
            "UMD comparison outcomes by market state "
            "(not analog retrieval; not the PM book)"
        ),
        "tail_loss_label": (
            "UMD comparison: state-conditioned tail-loss frequency "
            "(matured labels)"
        ),
    }
    return MVPRunResult(
        schema_version=MVP_RUN_SCHEMA_VERSION,
        config=config,
        deterministic_input=deterministic_input,
        interpretation=interpretation,
        unwind=unwind,
        full_run_fingerprint=fingerprint,
        display_labels=display_labels,
    )
