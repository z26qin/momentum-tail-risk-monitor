# Phase 5 reconstruction review: momentum unwind structure monitor

Date: 2026-07-29

Status: approved by the operator; implementation and notebook integration complete

## Executive recommendation

Re-scope Phase 5 as:

```text
Phase 5 — Momentum Unwind Structure, Crowding, Breadth, and Fundamental Anchor
```

The repository can support a bounded public-data unwind monitor without
rebuilding Phases 1–4. Existing prices, monthly holdings, daily leg returns,
realized beta, benchmark returns, volume, and current sector labels are
sufficient for concentration, breadth, residual long-leg loss, cross-sectional
reversal, synchronous decline, and labeled liquidity proxies.

The main constraints are equally important:

- historical S&P 500 membership and sector classifications are current-snapshot
  proxies;
- the persisted portfolio has equal target weights, so formation-date
  effective bets are mechanically fixed and the useful exposure measure is the
  drifted beginning-of-day exposure;
- no constituent-level P&L contribution history is persisted today;
- only close and volume data are available, not open/high/low or order-book
  data;
- the full SEC Company Facts cache is local and ignored by Git;
- Phase 5A produced one audited 2026-06-30 feasibility snapshot, not a
  historical fundamental panel;
- public data cannot prove hedge-fund leverage, dealer constraints, or forced
  liquidation.

The minimum architecture should therefore add a separate, nullable six-row
unwind scorecard and rule-based scenario assessment. It must not change the
existing four-row Phase 4 scorecard or the version-1 Phase 6 deterministic
contract. Notebook integration should consume the new assessment alongside
the current Evidence Card.

## A. Repository diagnosis

### What exists from Phase 5A

The implemented Phase 5A boundary is
`src.data.sec_fundamentals.run_phase5a`. It:

1. calls `src.data.sec_fundamentals.build_eligible_universe` to resolve the
   latest price-eligible universe;
2. uses `src.data.sec_edgar.fetch_company_facts_by_cik` through
   `src.data.sec_fundamentals.acquire_distinct_ciks` for cache-first,
   one-request-per-CIK acquisition;
3. applies filing-date and next-trading-day availability rules through
   `first_trading_day_after`;
4. parses approved revenue, EPS, and operating-income tags through
   `audit_company_facts_payload`;
5. constructs revenue-growth acceleration, bounded EPS-growth acceleration,
   and operating-margin change;
6. applies the 180-day staleness rule and financial/REIT margin exclusions;
7. maps issuer results back to securities through `build_company_coverage`;
8. produces metric, sector, leg, missingness, taxonomy, acquisition, and audit
   summaries.

The tracked Phase 5A outputs are:

- `outputs/fundamental_alignment/phase_5a_audit.json`;
- `outputs/fundamental_alignment/phase_5a_metric_coverage.csv`;
- `outputs/fundamental_alignment/phase_5a_missing_diagnostics.csv`;
- `outputs/fundamental_alignment/phase_5a_portfolio_leg_coverage.csv`;
- `outputs/fundamental_alignment/phase_5a_sector_coverage.csv`.

The local audit also produced company-level, taxonomy, and acquisition files,
but the large company-level file and 497 CIK payloads plus sidecars are ignored
and are not portable in a clean clone.

Verified 2026-06-30 issuer results:

| Item | Result |
|---|---:|
| Eligible securities | 500 |
| Distinct mapped issuers | 497 |
| Available Company Facts payloads | 497 |
| Revenue-acceleration coverage | 449 / 497, 90.34% |
| EPS-acceleration coverage | 23 / 497, 4.63% |
| Operating-margin coverage, applicable denominator | 324 / 401, 80.80% |
| Two-of-three coverage | 322 / 497, 64.79%, degraded |
| Long-leg two-of-three coverage | 8 / 10, normal |
| Short-leg two-of-three coverage | 7 / 10, degraded |

This is useful feasibility infrastructure. It is not a historical fundamental
signal and does not contain production alignment flags.

### What was never implemented

The following planned files and products do not exist:

- `src/features/fundamental_momentum.py`;
- `src/monitoring/fundamental_alignment.py`;
- `src/risk/breadth.py`;
- a historical SEC fundamental stock panel;
- industry/sector-relative fundamental ranks;
- price-versus-fundamental Spearman alignment;
- long-minus-short fundamental spreads;
- production alignment flags;
- portfolio concentration history;
- momentum breadth history;
- the separate Fundamental Alignment Scorecard.

The Phase 5A module explicitly states that it stops before all of these.

### Where breadth and concentration disappeared

They did not fail or get removed from production code. The Phase 5 review
reserved them for the unapproved post-5A work:

- Phase 5B: historical universe stock panel;
- Phase 5C: universe and portfolio alignment;
- Phase 5D: effective bets, top-five contribution share, and sector
  concentration.

The repository stopped at the Phase 5A approval gate. Commit `49e3f1c`
therefore froze the acquisition/feasibility audit without adding any 5B–5D
module. Phase 6 respected that boundary and explicitly reported Phase 5
alignment as unavailable.

### Reusable Phase 1–4 and Phase 5A components

| Capability | Existing reusable entry point | Verified use |
|---|---|---|
| PIT macro state | `src.regime.market_state.build_regime_history` | Existing drawdown, recovery, volatility, and high-volatility-recovery state |
| Full-universe 12-1 momentum | `src.portfolio.momentum.build_momentum_signals` | Monthly eligible-universe breadth and ranks |
| Named portfolio construction | `src.portfolio.momentum.build_momentum_holdings` | Long 10 / short 10 membership and target weights |
| Monthly-drift portfolio returns | `src.portfolio.momentum.build_portfolio_returns` | Authoritative long, short-underlying, signed contribution, and portfolio return convention |
| Realized leg risk | `src.risk.leg_decomposition.build_leg_risk_history` | Long beta, short-underlying beta, benchmark return, volatility, and contribution windows |
| Existing Phase 4 state | `src.monitoring.scorecard.build_scorecard` | Kept unchanged as a separate four-row crash-risk scorecard |
| Current classifications | `src.data.sp500.classification_snapshot_from_nasdaq` and `sp500_universe.parquet` | Sector/industry proxy, always labeled non-PIT |
| Company Facts acquisition | `src.data.sec_edgar.fetch_company_facts_by_cik` | Existing fair-access, cache, provenance, and one-CIK route |
| Fundamental parsing | `src.data.sec_fundamentals.audit_company_facts_payload` | Existing PIT signal values and accounting exclusions |
| Fundamental coverage | `build_company_coverage`, `metric_coverage_table`, `leg_coverage_table` | Exact-date lightweight anchor input when local caches exist |
| Phase 6 adapter | `src.mvp.evidence_card.build_deterministic_evidence_input` | Existing deterministic Evidence Card remains the source of Phase 1–4 facts |
| Phase 6 notebook | `notebooks/03_pm_evidence_card_demo.ipynb` | Add one compact section after the new monitor is independently accepted |

Private helpers such as `src.monitoring.scorecard._threshold` and
`src.mvp.evidence_card._historical_analogs` should not become new public
dependencies.

### Verified data availability

| Artifact | Verified coverage | New Phase 5 use |
|---|---|---|
| `sp500_prices.parquet` | 1,293,310 rows; 2016-01-04 to 2026-07-27; adjusted close, as-traded volume, and dollar volume complete | Constituent returns, breadth, drifted exposure, co-decline, correlation, and liquidity proxies |
| `sp500_universe.parquet` | 503 current constituents; sector present for 500; snapshot dated 2026-07-24 | Current-membership and current-sector proxy only |
| `momentum_portfolio_holdings.parquet` | 114 formations; 2017-01-31 to 2026-06-30; 2,280 rows | Active long/short membership, ranks, target weights, turnover, and overlap |
| `momentum_portfolio_returns.parquet` | 2,365 complete daily rows; 2017-02-01 to 2026-06-30 | Authoritative leg and long-short return reconciliation |
| `leg_risk_history.parquet` | Same 2,365 dates, 48 fields | Benchmark return, prior beta, leg risk, and Phase 1 regime joins |
| Phase 5A audit outputs | One audited formation, 2026-06-30 | Exact-date anchor or unavailable; never carried backward or forward silently |

