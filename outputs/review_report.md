# MVP review against the take-home assignment

> **Historical snapshot.** This review describes the repository before the
> 2026-07-26 streamlined MVP implementation. Its primary findings drove the new
> `src/pipeline.py`, DM/PIT primary state, real overlay integration, PM briefs,
> and logical archive. Consult the root README and `NEXT_STEPS.md` for current
> status.

Reviewer stance: skeptical quant at a global macro pod. Read-only session, 2026-07-25.
Everything below cites a path; where I could not find evidence I say "not found."
Test counts were verified by running the suite this session, in two states: the build
worktree with full caches (121 passed, 1 skipped) and this clean checkout, which is
what a cloning reviewer gets (1 failed, 118 passed, 3 skipped).

## Executive summary (ten lines)

1. **Overall state in one sentence:** the data foundations and point-in-time discipline are genuinely strong, but the system the v3 plan promises — DM risk state, conditional probability, wired-in overlays, evidence layer, PM brief — does not exist yet, and what monitoring code does exist implements the architecture the project formally abandoned.
2. **Most serious gap #1:** the risk state of record in the repo is the *fitted B2 logistic regression* ([risk_state.py:35](src/monitoring/risk_state.py), `outputs/debug/risk_state_2009-03-06.json` serves `risk_probability: 0.7917`), while README.md:159-162 and PROJECT_PLAN_v3 §0 declare "there is no fitted model in this project." An interviewer who opens one debug file catches the contradiction in thirty seconds.
3. **Most serious gap #2:** the three legs never meet. Nothing in `src/monitoring/` or `src/evidence/` reads `positioning_panel.parquet` or `narrative_panel.parquet` (verified by grep — zero references). The assignment's core ask is a system that *combines* market, text, and positioning; today it is three well-built parts and no junction.
4. **Most serious gap #3:** the one cheap validation PLAN_v3 calls load-bearing — the conditional-vs-unconditional tail-loss frequency table proving the adopted DM rule separates in this data — is not found anywhere, so "did you check?" currently has no answer.
5. **Also material:** the narrative leg is 2 of 5 mechanisms, volume-only, no tone, query precision unassessed, and its raw GDELT payloads exist only on the build machine (git-ignored, `.gitignore:15-18`), which is why one determinism test fails on a fresh clone.
6. **Most likely to impress:** the point-in-time discipline applied to *unconventional* joins — FINRA short interest gated on reconstructed publication dates with a test proving settlement dates cannot drive the join ([test_positioning_pit.py:88-99](tests/test_positioning_pit.py)), GDELT buckets mapped to next-trading-day availability, and a self-review log that caught four real data defects before anyone else could.
7. **Most likely to get attacked:** the coexistence of two architectures — a repo that says "nothing is fitted" while shipping fitted-model machinery, folds, freeze hashes, and a 79% fitted probability in its own example output.
8. Docs are internally inconsistent: NEXT_STEPS.md:91-94 asserts "No risk state module … evidence layer … or PM brief" exists, but `src/monitoring/risk_state.py` and `src/evidence/` are in the tree and committed.
9. Deliverables status: PoC package exists; memo, presentation, and PM brief are expected-missing per the PLAN_v3 §5 schedule (due 7/27-8/13); `main` (587a099) does not yet contain the overlays or the v3 plan — everything new sits on `dear/*` branches.
10. Budget — **corrected by the operator after first issue**: the existing repo accounts for ≈4h of the ~20h cap, not the ≈9-14h implied by `PROJECT_PLAN_v3.md` §5 ("spent to date ≈ 9h", now superseded). ≈16h remain; the punch list in Part 5 fits without the trims originally recommended.

---

## Part 1 — Requirement scorecard

