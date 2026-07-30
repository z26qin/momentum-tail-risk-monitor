# PM Evidence Card — 20-minute demo walkthrough

## Pre-demo reliability check

Run these commands from the repository root:

```bash
uv run python -m src.mvp.demo_smoke_test
uv run jupyter-execute \
  --inplace \
  --timeout=120 \
  notebooks/03_pm_evidence_card_demo.ipynb
uv run python -m pytest
```

Expected results:

- smoke output contains `"status": "ready"`;
- the notebook saves without an execution error;
- the full suite reports `253 passed, 4 skipped`;
- the default run ID is `53c34aa57bb437fc`.

Open the pre-executed notebook:

```bash
uv run --with jupyterlab jupyter lab \
  notebooks/03_pm_evidence_card_demo.ipynb
```

Use this reliable parameter configuration:

```python
AS_OF_DATE = "2024-01-05"
COMPARE_TO_DATE = "2023-12-01"
THRESHOLD_PROFILE = "default"
USE_LLM = False
```

`default` is the only approved threshold profile. Do not invent a sensitivity
profile during the demo.

## Minute 0–2 — Problem Framing

Open with one question:

> Is the current momentum environment becoming fragile, what is driving the
> change, and what evidence would confirm or invalidate that view?

Make three points:

1. Momentum crashes are rare and state-dependent; a rebound can hurt the
   recent-winner/short-loser construction in ways a normal-volatility summary
   misses.
2. A single score is insufficient because state, leg behavior, drawdown,
   thresholds, corroborating evidence, and missing evidence matter separately.
3. This tool monitors fragility and organizes auditable evidence. It does not
   claim perfect crash prediction or prescribe a trade.

Show the architecture cell:

```text
date + approved threshold profile
→ deterministic indicators and risk state
→ point-in-time evidence retrieval
→ optional constrained interpretation
→ final PM Evidence Card
```

## Minute 2–5 — Research Foundation

Point to the four deterministic indicators:

- high-volatility recovery;
- short-minus-long beta gap;
- long-short portfolio drawdown;
- short-leg loss during recovery.

Explain the discipline:

- Phase 1–4 code owns all values, thresholds, trigger states, comparison
  deltas, and the run ID.
- Thresholds are prior-only research rules under the single approved
  `default` profile; the demo does not tune them on showcased dates.
- The selected as-of date creates a post-close cutoff. Evidence published
  after that cutoff is rejected.
- Labels and historical summaries are admitted only when their horizons have
  matured.
- Interpretation receives a detached, allow-listed copy of structured facts.
  It has no output field that can overwrite a quantitative value.

Do not call the state a probability of a crash. The repository intentionally
leaves `deterministic_score` unavailable rather than manufacturing a composite
number.

## Minute 5–9 — Quantitative Demo

Start with:

```python
AS_OF_DATE = "2024-01-05"
COMPARE_TO_DATE = "2023-12-01"
THRESHOLD_PROFILE = "default"
USE_LLM = False
```

Run all cells and show:

1. run metadata, including the selected dates, profile, cutoff, and run ID;
2. the complete four-indicator quantitative table;
3. the trailing selected-date context chart;
4. the before-versus-after table ranked by absolute structured change;
5. the deterministic section of the final card before discussing narrative.

For a clear date-driven contrast, change the parameter cell to:

```python
AS_OF_DATE = "2020-03-24"
COMPARE_TO_DATE = "2020-02-24"
THRESHOLD_PROFILE = "default"
USE_LLM = False
```

Run all cells. The expected contrast is:

- state changes from `bear_low_volatility` to `panic_elevated`;
- triggered conditions change from zero to three;
- comparison deltas and the ranked before/after view change;
- run ID changes from `53c34aa57bb437fc` to
  `87c48fc913f38386`;
- evidence becomes unavailable because no validated exact-date cache exists.

The notebook also runs this two-date regression internally and fails if the
quantitative signatures, interpretations, or run IDs do not change.

Return to `2024-01-05` before the evidence discussion. It is the only date with
both complete quantitative history and a validated date-matched evidence
cache.

## Minute 9–14 — Evidence Layer

In the final card, show the three separate evidence areas:

- supporting elevated risk;
- contradicting or moderating;
- contextual, missing, or uncertain.

For `2024-01-05`, the validated cache contains seven items: three supporting,
one contradicting, and three contextual. Point to source names, timestamps,
locators, and the `2024-01-05T16:00:00-05:00` cutoff.

Explain what text adds:

- it distinguishes support, contradiction, and context;
- it makes missing evidence explicit;
- it gives the PM monitoring questions and invalidation conditions;
- it does not establish causality.

Explain the constrained interpretation boundary:

- the model can return only the eight validated narrative fields;
- citations are evidence IDs already present in retrieval;
- unsupported or stance-inconsistent IDs are removed and warned;
- generated numerical claims, causal certainty, crash certainty, and trading
  recommendations fail closed;
