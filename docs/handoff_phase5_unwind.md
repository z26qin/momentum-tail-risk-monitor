# Phase 5 unwind monitor handoff

Date: 2026-07-29

Status: implementation and notebook integration complete

## Run the demo

Open the pre-executed notebook:

```text
notebooks/03_pm_evidence_card_demo.ipynb
```

Or execute it from the repository root:

```bash
.venv/bin/jupyter execute \
  --inplace \
  --timeout=180 \
  --kernel_name=python3 \
  notebooks/03_pm_evidence_card_demo.ipynb
```

The parameter cell controls the complete view:

```python
AS_OF_DATE = "2024-01-05"
COMPARE_TO_DATE = "2023-12-01"
THRESHOLD_PROFILE = "default"
USE_LLM = False
```

## Run the Phase 5 assessment

Interactive, read-only use:

```python
import pandas as pd

from src.monitoring.unwind_structure import build_unwind_assessment

assessment = build_unwind_assessment(
    as_of_date=pd.Timestamp("2024-01-05"),
)
```

Persist histories and an exact-date scorecard:

```bash
.venv/bin/python -m src.monitoring.unwind_structure \
  --as-of-date 2024-01-05
```

The default does not parse the entire SEC cache. To perform the slower local
exact-date parse explicitly:

```bash
.venv/bin/python -m src.monitoring.unwind_structure \
  --as-of-date 2024-01-05 \
  --parse-fundamentals
```

That command acquires no new data, but it requires the existing ignored local
SEC cache and may take several minutes.

## Tests

Focused:

```bash
.venv/bin/pytest -q \
  tests/test_concentration.py \
  tests/test_momentum_breadth.py \
  tests/test_fundamental_anchor.py \
  tests/test_unwind_structure.py \
  tests/test_demo_smoke_test.py
```

Full:

```bash
.venv/bin/pytest
```

Latest results:

```text
focused: 32 passed
full: 284 passed, 4 skipped
notebook: executed successfully, 0 error outputs
```

## Files

New production modules:

- `src/risk/concentration.py`;
- `src/features/momentum_breadth.py`;
- `src/monitoring/fundamental_anchor.py`;
- `src/monitoring/unwind_structure.py`.

New tests:

- `tests/test_concentration.py`;
- `tests/test_momentum_breadth.py`;
- `tests/test_fundamental_anchor.py`;
- `tests/test_unwind_structure.py`.

Modified integration:

- `notebooks/03_pm_evidence_card_demo.ipynb`;
- `src/mvp/demo_smoke_test.py`;
- `src/mvp/evidence_card.py`;
- `tests/test_demo_smoke_test.py`.

Generated outputs:

- `data/processed/momentum_breadth_history.parquet`;
- `data/processed/unwind_structure_history.parquet`;
- `outputs/unwind_structure/unwind_scorecard_2024-01-05.csv`;
- `outputs/unwind_structure/unwind_assessment_2024-01-05.json`;
- `outputs/unwind_structure/unwind_audit.json`.

Review documents:

- `docs/phase_reviews/phase_5_reconstruction_review.md`;
- `docs/phase_reviews/phase_5_unwind_monitor_review.md`;
- `docs/handoff_phase5_unwind.md`.

## Demonstrated output

For 2024-01-05:

```text
existing Phase 1–4 state: bear_low_volatility
Phase 5 scenario: normal_drawdown
Phase 5 completeness: moderate
triggered Phase 5 row: synchronous_winner_liquidation
missing Phase 5 row: fundamental_anchor
LLM requested/effective: False/False
```

The displayed final card retains the three separate audit components behind
the existing high-volatility-recovery state:

- recent market drawdown;
- recovery from trough;
- 21-day realized volatility.

## Operational notes

- `build_unwind_assessment` rebuilds deterministic histories in memory and
  takes approximately 15 seconds on the current local artifacts.
- The fundamental row fails closed. Missing exact-date coverage is not
  converted to a non-trigger.
- `--parse-fundamentals` is deliberately opt-in because parsing the complete
  SEC cache is unsuitable for the live demo path.
- `evaluate_historical_rebound` is historical-only and must not be merged into
  the live assessment.
- The current-membership and current-classification limitations must remain
  visible.
- Public data cannot directly establish leverage, forced selling, or
  proprietary crowding.

## Deferred

- Recent semiconductor/AI case study;
- point-in-time historical membership and classifications;
- portable historical SEC fundamental panel;
- versioned LLM input containing Phase 5 facts;
- performance caching beyond the two generated histories;
- threshold optimization or predictive validation.
