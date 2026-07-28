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
    EvidenceCard,
    build_evidence_card,
    render_evidence_card_html,
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


def _quant_signature(card: EvidenceCard) -> tuple[object, ...]:
    signals = card.triggered_quant_signals + card.non_triggered_relevant_signals
    return (
        card.overall_risk_state,
        tuple((signal.name, signal.current_value, signal.status) for signal in signals),
    )


def run_smoke_test() -> dict[str, object]:
    """Validate the deterministic demo without writing output artifacts."""

    inputs = _require_local_inputs()
    dependencies = _require_notebook_dependencies()
    primary = build_evidence_card(
        as_of_date=pd.Timestamp(DEMO_AS_OF_DATE),
        compare_to_date=pd.Timestamp(DEMO_COMPARE_TO_DATE),
        threshold_profile=DEMO_THRESHOLD_PROFILE,
        use_llm=DEMO_USE_LLM,
    )
    regression = build_evidence_card(
        as_of_date=pd.Timestamp(REGRESSION_AS_OF_DATE),
        compare_to_date=pd.Timestamp(REGRESSION_COMPARE_TO_DATE),
        threshold_profile=DEMO_THRESHOLD_PROFILE,
        use_llm=False,
    )
    if not isinstance(primary, EvidenceCard):
        raise TypeError("demo result did not validate as an EvidenceCard")
    if _quant_signature(primary) == _quant_signature(regression):
        raise AssertionError("fixed historical dates produced identical quant results")
    evidence = (
        primary.supporting_evidence
        + primary.contradicting_evidence
        + primary.contextual_evidence
    )
    cutoff = datetime.fromisoformat(primary.data_cutoff)
    if any(datetime.fromisoformat(item.timestamp) > cutoff for item in evidence):
        raise AssertionError("retrieved evidence exceeds the point-in-time cutoff")
    rendered = render_evidence_card_html(primary)
    if "PM Evidence Card" not in rendered:
        raise AssertionError("Evidence Card rendering failed")
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
        "data_version": primary.data_version,
        "quant_model_version": primary.quant_model_version,
        "synthesis_mode": primary.synthesis_mode,
        "validated_inputs": inputs,
        "notebook_dependencies": dependencies,
    }


def main() -> None:
    print(json.dumps(run_smoke_test(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
