# Phase 6 implementation plan: PM Evidence Card

Date: 2026-07-29

Status: approved; Sessions 1 and 2 completed. Phase 1–5 calculations,
retrieval rules, thresholds, notebooks, and rendering remain unchanged.

## Executive finding

The repository already contains a thin Phase 6A candidate that implements most
of the requested integration:

```python
src.mvp.evidence_card.build_evidence_card(
    as_of_date=...,
    threshold_profile="default",
    compare_to_date=...,
    use_llm=...,
)
```

It returns a validated `EvidenceCard`, has a dependency-free HTML renderer, and
is already used by `notebooks/03_pm_evidence_card_demo.ipynb`. The focused
smoke test is ready and 47 adjacent scorecard, retrieval, archive, preview, and
Evidence Card tests passed during this audit.

The minimum path is therefore to adopt and harden this façade, not to create a
second pipeline, a new retrieval system, or a new UI. The Phase 1–4
quantitative modules and existing evidence retrieval/classification modules
should remain unchanged.

Two distinctions are important:

1. `src/mvp/run_demo.py` is the documented deterministic final-MVP integration,
   while `src/mvp/evidence_card.py` is the narrower date-driven Evidence Card
   integration required here. `src/pipeline.py` is a retained earlier research
   path and should not become the notebook's integration seam.
2. The canonical Phase 5 review does **not** say all of Phase 5 is complete. It
   says Phase 5A acquisition/feasibility is complete and Phase 5B alignment
   remains unapproved. No fundamental-alignment signal should be added to the
   Evidence Card.

## Approval and Session 1 acceptance

The plan was approved on 2026-07-29. Session 1 freezes:

- `src.mvp.evidence_card.build_evidence_card` as the notebook-facing façade;
- the field order of `EvidenceCard`, `QuantSignal`, and `RetrievedEvidence`;
- `evidence-card-v1` as the current card schema version;
- `default` as the sole approved threshold profile backed by `DEFAULT_CONFIG`;
- the absence of Phase 5B fundamental-alignment fields from the card.

These decisions are guarded by focused tests in
`tests/test_evidence_card.py`. The smoke test remained `ready`, and the
expanded focused baseline completed with 49 passing tests. Session 1 changed
tests and this plan only.

## Session 2 implementation record

Session 2 added:

- `DeterministicEvidenceInput`, a validated narrative-free schema that reuses
  the existing `QuantSignal` and `RetrievedEvidence` contracts;
- `build_deterministic_evidence_input(...)`, a thin public adapter over the
  existing deterministic Evidence Card assembly with `use_llm=False`;
- explicit warnings for the intentionally null composite score, missing
  point-in-time evidence, and unavailable/unapproved Phase 5B alignment;
- audit metadata containing data/model versions, evidence quality, counts,
  horizon, adapter version, and `llm_invoked=False`;
- focused date, profile, cutoff, schema, comparison, missing-evidence, and
  reproducibility tests.

No LLM client, prompt, notebook, dataset, threshold, or Phase 1–5 calculation
was added or changed. The expanded Session 2 targeted suite completed with 45
passing tests, and the existing demo smoke test remained `ready`.

## Scope inspected

### Phase reviews and handoffs

- `docs/phase_reviews/README.md`
- `docs/phase_reviews/phase_1_review.md`
- `docs/phase_reviews/phase_2_review.md`
- `docs/phase_reviews/phase_3_review.md`
- `docs/phase_reviews/phase_4_review.md`
- `docs/phase_reviews/phase_5_review.md`
- `docs/handoff_phase5.md`
- `docs/phase_6a_review.md`
- `phase_6_review.md`
- `README.md`

### Quantitative pipeline and contracts

- `src/regime/market_state.py`
- `src/risk/dm_engine.py`
- `src/risk/leg_decomposition.py`
- `src/monitoring/scorecard.py`
- `src/mvp/contracts.py`
- `src/mvp/run_demo.py`
- `src/pipeline.py`
- `src/utils/io.py`

