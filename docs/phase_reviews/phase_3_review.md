# Phase 3 review: long/short risk decomposition

Date: 2026-07-27

Status: complete, awaiting phase review

## Objective

Decompose the security-level momentum portfolio into transparent realized
long- and short-leg risk:

- unconditional and conditional beta;
- short-minus-long beta gap;
- leg and portfolio volatility;
- signed long and short contribution;
- portfolio drawdown;
- short-leg losses during early, high-volatility recoveries.

The module is descriptive and deterministic. It does not add a threshold or
risk score; those belong to Phase 4.

## Files created or modified

Created:

- `src/risk/leg_decomposition.py`
- `tests/test_leg_decomposition.py`
- `data/processed/sp500_benchmark.parquet`
- `data/processed/leg_risk_history.parquet`
- `data/processed/recovery_attribution.parquet`
- `data/raw/sp500/benchmark_acquisition_report.json`
- `outputs/risk/leg_risk_audit.json`
- `outputs/risk/leg_risk_2020-03-24.csv`
- `outputs/risk/leg_risk_2026-06-30.csv`
- `outputs/risk/recovery_attribution.csv`
- `docs/phase_reviews/phase_3_review.md`

Modified:

- `.gitignore`
- `src/data/sp500.py`
- `src/portfolio/momentum.py`
- `tests/test_momentum_portfolio.py`
- `docs/phase_reviews/phase_2_review.md`
- `docs/phase_reviews/README.md`
- regenerated Phase 2 portfolio returns and audit artifacts

## Phase 2 prerequisite correction

The pre-audit found that Phase 2 had reapplied equal weights every day. This
was an implicit daily rebalance, inconsistent with the monthly-rebalance
contract.

The corrected implementation:

1. sets each leg to gross-one equal weights at the start of the month;
2. lets constituent weights drift with relative wealth;
3. resets to equal weights only at the next monthly rebalance;
4. marks the remainder of a month unavailable after any missing constituent
   return, because the subsequent drift path cannot be known.

The correction changed 2,252 of 2,365 daily returns. The annualized tracking
error relative to the daily-rebalanced convention was 3.82%, so this was a
necessary economic correction rather than a cosmetic implementation detail.

## Benchmark

The primary beta benchmark is SPY:

- Yahoo Finance split- and dividend-adjusted close;
- 2,655 rows from 2016-01-04 through 2026-07-27;
- all 2,365 portfolio-return dates covered;
- status `primary_spy_total_return_proxy`.

SPY is an investable ETF total-return proxy. It is not the official S&P 500
cash index or official index total-return series. If the processed SPY series
is unavailable, the module falls back to the existing Ken French broad-US
market total-return proxy and labels that branch explicitly.

## Metric definitions

### Realized beta

For asset or leg return `r` and benchmark return `m`:

```text
beta = covariance(r, m) / variance(m)
```

- trailing window: 126 trading observations;
- minimum complete observations: 63;
- zero benchmark variance: unavailable;
- long beta uses the long underlying basket;
- short beta uses the short underlying basket before its portfolio sign;
- portfolio beta uses `long_return - short_underlying_return`;
- beta gap is `short_underlying_beta - long_beta`.

The implementation verifies:

```text
portfolio_beta = long_beta - short_underlying_beta
```

within floating-point tolerance.

### Conditional beta

The same trailing 126 observations are filtered by benchmark sign:

- up beta: `benchmark_return > 0`;
- down beta: `benchmark_return < 0`;
- zero-return days are excluded;
- at least 30 qualifying observations are required for each direction.

Observation counts are stored with the metrics. An insufficient conditional
sample stays null.

### Volatility and contributions

- long, short-underlying, and portfolio volatility are 21-day realized
  standard deviations annualized by `sqrt(252)`;
- 21-day contributions are arithmetic sums of daily signed contributions;
- arithmetic contribution is used because it reconciles exactly;
- the module does not present leg arithmetic contributions as independently
  compounded returns.

### Recovery attribution

Contiguous Phase 1 `early_recovery_state` observations form an episode.
For each episode the output records:

- trading days and high-volatility-recovery days;
- long net contribution;
- short net contribution;
- portfolio net contribution;
- magnitude of negative long and short daily contributions;
- short share of gross leg losses;
- minimum portfolio drawdown.

Short loss magnitude is:

```text
sum(max(-short_contribution, 0))
```

This captures days on which the underlying short basket rallied and the short
position lost money.

## Data and output coverage

| Item | Result |
|---|---:|
| Risk-history rows | 2,365 |
| First date | 2017-02-01 |
| Last date | 2026-06-30 |
| Benchmark-covered rows | 2,365 |
| Beta-available rows | 2,303 |
| Early-recovery episodes | 14 |
| Maximum daily contribution error | `2.78e-17` |
| Maximum 21-day contribution error | `1.39e-16` |

The corrected historical portfolio has a cumulative return of 609.98% and a
maximum drawdown of -53.96%. These are not strategy-performance claims:
membership is the 2026 current snapshot applied historically, costs and
financing are absent, and gross exposure is two.

## Representative result: 2020-03-24

