# Methodology

## Decision boundary

The monitor is descriptive and deterministic. It has two intentional layers:

1. **PM momentum portfolio (primary object)** — default implementation is an
   equal-weight S&P 500 12-1 long-10 / short-10 book. This stands in for a
   **customizable** PM momentum portfolio: the monitoring framework is built
   around named holdings, leg risk, scorecard triggers, and unwind structure.
2. **UMD comparison benchmark** — Ken French UMD / market factors and a
   Daniel–Moskowitz-inspired state. Used only as literature-aligned context and
   state-conditioned comparison statistics, not as the PM’s book.

Phase 1–4 scorecard values and triggers are the source of truth for the PM
portfolio layer. The Phase 5 unwind monitor and mechanism scenarios are a
separate deterministic layer on that same book. Evidence and interpretation can
organize supporting material but cannot change a value, threshold, trigger, or
risk state.

All daily observations are post-close facts whose earliest permitted use is the
next trading session.

## UMD comparison benchmark

Uses the Ken French broad-US-market total-return series, risk-free rate, and
UMD factor path to provide comparison context:

- cumulative market drawdown and 126-day trough / recovery;
- 21-day annualized realized volatility versus a prior-only expanding
  80th-percentile threshold;
- retained Daniel–Moskowitz-inspired 504-day bear / 126-day variance state;
- crash, early-recovery, and high-volatility-recovery booleans;
- state-conditioned matured UMD tail-loss frequencies (descriptive, not a
  forecast).

The card header state comes from this comparison path. It answers:
“What does the published momentum-factor backdrop look like?”
It does **not** score the PM’s customized book.

## PM momentum portfolio (S&P 10/10 default)

This is the primary monitored object. The default customization is:

For formation month \(m\), each eligible stock receives the 12-1 signal

\[
\text{momentum}_{i,m}
=
\frac{P_{i,m-1}}{P_{i,m-12}}-1.
\]

Month \(m\) is skipped. The ten highest-ranked names receive equal weights of
`+0.1`; the ten lowest receive `-0.1`. Formation is at month-end close;
holdings become effective in month \(m+1\) and drift during the month.

The universe is a dated current SPY snapshot applied historically. In a
production extension, a PM could substitute their own universe, ranking rule,
or target weights while reusing the same scorecard / unwind / evidence shell.

## Risk decomposition

Preserves separate definitions for long-basket return, short-underlying return,
signed long / short contributions, trailing and conditional betas, 21-day
volatility, and portfolio drawdown for the PM book. Every risk window ends on
the observation date.

## Four-row scorecard

Applied to the PM momentum portfolio:

1. `high_volatility_recovery`
2. `short_minus_long_beta_gap`
3. `portfolio_drawdown`
4. `short_loss_in_recovery`

The first row is a Boolean macro gate shared as market context. Other
thresholds use strictly prior observations when enough history exists,
otherwise labeled demonstration fallbacks. Missing inputs remain unavailable.

## Unwind monitor and mechanism scenarios

A six-row deterministic unwind scorecard is retained for auditability on the
PM book. On top of it, three independent mechanism states may trigger together:

1. `bear_market_recovery_crash` — severe recent drawdown, rapid recovery from
   the trough, and high realized volatility;
2. `short_book_reversal_crash` — extreme short-minus-long reversal with broad
   gains in the active short-underlying basket;
3. `crowded_theme_unwind` — pre-event correlated long cluster at `t-1`, then an
   extreme, broad, loss- or volume-confirmed selloff.

Theme membership uses 63 trading days of benchmark-demeaned returns ending at
`t-1`. It is a `correlated_theme_proxy`.

## Evidence preview

Offline and fail-closed. Requires the versioned local corpus, an exact-date
cached classification already marked schema-valid, provenance agreement,
publication no later than the cutoff, and grounded passages. No live retrieval
in the default demo.

## Assumptions

- A transparent long-10 / short-10 S&P book is a useful default customization
  for demonstrating the PM monitoring workflow.
- Published Ken French UMD / market factors are adequate as a comparison
  benchmark for a research prototype.
- Descriptive state rules are useful for PM review even without a predictive
  crash model.
- AI may organize evidence but must not become an independent risk signal
  without validation.

## Principal limitations

See [limitations.md](limitations.md).