### Evidence, prompts, and synthesis

- `src/evidence/corpus.py`
- `src/evidence/query_builder.py`
- `src/evidence/retriever.py`
- `src/evidence/classifier.py`
- `src/evidence/classification_validation.py`
- `src/evidence/prompts.py`
- `src/evidence/provider_contracts.py`
- `src/evidence/archived_provider.py`
- `src/evidence/versioned_classifier.py`
- `src/evidence/research_preview.py`
- `src/evidence/mvp.py`
- `src/mvp/evidence_card.py`
- `src/mvp/llm_synthesis.py`

### Notebook, rendering, and verification

- `notebooks/01_baseline_eda.ipynb`
- `notebooks/02_pm_prototype_validation.ipynb`
- `notebooks/03_pm_evidence_card_demo.ipynb`
- `src/reporting/pm_brief.py`
- `src/mvp/demo_smoke_test.py`
- `tests/test_evidence_card.py`
- `tests/test_demo_smoke_test.py`
- `tests/test_scorecard.py`
- `tests/test_research_preview.py`
- `tests/test_retriever.py`
- `tests/test_archived_evidence.py`
- `pyproject.toml`

The complete repository file structure was also inventoried. Relevant processed
Parquet schemas, evidence corpus coverage, and cached classification dates were
read directly.

## Verified repository components

