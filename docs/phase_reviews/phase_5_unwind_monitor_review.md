# Phase 5 unwind monitor review

Date: 2026-07-29

Status: implemented, integrated, and regression-tested

## Decision

Phase 5 is now a separate deterministic monitor for:

1. portfolio concentration;
2. momentum breadth deterioration;
3. synchronous winner liquidation;
4. cross-sectional reversal;
5. liquidity amplification proxies;
6. a lightweight fundamental anchor.

It supplements rather than replaces the frozen Phase 1–4 risk state. It does
not modify the Phase 4 four-row scorecard or the version-1 Phase 6 serialized
contracts, and it does not average the six rows into a probability.

The primary public entry point is:

```python
src.monitoring.unwind_structure.build_unwind_assessment(
    as_of_date=...,
) -> UnwindAssessment
```

The default path is safe for an interactive demo. It does not parse the full
SEC Company Facts cache. Exact-date company coverage may be supplied directly,
or the caller may explicitly opt into the slower local parse with
`load_fundamentals=True`. Otherwise, the fundamental row is nullable and
reported as unavailable.

## Reused repository components

| Existing component | Reuse |
|---|---|
| `src.portfolio.momentum.build_momentum_signals` | Authoritative 12-1 momentum values, eligible universe, and ranks |
| `momentum_portfolio_holdings.parquet` | Phase 2 long 10 / short 10 membership, ranks, weights, and formation dates |
| `momentum_portfolio_returns.parquet` | Authoritative long, short-underlying, and long-short return convention |
| `src.risk.leg_decomposition.build_leg_risk_history` output | Benchmark returns, lagged long beta, formation date, and Phase 1 regime |
| `src.regime.market_state.build_regime_history` output | Drawdown, recovery, volatility, and high-volatility-recovery state |
| `src.data.sec_fundamentals` | Filing-date-aware Phase 5A values, accounting exclusions, and coverage gates |
| `src.data.sec_edgar.fetch_ticker_map` | Existing cache and ticker-to-CIK mapping |
| `src.data.sp500.classification_snapshot_from_nasdaq` | Current sector/industry proxy |
| `src.mvp.evidence_card.build_deterministic_evidence_input` | Existing Phase 1–4 Evidence Card path, unchanged contract |

## New implementation

### Concentration and portfolio fragility

`src.risk.concentration` exposes:

- `effective_bets`;
- `top_absolute_share`;
- `sector_concentration`;
- `holding_overlap`;
- `build_constituent_return_history`;
- `build_concentration_history`;
- `build_rebalance_diagnostics`.

The useful effective-bets measure uses gross-normalized, drifted,
beginning-of-day absolute exposure:

```text
effective_bets = 1 / sum(normalized_absolute_exposure_i ^ 2)
```

Exposure concentration and realized contribution concentration remain
separate. The reconstructed daily constituent contributions reconcile to the
Phase 2 long, short, and portfolio returns with a maximum observed error of
`2.78e-17`.

Sector HHI and sector shares use current classifications and are labeled as
non-point-in-time proxies.

### Momentum breadth

`src.features.momentum_breadth` exposes:

- `summarize_momentum_snapshot`;
- `build_momentum_breadth_history`.

The compact monthly output contains:

- eligible-universe positive 12-1 momentum share;
- change from the previous rebalance;
- change from the prior three-rebalance high;
- active-long 21-day participation;
- positive-momentum leadership HHI and top-10 share;
- cross-sectional momentum dispersion;
- long-leg entries, exits, and overlap.

It calls the existing Phase 2 momentum calculation rather than reimplementing
the signal.

### Unwind fingerprint

`src.monitoring.unwind_structure` exposes:

- `UnwindMonitorConfig`;
- `build_leg_unwind_history`;
- `average_pairwise_correlation`;
- `build_constituent_unwind_history`;
- `build_unwind_fingerprint_history`;
- `prior_only_quantile`;
- `build_unwind_fingerprint_snapshot`;
- `build_unwind_assessment`;
- `evaluate_historical_rebound`;
- `run_unwind_assessment`.

The five-day beta-adjusted long-leg loss uses the previous day's published
126-day beta:

