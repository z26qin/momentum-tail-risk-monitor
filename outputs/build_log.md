# Alt-data build log

Running trail for the alternative-data session (structured positioning overlay +
unstructured narrative overlay). Entries are append-only and dated in UTC.

Session start: 2026-07-24. Working tree:
`.claude/worktrees/remote-control-f6040f`, branch `dear/remote-control-f6040f`.

Architecture note carried into this session: there is no fitted model. No
baseline ladder, no walk-forward folds, no freeze manifest, no bootstrap
intervals are built here. `docs/DECISIONS.md` Phase 1 entries describe an
abandoned architecture and were read as history only.

---

## Stage 0 — Environment

- No `uv` and no `.venv` were present in the worktree. Installed `uv 0.11.32`
  and ran `uv sync --locked --extra test`, which resolved the existing
  `uv.lock` without modification: Python 3.12.13, pandas 3.0.2, pyarrow 25.0.0,
  numpy 2.4.4, pytest 9.0.3.
- **Decision:** add no new third-party dependencies. All HTTP uses stdlib
  `urllib.request`, so `uv.lock` stays byte-identical and `uv sync --locked`
  keeps working for the operator. This rules out `yfinance`; prices are pulled
  from public CSV/JSON endpoints directly and cached.
- The system interpreter (3.9.6 / pandas 2.2.3) is not used.

---

## Stage 1 — Probes

### 1.1 GDELT schema and frequency probe

Probe query (deliberately generic, not one of the frozen five):
`(stock OR stocks OR equity OR equities OR "financial markets") sourcelang:english`

Pulled one normal year (2017) and one leap year (2020) across `timelinevol`,
`timelinetone`, `timelinevolraw`, `format=json`, `timelinesmooth=0`.
Raw JSON cached under the scratchpad first, then promoted into
`data/raw/gdelt/` by the real pipeline.

Observed:

| Assertion | Result |
|---|---|
| 1. Every observation is exactly one UTC calendar date | **Holds.** Every `date` is `YYYYMMDDT000000Z`; zero non-midnight stamps in 730 observations. |
| 2. All three modes return identical date grids | **Holds for 2020** (366/366/366, set-identical). See caveat below. |
| 3. No smoothing | **Holds.** `timelinesmooth=0` accepted; `query_details.date_resolution` is `"day"`. |
| 4. No adaptive multi-day bins | **Holds.** Observed day-gaps are only 1.0 and 2.0 days; a 2.0 gap is an *absent* day, not a widened bin — the surrounding bins remain daily and `date_resolution` stays `"day"`. |
| 5. Every requested date is present or unambiguously missing | **Qualified — see below.** |

Assertion 5 needed real work, so it is written up in full:

- GDELT does not emit a row for every requested calendar day. The 2020 pull
  returned 366 of 367 requested days; **2020-10-20 is absent entirely**. The
  2017 pull returned 364 of 366.
- An absent day is therefore ambiguous on its face between *the archive has no
  data* and *this query matched nothing*. Resolving that ambiguity is required
  by the spec's rule that `vol_intensity` may be zero only on a confirmed zero
  match, and that tone must be NaN (never 0) on a zero-match interval.
- **Resolution adopted:** pull a sixth *coverage* series — the bare market
  anchor group in `timelinevolraw` — over the same range. `timelinevolraw`
  carries `norm`, the count of all monitored articles that day, which is
  query-independent. A day present in the coverage series establishes that the
  GDELT archive covers that date; a day absent from a mechanism query but
  present in coverage is a **confirmed zero**; a day absent from both is
  **missing** and stays NaN. This is logged as `gdelt_archive_available` in the
  panel.
- `timelinevol.value` was verified to be `100 * value / norm` from
  `timelinevolraw` (2020-01-01: 4775/262970 = 1.8158%, matching the reported
  1.8158). This confirms `timelinevol` is a share-of-monitored-volume
  intensity, not a count, and that raw-count weighting for tone must come from
  `timelinevolraw.value` rather than from `timelinevol`.

Branch taken on the decision tree: **no adaptive bins, no persistent API
failure — Stage 2 proceeds.** The one blocking condition in this session was
not triggered.

Surprise worth recording: the API rate-limits hard. Roughly every other request
returned HTTP 429 at a 5–6 second spacing. Acquisition uses ≥12 s spacing with
exponential backoff to 5 retries.

### 1.2 FINRA access probe