| Capability | Verified module and entry point | Current behavior | Reuse decision |
|---|---|---|---|
| Headline quantitative state for an as-of date | `src.risk.dm_engine.build_primary_assessment` | Returns a validated `PrimaryRiskAssessment` with `normal`, `bear_low_volatility`, or `panic_elevated`, plus PIT descriptive tail-loss frequency for horizon 5 or 20. It reads only features and matured labels available through the as-of date. | Reuse unchanged. |
| Full macro regime history | `src.regime.market_state.build_regime_history` | Builds drawdown, recovery, realized volatility, DM state, crash/recovery flags, and rate proxy from the French factor history. Prior-only volatility thresholds are enforced. | Reuse unchanged. |
| Row-oriented macro assessment | `src.regime.market_state.build_regime_table` | Produces the Phase 1 ten-row assessment contract. | Available for diagnostics, but the Evidence Card should continue to use the reduced Phase 4 scorecard. |
| Four PM-relevant indicators and trigger states | `src.monitoring.scorecard.build_scorecard` | Returns exactly four ordered rows: `high_volatility_recovery`, `short_minus_long_beta_gap`, `portfolio_drawdown`, and `short_loss_in_recovery`. Missing inputs remain unavailable. | Reuse unchanged. This is the authority for indicator values, thresholds, directions, statuses, and triggers. |
| Threshold configuration | `src.monitoring.scorecard.ScorecardConfig`, `src.monitoring.scorecard.DEFAULT_CONFIG` | Frozen configuration for prior-only quantiles, minimum observations, guardrails, and fallback demo thresholds. | Reuse unchanged. |
| Named threshold-profile lookup | `src.mvp.evidence_card.THRESHOLD_PROFILES`, `src.mvp.evidence_card.resolve_threshold_profile` | Registry currently contains only `{"default": DEFAULT_CONFIG}`. Unknown names fail closed. | Reuse. Do not add profiles without a separately approved config. |
| Deterministic final-MVP integration | `src.mvp.run_demo.run_demo` | Composes Phase 1–4 state, portfolio holdings, scorecard, and the Phase 5A feasibility audit. It is read-only with respect to upstream artifacts but writes demo outputs. | Keep as a separate final-MVP/reporting path; do not route the Evidence Card through its larger output contract. |
| Evidence Card integration façade | `src.mvp.evidence_card.build_evidence_card` | Loads existing processed inputs, builds headline state and scorecard, optionally computes comparison deltas, replays evidence, builds historical context, runs constrained synthesis, and returns `EvidenceCard`. | Safest and smallest reusable entry point for the notebook. |
| Exact-date evidence replay used by the card | `src.evidence.research_preview.build_research_preview` | Validates an exact-date cached classification against the versioned local corpus and a 16:00 America/New_York cutoff. Missing or inconsistent caches return `unavailable`. | Reuse unchanged for the offline demo. |
| Lower-level deterministic retrieval | `src.evidence.query_builder.build_retrieval_request`, `src.evidence.retriever.retrieve` | Builds keyword queries from the legacy `RiskState`/`PositioningState` contracts, filters by cutoff/lookback/source, ranks, and deduplicates the local corpus. | Verified, but not wired to `build_evidence_card`. Do not introduce it into the card unless replacing the exact-date replay is separately approved. |
| Strict archived provider | `src.evidence.archived_provider.ArchivedEvidenceProvider.retrieve`, routed by `src.evidence.mvp.build_evidence_snapshot` | Checks publication, discovery, availability, and content-version timestamps; can validate a versioned classifier response through `src.evidence.versioned_classifier.validate_classifier_response`. | Code is reusable, but the default archive corpus `data/corpus/archived_momentum_evidence_v1.json` is absent and this path is not used by the card. It is not a ready replacement. |
| Cached structured evidence classification | `src.evidence.classifier.build_classification_result`, `src.evidence.classification_validation.validate_and_build_evidence_items` | Validates saved structured classifier responses and grounding against retrieved candidates. It does not call a model. | Reuse unchanged for fixture generation/replay. |
| Classifier prompt contract | `src.evidence.prompts.SYSTEM_PROMPT`, `src.evidence.prompts.build_classifier_input`; newer archive boundary in `src.evidence.versioned_classifier` | Defines allowed classifications and exact structured response validation. No live model client exists. | Reuse as evidence-classification infrastructure; do not confuse it with PM narrative synthesis. |
| Historical context | `src.risk.dm_engine.build_insurance_table`, called by `src.mvp.evidence_card._historical_analogs` | Produces aggregate state-conditional sample sizes, tail-loss frequencies, mean returns, and fifth-percentile returns. | Reuse, but label it as descriptive historical context. |
| Narrative-only synthesis output | `src.mvp.llm_synthesis.SynthesisResult`, `src.mvp.llm_synthesis.Synthesizer` | Frozen, validated narrative-only return type. A synthesizer cannot return quantitative fields. | Reuse and harden rather than redesign. |
| Deterministic fallback synthesis | `src.mvp.llm_synthesis.DeterministicSynthesizer` | Produces narrative, change summary, PM interpretation, monitoring questions, and invalidation conditions offline. | Reuse unchanged as the required fallback. |
| Evidence Card schema | `src.mvp.evidence_card.EvidenceCard`, `QuantSignal`, `RetrievedEvidence` | Validates dates, finite values, signal status, evidence stance, and evidence timestamps at or before the cutoff. | Reuse as the external notebook contract. |
| Notebook rendering | `src.mvp.evidence_card.render_signal_table_html`, `render_evidence_card_html` | Dependency-free HTML rendering used by Notebook 03. | Reuse unchanged unless a contract field changes. |
| Read-only pre-demo gate | `src.mvp.demo_smoke_test.run_smoke_test` | Checks local inputs/dependencies, two distinct dates, cutoff compliance, schema construction, and HTML rendering without writing artifacts. | Reuse unchanged and run before every demo. |

## Verified processed inputs and coverage

`build_evidence_card` currently depends on:

