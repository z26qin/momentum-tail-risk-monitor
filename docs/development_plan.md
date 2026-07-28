# Development plan: top-down risk monitoring MVP

Status: Phases 1–4 and Phase 5A are complete. The unnumbered final MVP
integration is complete. Phase 5B, Phase 7 Crowding Monitoring, and Phase 8
Full AI Research and Retrieval remain deferred.

## 1. Delivery method

Work remains sequential and review-gated. Before each phase:

1. inspect the relevant implementation and data;
2. identify reusable code;
3. name the exact files to change;
4. state the phase acceptance criteria;
5. wait for approval before a large change.

After each phase:

1. run targeted tests and the relevant regression tests;
2. show one representative output;
3. list assumptions and limitations;
4. create or update `docs/phase_reviews/phase_<n>_review.md` with empirical
   findings, development lessons, limitations, and consequences for the next
   phase;
5. stop for review.

The review journal format and index live in `docs/phase_reviews/README.md`.
Maintaining that journal is part of every phase's acceptance criteria.

The earlier `src.pipeline` path remains runnable as retained research. The
unique primary demo entry is now `src.mvp.run_demo`.

## 2. Budget and scope

The original reviewed plan was time-boxed to approximately 13 hours. The final
deadline integration did not renumber or silently complete deferred research
phases.

| Phase | Deliverable | Estimate / status |
|---:|---|---:|
| 1 | Macro regime module | 1.25 h |
| 2 | Synthetic S&P 500 portfolio | 2.75 h |
| 3 | Long/short risk decomposition | 1.25 h |
| 4 | Deterministic scorecard | 1.25 h |
| 5A | SEC acquisition and fundamental coverage feasibility | Complete |
| 5B | Production historical fundamentals and alignment | Deferred |
| Final MVP integration | Date-safe demo, 2023 case, bounded evidence preview | Complete |
| 7 | Crowding Monitoring | Deferred |
| 8 | Full AI Research and Retrieval Layer | Deferred |

Budget protection rules:

- Phase 2 gets the largest allocation because constituent data and return
  alignment determine every downstream result.
- If reliable point-in-time S&P 500 membership cannot be obtained quickly,
  use a frozen current-membership S&P 500 snapshot and expose
  `survivorship_bias=true`; do not substitute the current top-200 universe.
- Phase 5 began with full-universe Company Facts acquisition and a coverage
  audit. The observed 64.79% coverage is degraded but sufficient to preserve
  Phase 5B as a future production task.
- Phase 7 adds no fragile scraper without a separately reviewed data source.
- Do not build a standalone IC/IR analytics framework.
- No new predictive model is trained.

## 3. Phase plans

### Phase 1 — Macro regime

Inspect first:

- `src/risk/dm_engine.py`
- `src/features/market_features.py`
- `src/data/french.py`
- `src/data/vix.py`
- relevant DM, feature, and PIT tests

Expected reuse:

- 504-day market return, 126-day variance, trailing-return helpers, expanding
  PIT reference logic, as-of filtering, and the post-close convention.

Planned files:

- create `src/regime/__init__.py`
- create `src/regime/market_state.py`
- create `tests/test_market_regime.py`

Minimum acceptance:

- one dated table with `metric`, `value`, `threshold`, `state`,
  `triggered`, and `explanation`;
- market drawdown, recovery from trough, realized volatility, crash, early
  recovery, high-volatility recovery, and a simple rate-policy proxy;
- liquidity only if an existing, defensible source is available;
- future-row perturbations do not change earlier output;
- deterministic equality across repeated fixed-date runs;
- synthetic crash/recovery transitions are correct.

Likely design:

- use the broad-market wealth index for rolling peak, drawdown, and recovery;
- retain the DM bear/variance state as one regime dimension;
- define recovery only after a documented trough/drawdown condition;
- use the existing Ken French risk-free series as the first rate-regime
  candidate, subject to inspection;
- omit or mark liquidity unavailable rather than inventing a weak proxy.

### Phase 2 — Synthetic S&P 500 momentum portfolio

Inspect first:

- `src/data/universe.py`, `prices.py`, `trading_calendar.py`
- `src/features/positioning_panel.py`
- available raw universe snapshots and price coverage

