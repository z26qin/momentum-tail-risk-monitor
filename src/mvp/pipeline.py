"""Single entry point that assembles one MVP assessment.

Composes existing deterministic calculations without reimplementing them.
UMD / Daniel–Moskowitz inputs are historical context; the S&P 500 12-1
long-10 / short-10 book is the default PM portfolio proxy. The two are never
merged into one opaque risk score.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from src.monitoring.unwind_monitor import (
    MechanicalUnwindAssessment,
    build_mechanical_unwind_assessment,
)
from src.monitoring.unwind_structure import UnwindAssessment, build_unwind_assessment
from src.mvp.config import MVPConfig
from src.mvp.crowding_context import build_positioning_snapshot
from src.mvp.evidence_card import (
    DeterministicEvidenceInput,
    build_deterministic_evidence_input,
)
from src.mvp.evidence_interpretation import (
    EvidenceInterpretation,
    EvidenceInterpreter,
    interpret_evidence_card,
    mechanical_unwind_summary,
    public_positioning_proxy_items,
    structural_unwind_summary,
)
from src.mvp.pm_response import (
    PMResponse,
    PMResponseInterpreter,
    build_pm_response,
)

MVP_RUN_SCHEMA_VERSION = "mvp-run-v2"


@dataclass(frozen=True)
class MVPRunResult:
    """Validated output of one full MVP assessment."""

    schema_version: str
    config: MVPConfig
    deterministic_input: DeterministicEvidenceInput
    interpretation: EvidenceInterpretation
    unwind: UnwindAssessment
    mechanical_unwind: MechanicalUnwindAssessment
    pm_response: PMResponse
    full_run_fingerprint: str
    display_labels: dict[str, str]

    def __post_init__(self) -> None:
        if self.schema_version != MVP_RUN_SCHEMA_VERSION:
            raise ValueError("unsupported MVP run schema")
        if self.deterministic_input.as_of_date != self.config.as_of_date:
            raise ValueError("deterministic input date must match config")
        if self.unwind.as_of_date != self.config.as_of_date:
            raise ValueError("unwind assessment date must match config")
        if self.mechanical_unwind.as_of_date != self.config.as_of_date:
            raise ValueError("mechanical unwind date must match config")

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
            "mechanical_unwind": self.mechanical_unwind.to_dict(),
            "pm_response": self.pm_response.to_dict(),
            "full_run_fingerprint": self.full_run_fingerprint,
            "display_labels": dict(self.display_labels),
        }


def _full_run_fingerprint(
    *,
    config: MVPConfig,
    deterministic_input: DeterministicEvidenceInput,
    interpretation: EvidenceInterpretation,
    unwind: UnwindAssessment,
    mechanical_unwind: MechanicalUnwindAssessment,
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
        "mechanical_unwind": {
            "schema_version": mechanical_unwind.schema_version,
            "unwind_state": mechanical_unwind.unwind_state,
            "factor_footprint_r2": mechanical_unwind.factor_footprint_r2,
            "extreme_turnover_ratio": mechanical_unwind.extreme_turnover_ratio,
            "liquidity_absorption_failure": (
                mechanical_unwind.liquidity_absorption_failure
            ),
        },
    }
    payload = json.dumps(seed, sort_keys=True, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def run_mvp(
    config: MVPConfig,
    *,
    interpreter: EvidenceInterpreter | None = None,
    pm_interpreter: PMResponseInterpreter | None = None,
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
    unwind = build_unwind_assessment(
        as_of_date=config.as_of_timestamp,
        processed_dir=config.processed_dir,
        config=config.unwind_config,
        theme_config=config.theme_config,
    )
    mechanical_unwind = build_mechanical_unwind_assessment(
        as_of_date=config.as_of_timestamp,
        processed_dir=config.processed_dir,
        config=config.mechanical_unwind_config,
    )
    positioning = build_positioning_snapshot(
        as_of_date=config.as_of_date,
        context_elevated=bool(deterministic_input.triggered_quant_signals),
        processed_dir=config.processed_dir,
    )
    positioning_proxies = public_positioning_proxy_items(positioning)
    interpretation = interpret_evidence_card(
        deterministic_input,
        use_llm=config.use_llm,
        interpreter=interpreter,
        structural_unwind=structural_unwind_summary(unwind),
        mechanical_unwind=mechanical_unwind_summary(mechanical_unwind),
        public_positioning_proxies=positioning_proxies,
    )
    pm_response = build_pm_response(
        deterministic_input,
        unwind,
        use_llm=config.use_llm,
        interpreter=pm_interpreter,
        public_positioning_proxies=positioning_proxies,
    )
    fingerprint = _full_run_fingerprint(
        config=config,
        deterministic_input=deterministic_input,
        interpretation=interpretation,
        unwind=unwind,
        mechanical_unwind=mechanical_unwind,
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
        "mechanical_unwind_label": (
            "Liquidity / mechanical unwind "
            "(factor footprint · aligned turnover · absorption proxy)"
        ),
    }
    return MVPRunResult(
        schema_version=MVP_RUN_SCHEMA_VERSION,
        config=config,
        deterministic_input=deterministic_input,
        interpretation=interpretation,
        unwind=unwind,
        mechanical_unwind=mechanical_unwind,
        pm_response=pm_response,
        full_run_fingerprint=fingerprint,
        display_labels=display_labels,
    )
