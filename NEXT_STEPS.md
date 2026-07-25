# Next steps

Both overlays now exist. The prototype answered its question — see
`outputs/narrative_poc_review.md`. What follows is scope and judgement, not
plumbing.

## State

| Panel | Status |
|---|---|
| Positioning | Complete. 2,402 dates, 200/200 symbol match, days-to-cover reconciled to FINRA's own figure at 0.974 median. Now carries volume-free crowding alongside. |
| Narrative | Prototype. 2,385 dates, two mechanisms (`panic`, `riskoff`), **volume only — no tone**, breadth undefined. |

115 tests pass, 1 skip (the tone-dependent assertion).

## 1. ~~Decide what the `days_to_cover` sign behaviour means~~ — **settled 2026-07-25**

Resolved by carrying a volume-neutral variant alongside. The panel now has
`short_interest_ratio` (level, versus each symbol's own trailing median print)
and `short_interest_change` (accumulation), neither of which touches volume.
See `docs/DECISIONS.md`.

Correlation with the panic narrative fell from **−0.196** to **−0.029**; in the
139 days where `panic_vol_z > 2`, `days_to_cover_z` averages −0.66 while
`short_interest_ratio_z` averages −0.01. The false "safe" reading is gone.

Two things this **did not** buy, both important:

- It is not a positive stress signal. It goes to roughly zero during panic, not
  positive. In March 2020 and April 2025 it still reads mildly negative, because
  short interest genuinely falls as shorts cover — a real effect, unlike the
  volume artifact.
- Removing volume removed the only daily-updating term. It takes 3 distinct
  values a month against `days_to_cover`'s 21, and lags publication by ~8
  business days. It is a **precondition** measure, not a trigger.

**Also done:** short interest as a fraction of shares outstanding is now in the
panel, from SEC EDGAR — 198 of 200 symbols, 11,221 observations, joined on
filing date. Leg median 1.86% of float. It is the only one of the three
crowding metrics that *rises* during panic (+0.26) rather than merely failing to
fall, but it is the weaker **precondition** signal, likely because monthly leg
turnover moves a cross-sectionally comparable measure for reasons that have
nothing to do with crowding. Keep both; they answer different questions.

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