```text
beta_adjusted_long_return_5d
    = compounded_long_return_5d
    - sum(lagged_long_beta_126d * benchmark_return)

residual_long_loss_5d = -beta_adjusted_long_return_5d
```

Cross-sectional reversal preserves the Phase 2 short-underlying sign:

```text
short_minus_long_return_5d
    = short_underlying_return_5d - long_return_5d
```

Synchronous selling also exposes active-long decline share, downside breach
share, 21-day average pairwise correlation, and its change from a strictly
prior 63-day median.

The liquidity row uses downside abnormal-volume breadth and median Amihud
context. Both are public-data proxies. They are not direct evidence of
leverage, financing stress, or forced liquidation.

### Fundamental anchor

`src.monitoring.fundamental_anchor` exposes:

- `FundamentalAnchor`;
- `build_company_fundamental_states`;
- `build_fundamental_anchor`;
- `build_exact_date_company_coverage`;
- `build_fundamental_anchor_for_date`;
- `unavailable_fundamental_anchor`.

The anchor uses signs, not averages across unlike accounting units. A company
requires at least two valid measures among revenue acceleration, operating
margin change, and optional EPS acceleration. Existing Phase 5A
financial-sector and REIT margin exclusions remain in force.

The portfolio anchor requires at least six covered long names and six covered
short names:

- `supportive`: long support is at least 60% and improving shorts are below
  40%;
- `deteriorating`: long support is at most 40% or improving shorts are at
  least 60%;
- `mixed`: sufficient coverage but neither rule holds;
- `unavailable`: insufficient or absent exact-date input.

The anchor never blocks the other five rows.

## Scorecard contract

`UnwindAssessment.scorecard` contains exactly six ordered
`UnwindScorecardRow` objects. Each row includes:

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

Unavailable values remain `null`. They do not become zero, false, or safe.

Threshold provenance is one of:

- `literature`;
- `historical_quantile`;
- `historical_proxy_threshold`;
- `demo_threshold`;
- `insufficient_history`.

All calculated quantiles exclude the selected date and all future dates.

## Scenario v2 rules

`classify_momentum_crash_scenarios` evaluates three independent, potentially
simultaneous mechanisms. It does not force them through a priority tree:

1. `bear_market_recovery_crash` requires a recent severe broad-market
   drawdown, a rapid recovery from the trough, and high realized volatility.
   Drawdown, recovery, and volatility remain three separate displayed
   conditions.
2. `short_book_reversal_crash` requires the prior-only extreme
   short-underlying-minus-long return and at least 70% of the active short
   underlyings to rise over five trading days. Signed short beta is retained as
   optional context, not a hard gate.
3. `crowded_theme_unwind` requires a correlated active-long cluster defined
   through `t-1`, extreme cluster residual loss, at least 70% cluster decline
   breadth, and either at least 50% of active-long losses or abnormal volume
   concentrated in the cluster.

Each returns `triggered`, `watch`, `not_confirmed`, or `unavailable`, with
condition-level supporting, contradictory, and missing evidence. Multiple
mechanisms may trigger on one date. No scenario is a probability.

The six scorecard rows are unchanged. `classify_unwind_scenario` and
`scenario_classification` remain as a deliberately lossy v1 compatibility
view; v2 consumers use `mechanism_scenarios` and `active_scenarios`.

## Correlated-theme proxy

`src.risk.theme_concentration.build_theme_concentration_snapshot` uses only
existing repository artifacts:

- the active Phase 2 long book;
- split- and dividend-adjusted security prices;
- the existing SPY benchmark return;
- public volume and dollar volume;
- current sector classifications.

The cluster uses 63 trading days of benchmark-demeaned returns ending at
`t-1`. The correlation cutoff is the greater of 0.50 and the pre-event
cross-sectional 75th percentile. A deterministic all-pairs clique prevents
weak chain links from merging unrelated names. Event loss, decline breadth,
loss contribution, abnormal volume, and Amihud are measured through `t`.

The output is explicitly labeled `correlated_theme_proxy`. It is not observed
common ownership, leverage, financing pressure, order flow, or forced selling.
The existing universe has sector but no industry classification, so industry
concentration remains unavailable rather than fabricated.

The existing drawdown, recovery-from-trough, and realized-volatility
components remain visible individually in the notebook even though they
jointly determine the high-volatility-recovery state.