- the deterministic object is checked for mutation before and after provider
  execution.

Keep `USE_LLM=False` for the reliable live demonstration unless an approved
provider and credentials have been tested before the meeting. The deterministic
interpretation is complete and uses the same validated schema.

## Minute 14–17 — Historical Context

Use the `2020-03-24` comparison as the main historical contrast. Discuss which
conditions differ from the primary case without claiming that the same future
path must follow.

The adapter also carries state-conditional historical summaries from
`build_insurance_table`. These are aggregate matured-label base rates, not a
true matched-episode analog retriever. The compact final card does not present
them as named analogs. If asked:

- describe them as historical context only;
- emphasize sample size and state conditioning;
- do not imply recurrence, causal similarity, or a calibrated forecast;
- do not improvise a named analog that the repository did not retrieve.

## Minute 17–20 — PM Use and Limitations

Frame the use case as a monitoring process:

- identify which implemented conditions are triggered;
- see what changed since the comparison date;
- examine support and contradiction from contemporaneous evidence;
- review what to monitor next;
- define what would weaken the interpretation;
- retain the cutoff, profile, warnings, and run ID for audit.

Close with limitations:

- evidence is a small exact-date validated cache, not broad live retrieval;
- crowding and positioning fields are proxies rather than observed books;
- the historical security universe is survivorship-biased;
- only one threshold profile is approved;
- no composite deterministic score is defined;
- no concrete vendor LLM client ships with the repository;
- evidence is descriptive and cannot establish causality.

The production path is governance and data hardening, not a richer interface:
a broader archived corpus, point-in-time membership, retrieval evaluation,
approved threshold governance, provider timeout/logging/evaluation policy, and
operational monitoring.

## Likely questions and concise answers

### Is this predicting a momentum crash?

No. It monitors implemented fragility conditions and organizes evidence around
them. The output is an elevated-monitoring aid, not a crash probability or
trade instruction.

### Why use an LLM?

Only to organize validated structured facts into a short PM interpretation,
monitoring questions, and invalidation conditions. The deterministic pipeline
already works without it.

### What incremental value does text add?

Text distinguishes supporting, contradicting, contextual, and missing evidence.
That helps a PM understand whether a quantitative warning is corroborated,
moderated, or unresolved.

### How do you prevent hallucination?

The interpreter sees an allow-listed payload, returns a strict schema, cites
only supplied evidence IDs, cannot return quantitative fields, and fails closed
on unknown IDs or unsafe claims. This reduces risk but does not prove semantic
grounding, so the deterministic card and source evidence remain visible.

### Are the thresholds overfit?

The demo uses prior-only research thresholds and one frozen `default` profile.
It does not tune thresholds on the demo dates. Production sensitivity analysis
would require explicit research and governance approval.

### Is this UMD or a thematic semiconductor signal?

It is a cross-sectional momentum/UMD-oriented monitor. A semiconductor or AI
theme correction is not automatically a canonical UMD momentum crash, and no
semiconductor case was added.

### How would you validate the evidence layer?

Expand the archived point-in-time corpus, label a blinded evaluation set,
measure retrieval recall and precision by mechanism and stance, test
contradiction capture, audit timestamp/version provenance, and evaluate
interpretation grounding separately from retrieval.

### What changes in production?

Use point-in-time membership, broader versioned archives, governed profile
configuration, a named provider/model, secret management, timeouts, retries,
logging, cost controls, schema monitoring, and scheduled regression tests.

### What happens when retrieval or the LLM fails?

The quantitative card remains intact. Empty or invalid retrieval becomes an
explicit uncertainty warning; unavailable credentials, provider errors, or
invalid model output produce `use_llm=False` and deterministic interpretation.

### What should a PM do with the card?

Use it to escalate monitoring, review the named conditions and evidence, and
decide what further research is warranted under the firm's process. The card
does not recommend a position.

## Demo failure fallback

Use this sequence without improvising:

1. Set `USE_LLM=False` and Run All.
2. Show the deterministic card, comparison table, retrieved evidence, warnings,
   monitoring questions, and invalidation conditions.
3. Show a previously saved schema-valid interpretation only if it is clearly
   labeled as a saved example and its date, run ID, evidence IDs, prompt
   version, and non-live status are visible.
4. Explain that LLM interpretation is optional and is never the numerical
   source of truth.

Additional recovery:

- If retrieval is empty, use `2026-05-29` to demonstrate the explicit
  unavailable-evidence warning, then return to the primary case.
- If the kernel fails, restart it from the repository root and Run All; the
  checked-in notebook remains pre-executed.
- If the context chart fails to display, continue with the quantitative table,
  before/after table, and final card. The chart does not compute the state.

## Phrases to avoid

- “The model predicts a crash.”
- “The news caused the signal.”
- “The historical analog proves what happens next.”
- “No retrieved contradiction means the thesis is confirmed.”
- “This semiconductor selloff is a UMD crash.”
- “The PM should buy, sell, hedge, overweight, or underweight.”
