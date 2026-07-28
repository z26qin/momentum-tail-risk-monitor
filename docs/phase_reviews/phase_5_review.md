# Phase 5 review: universe fundamental momentum and portfolio alignment

Date: 2026-07-28

Status: revised feasibility plan, awaiting implementation approval

No Phase 5 production code or production data was edited during this review
gate.

## Revised objective

Phase 5 is a **Universe-Level Fundamental Momentum and Portfolio Alignment
Monitor**.

It must not calculate fundamentals only for the selected price-momentum long
and short names. The independent stock-level fundamental panel is built first,
across every covered eligible security, and only then mapped onto the
price-selected portfolio.

The required sequence at each rebalance is:

1. resolve the eligible S&P 500 membership and its data-quality status;
2. calculate 12-1 price momentum across the eligible universe;
3. independently calculate sector- or industry-relative fundamental momentum
   across all covered eligible stocks;
4. measure universe-level price-versus-fundamental alignment;
5. map the independent fundamental rank onto the selected top-10 and
   bottom-10 price-momentum legs;
6. calculate portfolio alignment diagnostics and deterministic flags.

The former forward-return IC/IR framework and static quality factor library
remain out of scope.

## Why current SEC coverage is 11/503

The observed 11/503 is not evidence that only 11 S&P 500 companies publish
usable SEC filings. It is a consequence of the existing acquisition route.

`src/data/sec_edgar.py` was built for shares outstanding, not fundamental
statements:

1. its existing CLI requested only the 200-symbol positioning universe;
2. it first queried the narrow
   `EntityCommonStockSharesOutstanding` company-concept endpoint;
3. it downloaded the broad Company Facts payload only when that narrow shares
   endpoint returned 404;
4. only 14 symbols followed that fallback path;
5. two fallback payloads, HONA and SPCX, contain no US-GAAP facts;
6. one usable payload, NET, is no longer in the current 503-security universe;
7. GOOG and GOOGL are two securities mapped to the same issuer and CIK.

Therefore the current cache contains usable Company Facts for 11 current
securities representing 10 issuers. The other 492 securities were mostly
**never queried through the Company Facts endpoint**.

The existing shares acquisition supports this diagnosis:

- 200 symbols were requested;
- 198 produced shares data;
- 186 narrow company-concept payloads were cached;
- 14 narrow concept requests returned 404 and invoked Company Facts;
- the acquisition completed without an unmapped ticker or early stop.

## Ticker-to-CIK and download diagnosis

The cached SEC ticker map contains 10,429 ticker records. After the repository's
dot-to-hyphen normalization and existing XOM override:

- current universe symbols: 503;
- ticker-to-CIK mappings found: 503;
- unmapped current symbols: 0.

Ticker mapping is therefore not the cause of 11/503 coverage.

The root download issue is route selection: Company Facts was a conditional
fallback for a shares-outstanding task, not an independently requested
fundamental source.

The environment currently has no `SEC_CONTACT_EMAIL`. SEC fair-access rules
require a real operator contact before the approximately 503 cache-first
Company Facts requests can be made. The implementation must not bypass this
requirement or embed a placeholder address.

## Current cached coverage breakdown

The following counts are for the current 503-security universe as of the
2026-06-30 portfolio rebalance. They diagnose the cache; they are not an
estimate of full-universe filing availability.

