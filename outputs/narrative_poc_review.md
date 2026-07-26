# Narrative overlay — proof-of-concept result

Built 2026-07-25 from cached GDELT payloads with **zero further API calls**.
GDELT's IP block was still in force (verified: HTTP 429 after ~10 hours of
near-silence), so the prototype was assembled from what was already on disk.

## Headline result

**The narrative overlay fires precisely when the structured overlay goes
quiet.** This is the single most useful thing the prototype shows, because it
addresses a known blind spot rather than duplicating an existing signal.

| Episode | `panic_vol_z` | `riskoff_vol_z` | `days_to_cover_z` | `short_vol_share_z` |
|---|---:|---:|---:|---:|
| Mar-2020 COVID crash | **+3.09** | +0.93 | **−2.23** | −0.81 |
| Aug-2024 unwind | **+4.06** | +1.99 | **−1.73** | +0.11 |
| Apr-2025 selloff | **+1.81** | +3.00 | **−1.47** | +0.77 |
| Mar-2023 bank stress | +0.91 | +1.12 | −1.01 | +0.11 |
| Jun-2022 selloff | +0.15 | −0.36 | −0.15 | +0.86 |
| Jan-2021 squeeze | +0.02 | −0.54 | +0.54 | +0.01 |
| Apr-2020 rebound | +0.12 | −0.20 | −1.72 | +0.85 |

`days_to_cover` mechanically **falls** during stress because volume is its
denominator and volume explodes in a crash. In all four of the most stressed
episodes the narrative panel rises while days-to-cover sinks. The two
conditional cuts agree:

- when `days_to_cover_z < −1` (n=491), mean `panic_vol_z` is **+0.49**;
- when `panic_vol_z > 2` (n=125), mean `days_to_cover_z` is **−0.66**.

Pooled correlations are modest and negative — `panic_vol_z` vs
`days_to_cover_z` is **−0.196** (n=1,988), `riskoff_vol_z` vs `days_to_cover_z`
is −0.143 — which is what a compensating signal should look like rather than a
redundant one.

January 2021 is a useful counter-example: elevated positioning (`dtc_z` +0.54)
with no panic narrative at all (+0.02). A single-name squeeze is not a market
panic, and the two overlays correctly disagree about it.

## Does the query actually work?

Yes, and this is the strongest evidence that the mechanism-level query design
does what it was meant to. The eight largest `panic_vol_z` readings, with no
episode-specific term anywhere in the query:

| Date | z | Episode |
|---|---:|---|
| 2018-02-07 | 24.54 | "VIXmageddon" volatility spike |
| 2024-08-06 | 22.34 | Yen-carry unwind |
| 2025-04-08 | 13.23 | April 2025 selloff |
| 2018-10-12 | 13.07 | October 2018 selloff |
| 2018-02-06 | 11.74 | same February 2018 episode |
| 2025-03-12 | 10.62 | March 2025 drawdown |
| 2024-08-07 | 10.34 | same August 2024 episode |
| 2022-02-25 | 8.60 | Ukraine invasion |

Every one is a real, identifiable equity-stress event. The panel senses episodes
generically, which is exactly what the hindsight rule was protecting.

**Caveat on magnitude.** A z of 24 does not mean 24 Gaussian sigmas. News
attention share is violently right-skewed and leptokurtic, so a rolling z on it
produces very large values by construction. These are ranks-in-context, not
tail probabilities, and must not be fed to anything that assumes normality.

## Correction to an earlier claim

I previously estimated that the strict all-126 normalisation rule would
"destroy" the narrative series, on the assumption that the 21 archive gaps were
spread evenly. **That assumption was wrong.** The real gaps are clustered:

| Gap | Days |
|---|---:|
| 2025-06-15 to 2025-07-01 | 17 |
| 2017-12-01 to 2017-12-02 | 2 |
| 2020-10-20 | 1 |
| 2023-03-23 | 1 |

Four gap *events*, not 21 scattered ones. Measured on the real panel:

| Rule | z-scores available (of 2,385 rows) |
|---|---:|
| Strict — all 126 preceding rows finite | 1,739 |
| Relaxed — 100 of 126 | **2,269** |

So the relaxation buys **530 additional z-scores (+30%)**, which is worthwhile
but far from the rescue I implied. The strict rule would have been usable. The
decision to relax was taken on my estimate, and the estimate was too pessimistic
— that is worth knowing before the rule is carried into anything downstream.

## What was actually built, and what is missing

`data/processed/narrative_panel.parquet` — 2,385 trading dates,
2017-01-03 to 2026-06-30.

| Series | Status |
|---|---|
| `panic_vol_intensity`, `panic_vol_z` | **Built.** 2,369 intensities, 2,269 z-scores. |
| `riskoff_vol_intensity`, `riskoff_vol_z` | **Built**, derived (see below). |
| `panic_tone`, `riskoff_tone` and their z-scores | **Empty.** Tone needs both `timelinetone` and the `timelinevolraw` raw counts that weight it; neither query holds both. Tone is left entirely NaN rather than weighted by the wrong units. |
| `crowding`, `rotation`, `policy` | **Absent.** Not enough cached to form a volume series. |
| `narrative_breadth` | **Undefined** (`narrative_breadth_defined = False`) — it is a five-mechanism statistic and only two exist. |

Two substitutions were made, both verified rather than assumed:

