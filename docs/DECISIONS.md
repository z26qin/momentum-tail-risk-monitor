# Decisions

## Phase 1 research contract

### Purpose and decision context

The intended user is a US-equity pod portfolio manager operating under explicit
drawdown limits and carrying exposure to the equity momentum factor. The
system's core research object is **US equity momentum factor reversal risk**:
the risk that established winner-versus-loser performance reverses sharply.
The eventual system may assess that risk with market, text, and positioning
information. Phase 1 remains market-only; text and positioning inputs cannot
enter any Phase 1 empirical result.

At each assessment, the system estimates the near-term probability that the
momentum factor will enter its left tail. The estimate is decision support for
three related actions:

1. **De-gross momentum exposure** when the projected tail risk is inconsistent
   with the pod's remaining drawdown budget.
2. **Hedge short-leg convexity** when a stressed-market rebound could cause the
   recent-loser short leg to rally sharply.
3. **Tighten review** by increasing monitoring and requiring a documented human
   review, without implying an automatic trade.

Phase 1 produces a calibrated risk estimate and evidence about market-state
mechanisms. It does not prescribe position sizes, execute trades, or select an
alert threshold, and it is a lean research prototype rather than a polished
production system. An alert threshold will require an explicit false-positive
/ false-negative cost or alert-capacity rule estimated on development folds.

### Assessment time, information set, and horizons

- The assessment timestamp is **US market close on trading date \(t\)**.
- A feature for \(t\) may use only information available by that close.
  No value is eligible merely because its source assigns it date \(t\).
- **Approved availability convention:** the empirical
  convention treats final date-\(t\) market closes as observable for a
  post-close assessment whose earliest action is the next session. The Ken
  French files and FRED series do not provide a historical, machine-readable
  release timestamp for every observation. Task 1 must check and document
  source publication conventions. If the mandate means availability at the
  closing bell rather than a post-close run, any source whose same-day
  availability cannot be established will be lagged one trading day.
- The prediction horizons are \(h \in \{5, 20\}\) momentum trading days.
- The forward window starts on the next momentum trading day, \(t+1\), and ends
  on \(t+h\). Assessment-day returns never enter the label.
- A configurable `AS_OF_DATE` is frozen for each run. Raw inputs are truncated
  to observations available on or before that date, and the selected value is
  recorded with the run artifacts.
- Phase 1 uses only public market data. Text and positioning data are outside
  the empirical information set and will not be ingested, modeled, or
  synthesized.

### Primary estimand and label

Let \(r^{mom}_u\) be the published daily UMD return in decimal units. For each
horizon \(h\),

\[
R^{mom}_{t,t+h}
=
\prod_{j=1}^{h}(1+r^{mom}_{t+j})-1.
\]

The primary binary outcome is

\[
\text{mom\_tail\_loss}_{h,t}
=
\mathbb{1}\!\left[
R^{mom}_{t,t+h} < q^{PIT}_{0.05,h,t}
\right],
\]

where \(q^{PIT}_{0.05,h,t}\) is the fifth percentile of only those historical
forward \(h\)-day UMD returns whose complete label windows have matured by the
assessment at \(t\). Equivalently, a historical assessment row \(s\) may enter
the threshold sample only if its `label_end_date` is on or before \(t\). The
most recent \(h\) assessment rows are not yet mature and cannot enter the
quantile. No full-sample or oracle threshold will be created for model use.

Before any label may enter the model sample, its threshold must have at least
ten years of matured daily label history. The full UMD history beginning in
1926 supplies that history before the VIX-bounded model sample begins.
Historical labels used only for descriptive crash reference may begin earlier
under a separately documented minimum-history rule. Labels are retained with
`label_start_date`, `label_end_date`, and `label_available_date`; the latter is
the close of `label_end_date`, when the outcome first becomes observable.

The primary event set is deliberately unconditional on the prior momentum
state: it represents losses that hit momentum P&L. Prior-state dependence is
handled through features. Thresholds at 2.5% and 10%, and a
prior-strength-conditioned variant, are descriptive sensitivities only and
will not be used to choose or train the primary Phase 1 model.

Consecutive positive label days are de-clustered for episode reporting. A new
episode begins only after at least five consecutive non-event assessment days;
the first positive day of an episode is its onset. This episode definition is
used for counts and validation adequacy, not to alter the daily binary target.

### Feature hypotheses by mechanism

| Mechanism | Feature family | Pre-specified hypothesis |
|---|---|---|
| Momentum state | Trailing UMD returns, drawdown, and volatility | Strong prior momentum and rising factor volatility may leave a crowded momentum book vulnerable; a deep existing drawdown may instead indicate that part of the unwind has already occurred. Signs can therefore differ across state and volatility terms. |
| Panic state | Long-horizon broad US market total-return proxy, bear indicator, market variance, and their interaction / percentile | Momentum tail losses should become more likely when a prolonged negative market state coincides with elevated market variance, consistent with the Daniel–Moskowitz panic-state mechanism. |
| Rebound trigger | Short-horizon broad-market returns and a bear-state × volatility-percentile × positive-rebound interaction | A sharp positive market rebound following a volatile bear state should raise crash risk by forcing a rapid reversal in recent losers. |
| Leg structure | Recent loser-leg return and volatility, loser-minus-winner volatility, and decile-based formation spread | Risk should rise when the recent-loser leg becomes unusually volatile or rebounds sharply relative to the winner leg. A large formation spread represents strong prior cross-sectional separation; its empirical sign is not imposed. |
| Beta instability | Rolling momentum-to-market beta, correlation, and recent beta change | Rapid changes in factor beta or correlation may identify unstable exposure and nonlinear unwind conditions not captured by standalone volatility. |

