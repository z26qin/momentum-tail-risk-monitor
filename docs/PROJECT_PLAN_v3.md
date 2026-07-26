# PROJECT PLAN & SYSTEM DESIGN v3 — Momentum Tail-Risk (Millennium Global Macro Pod)

> **Implementation status, 2026-07-26:** the streamlined MVP described by the
> pivot is now implemented through `src/pipeline.py`. B2 is a shadow benchmark,
> the heuristic checklist is experimental, real FINRA/GDELT overlays are wired
> into one PM brief, and evidence is explicitly fixture replay. The remaining
> production gaps are tracked in `NEXT_STEPS.md`.

Supersedes PROJECT_PLAN_v2.md and the plan sections of PROJECT_HANDOFF.md. Self-contained: this is the document to travel with.

Last updated: 2026-07-24. Review meeting ~week of Aug 10 (3-week window granted).

---

## 0. The pivot

**v2 was still building a model.** v3 does not.

The prototype's purpose is to demonstrate an AI-assisted workflow that fuses structured and unstructured alternative data into something a PM can use daily. Re-deriving the momentum-crash phenomenon is not that. Daniel-Moskowitz (2016) is published, peer-reviewed, and better known to a Millennium macro pod than to us. Reproducing it consumes budget and demonstrates nothing the reviewer doesn't already believe.

**Therefore:** the risk state is defined by the DM 2016 rule, adopted directly. No fitted model, no ladder, no freeze manifest, no purged walk-forward, no bootstrap CIs on ΔPR-AUC. That machinery existed to prevent overfitting; with nothing fitted, it has no job.

**What this does NOT mean.** Validation is an explicit Required Element: *"reasonable baselines, ablations, leakage controls, and at least one implemented or illustrative validation test."* It does not go to zero — it changes target:

| | Old target | New target |
|---|---|---|
| Question | Does my model beat baseline at predicting crashes? | Is this system's output trustworthy and useful? |
| Risk | Answer may be null; reads as a failed research project | Directly answers the stated evaluation criterion |
| Cost | ~4h | ~1.25h |

The assignment's stated interest is *"whether AI materially improves the research or risk-monitoring process."* Validating the AI layer is closer to that question than validating a logistic regression was.

**One cheap insurance item retained (~30 min).** A single table: unconditional tail-loss frequency vs frequency conditional on DM panic state, full sample, using Phase 1 data and state variables that already exist. This is not re-research. It demonstrates the rule was *verified in our own data* rather than cargo-culted — a distinction that matters when the PM asks "did you check?"

---

## 1. Architecture

Four components. Two of them are deterministic and auditable; two are AI and human-judged. The boundary is the most important thing in the System design section.

```
   STRUCTURED                    UNSTRUCTURED
   ├── Ken French UMD, legs      ├── GDELT timeline panel (attention/tone)
   ├── FRED VIXCLS               └── GDELT GKG article-level corpus
   └── FINRA positioning
                    │                          │
                    ▼                          ▼
        ┌───────────────────────────────────────────────┐
        │  [1] RISK STATE  — deterministic, no LLM      │
        │      DM 2016 panic-state rule                 │
        │      → state, conditional probability,        │
        │        conditional severity                   │
        └───────────────────────────────────────────────┘
                    │
                    ▼
        ┌───────────────────────────────────────────────┐
        │  [2] OVERLAYS — deterministic, no LLM         │
        │      structured: loser-leg crowding           │
        │      unstructured: narrative attention/tone   │
        │      → confirm / sharpen / contradict         │
        └───────────────────────────────────────────────┘
                    │
                    ▼  (triggered only when state elevated)
        ┌───────────────────────────────────────────────┐
        │  [3] EVIDENCE + ANALOG — LLM, human-judged    │
        │      retrieval → cited driver attribution     │
        │      top-k historical analogs                 │
        │      contradiction flagging                   │
        └───────────────────────────────────────────────┘
                    │
                    ▼
        ┌───────────────────────────────────────────────┐
        │  [4] PM BRIEF — generated daily artifact      │
        └───────────────────────────────────────────────┘
```