Consecutive monthly holding overlap is computable from current artifacts
(113 transitions for each leg). Initial target weights are always `+0.10` and
`-0.10`; therefore formation-date effective bets are mechanically 20 on
gross-normalized absolute exposure, or 10 per leg. The proposed concentration
monitor must use explicitly labeled drifted exposure for useful variation.

### Contracts that must remain unchanged

1. Phase 2 holdings and monthly-drift return semantics.
2. The persisted Phase 2 and Phase 3 Parquet schemas.
3. The Phase 4 four-row order, fields, threshold logic, and generated CSVs.
4. `evidence-card-v1` and `deterministic-evidence-input-v1`.
5. The `default` Phase 6 threshold profile.
6. Phase 5A raw signal formulas, availability dates, staleness rule,
   accounting exclusions, and existing audit files.

The new unwind scorecard is a parallel additive contract. It does not become a
fifth or sixth Phase 4 row.

## B. Proposed architecture

### Minimal module plan

Create:

- `src/risk/concentration.py`
  - pure drifted-exposure, contribution-concentration, sector-HHI, overlap,
    persistence, holding-duration, and turnover calculations;
  - separate ex-ante exposure from realized loss contribution;
  - reconcile constituent contributions to existing Phase 2 aggregates.
- `src/features/momentum_breadth.py`
  - pure monthly universe breadth, breadth change, long-leg participation, and
    leadership concentration calculations;
  - reuse `build_momentum_signals` rather than reimplement 12-1 momentum.
- `src/monitoring/fundamental_anchor.py`
  - convert exact-date Phase 5A company-level values into the lightweight
    `supportive`, `mixed`, `deteriorating`, or `unavailable` anchor;
  - reuse Phase 5A parsing and exclusions;
  - fail to unavailable when the local auditable input is absent.
- `src/monitoring/unwind_structure.py`
  - calculate residual long-leg loss, reversal, synchronous decline,
    correlation, and liquidity proxies;
  - calculate prior-only thresholds;
  - assemble and validate the six-row scorecard;
  - produce the deterministic scenario classification and evidence-completeness
    category;
  - expose one public `build_unwind_assessment(as_of_date, ...)` entry point.

Add focused tests:

- `tests/test_concentration.py`;
- `tests/test_momentum_breadth.py`;
- `tests/test_fundamental_anchor.py`;
- `tests/test_unwind_structure.py`.

Modify only after the new module is independently accepted:

- `notebooks/03_pm_evidence_card_demo.ipynb`;
- `src/mvp/demo_smoke_test.py`;
- `tests/test_demo_smoke_test.py`;
- Phase 5/6 review and demo documentation.

Do not modify:

- `src/portfolio/momentum.py` business rules;
- `src/risk/leg_decomposition.py` calculations;
- `src/regime/market_state.py`;
- `src/monitoring/scorecard.py`;
- the Phase 6 deterministic or interpretation schemas;
- `src/pipeline.py`;
- existing processed Phase 1–5 artifacts.

If constituent contribution code cannot exactly reconcile without duplicating
the Phase 2 drift convention, stop at that test failure and request approval
for a behavior-preserving extraction of a public constituent-return helper.
Do not silently maintain two portfolio engines.

### Proposed data flow

```text
sp500_prices + current-snapshot universe
        |
        +--> build_momentum_signals --> monthly breadth history
        |
holdings + prices + existing portfolio returns
        |
        +--> drifted exposure and constituent P&L reconciliation
        |       --> concentration and crowding-loss interaction
        |
        +--> active-name returns
                --> residual long loss
                --> synchronous decline / correlation
                --> long-vs-short reversal
                --> downside-volume and Amihud proxies

Phase 5A Company Facts cache and exact-date coverage
        |
        +--> lightweight fundamental anchor or explicit unavailable

all deterministic components + Phase 1 macro state
        |
        +--> six-row unwind scorecard
        +--> auditable scenario classification
        +--> supporting / contradictory / missing facts
        |
        +--> separate "Momentum Unwind Structure" notebook section
```