Every implemented feature will receive a separate audit row below this contract
with its exact formula, lookback, lag, first usable date, expected sign,
missing-value rule, and leakage note. Formation spread will refer only to the
decile-based prior-return spread; beta and correlation will not be described as
formation-spread compression.

### Validation design

The model sample begins only when every mandatory feature is genuinely
available, expected to be bounded by VIX history around 1990. The earlier
label-history sample is used for point-in-time threshold estimation and
historical episode reference, never as feature-complete model data.

Models form a pre-specified nested ladder:

- **B0:** point-in-time unconditional matured event rate.
- **B1:** unweighted logistic regression using bear state, 126-day market
  variance, and their interaction.
- **B2:** unweighted regularized logistic regression using all pre-specified
  Phase 1 market features.

All learned imputation, scaling, and model fitting occur inside a
training-fold-only scikit-learn pipeline. Class weighting is excluded from the
primary probability models because it changes the probability target; a
class-weighted ranking sensitivity may be reported separately.

Development evaluation uses rule-generated purged expanding walk-forward
splits, separately for \(h=5\) and \(h=20\):

- initial training window: 10 years;
- test block: 3 years;
- step: 3 years;
- chronological constraint:
  `max(train_date) < min(test_date)`;
- label-window purge: remove every training row whose `label_end_date` is on or
  after the test start;
- adequacy rule: halt and report if any test fold contains fewer than five
  de-clustered episodes for the relevant horizon.

The final three years are an untouched holdout. Model specification, feature
set, regularization-selection procedure, preprocessing, metric definitions,
and any sensitivity analyses must be frozen using development folds before the
holdout is evaluated once.

For each horizon and baseline, report log loss, Brier score, PR-AUC, secondary
ROC-AUC, calibration buckets, calibration intercept and slope, event capture
in the top predicted-risk decile, and event-day / episode counts. There is no
default 0.5 classification threshold.

### Contract decisions and alternatives considered

| Judgment | Options considered | Contract choice | Rationale |
|---|---|---|---|
| Assessment timing | Market open, intraday, or close | Market close on \(t\) | Public daily sources have a defensible close-to-close information set; intraday availability cannot be established from these data. |
| Dated close versus vendor publication | Treat a date-\(t\) value as available post-close; require proof of publication by the closing bell; lag uncertain sources one trading day | **Approved 2026-07-24:** post-close / next-session-action convention, with Task 1 source-timing audit | Ken French and FRED observation dates do not by themselves prove the exact publication time. Treating them as synonymous would hide a point-in-time assumption. |
| Event target | Any left-tail UMD loss; prior-strength-conditioned crash; full-sample fixed threshold | PIT fifth-percentile UMD loss, unconditional on prior strength | Matches realized factor P&L, preserves a stable monitored event concept, and avoids oracle information. |
| Threshold eligibility | Expanding quantile through row \(t\); lag by \(h\) rows; explicit maturity dates | Explicitly include only labels with `label_end_date <= t` | Makes maturity auditable and remains correct if the trading calendar has gaps. |
| Modeling unit | Event episodes or assessment days | Daily probability target, with episodes used for reporting and adequacy checks | The PM makes a decision each close, while de-clustering prevents overlapping positive days from overstating independent crashes. |
| Primary weighting | Unweighted or class-weighted logistic regression | Unweighted | Keeps predicted probabilities aligned with observed base rates and calibration objectives. |
| Holdout use | Repeated tuning or one-time evaluation | One-time evaluation after development choices are frozen | Protects the only clean estimate of final out-of-sample performance. |
| `AS_OF_DATE` | Hard-code an assumed date or configure and record it | Configurable, frozen per run | Supports reproducibility without silently guessing the user's intended data vintage. |

### Task 0 review status

Approved by the project owner on 2026-07-24. The approved convention is a
post-close assessment for earliest action in the next session, with source
publication timing audited rather than inferred from observation dates.

## Task 1 — Data pipeline decisions

### Frozen run date

The Task 1 audit run will use `AS_OF_DATE=2026-05-29`, the last common
observation in the four French archives retrieved on 2026-07-24. The value is
passed explicitly on the command line; the code has no moving "today" default.
Changing it creates a distinct run and must be recorded in the raw metadata and
audit outputs.

### Sources, units, and selected tables

| Dataset | Public source | Raw unit | Processing choice |
|---|---|---|---|
| Daily UMD | `F-F_Momentum_Factor_daily_CSV.zip`, Ken French Data Library | Percent return | Parse the single daily table and divide by 100. |
| Daily research factors | `F-F_Research_Data_Factors_daily_CSV.zip`, Ken French Data Library | Percent return | Retain `Mkt-RF` and `RF`, divide by 100, and define `mkt_total_return = mkt_rf + rf`. This is a broad US market total-return proxy and is never given an index-brand name. |
| Daily 2×3 size–momentum portfolios | `6_Portfolios_ME_Prior_12_2_Daily_CSV.zip`, Ken French Data Library | Percent return | Select the first `Average Value Weighted Returns -- Daily` block and divide by 100. |
| Daily momentum deciles | `10_Portfolios_Prior_12_2_Daily_CSV.zip`, Ken French Data Library | Percent return | Select the first `Average Value Weighted Returns -- Daily` block and divide by 100. |
| VIX close | `VIXCLS`, FRED | Index points | No unit conversion. Left-align to the UMD trading-date calendar; primary output never fills. |

The value-weighted portfolio tables were selected over the equal-weighted
tables because the French library's UMD construction uses the six
value-weighted portfolios. Parsing stops when the selected table's consecutive
eight-digit daily rows end, preventing the equal-weighted block and copyright
footer from entering the data.