| File | Verified coverage | Role |
|---|---|---|
| `data/processed/french_research_factors_daily.parquet` | 1926-07-01 through 2026-05-29 | Phase 1 regime history. |
| `data/processed/market_features.parquet` | 1926-11-03 through 2026-05-29 | Headline DM state and input-date ceiling. |
| `data/processed/leg_risk_history.parquet` | 2017-02-01 through 2026-06-30 | Phase 3 beta, contribution, return, and drawdown inputs to the scorecard. |
| `data/processed/momentum_labels_h5.parquet` | 1926-11-03 through 2026-05-29 | Matured 5-day descriptive tail labels. |
| `data/processed/momentum_labels_h20.parquet` | 1926-11-03 through 2026-05-29 | Matured 20-day descriptive tail labels. |

The practical full-card date domain is the intersection of these inputs,
not the latest date in any one file. At present, the leg-risk start date means
the four-row card is unavailable before 2017-02-01, while the regime/features
end date caps the complete path at 2026-05-29.

The compact evidence corpus contains 23 documents. Validated exact-date
classification caches exist for:

- `2009-03-06`: 4 supporting, 0 contradicting, and 3 contextual usable items;
- `2024-01-05`: 3 supporting, 1 contradicting, and 3 contextual usable items.

Only `2024-01-05` overlaps the Phase 3 leg-risk history and therefore supports
the complete quant-plus-evidence card.

## Current data contracts

### Notebook input contract

```text
as_of_date: date-like, required
compare_to_date: date-like or null, must be strictly before as_of_date
threshold_profile: supported string, currently only "default"
use_llm: bool
horizon: 5 or 20, default 20
```

The build rejects an as-of date after today or after the latest market-feature
date. A comparison date that cannot be computed is dropped with a warning.

### Threshold contract

`ScorecardConfig` currently exposes:

```text
historical_min_observations
beta_gap_quantile
beta_gap_demo_threshold
beta_gap_floor
drawdown_window
drawdown_quantile
drawdown_demo_threshold
drawdown_floor
drawdown_ceiling
short_loss_window
short_loss_quantile
short_loss_demo_threshold
```

The named profile is not a YAML file. It is the in-code
`THRESHOLD_PROFILES` registry of frozen `ScorecardConfig` instances.

### Four-row scorecard contract

`build_scorecard` returns these columns:

```text
as_of_date
monitor_family
metric
current_value
threshold
threshold_provenance
direction
triggered
severity
status
explanation
context
source_module
```

The row order and metric names are fixed by `SCORECARD_METRICS`. `triggered`
uses nullable Boolean semantics; `status="unavailable"` requires a null trigger.

### Headline state contract

`PrimaryRiskAssessment` contains:

```text
as_of_date / as_of_timestamp / horizon_days
state / elevated / bear_state
market_return_504d / market_variance_126d / panic_intensity
tail_loss_probability / conditioning_sample_size
conditional_mean_forward_return / conditional_fifth_percentile
unconditional_tail_loss_probability / unconditional_sample_size
label_maturity_cutoff_date
limitations / provenance
```

The tail-loss value is a descriptive state-conditional historical frequency,
not a calibrated forecast.

### Evidence replay contract

`build_research_preview` returns a dictionary with:

```text
status: "sample_only" or "unavailable"
evidence_case_date
deterministic_facts_sha256
deterministic_facts_unchanged
supporting / contradicting / contextual
research_questions
uncertainty
limitations
```

Every usable item carries document ID, title, source, publication timestamp,
citation locator, classification, mechanism, specificity, extracted passage,
rationale, and citation validity.

### Synthesis contract

`SynthesisResult` contains narrative fields only:

```text
narrative_state
what_changed
pm_interpretation
monitoring_questions
invalidation_conditions
model_or_prompt_version
```

It validates string lengths and list sizes. It has no field through which a
model can alter dates, states, values, thresholds, triggers, historical
frequencies, evidence records, or run identity.

### Evidence Card contract

`EvidenceCard` combines:

- selected and comparison dates;
- headline risk state and descriptive tail-loss frequency;
- triggered and non-triggered/unavailable `QuantSignal` rows;
- separated supporting, contradicting, and contextual `RetrievedEvidence`;
- missing/uncertain evidence;
- historical context;
- narrative-only synthesis fields;
- threshold, data, model, cutoff, run, and synthesis metadata;
- warnings.

