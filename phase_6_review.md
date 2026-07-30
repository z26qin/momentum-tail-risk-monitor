# Phase 6 review — final interactive PM Evidence Card

## Outcome

Phase 6 is ready for a reliable, deterministic-first 20-minute PM and
quant-researcher demonstration.

The final notebook accepts an as-of date, optional comparison date, and named
threshold profile; recomputes the existing quantitative pipeline; applies the
point-in-time evidence cutoff; optionally invokes a constrained interpretation
interface; and renders one auditable PM Evidence Card.

The deterministic card now also shows the Phase 5 scenario-v2 extension:
bear-market recovery, short-book reversal, and crowded-theme unwind are
independent, potentially simultaneous mechanisms. The existing six-row unwind
scorecard remains unchanged beneath this layer.

The reliable default is fully offline:

```python
AS_OF_DATE = "2024-01-05"
COMPARE_TO_DATE = "2023-12-01"
THRESHOLD_PROFILE = "default"
USE_LLM = False
```

No Phase 1–5 signal, label, dataset, trained model, or threshold was redesigned
or optimized.

## Implementation summary

Phase 6 added five bounded capabilities:

1. `DeterministicEvidenceInput`, a frozen validated projection of existing
   quantitative and point-in-time evidence outputs.
2. `build_deterministic_evidence_input(...)`, the single deterministic
   notebook-facing adapter.
3. `EvidenceInterpretation` and `interpret_evidence_card(...)`, a
   provider-neutral, schema-constrained narrative layer with deterministic
   fallback.
4. A pre-executed interactive notebook with a ranked comparison view and final
   PM-facing HTML Evidence Card.
5. A read-only smoke gate and focused tests for dates, profiles, cutoff,
   repeatability, interpretation safety, failure behavior, and notebook
   readiness.

The quantitative object remains separate from interpretation. Interpretation
cannot write the state, values, thresholds, trigger statuses, comparison
deltas, evidence records, dates, cutoff, or run ID.

## Final end-to-end flow

```text
AS_OF_DATE + COMPARE_TO_DATE + approved THRESHOLD_PROFILE
                            |
            existing deterministic Phase 1–4 pipeline
                            |
       six-row unwind inputs + three mechanism scenarios
                            |
            validated DeterministicEvidenceInput
                            |
       cutoff-enforced cached point-in-time evidence
                            |
        optional constrained EvidenceInterpretation
                            |
              final interactive PM Evidence Card
```

`USE_LLM=False` is a complete product path, not a degraded quantitative path.

## Reused Phase 1–5 components

| Existing component | Exact entry point | Phase 6 use |
|---|---|---|
| Primary risk assessment | `src.risk.dm_engine.build_primary_assessment` | Overall deterministic state and descriptive state-conditional tail-loss context |
| Four-row scorecard | `src.monitoring.scorecard.build_scorecard` | Values, prior-only thresholds, directions, trigger states, and explanations |
| Approved threshold config | `src.monitoring.scorecard.DEFAULT_CONFIG` via `src.mvp.evidence_card.THRESHOLD_PROFILES` | The sole approved `default` profile |
| Regime history | `src.regime.market_state.build_regime_history` | State input to the scorecard |
| Historical state context | `src.risk.dm_engine.build_insurance_table` | Aggregate matured-label context carried in `historical_analogs` |
| Point-in-time evidence replay | `src.evidence.research_preview.build_research_preview` | Exact-date cached retrieval with cutoff enforcement |
| Existing narrative convention | `src.mvp.llm_synthesis.Synthesizer` / `SynthesisResult` pattern | Provider-neutral dependency-injection and fail-closed design precedent |
| Repository I/O/date helpers | `src.utils.io` | Date normalization, versions, paths, hashes, and serialization conventions |
| Phase 5A outputs | Acquisition-feasibility review only | Reported as unavailable warning; no Phase 5B alignment signal is fabricated |
| Unwind structure | `src.monitoring.unwind_structure.build_unwind_assessment` | Retained six rows plus the v2 multi-label mechanism contract |
| Theme concentration | `src.risk.theme_concentration.build_theme_concentration_snapshot` | `t-1` correlated active-long cluster and selected-date liquidation proxy |

The lower-level archived retrieval/classification infrastructure was not
rewired into the final card. Phase 6 preserves the repository's existing
exact-date evidence replay boundary.

## Files added

- `docs/phase_6_implementation_plan.md`
  - verified the existing repository and froze the smallest integration path.
- `src/mvp/evidence_interpretation.py`
  - eight-field interpretation schema, allow-listed provider payload,
    versioned instructions, evidence-ID validation, safety validation, and
    deterministic fallback.
- `tests/test_deterministic_evidence_input.py`
  - adapter schema, date/profile validation, cutoff, warnings, comparison, and
    reproducibility tests.
- `tests/test_evidence_interpretation.py`
  - invariance, credential fallback, unsupported IDs, empty retrieval, schema,
    unsafe prose, numerical claims, and list-size tests.