### Leg and formation-spread definitions

\[
\begin{aligned}
\text{winner\_leg\_return}_t
&= \tfrac12(\text{Small Hi}_t + \text{Big Hi}_t),\\
\text{loser\_leg\_return}_t
&= \tfrac12(\text{Small Lo}_t + \text{Big Lo}_t),\\
\widehat{\text{UMD}}_t
&= \text{winner\_leg\_return}_t-\text{loser\_leg\_return}_t.
\end{aligned}
\]

The reconstruction is validated against published UMD after both inputs have
been converted to decimals. The acceptance tolerance is correlation at least
0.9999 and maximum absolute daily residual at most 0.00011; the nonzero
residual is expected from source returns rounded to two decimal percentage
points.

For decile \(k\), let

\[
C_{k,t}^{252,21}
=
\prod_{j=21}^{272}(1+r_{k,t-j})-1.
\]

Then

\[
\text{formation\_spread}_t
= C_{10,t}^{252,21} - C_{1,t}^{252,21}.
\]

Operationally this is a 21-row shift followed by a 252-row fully observed
rolling compound. It uses only returns through \(t-21\).

### Point-in-time availability and VIX gaps

The French archives are public research files assembled from CRSP and updated
in batches; their observation dates are economic dates, not per-row public
release timestamps. FRED labels VIXCLS as `Daily, Close`, but its current page
shows a dated close updated the following morning. Neither raw file supplies a
historical release timestamp for every observation.

Under the approved post-close / next-session-action convention, date-\(t\)
closing observations are treated as the economic information set for
assessment \(t\), while this vendor-publication limitation remains explicit.
This is not evidence that a literal closing-bell production job could download
the same files at that instant. Such a job would require a timely public feed
or a separately audited replication pipeline.

VIX alignment retains all UMD trading dates. Rows before the first observed VIX
value are structural pre-coverage missingness and do not count as unexpected
gaps. Within VIX coverage, a missing value on a UMD trading date remains `NaN`
and is listed in the audit report. The primary table always sets
`vix_was_filled=False`; a separately named sensitivity may fill only a missing
row whose immediately preceding UMD trading row has an observed value, setting
`vix_was_filled=True` and `vix_age_trading_days=1`. Consecutive gaps are never
propagated.

### Source quirks and choices

| Quirk / judgment | Options considered | Choice | Rationale |
|---|---|---|---|
| Multi-table portfolio archives | Parse every numeric row; select equal-weighted; select value-weighted | Select only the first explicitly labeled value-weighted daily block | Matches the official UMD construction and prevents table bleed. |
| Missing sentinels | Treat as returns; drop rows; convert to `NaN` | Convert `-99.99` and `-999` to `NaN` before percent conversion | These are documented French missing codes, not economic returns. |
| Six-portfolio preamble says CRSP database `0` and copyright `0` | Infer a missing vintage; reject archive; preserve quirk | Preserve and report the upstream text; do not infer a value | The observation range and bytes are auditable, while guessing the malformed preamble would fabricate metadata. |
| Network-restricted execution | Silently substitute another vendor; fabricate data; import existing official archives | Allow explicit offline import, recording import path, import time, original file mtime, source URL, and SHA256 | Preserves exact bytes and makes the non-download execution path visible. |
| Parquet engine initially unavailable locally | Write CSV with a `.parquet` suffix; loosen the requirement; wait for the pinned engine | Halted artifact generation, then installed pinned `pyarrow==25.0.0` when network access became available | A mislabeled or environment-dependent output would violate reproducibility. |
| FRED access initially blocked by environment policy | Route around the restriction; use a different VIX source; wait for official access | Halted VIX ingestion, then downloaded the official FRED CSV directly when access became available | The contract requires FRED VIXCLS and prohibits silent source substitution. |
| User-supplied UMD archive | Prefer it without comparison; prefer the existing cache; compare exact bytes | Compared SHA256 and retained the existing cache because both hashes equal `f4237e...78bcf` | Avoids creating two apparent vintages from identical bytes. |

### Final Task 1 data audit

All five raw sources have retrieval/import timestamps, source URLs, byte
counts, SHA256 hashes, raw units, conversions, and raw first/last observations
in `data/raw/manifest.json`. All generated Parquet files were read back and
checked for row counts, sorted unique dates, and `AS_OF_DATE` compliance.

| Dataset | First date | Last date | Rows | Raw SHA256 |
|---|---:|---:|---:|---|
| UMD | 1926-11-03 | 2026-05-29 | 26,152 | `f4237e2e36dffa13fd7823f55376316a94b5ac663af951dd9eaca8ed2c678bcf` |
| Research factors | 1926-07-01 | 2026-05-29 | 26,253 | `af8aec07d55c98caa15045a77b87455be68cb8847b2ee5bd03bf5c2c8a3f96e2` |
| 2×3 size–momentum | 1926-11-03 | 2026-05-29 | 26,152 | `55f0ca390ca3367313ce79d72c48e7cd2ba199d9df4807432cc0bd2a4a4cdd81` |
| Momentum deciles | 1926-11-03 | 2026-05-29 | 26,152 | `a19daa6c84ef6232f3f867159e2752c2a437d5990d6f3bf673fd91317eab6093` |
| FRED VIXCLS raw | 1990-01-02 | 2026-07-23 | 9,538 dated rows | `cd23b4782a91a5bf9be5782fdf9d90a9d2a91ed1b472fbc4486dd824e05b1149` |

