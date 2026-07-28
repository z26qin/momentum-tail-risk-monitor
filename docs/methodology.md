# Final MVP methodology

## Decision boundary

The monitor is descriptive and deterministic. Phase 1–4 values and triggers
are the source of truth. Phase 5A reports acquisition feasibility only. The
evidence preview can organize local supporting, contradicting, and contextual
material, but cannot change a value, threshold, trigger, or risk state.

All daily observations are post-close facts whose earliest permitted use is
the next trading session.

## Phase 1 — Macro regime

The macro module uses the Ken French broad-US-market total-return proxy and
risk-free rate. It calculates:

- cumulative market drawdown;
- the minimum drawdown over 126 trading days;
- recovery from the 126-day trough;
- 21-day annualized realized volatility;
- a prior-only expanding 80th-percentile volatility threshold;
- the retained Daniel–Moskowitz-inspired 504-day bear and 126-day variance
  state;
- crash, early-recovery, and high-volatility-recovery booleans;
- a simple 63-day change in the annualized 21-day risk-free-rate proxy.

The demo's `market_stage` is only a display adapter. Its fixed precedence is
high-volatility recovery, crash, early recovery, high volatility, and then the
frozen DM state. It creates no new risk threshold.

## Phase 2 — Synthetic momentum portfolio

For formation month \(m\), each eligible stock receives the 12-1 signal

\[
\text{momentum}_{i,m}
=
\frac{P_{i,m-1}}{P_{i,m-12}}-1.
\]

Month \(m\) is skipped. The ten highest-ranked names receive equal weights of
`+0.1`; the ten lowest-ranked names receive `-0.1`. Formation occurs at the
month-end close and holdings become effective in month \(m+1\). Constituents'
weights drift during the month rather than being reset daily.

The universe is a dated current SPY snapshot applied historically. It is a
transparent current-membership proxy, not a point-in-time S&P 500 membership
history.

## Phase 3 — Risk decomposition

The module preserves separate definitions for:

- long-basket return;
- short-basket underlying return;
- signed long contribution;
- signed short contribution, equal to the negative short-underlying return;
- long-short portfolio return, equal to the two signed contributions.

Trailing beta is covariance with SPY total return divided by SPY variance over
126 trading days, with 63 observations required. Up- and down-market betas use
positive and negative SPY-return observations respectively, with 30
observations required. The short-minus-long beta gap is

\[
\beta_{\text{short underlying}}-\beta_{\text{long}}.
\]

The module also reports 21-day annualized volatility, 21-day summed
contributions, and portfolio drawdown. Every risk window ends on the
observation date.

## Phase 4 — Deterministic scorecard

The scorecard remains the unchanged four-row contract:

1. `high_volatility_recovery`;
2. `short_minus_long_beta_gap`;
3. `portfolio_drawdown`;
4. `short_loss_in_recovery`.

The first row is a Boolean macro gate. Other thresholds use strictly prior
observations when enough history exists and labeled demonstration fallbacks
otherwise. Portfolio drawdown uses a rolling 63-day high-water mark. Missing
inputs remain unavailable; there is no aggregate probability or opaque score.

## Phase 5A — SEC feasibility only

Phase 5A fetched one Company Facts payload per distinct eligible CIK and
audited revenue-growth acceleration, EPS-growth acceleration, and
operating-margin change under a two-of-three rule. Filing availability is the
first trading day after the filing date, and the latest fiscal information
must be no more than 180 days stale. Operating margin is excluded where it is
not economically comparable, including banks, insurers, and REITs.

The reviewed result is 322 of 497 mapped issuers, or 64.79%, which is
`degraded` under the approved 60%–80% band. This result does not contain a
universe fundamental rank, Spearman alignment, portfolio spread, or alignment
flag. Those remain `null` until Phase 5B.

## Demo date alignment

The primary observation date is `2026-05-29`, the latest date shared by the
macro and realized-risk histories.

| Meaning | Date |
|---|---|
| Observation and realized risk | 2026-05-29 |
| Formation of portfolio bearing that risk | 2026-04-30 |
| Formation of next portfolio at observation-date close | 2026-05-29 |
| Phase 5A feasibility audit | 2026-06-30 |

The June 30 holdings formation and June 30 risk history are later module data.
They are not used in the May 29 current observation.

## Historical case

The same observation builder is used for:

- `2023-01-09`: relative elevated-risk, stress-precursor, and
  high-volatility-recovery example;
- `2023-02-02`: realized portfolio stress observation.

January 9 is not a formal `panic_elevated` state: the frozen DM state is
`bear_low_volatility`, even though the explicit Phase 1
high-volatility-recovery gate is true. February 2 records realized short-side
pressure. The sequence is descriptive and neither proves prediction nor
causality.

## Evidence preview

The Phase 8 capability preview is offline and fail-closed. It requires:

- the versioned local corpus;
- an exact-date cached classification already marked schema-valid;
- provenance agreement between cached items and corpus;
- publication no later than the date cutoff;
- grounded extracted passages.

The January 9, 2023 case has no exact-date validated cache, so the demo returns
`status="unavailable"` with empty supporting, contradicting, and contextual
arrays. A 2024 cached sample proves the replay path in tests but is not
substituted into the 2023 case.

## Principal limitations

- Current-membership survivorship bias.
- Vendor price and ticker-history discontinuities.
- No production point-in-time fundamental panel or alignment measures.
- No breadth, crowding, or full AI research layer.
- No causal inference, portfolio sizing, trading advice, or predictive risk
  probability.
