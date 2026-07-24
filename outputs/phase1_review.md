# Phase 1 Review — US Equity Momentum Tail Risk

## Executive conclusion

Phase 1 establishes a reproducible, point-in-time market-only research
baseline for sharp reversals in the US equity momentum factor. The fixed data
vintage ends on 2026-05-29. The feature-complete model sample begins on
1990-01-02 because VIX is mandatory and unfilled.

The panic-state baseline B1 has the clearest development evidence,
particularly for the 20-day horizon. The pre-specified full model B2 often
ranks 5-day risk but its probability calibration is unstable across time.
The 5-day holdout provides modest evidence of useful ranking. The 20-day
holdout contains only one independent episode and cannot support a strong
conclusion.

This is evidence for continued research, not for a production alert. No alert
threshold, position-sizing rule, text feature, or positioning feature is part
of Phase 1.

## Chosen labels and rationale

For horizon \(h \in \{5,20\}\), the outcome is the compounded published UMD
return over trading rows \(t+1,\ldots,t+h\). The primary event is:

\[
\text{mom\_tail\_loss}_{h,t}
=
\mathbb{1}\!\left[
R^{mom}_{t,t+h}<q^{PIT}_{0.05,h,t}
\right].
\]

The point-in-time threshold includes a historical assessment row \(s\) only
when its complete forward window has matured:
`label_end_date[s] <= assessment_date[t]`. Equality is allowed because the
outcome is known at the approved post-close assessment. The event comparison
is strict (`<`), and pandas `linear` quantile interpolation is frozen.

This unconditional left-tail label was chosen because it represents losses
that hit momentum P&L regardless of whether prior momentum was strong.
Prior-state dependence belongs in predictors rather than in the definition of
the loss. Each row stores the label start, end, and first-available dates.

Historical descriptive thresholds begin after 252 matured observations.
Before any model row is allowed, at least 2,520 matured observations and ten
calendar years of label history are required. At model start, the 5-day and
20-day thresholds have 16,979 and 16,964 matured observations respectively.

Positive days are assigned to the same episode until at least five
consecutive valid non-event days occur. Episodes are used for adequacy and
reporting; the model target remains daily.

### Label counts

| Horizon | Sample | Valid days | Event days | Event rate | Episodes |
|---:|---|---:|---:|---:|---:|
| 5 | Full label history | 25,891 | 1,295 | 5.00% | 340 |
| 5 | VIX-start model history | 9,164 | 680 | 7.42% | 173 |
| 20 | Full label history | 25,861 | 1,340 | 5.18% | 134 |
| 20 | VIX-start model history | 9,149 | 628 | 6.86% | 57 |

### Rejected or sensitivity-only variants

| Variant | Result | Decision |
|---|---|---|
| Full-sample fixed threshold | Would use future distribution information | Rejected as oracle leakage |
| PIT 2.5% tail | 673 event days / 186 episodes at 5 days; 759 / 79 at 20 days | Retained only as a sparse sensitivity |
| PIT 10% tail | 2,570 event days / 569 episodes at 5 days; 2,611 / 241 at 20 days | Retained only as a broader sensitivity |
| Primary tail plus prior 63-day strength above its PIT median | 689 event days / 210 episodes at 5 days; 812 / 107 at 20 days | Sensitivity only because it changes the monitored P&L event set |
| Class-weighted logistic | Would change the probability target and harm direct calibration interpretation | Excluded from primary models |
| Three-year development tests | Two 20-day folds had only 3 and 2 episodes | Rejected by the pre-specified adequacy gate; six-year non-overlapping tests approved |

Of primary episode onsets with observed prior state, 74.41% at 5 days and
79.85% at 20 days followed positive trailing 63-day UMD performance. This
supports tracking prior strength as a state variable without conditioning the
label on it.

## Feature set and exact lags

Every model feature is available at the date-\(t\) post-close assessment for
earliest action in the next session. “Lag 0” below means the value is used on
its economic date under that approved convention; it does not assert that a
historical vendor timestamp proves availability at the closing bell.