| Element | Status | Evidence (paths) | What specifically remains |
|---|---|---|---|
| 1. Problem definition | **satisfied** (in docs; memo pending) | `docs/DECISIONS.md:5-31` (PM user, drawdown limits, three decisions: de-gross / hedge short-leg convexity / tighten review), horizons h=5/20 (`docs/DECISIONS.md:45`), tail event = PIT 5th-percentile forward UMD loss (`docs/DECISIONS.md:56-100`) | Memo §1 restating it in 1 page; PLAN_v3 §3 traceability table not yet in README |
| 2. Data design | **partial** | Availability calendar: `PROJECT_PLAN_v3.md` §4, `outputs/data_review.md` §6; per-source rationale and quality: `outputs/build_log.md` Stage 1, `docs/DECISIONS.md:748-1156`; leakage channels named per source | Text leg is thin (see below); memo §2; FINRA daily-file coverage starts 2018-08 — stated, fine |
| — 2a. Market leg | **satisfied** | Tracked raw ZIPs + SHA256 manifest (`data/raw/manifest.json`), Task 1 audit `docs/DECISIONS.md:279-315`, UMD reconstruction corr 0.99999 | Nothing material |
| — 2b. Positioning leg | **satisfied** | `data/processed/positioning_panel.parquet` (2,402 dates, 200/200 symbol match), publication-date join (`docs/DECISIONS.md:857-890`), flow-vs-position paragraph (`docs/DECISIONS.md:891-904`), three crowding variants adjudicated (`docs/DECISIONS.md:1022-1155`) | Consumed by nothing downstream (see Element 3) |
| — 2c. Text leg | **built-but-deficient** | `data/processed/narrative_panel.parquet`: 2 of 5 mechanisms, volume only, tone entirely NaN, breadth undefined (`outputs/narrative_poc_review.md:90-101`); `precision_flag = "unassessed"` — nobody has read one returned headline (`outputs/data_review.md:159-169`); raw payloads absent from git | Acquire `crowding`+tone when GDELT unblocks (externally gated); run `src/data/gdelt_sanity.py`; or explicitly demote the leg to "prototype" in the memo |
| 3. System design | **built-but-deficient** | Intended design: `PROJECT_PLAN_v3.md` §1 (clear, good). Actual code: `src/monitoring/risk_state.py` serves the **abandoned** B2 model; `src/monitoring/domain_risk.py` is a checklist with hand-set thresholds (−10%, 0.80, 3%; lines 28-34) matching neither DM 2016 nor PLAN_v3; overlays feed nothing; evidence layer consumes a French-decile *dispersion proxy* as "positioning" (`src/monitoring/positioning.py:29`), not the FINRA panel | Build the v3 risk state (DM rule + PIT conditional frequency/severity); wire both overlay panels into the assessment; reconcile or retire the pre-v3 prototype |
| 4. Proof of concept | **satisfied** | Multiple concrete working artifacts: positioning panel with tested PIT join; narrative panel whose top-8 z-scores are all real stress episodes with no episode-specific query terms (`outputs/narrative_poc_review.md:44-58,186-203`); evidence pipeline with grounding validation replayed end-to-end for 2009-03-06 and 2024-01-05 (`outputs/debug/`); executed notebooks 01 and 02 | The pieces don't yet form one system — that is Element 3's problem, not Element 4's |
| 5. Validation plan & evidence | **partial** | Implemented and tested: label maturity + future-data invariance (`tests/test_labels.py`, `docs/DECISIONS.md:439-449`), publication-date PIT (`tests/test_positioning_pit.py`), rolling-z PIT (`tests/test_pit_normalisation.py`), retrieval timestamp cutoff (`src/evidence/retriever.py:156-167`, `tests/test_retriever.py`), AI-classification faithfulness vs 16 review labels (`outputs/retrieval_evaluation.csv`: relevance 15/16, classification 12/16, citations 16/16) | **Baseline separation ("insurance") table: not found.** Episode-level ablation (lead time / false alarms): not found as an artifact — fragments exist in `outputs/narrative_poc_review.md:172-183`. Analog check: not found (nothing named "analog" in `src/`) |
| 6. Example output | **built-but-deficient** | `outputs/debug/risk_state_*.json` has horizon, probability, severity, top-5 drivers, provenance hashes; `outputs/debug/classified_evidence_*.json` has cited, passage-grounded evidence; notebook 02 gives the PM narrative | The probability shown is the disavowed fitted B2; no conditional probability with sample size, no severity range, no crowding/narrative overlay read, no invalidation conditions, no PM-readable brief for a quiet day and an elevated day |
| 7. Production path | **partial** | Fragments: CRSP/Compustat replacement (`docs/universe.md`), production replacements list (`src/monitoring/positioning.py:149-153`), Phase 2 interface contract (`outputs/phase1_review.md:241-290`), GDELT operational characterisation (`BLOCKERS.md`) | Memo §5 with the procurement table (borrow fees, RavenPack/Bloomberg, PIT constituents) and a daily-process description; nothing consolidated exists |
| **Deliverable: code/PoC + README** | **built-but-deficient** | README exists and is honest per-section, but its first 155 lines describe the abandoned Phase 1 architecture as if current, with the pivot disclosed only at line 157+; traceability table (PLAN_v3 §3) absent; clone fails 1 test (verified) | Restructure README to lead with v3; add the traceability table; fix the rebuild-test guard; merge `dear/*` to `main` |
| **Deliverable: 6-10p memo** | **expected-missing** | PLAN_v3 §5 items 5, 11 (scheduled 7/27-8/11); not found in repo | Write it; the repo has nearly all raw material |
| **Deliverable: example risk output** | **built-but-deficient** | as Element 6 | PM brief generator, ≥2 days |
| **Deliverable: 15-20 min presentation** | **expected-missing** | PLAN_v3 §5 item 12 (8/12-8/13); not found | After memo |

