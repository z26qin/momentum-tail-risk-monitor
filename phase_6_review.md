# Phase 6 review — validated PM Evidence Card demo

## Outcome

The Phase 6 demo is ready for a deterministic, offline 20-minute presentation.
The notebook runs end to end, the complete test suite passes, two fixed
historical dates produce different quantitative cards, evidence is enforced at
the point-in-time cutoff, and no language-model credential is required.

No Phase 1–5 signal definition, label, validation method, trained model,
threshold, or research conclusion was changed.

## Final architecture

```text
Versioned local market and momentum artifacts
                    |
        Phase 1–4 deterministic components
                    |
     Risk state + four-indicator scorecard
                    |
   Cutoff-validated cached evidence (optional)
                    |
Constrained narrative-only synthesizer (optional)
                    |
       Validated and rendered Evidence Card
```

The quantitative layer owns every state, value, threshold, trigger, comparison
delta, and descriptive historical frequency. The synthesis interface can write
only narrative fields. Retrieval or synthesis failure leaves the quantitative
card intact and produces an explicit warning.

## Task 0 validation results

| Check | Final result |
|---|---|
| Notebook runs end to end | Pass: 11 code cells, no errors |
| Relevant and full tests pass | Pass: 231 passed, 4 skipped |
| Deterministic fallback works | Pass with no API credentials or external synthesizer |
| Selected date changes the result | Pass: fixed 2024 and 2020 signatures, triggers, evidence status, and run IDs differ |
| Comparison calculations work | Pass: per-indicator deltas and concise change list recompute |
| Text respects cutoff | Pass: validated in retrieval, integration, schema, tests, and smoke command |
| LLM layer is optional | Pass: reliable default is `USE_LLM = False` |
| Card renders without intervention | Pass: self-contained HTML rendering in a normal Jupyter kernel |

The baseline issue list was reported before editing. There were no blockers.
The concrete corrections were timezone-safe input dates, fail-closed retrieval
exceptions, schema-level evidence-cutoff validation, honest LLM fallback
labeling, versioned run metadata, and the missing demo/smoke presentation
elements.

## Files modified

- `src/mvp/evidence_card.py`
  - normalizes timezone-aware dates and rejects invalid/future dates;
  - fails closed on retrieval exceptions or evidence after the cutoff;
  - validates evidence timestamps again at the card schema boundary;
  - records data and quantitative-model versions in metadata and run IDs;
  - labels requested-but-unconfigured LLM use as deterministic fallback;
  - simplifies the PM-facing indicator and evidence rendering.
- `src/mvp/llm_synthesis.py`
  - makes the deterministic PM summary shorter and state-calibrated;
  - removes zero-change noise from the change list;
  - avoids describing a non-triggered state as guaranteed or generically benign.
- `src/mvp/demo_smoke_test.py`
  - adds the read-only pre-demo command and fixed two-date regression gate.
- `notebooks/03_pm_evidence_card_demo.ipynb`
  - adds `DEMO_MODE`, reliable defaults, data/model metadata, two-date
    validation, selected-date time-series context, separated evidence stances,
    concise historical context, and a re-rendered final card.
- `tests/test_evidence_card.py`
  - adds integration coverage for API-free fallback, retrieval exceptions,
    injected future evidence, run configuration metadata, and timezone-aware
    inputs.
- `tests/test_demo_smoke_test.py`
  - verifies that the pre-demo gate is ready and genuinely date-driven.
- `docs/demo_walkthrough.md`
  - replaces the mixed handoff with the final minute-by-minute walkthrough,
    PM questions, quant objections, and failure fallbacks.
- `phase_6_review.md`
  - this final review.

## Tests added or strengthened

The targeted Phase 6 coverage now explicitly verifies:

1. future as-of dates are rejected;
2. unknown threshold profiles are rejected;
3. comparison dates on or after the selected date are rejected;
4. LLM-on and LLM-off paths preserve identical quantitative fields;
5. evidence never exceeds the cutoff, including injected invalid evidence;
6. the card validates at its schema boundary;
7. missing API/external-synthesizer configuration uses deterministic fallback;
8. failed synthesis does not fail the card or notebook;
9. missing or failed retrieval produces explicit uncertainty and warnings;
10. identical deterministic inputs reproduce the same complete card;
11. metadata records dates, profile, horizon, LLM request, data version, and
    quantitative-model version;
12. an injected interpretation cannot alter indicator values or statuses;
13. timezone-aware input dates preserve their stated calendar date;
14. the smoke command proves two historical dates produce different results.

Final commands and results:

```bash
.venv/bin/python -m pytest -o addopts='' -q
# 231 passed, 4 skipped

.venv/bin/python -m src.mvp.demo_smoke_test
# "status": "ready"

git diff --check
# no output
```