| Feature | Mechanism | Exact information window | Availability lag |
|---|---|---|---:|
| `mom_return_21d` | Momentum state | Compounded UMD over 21 rows ending \(t\) | 0 |
| `mom_return_63d` | Momentum state | Compounded UMD over 63 rows ending \(t\) | 0 |
| `mom_return_126d` | Momentum state | Compounded UMD over 126 rows ending \(t\) | 0 |
| `mom_drawdown_252d` | Momentum state | Current cumulative UMD wealth versus its trailing 252-row peak | 0 |
| `mom_vol_21d` | Momentum state | Sample SD of UMD over 21 rows ending \(t\) | 0 |
| `mom_vol_63d` | Momentum state | Sample SD of UMD over 63 rows ending \(t\) | 0 |
| `vix_close` | Panic state | Untransformed FRED VIXCLS value dated \(t\) | 0 |
| `mkt_return_504d` | Panic state | Compounded broad-market proxy over 504 rows ending \(t\) | 0 |
| `bear_state` | Panic state | `mkt_return_504d < 0` | 0 |
| `mkt_variance_126d` | Panic state | Sample variance over 126 rows ending \(t\) | 0 |
| `bear_x_mkt_variance_126d` | Panic state | Bear indicator × 126-day variance | 0 |
| `mkt_vol_percentile_126d` | Panic state | Weak expanding percentile of current 126-day volatility using states through \(t\) | 0 |
| `mkt_return_1d` | Rebound trigger | Broad-market proxy return at \(t\) | 0 |
| `mkt_return_5d` | Rebound trigger | Compounded broad-market proxy over 5 rows ending \(t\) | 0 |
| `mkt_return_20d` | Rebound trigger | Compounded broad-market proxy over 20 rows ending \(t\) | 0 |
| `stress_rebound` | Rebound trigger | Bear × PIT volatility percentile × positive part of 5-day market return | 0 |
| `loser_leg_return_5d` | Leg structure | Compounded loser-leg return over 5 rows ending \(t\) | 0 |
| `loser_leg_return_20d` | Leg structure | Compounded loser-leg return over 20 rows ending \(t\) | 0 |
| `loser_leg_vol_21d` | Leg structure | Sample SD of loser leg over 21 rows ending \(t\) | 0 |
| `loser_minus_winner_vol_21d` | Leg structure | Loser-leg 21-day SD minus winner-leg 21-day SD | 0 |
| `formation_spread` | Leg structure | Decile-10 minus decile-1 compounded returns over 252 observations ending \(t-21\); full span 273 rows | 0, with internal 21-row skip |
| `mom_mkt_beta_126d` | Beta instability | Rolling 126-day UMD/market covariance divided by market variance | 0 |
| `mom_mkt_corr_126d` | Beta instability | Rolling 126-day UMD/market correlation | 0 |
| `beta_change_21d` | Beta instability | Current 126-day beta minus beta at \(t-21\) | 0, with internal 21-row comparison |

Volatility and variance remain in unannualized daily units. Full windows are
required. The three missing VIX dates remain missing until fold-local median
imputation. `vix_was_filled` and `vix_age_trading_days` are audit fields, not
model features.

## Baselines and frozen choices

- B0: constant primary-event rate in the purged training rows.
- B1: unweighted logistic regression on `bear_state`,
  `mkt_variance_126d`, and `bear_x_mkt_variance_126d`.
- B2: unweighted logistic regression on all 24 features; this is the
  pre-specified primary model.
- Logistic specification: L2, `C=1`, `lbfgs`, maximum 2,000 iterations.
- Preprocessing: training-fold median imputation followed by
  training-fold standardization inside one sklearn pipeline.
- Metrics: log loss, Brier, PR-AUC, secondary ROC-AUC, calibration intercept
  and slope, calibration buckets, and event capture in the top ranked decile.
- Alert threshold: none.

The specification hash frozen before holdout is
`43cd6360ea342331d2da13bcdac56c7c0d9706e278c4c89c531aa682a9270c2a`.

## Purged expanding validation

