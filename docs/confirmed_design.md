# Confirmed design: top-down momentum crash risk monitor

Status: design baseline updated through Phase 2, 2026-07-27.

## 1. Product objective

The repository will become a transparent research prototype that answers, in
order:

1. What macro and market regime is active?
2. What does a synthetic S&P 500 12-1 momentum portfolio own and short?
3. Is risk concentrated in the long leg or the short leg?
4. Which deterministic thresholds are triggered?
5. Is price momentum supported by improving, sector-normalized fundamentals,
   and is portfolio risk concentrated?
6. What external evidence supports or challenges those deterministic facts?

The deterministic monitor is the source of truth. Retrieval and language-model
output may add evidence, analogs, uncertainty, and research questions, but may
not create or modify trigger values.

The principal mechanism is a volatile recovery after a severe drawdown in
which distressed, high-beta recent losers rally sharply. Recovery by itself is
not a high-risk state.

## 2. Current repository audit

### 2.1 Active path

The current command is `python -m src.pipeline`. It produces a
Daniel–Moskowitz-inspired state, a point-in-time conditional tail-loss
frequency, a frozen B2 shadow prediction, a heuristic reversal checklist,
FINRA and GDELT overlays, gated evidence, and a Markdown PM brief.

| Area | Current modules | Current role |
|---|---|---|
| Active orchestration | `src/pipeline.py` | Builds one current MVP assessment and PM brief |
| Primary state | `src/risk/dm_engine.py` | DM-inspired bear/variance state and matured-label conditional frequency |
| Active contracts | `src/mvp/contracts.py` | Validated immutable assessment objects |
| Shadow model | `src/benchmarks/b2_shadow.py` | Reads a frozen B2 out-of-sample prediction; cannot alter primary state |
| Heuristic conditions | `src/experiments/reversal_checklist.py` | Explains preconditions and rebound triggers; research-only |
| Overlays | `src/overlays/snapshots.py` | Reads FINRA positioning and GDELT narrative panels |
| Evidence | `src/evidence/mvp.py`, `archived_provider.py`, `versioned_classifier.py` | Elevated-state gate, archive cutoff checks, retrieval hashing, grounded classifications |
| Reporting | `src/reporting/pm_brief.py` | Deterministic Markdown report |

### 2.2 Research and retained legacy modules

| Area | Modules | Disposition |
|---|---|---|
| Source acquisition | `src/data/` | Reuse selectively |
| Labels and market features | `src/features/labels.py`, `market_features.py`, `legs.py` | Reuse pure calculations and PIT patterns |
| Current-universe positioning | `src/features/positioning_panel.py` | Reuse calculations; do not treat its universe as the S&P 500 |
| Narrative panels | `src/features/gdelt.py`, `narrative_panel.py` | Optional evidence/attention inputs only |
| B0/B1/B2 modeling | `src/modeling/baselines.py`, `validation.py`, `audit.py` | Retained historical validation, not the new decision engine |
| B2c/B3 text ablation | `src/modeling/phase2.py` | Historical research only |
| Legacy monitor contracts and adapters | `src/monitoring/` | Reuse small helpers only; do not revive the B2-led risk path |
| Retrieval evaluation | `src/evaluation/retrieval_gold.py` | Reuse for evidence-quality validation |
| Notebooks | `notebooks/01_baseline_eda.ipynb`, `02_pm_prototype_validation.ipynb` | Historical research artifacts |

No new source module was added in Phase 0.

### 2.3 Current data sources and artifacts

| Source | Current use | Important limitation |
|---|---|---|
| Ken French daily momentum factor | Published UMD returns and labels | Factor portfolio, not named S&P 500 constituents |
| Ken French daily research factors | Broad US market total-return proxy (`Mkt-RF + RF`) and risk-free rate | Not a named S&P 500 cash index; source lacks per-observation publication timestamps |
| Ken French six size–momentum portfolios | Winner and loser leg return reconstruction | Aggregate factor legs, no constituent holdings |
| Ken French ten momentum portfolios | 12-2 formation spread | Aggregate deciles, no named holdings |
| FRED `VIXCLS` | VIX close and model-sample boundary | Three historical missing dates remain missing in the primary panel |
| Nasdaq stock screener | Current top-200 US large-cap universe | Current membership applied historically; not an S&P 500 universe |
| Yahoo Finance chart API, with Stooq fallback | Adjusted prices and volumes for the current top-200 universe | Current-universe survivorship bias; history starts in 2016 |
| State Street SPY daily holdings | Dated 503-name current S&P 500 proxy for Phase 2 | One current snapshot applied historically; not PIT membership |
| Yahoo Finance chart API | Total-return adjusted prices for all 503 Phase 2 names and the Phase 3 SPY beta proxy | Public-vendor data and current-constituent survivorship bias; SPY is an ETF proxy, not the official index |
| FINRA short interest and consolidated off-exchange short volume | Loser-leg crowding proxies | Short volume is flow, not a consolidated position |
| SEC EDGAR company facts | Shares outstanding for short-interest utilisation; future filing-date fundamental momentum inputs | Full Company Facts coverage is currently too sparse to enable the fundamental monitor |
| GDELT DOC 2.0 | Aggregate panic, crowding, and risk-off attention | Current active panel is volume-only and incomplete |
| Committed evidence corpus and fixtures | Retrieval and classification demonstrations | Default fixtures were curated after the historical dates and are not a strict historical text backtest |

