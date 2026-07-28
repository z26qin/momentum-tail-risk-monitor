# Development plan: top-down risk monitoring MVP

Status: Phase 2 implementation baseline, revised 2026-07-27 after the
Fundamental Momentum Alignment re-scope.

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

The current `src.pipeline` path remains runnable while the new modules are
built. It is replaced or redirected only in the final integration phase.

## 2. Budget and scope

The implementation target is approximately 12 hours, with 1–2 hours of
contingency inside the stated 10–15 hour review budget.

| Phase | Deliverable | Estimate |
|---:|---|---:|
| 1 | Macro regime module | 1.25 h |
| 2 | Synthetic S&P 500 portfolio | 2.75 h |
| 3 | Long/short risk decomposition | 1.25 h |
| 4 | Deterministic scorecard | 1.25 h |
| 5 | Fundamental Momentum Alignment plus minimal breadth | 2.00 h |
| 6 | Crowding reuse and research note | 0.25 h |
| 7 | Minimal AI evidence adaptation | 1.25 h |
| 8 | Demo, historical case, and documentation | 1.50 h |
| | Planned implementation | **11.50 h** |

Budget protection rules:

- Phase 2 gets the largest allocation because constituent data and return
  alignment determine every downstream result.
- If reliable point-in-time S&P 500 membership cannot be obtained quickly,
  use a frozen current-membership S&P 500 snapshot and expose
  `survivorship_bias=true`; do not substitute the current top-200 universe.
- Phase 5 is configuration-gated and may ship with unavailable values if
  public fundamentals cannot meet timestamp and coverage checks.
- Phase 6 adds no scraper.
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
- modify `src/mvp/contracts.py` only if a shared serialized contract is needed

Minimum acceptance:

- each row contains monitor family, metric, current value, threshold,
  threshold provenance, triggered flag, severity, direction, explanation,
  as-of date, and source module;
- minimum monitors cover drawdown, recovery, volatility, long beta, short beta,
  beta gap, long-short drawdown, short loss contribution, breadth, and
  concentration;
- boundary, missing-value, comparator-direction, schema, and repeatability
  tests pass;
- missing is explicit and is never silently false;
- DM/B0/B1/B2/B3 mapping is metadata or reference context, not an averaged
  score.

### Phase 5 — Fundamental Momentum Alignment and minimal breadth

Inspect first:

- Phase 2 signal, holdings, and current sector fields
- contribution definitions from Phase 3
- `src/data/sec_edgar.py`
- cached SEC Company Facts and filing-date coverage

Expected reuse:

- monthly price ranks, pure Pandas rank calculations, SEC filing-date
  availability controls, and Phase 3 contribution definitions.

Planned files:

- create `src/data/sec_fundamentals.py`
- create `src/monitoring/fundamental_alignment.py`
- create `src/risk/breadth.py`
- create `tests/test_sec_fundamentals.py`
- create `tests/test_fundamental_alignment.py`
- create `tests/test_breadth.py`
- modify `src/monitoring/scorecard.py` only to consume optional status and flags

Minimum acceptance:

- prioritize revenue-growth acceleration, EPS-growth acceleration, and
  operating-margin change; at least two valid signals per company;
- normalize every signal within sector before combining;
- output price rank, fundamental rank, cross-sectional Spearman correlation,
  long and short fundamental averages, long-minus-short spread, long-positive
  share, short-improving share, top/bottom overlap, and change versus the
  previous rebalance;
- deterministic flags cover weak/negative correlation, insufficient long
  support, improving shorts, narrow/negative spread, and sharp deterioration;
- thresholds use prior-only historical quantiles after at least 24 rebalances;
  earlier thresholds are labeled demonstration assumptions;
- use filing/availability dates, never fiscal-period end as availability;
- status is `disabled`, `unavailable`, `insufficient_coverage`, or `available`;
- imperfect fundamentals cannot block macro, portfolio, beta, or scorecard;
- retain only effective number of bets, top-five contribution share, and
  sector concentration;
- do not implement forward-return IC, rolling IC, ICIR, or a static
  quality/profitability factor library.

### Phase 6 — Crowding

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

### Phase 7 — Minimal AI evidence

Inspect first:

- `src/evidence/mvp.py`
- archive provider, classifier validator, prompts, and evidence contracts
- Phase 4 scorecard output

Expected reuse:

- deterministic gating, archive cutoffs, retrieval hashing, structured
  validation, grounded passages, and fail-closed behavior.

Planned files:

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
- no complex orchestration or multi-agent framework.

### Phase 8 — Demo and documentation

Inspect first:

- all prior phase outputs
- `src/pipeline.py` and `src/reporting/pm_brief.py`
- existing 2023 data coverage

Expected reuse:

- current CLI conventions, atomic output, contracts, and Markdown reporting.

Planned files:

- create `src/demo.py`
- create `tests/test_demo.py`
- modify `src/reporting/pm_brief.py`
- modify `README.md`
- modify `docs/confirmed_design.md`
- create `docs/methodology.md`
- create `docs/limitations.md`
- create `outputs/demo/` artifacts through the command, not by hand

Minimum acceptance:

- one command answers all ten confirmed demo questions;
- one current/as-available scorecard and one 2023 historical case are
  reproducible;
- output includes macro regime, named holdings, leg-risk driver, triggers,
  beta gap, breadth, concentration, fundamental-alignment status, evidence,
  and next research questions;
- architecture, methodology, limitations, and test summary match the code;
- the full test suite passes.

## 4. Cross-phase test strategy

Every new time-dependent calculation should receive:

- a small synthetic example with an analytically known answer;
- a future-data perturbation test;
- a fixed-as-of repeatability test;
- missing and boundary-value tests;
- an integration assertion that dates, holdings, returns, and benchmarks align.

The full existing suite should run after any change to shared utilities,
contracts, the active pipeline, or evidence validation.

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

Phase 0 is complete. No Phase 1 code should be written until the Phase 0 audit
and this proposed plan are reviewed.