`deterministic_score` is intentionally always null because the repository
forbids a new composite probability.

## Proposed integration flow

```text
Notebook parameters
  as_of_date, optional compare_to_date, threshold_profile, use_llm
        |
        v
resolve_threshold_profile
  -> THRESHOLD_PROFILES["default"]
        |
        +------------------------------+
        |                              |
        v                              v
build_primary_assessment         build_regime_history
  -> headline DM state                 |
  -> PIT descriptive frequency         v
                                build_scorecard
                                  -> four values
                                  -> four thresholds
                                  -> nullable triggers
                                        |
                    optional comparison build_scorecard
                    -> per-indicator deltas
                                        |
                                        v
build_research_preview
  -> exact-date validated cache replay
  -> unavailable on any date/provenance/cutoff failure
                                        |
                                        v
build_insurance_table
  -> descriptive state-conditional historical context
                                        |
                                        v
Synthesizer protocol
  -> external narrative-only result when explicitly injected
  -> deterministic fallback otherwise
                                        |
                                        v
validated EvidenceCard
                                        |
                         +--------------+--------------+
                         |                             |
                         v                             v
             render_signal_table_html      render_evidence_card_html
                         \_____________________________/
                                        |
                                        v
                    notebooks/03_pm_evidence_card_demo.ipynb
```

The Evidence Card should continue to call in-memory builders and should not
call the artifact-writing `run_*` wrappers.

## Safest reusable entry points

1. **Notebook/application seam:** `src.mvp.evidence_card.build_evidence_card`.
2. **Quantitative indicator authority:** `src.monitoring.scorecard.build_scorecard`.
3. **Headline state authority:** `src.risk.dm_engine.build_primary_assessment`.
4. **Macro-history builder:** `src.regime.market_state.build_regime_history`.
5. **Offline evidence seam:** `src.evidence.research_preview.build_research_preview`.
6. **Historical context:** `src.risk.dm_engine.build_insurance_table`.
7. **Narrative output boundary:** `src.mvp.llm_synthesis.Synthesizer` and
   `SynthesisResult`.
8. **Notebook display:** `render_signal_table_html` and
   `render_evidence_card_html`.
9. **Acceptance gate:** `src.mvp.demo_smoke_test.run_smoke_test`.

Private helpers such as `src.mvp.evidence_card._historical_analogs` and
`_scorecard_values` should not be imported by notebook code.

## Missing or incomplete functionality

### 1. A live structured LLM implementation is absent

No OpenAI, Anthropic, or other model SDK/client is installed or called.
`use_llm=True` without an injected synthesizer records
`deterministic_fallback`. This is safe and adequate for the offline demo, but it
is not a real LLM invocation.

### 2. The synthesizer input does not contain the retrieved evidence

The current `context` passed to `Synthesizer.synthesize` contains the headline
state, triggered-signal names, counts, comparison deltas, evidence quality, and
tail-loss frequency. It does **not** contain the supporting, contradicting, or
contextual evidence items. Therefore an injected model can phrase the
quantitative state, but cannot actually interpret the retrieved evidence.

This is the smallest material gap relative to the requested
"optional structured LLM interpretation" stage. The fix should pass a bounded,
immutable, citation-bearing evidence payload to the synthesizer while keeping
`SynthesisResult` narrative-only.

### 3. True historical analog retrieval is not implemented

`src.mvp.evidence_card._historical_analogs` is named like an analog retriever,
but it returns aggregate rows from `build_insurance_table` for all states. It
does not select historical dates or episodes similar to the selected state.
`src.risk.leg_decomposition.build_recovery_attribution` constructs recovery
episodes, but it is not an analog search and is not used by the card.

The existing output should be described as **historical context**, not
date-level analogs. Adding a nearest-neighbor or episode-retrieval method would
be new research and is not required for the minimal card.

