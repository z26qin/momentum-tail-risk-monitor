# Alternative-data review — positioning and narrative overlays

Session date: 2026-07-24. Branch `dear/remote-control-f6040f`.

> **Superseded in part, 2026-07-25.** The narrative panel now exists as a
> two-mechanism, volume-only prototype built from cached payloads with zero
> further API calls. Its results, limitations, and a correction to the
> normalisation-rule reasoning are in **`outputs/narrative_poc_review.md`**,
> which takes precedence over the narrative sections below. Everything about
> the positioning panel here remains current.

## Executive summary

This session was asked for two panels. **Both now exist; one is a prototype.**

- **Positioning panel: complete.** `data/processed/positioning_panel.parquet`,
  2,402 trading dates from 2017-01-03 to 2026-07-24, built on FINRA short
  interest joined on **publication date** and FINRA daily short-sale volume.
  All match rates are 100% at the symbol level.
- **Narrative panel: prototype.** 2,385 trading dates, two mechanisms
  (`panic`, `riskoff`), **volume only — no tone**, `narrative_breadth`
  undefined. GDELT's IP block was never lifted, so it was assembled from
  already-cached payloads via two independently verified substitutions. See
  `BLOCKERS.md` and `outputs/narrative_poc_review.md`.

**The prototype's headline result:** the narrative overlay fires precisely when
the structured one goes quiet. `days_to_cover` mechanically falls during volume
spikes (mean z −2.23 in March 2020, −1.73 in August 2024) while `panic_vol_z`
rises (+3.09 and +4.06). That addresses a known blind spot rather than
duplicating an existing signal, and it is the most useful thing these two
overlays do together.

Neither panel alters the risk number. Both inform monitoring and feed the
downstream evidence layer. No model, fold, freeze manifest, or bootstrap was
built, in line with the current architecture.

---

## 1. Probe findings

### 1.1 GDELT schema and frequency

Everything below was observed, not assumed.

| Assertion | Result |
|---|---|
| One observation = exactly one UTC calendar date | **Holds.** Every timestamp is `YYYYMMDDT000000Z`; zero non-midnight buckets across a normal year, a leap year, and a full-range request. |
| All three modes return identical date grids | **Holds** on the 2020 probe: 366/366/366, set-identical. |
| No smoothing | **Holds.** `timelinesmooth=0` accepted; `query_details.date_resolution` reports `"day"`. |
| No adaptive multi-day bins | **Holds**, including over a single 2017-2026 request. |
| Every requested date present or unambiguously missing | **Qualified.** See below. |

**The blocking condition specified for this session was tested and does not
hold.** Bins are daily; the day-to-trading-date mapping is well defined. Stage 2
failed on retrieval, not on mapping.

**Absent versus zero.** GDELT omits days rather than reporting zeros: a
fully non-matching query returns `{}`, and the archive itself has gaps —
2020-10-20 is absent even for an unrelated broad query, so gaps are
query-independent. Resolution adopted: a sixth *coverage* series (the bare
market anchor in `timelinevolraw`, whose `norm` counts all monitored articles
that day) establishes archive availability. Absent-from-query but
present-in-coverage is a **confirmed zero**; absent from both is **missing**.

**Volume intensity is a share, not a count.** Verified arithmetically:
2020-01-01 gave 4,775 matching of 262,970 monitored = 1.8158%, exactly the
reported `timelinevol` value. Tone weights therefore must come from
`timelinevolraw`, never from `timelinevol` — different units.

**Query length ceiling.** GDELT rejects over-long queries with **HTTP 200** and
the body "Your query was too short or too long." Measured: 202 characters
accepted, 261 rejected. This is now asserted in code at a 220-character ceiling,
and every response must parse as JSON before it may enter the cache.

### 1.2 FINRA access

| Question | Answer, established by observation |
|---|---|
| Daily short volume beyond 365 days | CDN bulk files, `cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt`. No auth, no rate limit. |
| Must facility files be combined? | **No.** `CNMS` is already consolidated. `FNSQ`/`FNYX`/`FNRA`/`FORF` are not needed. |
| Daily file coverage | 2018-08-01 → present confirmed by probe: `20180801` returns 200, `20180731` returns 403. Non-trading days return 403, so 403 is a legitimate absence, not an error. |
| Short interest history | Query API `otcMarket/consolidatedShortInterest`, POST, no auth. **206 settlement dates, 2017-12-29 → 2026-07-15.** |
| Paging | `record-max-limit: 5000`, `record-offset`, `record-total` in response headers; `domainFilters` accepts the whole universe in one body. |
| Publication-date field? | **No.** Only `settlementDate`. |