### Metrics selected for the MVP

#### 1. Portfolio concentration

Primary value:

```text
effective_bets_abs_exposure =
    1 / sum((abs(drifted_weight_i) / gross_exposure) ** 2)
```

Context:

- top-3 and top-5 absolute drifted-exposure share;
- top-3 and top-5 absolute realized-loss-contribution share;
- sector HHI, top-sector share, and top-two-sector share;
- overlap of the top ex-ante exposures with top realized loss contributors;
- correlation between pre-period absolute exposure and subsequent loss;
- long and short consecutive-rebalance overlap, turnover, and holding duration.

All metrics identify their denominator and whether the input is exposure or
realized loss. Sector values carry
`classification_status=current_snapshot_proxy`.

#### 2. Momentum breadth deterioration

Primary value:

```text
universe_positive_12_1_share =
    eligible names with positive 12-1 momentum / eligible names
```

Context:

- change from the previous rebalance;
- change from the recent three-rebalance maximum;
- active long names with positive trailing 21-day return;
- cross-sectional dispersion of 12-1 scores;
- positive-momentum leadership HHI;
- entries to and exits from the long portfolio.

This keeps four economically distinct ideas: universe breadth, long health,
deterioration, and leadership concentration.

#### 3. Synchronous winner liquidation

Primary value:

```text
residual_long_loss_5d =
    -(long_leg_return_5d
      - sum(lagged_long_beta_126d * benchmark_return over the same window))
```

The beta is lagged one day so the control is available before each return.
Sector-adjusted residual return is unavailable in the MVP because only current
sector classifications exist; current-sector loss context may be shown but
must not be described as production PIT attribution.

The row triggers only when residual loss is extreme and a documented share of
active long names decline over the same five-day window. Context includes:

- raw long return;
- beta-adjusted long return;
- percentage of long names falling;
- average pairwise 21-day correlation;
- correlation change versus prior history;
- simultaneous downside-threshold breach share.

#### 4. Cross-sectional reversal

Primary value:

```text
short_minus_long_return_5d =
    short_underlying_return_5d - long_leg_return_5d
```

Context:

- long-leg return;
- short-underlying return;
- long-minus-short return;
- percentage of long names falling;
- percentage of short names rising;
- optional rank reversal when both comparison ranks are available.

The short-underlying return remains distinct from signed short P&L.

#### 5. Liquidity amplification

Primary value:

```text
downside_abnormal_volume_share_5d =
    active long names with negative five-day return and
    five-day average volume above that name's prior-only 80th percentile
    / eligible active long names
```

Context may include median Amihud illiquidity and its prior-only percentile
when dollar volume is positive. Every output uses `proxy` in its name or
explanation. No output is called leverage, forced selling, dealer stress, or
fund liquidity.

Open/high/low gaps and range expansion are excluded because the repository
does not contain those fields.

#### 6. Fundamental anchor

For each company, use the sign of available:

- revenue-growth acceleration;
- operating-margin change when economically applicable;
- EPS acceleration only when available.

Require at least two economically valid measures for a company-level state.
Do not average raw measures with different units. Use a sign vote:

- more positive than negative measures: supportive;
- more negative than positive measures: deteriorating;
- tie: mixed;
- fewer than two valid measures: unavailable.

Aggregate outputs:

- long covered count and support share;
- short covered count and improving share;
- revenue and margin support shares;
- contradiction names;
- missing names and reasons;
- coverage status and limitations.

Use the existing 8/6 leg coverage boundaries. If either required leg has fewer
than six covered names, the scorecard row is unavailable. EPS never blocks an
otherwise valid revenue-plus-margin company assessment.

### Six-row scorecard contract

Create a new contract with exactly these ordered rows:

1. `portfolio_concentration`;
2. `momentum_breadth_deterioration`;
3. `synchronous_winner_liquidation`;
4. `cross_sectional_reversal`;
5. `liquidity_amplification_proxy`;
6. `fundamental_anchor`.

Columns:

```text
as_of_date
monitor_family
metric
current_value
threshold
threshold_provenance
direction
triggered
severity
status
explanation
context
source_module
data_quality
```

`current_value` and `threshold` may be numeric, string, or null. Numeric rows
use `greater_than_or_equal` or `less_than_or_equal`; the fundamental row uses
`rule_based`. `triggered` is nullable. Missing or insufficient-history inputs
must yield null triggers and may not become zero, safe, or `False`.

Allowed threshold provenance:

- `literature`;
- `historical_quantile`;
- `historical_proxy_threshold`;
- `demo_threshold`;
- `insufficient_history`.

Security-derived historical quantiles use
`historical_proxy_threshold` while the universe and classification history
remain current-snapshot proxies.

### Threshold policy

| Row | Primary threshold |
|---|---|
| Portfolio concentration | Prior-only 20th percentile of effective bets after 252 valid daily observations; otherwise insufficient history |
| Breadth deterioration | Prior-only 20th percentile of monthly positive-momentum share after 24 earlier rebalances; otherwise insufficient history |
| Synchronous winner liquidation | Prior-only 80th percentile of residual long loss after 252 observations, plus an explicit co-decline gate; no future data |
| Cross-sectional reversal | Prior-only 80th percentile of short-minus-long five-day return after 252 observations, floored at zero; a floor override is `demo_threshold` |
| Liquidity amplification proxy | Per-name prior-only 80th-percentile volume test plus an explicit demonstration breadth gate; unavailable when price/volume coverage is insufficient |
| Fundamental anchor | Rule-based sign and coverage policy; demonstration provenance, not a calibrated quantile |

Exact co-decline and liquidity breadth gates must be frozen in
`UnwindMonitorConfig` and tested before generating production artifacts. They
must not be selected after viewing the target case-study conclusion.

### Scenario-classification contract

Return one of:

```text
normal_drawdown
fundamental_repricing
panic_recovery_momentum_crash
crowded_momentum_unwind
mixed_repricing_and_unwind
insufficient_evidence
```

Recommended rule priority:

1. `insufficient_evidence` when fewer than four rows are available or both
   synchronous liquidation and reversal are unavailable;
2. `mixed_repricing_and_unwind` when the fundamental anchor is deteriorating
   and at least two unwind-mechanism rows trigger;
3. `crowded_momentum_unwind` when concentration, synchronous liquidation, and
   reversal trigger, with breadth or liquidity providing additional support;
4. `panic_recovery_momentum_crash` when the existing Phase 1
   high-volatility-recovery state and cross-sectional reversal trigger but the
   crowded-unwind rule is not met;
5. `fundamental_repricing` when fundamentals deteriorate and breadth weakens
   without more than one unwind-mechanism trigger;
6. `normal_drawdown` otherwise, provided evidence is sufficient.

Each result contains:

- rule identifier and rule text;
- supporting deterministic facts;
- contradictory deterministic facts;
- missing facts;
- completeness confidence: `high` for 6/6 rows, `moderate` for 4–5/6, and
  `insufficient` below that.

Completeness confidence is not a probability.

### Rebound diagnostics

Forward 1-, 3-, and 5-day rebound values must never appear in the live
assessment. Add a separate historical-only function and output with:

```text
evaluation_mode = historical_post_event
event_date
forward_window
long_return
short_underlying_return
long_minus_short_return
data_available_through
```

Tests must prove that `build_unwind_assessment` has no forward-return field and
does not change when observations after the assessment date are perturbed.

### Generated artifacts

Only after implementation approval:

- `data/processed/momentum_breadth_history.parquet`;
- `data/processed/unwind_structure_history.parquet`;
- `outputs/unwind_structure/unwind_scorecard_<date>.csv`;
- `outputs/unwind_structure/unwind_assessment_<date>.json`;
- `outputs/unwind_structure/unwind_audit.json`;
- an exact-date compact fundamental-anchor output when built from auditable
  local Phase 5A inputs.