### 4. Evidence coverage is intentionally narrow

The complete quant-plus-evidence card is available for one date,
`2024-01-05`. Other valid quant dates fail closed to quantitative-only cards.
No broader corpus should be implied, and missing evidence must not be read as a
benign finding.

### 5. Only one threshold profile is approved

The named profile mechanism exists, but `default` is the only profile. This
satisfies the named-profile input contract while avoiding unapproved threshold
variants. Additional profiles are research/governance work, not UI work.

### 6. Comparison behavior is intentionally limited

The comparison date drives four indicator-value deltas and the deterministic
`what_changed` text. It does not compare evidence sets, the headline DM state,
or historical frequencies. That is acceptable for the minimum demo but should
be stated.

### 7. Phase 5 alignment is unavailable

Phase 5A established degraded feasibility coverage only. There is no approved
historical fundamental stock panel, rank alignment, portfolio spread, or
fundamental scorecard to add to the Evidence Card.

## Minimum file plan

### Reuse unchanged

- `src/regime/market_state.py`
- `src/risk/dm_engine.py`
- `src/risk/leg_decomposition.py`
- `src/monitoring/scorecard.py`
- `src/mvp/contracts.py`
- `src/evidence/corpus.py`
- `src/evidence/query_builder.py`
- `src/evidence/retriever.py`
- `src/evidence/classifier.py`
- `src/evidence/classification_validation.py`
- `src/evidence/prompts.py`
- `src/evidence/provider_contracts.py`
- `src/evidence/archived_provider.py`
- `src/evidence/versioned_classifier.py`
- `src/evidence/research_preview.py`
- all Phase 1–5 processed data and existing evidence fixtures/caches

### Modify only if closing the optional synthesis gap

- `src/mvp/evidence_card.py`
  - build one bounded synthesis input after evidence validation;
  - include signal facts and citation-bearing evidence records;
  - preserve run ID and every quantitative field independently of synthesis.
- `src/mvp/llm_synthesis.py`
  - validate the bounded synthesis input shape;
  - keep `SynthesisResult` narrative-only and retain deterministic fallback.
- `tests/test_evidence_card.py`
  - prove the synthesizer receives only the approved context;
  - prove evidence can affect narrative only;
  - prove quant fields, evidence records, cutoff, and run ID are unchanged.
- `notebooks/03_pm_evidence_card_demo.ipynb`
  - no layout redesign; update only if a synthesis-mode label or narrative
    field changes.
- `src/mvp/demo_smoke_test.py` and `tests/test_demo_smoke_test.py`
  - update only if the accepted synthesis metadata contract changes.

### Add

No new production module, dependency, notebook, data source, database, or UI is
required for the deterministic Evidence Card.

This planning document is the only required new file from the present session.
A provider-specific live LLM adapter should be a separately approved addition,
not part of the minimum offline plan.

## Risks and assumptions

- The user premise treats Phases 1–5 as complete, but the canonical Phase 5
  review limits completion to Phase 5A. This plan follows the repository's
  recorded approval boundary.
- The headline `overall_risk_state` comes from the DM primary assessment,
  whereas the four PM indicators come from the Phase 4 scorecard. Both are
  deterministic, but they are separate state contracts.
- Scorecard availability starts with the leg-risk history on 2017-02-01 and
  ends at the common macro/features boundary, currently 2026-05-29.
- Historical portfolio results use a current-membership S&P 500 proxy and are
  survivorship-biased.
- Public-vendor prices and current classification snapshots can be revised.
- Thresholds are prior-only research rules with documented demo guardrails,
  not optimized trading thresholds.
- State-conditional frequencies are descriptive, serially dependent historical
  rates, not calibrated probabilities or advice.
- The evidence corpus was curated later and is small; exact cutoff checks do
  not establish complete historical coverage.