| Coverage stage | Securities | Notes |
|---|---:|---|
| Eligible 12-1 price-momentum universe | 500 | FDXF, HONA, and Q lack sufficient current signal history |
| Cached Company Facts payload | 12 | Includes HONA, whose payload has no US-GAAP facts |
| Usable US-GAAP filing facts | 11 | Ten issuers because GOOG/GOOGL share one CIK |
| Revenue tag data | 11 | All 11 usable securities |
| EPS tag data | 10 | ABNB lacks the selected EPS tags |
| Operating-income tag data | 10 | HOOD lacks `OperatingIncomeLoss` |
| Current revenue-acceleration signal | 11 | Using strict PIT quarterly continuity |
| Computable EPS acceleration before staleness gate | 2 | CVNA and DELL only; both are more than 180 days stale |
| Current EPS acceleration after staleness gate | 0 | Direct fourth-quarter EPS continuity is the main failure |
| Current operating-margin-change signal | 10 | Revenue and operating income both required |
| At least two of three current signals | 10 | HOOD has only revenue acceleration |
| Two-of-three coverage in eligible price universe | 10/500, or 2.0% | Far below the 60% gate because acquisition is incomplete |
| Latest long-leg coverage | 0/10 | No long symbol has a cached Company Facts payload |
| Latest short-leg coverage | 0/10 | No short symbol has a cached Company Facts payload |

The latest long-leg names are SNDK, LITE, WDC, MU, CIEN, STX, INTC, ECHO, TER,
and COHR. The latest short-leg names are ZTS, GDDY, PODD, BSX, INTU, IT, CSGP,
CHTR, FISV, and TTD. Their 0/20 coverage occurs because none followed the old
shares-endpoint fallback path. It is not a conclusion that they lack filings.

Current two-of-three cache coverage is concentrated in Technology:

| Current sector | Eligible | Two-of-three covered |
|---|---:|---:|
| Technology | 76 | 8 |
| Consumer Discretionary | 103 | 2 |
| All other classified sectors | 321 | 0 |
| Missing current sector | 3 | 0 |

This distribution is an acquisition artifact and cannot support
cross-sectional normalization.

## Taxonomy and period-handling diagnosis

### Taxonomy-tag variation

The cached sample confirms that a single tag is insufficient:

- revenue appears under
  `RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`, and
  `SalesRevenueNet`;
- EPS appears under `EarningsPerShareDiluted`,
  `EarningsPerShareBasicAndDiluted`, and `EarningsPerShareBasic`;
- operating income is usually `OperatingIncomeLoss`, but is absent for HOOD.

Selecting the tag with the longest history can select a stale legacy tag.
The correct as-of rule is:

1. evaluate each approved economically equivalent tag independently;
2. require one tag to cover the entire comparison window;
3. prefer the candidate with the most recent valid fiscal quarter;
4. use fixed economic priority only to break an equal-recency tie;
5. expose the chosen tag and never silently splice concepts.

Full-universe acquisition must produce a sector-by-sector tag coverage audit.
Banks, insurers, and REITs are the main risk because generic revenue and
operating-margin concepts may be absent or economically misleading.

### Quarterly and annual facts

For additive flow measures, direct quarterly facts are preferred. Fourth
quarter revenue and operating income may be derived as:

```text
fourth-quarter value = fiscal-year value - first-nine-month value
```

This is permitted only when fiscal-year identity, tag, unit, start date, and
filing availability all reconcile. The result remains labeled `derived_q4`.

EPS is not additive because annual and nine-month EPS can use different
weighted-average share counts. Annual EPS minus nine-month EPS is therefore
prohibited. Missing direct fourth-quarter EPS explains much of the current
EPS-acceleration loss.

### Fiscal-period alignment

SEC `fy` and `fp` fields cannot be used alone. Comparative observations
included in a later filing can carry the later filing's fiscal labels. The
parser must use:

- period start and end dates;
- duration;
- form and accession;
- filing and conservative availability dates;
- approximately one-quarter and one-year spacing checks.

Non-calendar and 52/53-week fiscal years must be aligned by fiscal sequence,
not forced into calendar quarters.

### Filing-date filtering

Company Facts supplies a filing date but not a reliable market-time timestamp.
The conservative availability convention is:

```text
available_date = first trading day after filed_date
```

At rebalance `t`, only facts with `available_date <= t` are eligible. A later
amendment or restatement may alter results only from its own availability date
forward.

