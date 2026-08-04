# AI value comparison summary

Concrete comparison for the primary frozen case (**2026-05-29 semi-unwind**).
This is not a claim that AI creates incremental PM alpha. It shows how the
evidence layer changes the **read** without changing deterministic metrics or
thresholds.

## Guardrails already demonstrated

- Deterministic scorecard values, thresholds, triggers, and mechanism states are
  immutable to the interpretation layer (`quant_fields_unchanged = True` in
  `ai_value_review.csv`).
- Evidence is timestamp-controlled (`evidence_cutoff_valid` checks).
- Missing credentials or schema failure falls back to deterministic narrative.
- External LLM runs in the worksheet remain optional; human-score columns stay
  blank until reviewed.

## Evaluation status

The retained worksheet does **not** demonstrate measured incremental LLM value.
For the May 29 `theme_proxy` case, the LLM arm is `not_run`,
`external_llm_called=False`, the active-pipeline evidence count is zero, and
the human score columns are blank. The comparison below therefore demonstrates
the value of an **evidence-assisted interpretation design** using the separate
human-curated `CSU-*` pack; it must not be described as an evaluated live-model
uplift result.

## Compact comparison — May 29 primary case

| Layer | What the PM sees | What changes? |
|---|---|---|
| **Deterministic-only monitoring** | Scorecard triggers inactive; `crowded_theme_unwind` triggered; concentration triggered; mechanical state `FRAGILITY_BUILDING`; absorption failure absent; DM recovery crash incomplete | Source of truth for risk state |
| **Evidence-assisted interpretation** | Same quantitative state, plus stance-labeled text: recovery backdrop (`CSU-2026-015`), contradicting operating strength (`CSU-2026-008`), and explicit missing items (forced deleveraging, absorption failure, loser rebound) | Narrative organization only |
| **What the evidence / AI layer added** | Separated DM vs Khandani–Lo vs fundamental lenses; located risk in long-side crowding rather than short-leg recovery pain; listed inspect-next / invalidation checks | Interpretation richness |
| **Unsupported inference avoided** | Did **not** rewrite inactive scorecard triggers into a crash call; did **not** treat contextual Prime Book / capex items as stance-confirmed support; did **not** claim forced deleveraging | Safety |
| **Contradictory evidence surfaced** | Strong supplier / operating results (`CSU-2026-008`) retained against a broad negative fundamental thesis | Challenge step |
| **Still requires human review** | Whether the correlated-theme proxy maps to an economic semiconductor theme; whether post-cutoff market moves deserve a refreshed as-of run; whether positioning overlays would confirm or refute localized unwind | PM judgment |

## Bottom line

Deterministic monitors decide the state. The evidence layer (deterministic
template or optional LLM) organizes supporting, contradicting, and missing
material so the PM can challenge the signal before acting. It does not create a
crash probability or change a threshold.

## Human PM-usefulness review

A compact human review of the frozen May 29 case scored it **16/18** on a
0–3 rubric: mechanism discrimination 3, portfolio linkage 2, evidence
grounding 3, contradiction coverage 3, next-diagnostic usefulness 3, and
brevity 2. The main deduction was deliberate: the default book and statistical
cluster are not a validated semiconductor portfolio or observed common
ownership. This is a review of the completed case pack, not an LLM benchmark
and not evidence of incremental alpha.

Worksheet detail: `ai_value_review.csv` and `ai_inputs/`.
Episode interpretability: `episode_fingerprints.md`.