Recorded because it contradicts the vendor's own documentation: the dataset
description says data is available "for one rolling year". That describes the
web UI. The API returned the full 2017-2026 history.

The sibling dataset `otcMarket/equityShortInterest` was inspected and rejected —
its rows are OTC / non-exchange issues, not the exchange-listed universe.

### 1.3 Publication-date branch taken

**Branch 2 — reconstructed from FINRA's published schedule.**

Branch 1 does not apply (no publication-date field). Branch 3 (approximation) is
not the primary rule.

FINRA publishes a *Short Interest Reporting Dates* table with explicit
Settlement Date, Due Date, and Publication Date columns. **197 settlement dates
covering 2018-10-31 to 2026-12-31** were recovered from the live page plus nine
archived snapshots of the same FINRA page. Overlapping snapshots were
cross-checked and **agree on every settlement date they share — zero conflicts.**

| Rule | Settlement dates | Period |
|---|---:|---|
| `finra_published_schedule` | 186 | 2018-10-31 onward |
| `settlement_plus_8_business_days` (fallback) | 20 | 2017-12-29 to 2018-10-15 |

The fallback covers the window where no retrievable page carried a 2018 table —
the pre-2019 FINRA site linked its schedule from a separate page that now
redirects.

**The fallback rule was measured rather than assumed.** The spec's stated
fallback is settlement + 8 plain business days. Across the 197 retrieved pairs
the actual gap is **7 business days excluding US federal holidays** in 186
cases (6 in four, 8 in seven). The derived rule is used, flagged distinctly in
`publication_date_rule`, and the 10-business-day sensitivity variant is carried
alongside. The column name retains the spec's label for traceability; the
implemented offset is the derived 7-federal-business-day rule.

---

## 2. Frozen queries and the sanity check

All five validate against the anchor, language, and hindsight constraints, which
are asserted in code and covered by tests.

| Key | Mechanism | Query (frozen) |
|---|---|---|
| `panic` | equity-market stress | `(selloff OR "sell-off" OR plunge OR rout OR turmoil OR panic OR slump) (stock OR stocks OR equity OR equities OR "stock market" OR "financial markets") sourcelang:english` |
| `rotation` | factor/style rotation, momentum unwind | `("factor rotation" OR "momentum stocks" OR "growth stocks" OR "value stocks" OR unwind) …anchor… sourcelang:english` |
| `policy` | central-bank surprise, rate repricing | `("central bank" OR "monetary policy" OR "interest rates" OR "rate hike" OR "rate cut") …anchor… sourcelang:english` |
| `crowding` | short squeeze, crowded-trade deleveraging | `("short squeeze" OR "short sellers" OR "crowded trade" OR deleveraging OR "margin call") …anchor… sourcelang:english` |
| `riskoff` | flight to safety | `("risk-off" OR "flight to safety" OR "safe haven" OR "safe-haven") …anchor… sourcelang:english` |

Plus a non-mechanism `coverage` series (bare anchor, `timelinevolraw` only) used
solely to establish archive availability.

### Queries that were changed, and why

Not a semantic narrowing from the sanity check — a **technical** correction
forced by the length ceiling, made before any panel existed.

| Key | Before (chars) | After (chars) | Terms dropped |
|---|---:|---:|---|
| `panic` | 202 | 170 | `plunged`, `tumble`, `tumbled` |
| `rotation` | **261 (rejected by API)** | 187 | `"style rotation"`, `"momentum trade"`, `"rotation out of"`, `unwinding` |
| `policy` | 219 | 186 | `"policy meeting"`, `inflation` |
| `crowding` | **263 (rejected by API)** | 188 | `"short interest"`, `"margin calls"`, `"forced selling"`, `"hedge funds"` |
| `riskoff` | 207 | 166 | `"flight to quality"`, `"haven assets"` |

No mechanism lost its defining vocabulary, and no anchor or language constraint
was weakened. Because nothing in this project is fitted against labels, a
descriptive query change carries no selection risk — only a documentation
obligation, discharged here and in `DECISIONS.md`.

### Semantic sanity check

**Not performed.** It requires 10 further `artlist` requests, and GDELT was
blocked. The runner exists (`src/data/gdelt_sanity.py`) and writes
`outputs/narrative_sanity_check.json` plus per-query precision flags.