- `src/risk/theme_concentration.py`
  - pure point-in-time correlated-cluster, concentration, liquidation, volume,
    and liquidity-proxy calculations.
- `tests/test_theme_concentration.py`
  - cross-sector cluster, unchanged effective-bets, selected-date exclusion,
    and future-row leakage tests.

## Files modified

- `src/mvp/evidence_card.py`
  - added the validated deterministic adapter while reusing the existing
    Evidence Card integration path.
- `notebooks/03_pm_evidence_card_demo.ipynb`
  - now uses the deterministic adapter and constrained interpreter, has one
    four-variable parameter cell, a ranked before/after comparison, and the
    final consolidated PM card.
- `src/mvp/demo_smoke_test.py`
  - now validates the same adapter-plus-interpreter flow as the notebook.
- `tests/test_evidence_card.py`
  - freezes the Evidence Card contract and approved profile boundary.
- `tests/test_demo_smoke_test.py`
  - validates date-driven output, profile, evidence availability, and
  deterministic interpretation mode.
- `src/monitoring/unwind_structure.py`
  - upgrades the assessment to v2, adds three independent mechanism contracts,
    and retains a documented v1 single-label compatibility view.
- `tests/test_unwind_structure.py`
  - validates independent triggers, multi-label output, optional beta context,
    missing evidence, and the v2 schema.
- `docs/demo_walkthrough.md`
  - current minute-by-minute script, Q&A, phrases to avoid, and failure
    fallback.
- `phase_6_review.md`
  - replaced the earlier Phase 6A handoff with this final end-to-end review.

No dependency, dataset, website, model fit, or threshold-profile expansion was
added.

## Scenario-v2 extension

The v2 assessment adds:

- `mechanism_scenarios`, three ordered condition-level results;
- `active_scenarios`, every mechanism with status `triggered`;
- `theme_concentration`, the validated `correlated_theme_proxy`;
- a retained `scenario_classification` field documented as a lossy v1
  compatibility view.

The theme proxy uses existing prices, SPY benchmark returns, holdings, volume,
dollar volume, and sector labels. Cluster correlation stops at `t-1`, and
tests prove that selected-date or future returns cannot alter the cluster
definition. It does not claim to observe ownership, leverage, or forced sales.

## QA results

The final Session 6 QA pass ran on 2026-07-29.

| Required check | Result |
|---|---|
| Date reaches deterministic pipeline | Pass: `2024-01-05`, `2020-03-24`, and `2026-05-29` produce date-specific results |
| Comparison date handled | Pass: `2023-12-01` and `2020-02-24` produce non-null per-signal changes where supported |
| Threshold profile recorded | Pass: `default` appears in the adapter, metadata, card, smoke output, and run configuration |
| Retrieval respects cutoff | Pass: every evidence timestamp is at or before `data_cutoff` |
| LLM cannot alter deterministic values | Pass: immutable input snapshots and schema boundaries are tested |
| LLM-disabled fallback works | Pass: `USE_LLM=False` renders the complete card |
| Unavailable data is warned | Pass: `2026-05-29` has empty evidence plus explicit uncertainty |
| Final card renders | Pass: four HTML outputs, one inline PNG, all required sections, no execution errors or stderr |
| Repeated deterministic runs stable | Pass: identical input returns identical schema output and run ID |

Final automated results:

```text
Smoke test: status=ready
Notebook: 24 cells, 12 code cells, no errors
Full suite: 292 passed, 4 skipped
git diff --check: clean
```

The four skips are existing optional cache/data-availability skips, not Phase 6
failures.

## Exact commands to run

### Read-only pre-demo gate

```bash
uv run python -m src.mvp.demo_smoke_test
```

Expected output includes:

```text
"status": "ready"
"primary_run_id": "53c34aa57bb437fc"
"threshold_profile": "default"
"interpretation_use_llm": false
```

### Execute the notebook headlessly

```bash
uv run jupyter-execute \
  --inplace \
  --timeout=120 \
  notebooks/03_pm_evidence_card_demo.ipynb
```

### Open the notebook for the live demo

```bash
uv run --with jupyterlab jupyter lab \
  notebooks/03_pm_evidence_card_demo.ipynb
```

### Run focused Phase 6 checks

```bash
uv run python -m pytest -q \
  tests/test_deterministic_evidence_input.py \
  tests/test_evidence_interpretation.py \
  tests/test_evidence_card.py \
  tests/test_demo_smoke_test.py
```

### Run the complete repository suite

```bash
uv run python -m pytest
```

## Required environment variables

For the recommended deterministic demo:

```text
None
```

The notebook, retrieval cache, interpretation fallback, and final card run
without network access or an API key.

For a future live injected interpreter, the current credential gate recognizes:

```text
OPENAI_API_KEY
ANTHROPIC_API_KEY
```

Credentials alone are insufficient. The notebook also requires an approved
object implementing `EvidenceInterpreter` to be injected as
`INJECTED_INTERPRETER`. No vendor client is included, and no live credential
call was made during Phase 6.

## Tested example dates

### Primary quant-plus-evidence demo

