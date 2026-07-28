# Phase 4 review: minimal deterministic scorecard

Date: 2026-07-28

Status: complete, awaiting phase review

## Objective

Turn the Phase 1 macro state and Phase 3 leg-risk history into one auditable
deterministic scorecard without repeating every diagnostic as a separate
alert.

The reviewed scope was simplified to exactly four risk decisions:

1. high-volatility recovery;
2. short-underlying minus long beta gap;
3. long-short portfolio drawdown;
4. short-leg loss magnitude during early recovery.

Drawdown, recovery, volatility, long beta, short beta, and portfolio beta are
still retained in their source histories and included as scorecard context.
They are not duplicate alert rows. The scorecard does not produce an averaged
score or risk probability.

## Files created or modified

Created:

- `src/monitoring/scorecard.py`
- `tests/test_scorecard.py`
- `outputs/scorecard/scorecard_2020-03-24.csv`
- `outputs/scorecard/scorecard_2026-05-29.csv`
- `outputs/scorecard/scorecard_2026-06-30.csv`
- `outputs/scorecard/scorecard_audit.json`
- `docs/phase_reviews/phase_4_review.md`

Modified:

- `docs/confirmed_design.md`
- `docs/development_plan.md`
- `docs/phase_reviews/README.md`

The old `src/mvp/contracts.py` and probability-led pipeline were not changed.
Phase 4 is an independent deterministic contract.

## Reused implementation and data

- `src.regime.market_state.build_regime_history` supplies the Phase 1 macro
  gate and its underlying diagnostic values.
- `data/processed/leg_risk_history.parquet` supplies Phase 3 beta,
  contribution, and drawdown facts.
- atomic CSV and deterministic JSON writers in `src.utils.io` preserve the
  repository's output conventions.
- comparator, schema-validation, missing-value, and future-perturbation test
  patterns were reused from the existing monitoring tests.

## Serialized contract

