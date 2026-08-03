# Day 2 Stage A — LLM Calibration Audit Baseline Review

**Branch:** `main`  
**Commit:** `ecd75312afd0c44e4b2e208e4b5a853007aeed68`  
**Working tree:** clean at Stage A start  
**Assessment case:** frozen May 29, 2026 (Day 1 pack)  
**Live provider credentials:** none (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` unset)

Stage A created only this directory’s diagnostic artifacts. No production source, tests, notebooks, Day 1 artifacts, thresholds, or pipeline logic were modified.

---

## Repository and Day 1 prerequisites

| Check | Result |
| --- | --- |
| Day 1 structured snapshot / evidence pack / annotations / outputs | Present |
| Human-confirmed rows | `ANN-001`, `ANN-003`, `ANN-004`, `ANN-005`, `ANN-008` |
| ANN-003 CSV parse | Title contains an unquoted comma (`MacroMemo — May 5–25, 2026`); standard `csv.DictReader` misaligns columns. Labels were recovered from the same file fields (not inferred). |

---

## A1. Current contracts

### Prompt / schema versions

| Layer | Schema | Prompt | Deterministic fallback |
| --- | --- | --- | --- |
| Evidence interpretation | `evidence-interpretation-v1` | `evidence-interpretation-prompt-v1` | `deterministic-evidence-interpretation-v1` |
| PM response | `pm-response-v1` | `pm-response-prompt-v1` | `deterministic-pm-response-v1` |

### EvidenceInterpretation output fields

`narrative_state`, `narrative_changes`, `supporting_evidence_ids`, `contradicting_evidence_ids`, `missing_or_uncertain_evidence`, `pm_interpretation`, `monitoring_questions`, `invalidation_conditions` (+ `use_llm`, `model_or_prompt_version`, `warnings`).

### PMResponse output fields

`current_posture`, `main_vulnerability`, `what_would_change_the_reading`, `conditional_response`, `why_not_act_yet`, `response_categories` / model field `selected_categories`.

### Evidence-ID validation

- Supporting IDs must exist **and** have `stance == "supporting"`.
- Contradicting IDs must exist **and** have `stance == "contradicting"`.
- Unknown or stance-inconsistent IDs are removed with a warning.
- Empty evidence clears citations and adds uncertainty text.
- **Contextual evidence cannot be cited in either ID list.**

### Prohibited claims

Interpretation rejects numeric literals/number-words; causal/certainty language (`caused`, `proves`, crash certainty); trade/recommendation language.  
PM response additionally rejects ticker/size hints and execution language; categories must stay on the deterministic allow-list.

### Deterministic fallback

- No credentials → fallback + warning; provider not called.
- No interpreter → fallback + warning.
- Schema/safety failure → fallback + warning.
- Fallback interpretation uses triggered quant signals + evidence stance counts only.
- Fallback PM uses `derive_pm_context` over scorecard + **structural** unwind.

### Length limits

- Narrative fields: 600 chars.
- List items: max 8; item max 300 chars.
- LLM interpretation: 3–5 monitoring questions; 2–4 invalidation conditions.
- LLM PM: 1–5 change lines; 1–6 conditional lines.

### How channels enter context

| Channel | EvidenceInterpretation | PMResponse |
| --- | --- | --- |
| Market backdrop / quant signals | Yes (`quantitative_signals`, risk state) | Yes (triggered / non-triggered) |
| Retrieved evidence | Yes | **No** |
| Historical analogs | Yes | No |
| Structural unwind / mechanisms | **No** | Yes (`mechanism_statuses`, `unwind_triggers`, active scenarios) |
| Mechanical unwind / absorption | **No** | **No** |

### Prompt design gaps vs Day 2 target

11. Current prompts do **not** explicitly compare DM, KL, and Fundamental lenses.  
12. Supporting vs contradicting fields exist and are separate; unconfirmed/missing is a third list. Contextual items have **no citation channel**.

---

## A2. Frozen May 29 runs

### Deterministic facts (live replay matches Day 1 snapshot)

- Quant triggers: none (`overall_risk_state = normal`).
- Structural: `crowded_theme_unwind = triggered`; `bear_market_recovery_crash = watch`; `short_book_reversal_crash = not_confirmed`.
- Mechanical: `FRAGILITY_BUILDING`; `liquidity_absorption_failure = false`.
- PM posture/vulnerability: `escalate_for_pm_review` / `long_side_crowding`.

### Path 1 — LLM path

No live credentials. Used the repository’s injected structured-response mechanism with a **context-faithful** payload (only fields visible in `_model_context`).

Artifacts:

- `evidence_interpretation_llm.json`
- `pm_response_llm.json`

### Path 2 — Deterministic fallback

Artifacts:

- `evidence_interpretation_fallback.json`
- `pm_response_fallback.json`

### Path contrast (May 29)

| Layer | Fallback | Injected LLM (context-faithful) |
| --- | --- | --- |
| Interpretation state | “No implemented fragility condition is currently triggered.” | Same core fact: no quant trigger; mixed text evidence |
| Supporting IDs | `CSU-2026-015` | `CSU-2026-015` |
| Contradicting IDs | `CSU-2026-008` | `CSU-2026-008` |
| Contextual KL/capex IDs | Not citable | Not citable (`CSU-2026-013/004/005` stripped if forced into supporting) |
| Structural crowded-theme trigger | **Invisible** to interpretation | **Invisible** to interpretation |
| Mechanical fragility / absorption | **Invisible** to both LLM layers | **Invisible** to both LLM layers |
| PM posture | Escalate; long-side crowding | Escalate; long-side crowding (structural visible to PM) |

---

## A3. PM usefulness scores

Scale: 0 absent · 1 generic · 2 useful · 3 directly decision-supportive.

Reference quality: Day 1 human `pm_case_read.md` / `mechanism_comparison.md`.

### EvidenceInterpretation — fallback

| Dimension | Score | Notes |
| --- | ---: | --- |
| Mechanism discrimination | 0 | No DM / KL / Fundamental separation |
| Structured-text alignment | 1 | Aligns to quant non-triggers only; misses triggered structural channel |
| Portfolio linkage | 1 | Generic monitored-signal language |
| Supporting-evidence use | 1 | Stance filter keeps only `CSU-2026-015` |
| Contradicting-evidence use | 2 | Keeps `CSU-2026-008` |
| Unconfirmed-evidence clarity | 1 | Generic / incomplete on contextual items |
| Next-diagnostic usefulness | 1 | Generic threshold / evidence questions |
| Invalidation clarity | 1 | Generic trigger-reversal language |
| Boundedness | 3 | Safe; no trade/causal overclaim |
| Brevity | 3 | Short |

### EvidenceInterpretation — injected LLM (current prompt contract)

| Dimension | Score | Notes |
| --- | ---: | --- |
| Mechanism discrimination | 1 | Mentions recovery vs operating strength; no explicit three-lens adjudication |
| Structured-text alignment | 1 | Cannot align to crowded-theme / mechanical state (absent from context) |
| Portfolio linkage | 1 | Limited to non-triggered quant signals |
| Supporting-evidence use | 1 | Only supporting-stance ID retained |
| Contradicting-evidence use | 2 | Explicit |
| Unconfirmed-evidence clarity | 2 | Names contextual / missing structured channels |
| Next-diagnostic usefulness | 1–2 | Better than fallback, still mostly generic |
| Invalidation clarity | 2 | Observable but incomplete vs Day 1 pack |
| Boundedness | 3 | Passes safety gates |
| Brevity | 3 | Within limits |

### PMResponse — fallback / injected LLM

| Dimension | Score | Notes |
| --- | ---: | --- |
| Mechanism discrimination | 1 | Posture/vulnerability reflect structural crowding, not full three-lens text adjudication |
| Structured-text alignment | 1 | No retrieved evidence in PM context; no mechanical absorption |
| Portfolio linkage | 2 | Correct long-side crowding / escalate posture |
| Supporting / contradicting / unconfirmed | 0–1 | Not evidence-ID aware |
| Next-diagnostic usefulness | 2 | Change-signals tied to mechanisms/signals |
| Invalidation clarity | 2 | Confirmation-gated |
| Boundedness | 3 | Allow-listed; trade/execution rejected |
| Brevity | 3 | Compact |

### Scores below 2 — root causes

| Gap | Observed | Why insufficient | Smallest fix | Root cause |
| --- | --- | --- | --- | --- |
| Interpretation misses crowded-theme trigger | Fallback: “no fragility triggered” while `crowded_theme_unwind` is triggered | Contradicts Day 1 PM read | Supply structural (and mechanical) status into interpretation context | **structured-data problem** |
| Mechanical / absorption absent | Neither LLM context includes `FRAGILITY_BUILDING` / absorption | Cannot bound KL vs liquidity failure | Plumb mechanical summary into context | **structured-data problem** |
| Contextual KL/capex not citable | `CSU-2026-013/004/005` removed from supporting | Human-confirmed KL/fundamental context cannot ground claims via ID fields | Allow contextual IDs in a dedicated citation path, or relax stance filter for contextual | **schema limitation** |
| No three-lens comparison | Prompts never require DM/KL/Fundamental | Mechanism discrimination stays generic | Prompt v2 three-lens checklist | **prompt problem** (secondary) |
| Generic monitoring questions | “Do triggered conditions remain…?” | Not diagnostic for propagation / absorption / revisions | Prompt for concrete diagnostics | **prompt problem** (secondary) |
| No live provider | Credentials absent | Cannot observe production model wording variance | Use approved provider when available | **provider instability** / availability |
| ANN-003 CSV mis-parse | Unquoted comma in title | Fragile gold-label loading | Quote the title field in Day 1 CSV (data fix; outside Stage B source scope) | **evidence problem** |

**Probe:** forcing contextual IDs into `supporting_evidence_ids` yields warning:  
`Unsupported or stance-inconsistent evidence IDs were removed: CSU-2026-004, CSU-2026-005, CSU-2026-013.`

Overclaim probes (`proves`, `should sell`, `caused`, execution language) fail closed as designed.

---

## A4. Boundedness cases (injected provider)

All five cases used the existing FixedInterpreter pattern. Pass = accepts bounded mechanism-separating output **and** rejects prohibited overclaim where tested.

| Case | Mechanism conclusion | Overclaim handling | Pass/Fail |
| --- | --- | --- | --- |
| 1 Strong KL | KL supported; DM/Fundamental unconfirmed | Forced-deleveraging + trade language rejected | **PASS** |
| 2 DM recovery | DM supported; KL unconfirmed | Causal forced-deleveraging rejected | **PASS** |
| 3 Fundamental only | Fundamental supported; KL/DM unconfirmed | No broad-factor claim in accepted payload | **PASS** |
| 4 Mixed | Mixed/partial; contradiction explicit | `proves` language rejected | **PASS** |
| 5 Insufficient | Uncertainty; hallucinated IDs removed; fallback works | Hallucinated support stripped | **PASS** |

Boundedness of **safety gates** is strong. Boundedness of **mechanism usefulness on May 29** is limited by missing context and contextual-ID rules, not by weak reject logic.

---

## A5. Smallest change-set diagnosis

1. **Is the main problem prompt wording?** No. Primary failure is missing structural/mechanical context in `EvidenceInterpretation`, plus inability to cite contextual human-confirmed IDs.
2. **Is required mechanical or portfolio context already supplied?** Portfolio quant signals: yes. Structural unwind: to PM only. Mechanical unwind/absorption: to neither LLM layer.
3. **Can the issue be fixed without a new field or schema?** Prompt-only can improve lens language over text evidence, but cannot surface `crowded_theme_unwind` or absorption inside interpretation. Plumbing context requires `pipeline.py` (read-only) and/or schema/context expansion.
4. **Is deterministic fallback already acceptable?** Acceptable as a safe offline floor; **not** acceptable as a May 29 PM-useful mechanism read (it denies triggered fragility that exists structurally).
5. **Would a prompt change materially improve the May 29 read?** Marginally for text lenses; **not** for the core structured alignment gap.
6. **Could a stronger prompt increase false confidence?** Yes — if it asks the model to adjudicate channels it cannot see, it invites hallucination of structural/mechanical facts.

### Proposed change inventory (not executed)

| Area | Proposal | Stage B fit? |
| --- | --- | --- |
| Prompt | Three-lens checklist; fact vs interpretation; concrete monitors/invalidations | Possible, but insufficient alone |
| Validation | Allow contextual IDs to be cited without calling them “supporting” | Small guard possible in interpretation module |
| Fallback wording | Mention that structural/mechanical channels are outside this layer | Cosmetic; does not fix context gap |
| Context plumbing | Pass structural + mechanical summaries into interpretation (and mechanical into PM) | **Requires pipeline / broader change — out of Stage B scope** |
| Files if Stage B were forced | `evidence_interpretation.py` ± `pm_response.py` ± one test | Max scope still cannot fix pipeline-gated context |
| Expected line scope | Prompt block + optional contextual-ID handling | < ~80 lines if attempted |
| Tests | `tests/test_evidence_interpretation.py` | Only if validation changes |
| Do not modify | `pipeline.py`, thresholds, notebooks, Day 1 pack, mechanical engines | Contract |

---

## Stage A recommendation

```text
D. Stop — limitation is evidence, context, schema, or provider related
```

### Why not A / B / C

- **A:** Fallback and current prompts are not May 29 PM-useful at Day 1 human quality.
- **B:** Prompt-only calibration cannot expose structural/mechanical channels absent from interpretation context; risk of false confidence.
- **C:** A contextual-ID citation guard would help grounding, but still would not let interpretation see the triggered `crowded_theme_unwind` or mechanical absorption state without context plumbing.

### Smallest future step (after Day 2)

1. Quote-fix ANN-003 title in the annotation CSV (data integrity).  
2. Add a read-only structural + mechanical summary to the interpretation model context via an approved pipeline-adjacent change.  
3. Only then do **one** prompt-version increment requiring explicit DM / KL / Fundamental adjudication with evidence-ID citations.

### Explicit non-actions

- No Stage B production edits without approval.  
- No new provider, schema object, agent, benchmark framework, or PM category.  
- No overwrite of Day 1 outputs.  
- No commit or push.

---

## Artifact index

```text
outputs/current_semi_unwind/day2_baseline/
  evidence_interpretation_llm.json
  pm_response_llm.json
  evidence_interpretation_fallback.json
  pm_response_fallback.json
  baseline_review.md
```

**Stop for explicit user approval before any Stage B work.**