**Consequence, stated plainly:** every query in the narrative panel would carry
`precision_flag = "unassessed"`. Nobody has yet checked that `unwind` inside a
market-anchored query returns market coverage rather than, say, spa and wellness
copy. The anchor makes gross off-target matching unlikely, but "unlikely" is not
"checked", and this check should be the first thing run when access returns.

---

## 3. Coverage summary

### 3.1 Positioning panel — `data/processed/positioning_panel.parquet`

2,402 rows, 2017-01-03 → 2026-07-24.

| Year | Trading days | `days_to_cover` | `days_to_cover_z` | `short_vol_share` | `short_vol_share_z` | Mean leg size | Mean match rate |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2017 | 251 | 0 | 0 | 0 | 0 | 18.0 | 0.00 |
| 2018 | 251 | 245 | 119 | 101 | 0 | 18.0 | 0.90 |
| 2019 | 252 | 252 | 252 | 252 | 227 | 18.0 | 0.96 |
| 2020 | 253 | 253 | 253 | 253 | 253 | 18.6 | 0.97 |
| 2021 | 252 | 252 | 252 | 252 | 252 | 19.0 | 0.99 |
| 2022 | 251 | 251 | 251 | 251 | 251 | 19.4 | 0.98 |
| 2023 | 250 | 250 | 250 | 250 | 250 | 20.0 | 1.00 |
| 2024 | 252 | 252 | 252 | 252 | 252 | 20.0 | 1.00 |
| 2025 | 250 | 250 | 250 | 250 | 250 | 20.0 | 1.00 |
| 2026 | 140 | 140 | 140 | 140 | 140 | 20.0 | 0.99 |

The 2017 blank is correct and is the point of the whole design: the first short
interest print settles 2017-12-29 and **publishes 2018-01-10**, so nothing is
visible before then. `short_vol_share` starts 2018-08-07 — the consolidated
daily files begin 2018-08-01 and the metric needs a 5-session window.

Distributions: `days_to_cover` median 2.59, range 1.31 to 4.88;
`short_vol_share` median 0.447, range 0.343 to 0.539. Roughly 45% of
off-exchange volume being short-marked is in the normal range for these files.
Neither series has a flat stretch — the longest run of identical values is 1 in
both. First-order autocorrelation is 0.990 and 0.976, appropriate for slow
crowding measures.

### 3.2 Narrative panel

Not built. Had it been, coverage would have been bounded by the 21 archive gaps
implied by the coverage probe (3,447 daily buckets over 3,468 calendar days).
See the self-review for why that number matters more than it looks.

---

## 4. Universe

**Definition:** the 200 largest US-domiciled, US-listed common stocks by market
capitalisation on 2026-07-24, per the Nasdaq stock screener, after excluding
non-common-stock instruments by name **and** requiring at least $5,000,000 of
traded notional on the snapshot date. Full list in `docs/universe.md`.

Price retrieval succeeded for **200 of 200**, so no expansion was needed.

### Survivorship flag — carried in every output built on this panel

The list is **current membership applied historically**, biased in both
directions: names that were large during the sample but were later acquired,
delisted, or shrank out of the top 200 are absent for the *entire* sample; names
that grew into the top 200 late are present from the start.

The screen is by market capitalisation, so the universe is large-cap dominated.
A real momentum loser decile contains far more mid- and small-cap names — which
are exactly where short-leg crowding is most acute. **The panel therefore
understates crowding relative to a true momentum universe.** It is a labelled
proxy, not a reconstruction. Production would use CRSP/Compustat point-in-time
constituents.

The panel carries `universe_survivorship_bias = True` on every row so a
downstream consumer cannot lose the caveat.

---

## 5. Match rates and unmatched tickers

| Source | Symbol-level match rate | Unmatched |
|---|---:|---|
| FINRA consolidated short interest | **200 / 200 (100%)** | none |
| FINRA CNMS daily short volume | **200 / 200 (100%)** | none |

Far above the 70% threshold that would have triggered a diagnostic iteration.
This required the per-source symbol normaliser: the three sources spell share
classes differently (`BRKB` / `BRK/B` / `BRK-B`), and `BRK-B` returns **zero**
rows from the short-interest dataset. Without normalisation every dual-class
name would have silently vanished.