### [1] Risk state — deterministic

**Rule (adopted, not derived).** DM 2016 panic state: bear market condition × elevated market volatility, with the momentum portfolio's negative beta in that state as the mechanism. Phase 1 already encodes this as `bear_state` (cumulative market return over the trailing ~24 months < 0) and `mkt_variance_126d`.

> **Travel action item:** verify the exact parameterization against the DM 2016 PDF in your packet and cite it precisely in the memo. Do not restate the paper's thresholds from memory or from this document.

**Probability, without fitting.** Given the state classification at date t, the probability is the *empirical conditional frequency* of a forward h-day tail loss in that state, computed from history available at t only (expanding, PIT). No parameters, no training. A PM can reproduce it with a spreadsheet.

**Severity, from the same object.** The conditional distribution of forward h-day UMD returns in that state: report the mean and the 5th percentile, with the conditioning sample size. Reported as a range with its n, never as a point forecast.

Horizon: h = 20 primary, h = 5 secondary.

**Why this is the right choice, stated in the memo:** conventional methods are more appropriate here than AI. The state rule is transparent, literature-anchored, has a century of data behind it, and cannot silently overfit. AI is deployed where it is genuinely better — reading unstructured text at volume and assembling traceable explanation.

### [2] Overlays — deterministic

Neither overlay changes the risk number. They confirm, sharpen, or contradict it, and they feed the evidence layer as context.

**Structured — loser-leg crowding.** The DM mechanism is the loser leg crashing up in a rebound. The observable precondition is a squeezed short leg, so this is direct measurement of the adopted mechanism, not a generic flow add-on.

- Proxy loser leg: fixed liquid universe (~150-200 US large/mid caps), monthly 12-2 momentum ranking from free daily prices, bottom decile. Labeled a proxy; survivorship bias flagged (current list applied historically).
- `si_ratio`: short interest / shares outstanding, equal-weighted across the leg, **joined on publication date**, step function between prints.
- `short_vol_share`: daily short volume / total volume, equal-weighted, 5-day mean.
- Both as 126-day rolling z-scores for interpretability.

**Unstructured — narrative attention.** 5 mechanism-level GDELT queries (panic / rotation / policy / crowding / risk-off), timeline volume and tone, 126-day rolling z. Serves as a monitoring indicator and as the input to the lead-time check. The article-level GKG corpus serves retrieval.

### [3] Evidence + analog — AI, human-judged

**Trigger.** Fires only when the risk state is elevated. Cost discipline and analytical discipline both.

**Two-track rule (unchanged, load-bearing).** Backtest track uses archived PIT sources (GDELT GKG same-day discovery + content fetch). Production track uses live retrieval. Tracks never cross — a live index searched today returns retrospectives about 2020, not the information set of 2020. This single point is one of the strongest things in the memo; it shows PIT thinking applied to *text*, which most people only apply to prices.

**Inputs.** Retrieved article-level text, current state variables, current positioning snapshot, top-k analogs.

**Output.** Driver attribution in which every claim carries a citation to a timestamped source.

**Guardrails.**
1. The evidence layer cannot modify the risk number.
2. Claims without a retrievable citation are dropped, not paraphrased.
3. If evidence contradicts the state read, the system flags the contradiction for human review rather than reconciling it silently.

**Minimal agent loop.** trigger → retrieve → call analytics tool (leg decomposition, positioning snapshot) → draft attribution → self-check each claim against its citation → one re-query if uncited or contradicted → emit with flags. One loop, one re-query, bounded. Satisfies the optional agentic element without scope creep.

**Analog layer.** Joint market-state + narrative embedding, top-k historical episode retrieval.

### [4] PM brief — the usable artifact

Generated by the pipeline, not hand-written, for **multiple days** (a quiet day and an elevated day at minimum) so the reviewer sees the system running rather than a single staged example.