Do not persist a new historical fundamental panel in the MVP.

### Test plan

New focused tests must cover:

- zero, missing, normalized, and non-normalized exposures;
- gross-normalized effective bets;
- top-3/top-5 exposure and loss-contribution shares;
- sector HHI with missing classifications;
- exact constituent-to-Phase-2 P&L reconciliation;
- overlap, turnover, rank persistence, and holding duration;
- full-universe positive-momentum breadth and prior-rebalance changes;
- future-observation perturbation invariance;
- prior-only quantile leakage;
- lagged-beta residual-return calculation;
- long/short sign conventions and reversal boundaries;
- co-decline and constant/one-name correlation edge cases;
- missing volume, zero dollar volume, and proxy labels;
- absence of future rebound fields from live output;
- fundamental sign voting, EPS optionality, and financial-sector margin
  exclusions;
- exact 8/6 leg coverage boundaries;
- all scenario rule boundaries and priority;
- six-row schema, nullable missing fields, and deterministic repeatability;
- byte- or schema-identical Phase 1–4 artifacts and unchanged Phase 4
  scorecard outputs.

Required verification:

```bash
git diff --check
uv run python -m pytest -q \
  tests/test_concentration.py \
  tests/test_momentum_breadth.py \
  tests/test_fundamental_anchor.py \
  tests/test_unwind_structure.py
uv run python -m pytest
```

### Notebook integration plan

After the new monitor passes independent review:

1. keep the existing Phase 6 parameter cell;
2. call `build_unwind_assessment` with the same `AS_OF_DATE`;
3. add one compact `Momentum Unwind Structure` section containing the six-row
   scorecard, scenario, support/contradiction/missing lists, and limitations;
4. keep the existing Phase 1–4 quantitative table and Evidence Card fields
   unchanged;
5. keep the LLM optional and deterministic facts immutable;
6. do not pass new facts to the LLM in the MVP unless a separately versioned
   interpretation-contract change is approved;
7. extend the smoke test to verify date propagation, null handling, and clean
   HTML rendering.

This gives one notebook experience without silently changing
`deterministic-evidence-input-v1`.

## C. Scope recommendation

### Must-have MVP

- Drifted-exposure effective bets.
- Top-3/top-5 exposure and realized-loss-contribution concentration.
- Current-sector HHI and explicit proxy warnings.
- Long/short holding overlap and turnover.
- Universe positive 12-1 momentum breadth and change.
- Active-long participation and leadership concentration.
- Lagged-beta-adjusted long loss.
- Five-day long/short reversal and decline/rise participation.
- Co-decline share and simple average pairwise correlation.
- Downside abnormal-volume share and optional Amihud context, both labeled
  proxies.
- Exact-date lightweight fundamental anchor or explicit unavailable.
- Separate six-row scorecard and auditable scenario classification.
- Historical-only rebound evaluator with strict live-output exclusion.
- Focused tests, full regression suite, audit outputs, and compact notebook
  integration.

### Nice-to-have

- Rank-reversal diagnostics beyond the existing active long/short groups.
- Current-sector loss context, clearly labeled non-PIT.
- First-principal-component variance only if correlation is demonstrably
  insufficient; no new dependency is needed, but it is not required.
- A recent semiconductor/AI case-study output only after the required dates,
  price/volume coverage, active portfolio, and point-in-time limitations pass
  a separate gate.
- Versioned LLM context that includes the new scorecard after deterministic
  acceptance.

### Explicitly deferred

- Historical point-in-time S&P 500 membership and sector classifications.
- A historical fundamental panel or the old Fundamental Alignment Scorecard.
- Repairing EPS coverage.
- Proprietary leverage, prime-broker, hedge-fund, dealer, 13F, short-interest,
  options-gamma, ETF-flow, or social-media crowding models.
