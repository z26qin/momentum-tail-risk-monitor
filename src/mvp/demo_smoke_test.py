"""Fast, read-only pre-demo validation for the PM Evidence Card.

Run from the repository root:

    python -m src.mvp.demo_smoke_test
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.mvp.evidence_card import (
    DATA_VERSION_FILES,
    DeterministicEvidenceInput,
    build_deterministic_evidence_input,
)
from src.mvp.evidence_interpretation import interpret_evidence_card
from src.monitoring.unwind_structure import (
    MECHANISM_SCENARIOS,
    UNWIND_SCHEMA_VERSION,
    UNWIND_SCORECARD_METRICS,
    build_unwind_assessment,
)
from src.utils.io import DEFAULT_PROCESSED_DIR, REPO_ROOT


DEMO_MODE = True
DEMO_AS_OF_DATE = "2024-01-05"
DEMO_COMPARE_TO_DATE = "2023-12-01"
DEMO_THRESHOLD_PROFILE = "default"
DEMO_USE_LLM = False
REGRESSION_AS_OF_DATE = "2020-03-24"
REGRESSION_COMPARE_TO_DATE = "2020-02-24"
NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "03_pm_evidence_card_demo.ipynb"
NOTEBOOK_DEPENDENCIES = ("IPython", "ipykernel", "matplotlib", "nbclient", "nbformat")


def _require_local_inputs() -> list[str]:
    required = [DEFAULT_PROCESSED_DIR / name for name in DATA_VERSION_FILES]
    required.append(NOTEBOOK_PATH)
    missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing demo inputs: " + ", ".join(missing))
    return [str(path.relative_to(REPO_ROOT)) for path in required]


def _require_notebook_dependencies() -> list[str]:
    missing = [
        name for name in NOTEBOOK_DEPENDENCIES if importlib.util.find_spec(name) is None
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
    primary = build_deterministic_evidence_input(
        as_of_date=pd.Timestamp(DEMO_AS_OF_DATE),
        compare_to_date=pd.Timestamp(DEMO_COMPARE_TO_DATE),
        threshold_profile=DEMO_THRESHOLD_PROFILE,
    )
    primary_interpretation = interpret_evidence_card(
        primary,
        use_llm=DEMO_USE_LLM,
    )
    unwind = build_unwind_assessment(
        as_of_date=pd.Timestamp(DEMO_AS_OF_DATE),
    )
    regression = build_deterministic_evidence_input(
        as_of_date=pd.Timestamp(REGRESSION_AS_OF_DATE),
        compare_to_date=pd.Timestamp(REGRESSION_COMPARE_TO_DATE),
        threshold_profile=DEMO_THRESHOLD_PROFILE,
    )
    regression_interpretation = interpret_evidence_card(
        regression,
        use_llm=False,
    )
    if not isinstance(primary, DeterministicEvidenceInput):
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
    if unwind.as_of_date != primary.as_of_date:
        raise AssertionError("unwind assessment date differs from Evidence Card")
    if _quant_signature(primary) == _quant_signature(regression):
        raise AssertionError("fixed historical dates produced identical quant results")
    if (
        primary_interpretation.narrative_state
        == regression_interpretation.narrative_state
    ):
        raise AssertionError("fixed historical dates produced identical interpretations")
    evidence = primary.retrieved_evidence
    cutoff = datetime.fromisoformat(primary.data_cutoff)
    if any(datetime.fromisoformat(item.timestamp) > cutoff for item in evidence):
        raise AssertionError("retrieved evidence exceeds the point-in-time cutoff")
    notebook_source = NOTEBOOK_PATH.read_text(encoding="utf-8")
    for marker in (
        "build_deterministic_evidence_input",
        "interpret_evidence_card",
        "build_unwind_assessment",
        "Momentum Crash Mechanisms",
        "mechanism_scenarios",
        "correlated-theme proxy",
        "Final Interactive Evidence Card",
    ):
        if marker not in notebook_source:
            raise AssertionError(f"final notebook is missing {marker!r}")
    return {
        "status": "ready",
        "demo_mode": DEMO_MODE,
        "primary_date": primary.as_of_date,
        "comparison_date": primary.comparison_date,
        "regression_date": regression.as_of_date,
        "primary_state": primary.overall_risk_state,
        "regression_state": regression.overall_risk_state,
        "primary_run_id": primary.run_id,
        "regression_run_id": regression.run_id,
        "evidence_items": len(evidence),
        "data_version": primary.audit_metadata["data_version"],
        "quant_model_version": primary.audit_metadata["quant_model_version"],
        "interpretation_use_llm": primary_interpretation.use_llm,
        "interpretation_version": (
            primary_interpretation.model_or_prompt_version
        ),
        "threshold_profile": primary.threshold_profile,
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
        "validated_inputs": inputs,
        "notebook_dependencies": dependencies,
    }


def main() -> None:
    print(json.dumps(run_smoke_test(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