Expected reuse:

- price parsing, symbol normalization, month-end extraction, 12-2 formation
  logic, next-month membership convention, and current PIT tests.

Planned files:

- create `src/data/sp500.py`
- create `src/portfolio/__init__.py`
- create `src/portfolio/momentum.py`
- create `tests/test_momentum_portfolio.py`
- create or update `docs/universe.md` only for the selected S&P 500 universe
  contract and survivorship disclosure

Minimum acceptance:

- a dated S&P 500 universe table with source and PIT/fallback status;
- configurable `n_long=10`, `n_short=10`;
- 12-1 signal with the most recent month skipped;
- formation at month-end, application beginning in the next trading month;
- equal `+1/n_long` long weights and `-1/n_short` short weights;
- long-basket, short-basket, portfolio, cumulative return, and drawdown output;
- signal/return alignment proven by synthetic tests;
- no current top-200 proxy mislabeled as S&P 500.

Data gate:

- cap S&P 500 membership acquisition work;
- prefer a dated public membership/change history if it is clean;
- otherwise commit one frozen current S&P 500 snapshot and clearly state that
  the historical demonstration is survivorship-biased;
- use only dates for which sufficient price history and at least 10 eligible
  names per leg exist.

### Phase 3 — Long/short risk decomposition

Inspect first:

- Phase 2 holdings and returns
- `src/features/market_features.py`
- legacy leg/beta helpers in `src/monitoring/market_context.py`

Expected reuse:

- rolling covariance/variance beta formula and trailing-window discipline.

Planned files:

- create `src/risk/leg_decomposition.py`
- create `tests/test_leg_decomposition.py`

Minimum acceptance:

- realized long, short-underlying, and long-short beta;
- short-minus-long beta gap;
- up- and down-market beta using benchmark-return sign;
- long, short, and portfolio volatility;
- signed long and short contribution with arithmetic reconciliation;
- portfolio drawdown and short-leg loss contribution in recovery windows;
- documented benchmark, window, minimum observations, and missing-data rule;
- all windows end on or before the as-of date.

Default prototype convention, subject to phase review:

- 126 trading-day rolling beta, minimum 63 observations;
- S&P 500 total-return proxy if acquired with the portfolio data, otherwise the
  existing broad US market return proxy with an explicit label;
- `benchmark > 0` and `< 0` for conditional betas; zero-return days excluded.

### Phase 4 — Deterministic scorecard

Inspect first:

- Phase 1 and Phase 3 table schemas
- `src/mvp/contracts.py`
- `src/monitoring/domain_risk.py`

Expected reuse:

- validated dataclass patterns, explicit comparator logic, and deterministic
  threshold tests.

Planned files:

- create `src/monitoring/scorecard.py`
- create `tests/test_scorecard.py`
- leave `src/mvp/contracts.py` unchanged; the old probability-led path is not
  the new scorecard contract

Minimum acceptance:

- each row contains monitor family, metric, current value, threshold,
  threshold provenance, triggered flag, severity, direction, explanation,
  as-of date, and source module;
- expose exactly four Phase 4 alert rows: high-volatility recovery,
  short-minus-long beta gap, portfolio drawdown, and short loss in recovery;
- keep underlying drawdown, recovery, volatility, long beta, short beta, and
  portfolio beta as diagnostic context rather than duplicate alerts;
- use prior-only historical quantiles after 252 observations, with explicitly
  labeled demonstration fallbacks;
- measure portfolio drawdown from the trailing 63-day high-water mark and
  bound its threshold between -20% and -5%, so stale underwater history cannot
  make the alert progressively more tolerant;
- boundary, missing-value, comparator-direction, schema, and repeatability
  tests pass;
- missing is explicit and is never silently false;
- do not emit an averaged score, unexplained risk probability, or separate
  DM/B0/B1/B2/B3 vote.

### Phase 5 — Universe Fundamental Momentum and Portfolio Alignment

Inspect first:

- Phase 2 full-universe signal, ranks, holdings, and current classifications
- contribution definitions from Phase 3
- `src/data/sec_edgar.py`
- ticker-to-CIK coverage, Company Facts acquisition routing, taxonomy tags,
  quarterly/annual periods, fiscal alignment, and filing-date filters

