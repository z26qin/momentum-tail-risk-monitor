# Methodology

## Decision boundary

The monitor is descriptive and deterministic. It keeps these objects separate:

1. **PM momentum portfolio (primary object)** — default implementation is an
   equal-weight S&P 500 12-1 long-10 / short-10 book. This stands in for a
   **customizable** PM momentum portfolio: monitoring is built around named
   holdings, leg risk, scorecard triggers, and unwind structure.
2. **UMD comparison benchmark** — Ken French UMD / market factors and a
   Daniel–Moskowitz-inspired state. Used only as literature-aligned context and
   state-conditioned comparison statistics, not as the PM’s book.
3. **Mechanical unwind / market absorption** — a lightweight public-data proxy
   for factor-aligned flow and short-horizon absorption stress. It does not
   merge into the macro state or the four-row PM scorecard.

Phase scorecard values and triggers are the source of truth for the PM
portfolio layer. The unwind monitor and mechanism scenarios are a separate
deterministic layer on that same book. Evidence and interpretation can
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

## Mechanical unwind and market absorption

A separate lightweight layer (`src/monitoring/unwind_monitor.py`) adds
Khandani–Lo-inspired diagnostics that distinguish economic momentum reversal
from possible mechanical / factor-aligned unwind pressure. It does **not**
merge into the four-row PM scorecard or the six-row unwind triggers.

Daily diagnostics (all controls / membership lagged one session):

1. **Cross-sectional factor footprint** — OLS of stock returns on lagged
   momentum rank, trailing volatility, and (when coverage allows) a PIT
   SEC×price log-size proxy. Outputs `cross_sectional_r2`, `momentum_beta`,
   and prior-only percentiles.
2. **Momentum-aligned abnormal turnover** — abnormal volume
   (`volume / rolling median`) for lagged PM L10 / S10 extremes versus the
   universe; `extreme_turnover_ratio` is their ratio.
3. **Market-absorption proxy** — next-day short-leg minus long-leg return of
   lagged extremes (`short_horizon_reversal`); continuation and a simple
   absorption-failure flag. This is a daily price proxy, not dealer inventory
   or TAQ liquidity.

Rule-based states use rolling historical percentiles:

- `NORMAL`
- `FRAGILITY_BUILDING` (≥2 elevated vulnerability indicators)
- `ACTIVE_UNWIND` (portfolio losses with elevated footprint, aligned turnover,
  and continuation / failed absorption)
- `STABILIZING_REVERSAL` (recent active-unwind window followed by rebound and
  declining footprint / turnover)

Limitation retained verbatim for PM communication:

> The module detects factor-aligned trading footprints, not actual hedge-fund
> liquidations. It should be interpreted as a mechanical-unwind proxy rather
> than direct positioning evidence.

Adding this layer to `MVPRunResult` bumps the run schema to `mvp-run-v2` and
changes `full_run_fingerprint` by design.

## Evidence preview

Offline and fail-closed. Requires the versioned local corpus, an exact-date
cached classification already marked schema-valid, provenance agreement,
publication no later than the cutoff, and grounded passages. No live retrieval
in the default demo.

**Labeling note:** frozen case packs under `outputs/*/` and curated evidence
under `data/evaluation/` and `data/corpus/` are manually curated or
exact-date cached artifacts. Exact-date classification caches live in
`outputs/evidence_cache/` and are labeled there. They are not live
institutional news feeds.

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
