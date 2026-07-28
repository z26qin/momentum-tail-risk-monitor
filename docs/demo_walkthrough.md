# PM Evidence Card — 20-minute walkthrough

## Pre-demo check

From the repository root, run:

```bash
.venv/bin/python -m src.mvp.demo_smoke_test
.venv/bin/python -m pytest -q tests/test_evidence_card.py tests/test_demo_smoke_test.py
```

The smoke result must say `status: ready`. Then open the pre-executed notebook:

```bash
.venv/bin/jupyter lab notebooks/03_pm_evidence_card_demo.ipynb
```

The reliable default is `DEMO_MODE = True`, `AS_OF_DATE = "2024-01-05"`,
`COMPARE_TO_DATE = "2023-12-01"`, `THRESHOLD_PROFILE = "default"`, and
`USE_LLM = False`. The pipeline computes the output; demo mode does not hardcode
an analytical result.

## Minute 0–2 — Problem framing

Ask one question:

> Is the current momentum environment becoming fragile, what is driving that
> change, and what evidence would confirm or invalidate the warning?

The system monitors momentum-fragility conditions. It does not claim to predict
every crash or convert the reading into a portfolio instruction. The intended
use is an auditable watch process for states in which a rebound can squeeze the
recent-loser leg.

## Minute 2–5 — Research foundation

Show the compact architecture and the four deterministic indicators:

- high-volatility recovery;
- short-minus-long beta gap;
- long-short portfolio drawdown;
- short-leg loss during recovery.

The quantitative layer determines the state and triggers. Thresholds use only
prior observations. The selected date establishes a post-close cutoff, and
retrieved text published later than that cutoff is rejected. Narrative
synthesis receives structured facts only and has no field through which it can
change a number, threshold, status, or run ID.

## Minute 5–9 — Interactive quant demo

Start with `2024-01-05` versus `2023-12-01` and run all cells. Show:

1. the state summary and four-indicator table;
2. the trailing 252-observation context clipped at the selected date;
3. the three material changes versus the comparison date.

Then use the elevated fixed case:

```python
AS_OF_DATE = "2020-03-24"
COMPARE_TO_DATE = "2020-02-24"
```

Run all cells again. The state changes from `bear_low_volatility` to
`panic_elevated`, the triggered set changes from zero indicators to three, the
comparison deltas change, and a new run ID is produced. The notebook's
date-interactivity regression cell computes both cases and fails if their
quantitative signatures are identical.

Return to `2024-01-05` before the evidence discussion because it is the only
date with both complete quantitative history and a validated date-matched
evidence cache.

## Minute 9–14 — Evidence layer

Read the evidence in three separate groups:

- supporting;
- contradicting or moderating;
- contextual, uncertain, or missing.

The evidence is a replay of a small validated local cache, not live retrieval.
It may organize support or contradiction but does not establish causality. Point
out the publication timestamps and the `2024-01-05T16:00:00-05:00` cutoff.

Set `USE_LLM = True` only if you want to demonstrate failure behavior. No
external synthesizer or API configuration is installed in this repository, so
the card explicitly reports `deterministic_fallback` and continues. An injected
external synthesizer must return the narrative-only `SynthesisResult` schema;
any exception or invalid response also falls back.

## Minute 14–17 — Historical context or comparison

Use the comparison section as the primary historical view. It shows what
materially changed without implying that a historical episode must repeat.

If time permits, show the compact state-conditional table. These are descriptive
20-day tail-loss frequencies from matured labels, not calibrated crash
probabilities or causal estimates. Do not present the `2020-03-24` case as proof
that the system forecasts every momentum crash.

## Minute 17–20 — Implications and limitations

A PM can use the card to decide what deserves monitoring, what evidence is
missing, and what would invalidate the warning. It is not an investment
recommendation. Productionization would require a larger archived
point-in-time corpus, a point-in-time security universe, approved policy
thresholds, and an explicitly configured and monitored language-model client.

### Three main messages

1. The quantitative layer determines the risk state.
2. The LLM explains and organizes evidence but does not invent the signal.
3. The value is auditable decision support, not an opaque crash forecast.

### Likely PM questions

**What action should I take from this?**

Treat it as a monitoring escalation, not a trade instruction. Review exposures,
liquidity, and the named invalidation conditions under the firm's own mandate.

**Why not just use a dashboard?**

A dashboard can display the same deterministic layer. The Evidence Card adds an
auditable explanation of what changed, separates support from contradiction,
and makes missing evidence and invalidation conditions explicit.

**What does the LLM add?**

Only narrative organization. It can shorten and structure the evidence review;
it cannot calculate or edit quantitative fields. The demo remains complete
without it.

**How do you know the news is causal?**

We do not. Co-occurrence is context, not causal identification, and the card
says so.

**How sensitive is this to thresholds?**

The demo uses one approved default profile. Thresholds are prior-only research
rules, not tuned on the demo dates. A production review should add governed
sensitivity analysis rather than silently changing the profile.

**Does it detect the current semiconductor selloff?**

That case was not added because the repository lacks sufficient supported
point-in-time sector evidence. A thematic correction is not automatically a
canonical cross-sectional UMD momentum crash.

**What happens if the LLM is wrong?**

Its response is schema-validated and narrative-only. Invalid output or a failed
call is discarded, a warning is shown, and deterministic text is used.

### Likely quant-researcher objections

**Look-ahead leakage**

Labels are admitted only after their horizon matures; thresholds use prior
observations; evidence must precede the selected post-close cutoff.

**Threshold overfitting**

The demo does not tune thresholds on showcased dates. Only the frozen default
profile is supported.

**Data snooping**

The card composes existing research outputs and does not retrain or select a new
model from these examples. The examples demonstrate mechanics, not new
statistical significance.

**Weak crowding proxies**

Agreed. Beta, drawdown, and short-leg loss are fragility proxies, not direct
positioning measurements.

**Selection bias in retrieved text**

Agreed. The cached corpus is small, and missing contradiction is explicitly not
treated as confirmation.

**Unstable LLM outputs**

The deterministic path is the default. External output is constrained to five
narrative fields, validated, and discarded on failure.

**Confusing sector momentum with UMD**

The system monitors a cross-sectional momentum construction. A sector or theme
selloff requires separate labeling and must not be called a UMD crash without
supporting evidence.

**Lack of causal identification**

The evidence layer is corroborative and descriptive. It makes no causal claim.

### Demo failure fallback

- **LLM API fails:** leave `USE_LLM = False`, or show the explicit
  `deterministic_fallback`. The quantitative card is unchanged.
- **Retrieval is empty:** show the deterministic card and its
  `evidence_quality = unavailable` warning. Absence is uncertainty.
- **Kernel needs restarting:** restart, confirm the repository root, and Run
  All. The notebook bootstraps `src` imports from either the root or
  `notebooks/`.
- **One visualization fails:** run the smoke command and use the pre-executed
  state table plus final deterministic Evidence Card. The chart is not needed
  to compute the result.