The parser must also impose a staleness limit. A component whose latest fiscal
period end is more than 180 calendar days before the rebalance is unavailable.
This prevents an old computable EPS sequence, such as the cached CVNA sequence,
from being treated as current support.

## Data feasibility conclusion

Full-universe feasibility is promising but not yet proven:

- ticker-to-CIK mapping is 503/503;
- the existing SEC cache and request controls are reusable;
- the cached filings demonstrate that revenue acceleration and margin change
  can be constructed with PIT filing dates;
- current 11/503 is primarily a missing acquisition route, not a filing
  failure.

However, the project cannot claim 60% or 80% signal coverage until all current
eligible CIKs have been cache-fetched and parsed. Taxonomy variation,
financial-sector accounting, direct quarterly EPS availability, and fiscal
alignment are the real feasibility risks.

The recommended next approved action is therefore a bounded **Phase 5A data
feasibility acquisition**, not production monitor implementation:

1. fetch Company Facts once per distinct eligible CIK;
2. preserve cache hashes and retrieval timestamps;
3. run the seven-stage coverage audit by rebalance and sector;
4. inspect unmapped tags and period failures;
5. approve the final signal map only after observed coverage is known.

Production monitor work should proceed only after this audit shows at least
60% universe coverage or identifies a small, economically defensible tag
adjustment that reaches it. The design target is at least 80%.

## Eligible universe and known membership limitation

At rebalance `t`, the intended eligible universe is:

```text
S&P 500 members effective at t
intersect securities with sufficient PIT price history for 12-1 momentum
```

Missing fundamentals do not remove a security from the eligible denominator.
They reduce the covered count.

The repository currently has one dated current-membership snapshot, not
historical S&P 500 membership intervals. Phase 5 will accept an
effective-from/effective-to membership table when available, but the MVP
history must retain:

```text
membership_status = current_snapshot_proxy
survivorship_bias = true
```

It must not describe the historical 2017–2026 universe as genuinely
point-in-time. This limitation is independent of SEC filing-date discipline.
In particular, the latest stored membership snapshot is dated 2026-07-24,
after the 2026-06-30 formation date, so the current latest portfolio remains a
labeled membership proxy rather than a PIT constituent set.

## Stock-level panel and formulas

The primary Phase 5 artifact is one row per rebalance and eligible stock. It is
built before the portfolio mapping.

### Price momentum

```text
price_momentum = total_return_price[m-1] / total_return_price[m-12] - 1
```

Formation month `m` is skipped, consistent with Phase 2. Rank 1 is the
strongest price momentum across the eligible universe. The panel retains the
raw score, raw rank, percentile rank, signal dates, and eligibility status.

### Revenue-growth acceleration

```text
revenue_yoy_t = revenue_t / revenue_t-4 - 1
revenue_acceleration_t = revenue_yoy_t - revenue_yoy_t-1
```

Revenue must be positive in every comparison period.

### EPS-growth acceleration

EPS can cross zero, so use bounded symmetric growth:

```text
symmetric_growth(x, y) = 2 * (x - y) / (abs(x) + abs(y))

eps_acceleration_t =
    symmetric_growth(eps_t, eps_t-4)
    - symmetric_growth(eps_t-1, eps_t-5)
```

The comparison is missing when both values in either pair are zero.

### Operating-margin change

```text
operating_margin_t = operating_income_t / revenue_t
operating_margin_change_t =
    operating_margin_t - operating_margin_t-4
```

The year-over-year comparison reduces seasonality.

### Relative normalization

Each signal is normalized independently:

1. use industry-relative percentile rank when the industry has at least 10
   valid companies for that signal;
2. otherwise fall back to sector-relative percentile rank;
3. require at least five valid sector peers;
4. map the average-rank percentile to `[-1, +1]`;
5. preserve equal raw values as ties;
6. leave the signal missing if neither peer group is adequate.

