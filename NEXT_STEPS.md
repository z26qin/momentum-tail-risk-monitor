# Next steps

Rebuilt 2026-07-25 from `outputs/review_report.md`. The previous version of this
file is superseded — its status claims were stale: it said no risk-state or
evidence modules exist, but `src/monitoring/` and `src/evidence/` are committed
(`8e1b641`, `04f6f3d`), built on the **abandoned** pre-v3 architecture. That
contradiction is itself item 3 below.

## Budget

Operator-corrected: **the existing repo accounts for ≈4h** of the ~20h cap, so
**≈16h remain**. `PROJECT_PLAN_v3.md` §5's "Spent to date ≈ 9h" is superseded
and should be corrected there when the plan is next touched. Log actual hours
per item from here on — interview question "where did the 20 hours go?" is only
answerable if they are written down.

## State (verified by the review, 2026-07-25)

| Piece | Status |
|---|---|
| Positioning panel | Complete. 2,402 dates, 200/200 match, publication-date join tested, three crowding variants. **Consumed by nothing downstream.** |
| Narrative panel | Prototype. 2 of 5 mechanisms, volume only, no tone, precision unassessed. Raw GDELT payloads exist only on the build machine. **Consumed by nothing downstream.** |
| Risk state (v3: DM rule + PIT conditional frequency/severity) | **Does not exist.** |
| Baseline separation ("insurance") table | **Does not exist.** |
| Pre-v3 monitoring/evidence prototype | Exists (`src/monitoring/`, `src/evidence/`) but serves the fitted B2 probability the project disavowed; thresholds in `domain_risk.py` match neither DM 2016 nor PLAN_v3. |
| PM brief, memo, slides | Do not exist. |
| Tests | 121 passed / 1 skipped in the build worktree; **a fresh clone fails 1 test** (narrative rebuild needs git-ignored payloads) and skips 3. |
| Branches | `main` (587a099) lacks the overlays and the v3 plan; everything new is on `dear/*`. |

## Ordered work list (from review Part 5 — marginal value per hour)

| # | What | Why | Est. h | Depends on |
|---|---|---|---:|---|
| 1 | **Insurance table**: unconditional vs DM-panic-state-conditional forward tail-loss frequency, full sample, both horizons, n per cell. Inputs already exist (`data/processed/momentum_labels_h*.parquet`, `market_features.parquet`). | Required Element 5; answers "did you check the rule in your own data?" | 0.5 | — |
| 2 | **v3 risk-state module**: DM rule from existing `bear_state` × `mkt_variance_126d`, PIT conditional probability and severity range with sample size; run on one elevated and one quiet date. Cite DM 2016's exact parameterization (open travel item, `PROJECT_PLAN_v3.md:75`). | Elements 1/3/6; removes the fitted-B2 contradiction | 1.5 | 1 |
| 3 | **Coherence pass**: README leads with v3 + traceability table (PLAN_v3 §3); DECISIONS entry assigning `src/monitoring/` + `src/modeling/` to "prior iteration, retained as history"; correct PLAN_v3 §5 hours; align `src/utils/pit.py` docstring with the corrected gap-clustering finding. | README deliverable; kills the sharpest interview attack | 1.0 | 2 |
| 4 | **PM brief generator** (markdown, from the pipeline, quiet day + elevated day): state, conditional probability (n), severity range, crowding read (`short_interest_ratio_z`, utilisation), narrative read (`panic_vol_z`, `crowding_vol_z`), cited evidence replayed from existing classified outputs, explicit invalidation conditions. | Elements 3 + 6 — the first artifact where all three legs meet | 1.5 | 2 |
| 5 | **Episode ablation table** (descriptive): per episode (2020-03, 2021-01, 2024-08, 2025-04) — did the DM state flag it; overlay lead-time readings. Numbers already measured in `outputs/narrative_poc_review.md:172-183`; formalize into one artifact. | Element 5 item 3 | 0.5 | 2 |
| 6 | **Reproducibility guard**: fix `test_narrative_panel_rebuild_is_byte_identical`'s skip condition (guard on raw payloads, not the tracked parquet); README paragraph on what a clone can regenerate; track the six small GDELT payload JSONs; merge `dear/*` → `main`. | A cloning interviewer currently sees a failing suite | 0.5 | — |
| 7 | **Memo, 6-10 pp** (hand-written per plan §5 item 5). Much of §2/§4 already exists in `docs/DECISIONS.md` and `outputs/data_review.md`; §5 needs the procurement table (borrow fees, RavenPack/Bloomberg, PIT constituents). | Deliverable | 2.5 | 1-5 |
| 8 | **Slides + rehearsal** | Deliverable | 0.75 | 7 |
| | **Core total** | | **8.75** | |

## Affordable extensions (budget now permits; keep this order)

1. **Trigger discipline + minimal agent loop** (~1.0-1.5h): gate evidence on an
   elevated state; bounded one-loop-one-requery per `PROJECT_PLAN_v3.md:113`.
2. **Faithfulness sample extension** (~0.5h): a third demo day and more review
   labels — n=16 developer-labeled rows is the thinnest AI-validation number.
3. **Analog check** (~1.5h): lowest evidence-per-hour on the board; do last or
   leave as a designed-but-unbuilt memo paragraph.

Core + extensions 1-2 ≈ 10.75h → cumulative ≈ 15h, under the cap with buffer.

## Opportunistic (zero planned hours — externally blocked)

GDELT access may return at any time. Each command is fail-fast and resumable;
do not loop, do not wait on it:

```bash
uv run python -m src.data.gdelt --queries panic      # 2 requests: adds tone
uv run python -m src.data.gdelt_sanity               # 4 requests: precision flags
```

(`crowding` volume is already cached; `panic` tone is the highest-value missing
piece, then the sanity check — both queries still carry
`precision_flag = "unassessed"`.)

## Open questions carried forward

- **12-2 formation window**: implemented as month-end *m*−12 to *m*−2 (10-month
  window, skips two months) per the spec's literal wording; the common
  convention skips one. PIT-safe either way; confirm which was intended before
  the memo states it.
- **Normalisation convention**: narrative panel requires 100 of 126 finite
  observations, positioning panel all 126. Both recorded per row; unify only if
  a downstream consumer needs one rule.

## Never cut (unchanged from PLAN_v3 §5)

PIT/leakage tests, the insurance table, the generated PM brief, the two-track
text rule's honest treatment in the memo.
