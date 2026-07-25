# Next steps

Both overlays now exist. The prototype answered its question — see
`outputs/narrative_poc_review.md`. What follows is scope and judgement, not
plumbing.

## State

| Panel | Status |
|---|---|
| Positioning | Complete. 2,402 dates, 200/200 symbol match, days-to-cover reconciled to FINRA's own figure at 0.974 median. |
| Narrative | Prototype. 2,385 dates, two mechanisms (`panic`, `riskoff`), **volume only — no tone**, breadth undefined. |

106 tests pass, 1 skip (the tone-dependent assertion).

## 1. Decide what the `days_to_cover` sign behaviour means for the evidence layer

The most consequential open question, and the prototype sharpened it rather than
settling it.

`days_to_cover` mechanically **falls** during stress because volume is its
denominator: mean `days_to_cover_z` was −2.23 in March 2020 and −1.73 in the
August 2024 unwind. The narrative overlay rises in exactly those windows
(+3.09 and +4.06). So the pair is informative, but **only if the consumer knows
the structured metric inverts under stress.** If the evidence layer reads a high
`days_to_cover_z` as "crowded", it will read the most dangerous moments as safe.

Options: carry a volume-neutral variant alongside; document the inversion and
require the consumer to handle it; or combine the two overlays into one state
that is explicitly conditioned on the volume regime. This is a design decision
about what the overlay is *for*.

## 2. Acquire `crowding` when GDELT access returns (3 requests)

`crowding` is the direct narrative counterpart of the positioning panel — short
squeezes and crowded-trade deleveraging against measured squeeze. `riskoff`
currently stands in for it only because `riskoff` happened to be cached.

```bash
uv run python -m src.data.gdelt --queries crowding
```

Fail-fast and resumable. Do not loop it.

## 3. Add tone (2 requests per query)

Tone is half the narrative construct and is entirely absent. It needs
`timelinetone` **and** `timelinevolraw` for the raw-count weights; no query
currently holds both.

Everything for it is implemented and tested — the raw-count weighting, the
NaN-on-missing-weight rule, the zero-match rule. Only the data is missing.

## 4. Run the semantic sanity check (4 requests)

```bash
uv run python -m src.data.gdelt_sanity
```

Both queries carry `precision_flag = "unassessed"`. The episode evidence is
strong indirect support — the eight largest `panic_vol_z` readings are all real
stress events — but nobody has read a headline these queries actually return.

## 5. Confirm the 12-2 formation window convention

Implemented per the spec's literal wording: month end *m*−12 to *m*−2, a
10-month window skipping two months. The more common convention skips one. It is
point-in-time safe either way; someone should confirm which was intended.

## 6. Revisit the normalisation rule if it matters downstream

The narrative panel uses 100 of 126; the positioning panel uses the strict 126.
Measured on real data the relaxation buys 530 z-scores (+30%), less than the
original argument claimed — the archive gaps turned out to be clustered, not
spread. Both rules are viable. If a single convention is wanted across panels,
now is the cheap moment to pick one.

## Out of scope, unchanged

No risk state module, conditional probability or severity computation, evidence
layer, retrieval, LLM attribution, analogs, or PM brief. Nothing is fitted in
this project — no model, folds, freeze manifest, or bootstrap.
