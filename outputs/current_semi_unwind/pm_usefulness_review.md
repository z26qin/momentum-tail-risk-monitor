# PM usefulness review

**Artifact reviewed:** `pm_case_read.md`  
**Scale:** 0 absent · 1 generic · 2 useful · 3 directly decision-supportive

| Dimension | Score | Rationale |
| --- | ---: | --- |
| Mechanism discrimination | 3 | DM, Khandani–Lo, and fundamental repricing are assessed independently, with explicit support and contradictions. |
| Portfolio linkage | 2 | The read identifies long-side crowding, concentration, drawdown, and mechanical fragility, but the default book is not a validated semiconductor portfolio. |
| Evidence grounding | 3 | Structured facts are frozen from the repository and text claims cite evidence IDs with timestamp and hash controls. |
| Contradictory evidence | 3 | Strong supplier results, healthy breadth, no short reversal, and no absorption failure are retained prominently. |
| Next-diagnostic usefulness | 3 | Three bounded propagation diagnostics and three invalidation conditions are stated. |
| Brevity | 2 | The three-sentence current read is compact, but the full handoff remains longer because staleness and attribution caveats are material. |

**Total:** 16 / 18

## Main usefulness limit

The pack is decision-supportive for the **May 29 default momentum book**, but not for the current August semiconductor selloff. Its most important finding is the boundary: the repository detects statistical long-cluster fragility but does not possess current-date or economic semiconductor-theme attribution.

## Day 2 prompt issues — recorded, not tuned

1. Require an explicit `structured_date`, `evidence_cutoff`, and `current_market_date` comparison before any use of “current.”
2. Require the response to distinguish statistical cluster, economic theme, sector, and factor propagation.
3. Require direct versus second-hand positioning evidence to be labeled separately.
4. Require every mechanism claim to list one supporting and one contradicting fact, or state that one side is missing.
5. Prevent a triggered correlated-theme proxy from being paraphrased as observed crowding or forced liquidation.
6. Require a distinct “cannot adjudicate post-cutoff events” response when market events occur after the structured date.

No prompt, source module, threshold, schema, or PM category was changed on Day 1.