Current Nasdaq data contain industry labels for 500/503 securities across 112
industries, but these labels are also a current, non-PIT snapshot.
Normalization provenance must say `industry_current_snapshot_proxy` or
`sector_current_snapshot_proxy`.

### Composite fundamental momentum

```text
fundamental_momentum_score =
    mean(valid relative revenue acceleration,
         valid relative EPS acceleration,
         valid relative operating-margin change)
```

At least two signals are required. Rank 1 is the strongest composite score
across all covered eligible stocks. The score and rank are independent of
whether a stock is selected by price momentum.

The stock panel retains:

- rebalance date, symbol, CIK, sector, and industry;
- universe eligibility and membership quality;
- price score, rank, and rank percentile;
- three raw fundamental components;
- three relative components and their normalization level;
- composite score, rank, and rank percentile;
- valid-signal count;
- latest fiscal-period, filing, and availability dates;
- chosen XBRL tags and direct/derived-quarter provenance;
- coverage or missing reason.

GOOG and GOOGL receive the same issuer facts and tied fundamental score while
retaining their separate security-level price ranks and portfolio weights.

## Universe-level outputs

For every rebalance:

- eligible universe count;
- covered universe count and coverage ratio;
- stock-level fundamental score and rank;
- stock-level price score and rank;
- Spearman correlation between price and fundamental ranks on the covered
  intersection;
- top-group overlap count and share;
- bottom-group overlap count and share;
- sector-level eligible, covered, and coverage ratios;
- alignment change versus the immediately previous valid rebalance.

Top and bottom groups use the configured portfolio group size, currently ten:

```text
top overlap = intersection(price top 10, fundamental top 10) / 10
bottom overlap = intersection(price bottom 10, fundamental bottom 10) / 10
```

Alignment change is:

```text
spearman_t - spearman_previous_valid_rebalance
```

No forward returns, forward rank IC, rolling IC, ICIR, or portfolio IR are
introduced.

## Portfolio-level outputs

Only after the independent universe ranking is complete is it joined to the
selected price-momentum holdings.

Required outputs are:

- long-leg average fundamental rank;
- long-leg median fundamental rank;
- short-leg average fundamental rank;
- short-leg median fundamental rank;
- long-minus-short fundamental score spread;
- percentage of covered long names with composite score greater than zero;
- percentage of covered short names with composite score greater than zero;
- price winners with deteriorating fundamentals: long names with score below
  zero;
- price losers with improving fundamentals: short names with score above zero;
- covered count, coverage status, and missing-symbol list for each leg.

Raw rank averages are accompanied by rank percentiles because raw ranks change
scale when the covered universe count changes.

Exception lists are preserved as structured rows as well as compact JSON
context in the visible scorecard. They include symbol, price rank,
fundamental rank, composite score, and valid-signal count.

## Revised coverage policy

Universe coverage:

| Coverage ratio | Status | Behavior |
|---|---|---|
| `>= 80%` | `normal` | Universe and portfolio alignment can be used normally |
| `>= 60% and < 80%` | `degraded` | Metrics remain visible with an explicit warning |
| `< 60%` | `insufficient` | Universe alignment flags are unavailable, not false |

Portfolio-leg coverage:

| Covered names | Status | Behavior |
|---|---|---|
| `8–10 of 10` | `normal` | Leg metrics can be used normally |
| `6–7 of 10` | `degraded` | Leg metrics remain visible with an explicit warning |
| `< 6 of 10` | `insufficient` | Affected leg metrics and flags are unavailable |

Universe metrics and leg metrics are gated independently. For example, valid
universe alignment may remain visible when one selected leg has insufficient
coverage. Overall display status is the worst applicable coverage state, but
no opaque numeric coverage score is created.

## Deterministic alignment flags

After 24 earlier valid monthly rebalances, thresholds use prior-only history.
Before that, fallbacks are labeled `demo_threshold`.