Every assessment contains exactly four rows and the following columns:

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
```

`triggered` uses Pandas nullable Boolean semantics. If an input or activation
gate is unavailable, the trigger is null, `status=unavailable`, and
`severity=unavailable`. Missing never becomes `False`.

Available rows have only two severities:

- `normal` when the deterministic rule is false;
- `high` when it is true.

No additional watch band was added because it would require another
unvalidated threshold.

The `context` field is deterministic JSON. It exposes the useful underlying
values without creating extra alert rows.

## Deterministic rules

### 1. High-volatility recovery

```text
trigger = Phase 1 high_volatility_recovery_state
```

This one macro gate replaces separate alert rows for market drawdown, recovery,
and volatility. Phase 1 defines it as:

- a recent drawdown at or below -20%;
- recovery of at least 5% from the 126-day trough;
- trough age from 1 through 63 trading days;
- 21-day realized volatility at or above its prior-only historical 80th
  percentile.

The scorecard threshold is Boolean `1`. Provenance is `demo_threshold` because
the -20%, +5%, and 63-day structural cutoffs remain demonstration assumptions,
even though the volatility component is historically calibrated.

### 2. Short-minus-long beta gap

```text
value = short-underlying beta 126d - long beta 126d
trigger = value >= threshold
```

The threshold is the 80th percentile of valid beta gaps strictly before the
assessment date after at least 252 prior observations. A structural floor of
zero prevents a still-negative gap from being called a short-leg squeeze
setup merely because it is high relative to a negative history.

Before 252 observations, the labeled demonstration threshold is `+0.25`.
Long, short-underlying, and portfolio beta remain auxiliary context.

### 3. Portfolio drawdown

```text
value = current long-short wealth / highest wealth in the last 63 days - 1
raw threshold = prior-only 20th percentile of the same 63-day drawdown
threshold = clip(raw threshold, -20%, -5%)
trigger = value <= threshold
```

The 63-day window matches Phase 1's maximum early-recovery age. It measures
damage over the mechanism window without allowing an old, unrecovered loss to
contaminate every later observation.

The historical threshold starts after 252 valid observations. It can tighten
with history but can never become more tolerant than `-20%`. A `-5%` ceiling
also prevents an unusually calm history from treating a zero or trivial
drawdown as high risk. Before sufficient history, the labeled demonstration
threshold is `-20%`.

Threshold provenance describes the active threshold, not only the raw
calibration input. When the raw historical quantile lies within the structural
bounds, provenance is `historical_quantile`. When the zero beta-gap floor or
either drawdown bound overrides the raw quantile, provenance is
`demo_threshold`; the explanation preserves the raw quantile, applied bound,
and final active threshold for auditability.

The portfolio has gross exposure two. Its drawdown is not comparable to a
long-only market drawdown, so the scorecard uses the portfolio's own history.
The since-inception drawdown remains available in row context but no longer
sets the alert.

#### Threshold correction after Phase 4 review

The initial implementation compared since-inception drawdown with its
expanding 20th percentile. By 2026-06-30 that threshold had drifted to
`-40.08%`. The portfolio spent long periods below its old high-water mark, so
the distribution described time under water rather than a useful current
warning threshold.

Candidate latest thresholds were:

| Candidate | Latest threshold | Historical trigger rate | Decision |
|---|---:|---:|---|
| Since-inception expanding 20th percentile | -40.08% | 35.1% | Rejected: stale and too tolerant |
| 21-day rolling-peak drawdown | -10.20% | 22.8% | Rejected: too close to routine one-month noise and duplicates the 21-day loss horizon |
| 42-day rolling-peak drawdown | -14.14% | 21.0% | Rejected: no direct architecture anchor |
| 63-day rolling-peak drawdown | -17.20% | 22.7% after bounds | Selected: matches the recovery window |

The selected rule is not claimed to be an optimized predictor. It is a
transparent, point-in-time risk-state threshold that fixes the identified
path-dependence failure while retaining historical calibration.

### 4. Short loss in recovery

```text
daily short loss = max(-signed short contribution, 0)
value = sum(daily short loss over trailing 21 trading days)
trigger = early_recovery_state and value >= threshold
```

The threshold is the prior-only 80th percentile after 252 valid trailing
windows. The pre-history demonstration threshold is `10%`.

This row is a mechanism confirmation, not another macro alert. It can trigger
only when the Phase 1 early-recovery gate is known and true. If the macro gate
is unavailable, the current loss magnitude may still be displayed, but the
trigger remains null.

## Point-in-time controls

- Historical thresholds use dates strictly earlier than the assessment date.
- The current observation is never included in its own threshold.
- Rolling portfolio drawdown uses only wealth observations in the trailing
  63-trading-day window.
- Rolling short loss ends on the as-of date and uses no future contribution.
- Post-close facts have an earliest permitted use in the next trading
  session.
- Changing risk or regime rows after an assessment date leaves the earlier
  scorecard exactly unchanged.
- A scorecard date must occur in at least one source history; otherwise the
  build fails rather than emitting four unexplained nulls.

## Representative result: 2020-03-24

| Metric | Value | Threshold | Trigger |
|---|---:|---:|---|
| High-volatility recovery | 1 | 1 | Yes |
| Short-minus-long beta gap | +0.055 | 0.000 floor | Yes |
| Portfolio drawdown, 63d | -4.82% | -14.45% | No |
| Short loss in recovery, 21d | 40.29% | 15.37% | Yes |

The macro setup and the short-leg mechanism both fired. The positive beta gap
showed that recent losers were modestly more market-sensitive than winners.
The portfolio drawdown did not yet fire because the crash-period long-short
portfolio remained close to its own prior peak.

The macro context on that date was:

- broad-market drawdown: -28.07%;
- recovery from the 126-day trough: +9.35%;
- annualized 21-day realized volatility: 91.26%;
- prior-only volatility threshold: 17.83%.

## Latest complete result: 2026-05-29

| Metric | Value | Threshold | Trigger |
|---|---:|---:|---|
| High-volatility recovery | 0 | 1 | No |
| Short-minus-long beta gap | -2.068 | +0.249 | No |
| Portfolio drawdown, 63d | -7.52% | -17.41% | No |
| Short loss in recovery, 21d | 15.51% | 25.04% | No |

All four rules were available and none triggered. The strongly negative beta
gap confirms the Phase 3 finding that current realized exposure was dominated
by the long leg rather than by a high-beta recent-loser short basket.

## Latest portfolio result with incomplete macro data: 2026-06-30

| Metric | Value | Threshold | Status / trigger |
|---|---:|---:|---|
| High-volatility recovery | unavailable | 1 | unavailable |
| Short-minus-long beta gap | -2.339 | +0.247 | available / no |
| Portfolio drawdown, 63d | -10.50% | -17.20% | available / no |
| Short loss in recovery, 21d | 18.36% | 24.94% | unavailable |

The Phase 1 source ends on 2026-05-29. Therefore the macro gate and the
recovery-gated interpretation of short losses are null, not safe. The beta gap
and drawdown remain independently evaluable.

## Descriptive history findings

Across the 2,365 portfolio dates:

| Rule | Triggered days | Evaluable days |
|---|---:|---:|
| High-volatility recovery | 202 | 2,344 |
| Short-minus-long beta gap | 710 | 2,303 |
| Portfolio drawdown, 63d | 523 | 2,303 |
| Short loss in recovery | 198 | 2,324 |

These are serially correlated daily states and not probabilities. Historical
quantile labels do not imply that realized trigger frequencies must equal
20%, especially for persistent, nonstationary beta and drawdown series. The
revised drawdown rule triggered on 22.7% of evaluable dates, compared with
35.1% under the rejected since-inception rule.

There were 243 early-recovery days. Short loss triggered on 198 of them.
It overlapped with high-volatility recovery on 168 days:

- 34 high-volatility-recovery days did not have extreme trailing short loss;
- 30 extreme-short-loss early-recovery days did not have high volatility.

The overlap is high but not exact. The macro row describes the setup; the
short-loss row confirms whether the intended portfolio mechanism is already
appearing.

## Tests and reproducibility

Phase 1, 3, and 4 targeted suite:

- 26 passed.

Full repository suite:

- 185 passed;
- 4 skipped for the existing raw-payload prerequisites.

Phase 4 tests cover:

- exact four-row schema and absence of duplicate beta/volatility alerts;
- inclusive comparator boundaries;
- greater-than and less-than direction;
- early-recovery activation gate;
- null macro and null risk inputs;
- demonstration fallback provenance;
- guardrail-overridden versus directly active historical provenance;
- direct scorecard-module attribution for the derived 63-day drawdown and
  21-day short-loss metrics;
- beta-gap zero floor;
- 63-day rolling high-water drawdown rather than since-inception drawdown;
- -20% maximum drawdown tolerance and inclusive floating-point boundary;
- future-data perturbation invariance;
- exact repeatability;
- duplicate-date rejection.

The three scorecards and audit JSON were generated twice. All four SHA-256
hashes were identical.

## Engineering and research lessons

### 1. A scorecard should contain decisions, not every available measurement

Phase 1 and Phase 3 intentionally produce rich diagnostic histories. Promoting
each field to an alert would double-count the same mechanism and make the
scorecard harder to interpret. Deterministic JSON context preserves the detail
without increasing the number of decisions.

### 2. Missing activation context is different from a false condition

The 2026-06-30 short loss magnitude is measurable, but whether it is a loss
*in recovery* is not. Separating value availability from trigger availability
prevents the most important fail-open error in this phase.

### 3. Historical quantiles still require economic constraints

Before 2020-03-24, the raw beta-gap 80th percentile was slightly negative.
Without a zero floor, a negative short-minus-long beta gap could trigger the
short-squeeze setup. The floor is explicit and should be validated rather than
hidden inside calibration.

### 4. The metric horizon matters as much as the percentile

No expanding percentile could repair a since-inception drawdown that remained
under water for years. Aligning the drawdown horizon with the 63-day recovery
mechanism removed stale path dependence before applying the historical
threshold.

### 5. A historical percentile is not a calibrated event probability

Persistent drawdowns and beta regimes can remain beyond a growing historical
threshold for long runs. Trigger counts are descriptive flags; Phase 4 does
not convert them into odds of a future momentum crash.

### 6. Setup and realized mechanism can be related without being identical

High-volatility recovery and recovery-period short loss overlap heavily, but
the exceptions are economically informative. The former is a market state;
the latter is observed portfolio damage.

## Assumptions and limitations

- All portfolio-derived rows inherit frozen current-constituent survivorship
  bias.
- SPY and constituent prices are public-vendor research data that can be
  revised.
- The 126-day beta is backward-looking and spans changing monthly holdings.
- The zero beta-gap floor and all demonstration fallbacks are assumptions, not
  literature estimates.
- The 63-day drawdown window and its -20%/-5% bounds are documented operational
  choices, not literature estimates or out-of-sample optimized values.
- A rolling drawdown can reset after an old peak leaves the window even if the
  since-inception portfolio remains under water; the latter is retained in
  context for that reason.
- Short loss is an arithmetic magnitude. It is designed for exact
  contribution reconciliation and is not a compounded return.
- Thresholds use the full expanding past rather than a rolling structural
  regime, so they can adapt slowly after a persistent change.
- Transaction costs, borrow costs, financing, liquidity, capacity, and taxes
  remain absent.
- The macro and beta benchmark proxies are not the same instrument.
- Daily trigger counts are strongly serially dependent and have not been
  out-of-sample calibrated.

## Consequence for Phase 5

Phase 5 should preserve this reduced presentation:

- build all required Fundamental Momentum Alignment diagnostics and flags in
  their own transparent module;
- build only effective bets, top-five contribution share, and sector
  concentration for breadth;
- add no more than one top-level fundamental-alignment row and one top-level
  concentration/breadth row to the official scorecard, with component metrics
  in context;
- keep the fundamental branch configuration-gated so unavailable SEC data
  cannot block or change these four Phase 4 rows.

The high overlap between the two recovery rows should be revisited after
Phase 5 adds fundamental and concentration context. The drawdown correction is
now explicit in code, tests, output metadata, and this review rather than being
a silent calibration change.

## Post-review metadata correction

The review identified two metadata descriptions that were less precise than
the implemented calculations. The numerical thresholds and trigger decisions
did not change.

- A historical quantile overridden by the zero beta-gap floor or the
  `-20%`/`-5%` drawdown bounds is now labeled `demo_threshold`. A historical
  quantile is labeled `historical_quantile` only when it is the active
  threshold without an override.
- `source_module` for the 63-day drawdown now includes
  `src.monitoring.scorecard` and `src.risk.leg_decomposition`. The 21-day
  short-loss-in-recovery row additionally includes
  `src.regime.market_state`.

The `-5%` ceiling remains the documented defensive guardrail: it prevents a
flat historical sample from treating zero or immaterial drawdown as a risk
event. This correction makes that judgment visible in provenance rather than
changing or expanding the Phase 4 scorecard.