Across the full common history, reconstructed UMD has correlation
0.9999865369 with published UMD, mean absolute residual 0.0000292769, RMSE
0.0000409094, and maximum absolute residual 0.0001000000. The first usable
formation-spread date is 1927-09-28, with 25,880 usable rows through
2026-05-29.

The VIX-aligned table has 26,152 UMD-calendar rows from 1926-11-03 through the
frozen `AS_OF_DATE`. Its 16,983 rows before 1990-01-02 are structural
pre-coverage missingness. There are 9,166 observed VIX values through
2026-05-29 and exactly three unexpected missing values within coverage:
1991-03-01, 1997-01-31, and 1997-11-26. The primary output retains all three as
`NaN`. The separately named one-day-fill sensitivity fills exactly these dates
from their immediately preceding UMD trading rows and marks them with
`vix_was_filled=True` and `vix_age_trading_days=1`.

The environment is locked in `uv.lock`. The final audit re-read all seven
Parquet artifacts, rechecked all five raw hashes, verified
`mkt_total_return == mkt_rf + rf`, rechecked the leg identities and UMD
tolerances, and confirmed that every processed date is on or before
2026-05-29. A complete rerun produced identical SHA256 hashes for all seven
Parquet files. The audited runtime is Python 3.11.14, NumPy 2.4.4, pandas
3.0.2, PyArrow 25.0.0, and scikit-learn 1.8.0.

### Task 1 review status

Approved by the project owner on 2026-07-24.

## Task 2 — Label construction decisions

### Stored label tables

Labels are stored in separate full-history files for \(h=5\) and \(h=20\).
Each row contains the assessment date, compounded forward return,
`label_start_date`, `label_end_date`, `label_available_date`, all PIT
thresholds, the matured-history count, sensitivity labels, and the primary
episode fields. The final \(h\) assessment rows have unknown forward returns
and labels because their windows extend beyond `AS_OF_DATE`; they remain
`NaN` rather than being dropped or silently treated as non-events.

For each horizon, a forward return is calculated as

\[
\text{fwd\_mom\_return}_{h,t}
=
\exp\left(\sum_{j=1}^{h}\log(1+r^{mom}_{t+j})\right)-1.
\]

This is algebraically identical to direct compounding and excludes the
assessment-day return.

### Maturity, threshold, and early-history choices

At row \(t\), the forward-return series is shifted by exactly \(h\) UMD
trading rows before applying an expanding quantile. Thus the newest permitted
threshold observation was assessed at \(t-h\) and has a label window ending
at \(t\). The most recent \(h\) historical assessments remain excluded. PIT
quantiles use pandas' deterministic `linear` interpolation.

The prompt requires ten years of mature history before the first model-sample
label but also requests descriptive validation against 1932. Applying a
ten-year minimum to the entire 1926-starting historical series would make the
1932 check impossible. The following two-tier rule is therefore used:

- descriptive label-history thresholds begin after 252 matured observations;
- at the conservative VIX-bound model proxy start, 1990-01-02, every horizon
  must have at least 2,520 matured observations and at least ten calendar years
  between the earliest available historical label and model entry.

The 252-observation early-history choice affects only descriptive historical
episodes. It is not a relaxation for any model row.

### Sensitivities and prior state

The 2.5% and 10% labels use the same maturity shift, minimum history, and
interpolation as the primary 5% label. The prior-strength sensitivity is

\[
\text{mom\_tail\_loss}_{h,t}
\quad\land\quad
\left(
\text{trailing\_umd\_return}_{63,t}
>
\text{PIT median of trailing 63-day UMD returns through }t
\right).
\]

The PIT median may include the current trailing-state observation because all
of its component returns are known at assessment close \(t\). It never uses a
future return. These sensitivity labels are stored and reported but are not
eligible model targets.

The descriptive phrase "preceded by positive trailing 63-day UMD return" is
operationalized at each primary episode onset using the compounded UMD return
over the 63 trading rows ending at that assessment date. This state includes
date \(t\) but none of the label's forward window.

### Episode rule

The daily primary target is not altered. Event rows share an episode until at
least five consecutive valid non-event assessment days occur; the next event
then starts a new integer `event_episode_id` and has `event_onset=True`.
Non-event and unknown-label rows have no episode ID. Unknown rows do not count
as quiet days.

### Task 2 results

| Horizon | Full-history valid days | Event days | Event rate | Episodes | VIX-start valid days | VIX-start event days | VIX-start event rate | VIX-start episodes |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 | 25,891 | 1,295 | 5.0017% | 340 | 9,164 | 680 | 7.4203% | 173 |
| 20 | 25,861 | 1,340 | 5.1815% | 134 | 9,149 | 628 | 6.8641% | 57 |

At the 1990-01-02 conservative model-start proxy, the 5-day threshold has
16,979 matured observations and the 20-day threshold has 16,964, versus the
required 2,520. The newest threshold source rows are 1989-12-22 and
1989-12-01 respectively; both label windows end exactly on 1990-01-02. The
first descriptive PIT thresholds occur on 1927-09-09 for \(h=5\) and
1927-09-27 for \(h=20\). The last fully mature assessment rows are
2026-05-21 and 2026-04-30 respectively.

| Horizon | Sensitivity | Valid days | Event days | Event rate | Episodes |
|---:|---|---:|---:|---:|---:|
| 5 | 2.5% tail | 25,891 | 673 | 2.5994% | 186 |
| 5 | 10% tail | 25,891 | 2,570 | 9.9262% | 569 |
| 5 | 5% tail and prior strength above PIT median | 25,834 | 689 | 2.6670% | 210 |
| 20 | 2.5% tail | 25,861 | 759 | 2.9349% | 79 |
| 20 | 10% tail | 25,861 | 2,611 | 10.0963% | 241 |
| 20 | 5% tail and prior strength above PIT median | 25,819 | 812 | 3.1450% | 107 |