---

## Part 2 — Quant research thought process

### 2.1 Point-in-time discipline — implemented and tested; the repo's strongest asset

- **Label maturity:** thresholds admit only rows with `label_end_date <= t`; the shift-by-h implementation and the future-data invariance check (all UMD after 2020 set to extreme values, thresholds bit-identical) are in `docs/DECISIONS.md:344-358, 439-449` and `tests/test_labels.py`.
- **Positioning publication join:** implemented in `src/features/positioning_panel.py` and tested three ways — invisible before publication, step changes only on publication dates, settlement strictly older than the gating date (`tests/test_positioning_pit.py:50-99`). The 20 reconstructed dates carry `publication_date_rule` per row plus a 10-business-day sensitivity column (`tests/test_positioning_pit.py:102-121`).
- **Text information-set mapping:** GDELT day-D bucket available at close of next trading day, with a parametrised test that no trading date is ever in its own information set (`outputs/build_log.md:300`, `tests/test_narrative_mapping.py`).
- **Retrieval cutoff:** documents post-dating the assessment are excluded with reason codes (`src/evidence/retriever.py:156-167`) and citation validity re-checks the cutoff independently (`src/evidence/classification_validation.py:167-180`).
- Even the split-adjustment's PIT status is argued and pinned by a test (`docs/DECISIONS.md:1060-1067`, `tests/test_volume_neutral_crowding.py`).

**Finding: satisfied — these are habits, not claims.** No fix needed.

### 2.2 Leakage awareness — mostly closed by construction; one channel only flagged

Closed by construction and test: settlement-date look-ahead, label immaturity, rolling-z windows, retrieval timestamps, SEC filing-date (not period-end) joins (`docs/DECISIONS.md:1101-1105`). Disclosed rather than closed: (a) vendor file publication timing is a stated *convention* (post-close assessment, `docs/DECISIONS.md:243-256`) — acceptable, and honestly labeled; (b) **the evidence corpus was curated in 2026 for 2009 assessment dates.** The code flags it (`historical_corpus_was_curated_after_the_assessment_date`, `src/evidence/retriever.py:271`) but the PLAN_v3 §1 two-track rule (backtest track = archived same-day GDELT GKG) is not implemented — corpus *selection* is a hindsight channel that per-document timestamps do not close; (c) Phase 1 holdout count contamination — disclosed and adjudicated (`docs/DECISIONS.md:587-596`), now moot since the architecture was abandoned.

**Smallest fix for (b):** one paragraph in the memo demoting the current corpus to "illustrative fixture," plus the GKG-based track as the named production mechanism.

### 2.3 Mechanism-driven design — the panels yes; the live checklist no

The positioning panel measures the stated DM mechanism directly (loser-leg squeeze preconditions), and the three crowding variants were adjudicated on mechanism grounds, not accretion — the `days_to_cover` volume-denominator inversion is diagnosed, quantified (−2.23 z in March 2020), and answered with volume-free variants (`docs/DECISIONS.md:1022-1078`). Narrative queries are mechanism-level with a hindsight rule asserted in code (forbidden-token test, `tests/test_gdelt_acquisition.py`). The Phase 1 feature catalog is hypothesis-first (`docs/DECISIONS.md:102-116`).

But the **live risk logic is not the stated mechanism**: `domain_risk.py:28-34` uses −10% two-year decline and a 0.80 volatility percentile — thresholds with no citation, no derivation, and no correspondence to the DM 2016 rule (`bear_state` = trailing 504-day return < 0 × elevated variance) that PLAN_v3 §1 adopts and that Phase 1 already encodes. The plan's own travel action item ("verify the exact DM parameterization, do not restate from memory," `PROJECT_PLAN_v3.md:75`) is still open.

