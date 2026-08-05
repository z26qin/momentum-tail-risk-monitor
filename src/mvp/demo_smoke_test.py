"""Fast, read-only pre-demo validation for the PM Evidence Card.

Run from the repository root:

    python -m src.mvp.demo_smoke_test
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime

from src.mvp.config import (
    DEFAULT_AS_OF_DATE,
    DEFAULT_COMPARE_TO_DATE,
    DEFAULT_THRESHOLD_PROFILE,
    DEFAULT_USE_LLM,
    HISTORICAL_EXAMPLE_DATE,
    MVPConfig,
    REGRESSION_AS_OF_DATE,
    REGRESSION_COMPARE_TO_DATE,
    default_demo_config,
)
from src.mvp.evidence_card import DATA_VERSION_FILES, DeterministicEvidenceInput
from src.mvp.pipeline import run_mvp
from src.monitoring.unwind_structure import (
    MECHANISM_SCENARIOS,
    UNWIND_SCHEMA_VERSION,
    UNWIND_SCORECARD_METRICS,
)
from src.utils.io import DEFAULT_PROCESSED_DIR, REPO_ROOT


DEMO_MODE = True
NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "final_mvp_demo.ipynb"
NOTEBOOK_DEPENDENCIES = ("IPython", "ipykernel", "matplotlib", "nbclient", "nbformat")


def _require_local_inputs() -> list[str]:
    required = [DEFAULT_PROCESSED_DIR / name for name in DATA_VERSION_FILES]
    required.append(NOTEBOOK_PATH)
    missing = [
        str(path.relative_to(REPO_ROOT)) for path in required if not path.is_file()
    ]
    if missing:
        raise FileNotFoundError("missing demo inputs: " + ", ".join(missing))
    return [str(path.relative_to(REPO_ROOT)) for path in required]


def _require_notebook_dependencies() -> list[str]:
    missing = [
        name
        for name in NOTEBOOK_DEPENDENCIES
        if importlib.util.find_spec(name) is None
    ]
    if missing:
        raise RuntimeError(
            "missing notebook dependencies: "
            + ", ".join(missing)
            + "; install the repository dev dependency group"
        )
    return list(NOTEBOOK_DEPENDENCIES)


def _quant_signature(card: DeterministicEvidenceInput) -> tuple[object, ...]:
    signals = card.triggered_quant_signals + card.non_triggered_relevant_signals
    return (
        card.overall_risk_state,
        tuple((signal.name, signal.current_value, signal.status) for signal in signals),
    )


def run_smoke_test() -> dict[str, object]:
    """Validate the deterministic demo without writing output artifacts."""

    inputs = _require_local_inputs()
    dependencies = _require_notebook_dependencies()
    primary = run_mvp(default_demo_config())
    regression = run_mvp(
        MVPConfig(
            as_of_date=REGRESSION_AS_OF_DATE,
            compare_to_date=REGRESSION_COMPARE_TO_DATE,
            threshold_profile=DEFAULT_THRESHOLD_PROFILE,
            use_llm=False,
        )
    )
    historical = run_mvp(MVPConfig(as_of_date=HISTORICAL_EXAMPLE_DATE))
    card = primary.deterministic_input
    interpretation = primary.interpretation
    unwind = primary.unwind
    mechanical = primary.mechanical_unwind
    if not isinstance(card, DeterministicEvidenceInput):
        raise TypeError(
            "demo result did not validate as a DeterministicEvidenceInput"
        )
    if tuple(row.metric for row in unwind.scorecard) != UNWIND_SCORECARD_METRICS:
        raise AssertionError("unwind assessment does not contain six ordered rows")
    if unwind.schema_version != UNWIND_SCHEMA_VERSION:
        raise AssertionError("unwind assessment is not using the v2 contract")
    if tuple(item.scenario for item in unwind.mechanism_scenarios) != (
        MECHANISM_SCENARIOS
    ):
        raise AssertionError("unwind assessment does not contain three mechanisms")
    if unwind.theme_concentration.cluster_definition_cutoff >= unwind.as_of_date:
        raise AssertionError("theme cluster definition does not stop before as-of")
    if unwind.as_of_date != card.as_of_date:
        raise AssertionError("unwind assessment date differs from Evidence Card")
    if mechanical.as_of_date != card.as_of_date:
        raise AssertionError("mechanical unwind date differs from Evidence Card")
    if mechanical.unwind_state not in {
        "NORMAL",
        "FRAGILITY_BUILDING",
        "ACTIVE_UNWIND",
        "STABILIZING_REVERSAL",
    }:
        raise AssertionError("mechanical unwind state is not recognized")
    if _quant_signature(card) == _quant_signature(regression.deterministic_input):
        raise AssertionError("fixed historical dates produced identical quant results")
    if interpretation.narrative_state == regression.interpretation.narrative_state:
        raise AssertionError(
            "fixed historical dates produced identical interpretations"
        )
    evidence = card.retrieved_evidence
    cutoff = datetime.fromisoformat(card.data_cutoff)
    if any(datetime.fromisoformat(item.timestamp) > cutoff for item in evidence):
        raise AssertionError("retrieved evidence exceeds the point-in-time cutoff")
    notebook_source = NOTEBOOK_PATH.read_text(encoding="utf-8")
    for marker in (
        "MVPConfig",
        "run_mvp",
        "Two momentum-crash mechanisms",
        "Primary correlated-cluster case",
        "AI evidence view",
        "2020 historical validation",
        "2024 quiet control",
        "Cross-case comparison",
        "current_semi_unwind",
        "march_2020_reference",
        "quiet_control_2024",
        "cross_case_comparison.md",
        "docs/production_path.md",
        "Daniel–Moskowitz",
        "Khandani–Lo",
    ):
        if marker not in notebook_source:
            raise AssertionError(f"final notebook is missing {marker!r}")
    pm_response = primary.pm_response
    if not pm_response.current_state or not pm_response.response_categories:
        raise AssertionError("PM response readout is incomplete")
    return {
        "status": "ready",
        "demo_mode": DEMO_MODE,
        "primary_date": card.as_of_date,
        "comparison_date": card.comparison_date,
        "regression_date": regression.deterministic_input.as_of_date,
        "historical_date": historical.deterministic_input.as_of_date,
        "primary_state": card.overall_risk_state,
        "regression_state": regression.deterministic_input.overall_risk_state,
        "primary_run_id": card.run_id,
        "full_run_fingerprint": primary.full_run_fingerprint,
        "regression_run_id": regression.deterministic_input.run_id,
        "evidence_items": len(evidence),
        "data_version": card.audit_metadata["data_version"],
        "quant_model_version": card.audit_metadata["quant_model_version"],
        "interpretation_use_llm": interpretation.use_llm,
        "interpretation_version": interpretation.model_or_prompt_version,
        "pm_response_use_llm": pm_response.use_llm,
        "pm_response_categories": list(pm_response.response_categories),
        "threshold_profile": card.threshold_profile,
        "unwind_scenario": unwind.scenario_classification,
        "unwind_schema_version": unwind.schema_version,
        "mechanism_statuses": {
            item.scenario: item.status for item in unwind.mechanism_scenarios
        },
        "active_mechanisms": list(unwind.active_scenarios),
        "theme_cluster": list(unwind.theme_concentration.cluster_symbols),
        "theme_definition_cutoff": (
            unwind.theme_concentration.cluster_definition_cutoff
        ),
        "unwind_completeness": unwind.completeness_confidence,
        "unwind_scorecard_rows": len(unwind.scorecard),
        "mechanical_unwind_state": mechanical.unwind_state,
        "mechanical_unwind_schema": mechanical.schema_version,
        "demo_defaults": {
            "as_of_date": DEFAULT_AS_OF_DATE,
            "compare_to_date": DEFAULT_COMPARE_TO_DATE,
            "use_llm": DEFAULT_USE_LLM,
        },
        "validated_inputs": inputs,
        "notebook_dependencies": dependencies,
    }


def main() -> None:
    print(json.dumps(run_smoke_test(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