Of primary episode onsets with an observed trailing state, 253 of 340
(74.41%) for \(h=5\) and 107 of 134 (79.85%) for \(h=20\) were preceded by
positive trailing 63-day UMD performance.

### Historical sanity checks

| Window | 5-day event days / episodes touched | Worst 5-day forward UMD | 20-day event days / episodes touched | Worst 20-day forward UMD |
|---|---:|---:|---:|---:|
| 1932 | 61 / 6 | -16.06% | 65 / 3 | -32.18% |
| 2009 H1 | 50 / 6 | -14.31% | 56 / 2 | -30.04% |
| November 2020 | 10 / 2 | -13.52% | 8 / 1 | -19.50% |
| January 2021 | 0 / 0 | -1.88% | 3 / 1 | -7.25% |

January 2021 does not cross the 5-day PIT fifth-percentile threshold, but it
does cross the 20-day threshold. This is retained as an honest horizon
difference rather than forcing both labels to match a named episode.

### Leakage and reproducibility audit

For both horizons, forward returns were compared with direct manual
compounding on pre-specified dates. PIT thresholds were independently
recomputed from only rows \(s\) whose label end was on or before \(t\).
Changing every UMD return after 2020-01-02 to an extreme positive value left
all PIT thresholds through that date bit-for-bit unchanged. Every episode
onset after the first has the required five immediately preceding non-event
days. No oracle threshold column exists. Both label Parquets and
`outputs/task2_label_audit.json` have stable SHA256 hashes across a complete
rerun.

## Task 3 — Market feature engineering

Task 2 was approved before Task 3 began. Task 3 adds market-only predictors;
text and positioning features remain explicitly deferred.

### Shared conventions

For a return series \(r\), the compounded return over the \(L\) rows ending
at assessment date \(t\) is

\[
\mathrm{CR}_{L,t}=\prod_{j=0}^{L-1}(1+r_{t-j})-1.
\]

Rolling standard deviations, variances, covariances, and correlations use a
complete window and sample degrees of freedom (`ddof=1`). Volatility and
variance are left in daily, unannualized units. No market return or derived
feature is backfilled. Unless a feature says otherwise, lag zero means that
its window ends on assessment date \(t\), consistent with the approved
post-close / next-session action convention.

`PITPct(x_t)` is the weak empirical CDF of the current observation among only
the valid observations available through \(t\):

