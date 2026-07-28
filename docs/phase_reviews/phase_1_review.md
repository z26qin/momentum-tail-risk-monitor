# Phase 1 review: deterministic macro regime monitor

Date: 2026-07-27

Status: complete, awaiting phase review

## Objective

Create a deterministic, point-in-time macro monitor that distinguishes:

- severe market drawdown;
- crash conditions;
- early recovery;
- high-volatility recovery;
- ordinary recovery;
- the existing DM bear/panic state;
- a simple interest-rate regime.

The important research requirement was to test whether recovery alone differs
from a high-volatility recovery associated with momentum crash risk.

## Files created

- `src/regime/__init__.py`
- `src/regime/market_state.py`
- `tests/test_market_regime.py`
- `outputs/regime/regime_state_2020-03-24.csv`

The existing `src.pipeline` and DM engine were not modified.

## Reused components

- `mkt_total_return` and `rf` from the processed Ken French research factors;
- the existing 504-day compounded market return helper;
- `src.risk.dm_engine.build_state_history`;
- existing as-of parsing and atomic output utilities;
- the repository's future-data perturbation and deterministic replay testing
  patterns.

No new external data source was introduced.

## Deterministic rules

| Dimension | Rule | Provenance |
|---|---|---|
| Severe drawdown | Broad-market total-return wealth is at least 20% below its prior peak | Demo threshold |
| Recent severe drawdown | Minimum drawdown in the prior 126 trading days is at most -20% | Demo threshold |
| Recovery | At least 5% above the lowest market wealth in the prior 126 trading days | Demo threshold |
| Early recovery | Recent severe drawdown, recovery of at least 5%, and trough age of 1–63 trading days | Composite demo rule |
| Realized volatility | Annualized standard deviation of the prior 21 daily market returns | Deterministic calculation |
| High volatility | Realized volatility is above the PIT 80th percentile of prior observations | Historical quantile |
| Crash state | Current drawdown is at most -20% and volatility is high | Composite demo rule |
| High-volatility recovery | Early recovery and high volatility are both true | Composite demo rule |
| DM bear | Trailing 504-day broad-market return is negative | Daniel–Moskowitz structure |
| DM panic | Bear state and 126-day variance at least its expanding PIT bear-state mean | Existing documented operationalization |
| Rate regime | 63-day change in annualized 21-day `rf`; ±25 bp maps to tightening/easing | Demo threshold |
| Liquidity | Unavailable | No reliable existing series |

The volatility threshold uses only observations before the current row.

## Output contract

Each row contains:

- `as_of_date`
- `metric`
- `value`
- `threshold`
- `threshold_provenance`
- `state`
- `triggered`
- `explanation`
- `source_module`

The liquidity row carries null value, null threshold, and null trigger rather
than a false signal.

## Representative result: 2020-03-24

| Metric | Value | Threshold/state | Triggered |
|---|---:|---|---:|
| Market drawdown | -28.07% | -20% | Yes |
| Recovery from 126-day trough | +9.35% | +5% | Yes |
| 21-day annualized realized volatility | 91.26% | PIT threshold 17.83% | Yes |
| DM trailing 504-day market return | -5.01% | Bear below 0% | Yes |
| DM panic intensity | 2.255 | Threshold 1.0 | Yes |
| Crash state | — | Crash | Yes |
| Early recovery | — | Early recovery | Yes |
| High-volatility recovery | — | High-volatility recovery | Yes |
| Rate proxy | 0 bp change | Stable | No |
| Liquidity | — | Unavailable | — |

The transition is economically interpretable:

- 2020-03-16 was a crash/high-volatility state without recovery;
- 2020-03-24 was still in a severe drawdown but had rebounded 9.35% from the
  recent trough, so early recovery and high-volatility recovery both triggered.

## Historical diagnostic

This diagnostic joins the point-in-time regime history to the existing matured
PIT fifth-percentile momentum tail-loss labels from 1990 onward.