**Date-level match rates are lower than symbol-level rates**, and this is
expected rather than a defect: 903 of 2,402 dates have at least one leg
constituent without FINRA data on that date, with a mean rate of 0.90 in 2018
rising to 1.00 from 2023. The causes are ticker changes (below) and names not
yet listed under their current symbol.

---

## 6. Availability calendar as actually built

| Source | Reference stamp (what the data is about) | Availability stamp (when it may be used) | Basis |
|---|---|---|---|
| FINRA short interest | `settlement_date` (metadata only) | `publication_date` | FINRA's published schedule; fallback flagged |
| FINRA daily short volume | `trade_date` | close of `trade_date` | FINRA posts no later than 6:00 p.m. ET that day |
| Price / volume | session date | close of session date | Phase 1 post-close assessment convention |
| GDELT bucket for calendar day *D* | calendar day *D* (UTC) | close of the next trading day after *D* | bucket completes 00:00 UTC on *D+1*, ≈19:00-20:00 ET on *D* |

All consistent with the Phase 1 contract: assessment after the US close on date
*t*, earliest action the next session.

A test asserts that for every populated row the settlement date is strictly
older than the publication date it was gated on, so settlement date cannot have
driven the join.

---

## 7. Limitations, stated plainly

Ordered by how much they should worry the reader.

1. **The narrative overlay does not exist.** Half the requested deliverable is
   missing. The cause is an API block, not a design failure, but the operator
   has one panel, not two, and no network access for a week.

2. **`days_to_cover` mechanically *falls* during crashes.** Volume is the
   denominator, and volume explodes in stress. Measured mean `days_to_cover_z`:
   **−2.23 in March 2020**, −1.73 in the August 2024 unwind, −1.72 in the April
   2020 rebound. Reading "low days-to-cover" as "low squeeze risk" during a
   volume spike is exactly backwards, and this panel will produce that reading
   at precisely the moments it matters most. This is a property of the standard
   metric, not a bug, but it is the single most dangerous thing to hand a PM
   without a warning label.

3. **The universe is large-cap only and survivorship-biased.** Section 4. The
   crowding level is understated relative to a real momentum book.

4. **The daily files are off-exchange only.** They cover trades reported to a
   TRF, the ADF, or the ORF for public dissemination, are not consolidated with
   exchange data, and do not reflect offsetting buys, which inflates apparent
   short concentration. FINRA states explicitly that they do not equate to short
   interest position data. `short_vol_share` is a **flow** measure;
   `days_to_cover` is a **position** measure.

5. **Ticker reuse contaminated three names before it was caught.** The price
   vendor back-fills a company's whole history under its *current* ticker, while
   FINRA uses the ticker in force on the trade date. `META` in FINRA data before
   mid-2022 is the **Roundhill Ball Metaverse ETF**; `BNY` before 2026 is
   **Blackrock New York Muni Trust**; `SPCX` before mid-2026 is **The SPAC and
   New Issue ETF**. Left alone this attached one company's short interest to
   another's prices for 111 leg-date rows, 61 of them in the January-April 2020
   window. Now guarded, with a detector that reports future candidates. Residual
   risk: the detector cannot itself distinguish a reused ticker from a genuine
   rename (GE → GE Aerospace, Raytheon Technologies → RTX share no name tokens
   either), so it reports for human reading rather than dropping automatically.
   A future universe change needs someone to read its output.

6. **20 of 206 settlement dates use the derived publication rule**, not FINRA's
   published table — the 2017-12-29 to 2018-10-15 window. The derived rule
   matches FINRA's own schedule exactly in 186 of 197 checkable cases, so the
   error is at most a day or two, but those rows are approximations and are
   flagged as such.

7. **`short_vol_share` has a mild secular drift** of about +0.006 per year
   against a series standard deviation of 0.036 — roughly one-sixth of a
   standard deviation annually, plausibly reflecting the rising off-exchange
   share of US volume rather than crowding. The 126-day rolling z-score absorbs
   drift on that timescale by construction, so the z-series is largely immune;
   the raw level series is not, and should not be compared across years.

8. **Momentum ranking uses total-return adjusted prices from a free vendor.**
   No vendor cross-check was performed. The reconciliation in section 8 gives
   indirect comfort on volume but says nothing about price accuracy.

9. **`CCZ` was in the universe until it was caught.** See the self-review. It is
   fixed, but it got as far as producing an 8.5-sigma reading.