Everything below was established by observation against the live endpoints, not
assumed.

**Daily short sale volume.** Retrieval path is the CDN bulk file, not the Query
API:
`https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt`

- Pipe-delimited, header `Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market`.
- No authentication, no rate limit encountered.
- `CNMS` is the **already-consolidated** NMS file, so the separate reporting
  facility files (`FNSQ`, `FNYX`, `FNRA`, `FORF`) do **not** need to be
  combined. This resolves the open question in the probe spec.
- Coverage confirmed by observation: `20180801` → HTTP 200 (249,497 bytes),
  `20180731` → HTTP 403. The 2018-08-01 consolidated start is real, not folklore.
  `20260722` → HTTP 200. Non-trading days (e.g. `20240101`) → HTTP 403, so 403
  is the normal "no session" response and must not be treated as an error.
- The Query API alternative (`otcMarket/regShoDaily`) exposes the same data but
  split by `reportingFacilityCode`, i.e. it would require the combination step
  the CDN file already did. Rejected in favour of the CDN files.

**Equity short interest.** Retrieval path is the FINRA Query API dataset
`otcMarket/consolidatedShortInterest` (POST, JSON body, no authentication).

- Fields (from `https://api.finra.org/metadata/group/otcMarket/name/consolidatedShortInterest`):
  `accountingYearMonthNumber`, `symbolCode`, `issueName`,
  `issuerServicesGroupExchangeCode`, `marketClassCode`,
  `currentShortPositionQuantity`, `previousShortPositionQuantity`,
  `stockSplitFlag`, `averageDailyVolumeQuantity`, `daysToCoverQuantity`,
  `revisionFlag`, `changePercent`, `changePreviousNumber`, `settlementDate`.
- Paging: `record-max-limit: 5000`, `record-offset`, `record-total` returned as
  response headers. `domainFilters` accepts multiple `symbolCode` values in one
  request, so the whole universe can be pulled in a handful of paged calls.
- **Coverage established by observation:** 206 settlement dates,
  **2017-12-29 through 2026-07-15**, and every symbol tested returned exactly
  206 rows (AAPL, MSFT, XOM, TSLA, GME) — no missing prints. The dataset
  description claims "one rolling year"; that describes the web UI, not the
  API. Recorded because it contradicts the vendor's own documentation.
- The dataset carries `averageDailyVolumeQuantity` and `daysToCoverQuantity`,
  so FINRA's own days-to-cover is available for the reconciliation the spec
  asks for.
- The sibling dataset `otcMarket/equityShortInterest` was inspected and
  rejected: its rows are OTC / non-exchange issues
  (`marketCategoryDescription: "Other OTC"`), not the exchange-listed universe.

**Publication date — decision-tree branch.**

- Branch 1 (explicit publication-date field) does **not** apply. The dataset has
  `settlementDate` only. Joining on it would embed roughly two weeks of
  look-ahead.
- Branch 2 **applies and is the branch taken.** FINRA publishes an explicit
  *Short Interest Reporting Dates* table with three columns — Settlement Date,
  Due Date, Publication Date — at
  `https://www.finra.org/filing-reporting/regulatory-filing-systems/short-interest`.
  The live page carries the 2026 schedule in full and the tail of 2025.
  Historical years are recovered from archived snapshots of the same FINRA page
  (see the acquisition entry below). Publication dates are therefore
  **reconstructed from FINRA's published schedule**, not approximated.
- Branch 3 (settlement + 8 business days) is **not** the primary rule. It is
  retained only as a fallback for any settlement date not covered by a
  retrieved schedule, and every row records which rule produced its
  publication date.

**Symbology — a mechanical mismatch found early.** The two FINRA sources do not
agree with each other, and neither agrees with the price vendor:

| Security | Short interest API | CNMS daily file | Price vendor |
|---|---|---|---|
| Berkshire Hathaway B | `BRKB` | `BRK/B` | `BRK-B` |
| Brown-Forman B | `BFB` | `BF/B` | `BF-B` |
| Lennar B | `LENB` | `LEN/B` | `LEN-B` |

Verified by direct query: `BRKB` → 206 rows, `BRK/B` → 0 rows, `BRK-B` → 0 rows
against the short-interest dataset; `BF/B` and `BF/A` present in the CNMS file.
A per-source symbol normaliser is therefore mandatory rather than optional, and
this is exactly the failure mode the spec flagged. Handled in Stage 3.

---

## Stage 2 — Narrative panel

