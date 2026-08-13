# Architecture to PM value

Internal map from MVP components to PM questions. For the PPT-backed product
demo, start with `README.md` and `notebooks/final_mvp_demo.ipynb` (the
step-by-step 2026-05-29 runbook). For why each risk metric exists, why its
threshold is set that way, and what a numerical move means, see
[`docs/wiki/README.md`](wiki/README.md).

| Existing component | PM question | Implemented value | Current evidence | Remaining limitation |
| --- | --- | --- | --- | --- |
| DM market state | Is the environment historically fragile for momentum? | Literature-aligned regime context for UMD | Existing conditional UMD history; demo / regression dates | Not a full paper replication |
| PM scorecard | Is the monitored book under stress? | Book-specific diagnostics (beta gap, drawdown, short loss, recovery gate) | Deterministic four-row outputs in `run_mvp` | Synthetic survivorship-biased S&P 10/10 book |
| Mechanism monitor | Where may losses originate? | Separates recovery, short squeeze, and long-theme unwind | `outputs/research_validation/episode_fingerprints.*` | Limited OOS validation; no historical mechanism series yet |
| Evidence retrieval | What public information fits the date? | Timestamp-valid context with hard cutoff | Exact-date fixtures / classified caches | Not live institutional retrieval |
| LLM synthesis | What should the PM inspect next? | Structured, evidence-constrained narrative compression | Safe interface + deterministic fallback; `ai_value_review.csv` | Incremental usefulness requires human review of real LLM runs |

## How to read the research-validation artifacts

1. **Episode fingerprints** — interpretability check that the three mechanisms
   leave different fingerprints on known episodes. Priors never enter computation.
2. **PM-book outcomes** — deliberately skipped until mechanism history is
   persisted (`pm_book_outcomes.md`).
3. **AI value worksheet** — compares quant-only facts, the deterministic
   template, and the optional LLM path without inventing evaluation scores.

## Bottom line

The stack is built to keep quantitative state immutable and explanations
swappable. Episode fingerprints support mechanism interpretability; AI
incremental value remains a testable hypothesis until reviewed LLM runs fill
the human-score columns.