Processed data now also includes 1,293,310 S&P 500 proxy price rows for
2016-01-04 through 2026-07-27, 2,280 dated momentum holdings rows, and 2,365
complete daily portfolio returns.

### 2.4 Existing point-in-time safeguards

The following controls are sound and should be preserved:

- Every run has a frozen as-of date, and active market inputs are filtered
  through it.
- Assessment timing is post-close on date `t`, with earliest action in the
  next session.
- Forward labels cover `t+1` through `t+h` and become usable only on
  `label_available_date = label_end_date`.
- Expanding label thresholds include only matured forward windows; model
  training also purges labels crossing a test boundary.
- Rolling market features use trailing observations only. GDELT normalization
  is prior-only.
- Monthly loser-leg membership is formed at the prior month-end and is fixed
  during the next month.
- FINRA short interest is joined on publication date, not settlement date.
- SEC shares outstanding is joined on filing date.
- GDELT calendar information is mapped into the next complete trading-date
  information interval; confirmed zero and unavailable data are distinct.
- Evidence must be published, discovered, available, and archived by the
  assessment cutoff. Retrieval and classifier inputs are hash-bound.
- Missing or unclassified evidence cannot become a low-risk conclusion.
- The evidence layer has no reference that permits it to mutate the primary
  risk assessment.

Known qualifications:

- The French and FRED daily files do not expose exact historical release
  timestamps, so the post-close convention is an explicit assumption.
- The current symbol universe is survivorship-biased.
- The current price history and SEC/FINRA coverage are not a point-in-time
  S&P 500 membership history.

### 2.5 Current labels

For horizons `h` of 5 and 20 trading days, the current primary research label
is:

`mom_tail_loss_h = 1[compound(UMD returns from t+1 through t+h) <
PIT expanding fifth percentile]`.

The expanding percentile uses only fully matured historical forward windows.
Sensitivity labels use 2.5% and 10% quantiles and a prior-strength condition.
Event days are grouped into episodes after five consecutive non-event days.
Ten years of matured history is required before the original model sample.

These labels remain useful for historical validation and threshold calibration.
They will not be the new monitor's live risk decision.

### 2.6 Current DM and B0/B1/B2/B3 logic

| Name | Definition in the repository | Role after re-scope |
|---|---|---|
| DM/PIT | Negative trailing 504-day broad-market return plus 126-day variance; `panic_elevated` when bear-state variance is at least its expanding PIT bear-state mean | Reuse and extend as the macro-regime foundation |
| B0 | Constant matured event rate inside each purged training sample | Historical base-rate reference only |
| B1 | Unweighted logistic model on bear state, market variance, and their interaction | Historical validation only |
| B2 | Unweighted L2 logistic model on 24 market features, with fold-local median imputation and scaling | Frozen shadow benchmark only |
| B2c | Phase 2 common-sample version of B2 | Historical text-ablation comparator only |
| B3 | B2c plus aggregate attention, breadth, and tone features | Historical ablation only; not an active risk decision |

There is no active B3 path in `src/pipeline.py`.

### 2.7 Existing portfolio construction and market features

The current repository has two distinct constructions:

- The main factor path uses published Ken French UMD and reconstructs aggregate
  winner and loser returns as equal averages of small/big high- and
  low-momentum portfolios. It has no security holdings or security weights.
- The positioning path ranks a current top-200 large-cap universe on 12-2
  momentum, assigns the bottom decile to a proxy loser leg, and applies that
  membership in the following month. It does not construct a long leg or a
  dollar-neutral return series and is not an S&P 500 portfolio.

The existing market panel has 24 features covering momentum returns and
drawdown, momentum volatility, VIX, a 504-day market return, bear state,
126-day market variance and volatility percentile, 1/5/20-day market returns,
a stress-rebound interaction, aggregate loser-leg returns and volatility,
formation spread, momentum-to-market beta/correlation, and beta change.

Useful missing state variables are recovery from trough, explicit early/high-
volatility recovery states, and a documented rate-policy/liquidity state.

### 2.8 Existing retrieval and text components

The active evidence path already provides most safety controls needed later:

- retrieval is gated on an elevated deterministic state;
- fixture replay and strict archived point-in-time modes are visibly distinct;
- the archived path validates corpus inventory and timestamps, deduplicates
  documents, uses a frozen mechanism query, and records hashes;
- a versioned classifier response must match the exact retrieval before any
  supporting or contradicting claim is emitted;
- claims include exact grounded passages and citations;
- no qualifying documents is `unavailable`, not benign.

The current output is narrower than the confirmed schema. It counts supporting,
contradicting, and contextual items, but does not yet return historical analogs,
research questions, explicit confidence, missing evidence, or a clean
deterministic-facts/AI-interpretation separation.