- `build_research_preview` validates cutoff and major provenance fields. A
  future hardening pass may also require the cached
  `publication_timestamp` to equal the corpus timestamp exactly, rather than
  relying on cutoff validation at both layers.
- The current notebook is interactive through an editable parameter cell and
  Run All. No widget framework is required.
- A real external synthesizer would require an approved model/version,
  credential handling, timeout/retry policy, logging policy, and evaluation
  gate. None should be guessed.

## Explicit non-goals

- No changes to Phase 1–5 signal definitions, thresholds, labels, portfolio
  construction, or historical findings.
- No new composite risk score or probability.
- No Phase 5B fundamental alignment implementation.
- No new data acquisition or live-news scraping.
- No vector database, embedding service, or new retrieval architecture.
- No historical analog model or nearest-neighbor research in the minimal path.
- No chatbot, conversational agent, standalone website, dashboard, or deployed
  service.
- No notebook widget framework or UI redesign.
- No live LLM client unless separately approved.
- No new dependency.
- No semiconductor-selloff analysis or sector case study.
- No trading recommendation, causal claim, or production backtest claim.

## Recommended sequence for the next five 20-minute sessions

### Session 1 — Accept and freeze the integration contract

- Treat `build_evidence_card` as the single notebook-facing façade.
- Confirm the accepted field names in `EvidenceCard`, `QuantSignal`, and
  `RetrievedEvidence`.
- Record that `default` is the sole threshold profile and that Phase 5B is
  unavailable.
- Run the existing smoke test and focused tests as the baseline.

Expected file changes: tests/documentation only if the acceptance wording is
not already sufficient.

### Session 2 — Harden the structured synthesis input

- Add a bounded synthesis-input contract in the existing MVP synthesis layer.
- Pass validated scorecard facts and the already cutoff-approved evidence
  records into that input.
- Keep citations, stances, and missing-evidence warnings explicit.
- Do not permit the synthesizer to return or overwrite quantitative fields.

Expected file changes: `src/mvp/evidence_card.py`,
`src/mvp/llm_synthesis.py`, and `tests/test_evidence_card.py`.

### Session 3 — Prove deterministic and injected-synthesizer behavior

- Add tests for supporting, contradicting, contextual, and unavailable evidence
  in the synthesis input.
- Prove byte-identical quantitative fields and run identity with LLM off, a
  successful injected synthesizer, a malformed result, and an exception.
- Keep the deterministic fallback as the default demo path.

Expected file changes: tests first; production changes only for defects exposed
by those tests.

### Session 4 — Re-verify the notebook experience

- Run Notebook 03 from the parameter cell through the final card for
  `2024-01-05` and the `2020-03-24` quantitative contrast.
- Confirm the selected date, comparison date, profile, data cutoff, evidence
  availability, and synthesis mode are visible.
- Keep the existing inline Matplotlib context and HTML renderers; do not build
  widgets or a separate UI.

Expected file changes: `notebooks/03_pm_evidence_card_demo.ipynb` only if the
accepted contract changed.

### Session 5 — Final acceptance and handoff

- Run `python -m src.mvp.demo_smoke_test`.
- Run the focused Evidence Card, scorecard, retrieval, archive, and cutoff
  tests, then the full regression suite.
- Verify upstream artifact hashes are unchanged and run `git diff --check`.
- Update the Phase 6 review/handoff with exact test results, the one-date
  evidence limitation, the deterministic fallback, and the Phase 5A boundary.

Expected file changes: review/handoff documentation only.

## Audit result from this session

Commands completed without changing production code:

```text
python -m src.mvp.demo_smoke_test
  status: ready
  primary date: 2024-01-05
  primary run ID: 53c34aa57bb437fc
  regression date: 2020-03-24
  regression run ID: 87c48fc913f38386
  evidence items: 7

focused tests:
  47 passed
```

This result verifies the existing integration candidate. It does not erase the
missing live LLM client, limited evidence-date coverage, absent true analog
retrieval, or unapproved Phase 5B work.