The four skipped tests are pre-existing optional cache/data-availability skips,
not Phase 6 failures.

## Notebook run instructions

From the repository root:

```bash
.venv/bin/jupyter lab notebooks/03_pm_evidence_card_demo.ipynb
```

Open the notebook and choose **Run All**. It bootstraps repository imports when
started from either the root or `notebooks/`. The checked-in notebook is also
pre-executed.

Reliable demo configuration:

```python
DEMO_MODE = True
AS_OF_DATE = "2024-01-05"
COMPARE_TO_DATE = "2023-12-01"
THRESHOLD_PROFILE = "default"
USE_LLM = False
```

Headless deterministic card:

```bash
.venv/bin/python -m src.mvp.evidence_card \
  --as-of-date 2024-01-05 \
  --compare-to-date 2023-12-01 \
  --no-llm
```

## Smoke-test instructions

Run immediately before the meeting:

```bash
.venv/bin/python -m src.mvp.demo_smoke_test
```

This validates imports, required local data, notebook dependencies, schema
creation, cutoff compliance, deterministic rendering, and distinct quantitative
results for the two recommended historical dates. It does not write analytical
artifacts.

## Deterministic fallback and LLM configuration

No API key, language-model SDK, or external synthesizer is installed or
required. `USE_LLM = False` produces `deterministic_no_llm`.

If `USE_LLM = True` without an injected synthesizer, the card reports
`deterministic_fallback` and warns that no external synthesizer/API
configuration is installed. If an injected synthesizer raises or returns an
invalid object, its output is discarded and the same fallback is used.

An external implementation must satisfy the existing `Synthesizer` protocol
and return `SynthesisResult`. That result contains narrative text only; it has
no quantitative fields. A real network client remains intentionally
unimplemented.

## Exact recommended demo dates and expected output

### Primary evidence case

- As-of date: `2024-01-05`
- Comparison date: `2023-12-01`
- State: `bear_low_volatility`
- Triggered indicators: none of four
- Descriptive 20-day state-conditional tail-loss frequency: approximately 8.2%
- Material changes: beta gap and short-loss measure decreased; portfolio
  drawdown became slightly shallower
- Evidence: available from the validated cache — 3 supporting, 1
  contradicting, and 3 contextual items
- Expected deterministic run ID for the checked-in data/config:
  `53c34aa57bb437fc`

### Elevated quantitative contrast

- As-of date: `2020-03-24`
- Comparison date: `2020-02-24`
- State: `panic_elevated`
- Triggered indicators: high-volatility recovery, short-minus-long beta gap,
  and short loss in recovery
- Descriptive 20-day state-conditional tail-loss frequency: approximately 23.8%
- Comparison: the recovery gate turns on and short-loss magnitude rises
  materially
- Evidence: unavailable because there is no exact-date validated cache; the
  card shows explicit uncertainty and retains the quantitative result
- Expected deterministic run ID for the checked-in data/config:
  `87c48fc913f38386`

Run IDs intentionally include the selected dates, threshold profile, horizon,
indicator values, data version, and quantitative-model version. They will
change if those inputs change.

## Known limitations and mocked/incomplete functionality

- Evidence is a small exact-date validated cache replay, not live retrieval.
- The only fully usable quant-plus-evidence date is `2024-01-05`; broader
  evidence coverage is incomplete.
- No real LLM call is implemented. External synthesis is an injectable,
  constrained interface only.
- Crowding and positioning measures are proxies, not observed institutional
  books.
- Historical security membership is survivorship-biased.
- The default threshold profile is the only approved profile; governed
  sensitivity profiles are not implemented.
- State-conditional frequencies are descriptive, not calibrated forecasts or
  trading instructions.
- Text evidence is contextual and does not establish causality.
- The optional semiconductor/AI-infrastructure case study was not completed.
  The existing data did not support adding a defensible point-in-time sector
  case without expanding scope or infrastructure.

## Remaining technical debt

1. Build a broader archived point-in-time corpus with documented coverage and
   contradiction sampling.
2. Replace current-membership historical constituents with a point-in-time
   universe.
3. Add governed threshold sensitivity profiles only after research approval.
4. Implement an external synthesizer client only with explicit model/version,
   credential, timeout, logging, and evaluation policy.
5. Add a sector case only after defining the sector universe and separating
   thematic correction from canonical cross-sectional momentum.

## Recommended next phase after the meeting

Prioritize evidence and provenance hardening: expand the archived
point-in-time corpus, measure retrieval coverage and selection bias, and add a
point-in-time universe audit. Those changes improve defensibility more than a
new interface or a more elaborate LLM layer. Keep the current deterministic
Evidence Card and smoke gate as the acceptance harness for that work.