\[
\mathrm{PITPct}(x_t)=
\frac{\#\{s\le t:x_s\le x_t\}}{\#\{s\le t:x_s\text{ is observed}\}}.
\]

It is expanding, not a percentile computed over the full sample.

### Feature catalog

The first-usable dates below are observed dates in the frozen Task 1 data, not
lookback estimates.

| Feature | Mechanism | Formula / construction | Lookback | Lag | First usable | Expected relationship to reversal risk | Missing-value rule | Leakage note |
|---|---|---|---:|---:|---|---|---|---|
| `mom_return_21d` | Recent momentum strength / crowding | \(\mathrm{CR}_{21,t}(\mathrm{UMD})\) | 21 | 0 | 1926-11-27 | Higher may raise risk conditionally | Require 21 observations | Ends at \(t\) |
| `mom_return_63d` | Medium-horizon momentum strength | \(\mathrm{CR}_{63,t}(\mathrm{UMD})\) | 63 | 0 | 1927-01-18 | Higher may raise risk conditionally | Require 63 observations | Ends at \(t\) |
| `mom_return_126d` | Persistent momentum strength | \(\mathrm{CR}_{126,t}(\mathrm{UMD})\) | 126 | 0 | 1927-04-04 | Higher may raise risk conditionally | Require 126 observations | Ends at \(t\) |
| `mom_drawdown_252d` | Damage already sustained by momentum | Current UMD wealth divided by its maximum over the trailing 252 rows, minus one | 252 | 0 | 1927-09-02 | Ambiguous: stress may persist or exhaust | Require 252 observations | Trailing peak only |
| `mom_vol_21d` | Short-run instability | Sample SD of UMD returns | 21 | 0 | 1926-11-27 | Positive | Require 21 observations | Trailing window only |
| `mom_vol_63d` | Persistent instability | Sample SD of UMD returns | 63 | 0 | 1927-01-18 | Positive | Require 63 observations | Trailing window only |
| `vix_close` | Option-implied market stress | Untransformed FRED `VIXCLS` close | Point | 0 | 1990-01-02 | Positive | Preserve structural pre-coverage missingness and the three unfilled gaps | Economic-date value under the approved timing convention |
| `mkt_return_504d` | Broad-market regime | \(\mathrm{CR}_{504,t}(\mathrm{Mkt-RF})\) | 504 | 0 | 1928-07-12 | Lower values imply more reversal risk | Require 504 observations | Trailing window only |
| `bear_state` | Bear-market state | \(1[\texttt{mkt\_return\_504d}<0]\) | 504 | 0 | 1928-07-12 | Positive | Missing if the 504-day return is missing | Uses contemporaneously known trailing return |
| `mkt_variance_126d` | Market turbulence | Sample variance of `Mkt-RF` | 126 | 0 | 1927-04-04 | Positive | Require 126 observations | Trailing window only |
| `bear_x_mkt_variance_126d` | Turbulent bear regime | `bear_state * mkt_variance_126d` | 504 / 126 | 0 | 1928-07-12 | Positive | Missing if either input is missing | Inputs are point-in-time |
| `mkt_vol_percentile_126d` | Relative market stress | `PITPct(sqrt(mkt_variance_126d))` | 126 plus expanding history | 0 | 1927-04-04 | Positive | Missing until 126-day volatility exists | Expanding weak ECDF through \(t\) only |
| `mkt_return_1d` | Immediate rebound | Current `Mkt-RF` return | 1 | 0 | 1926-11-03 | Positive in a stressed rebound; ambiguous alone | Preserve source missingness | Current close only |
| `mkt_return_5d` | Short rebound | \(\mathrm{CR}_{5,t}(\mathrm{Mkt-RF})\) | 5 | 0 | 1926-11-08 | Positive in a stressed rebound; ambiguous alone | Require 5 observations | Ends at \(t\) |
| `mkt_return_20d` | Medium rebound | \(\mathrm{CR}_{20,t}(\mathrm{Mkt-RF})\) | 20 | 0 | 1926-11-26 | Positive in a stressed rebound; ambiguous alone | Require 20 observations | Ends at \(t\) |
| `stress_rebound` | Rebound during a stressed bear regime | `bear_state * mkt_vol_percentile_126d * max(mkt_return_5d, 0)` | 504 / 126 / 5 | 0 | 1928-07-12 | Positive | Missing if an input is missing | All components end at \(t\) |
| `loser_leg_return_5d` | Short squeeze in prior losers | \(\mathrm{CR}_{5,t}(\mathrm{Lo\,10})\) | 5 | 0 | 1926-11-08 | Positive | Require 5 observations | Uses the research-return loser leg through \(t\) |
| `loser_leg_return_20d` | Sustained loser rebound | \(\mathrm{CR}_{20,t}(\mathrm{Lo\,10})\) | 20 | 0 | 1926-11-26 | Positive | Require 20 observations | Uses the research-return loser leg through \(t\) |
| `loser_leg_vol_21d` | Loser-leg instability | Sample SD of `Lo 10` returns | 21 | 0 | 1926-11-27 | Positive | Require 21 observations | Trailing window only |
| `loser_minus_winner_vol_21d` | Asymmetric instability across legs | \(SD_{21}(\mathrm{Lo\,10})-SD_{21}(\mathrm{Hi\,10})\) | 21 | 0 | 1926-11-27 | Positive | Require both 21-day leg windows | Difference of separately estimated trailing volatilities |
| `formation_spread` | Formation-period winner–loser separation | \(\mathrm{CR}_{252,t-21}(\mathrm{Hi\,10})-\mathrm{CR}_{252,t-21}(\mathrm{Lo\,10})\) | 252 observations after a 21-row shift | 0 | 1927-09-28 | Larger spreads may indicate crowding; sign may be nonlinear | Require both complete 252-row formation windows | Explicitly skips the most recent 21 rows; the full span is 273 trading rows |
| `mom_mkt_beta_126d` | Momentum's market exposure | \(Cov_{126}(\mathrm{UMD},\mathrm{Mkt-RF})/Var_{126}(\mathrm{Mkt-RF})\) | 126 | 0 | 1927-04-04 | More positive exposure can amplify rebounds; state-dependent | Require a complete window and nonzero market variance | Trailing covariance only |
| `mom_mkt_corr_126d` | Momentum–market coupling | Rolling sample correlation of UMD and `Mkt-RF` | 126 | 0 | 1927-04-04 | State-dependent | Require a complete, nondegenerate window | Trailing correlation only |
| `beta_change_21d` | Fast change in market exposure | `mom_mkt_beta_126d[t] - mom_mkt_beta_126d[t-21]` | 126 plus 21 | 0 | 1927-04-29 | A rapid increase is expected to raise rebound sensitivity | Require current and 21-row-prior betas | Both beta estimates are available by \(t\) |

### Judgment calls frozen for Task 3

| Question | Decision | Rationale |
|---|---|---|
| Is VIX only a sample boundary or also a feature? | `vix_close` is a mandatory model feature. `vix_was_filled` and `vix_age_trading_days` are retained only as audit columns. | Otherwise the required VIX-bound sample would affect row eligibility without supplying the model any VIX information. The primary VIX series is unfilled, as approved in Task 1. |
| Should rolling volatility be annualized? | No; daily units are retained. | Scaling adds no model information and daily units keep formulas directly auditable. |
| How is the volatility percentile ranked? | Weak expanding empirical CDF through the current row. | It is deterministic, bounded in \([0,1]\), includes information known at close \(t\), and never sees a future state. |
| How is momentum drawdown defined? | Drawdown from the maximum cumulative UMD wealth observed within the trailing 252 rows. | This is a genuine path-dependent trailing drawdown rather than a return proxy. |
| What does loser-minus-winner volatility mean? | Difference between the legs' separately estimated 21-day volatilities. | This measures which leg is more unstable; it is not the volatility of the daily loser-minus-winner spread. |
| How is beta change defined? | Level difference between current beta and beta 21 trading rows earlier. | This keeps interpretation in beta units and avoids an unstable percentage change near zero. |

### Task 3 sample and audit

The feature table has 26,152 UMD-calendar rows from 1926-11-03 through
2026-05-29 and 24 mandatory model features. Because `vix_close` is mandatory,
the first complete row and conservative model-sample start are both
1990-01-02. There are 9,169 rows on or after that date, of which 9,166 are
complete. The only incomplete rows are the three unfilled VIX gaps already
frozen in Task 1: 1991-03-01, 1997-01-31, and 1997-11-26. They remain missing
for later fold-local imputation; no feature-specific global fill was applied.

Direct formula checks were independently recomputed for 2020-11-06, covering
compounded returns, drawdown, beta, correlation, beta change, the expanding
volatility percentile, stress rebound, and loser-minus-winner volatility.
Changing every UMD, market, winner-leg, and loser-leg return after 2020-01-02
to extreme values left all 24 features through that cutoff bit-for-bit
unchanged. Range checks confirmed no infinities, correlations within
\([-1,1]\), percentiles within \([0,1]\), and drawdowns no greater than zero.
`data/processed/market_features.parquet` and
`outputs/task3_feature_audit.json` have stable SHA256 hashes across a complete
rerun.

## Task 4 — Validation and baselines

Task 3 was approved before Task 4 began. The validation split and episode
gate were evaluated before fitting any baseline or selecting any model. A
first implementation inadvertently exposed aggregate holdout counts, as
disclosed below.

### Frozen interpretation of the requested split rule

- The model sample begins on 1990-01-02, the Task 3 VIX-bound start.
- The first development test block begins ten calendar years later.
- Development tests are complete three-calendar-year half-open windows,
  advanced in three-year steps. A partial final development block is not
  emitted.
- The holdout boundary is the final three calendar years relative to the fixed
  `AS_OF_DATE`, beginning nominally on 2023-05-29. The split gate loads and
  reports only dates strictly before that boundary.
- Training expands from model start. For every split and horizon, a candidate
  training row is purged when `label_end_date >= test_start`.
- Episode counts are distinct approved Task 2 `event_episode_id` values
  touched by event-positive rows in the split. This is at least as permissive
  as counting only episode onsets inside the split.
- The minimum-five-test-episodes gate applies to every development fold
  before any model is fit. The production gate does not read, count, model, or
  score holdout outcomes.

Seven complete development blocks are available for each horizon. Every
5-day block passes, with between 8 and 25 test episodes. The 20-day horizon
fails in two blocks:

| Split | Test range | Event days | Distinct episodes | Required |
|---|---|---:|---:|---:|
| `dev_01` | 2003-01-02 through 2005-12-30 | 36 | 3 | 5 |
| `dev_04` | 2012-01-03 through 2014-12-31 | 14 | 2 | 5 |

Per the explicit instruction to halt when any fold has fewer than five test
episodes, no B0/B1/B2 model has been fit, no development or holdout prediction
has been generated, and the holdout has not been used for model selection.
`outputs/split_manifest.csv` contains the full row-level split audit and
`outputs/task4_split_gate.json` records the blocking folds.

During the first implementation check, aggregate holdout event-day and episode
counts were inadvertently computed before the failed development gate was
handled. No model was fit and no model or threshold choice was made from those
counts. The code and published manifest were corrected immediately to
quarantine all holdout rows, but the aggregate counts were observed by the
research process; therefore the originally designated final-three-year
holdout cannot honestly be called perfectly unseen. A replacement or explicit
acceptance of this limited contamination is required before eventual holdout
reporting.

### Approved split resolution

A read-only count check was used only to identify viable options for review.
Keeping a three-year step, four-year test windows still fail with a minimum of
four 20-day episodes; five-year windows pass exactly with a minimum of five;
six-year windows pass with a minimum of eight. Using six-year non-overlapping
windows also passes, with a minimum of nine, but yields only three development
tests.

The six-year non-overlapping option was approved after the gate report.
`test_block_years=6` and `step_years=6` now apply to both horizons. The
three development tests are 2000–2005, 2006–2011, and 2012–2017. All choices
described below are frozen using this development design before the retained
final-three-year holdout is scored. The limited aggregate-only holdout
contamination disclosed above is accepted; no holdout prediction or
performance metric had been inspected.

### Specification frozen before holdout

The following specification was frozen after development generation and
before any holdout prediction:

- B0 is one constant probability per split and horizon: the primary event
  rate among the purged training rows. Every contributing label has
  `label_end_date < test_start`, so this is a point-in-time matured rate.
- B1 is an unweighted logistic regression on `bear_state`,
  `mkt_variance_126d`, and `bear_x_mkt_variance_126d`.
- B2 is an unweighted logistic regression on all 24 Task 3 model features.
- Both logistic models use fold-local median imputation, fold-local
  standardization, L2 regularization with `C=1`, the `lbfgs` solver, and no
  class weighting. No hyperparameter is selected from development metrics.
- Each fold fits a new sklearn `Pipeline`; neither imputation nor scaling is
  fit on pooled development or holdout data.
- The reported metrics are log loss, Brier score, PR-AUC, ROC-AUC,
  calibration intercept and slope, and event capture in the highest-ranked
  10% of rows. Calibration intercept and slope come from an unpenalized
  logistic regression of the event on predicted log odds. A constant
  per-fold B0 has undefined calibration slope; its intercept is reported as
  calibration-in-the-large.
- Calibration tables use up to ten equal-frequency probability buckets;
  duplicate probability edges are collapsed. Exact top-decile row counts use
  `ceil(0.10 * n)` with assessment date as a deterministic tie-break, making
  B0's top-decile capture diagnostic rather than economically ranked.
- No 0.5 classification threshold and no alternative alert threshold is
  defined. Alert policy remains deferred until an explicit cost or capacity
  rule is supplied.

This immutable specification is serialized and SHA256-hashed in
`outputs/task4_development_audit.json`. Holdout execution must reproduce that
hash or halt.

### Development results

The three development test blocks contain 4,528 assessment rows per horizon.
They contain 416 event days across 99 distinct episodes for the 5-day target
and 404 event days across 33 distinct episodes for the 20-day target.

| Horizon | Baseline | Log loss | Brier | PR-AUC | ROC-AUC | Calibration intercept | Calibration slope | Event capture, top decile |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 5 | B0 | 0.3343 | 0.0861 | 0.0785 | 0.3984 | -4.180 | -0.644 | 2.16% |
| 5 | B1 | 0.3431 | 0.0895 | 0.3005 | 0.7707 | -1.533 | 0.369 | 35.58% |
| 5 | B2 | 0.9440 | 0.1685 | 0.2798 | 0.7880 | -2.212 | 0.177 | 35.10% |
| 20 | B0 | 0.3334 | 0.0842 | 0.0762 | 0.3885 | -4.157 | -0.600 | 1.49% |
| 20 | B1 | 0.2966 | 0.0806 | 0.3737 | 0.8106 | -1.344 | 0.464 | 42.57% |
| 20 | B2 | 0.6133 | 0.1130 | 0.2485 | 0.7396 | -1.787 | 0.172 | 37.62% |

Pooled B0 ROC-AUC can differ from 0.5 because its constant is re-estimated in
each test block and the three block-level rates differ; B0 ROC-AUC is exactly
0.5 within every individual fold. Its pooled ranking and top-decile numbers
are not economically meaningful.

B1 shows useful out-of-time ranking, particularly for the 20-day target. B2
also ranks risk for the 5-day target but produces extreme probability shifts
in the first two development blocks. Its low pooled calibration slopes and
poor log loss are evidence of substantial temporal instability, not a reason
to tune on the holdout. B2 remains the pre-specified primary model, with this
weak calibration evidence retained honestly.

### Single holdout report

The frozen specification hash matched before the holdout was evaluated. The
5-day holdout contains 748 valid assessment rows, 31 event days, and 17
episodes. The 20-day holdout contains 733 valid rows, 9 event days, and only
one episode.

| Horizon | Baseline | Log loss | Brier | PR-AUC | ROC-AUC | Calibration intercept | Calibration slope | Event capture, top decile |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 5 | B0 | 0.1831 | 0.0410 | 0.0414 | 0.5000 | -0.660 | undefined | 9.68% |
| 5 | B1 | 0.1712 | 0.0397 | 0.0966 | 0.6357 | 0.320 | 1.273 | 12.90% |
| 5 | B2 | 0.1715 | 0.0402 | 0.0785 | 0.6550 | -1.040 | 0.739 | 19.35% |
| 20 | B0 | 0.1070 | 0.0158 | 0.0123 | 0.5000 | -1.846 | undefined | 0.00% |
| 20 | B1 | 0.0943 | 0.0146 | 0.0117 | 0.4283 | -13.854 | -3.080 | 0.00% |
| 20 | B2 | 0.0848 | 0.0147 | 0.0143 | 0.5583 | -4.051 | 0.101 | 0.00% |

For the 5-day target, B1 and B2 both improve log loss over B0. B2 has the
highest ROC-AUC and top-decile capture, while B1 has the best Brier score and
PR-AUC. The single 20-day holdout episode makes its ranking, capture, and
calibration estimates too fragile for model-selection claims.

### Artifacts and integrity audit

`outputs/baseline_predictions.parquet` contains development and holdout
probabilities. `outputs/baseline_metrics.csv`,
`outputs/calibration_table.csv`, `outputs/model_coefficients.csv`, and
`outputs/preprocessing_statistics.csv` contain the requested reports and
fold-level provenance. Separate development and holdout files preserve the
evaluation boundary. `notebooks/01_baseline_eda.ipynb` has 12 cells and
covers cumulative UMD with episode onsets, winner/loser behavior inside event
days, feature distributions, baseline metrics, and calibration plots.

The read-only final audit independently recomputed all 48 saved log-loss,
Brier, PR-AUC, and ROC-AUC values; reconciled 24 calibration row/event totals;
confirmed strict train/test ordering, horizon-exact purges, non-overlapping
development and holdout predictions, fold-specific preprocessing statistics,
valid probability bounds, and a fully executed notebook with no error output.
The results and artifact hashes are stored in
`outputs/task4_validation_audit.json`. The holdout was not refit or rescored
during this final audit.

## Task 5 — Tests and Phase 1 handoff

Task 4 was approved and frozen before Task 5 began. “Frozen” means the
validation design, feature sets, preprocessing, logistic specification,
metrics, and one-time holdout interpretation cannot be changed in response to
holdout performance. A substantive change would require a newly reserved
evaluation period. Documentation corrections and correctness bugs remain
eligible for transparent repair, with any effect on frozen results disclosed.

Seven pytest tests cover forward-return alignment, threshold maturity and
future-data invariance, episode de-clustering, strict purged walk-forward
ordering, fold-local preprocessing, real-data UMD reconstruction, and stable
artifact hashes under the fixed `AS_OF_DATE`. All seven pass.

While constructing the handoff's exact-lag table, one Task 3 documentation
formula was found to say that `formation_spread` compounded 231 observations.
The implementation, Task 1 audit, first-usable date, and frozen artifact all
use 252 observations after a 21-row shift. The table was corrected to the
implemented formula, \(\mathrm{CR}_{252,t-21}\), and no data, feature,
prediction, or metric changed.

`README.md` contains the end-to-end reproduction commands, public source URLs,
artifact guide, and limitations. `outputs/phase1_review.md` records the label
rationale, rejected variants, exact feature lags, thresholds, split and event
tables, probability and calibration results, strongest and weakest evidence,
unresolved limitations, and Phase 2 interface requirements.

Phase 1 is complete at the Task 5 review gate. No GDELT spike, text ingestion,
positioning ingestion, Phase 2 feature, or Phase 2 model has been created.