**Smallest fix:** implement the risk state exactly as PLAN_v3 §1 specifies from the existing `bear_state`/`mkt_variance_126d` columns and cite DM 2016 precisely.

### 2.4 Honest proxy labeling — exemplary, and placed where users look

Survivorship: carried as a column on every panel row (`universe_survivorship_bias = True`, `outputs/data_review.md:267-268`) plus `docs/universe.md` and README:230-233. Flow-vs-position: a purpose-written quotable paragraph (`docs/DECISIONS.md:891-904`). Reconstructed publication dates: flagged per row. GDELT estimand: its own DECISIONS section — attention share of global English coverage, explicitly *not* US journalism, not sentiment, not counts (`docs/DECISIONS.md:773-790`). The z-of-24-is-not-Gaussian caveat is in the PoC review where the impressive table lives (`outputs/narrative_poc_review.md:60-63`). **Satisfied.** One residue: the docstring in `src/utils/pit.py:21-28` still carries the *superseded* "series would be nearly destroyed" justification that the operator later corrected (`outputs/narrative_poc_review.md:65-88`) — trivial to align.

### 2.5 Decision hygiene — real adjudication, with one credibility hole

`docs/DECISIONS.md` reads like adjudication, not a changelog: options tables with rejections (e.g., `:161-172`, `:266-277`, absent-vs-zero `:820-846`), and — rarer — decisions recorded *against* the author's own interest: the normalisation rule chosen on a wrong estimate, with the correction quantified (`:1000-1008`); the formation-spread doc error (`:729-738`); the holdout contamination disclosure. The hole: **the tree's own status documents are stale and contradict the tree.** NEXT_STEPS.md:91-94 and `outputs/data_review.md` ("no risk state module … evidence layer") are false as statements about the repo — those modules exist at commits `8e1b641`/`04f6f3d`. PLAN_v3 §7's "decisions to log" are also not yet appended as entries. A reviewer who finds the contradiction stops trusting the log exactly where trust matters.

**Smallest fix:** one DECISIONS entry naming the pre-v3 prototype as a prior iteration, its disposition, and updating NEXT_STEPS.

### 2.6 Scope judgment — the over-build is real, and it is still wired in

- **Abandoned-architecture residue is not just present, it is load-bearing.** `src/modeling/baselines.py` (811 lines), `validation.py`, `audit.py`, development/holdout manifests, and the frozen specification hash all remain — defensible as history — but `src/monitoring/risk_state.py` *actively serves* B2's saved OOS probability as `risk_probability`, and `domain_risk.py` carries it as a "legacy benchmark" (`:336-355`). PLAN_v3 said the freeze/fold machinery "has no job"; in this tree it still has one. This is precisely the confusion signal the pivot was supposed to remove.
- `src/monitoring/contracts.py` is 1,197 lines of dataclass ceremony for a two-day demo — heavy for an MVP, light on payoff.
- Three crowding variants (`days_to_cover`, own-history ratio, EDGAR utilisation) where the MVP needed one clearly-labeled one — each variant did answer a diagnosed defect, so this is at the defensible edge, but the ~200-request SEC EDGAR leg (`docs/DECISIONS.md:1080-1155`) bought a third metric the memo may never cite. Volume of data is explicitly not quality here.
- Bootstrap/CI machinery: **not found** — correctly dropped.

**Smallest fix:** don't delete code; delete *ambiguity*. One README paragraph and one DECISIONS entry assigning every module to "current v3" or "prior iteration, retained as history," and remove the B2 number from anything presented as current output.

### 2.7 Reproducibility — split verdict, verified by execution

- Phase 1: reproducible offline — raw ZIPs and hashes tracked (`data/raw/manifest.json`), rebuilds byte-identical per `docs/DECISIONS.md:308-315`.
- Overlays: processed panels are tracked and the positioning panel rebuilds byte-identically offline from tracked inputs (test passed in this clean checkout). But the raw caches behind them — prices (403 files), FINRA daily (4,088 files), GDELT payloads — live only in the build worktree and are git-ignored (`.gitignore:15-18`). Consequence, verified this session: **a fresh clone fails `tests/test_cache_determinism.py::test_narrative_panel_rebuild_is_byte_identical`** (guard checks the tracked parquet, rebuild needs the untracked payloads) and silently skips three other determinism tests. README:188-191's "second run makes zero network calls" is true only on the build machine.
- Docs claim "115 tests pass, 1 skip" (NEXT_STEPS.md:14); actual is 121/1 in the build worktree — stale but in the right direction.