- A full sector/factor attribution model.
- Open/high/low gap and range measures without source data.
- PCA as a default MVP requirement.
- Machine learning, threshold optimization, predictive probability, IC/ICIR,
  trading recommendations, or an LLM-controlled score.
- New datasets, dependencies, website, chatbot, or agent framework.

## D. Execution estimate

Each item is intended to fit one focused Codex Max execution window.

### Session 1 — Freeze contracts; concentration and breadth

- Add the new config and six-row schema tests first.
- Implement drifted-exposure, contribution reconciliation, sector
  concentration, overlap, turnover, and holding-duration functions.
- Implement monthly breadth, breadth change, long participation, and leadership
  concentration.
- Stop if constituent P&L does not exactly reconcile to Phase 2.

Expected production files:
`src/risk/concentration.py`,
`src/features/momentum_breadth.py`.

### Session 2 — Unwind fingerprint and liquidity proxies

- Implement lagged-beta residual long loss.
- Implement five-day reversal, co-decline, correlation, and downside-threshold
  participation.
- Implement downside abnormal-volume share and Amihud context.
- Add prior-only threshold logic and leakage tests.

Expected production file:
`src/monitoring/unwind_structure.py`.

### Session 3 — Fundamental anchor and scenario rules

- Build the lightweight sign-vote anchor over existing Phase 5A facts.
- Enforce accounting exclusions and leg coverage gates.
- Assemble the six-row scorecard.
- Implement scenario classification, evidence lists, completeness confidence,
  and artifacts.
- Confirm clean-clone behavior returns fundamental `unavailable` when required
  local inputs are absent.

Expected production file:
`src/monitoring/fundamental_anchor.py`.

### Session 4 — Historical rebound boundary and notebook integration

- Add the historical-only 1/3/5-day evaluator and prove it cannot enter live
  output.
- Add the compact notebook section without changing the Phase 6 v1 schemas.
- Extend the read-only smoke test.
- Do not run the semiconductor case study unless separately approved after a
  data-availability check.

Expected modified files:
`notebooks/03_pm_evidence_card_demo.ipynb`,
`src/mvp/demo_smoke_test.py`,
`tests/test_demo_smoke_test.py`.

### Session 5 — QA, artifacts, and review

- Run focused and full suites.
- Run notebook execution on a normal date, a known stress date, a missing
  fundamental-anchor date, and the exact Phase 5A date where upstream coverage
  permits.
- Verify Phase 1–4 artifacts and Phase 4 scorecards are unchanged.
- Generate deterministic audit outputs.
- Write `docs/phase_reviews/phase_5_unwind_monitor_review.md` and
  `docs/handoff_phase5_unwind.md`.

Production implementation began only after the operator approved this plan.

## Planning-gate verification

This review changed documentation only.

Read-only focused regression run:

```text
77 passed
```

The run covered the existing Phase 2 portfolio, Phase 3 leg decomposition,
Phase 4 scorecard, Phase 5A SEC feasibility, and Phase 6 deterministic card
contracts. The working tree was clean before this document was added.

## Session 1 implementation record

Implemented:

- `src.risk.concentration.effective_bets`;
- `src.risk.concentration.top_absolute_share`;
- `src.risk.concentration.sector_concentration`;
- `src.risk.concentration.build_constituent_return_history`;
- `src.risk.concentration.build_concentration_history`;
- `src.risk.concentration.build_rebalance_diagnostics`;
- `src.features.momentum_breadth.summarize_momentum_snapshot`;
- `src.features.momentum_breadth.build_momentum_breadth_history`.

The implementation did not modify Phase 2. The new constituent history
reconstructs its published month-start weights and within-month drift for
inspection, and a regression check reconciles the new constituent
contributions back to the existing daily leg returns.

Full-artifact read-only verification:

| Check | Result |
|---|---:|
| Constituent rows | 47,300 |
| Reconciled daily dates | 2,365 |
| Maximum long contribution error | `2.78e-17` |
| Maximum short contribution error | `2.78e-17` |
| Maximum portfolio return error | `2.78e-17` |
| Concentration history rows | 2,365 |
| Effective-bets observed range | 16.5162 to 20.0000 |
| Breadth history rows | 114 |
| Positive 12-1 breadth observed range | 23.53% to 96.50% |