| Flag | Direction | Historical threshold | Demonstration fallback |
|---|---|---|---|
| Weak price/fundamental correlation | `correlation <=` | prior 20th percentile, with zero threshold floor | `0.00` |
| Insufficient long support | `long_positive_share <=` | prior 20th percentile | `0.60` |
| Improving short leg | `short_positive_share >=` | prior 80th percentile | `0.40` |
| Narrow/negative score spread | `long_minus_short_score_spread <=` | prior 20th percentile, with zero threshold floor | `0.00` |
| Sharp alignment deterioration | `alignment_change <=` | prior 20th percentile | `-0.20` |

Negative correlation and a negative long-minus-short score spread must always
qualify as risk. A structural guardrail that overrides the historical
quantile is labeled `demo_threshold`, matching Phase 4 provenance rules.

The five flags remain separate. They are not averaged into a probability or
composite alert count.

## Separate Fundamental Alignment Scorecard

The existing four-row Phase 4 scorecard remains unchanged internally.
Phase 5 creates a separate visible artifact for the final demo:

```text
outputs/fundamental_alignment/
    fundamental_alignment_scorecard_<rebalance-date>.csv
```

The visible scorecard contains these auditable rows:

1. universe data coverage;
2. universe price/fundamental rank correlation;
3. long-leg fundamental support;
4. improving fundamentals in the short leg;
5. long-minus-short fundamental score spread;
6. alignment deterioration.

Top/bottom overlap, sector coverage, average/median leg ranks, contradiction
lists, missing symbols, tag provenance, and membership limitations are exposed
as row context and in the underlying output tables. Coverage rows use the
explicit `normal`, `degraded`, and `insufficient` policy rather than a
historical quantile.

The scorecard cannot modify Phase 1–4 trigger values and cannot fail their
pipeline.

## Retained minimal concentration work

The already approved low-cost concentration module remains secondary to the
alignment panel and independent of SEC availability:

- effective number of bets;
- top-five absolute contribution share;
- sector concentration.

It uses the completed holding month before each rebalance and the Phase 2
signed-contribution convention. No additional breadth, forward-return IC, or
crowding framework is added.

## Exact files proposed for production implementation

Documents revised during this review gate only:

- `docs/confirmed_design.md`
- `docs/development_plan.md`
- `docs/meeting_feedback.md`
- `docs/phase_reviews/README.md`
- `docs/phase_reviews/phase_5_review.md`

Create:

- `src/data/sec_fundamentals.py`
- `src/features/fundamental_momentum.py`
- `src/monitoring/fundamental_alignment.py`
- `src/risk/breadth.py`
- `tests/test_sec_fundamentals.py`
- `tests/test_fundamental_momentum.py`
- `tests/test_fundamental_alignment.py`
- `tests/test_breadth.py`

Modify:

- `src/data/sec_edgar.py`
  - expose one public cache-first Company Facts fetch function;
  - keep the existing SEC contact and request-throttling controls;
- `src/data/sp500.py`
  - expose current industry alongside current sector classification without
    presenting either as historical PIT data;
- `docs/development_plan.md`
  - record the universe-first sequence and revised coverage gates;
- `docs/phase_reviews/phase_5_review.md`
  - add observed implementation outputs, tests, findings, and lessons after
    approval;
- `docs/phase_reviews/README.md`
  - track Phase 5 status.

Do not modify:

- `src/monitoring/scorecard.py`;
- `src/pipeline.py`;
- `src/mvp/`;
- Phase 1–4 processed data products;
- project dependencies.

Planned generated artifacts:

- `data/raw/sec/company_facts_CIK<10-digit-CIK>.json` and provenance sidecars,
  one fetch per distinct CIK rather than duplicate requests for share classes;