**Smallest fix (~0.5h):** guard the narrative rebuild test on raw-payload presence; add a README paragraph stating exactly what a clone can and cannot regenerate; track the six GDELT payload JSONs (they are small — the 150 MB problem is prices/FINRA, not GDELT).

---

## Part 3 — AI leverage

### 3.1 AI inside the system

The boundary is visible and, for what exists, enforced by construction: the pipeline is one-directional (risk state → query → retrieval → classification), so classifier output has no code path back to any risk number; the flag `classification_does_not_change_risk_probability` is stamped on results (`src/evidence/classifier.py:159`). The guardrails are the best part: extracted passages must be verbatim substrings of the source document (`src/evidence/classification_validation.py:112-115`), supporting claims *hard-fail* without a valid, cutoff-respecting citation (`:255-260`), mechanisms and drivers are whitelisted per request, and a "contradicting" class exists and was exercised (Reuters 2024-01-05 item, `outputs/retrieval_evaluation.csv`). Faithfulness was measured, not asserted: 16/16 citations complete, 15/16 relevance agreement, 12/16 exact classification agreement against review labels.

What is *not* there: the trigger discipline (evidence ran on a quiet day; no elevation gate anywhere in `src/evidence/query_builder.py`); the one-loop-one-requery agent (`PROJECT_PLAN_v3.md:113` — not found); the analog layer (not found); a real archive behind retrieval (23 hand-curated documents, 20 of them official Fed/BLS/BEA releases — `data/corpus/momentum_evidence_corpus_v1.json`); and the classifier itself is a cached fixture from an unidentified model (`"model_identifier": "codex-session-model-unspecified"`, `data/fixtures/classifier_response_2009-03-06.json`). "AI never alters the risk number" is enforceable by construction *as wired* — but the honest statement is that the AI whose influence is being bounded is, today, a replayed fixture.

### 3.2 AI in the workflow

This is a genuinely strong record, and it is the credible interview narrative: `outputs/build_log.md` is a first-person agent build log that names its own worst mistake (retry storm prolonging the GDELT ban, `:167-178`); the self-review caught four real defects — the CCZ 8.5σ artifact, ticker reuse attaching an ETF's short interest to Meta, gzip'd Wayback pages silently zeroing two schedule years, a cache key ignoring the request body (`outputs/data_review.md` §8.1) — plus the BKNG 25:1 split producing a fake 11σ reading (`docs/DECISIONS.md:1050-1059`); and the operator's own wrong estimate (gap clustering) is corrected in writing with numbers (`outputs/narrative_poc_review.md:65-88`). AI-written work being caught wrong and corrected is documented in both directions — the tooling catching data, and the human catching the tooling. Missing from the record: the prompt specs themselves (`claude_code_phase2_prompt_v3.md` is referenced in PLAN_v3 §6 but not found in-repo) and any named model identity for the evidence classifier.

### 3.3 The negative space

Explicit and well-argued: PLAN_v3 §1 states outright that conventional statistics beat AI for the risk state ("transparent, literature-anchored, cannot silently overfit," `:83`); README:159-163 and notebook 02's "we are not offering a black-box crash probability" carry it into artifacts. **Satisfied.**

### Verdict

On current evidence a reviewer would conclude: **AI was used impressively to *build* this project, and deliberately, defensibly *not* used for the risk number — but "AI materially improves the risk-monitoring process" is not yet demonstrated, because the AI that is supposed to do the improving (evidence attribution over a real archive, triggered on elevated states, feeding a PM brief) exists only as a two-day fixture replay over 23 curated documents.** The verdict flips on two unbuilt components: the v3 evidence layer run against a genuine point-in-time archive (or an honest fixture clearly labeled as such in the brief), and the PM brief that places the cited AI attribution next to the deterministic number so the division of labor is visible on one page.

---

## Part 4 — The interview gauntlet

1. **"Your README says nothing in this project is fitted. Your example output is a 79% probability from a fitted logistic regression. Which repo am I looking at?"**
   Cannot answer coherently today. `README.md:159-162` vs `src/monitoring/risk_state.py:35,429` and `outputs/debug/risk_state_2009-03-06.json`. Needs: the v3 risk state built, and the B2 prototype explicitly reframed as a prior iteration (or its debug artifacts regenerated without it).