### Acquisition: three surprises, in the order they appeared

**1. GDELT applies a stateful IP penalty, not a simple rate limit.** The 429
body reads "Please limit requests to one every 5 seconds", but requests spaced
20 seconds apart were still refused. The penalty is sticky: once tripped,
continued requests — including polite retries — keep it tripped. The first
acquisition driver made this worse by retrying with exponential backoff inside
each request, which is exactly the wrong response.

The working approach is the opposite of retrying: **go completely quiet**. A
poller now waits for a clean probe before doing any work and treats every 429 as
a signal to stop all traffic for five minutes rather than to retry sooner. The
penalty cleared after a single five-minute silence the first time it was
applied properly.

**2. GDELT rejects over-long queries with HTTP 200.** The body reads "Your query
was too short or too long." Because the status is 200, the first driver cached
that sentence as if it were a timeline and then crashed parsing it — and worse,
a cached poison pill would have survived every later run. Two fixes: every
timeline response must now parse as JSON before it is allowed into the cache,
and `validate_queries` asserts a 220-character ceiling measured against the live
API (202 accepted, 261 rejected). The `rotation` and `crowding` queries were
over the ceiling and were trimmed; the change is logged in `DECISIONS.md`
with the exact terms dropped.

**3. A single full-range request keeps daily resolution.** Verified directly:
2017-01-01 to 2026-06-30 in one request returns 3,447 daily buckets with
`date_resolution: "day"`. This removes chunk seams entirely and cuts request
volume from ~160 to 16 against an API that is the binding constraint. Year
chunking and its seam assertions remain implemented and tested as the fallback
path.

3,447 buckets against 3,468 calendar days implies **21 days the GDELT archive
does not cover** across the sample.

### A consequence of the specified normalisation rule that the operator must see

The spec requires the 126-row window to be the *immediately preceding* 126
trading-date rows, available only when all 126 are finite, with no backward
search. Combined with the rule that an archive gap makes its whole interval
unavailable, **one missing GDELT day removes the next 126 trading days of
z-scores.**

A synthetic end-to-end run with two planted archive gaps confirmed the
arithmetic exactly: 2,385 trading rows, 2,382 intervals available, but only
2,004 z-scores — 126 lost to the initial warm-up and 126 lost after each gap.

With 21 real archive gaps this is potentially severe, and the exact cost is
measured against the real panel in `data_review.md` rather than estimated here.
The rule is implemented **as specified** and not quietly relaxed; the honest
reporting of what it costs is the deliverable.

---

## Stage 3 — Positioning panel

### Universe

200 names, defined as the largest US-domiciled US-listed common stocks by market
capitalisation on the retrieval date (Nasdaq stock screener), written to
`docs/universe.md` with its survivorship warning. Price retrieval succeeded for
**200 of 200** symbols, so no universe expansion was needed.

### Trading calendar

Built from the Ken French momentum calendar already frozen in the repository,
extended past its 2026-05-29 vintage by 38 observed exchange sessions from the
price panel. The two sources were checked against each other over **2,616
overlapping trading days and disagree on none.** That is a stronger validation
than either source alone and it is why the calendar is not simply assumed.

### The volume-adjustment trap, and evidence that it was real

`days_to_cover` divides a FINRA share count by an average daily volume. The
price vendor returns split-*adjusted* volume, so for any name that split, the
naive computation understates days-to-cover by the split factor — silently, and
only for those names. 48 of the 200 universe names split during the sample.

The pipeline un-adjusts volume to as-traded shares using the vendor's own split
events. Spot check: Apple's 2020-08-28 close recovers to $499.23 and its volume
to 46,907,500 shares, both matching the actual pre-split figures.

Reconciled against FINRA's own `averageDailyVolumeQuantity` across 38,502
settlement-date observations:

| Volume basis | Median ratio to FINRA's ADV | Share within 2x |
|---|---:|---:|
| As-traded (used) | 1.023 | **99.2%** |
| Split-adjusted (counterfactual) | 1.049 | 89.2% |

The medians are similar because most names never split; the tail is where the
error lived, and the un-adjustment removes it. FINRA's ADV excludes non-media
trades, so exact agreement was never expected — a median ratio of 1.02 is about
as close as this comparison can get.

### Match rates

- Short interest: **200 of 200** universe symbols matched (39,109 rows across
  206 settlement dates). The per-source symbol normaliser was required to get
  here; without it every dual-class name would have matched zero rows.