The approved resolution uses an initial ten-year training window followed by
six-year, non-overlapping development tests. Training expands from
1990-01-02. Every candidate training row with
`label_end_date >= test_start` is purged.

| Horizon | Split | Train end after purge | Test range | Purged | Test event days | Test episodes |
|---:|---|---|---|---:|---:|---:|
| 5 | `dev_00` | 1999-12-23 | 2000-01-03–2005-12-30 | 5 | 181 | 39 |
| 5 | `dev_01` | 2005-12-22 | 2006-01-03–2011-12-30 | 5 | 169 | 35 |
| 5 | `dev_02` | 2011-12-22 | 2012-01-03–2017-12-29 | 5 | 66 | 26 |
| 20 | `dev_00` | 1999-12-02 | 2000-01-03–2005-12-30 | 20 | 176 | 12 |
| 20 | `dev_01` | 2005-12-01 | 2006-01-03–2011-12-30 | 20 | 175 | 13 |
| 20 | `dev_02` | 2011-12-01 | 2012-01-03–2017-12-29 | 20 | 53 | 9 |

All development tests pass the five-episode minimum. Data after the final
development test and before the holdout are eligible for the final expanding
training fit but do not form a partial development test.

The retained holdout begins on the first observed trading date after its
nominal 2023-05-29 boundary:

| Horizon | Train end after purge | Holdout range with valid labels | Purged | Event days | Episodes |
|---:|---|---|---:|---:|---:|
| 5 | 2023-05-19 | 2023-05-30–2026-05-21 | 5 | 31 | 17 |
| 20 | 2023-04-28 | 2023-05-30–2026-04-30 | 20 | 9 | 1 |

## Probability and calibration results

### Development

| Horizon | Baseline | Log loss | Brier | PR-AUC | ROC-AUC | Cal. intercept | Cal. slope | Top-decile capture |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 5 | B0 | 0.3343 | 0.0861 | 0.0785 | 0.3984 | -4.180 | -0.644 | 2.16% |
| 5 | B1 | 0.3431 | 0.0895 | 0.3005 | 0.7707 | -1.533 | 0.369 | 35.58% |
| 5 | B2 | 0.9440 | 0.1685 | 0.2798 | 0.7880 | -2.212 | 0.177 | 35.10% |
| 20 | B0 | 0.3334 | 0.0842 | 0.0762 | 0.3885 | -4.157 | -0.600 | 1.49% |
| 20 | B1 | 0.2966 | 0.0806 | 0.3737 | 0.8106 | -1.344 | 0.464 | 42.57% |
| 20 | B2 | 0.6133 | 0.1130 | 0.2485 | 0.7396 | -1.787 | 0.172 | 37.62% |

B0 is constant only within each fold. Its pooled ROC-AUC and top-decile
capture are artifacts of differing fold-level base rates and are not ranking
evidence.

### One-time holdout

| Horizon | Baseline | Log loss | Brier | PR-AUC | ROC-AUC | Cal. intercept | Cal. slope | Top-decile capture |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 5 | B0 | 0.1831 | 0.0410 | 0.0414 | 0.5000 | -0.660 | undefined | 9.68% |
| 5 | B1 | 0.1712 | 0.0397 | 0.0966 | 0.6357 | 0.320 | 1.273 | 12.90% |
| 5 | B2 | 0.1715 | 0.0402 | 0.0785 | 0.6550 | -1.040 | 0.739 | 19.35% |
| 20 | B0 | 0.1070 | 0.0158 | 0.0123 | 0.5000 | -1.846 | undefined | 0.00% |
| 20 | B1 | 0.0943 | 0.0146 | 0.0117 | 0.4283 | -13.854 | -3.080 | 0.00% |
| 20 | B2 | 0.0848 | 0.0147 | 0.0143 | 0.5583 | -4.051 | 0.101 | 0.00% |

Full predicted-probability buckets and realized rates are in
`outputs/calibration_table.csv`.

## Strongest evidence