2. **"You joined short interest on publication date. Prove settlement date never drives the join — including the 20 prints where you reconstructed the date yourself."**
   Answerable, well. `tests/test_positioning_pit.py:88-99` (settlement strictly older, metadata only), `docs/DECISIONS.md:857-890` (measured 7-business-day rule, per-row rule flag, 10-day sensitivity), `outputs/data_review.md` §1.3.

3. **"Show me the conditional frequencies. Why should I believe the DM panic state separates tail losses in *your* data rather than in a 2016 paper's data?"**
   Cannot answer. The insurance table (PLAN_v3 §0 "one cheap insurance item," §2 item 2) is not found in `outputs/` or notebooks. All inputs exist (`momentum_labels_h20.parquet`, `market_features.parquet`). This is ~30 minutes of work protecting the whole "adopted, not derived" stance.

4. **"Your loser leg is today's top-200 large caps. GME and AMC were never in it. What is your crowding series measuring, and which way is it biased?"**
   Answerable: `docs/universe.md`, `outputs/data_review.md` §4 (bias direction argued: understates crowding), and the honest orthogonality discussion — the crowding narrative query measures market-wide squeeze salience, near-zero correlation with the leg's own crowding (`outputs/narrative_poc_review.md:186-213`). Weakness: "understates" is argued from composition, not measured against any point-in-time benchmark.

5. **"Your headline is that the narrative overlay fires when the positioning overlay goes quiet. Isn't that negative correlation just your own volume-denominator artifact congratulating itself?"**
   Partially answerable — and the repo already half-concedes it: with the volume term removed the correlation collapses from −0.196 to −0.029 (`outputs/narrative_poc_review.md:157-163`). The defensible claim is precondition-vs-trigger complementarity on four episodes, explicitly labeled "description of four events, not evidence" (`docs/DECISIONS.md:1069-1078`). Needs: the headline in `data_review.md` §"Executive summary" reframed before a reviewer does it for you.

6. **"What does a z of 24 on a news series mean, and what exactly is the estimand of your text panel?"**
   Answerable, well: ranks-in-context caveat (`outputs/narrative_poc_review.md:60-63`), estimand section — global English attention share, not sentiment, not counts (`docs/DECISIONS.md:773-790`).

7. **"Why would I trust an LLM-written attribution in a risk report?"**
   Partially answerable. Strong: grounding by construction (verbatim-substring passages, hard-fail citations, whitelisted mechanisms — `src/evidence/classification_validation.py`), measured agreement (15/16, 12/16 on `outputs/retrieval_evaluation.csv`). Weak: n=16, labels are the developer's own review (`reference_label_provenance: developer_review_not_independent_ground_truth`), the model is unnamed, corpus is 23 documents. Needs: a named model, a larger sample, and the trigger discipline actually implemented.

8. **"Your backtest text track promises the information set of the day. Your corpus was assembled in 2026 for March 2009. How is document *selection* not hindsight?"**
   Cannot fully answer. The code flags it (`historical_corpus_was_curated_after_the_assessment_date`) but the two-track rule (PLAN_v3 §1, archived same-day GDELT GKG for the backtest track) is unimplemented. Needs: either the GKG track or an explicit demotion of the current demo to "illustrative fixture" in the memo.

9. **"Where do −10%, the 0.80 percentile, and 3% come from?"**
   Cannot answer. `src/monitoring/domain_risk.py:28-34` cites nothing; the thresholds match neither DM 2016 nor PLAN_v3's adopted rule; the plan's own instruction to verify DM's exact parameterization (`PROJECT_PLAN_v3.md:75`) is open. Needs: cite DM precisely and use its rule, or show the thresholds' descriptive provenance.

10. **"You were given about 20 hours. Where did they go, and what did you decide not to build?"**
    Answerable, unusually well, if updated: PLAN_v3 §5 shows the budget, admits the projected overrun, and pre-commits trims; `BLOCKERS.md` shows an external constraint handled without circumvention; the dropped-machinery list is explicit (`PROJECT_PLAN_v3.md:201-203`). Needs: actuals for the 7/24-25 session written down.

---

## Part 5 — Prioritized punch list