Expected reuse:

- monthly 12-1 price calculations, pure Pandas rank calculations, SEC
  cache/provenance controls, and Phase 3 contribution definitions.

Phase 5A implemented files:

- create `src/data/sec_fundamentals.py`
- create `tests/test_sec_fundamentals.py`
- modify `src/data/sec_edgar.py` only to expose public cache-first Company
  Facts acquisition
- modify `src/data/sp500.py` to expose current industry classification with
  its non-PIT status

Deferred Phase 5B files:

- `src/features/fundamental_momentum.py`
- `src/monitoring/fundamental_alignment.py`
- focused production tests for the historical panel and alignment contract
- a separate visible Fundamental Alignment Scorecard

Minimum acceptance:

- perform a full-universe SEC acquisition and feasibility gate before
  production monitor implementation;
- define the eligible membership/price universe first, retaining the current
  snapshot and survivorship warnings where historical membership is missing;
- calculate price momentum and its ranks across the full eligible universe;
- prioritize revenue-growth acceleration, EPS-growth acceleration, and
  operating-margin change; at least two valid signals per company;
- use industry-relative normalization only with at least ten valid peers,
  otherwise fall back to sector-relative normalization; at least ten peers is
  normal, 5–9 is degraded, and fewer than five is unavailable;
- rank fundamental momentum across all covered eligible stocks before joining
  the independently selected price-momentum portfolio;
- output eligible/covered counts, stock-level price and fundamental scores and
  ranks, Spearman correlation, top/bottom overlap, sector coverage, and
  change versus the previous valid rebalance;
- output average and median fundamental ranks by leg, long-minus-short score
  spread, long-positive and short-positive-relative shares, contradiction
  lists, and covered/missing names for each leg;
- deterministic flags cover weak/negative correlation, insufficient long
  support, improving shorts, narrow/negative spread, and sharp deterioration;
- thresholds use prior-only historical quantiles after at least 24 rebalances;
  earlier thresholds are labeled demonstration assumptions;
- define `correlation_threshold = max(prior_20th_percentile, 0.0)` and
  `spread_threshold = max(prior_20th_percentile, 0.0)`;
- label calibration based on current-membership or current-classification
  history as `historical_proxy_threshold`;
- do not calculate operating-margin change for banks, insurers, REITs, or
  other accounting categories where it is not economically comparable;
- use Spearman rank correlation as the primary universe-alignment metric;
  top/bottom-10 overlap is a portfolio-oriented diagnostic;
- use the first trading day after filing as availability and reject components
  whose latest fiscal period is more than 180 days stale;
- universe coverage is normal at 80% or more, degraded from 60% to below 80%,
  and insufficient below 60%;
- leg coverage is normal at 8–10 names, degraded at 6–7, and insufficient
  below 6;
- insufficient inputs remain nullable, not silently safe;
- produce a separate six-row visible Fundamental Alignment Scorecard;
- imperfect fundamentals cannot block macro, portfolio, beta, or scorecard;
- retain only effective number of bets, top-five contribution share, and
  sector concentration;
- do not implement forward-return IC, rolling IC, ICIR, or a static
  quality/profitability factor library.

Approved execution boundary:

- Phase 5A may fetch one Company Facts payload per eligible CIK and report
  coverage by metric, sector, and current portfolio leg, including missing
  tags, periods, staleness, and accounting-category diagnoses;
- stop after Phase 5A review;
- do not yet build the historical panel, calibration history, breadth module,
  production flags, or separate production scorecard.

### Phase 7 — Crowding Monitoring (deferred)

Inspect first:

- Phase 5 concentration results
- `src/features/positioning_panel.py`
- `src/overlays/snapshots.py`

Expected reuse:

- effective bets, contribution and sector concentration, plus existing FINRA
  loser-leg crowding snapshots.

Planned files:

- create `docs/crowding_research.md`
- modify the final scorecard mapping only if Phase 5 metrics need a crowding
  family label

Minimum acceptance:

- every crowding field says `proxy`;
- no fragile data acquisition is introduced;
- the note covers 13F, ownership concentration, short interest, FINRA
  off-exchange volume, options, social attention, and ETF ownership/flows;
- ETF overlap is included only if a ready, dated holdings source is already
  available.