| State | Future 5-day tail-loss rate | Future 20-day tail-loss rate |
|---|---:|---:|
| All observations | 7.42% | 6.86% |
| Ordinary recovery | 6.30% | 4.72% |
| High-volatility recovery | 29.59% | 27.65% |
| DM panic | 33.61% | 35.29% |
| Neither high-volatility recovery nor DM panic | 4.91% | 4.19% |

Post-1990 state coverage:

| State | Trading days | Share | State episodes |
|---|---:|---:|---:|
| Crash | 860 | 9.38% | 47 |
| Early recovery | 1,028 | 11.21% | 62 |
| High-volatility recovery | 774 | 8.44% | 65 |
| DM panic | 476 | 5.19% | 10 |

These are descriptive historical results, not independently validated
probability forecasts.

## Main research finding

Recovery alone is not a useful danger signal. Ordinary recoveries have tail-
loss rates close to or below the unconditional rate.

The combination of a recent severe drawdown, a rebound from the trough, and
persistently high volatility is materially more informative. In this
historical diagnostic, five- and twenty-day momentum tail-loss frequencies are
about four times their unconditional rates.

The macro monitor is therefore useful as a first-stage risk gate:

- it identifies when the market environment is compatible with a momentum
  crash mechanism;
- it should not make the final risk decision by itself;
- the portfolio phases must determine whether the current short leg is
  actually high-beta, distressed, low-quality, crowded, or rapidly rebounding.

## Engineering and research lessons

### 1. The recovery interaction matters

A single recovery flag would generate the wrong interpretation. Requiring
recent severe drawdown and high volatility separates ordinary normalization
from a stressed rebound.

### 2. DM remains useful but is narrower

DM panic is historically more selective and has a higher conditional tail-loss
rate than the new high-volatility-recovery state. It should remain a core macro
dimension rather than being replaced.

### 3. The new recovery state is intentionally more sensitive

High-volatility recovery covers 8.44% of post-1990 days and appears in 65
state episodes, versus 10 DM panic episodes. Daily thresholds can create
short state fragments. A later reporting layer may need deterministic
persistence or hysteresis, but Phase 1 does not add it without validation.

### 4. The rate proxy is weak

The Ken French daily risk-free rate is rounded and is not a policy-rate
release series. It is acceptable as a coarse regime descriptor but should not
be treated as a precise central-bank signal. On 2020-03-24 it remained stable
under the selected 63-day comparison.

### 5. Not inventing liquidity is the correct result

GDELT attention and FINRA short-sale data are not macro liquidity measures.
Leaving liquidity unavailable is more defensible than adding an ambiguous
proxy to satisfy a schema.

### 6. Historical event rates are not alert probabilities

Forward label windows overlap, and the rules were assessed on the same
historical record. The large conditional-rate differences establish economic
usefulness for monitoring, not production calibration or tradability.

## Tests

Phase 1 targeted suite:

- 6 passed.

Full repository suite after implementation:

- 157 passed;
- 4 skipped for the existing raw-payload prerequisites.

Tests cover:

- synthetic normal → crash → high-volatility-recovery transitions;
- invariance to source changes after the assessment date;
- exact repeatability for a fixed date;
- required output schema;
- the 2020 crash/recovery transition;
- explicit null treatment for unavailable liquidity;
- byte-identical repeated CSV generation.

## Limitations

- The market input is the Ken French broad US market total-return proxy, not
  the S&P 500.
- The -20%, +5%, 63-day, and ±25 bp boundaries are labeled demo thresholds.
- The expanding volatility threshold is historically adaptive and is not a
  production alert calibration.
- The monitor contains no security holdings, long/short beta, quality,
  distress, breadth, or concentration information.
- It is not yet connected to the active pipeline.

## Consequence for Phase 2

Phase 2 must test whether the macro precondition is confirmed by the actual
synthetic portfolio. In particular, it must produce named long and short
holdings and correctly aligned post-formation returns so later phases can
measure whether high-volatility recovery is accompanied by a genuine
short-leg junk rally.
