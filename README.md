# Momentum Tail-Risk Monitoring MVP

This repository is a transparent research prototype for monitoring conditions
associated with US equity momentum crashes. Its source of truth is a
deterministic, top-down workflow:

1. macro and market regime;
2. synthetic S&P 500 12-1 momentum portfolio;
3. realized long/short risk decomposition;
4. four-row deterministic scorecard;
5. six-row momentum unwind inputs;
6. three independent momentum-crash mechanism scenarios;
7. point-in-time evidence and an optional constrained interpretation layer.

The project is not a trading system, investment recommendation, causal model,
or production point-in-time backtest.

## Run the interactive PM demo

Python 3.11–3.14 and [`uv`](https://docs.astral.sh/uv/) are required.

```bash
uv sync --locked --all-groups
uv run python -m src.mvp.demo_smoke_test
uv run jupyter-execute \
  --inplace \
  --timeout=180 \
  notebooks/03_pm_evidence_card_demo.ipynb
```

The notebook parameter cell drives the full deterministic flow:

```python
AS_OF_DATE = "2024-01-05"
COMPARE_TO_DATE = "2023-12-01"
THRESHOLD_PROFILE = "default"
USE_LLM = False
```

`USE_LLM=False` is the reliable offline path and still renders the complete
Evidence Card. The CLI summary remains available:

```bash
uv run python -m src.mvp.run_demo --as-of-date 2026-05-29
```

## Current demo contents

| Section | Status | Authority |
|---|---|---|
| Phase 1 macro regime | Complete | Deterministic |
| Phase 2 named 10-long/10-short portfolio | Complete | Deterministic |
| Phase 3 contribution, beta, conditional beta, drawdown | Complete | Deterministic |
| Phase 4 four-row scorecard | Complete and unchanged | Deterministic source of truth |
| Phase 5A SEC coverage audit | Complete; 64.79% coverage, degraded | Feasibility only |
| Phase 5B–5E unwind structure | Complete | Separate six-row deterministic monitor |
| Correlated-theme concentration | Complete | Public-data proxy; cluster fixed at `t-1` |
| Scenario v2 | Complete | Three independent, potentially multi-label rules |
| Final Evidence Card notebook | Complete | Deterministic-first; LLM optional |
| January–February 2023 case | Reproducible historical proxy | Descriptive, not causal |
| Evidence preview | Bounded offline capability preview | Cannot change deterministic facts |

### Scenario v2

`build_unwind_assessment(...)` retains the original six-row scorecard and now
returns three independent mechanism states:

1. `bear_market_recovery_crash` — recent severe market drawdown, rapid
   recovery from the trough, and high realized volatility;
2. `short_book_reversal_crash` — an extreme short-minus-long reversal with
   broad gains in the active short-underlying basket;
3. `crowded_theme_unwind` — a pre-event correlated cluster in the active long
   book followed by an extreme, broad, loss- or volume-confirmed selloff.

The mechanisms can trigger together. `scenario_classification` remains only as
a lossy v1 compatibility field; new consumers should use
`mechanism_scenarios` and `active_scenarios`.

Validated date contrasts make the separation visible:

- `2020-03-24`: `bear_market_recovery_crash` triggers;
- `2024-01-05`: recovery is on watch, with neither reversal nor theme unwind
  confirmed;
- `2026-05-29`: `crowded_theme_unwind` triggers for the pre-event
  `CIEN` / `COHR` / `LITE` correlated cluster, without requiring a bear-market
  precondition or short-book reversal.

The theme calculation uses 63 trading days of benchmark-demeaned returns
ending at `t-1`, an all-pairs correlated cluster, strictly prior loss and
volume thresholds, and the existing monthly holdings. It is explicitly a
`correlated_theme_proxy`: it does not observe common ownership, leverage,
financing, or forced selling. Industry classification is unavailable in the
current repository and is reported as missing rather than invented.

The 2023 case uses `2023-01-09` as a relative elevated-risk/high-volatility
recovery precursor and `2023-02-02` as the realized stress observation. It is
not labeled a formal `panic_elevated` alert, a proven crash forecast, or proof
of a causal Fed-repricing mechanism.

## Evidence boundary

`src/evidence/research_preview.py` is labeled:

> Phase 8 capability preview — not the completed Phase 8 implementation.

It can only replay the versioned local corpus and an exact-date, already
validated cached classification. It makes no network or model call, creates no
threshold or risk probability, and cannot write back to deterministic facts.
When reliable date-matched evidence is absent, it returns `unavailable` and
empty supporting, contradicting, and contextual lists.

## Data and point-in-time controls

- Market and risk windows end on or before the observation date.
- Portfolio signal endpoints, formation dates, effective months, and
  observation dates are separate fields.
- Long weights sum to `+1`; short weights sum to `-1`.
- Short-underlying returns and signed short contributions use explicit,
  opposite signs.
- SEC feasibility uses filing availability rather than fiscal-period end and
  applies a staleness gate.
- Missing values remain unavailable and never silently pass a threshold.
- Evidence publications and cached classifications must satisfy the local
  cutoff and provenance checks.
- Theme-cluster membership and its correlation cutoff stop at `t-1`; the
  selected-date return can affect liquidation evidence but not cluster
  definition.
- The bear-market recovery scenario keeps drawdown, recovery-from-trough, and
  realized volatility as three separately visible conditions.

The portfolio uses a current SPY membership snapshot as a historical proxy and
is survivorship-biased. Public-vendor price histories can contain ticker or
corporate-action discontinuities; extreme momentum observations should be
investigated before economic interpretation.

## Tests

```bash
uv run python -m pytest -q
git diff --check
```

Focused theme and scenario tests protect cross-sector cluster detection,
unchanged name-level effective bets, `t-1` cluster definition, future-row
invariance, independent scenario triggers, multi-label output, and fail-closed
missing evidence.

## Deferred roadmap

The following work remains explicitly deferred, not cancelled or completed:

- point-in-time historical membership and industry classifications;
- observed holdings, leverage, financing, and order-flow data;
- predictive validation of the three descriptive mechanism rules;
- Phase 8 — Full AI Research and Retrieval Layer.

Live news, vector databases, new predictive models, dashboards, deployment,
and production infrastructure are not part of this research prototype.

## Documentation

- [Methodology](docs/methodology.md)
- [Demo walkthrough](docs/demo_walkthrough.md)
- [Final handoff](docs/handoff.md)
- [Confirmed design](docs/confirmed_design.md)
- [Development plan](docs/development_plan.md)
- [Phase 5A handoff](docs/handoff_phase5.md)
- [Phase 5 unwind monitor review](docs/phase_reviews/phase_5_unwind_monitor_review.md)
- [Phase 5 unwind handoff](docs/handoff_phase5_unwind.md)

The earlier Daniel–Moskowitz conditional-frequency pipeline remains available
through `python -m src.pipeline` as a retained research path. It is not the
primary final-MVP entry point and does not replace the deterministic Phase 1–4
scorecard.