| Metric | Value |
|---|---:|
| Long beta, 126d | 1.238 |
| Short-underlying beta, 126d | 1.293 |
| Short-minus-long beta gap | +0.055 |
| Portfolio beta | -0.055 |
| Long up beta | 1.161 |
| Short-underlying up beta | 1.273 |
| Long down beta | 1.264 |
| Short-underlying down beta | 1.343 |
| Long volatility, 21d annualized | 114.42% |
| Short-underlying volatility, 21d annualized | 124.29% |
| Portfolio volatility, 21d annualized | 51.49% |
| Long contribution, prior 21d | -28.19% |
| Short contribution, prior 21d | +45.48% |
| Portfolio contribution, prior 21d | +17.30% |

The day was both an early recovery and a high-volatility recovery. The beta
gap was positive: the recent-loser short basket was modestly higher beta and
more volatile than the long basket.

For the contiguous 2020-03-24 through 2020-06-22 recovery episode:

| Metric | Arithmetic contribution |
|---|---:|
| Long net contribution | +52.77% |
| Short net contribution | -80.41% |
| Portfolio net contribution | -27.64% |
| Short loss magnitude | 182.78% |
| Long loss magnitude | 51.19% |
| Short share of gross leg losses | 78.12% |
| Minimum portfolio drawdown | -50.77% |

Loss magnitudes sum negative daily contributions and can exceed 100%; they are
not compounded investment returns.

This is direct support for the intended mechanism: once the stressed recovery
became sustained, losses were dominated by the short leg rallying.

## Latest result: 2026-06-30

| Metric | Value |
|---|---:|
| Long beta, 126d | 2.746 |
| Short-underlying beta, 126d | 0.407 |
| Short-minus-long beta gap | -2.339 |
| Portfolio beta | +2.339 |
| Long volatility, 21d annualized | 81.56% |
| Short-underlying volatility, 21d annualized | 46.76% |
| Portfolio volatility, 21d annualized | 110.03% |
| Long contribution, prior 21d | +12.84% |
| Short contribution, prior 21d | +11.84% |
| Portfolio contribution, prior 21d | +24.68% |
| Portfolio drawdown | -10.50% |

The current security-level risk is long-leg dominated, not a classic
high-beta short-leg setup. This is economically useful because it shows that a
large momentum risk reading need not imply the Daniel–Moskowitz junk-rally
mechanism.

Phase 1 regime data currently end on 2026-05-29, so the 2026-06-30 recovery
flags are unavailable. The leg result alone cannot establish the overall
current risk state.

## Aggregate recovery finding

Across the 14 early-recovery episodes available in the portfolio sample:

- short loss magnitude: 4.717 arithmetic return units;
- long loss magnitude: 1.446;
- short share of gross leg losses: 76.54%.

This is descriptive, same-sample evidence and inherits the current-constituent
bias. It is not a calibrated probability or an independently validated
strategy result.

## Tests

Phase 1–3 targeted suite:

- 21 passed.

Full repository suite:

- 172 passed;
- 4 skipped for the existing raw-payload prerequisites.

Phase 2 and Phase 3 tests cover:

- month-start equal weights and intra-month drift;
- exact beta identities and beta-gap sign;
- up/down benchmark filtering;
- missing conditional samples;
- future-data perturbation invariance;
- signed short loss and recovery attribution;
- contribution reconciliation;
- SPY adjusted-close return construction.

The corrected portfolio returns, risk history, recovery attribution, and audit
JSON were regenerated twice; all four SHA-256 hashes were identical.

## Engineering and research lessons

### 1. Economic conventions need tests

Date alignment and weight sums can both pass while the rebalance frequency is
wrong. The explicit two-stock drift test now proves the monthly convention.

### 2. Short underlying risk and signed short P&L are different objects

Short beta is measured on the underlying loser basket. P&L contribution has
the opposite sign. Mixing them would invert the mechanism interpretation.

### 3. Beta gap identifies which leg carries market sensitivity

A positive gap in March 2020 identified a more market-sensitive short basket.
The strongly negative gap in June 2026 identifies a long-leg-dominated
portfolio. A generic portfolio beta would obscure that distinction.

### 4. Recovery attribution is more informative than one-day P&L

On 2020-03-24 the prior 21-day short contribution was positive because the
crash had hurt the underlying losers. Across the subsequent recovery episode,
the short contribution became strongly negative. The monitor needs both the
current trailing state and the recovery-window path.

### 5. Arithmetic attribution must be labeled

Signed daily contributions reconcile exactly when summed. Compounding each leg
separately would not add back to compounded long-short performance.

## Limitations

- All portfolio results inherit the frozen current-membership bias.
- SPY and constituent adjusted prices are public-vendor research data and may
  contain later corrections.
- Beta is realized and backward-looking, not an ex-ante risk estimate.
- Monthly holdings can change inside a 126-day beta window; the beta describes
  the realized portfolio path, not a fixed basket.
- Conditional beta estimates use as few as 30 sign-filtered observations.
- Regime state and SPY beta use different broad-market proxies.
- Recovery episodes can fragment when a daily threshold toggles; Phase 1
  already identified possible persistence/hysteresis as future research.
- Transaction costs, borrow, financing, capacity, and taxes remain absent.
- Extreme current names and corporate actions still require dedicated data
  quality review.

## Consequence for Phase 4

Phase 4 can consume deterministic rows for:

- long beta;
- short-underlying beta;
- beta gap;
- portfolio beta;
- long, short, and portfolio volatility;
- portfolio drawdown;
- short loss magnitude and short share of recovery losses.

Thresholds must remain separate from these measurements and identify
historical-quantile or demonstration provenance. A missing June macro state
must remain missing rather than being interpreted as low risk.