10. **Exchange holidays are approximated by US federal holidays** in the
    publication-date fallback only. These calendars differ (Good Friday, Columbus
    Day, Veterans Day), which is visible as the 6/7/8-business-day spread in the
    measured rule.

---

## 8. Self-review

The instruction was to re-read my own outputs against the acceptance criteria
and be honest. Four defects were found this way and three were fixed.

### 8.1 Defects found by self-review

**(a) An 8.5-sigma reading that was entirely an artifact. Fixed.**
`days_to_cover_z` peaked at 8.53 on 2024-05-20. Decomposing the leg showed the
whole spike was one name: `CCZ`, Comcast Holdings ZONES — an exchangeable
debenture with a 20-day average volume of **5 shares** and a days-to-cover of
120 against a leg median near 2.9. One constituent in a 20-name equal-weighted
mean moved the average from 2.9 to 8.8.

The universe screen had admitted it on market capitalisation, and the
non-common-stock name filter missed it because "Comcast Holdings ZONES" contains
none of the excluded words. Fixed with a liquidity floor of $5M daily notional —
three orders of magnitude below the least liquid genuine constituent, which
trades $60M a day. Effects: `days_to_cover` max fell from 9.08 to 4.88, the
z-range tightened from [−3.33, 8.53] to [−2.90, 4.04], and agreement with
FINRA's own days-to-cover rose from 98.0% to **98.8%** within 2×.

*Had I not looked at the top-10 z-scores and decomposed them, this would have
shipped as the panel's most extreme "crowding signal".*

**(b) Ticker reuse silently mixing two companies. Fixed.** Limitation 5. Found by
reading FINRA's `issueName` across all 58 universe symbols whose issue name
changed, not by any automated check — the automated check came afterwards.

**(c) Wayback pages decoding to binary noise. Fixed.** The `id_` endpoint
replays the original captured bytes, several of which were gzip-compressed.
Without decompression the 2022 and 2024 schedules parsed to **zero rows with no
error at all** — the failure was completely silent, and I only caught it because
the per-year row counts looked wrong. A second bug let stray prose dates group
into triplets with 150-day publication lags. Both fixed; the parser now bounds
the settlement-to-publication gap.

**(d) A cache key that ignored the request body. Fixed.** The short-interest
cache path did not include the requested symbol set, so changing the universe
would silently reuse the previous universe's cached pages. Now keyed on a hash
of the symbol list.

### 8.2 Series plausibility

- **No flat stretches.** Longest run of identical values is 1 for both metrics.
- **No impossible ranges.** `short_vol_share` sits in [0.343, 0.539], within
  what FINRA's off-exchange files produce. `days_to_cover` sits in [1.31, 4.88].
- **z-scores exceed 1 regularly** in both directions; neither series is inert.
- **No chunk seams exist** in the positioning panel by construction.
- **The step function is correct.** Verified directly: every change in AAPL's
  short interest lands *exactly* on a publication date, never between them.
- **The split un-adjustment is validated.** Apple's 2020-08-28 as-traded close
  recovers to $499.23 and volume to 46,907,500 — the real pre-split figures.
  Across 403,853 observations my 20-day ADV sits at a median ratio of **0.974**
  to FINRA's own average daily volume with **98.8% within 2×**. The
  counterfactual using split-adjusted volume achieves only 89.2%, so the
  un-adjustment removed a real error affecting the 48 universe names that split.

### 8.3 Coverage that is worse in some years

Yes, and the pattern is explicable rather than suspicious. 2017 is empty because
no short-interest print had published. 2018 is partial because `short_vol_share`
only begins in August and its z-score needs a further 126 sessions. Date-level
match rates rise from 0.90 in 2018 to 1.00 from 2023 as ticker-change effects
wash out. None of this suggests a data problem.

### 8.4 Do the two metrics move together?

**No, and I am reporting that as a finding rather than resolving it.**
Correlation of `days_to_cover_z` with `short_vol_share_z` is **0.051** in levels
and 0.061 in changes. Annual correlations range from −0.15 to +0.27 with no
stable sign.

Is that signal or a join error? The evidence says **not a join error**:

- Both have 100% symbol-level match rates and near-identical date-level rates.
- `days_to_cover` reconciles to FINRA's own figure at a median ratio of 0.974.
- The publication-date step function is verified exact.
- They genuinely measure different things — a position stock versus an
  off-exchange flow — and FINRA states outright that the daily files do not
  equate to short interest data.