Contents: risk horizon; state classification; conditional probability with its sample size; conditional severity range; structured overlay read (crowding); unstructured overlay read (narrative); primary drivers with citations; closest historical analogs; graduated action (de-gross / hedge short-leg convexity / tighten review); **what would change this assessment** (explicit invalidation conditions); human review points marked inline; contradiction flags if any.

---

## 2. Validation — relocated

Four items. All implemented; none requires model fitting.

1. **Leakage controls (already built, extend).** Maturity rule on labels; positioning joined on publication date not settlement date; text mapped to the prior-trading-day information set; automated assertion that no retrieved document postdates the assessment date. The settlement-date trap is worth a paragraph: the naive join embeds ~2 weeks of look-ahead and looks entirely innocuous.

2. **Baseline separation (the insurance table, ~30 min).** Unconditional tail-loss frequency vs DM-panic-state conditional frequency, full sample. Confirms the adopted rule separates in our data.

3. **Ablation at the usability level.** On known crash episodes: does the DM state alone flag them? Do the structured and unstructured overlays add lead time or reduce false alarms? Reported descriptively, episode by episode — not as a day-level metric with confidence intervals, which the sample cannot support and which would misrepresent the evidence.

4. **AI-layer validation (the distinctive part).**
   - *Retrieval PIT correctness:* automated — zero retrieved documents postdate the assessment date.
   - *Analog check:* do top-k analogs' forward returns skew left relative to matched random draws?
   - *Attribution faithfulness:* sample generated claims, verify each against its cited source, report the rate.

5. **What is not validated.** Stated explicitly: no out-of-sample predictive claim is made for the overlays; the positioning proxy carries survivorship bias; the evidence layer is demonstrated on a small number of days; the analog check is a sanity check, not a performance claim.

---

## 3. Requirement → artifact traceability

Put this table in the README and the memo's opening.

| Required Element | Primary artifact |
|---|---|
| 1. Problem definition | Memo §1 — factor, tail event, horizon, user, decision informed |
| 2. Data design | Memo §2 + availability-calendar table; PIT tests |
| 3. System design | Memo §3 + architecture diagram; deterministic/AI/human-review boundary |
| 4. Proof of concept | Notebook: state engine + overlays + evidence demo on selected days |
| 5. Validation plan and evidence | Memo §4 + the four validation items above |
| 6. Example output | Generated PM briefs, multiple days |
| 7. Production path | Memo §5 + procurement table (borrow-fee data, RavenPack/Bloomberg, constituent data) |

---

## 4. Data availability calendar

| Family | Source | Reference stamp | Availability stamp |
|---|---|---|---|
| Market | French UMD, 6 portfolios, 10 deciles | trading day t | vendor file update (lagged; production concern) |
| Market | FRED VIXCLS | trading day t | same-day post-close |
| Unstructured | GDELT timeline | UTC calendar-day bucket | complete 00:00 UTC D+1 (~19-20:00 ET day D) |
| Unstructured | GDELT GKG article-level | article publish time | same-day |
| Structured | FINRA Daily Short Sale Volume | trade day t | **≤18:00 ET same day** |
| Structured | FINRA Short Interest | semi-monthly settlement | **~7th business day after settlement** |

Verified public facts (July 2026):
- FINRA Daily Short Sale Volume files are posted no later than 6:00pm ET of the same trade date; consolidated NMS files begin 2018-08-01.
- Those files cover only off-exchange trades reported to a TRF/ADF/ORF for public dissemination; they are not consolidated with exchange data; offsetting buys are not reflected, which inflates apparent short concentration; FINRA states explicitly they do not equate to short interest position data. Flow, not position.
- Short interest is reported twice monthly (mid-month settlement ~the 15th, and month-end), due to FINRA on the 2nd business day after settlement, published approximately the 7th business day after settlement.

**Not yet verified — do not write specifics into the memo until confirmed on 7/25:** FINRA Query API mechanics and rate limits for historical daily short-volume retrieval beyond the 365-day interactive window; the bulk download path.

---