### Phase 8 — Full AI Research and Retrieval Layer (deferred)

Inspect first:

- `src/evidence/mvp.py`
- archive provider, classifier validator, prompts, and evidence contracts
- Phase 4 scorecard output

Expected reuse:

- deterministic gating, archive cutoffs, retrieval hashing, structured
  validation, grounded passages, and fail-closed behavior.

Future planned files:

- create `src/evidence/risk_research.py`
- create `tests/test_risk_research.py`
- modify `src/mvp/contracts.py` for the confirmed structured output
- modify `src/evidence/prompts.py` only if a versioned prompt is required

Minimum acceptance:

- output fields are `risk_state`, `triggered_metrics`,
  `supporting_evidence`, `contradicting_evidence`, `historical_analogs`,
  `research_questions`, `citations`, `confidence`, and `limitations`;
- deterministic facts and AI interpretation are separate;
- current long/short names and selected comparison window enter the request;
- the response cannot change metric values, thresholds, or trigger flags;
- future, ungrounded, omitted, and retrieval-mismatched evidence fails closed;
- no unreviewed complex orchestration or multi-agent framework.

The final MVP's `src/evidence/research_preview.py` is not this phase. It is a
bounded offline capability preview that replays only exact-date validated
caches and fails closed.

### Final MVP integration — completed, not a roadmap phase

Inspect first:

- all prior phase outputs
- `src/pipeline.py` and `src/reporting/pm_brief.py`
- existing 2023 data coverage

Expected reuse:

- current CLI conventions, atomic output, contracts, and Markdown reporting.

Implemented files:

- create `src/mvp/run_demo.py`
- create `tests/test_demo.py`
- create `src/evidence/research_preview.py`
- create `tests/test_research_preview.py`
- modify `README.md`
- modify `docs/confirmed_design.md`
- create `docs/methodology.md`
- create `docs/demo_walkthrough.md`
- create `docs/handoff.md`
- create `outputs/demo/` artifacts through the command, not by hand

Minimum acceptance:

- one command produces one structured, date-aligned demo;
- one current/as-available scorecard and one 2023 historical case are
  reproducible;
- output includes macro regime, named holdings, leg-risk drivers, triggers,
  beta gap, Phase 5A feasibility, unavailable alignment fields, bounded
  evidence, limitations, and next research questions;
- architecture, methodology, limitations, and test summary match the code;
- the full test suite passes.

Explicit final-integration exclusions:

- no Phase 5B, breadth, concentration, crowding, live news, vector database,
  dashboard, deployment, predictive model, or calculation-module refactor;
- exactly four focused demo tests and two focused evidence-preview tests.

## 4. Cross-phase test strategy

Future substantive calculation phases should receive:

- a small synthetic example with an analytically known answer;
- a future-data perturbation test;
- a fixed-as-of repeatability test;
- missing and boundary-value tests;
- an integration assertion that dates, holdings, returns, and benchmarks align.

The final MVP integration intentionally uses only its six approved focused
tests plus the full existing regression suite. Final validation collected 215
tests: 211 passed and 4 cache-dependent rebuild tests skipped.

## 5. Principal delivery risks

| Risk | Control |
|---|---|
| Public S&P 500 membership history is incomplete | Time-box acquisition; freeze and disclose current membership rather than imply PIT membership |
| Adjusted prices or delisted names are missing | Record eligibility and coverage per rebalance; never backfill a missing return with zero |
| Short-return sign is misunderstood | Store underlying short-basket return and signed portfolio contribution as separate columns |
| Recovery rule becomes arbitrary | Show metric, threshold, provenance, and transition tests |
| Fundamentals are restated or sparsely tagged | Join on filing date, report source concept and coverage, and fail to unavailable |
| Scorecard becomes an opaque aggregate | Keep row triggers as the official output; any summary is a deterministic count/severity rule |
| AI appears to decide risk | Pass immutable facts, validate echoed values, and prohibit write-back |
| Historical 2023 demo benefits from hindsight | Freeze the as-of date and include only inputs available by that date |

## 6. Review gate

The final MVP integration is complete. Any work on Phase 5B, Phase 7, or the
full Phase 8 requires a new review and explicit authorization.