So near-orthogonality is defensible. But I want to be clear that "defensible"
is weaker than "verified": I have ruled out the mechanical explanations I could
test, not established that the divergence is economically meaningful.

### 8.5 Things I approximated, and how much I think it matters

| Approximation | Assessment |
|---|---|
| 20 settlement dates on the derived publication rule | **Low.** Matches FINRA's own schedule in 186/197 checkable cases; affects early 2018 only, mostly before the z-scores begin. |
| Federal holidays standing in for exchange holidays in the fallback | **Low.** Only touches those same 20 dates. |
| Current-membership universe | **High**, and irreducible without CRSP/Compustat. Section 4. |
| Off-exchange volume as a shorting-flow proxy | **Medium.** Inherent to the source; documented, not fixable. |
| FINRA ADV excludes non-media trades, so the reconciliation is approximate | **Low.** A median ratio of 0.974 is about as close as this comparison can get. |

### 8.6 Things I would want a second pair of eyes on

1. **The `days_to_cover` sign behaviour in crashes** (limitation 2). I believe
   this is correct metric behaviour, but if the downstream evidence layer treats
   a high z-score as "crowded", it will systematically read the March-2020 type
   episode as *un*crowded. Someone should decide deliberately whether the panel
   should carry a volume-neutral variant alongside.

2. **Whether near-zero correlation between the two metrics is acceptable**
   (8.4). I have argued it is expected. I have not proved it.

3. ~~**The 126-row normalisation rule's interaction with archive gaps.**~~
   **RESOLVED, and my reasoning here was wrong.** I argued the rule could remove
   nearly all narrative z-scores because the 21 archive gaps might be spread
   evenly. Measured on the real panel, the gaps are **clustered into four
   events** — 17 consecutive days in June-July 2025, two in December 2017, and
   two isolated single days. The strict rule yields 1,739 z-scores against the
   relaxed rule's 2,269: a real gain of 530 (+30%), but nothing like the rescue
   I implied, and the strict rule would have been perfectly usable. The panel
   ships with the relaxed rule (100 of 126) recorded in `z_min_observations`;
   the positioning panel keeps the strict rule. Full detail in
   `outputs/narrative_poc_review.md`.

4. **The 12-2 formation window.** I implemented the spec's literal wording —
   month end *m*−12 to month end *m*−2, a 10-month window skipping two months.
   The more common convention is an 11-month window skipping one. It is PIT-safe
   either way and the choice is documented, but it is not the textbook default
   and someone should confirm it is intended.

5. **The unassessed query precision flags** (section 2). Nobody has looked at a
   single headline these queries return.

---

## 9. Acceptance criteria

| # | Criterion | Status |
|---|---|---|
| 1 | Both panels exist, or `BLOCKERS.md` explains why not | **Partial.** Positioning complete; narrative blocked with a full write-up. |
| 2 | All 4.1 tests pass, or failures documented | **Pass.** 96 passed, 2 skipped (both skips are narrative-panel tests, skipped only because the panel does not exist). |
| 3 | Every network artifact cached; second run makes zero network calls | **Pass**, asserted by test with the network hard-disabled. |
| 4 | Publication-date branch recorded; PIT assertion passes | **Pass.** Branch 2, recorded per row; assertion passes against the built panel. |
| 5 | Limitations stated honestly, including approximations | **Pass.** Section 7 and 8.5. |
| 6 | No abandoned-architecture component built | **Pass.** No model, folds, freeze manifest, or bootstrap. |
| 7 | Self-review performed and written down | **Pass.** Section 8, including four defects it caught and five open questions. |

## 10. Artifacts

| Path | Contents |
|---|---|
| `data/processed/positioning_panel.parquet` | the positioning panel |
| `data/processed/loser_leg_membership.parquet` | leg membership history |
| `data/processed/finra_short_interest.parquet` | short interest, all universe symbols |
| `data/processed/finra_daily_universe.parquet` | daily short volume, universe extract |
| `data/processed/finra_publication_schedule.parquet` | settlement → publication map |
| `data/processed/universe_prices.parquet` | prices, both adjustment conventions |
| `outputs/positioning_panel_diagnostics.json` | match rates, reconciliation, identity guard |
| `outputs/positioning_unmatched_symbols.json` | unmatched-ticker diagnostic (both empty) |
| `docs/universe.md` | universe definition and survivorship warning |
| `outputs/build_log.md` | running trail |
| `BLOCKERS.md` | the GDELT block |