1. B1 provides strong development ranking for the 20-day target:
   ROC-AUC 0.811, PR-AUC 0.374, and 42.57% of event days captured in the
   highest-ranked decile.
2. For the 5-day holdout, both fitted models improve log loss over B0. B2
   reaches ROC-AUC 0.655 and captures 19.35% of event days in 10% of rows.
3. Winner/loser reconstruction tracks published UMD at correlation
   0.9999865 with maximum absolute daily residual 0.00010, supporting the
   leg-level feature construction.
4. Point-in-time invariance checks and synthetic tests show that later returns
   cannot change earlier thresholds or features.

## Weakest evidence

1. B2 has severe development probability instability despite acceptable
   ranking. Its pooled calibration slopes are 0.177 and 0.172, with log loss
   materially worse than B0.
2. The 20-day holdout has only one episode. Its calibration, ranking, and
   top-decile results are not reliable model-selection evidence.
3. Only three development tests remain after enforcing adequate episode
   counts, so uncertainty across regimes is large.
4. Market-only inputs cannot directly observe crowding, dealer positioning,
   flows, or narrative catalysts.

## Unresolved limitations

- The broad-market total-return proxy is `Mkt-RF + RF`; it is not a named
  cash index and should not be represented as one.
- VIX starts on 1990-01-02 and binds the model sample. The three unfilled
  trading-date gaps are 1991-03-01, 1997-01-31, and 1997-11-26.
- Same-date market closes are accepted for post-close assessment and
  next-session action. Historical release timestamps are not supplied in the
  source CSV files.
- `formation_spread` is a 252-observation decile return spread ending at
  \(t-21\), with a full span of 273 trading rows. It is not beta compression.
- Daily forward labels overlap and are serially dependent; episode counts are
  the more relevant measure of independent stress.
- Aggregate holdout counts were exposed during an early gate implementation.
  No holdout prediction or performance metric informed a model choice, and
  the limited contamination was accepted before the single evaluation.
- Public data can be revised after this frozen snapshot.
- No transaction costs, capacity, portfolio exposure mapping, hedge
  effectiveness, or economic loss function is modeled.
- No alert threshold exists because no false-positive / false-negative cost
  or review-capacity constraint was provided.

## Phase 2 interface notes

These are interface requirements only; no Phase 2 ingestion or modeling was
performed.

### Assessment contract

- One assessment per momentum trading date after the US close.
- Earliest action is the next trading session.
- Every input must carry an `available_at` timestamp or an explicit,
  documented release-lag rule.
- Text and positioning values may join date \(t\) only when they were
  genuinely available by the assessment cutoff. Observation dates alone are
  insufficient.

### Candidate input boundary

- Preserve all 24 Phase 1 market features and their names.
- Add text and positioning families as separately versioned blocks; do not
  overwrite or reinterpret existing market columns.
- Retain raw-source snapshot hashes, retrieval timestamps, source observation
  dates, effective availability dates, missingness flags, and any fill age.
- GDELT, if pursued, requires the separate feasibility spike specified in the
  project brief before any panel or feature is approved.

### Candidate output boundary

Each prediction record should minimally contain:

- `assessment_date`;
- `horizon_days`;
- `predicted_tail_probability`;
- `model_version`;
- `specification_hash`;
- `data_vintage`;
- `feature_available_at_max`;
- missingness / staleness audit fields.

The probability remains the primary deliverable. Alert state, hedge size, and
de-gross recommendation must be downstream policy fields based on an explicit
cost or capacity rule, not a default probability of 0.5.

### Evaluation discipline

- Phase 2 choices must be made on a new development protocol.
- The reported Phase 1 holdout must not be reused as a clean tuning set.
- A future final evaluation requires a newly reserved period or a prospective
  shadow run.
- Calibration must be reassessed by horizon and regime before operational use.

## Integrity status

Seven pytest tests pass. The read-only Task 4 audit independently recomputes
48 saved probability metrics and reconciles all calibration totals without
refitting. The executed notebook has 12 cells and no error output. Raw source,
processed artifact, model specification, and final output hashes are retained
with the project.