## 5. Budget

Cap: "no more than approximately 20 hours." Spent to date ≈ 9h.

| # | Work | Hours | When |
|---|---|---|---|
| 1 | GDELT spike + schema probe + FINRA API check | 0.75 | 7/25 AM |
| 2 | GDELT panel acquisition (slim: 5 queries, timeline, z-scores, light sanity check) | 1.0 | 7/25 PM |
| 3 | Positioning vertical: universe, momentum ranks, FINRA pulls, crowding series | 1.5 | 7/26 |
| 4 | Travel package generation | 0.25 | 7/26 PM |
| 5 | Memo §1-3 handwritten, no Claude | 2.5 | 7/27-8/2 |
| 6 | Risk state module: DM rule + conditional probability/severity + insurance table | 1.0 | 8/3 |
| 7 | Validation suite (4 items) | 1.25 | 8/4 |
| 8 | Evidence layer + agent loop + analogs | 2.5 | 8/5-8/7 |
| 9 | PM brief artifact, multiple days | 1.25 | 8/8 |
| 10 | README + traceability table | 0.5 | 8/10 |
| 11 | Memo assembly | 1.0 | 8/11 |
| 12 | Slides + rehearsal | 0.75 | 8/12-8/13 |

Remaining ≈ 14.25h; cumulative ≈ 23h. Over "approximately 20." Trim options in order: memo offline 2.5 → 2.0; positioning 1.5 → 1.25; validation 1.25 → 1.0; slides 0.75 → 0.5. Lands ≈ 21.5h, which is defensible against "approximately." The README states the actual allocation — declaring it evidences scoping discipline rather than hiding overrun.

**Dropped from v2 (~2h recovered):** fitted model ladder B2c/B3a/B3b; freeze manifest; purged walk-forward with fixed folds; paired moving-block bootstrap and ΔPR-AUC CIs; heavy semantic audit with frozen LLM classifier and kappa; missingness gate protocol.

**Cut-list if still over:** evidence demo days 3 → 2 → 1; simplify analog check; drop tone overlay, keep attention only. **Never cut:** PIT/leakage tests, the baseline separation table, the generated PM brief, the two-track text rule.

---

## 6. Consequences for existing artifacts

- `claude_code_phase2_prompt_v3.md` is **obsolete**. Replace with a much lighter spec: acquisition + z-scores + monitoring overlay, no model, no freeze protocol.
- **Phase 1 is no longer a hard gate on everything**, but its outputs are still used: UMD series, leg reconstruction, episode definitions (for case-day selection), and the state variables feeding the conditional-frequency computation. The acceptance review is still worth doing — particularly leg reconstruction correlation and episode capture of 1932 / 2009 / Nov 2020 / Jan 2021 — but it no longer blocks the pre-departure data pulls.
- The GDELT spike on 7/25 remains the highest-priority pre-departure item: it is the last window to discover API surprises before a week without access.

---

## 7. Decisions to log

- Risk state adopted from DM 2016 rather than fitted. *Rationale: re-deriving published results consumes budget and demonstrates nothing to this audience; the assignment's interest is in AI-assisted workflow and judgment.*
- Probability and severity from PIT conditional empirical frequency, not a model. *Rationale: transparent, reproducible by hand, cannot overfit.*
- Validation retargeted from predictive performance to system trustworthiness. *Rationale: Required Element 5 remains satisfied; the new target is closer to the stated evaluation criterion.*
- Baseline separation table retained despite the pivot. *Rationale: demonstrates the adopted rule was verified in our data, not cargo-culted.*
- Positioning framed as structured alternative data feeding monitoring and evidence, never a fitted feature. *Rationale: publication lag, off-exchange-only coverage, 2018-08 start.*
- Positioning joined on publication date. *Rationale: settlement-date join embeds ~2 weeks of look-ahead.*
- Overlays reported descriptively at episode level, not as day-level metrics with CIs. *Rationale: the sample cannot support inferential claims; presenting them as if it could would misrepresent the evidence.*