## Historical rebound boundary

`evaluate_historical_rebound` calculates forward 1-, 3-, and 5-trading-day
long, short-underlying, and long-minus-short returns for historical evaluation
only. Each record is labeled `historical_post_event`.

No forward-return field exists in `UnwindAssessment`, the live scorecard, or
the notebook's selected-date assessment.

## Generated artifacts

For the validated 2024-01-05 run:

- `data/processed/momentum_breadth_history.parquet`;
- `data/processed/unwind_structure_history.parquet`;
- `outputs/unwind_structure/unwind_scorecard_2024-01-05.csv`;
- `outputs/unwind_structure/unwind_assessment_2024-01-05.json`;
- `outputs/unwind_structure/unwind_audit.json`.

The two processed histories are deterministic derivatives of existing Phase
1–3 artifacts. No new market dataset was acquired.

## Notebook integration

`notebooks/03_pm_evidence_card_demo.ipynb` calls
`build_unwind_assessment` using the same `AS_OF_DATE` as the existing Evidence
Card. It renders:

- the three independent v2 mechanism states and condition evidence;
- correlated-theme cluster symbols and the `t-1` definition cutoff;
- the legacy single-label compatibility view and completeness;
- the six-row scorecard;
- supporting, contradictory, and missing evidence;
- public-data limitations.

The same content is embedded in the final HTML Evidence Card. The LLM is not
given control of these fields and the notebook remains functional with
`USE_LLM=False`.

## Validated demonstration

The notebook was executed in place with:

```text
AS_OF_DATE = "2024-01-05"
COMPARE_TO_DATE = "2023-12-01"
THRESHOLD_PROFILE = "default"
USE_LLM = False
```

Observed Phase 5 result:

| Row | Current | Threshold | Result |
|---|---:|---:|---|
| Portfolio concentration | 19.9287 effective bets | 19.7936 | not triggered |
| Momentum breadth deterioration | 64.24% | 51.32% | not triggered |
| Synchronous winner liquidation | 3.12% residual loss | 1.82% | triggered |
| Cross-sectional reversal | 2.71% | 3.34% | not triggered |
| Liquidity amplification proxy | 20.00% | 50.00% | not triggered |
| Fundamental anchor | unavailable | coverage-gated rule | unavailable |

The v2 mechanism results are:

- `bear_market_recovery_crash`: `watch` because recovery is present while
  severe recent drawdown and high volatility are not;
- `short_book_reversal_crash`: `not_confirmed`;
- `crowded_theme_unwind`: `not_confirmed`, with no qualifying pre-event
  all-pairs cluster.

The retained v1 compatibility result is `normal_drawdown` with `moderate`
evidence completeness. This is not a statement that the date was safe. The
separate synchronous-winner-liquidation input is triggered, while none of the
three complete crash mechanisms is confirmed.

Two additional date checks confirm that the mechanisms are not aliases:

- `2020-03-24` triggers only `bear_market_recovery_crash`;
- `2026-05-29` triggers only `crowded_theme_unwind`, using the `CIEN`, `COHR`,
  and `LITE` cluster defined through `2026-05-28`.

## Verification

Final QA counts are recorded in `docs/handoff_phase5_unwind.md` after the full
suite and notebook execution.

No dependency, Phase 1–4 business rule, Phase 4 scorecard schema, or Phase 6
version-1 schema was changed.

## Limitations and non-goals

- Historical membership and classifications remain current-snapshot proxies.
- The Phase 2 portfolio is an equal-weight monthly long 10 / short 10 research
  portfolio, not observed manager holdings.
- Close and volume cannot identify order flow, financing, or the identity of
  sellers.
- The liquidity row is a proxy, not proof of deleveraging.
- The fundamental anchor is unavailable without exact-date local coverage;
  parsing all 497 cached Company Facts payloads is intentionally outside the
  live notebook path.
- Historical rebound uses future observations and is never a live feature.
- Correlated-theme history is a behavior proxy and cannot establish crowded
  ownership or deleveraging.
- Industry classification is absent from existing data.
- No semiconductor case study, new dataset, model retraining, threshold
  optimization, predictive probability, website, or LLM-controlled score was
  added.