- The match rate is far above the 70% threshold that would have triggered a
  diagnostic iteration.

### Publication schedule

197 settlement dates recovered from the live FINRA page plus nine archived
snapshots, covering 2018-10-31 to 2026-12-31, with **zero conflicts** between
overlapping snapshots.

One parsing failure is worth recording because it failed *silently*: the Wayback
`id_` endpoint replays the original captured bytes, and several FINRA snapshots
were captured gzip-compressed. Without decompression the page decoded to binary
noise and the schedule parsed to zero rows — which is how the 2022 and 2024
schedules first went missing without any error. A second bug let stray prose
dates group into plausible-looking triplets with 150-day publication lags; both
are fixed and the triplet parser now bounds the settlement-to-publication gap.

Uncovered: the 20 settlement dates from 2017-12-29 to 2018-10-15, because the
pre-2019 FINRA site linked its schedule from a separate page that now redirects.
Those rows use the derived fallback and are flagged distinctly.

---

## Stage 4 — Tests, self-review, and close-out

### Test suite

96 passed, 2 skipped. The two skips are the narrative-panel assertions, skipped
only because the panel does not exist; they are not failures and will run as
soon as the GDELT cache is populated.

Coverage against the required list:

| Required test | Where | Status |
|---|---|---|
| Mapping worked examples; day-*t* bucket excluded | `test_narrative_mapping.py` | pass (Tuesday, Monday, post-holiday, plus a parametrised assertion that no trading date is ever in its own information set) |
| Tone NaN when a raw count is unavailable; mixed units impossible | `test_narrative_mapping.py` | pass (includes an explicit assertion that the intensity-weighted answer differs) |
| Tone NaN on a zero-match interval | `test_narrative_mapping.py` | pass (volume 0, tone NaN, in the same assertion) |
| Rolling z is PIT — three assertions | `test_pit_normalisation.py` | pass |
| Normalisation NaN when any of 126 preceding rows is non-finite; no backward search | `test_pit_normalisation.py` | pass (checks all 126 offsets, then that row 127 recovers) |
| `narrative_breadth` NaN when any constituent is missing | `test_narrative_mapping.py` | pass |
| No positioning observation visible before its publication date | `test_positioning_pit.py` | pass, against the built panel and at per-symbol granularity |
| Chunk stitching: no gaps or overlaps | `test_gdelt_acquisition.py` | pass, including a deliberate-overlap negative case |
| Cache determinism: zero network calls, identical outputs | `test_cache_determinism.py` | pass with the network hard-disabled |

### Self-review found four defects; three were fixed on the spot

1. **`CCZ` produced an 8.5-sigma artifact.** Comcast Holdings ZONES, an
   exchangeable debenture trading 5 shares a day, entered the universe on market
   cap and single-handedly moved the leg's equal-weighted days-to-cover from 2.9
   to 8.8. Fixed with a $5M daily-notional floor. This was found by decomposing
   the top-10 z-scores — not by any test — and would otherwise have shipped as
   the panel's headline crowding signal.
2. **Ticker reuse mixed two companies.** `META` before mid-2022 is the Roundhill
   Ball Metaverse ETF in FINRA data; `BNY` before 2026 is a Blackrock muni
   trust; `SPCX` before mid-2026 is a SPAC ETF. 111 leg-date rows affected, 61 of
   them in the Jan–Apr 2020 window. Fixed with an observation-derived guard plus
   a detector for future cases.
3. **Wayback pages decoded to binary noise**, silently zeroing the 2022 and 2024
   schedules. Fixed.
4. **The short-interest cache key ignored the request body**, so a universe
   change would have reused stale pages. Fixed.

The fourth item was found while changing the universe for item 1 — a good
argument for the build → verify → fix loop, since fixing one defect exposed
another.

### What the self-review could not resolve

Written up in `data_review.md` §8.6. Briefly: the sign behaviour of
`days_to_cover` during volume spikes, whether the near-zero correlation between
the two crowding metrics is economically meaningful, whether the specified
126-row normalisation rule is viable against a source with 21 archive gaps, and
the fact that no query's precision has actually been eyeballed.

### Final state

- **Positioning panel: delivered.**
- **Narrative panel: blocked**, `BLOCKERS.md` B1. The GDELT poller was still
  running at close and will populate the cache automatically if the block lifts.
- Nothing from the abandoned architecture was built.
- Files are on disk and **not committed** — no commit was requested.