```text
AS_OF_DATE = 2024-01-05
COMPARE_TO_DATE = 2023-12-01
THRESHOLD_PROFILE = default
```

Verified:

- state: `bear_low_volatility`;
- triggered signals: zero;
- retrieved evidence: seven items;
- evidence split: three supporting, one contradicting, three contextual;
- cutoff: `2024-01-05T16:00:00-05:00`;
- run ID: `53c34aa57bb437fc`.

### Elevated quantitative contrast

```text
AS_OF_DATE = 2020-03-24
COMPARE_TO_DATE = 2020-02-24
THRESHOLD_PROFILE = default
```

Verified:

- state: `panic_elevated`;
- triggered signals: three;
- retrieved evidence: unavailable at this exact date;
- run ID: `87c48fc913f38386`.

### Missing-evidence and no-comparison case

```text
AS_OF_DATE = 2026-05-29
COMPARE_TO_DATE = None
THRESHOLD_PROFILE = default
```

Verified:

- state: `normal`;
- triggered signals: zero;
- retrieved evidence: empty;
- comparison view: explicitly unavailable;
- missing-evidence uncertainty: visible;
- run ID: `4fc9fd29eb452a25`.

Tests also cover future-date rejection, a comparison date not strictly before
the as-of date, and rejection of unknown threshold profiles.

## Interpretation and fallback behavior

The eight model-owned fields are:

- `narrative_state`;
- `narrative_changes`;
- `supporting_evidence_ids`;
- `contradicting_evidence_ids`;
- `missing_or_uncertain_evidence`;
- `pm_interpretation`;
- `monitoring_questions`;
- `invalidation_conditions`.

Operational metadata records effective `use_llm`, prompt/version, and warnings.

Fail-closed behavior:

- `USE_LLM=False`: deterministic interpretation, no provider call;
- no supported credential: deterministic interpretation plus warning;
- credential but no interpreter: deterministic interpretation plus warning;
- provider error or invalid schema: output discarded, deterministic
  interpretation plus warning;
- unsupported or stance-inconsistent evidence ID: removed and warned;
- empty retrieval: no citations and an explicit uncertainty statement;
- unsafe numerical, causal, certainty, or trade language: provider output is
  rejected.

An injected schema-valid test provider was exercised without a network call to
verify the notebook's effective `USE_LLM=True` rendering. A live vendor call
remains untested and unavailable.

## Historical context status

`historical_analogs` is implemented only as aggregate state-conditional output
from `build_insurance_table`. It is not a nearest-neighbor or named-episode
retriever.

The final compact card does not present these rows as matched analogs. The demo
uses the explicit `2020-03-24` comparison for historical contrast and explains
that similarity does not imply the same future path.

## Known limitations

- Evidence is a small exact-date validated cache replay, not live or broad
  point-in-time retrieval.
- `2024-01-05` is the only complete date with quantitative history and a
  validated exact-date evidence cache.
- No concrete vendor LLM client is included; live provider behavior, latency,
  cost, retry, and outage handling are not production-tested.
- Schema and lexical safety checks cannot prove complete semantic grounding of
  arbitrary prose.
- `deterministic_score` is intentionally unavailable; no composite crash
  probability is fabricated.
- `default` is the only approved threshold profile.
- Historical context is aggregate and descriptive, not a matched analog
  forecast.
- Crowding and positioning measures are proxies rather than observed
  institutional holdings.
- Historical security membership is survivorship-biased.
- Evidence does not establish causality.
- Phase 5B fundamental alignment remains unavailable and unapproved.

## Mocked or unavailable functionality

- The live LLM provider is unavailable. Tests use an injected structured stub
  and test-only credential marker; no network model output is stored or
  presented as live.
- Evidence retrieval is a deterministic local cache replay, not autonomous web
  search.
- A previously saved LLM example is not required for the demo and was not
  fabricated. If one is ever used, it must be labeled with date, run ID,
  evidence IDs, prompt/model version, and non-live status.
- True historical analog retrieval is unavailable.
- Additional threshold profiles are unavailable pending research approval.

## Semiconductor case-study status

The semiconductor case study remains optional and was not started.

A thematic semiconductor correction is not automatically a canonical
cross-sectional UMD momentum crash. Adding that case would require an approved
sector definition, point-in-time evidence, and a separate validation question.
It is not required for the core demo and should not be improvised during the
interview.

## Recommended post-interview work

Prioritize defensibility rather than interface expansion:

1. build and evaluate a broader archived point-in-time evidence corpus;
2. quantify retrieval recall, precision, stance balance, and contradiction
   capture on a blinded labeled set;
3. replace current-membership historical constituents with a point-in-time
   universe;
4. define governance for approved threshold profiles and sensitivity review;
5. select and evaluate a named LLM provider only with secret management,
   timeouts, retries, logging, schema monitoring, grounding evaluation, and
   cost controls;
6. preserve the smoke gate, deterministic adapter, and notebook regression
   cases as the acceptance harness.

The optional semiconductor case should remain deferred until the core evidence
and provenance work is accepted.