Budget context — **corrected 2026-07-25 after first issue.** This review originally estimated ≈13-14h spent by trusting `PROJECT_PLAN_v3.md:182` ("Spent to date ≈ 9h") plus the alt-data session. The operator's actual figure is that **the existing repo accounts for ≈4h**, leaving **≈16h under "approximately 20."** PLAN_v3 §5's spent-to-date line is therefore superseded and should be corrected in the plan itself; the interview answer to Q10 depends on the actuals being written down. The estimate-vs-actual gap is itself worth logging — it changed which cuts this review recommended.

| # | What | Why (requirement served) | Est. h | Depends on |
|---|---|---|---:|---|
| 1 | **Insurance table**: unconditional vs DM-state-conditional forward tail-loss frequency, full sample, both horizons, with n per cell — from existing `momentum_labels_*.parquet` + `market_features.parquet` | Element 5; kills gauntlet Q3; protects the entire "adopted, not derived" stance | 0.5 | none |
| 2 | **v3 risk-state module**: DM rule from existing `bear_state` × `mkt_variance_126d`, PIT conditional probability and severity range with sample size; run for 2-3 dates incl. one elevated, one quiet | Elements 1, 3, 6; kills Q1 and Q9 | 1.5 | 1 (shares logic) |
| 3 | **Coherence pass**: README restructured to lead with v3 + traceability table (PLAN_v3 §3); DECISIONS entry assigning `src/monitoring/` + `src/modeling/` to "prior iteration, retained as history"; fix stale NEXT_STEPS/data_review claims; align `src/utils/pit.py` docstring | Deliverable README; kills Q1's sting; §2.5-2.6 findings | 1.0 | 2 (so the new lead is real) |
| 4 | **PM brief generator** (markdown, from the pipeline): state, conditional probability (n), severity range, crowding read (`short_interest_ratio_z`, utilisation), narrative read (`panic_vol_z`, `crowding_vol_z`), cited evidence replayed from existing classified outputs, explicit invalidation conditions; one quiet day, one elevated day | Elements 3 + 6 — this is where the three legs finally meet on one page; the deliverable "example risk output" | 1.5 | 2 |
| 5 | **Episode ablation table** (descriptive): per episode (2020-03, 2021-01, 2024-08, 2025-04), did the DM state flag it, and overlay lead-time readings — formalizing numbers already measured in `outputs/narrative_poc_review.md:172-183` | Element 5 item 3 | 0.5 | 2 |
| 6 | **Reproducibility guard**: fix the narrative-rebuild test's skip condition; README paragraph on what a clone can regenerate; track the six small GDELT payload JSONs; merge `dear/*` → `main` | Deliverable hygiene; a cloning interviewer currently sees a failing suite | 0.5 | none |
| 7 | **Memo, 6-10 pp** (hand-written per plan) | Deliverable; Elements 1-3, 5, 7 all have their permanent home here | 2.5 | 1-5 |
| 8 | **Slides + rehearsal** | Deliverable | 0.75 | 7 |
| | **Total** | | **8.75** | |

**Cross-check vs budget (corrected): 8.75h core needed, ≈16h available.** Nothing has to be cut for budget reasons. With the slack, the extensions below are affordable, ranked by evidence-per-hour — but the ranking discipline still applies, and volume is still not quality:

- **Trigger discipline + minimal agent loop (~1.0-1.5h):** gate the evidence layer on an elevated state and implement the bounded one-loop-one-requery per `PROJECT_PLAN_v3.md:113`. Directly answers gauntlet Q7's weakest flank and completes the PLAN_v3 §1 [3] design.
- **Faithfulness sample extension (~0.5h):** a third demo day and more review labels; n=16 developer-labeled rows is the thinnest number in the AI-validation story.
- **Analog check (~1.5h, do last or not at all):** still the lowest evidence-per-hour item on the board — the plan itself calls it "a sanity check, not a performance claim." Build it only after everything above lands; a designed-but-unbuilt paragraph in the memo remains acceptable.
- **GDELT completion (crowding tone, semantic sanity check): zero planned hours.** Externally blocked; run the fail-fast commands opportunistically and take whatever lands. Do not spend budget waiting.

Core list + first two extensions ≈ 10.75h → cumulative ≈15h, comfortably under the cap with buffer for the memo running long — which memos do.

**What I would not cut, ever, in agreement with the plan's own never-cut list:** the PIT/leakage tests, the insurance table, the generated PM brief, and the two-track text rule's honest treatment in the memo. Items 1-4 above are the difference between "three good panels and a story" and "a system a PM could challenge across the table."
