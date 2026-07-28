# Final MVP demo walkthrough

## Run

From the repository root:

```bash
uv run python -m src.mvp.run_demo --as-of-date 2026-05-29
```

The command is offline and writes four files under `outputs/demo/`. A
successful run prints a compact JSON status line naming the summary file.

## Read the outputs

Start with `demo_report_2026-05-29.md`. Its eight sections are ordered to
prevent later context from overwriting deterministic facts:

1. observation, active-portfolio, next-rebalance, and module-latest dates;
2. macro regime;
3. separately labeled active and next portfolios;
4. return, contribution, beta, and conditional beta;
5. unchanged Phase 4 scorecard;
6. Phase 5A feasibility with alignment fields explicitly unavailable;
7. January-to-February 2023 historical case;
8. evidence-preview status and limitations.

Use `demo_summary_2026-05-29.json` for complete structured values,
`demo_scorecard_2026-05-29.csv` for the four deterministic decisions, and
`demo_portfolio_2026-05-29.csv` for the named holdings.

## Current observation

The current case is anchored on `2026-05-29`. The active portfolio was formed
on `2026-04-30` for May. A different portfolio was formed at the May 29 close
for June and is labeled `next_rebalance_portfolio`.

The report answers:

- What macro state is active?
- Is the market in early or high-volatility recovery?
- Which names are currently long and short?
- Which names enter the next rebalance?
- Did daily and trailing losses come from the long or short side?
- How large are long, short-underlying, portfolio, up-market, and down-market
  betas?
- Which of the four scorecard rules triggered?
- Is Phase 5 coverage sufficient for production alignment? No: it is degraded
  feasibility only.
- Are fundamental alignment ranks or flags available? No: they remain `null`.
- What historical stress case illustrates the mechanism?
- What evidence is available without changing the deterministic result?
- What limitations should prevent over-interpretation?

## 2023 case

The report embeds two observations created by the same code path:

- `2023-01-09` shows a severe prior drawdown, an 8%+ recovery from the recent
  trough, realized volatility above its prior-only threshold, and a large
  short-minus-long beta gap. It is described only as relative elevated risk,
  a stress precursor, and a high-volatility recovery example.
- `2023-02-02` shows the realized stress outcome, including a large negative
  daily portfolio return and short-side loss contribution.

Do not present January 9 as a formal `panic_elevated` alert or a proven crash
forecast. Do not infer that Fed repricing caused the February loss.

## Phase 5 and evidence

Phase 5A displays 64.79% coverage and `degraded` status. Its alignment status
is `future_work`; ranks, Spearman correlation, spread, and flags are `null`.
This prevents acquisition coverage from being mistaken for fundamental
support.

The evidence section is explicitly a Phase 8 capability preview. The 2023
case lacks an exact-date validated local classification, so it fails safely to
`unavailable` with empty evidence lists. This absence is uncertainty, not a
benign finding.

## Reproduce and review

```bash
uv run python -m pytest -q tests/test_demo.py tests/test_research_preview.py
uv run python -m pytest -q
git diff --check
```

Repeated demo runs for the same date produce identical structured JSON. The
test suite also hashes the existing Phase 1–5 artifacts before and after the
demo to confirm they are not modified.

---

# Phase 6A — interactive PM Evidence Card (20-minute walkthrough)

This is the date-driven demo. It reuses the same Phase 1–4 deterministic code
and the point-in-time evidence replay, exposed through one notebook whose
parameter cell recomputes the whole card.

## Open it

```bash
uv run --with jupyterlab jupyter lab notebooks/03_pm_evidence_card_demo.ipynb
```

The notebook ships pre-executed, so it can also be read directly. The single
parameter cell is:

```python
AS_OF_DATE = "2024-01-05"
COMPARE_TO_DATE = "2023-12-01"
THRESHOLD_PROFILE = "default"
USE_LLM = True
```

Edit it and **Run All** to recompute. A headless card is also available:

```bash
uv run python -m src.mvp.evidence_card --as-of-date 2024-01-05 --compare-to-date 2023-12-01
```

## Minute 0–2 — Problem

Momentum crashes are rare and state-dependent. The system **monitors fragility
conditions** — situations where a market rebound could squeeze the recent-loser
leg — rather than claiming perfect crash prediction. Every number on the card is
deterministic; the language layer only phrases text.

## Minute 2–5 — Research foundation

Walk the four Phase 4 scorecard signals (macro high-volatility-recovery gate,
short-minus-long beta gap, long-short drawdown, short-loss-in-recovery). Point
out prior-only thresholds and the post-close cutoff: the card's `data_cutoff` is
the selected date's close, and no later information is used.

## Minute 5–9 — Interactive quantitative demo

Keep `AS_OF_DATE = 2024-01-05`, then change it (e.g. to `2026-05-29`) and Run
All. The risk state, signal values, and triggers recompute from the selected
date. Change `COMPARE_TO_DATE` and show the `Δ vs compare` column and the
**What changed** list update. This proves the output is computed, not fixed.

## Minute 9–14 — Evidence layer

On `2024-01-05`, section 6 shows real supporting, contradicting/moderating, and
missing evidence with timestamps and source locators. Emphasize:

- the LLM (when enabled) **organizes** evidence; it does not create the
  quantitative signal, and cannot change any number;
- evidence is point-in-time — nothing after the cutoff appears;
- on a date with no cache (e.g. `2026-05-29`) evidence fails safe to
  `unavailable` with a warning. Absence is uncertainty, not a benign finding.

## Minute 14–17 — Comparison and historical context

Section 5 summarizes the largest signal changes versus the comparison date.
Section 8 shows state-conditional tail-loss frequencies (`build_insurance_table`)
as descriptive base rates by regime — not a claim that history must repeat.

## Minute 17–20 — PM use and limitations

- **How a PM uses it:** read the state and triggered signals as a fragility
  watch, corroborate with point-in-time evidence, and track the monitoring
  questions.
- **What confirms the warning:** the monitoring questions in section 7.
- **What invalidates it:** the invalidation conditions in section 7 (beta gap
  falling back below threshold, drawdown recovering, macro gate exiting
  recovery, contradicting evidence outweighing support).
- **What productionization needs:** an archived point-in-time content corpus, a
  real guarded model invocation, a point-in-time universe, and approved policy
  thresholds (see `docs/phase_6a_review.md` and `NEXT_STEPS.md`).