1. **`riskoff` volume is derived from `timelinevolraw`** as `100 × value / norm`.
   Verified arithmetically against the API in Stage 1: the anchor query on
   2020-01-01 gave 4,775 of 262,970 = 1.8158%, exactly GDELT's reported
   `timelinevol`. The two modes are arithmetically equivalent.
2. **Archive availability uses `riskoff`'s `norm` in place of the dedicated
   coverage series.** `norm` counts *all* monitored articles that day and should
   be query-independent. That was **verified directly**: two entirely different
   queries returned byte-identical `norm` on all 366 overlapping days of 2020.
   This closes an assumption that was still open at the end of Stage 1.

`riskoff` stands in for `crowding` as the second mechanism, because nothing of
`crowding` is cached. `crowding` remains the better pairing with the positioning
panel and should be acquired first when access returns.

## Limitations specific to this prototype

1. **No tone anywhere.** Half the narrative construct — attention *and* tone —
   is absent. Everything above rests on attention volume alone.
2. **No semantic sanity check.** Both queries carry
   `precision_flag = "unassessed"`. The episode evidence above is strong
   indirect support, but nobody has read the headlines these queries return.
3. **Two mechanisms of five.** No breadth measure, and `crowding` — the direct
   narrative counterpart of the positioning panel — is the missing one.
4. **The z-scores are not Gaussian.** See the magnitude caveat above.
5. **The narrative/positioning correlations are computed on 1,988 overlapping
   rows** from 2018-07-12, so the pre-2018 period contributes nothing.

## Reproduce

```bash
uv run python -m src.features.narrative_panel   # zero network calls
uv run pytest -q
```

To extend when GDELT access returns, in priority order:

```bash
uv run python -m src.data.gdelt --queries crowding   # 3 requests
uv run python -m src.data.gdelt --queries panic      # 2 requests: adds tone
uv run python -m src.data.gdelt_sanity               # 4 requests: precision flags
```

Each command is fail-fast and resumable: one attempt per request, stops on the
first refusal, never caches a refusal. Do not loop it.

---

# Addendum — 2026-07-25

Two changes since the prototype was written: a volume-free crowding metric was
added to the positioning panel, and the real `crowding` narrative query landed.

## The `days_to_cover` inversion is fixed

`short_interest_ratio` scales each symbol's print by its own trailing median
print, so no volume enters. Correlation with `panic_vol_z` falls from **−0.196
to −0.029**. Across the 139 days where `panic_vol_z > 2`, `days_to_cover_z`
averages −0.66 — reading "uncrowded" in the middle of a panic — while
`short_interest_ratio_z` averages −0.01.

What it is *not*: a positive stress signal. It sits near zero during panic
rather than going positive, and in March 2020 and April 2025 it still reads
mildly negative because short interest genuinely falls as shorts cover. And
removing volume removed the only daily-updating term — it takes 3 distinct
values a month against `days_to_cover`'s 21, and lags publication by ~8 business
days. It describes a **precondition**, not a trigger.

Read that way it does its job. Measured 1–3 months ahead of each episode:

| Episode | `short_interest_ratio_z` before | `days_to_cover_z` before |
|---|---:|---:|
| March 2020 COVID | +0.98 | +0.96 |
| January 2021 squeeze | +1.11 | −0.54 |
| August 2024 yen carry | +1.23 | +0.42 |
| April 2025 tariff | +0.51 | −1.12 |

All four positive on the volume-free measure; `days_to_cover` is negative going
into two of them. Four episodes, no significance testing, nothing fitted — a
description of four events, not evidence of predictive power.

## The `crowding` query works, and measures something other than this universe

The eight largest `crowding_vol_z` readings:

| Date | `crowding_vol_z` | What it was |
|---|---:|---|
| 2021-01-28 | 21.91 | Robinhood restricts GME buying |
| 2021-01-29 | 19.81 | GameStop squeeze |
| 2021-01-26 | 12.49 | GameStop squeeze |
| 2024-05-14 | 12.47 | Roaring Kitty returns, GME second spike |
| 2021-01-27 | 11.14 | GameStop squeeze |
| 2018-08-08 | 10.42 | Tesla "funding secured" |
| 2023-01-23 | 10.40 | Meme-squeeze revival |
| 2020-02-05 | 9.17 | Tesla parabolic squeeze |

Every one is a genuine short-squeeze episode, from a query carrying **no
episode-specific terms** — the hindsight rule holding up. This is the strongest
evidence so far that the frozen queries measure what they claim, though it is
still not a substitute for the semantic sanity check, which remains unrun.

**But its correlation with the structured panel is essentially zero**: +0.009
with `days_to_cover_z`, +0.022 with `short_interest_ratio_z`, +0.013 with
`short_vol_share_z`.

That is not a failure, and it is worth being precise about why. The universe
here is large-cap — the January 2021 loser leg holds names like BKNG, CRM, NOW
and ADBE. GME and AMC are not in it and never were. So the query is measuring
**market-wide squeeze salience**, not crowding inside this particular leg, and
the two are close to orthogonal by construction.

Whether that is useful depends on the claim being made. January 2021 *was* a
momentum crash driven by short-squeezed losers, and the two panels describe it
in complementary registers: the structured panel showed crowding building over
the preceding months (+1.11), and the narrative panel then registered the
squeeze itself at 21.9σ. Slow precondition, fast trigger. That is one episode,
and the honest summary is that the pairing is coherent rather than demonstrated.