### 2.9 Existing tests

The suite contains 24 test modules. On 2026-07-27:

`151 passed, 4 skipped`.

Coverage includes label maturity and future-data invariance, purged temporal
splits, fold-local preprocessing, DM state construction, contract validation,
positioning publication dates, prior-only normalization, GDELT mapping,
primary/shadow isolation, overlay immutability, evidence gating and citation
cutoffs, archive schemas and hashes, classifier grounding, and end-to-end
quiet/elevated assessments.

The four skips are rebuild/integration cases whose raw payload prerequisites
are absent. They are not test failures.

## 3. Confirmed target architecture

```text
point-in-time market and constituent data
        |
        +--> deterministic macro regime
        |
        +--> monthly S&P 500 12-1 holdings and returns
                    |
                    +--> long/short risk decomposition
                    +--> minimal breadth and concentration
                    +--> fundamental momentum alignment, when PIT-safe
        |
        v
row-oriented deterministic scorecard  [SOURCE OF TRUTH]
        |
        +--> historical rates and B2 as labeled reference views
        +--> FINRA/GDELT as labeled proxy overlays
        |
        v  deterministic flags trigger bounded retrieval
structured evidence, contradictions, analogs, questions, uncertainty
        |
        v
one reproducible demo artifact
```

Required invariants:

- Constituents, signals, and weights are dated separately.
- A formation date can use prices no later than that date, skips the most
  recent month, and governs returns only after formation.
- Long weights sum to `+1`, short weights to `-1`, and net exposure is zero.
- A short-leg return is reported as the return of the underlying short basket;
  its portfolio contribution has the opposite sign. Both labels must be
  explicit.
- All risk windows end on or before the as-of date.
- Every scorecard row records metric, threshold, comparison direction,
  triggered flag, severity, explanation, date, and source module.
- Threshold provenance is `literature`, `historical_quantile`, or
  `demo_threshold`.
- Missing inputs remain missing and cannot silently pass a threshold.
- AI output receives a copy of deterministic facts and cannot write back to
  them.

## 4. Gap analysis

| Confirmed capability | Current state | Gap |
|---|---|---|
| Macro drawdown/volatility state | Strong partial | Add trough recovery, early recovery, high-vol recovery, and rate-policy proxy |
| Synthetic S&P 500 10×10 portfolio | Phase 2 complete | Uses an official dated 503-name SPY snapshot and explicit current-constituent-proxy status |
| Point-in-time membership | Missing | Phase 2 freezes and labels a current-membership fallback; production still needs constituent history |
| Named long and short holdings | Phase 2 complete | Dated signal endpoints, formation, next-month weights, and returns are persisted |
| Leg beta and risk contribution | Phase 3 complete | Realized long, short-underlying, portfolio and conditional beta, volatility, signed contribution, drawdown, and recovery attribution are persisted |
| Deterministic row scorecard | Partial legacy checklist | Replace single-state presentation with auditable metric rows |
| Minimal breadth and concentration | Missing | Add effective bets, top-five contribution share, and sector concentration only |
| Fundamental Momentum Alignment | Missing and data-gated | Add sector-normalized revenue/EPS acceleration and margin change using filing dates; no standalone static quality phase |
| Crowding | Useful partial | Reuse contribution/sector concentration; retain FINRA as an explicitly labeled proxy |
| Minimal AI evidence | Strong partial | Adapt output schema and add analogs/questions/uncertainty without decision authority |
| Final top-down demo | Missing | Current PM brief does not answer holdings, leg-risk, breadth, or quality questions |

## 5. Reuse, deprecation, and future work

Reuse unchanged where possible:

- atomic I/O, hashing, date parsing, and PIT rolling helpers in `src/utils/`;
- French and VIX loaders and the broad-market return history;
- DM state history logic, after extracting reusable pure calculations;
- price parsing, symbol normalization, and trading-calendar utilities;
- FINRA publication-date and SEC filing-date controls;
- archived evidence contracts, cutoff checks, grounding, and hash binding;
- current test patterns for future-data perturbation and deterministic replay.

Retain but remove from the main decision path:

- B0/B1/B2 model training and all B2-led legacy monitoring;
- B2c/B3 aggregate-news ablation;
- the current single conditional-frequency presentation as the primary risk
  number;
- the current top-200 loser leg as if it were the target portfolio.

Defer beyond the MVP:

- a new ML regime classifier or probability model;
- ex-ante factor-risk modeling;
- full CRSP/Compustat-grade historical S&P 500 membership;
- standalone IC/IR analytics and large fundamental factor libraries;
- fragile scrapers for 13F, options, social media, or fund flows;
- a multi-agent AI architecture;
- automated trading or sizing recommendations.

## 6. Phase 0 acceptance

- Repository map: complete.
- Data, PIT safeguards, labels, DM/B0–B3 logic, portfolios, features, evidence,
  and tests: documented.
- Gap analysis against the confirmed architecture: complete.
- Reuse and deprecation boundaries: explicit.
- Plan sized to 10–15 hours: in `docs/development_plan.md`.
- New feature implementation: none.