Focused and adjacent regression result after Session 1:

```text
88 passed
```

Full repository regression result:

```text
264 passed, 4 skipped
```

No processed artifact, threshold, scorecard, notebook, dependency, or Phase
1–4 business rule changed.

## Session 2 implementation record

Implemented in `src.monitoring.unwind_structure`:

- `UnwindMonitorConfig`;
- `build_leg_unwind_history`;
- `average_pairwise_correlation`;
- `build_constituent_unwind_history`;
- `build_unwind_fingerprint_history`;
- `prior_only_quantile`;
- `build_unwind_fingerprint_snapshot`.

The long-leg residual uses the previous day's 126-day realized beta:

```text
beta_adjusted_long_return_5d =
    compounded_long_return_5d
    - sum(lagged_long_beta_126d * benchmark_return over five days)
```

Cross-sectional reversal preserves the Phase 2 sign convention:

```text
short_minus_long_return_5d =
    short_underlying_return_5d - long_return_5d
```

The constituent layer adds:

- active-long five-day decline share;
- active-short five-day rise share;
- active-long downside-threshold breach share;
- active-long 21-day average pairwise correlation;
- change from its strictly prior 63-day median;
- downside abnormal-volume share using a per-name prior-only volume threshold;
- median Amihud proxy when positive dollar volume is available.

Missing volume or dollar volume leaves liquidity fields unavailable without
removing price-based decline and correlation diagnostics. Every liquidity
output and warning is explicitly labeled as a proxy.

The combined history has 2,365 daily rows from 2017-02-01 through 2026-06-30.
Observed availability:

| Metric | Available rows |
|---|---:|
| Residual long loss | 2,298 |
| Long pairwise correlation | 2,365 |
| Downside abnormal-volume proxy | 2,365 |

Representative read-only snapshots were built for 2020-03-24, 2024-01-05,
and 2026-05-29. Security-derived thresholds were labeled
`historical_proxy_threshold`; the co-decline and liquidity breadth gates were
labeled `demo_threshold`. No conclusion was hard-coded for any date.

Session 2 verification:

```text
focused and adjacent tests: 49 passed
full repository suite: 274 passed, 4 skipped
git diff --check: passed
```

No scorecard artifact, scenario classification, notebook integration, new
dataset, or dependency was added in Session 2.

## Sessions 3–5 completion record

Implemented:

- lightweight, coverage-gated `FundamentalAnchor`;
- six validated `UnwindScorecardRow` objects and `UnwindAssessment`;
- auditable scenario priority rules and completeness confidence;
- historical-only 1/3/5-day rebound evaluation;
- deterministic artifact runner and CLI;
- compact `Momentum Unwind Structure` notebook section;
- embedding of the scorecard in the final HTML Evidence Card;
- smoke-test checks for date propagation and the six-row contract.

The default interactive path does not parse the complete SEC cache. Exact-date
coverage can be supplied explicitly or generated with the opt-in
`--parse-fundamentals` CLI flag. Without it, the fundamental row remains
unavailable and the remaining monitor stays usable.

The 2024-01-05 notebook demonstration produced:

```text
Phase 1–4 state: bear_low_volatility
Phase 5 scenario: normal_drawdown
Phase 5 completeness: moderate
Phase 5 triggered row: synchronous_winner_liquidation
Phase 5 missing row: fundamental_anchor
LLM requested/effective: False/False
```

The original drawdown, recovery-from-trough, and 21-day volatility components
remain separately visible beneath their high-volatility-recovery composite.

Final verification:

```text
focused Phase 5 + smoke suite: 32 passed
full repository suite: 284 passed, 4 skipped
executed notebook error outputs: 0
git diff --check: passed
```

See `docs/phase_reviews/phase_5_unwind_monitor_review.md` for the production
review and `docs/handoff_phase5_unwind.md` for commands and operational notes.