- `outputs/sec_fundamental_acquisition_report.json`;
- `data/processed/sec_fundamental_facts.parquet`;
- `data/processed/fundamental_momentum_stock_panel.parquet`;
- `data/processed/fundamental_alignment_history.parquet`;
- `data/processed/fundamental_sector_coverage.parquet`;
- `data/processed/fundamental_alignment_exceptions.parquet`;
- `data/processed/portfolio_breadth_history.parquet`;
- `outputs/fundamental_alignment/fundamental_alignment_scorecard_<date>.csv`;
- `outputs/fundamental_alignment/alignment_audit.json`;
- `outputs/breadth/breadth_audit.json`.

## Recommended implementation sequence

### Phase 5A — acquisition and feasibility gate

1. Require the operator-provided `SEC_CONTACT_EMAIL`.
2. Fetch and cache Company Facts for every distinct CIK in the eligible
   universe.
3. Produce counts for usable filing, revenue, EPS, operating income/margin,
   two-of-three composite, each sector, and both current portfolio legs.
4. Diagnose missingness by ticker mapping, HTTP result, tag, unit, dimension,
   period continuity, staleness, and filing-date filter.
5. Stop for data review.

No monitor should be built if coverage remains below 60% without an understood
and economically defensible remediation.

### Phase 5B — universe stock panel

1. Parse PIT quarterly facts with explicit direct/derived provenance.
2. Build the three raw signals.
3. normalize by industry when at least ten peers exist, otherwise by sector;
4. require two valid signals and rank the composite across all covered
   eligible stocks;
5. persist the stock panel and sector-coverage history.

### Phase 5C — universe and portfolio alignment

1. Rebuild full-universe 12-1 price ranks.
2. Calculate Spearman alignment, top/bottom overlap, and prior-rebalance
   change.
3. Map the independent fundamental rank onto the selected price legs.
4. Emit leg ranks, spread, positive shares, contradiction lists, missing
   symbols, coverage states, and five deterministic flags.
5. Generate the separate visible Fundamental Alignment Scorecard.

### Phase 5D — minimal concentration and review

1. Build only the three approved contribution-concentration metrics.
2. Run targeted leakage, mapping, period, restatement, normalization,
   coverage-boundary, missing-data, and repeatability tests.
3. Run the full regression suite and prove the Phase 4 scorecard is unchanged.
4. Record observed outputs and lessons in this review and stop for approval.

## Minimum acceptance criteria

- The primary artifact is a universe-level stock panel, not a 20-name
  portfolio-only calculation.
- Eligible and covered universe denominators are separate.
- Full-universe price and fundamental ranks are calculated independently
  before the portfolio join.
- Ticker-to-CIK mapping and one-request-per-CIK behavior are auditable.
- Company Facts acquisition is explicit, cache-first, resumable, and cannot
  run uncached without a real SEC contact.
- Filing-date, next-trading-day availability, amendment, and future-data tests
  prevent look-ahead.
- Fiscal period and Q4 handling never subtract non-additive EPS.
- Every signal is industry-relative with at least ten peers or falls back to
  sector-relative normalization.
- At least two of three signals are required per covered stock.
- All required universe and portfolio outputs are persisted.
- Coverage states exactly follow the 80%/60% universe and 8/6 leg boundaries.
- Insufficient coverage produces nullable metrics and flags, never a silent
  safe result.
- A separate visible Fundamental Alignment Scorecard is produced without
  changing the Phase 4 scorecard.
- The concentration module still contains exactly three metrics.
- No forward-return IC, rolling IC, ICIR, portfolio IR, analyst-revision
  scraper, static quality library, new dependency, or unrelated refactor is
  introduced.

## Review decision required

Production implementation has not started.

Approval should first authorize Phase 5A full-universe Company Facts
acquisition and confirm:

- `filed_date + next trading day` availability;
- 180-day fiscal-period staleness limit;
- revenue acceleration, symmetric EPS acceleration, and year-over-year
  operating-margin change;
- industry normalization at ten valid peers, otherwise sector fallback;
- the exact 80%/60% universe and 8/6 leg coverage states;
- the six-row separate Fundamental Alignment Scorecard;
- keeping the Phase 4 scorecard unchanged.
