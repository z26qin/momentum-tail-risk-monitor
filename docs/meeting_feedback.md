# Meeting feedback and re-scope decisions

Status: confirmed input recorded during Phase 0, 2026-07-27.

## 1. Confirmed direction

The product is no longer primarily a conditional-frequency or fitted-
probability monitor. It is a top-down, deterministic risk-monitoring
prototype:

1. macro regime;
2. synthetic S&P 500 momentum portfolio;
3. long/short risk decomposition;
4. deterministic scorecard;
5. fundamental-momentum alignment and minimal concentration checks;
6. minimal evidence retrieval and AI research assistance;
7. one reproducible demonstration.

The deterministic layer owns the risk decision. AI may retrieve evidence,
challenge the interpretation, suggest analogs, and propose questions. It may
not generate the core decision or change deterministic values.

## 2. Mechanism that the system must distinguish

The relevant high-risk pattern is:

- a severe prior market drawdown;
- volatility that remains elevated;
- an early, rapid market recovery;
- a short leg populated by high-beta, low-quality, distressed, or deeply
  oversold names;
- a relatively defensive or quality long leg;
- a junk rally in which the short leg rebounds sharply.

A market recovery without high volatility and short-leg fragility is not
sufficient. The monitor must make this distinction visible in its states and
scorecard rows.

## 3. Changes to the current repository interpretation

| Existing element | Decision |
|---|---|
| DM/PIT bear and variance logic | Preserve as a core macro-state input, not the entire product |
| Conditional tail-loss frequency | Preserve as historical context, not the sole primary risk number |
| B0/B1 model ladder | Preserve for research history and validation |
| Frozen B2 probability | Keep as a clearly labeled shadow benchmark only |
| B2c/B3 text models | Retain as historical ablation work; do not reactivate |
| Heuristic reversal checklist | Reuse its interpretable precondition/trigger ideas, but replace ad hoc presentation with scorecard rows and threshold provenance |
| Ken French aggregate legs | Keep for literature/history checks; they cannot answer named-holding or constituent-risk questions |
| Current top-200 loser proxy | Keep only as an explicitly survivorship-biased FINRA overlay; it is not the required S&P 500 portfolio |
| Evidence safeguards | Preserve and extend to the new structured schema |
| Current PM brief | Replace at final integration with a top-down demo that answers the ten confirmed questions |

## 4. Portfolio decisions

The demonstration portfolio is:

- S&P 500 universe;
- point-in-time membership when reasonably available;
- explicit survivorship disclosure otherwise;
- 12-1 momentum, skipping the most recent month;
- monthly rebalance;
- top 10 names long and bottom 10 names short;
- equal-weighted legs;
- gross long exposure `+1`, gross short exposure `-1`, net exposure `0`;
- configurable leg size, with 10 names as the default demonstration.

The existing current top-200 Nasdaq screen cannot be relabeled or silently
used as the S&P 500.

## 5. Risk and scorecard decisions

Required leg-risk measures are realized beta, conditional up/down beta,
volatility, signed contribution, drawdown, beta gap, and short-leg loss
contribution during recovery windows. Ex-ante beta is acknowledged as a
production enhancement, not an MVP requirement.

The official risk artifact is a row-oriented scorecard. Every threshold must
identify its provenance as literature-based, a historical quantile, or a
clearly labeled demo threshold. Missing values remain missing.

The DM/B0/B1/B2/B3 names may be mapped for continuity, but their outputs are
not combined into an unexplained probability.

## 6. Fundamental alignment, breadth, and crowding decisions

The previous standalone breadth/IC/IR phase and static
quality/profitability phase are replaced by one focused Fundamental Momentum
Alignment Monitor.

The monitor first builds an independent universe-level fundamental-momentum
panel and only then maps it onto the price-selected portfolio. At each
rebalance it ranks 12-1 price momentum across the eligible S&P 500 universe,
calculates revenue-growth acceleration, EPS-growth acceleration, and
operating-margin change across all covered eligible stocks, and measures
universe and portfolio alignment.

Each fundamental component is normalized within industry when at least ten
valid peers exist; otherwise it falls back to sector. Filing or conservative
availability dates, rather than fiscal-period end, determine when facts may be
used. Analyst revisions remain excluded unless reliable point-in-time data
already exist.

Universe coverage is normal at 80% or more, degraded from 60% to below 80%,
and insufficient below 60%. A ten-name leg is normal with at least eight
covered names, degraded with six or seven, and insufficient below six.
Phase 5 first performs a full-universe Company Facts acquisition and coverage
audit rather than implementing a permanently disabled module.

The only retained low-cost breadth measures are effective number of bets,
top-five contribution share, and sector concentration. A full forward-return
IC/IR framework is out of scope.

Crowding work prioritizes the concentration measures already needed by the
portfolio. Existing FINRA measures remain labeled proxies. No large scraper
effort is approved for 13F, options, social media, ETF flows, or short-interest
extensions.

Sparse or unreliable fundamentals are configuration-gated and must not block
the macro, portfolio, beta, or deterministic scorecard paths. Phase 5 produces
a separate visible Fundamental Alignment Scorecard; the Phase 4 scorecard
remains unchanged.

## 7. Evidence decisions

Evidence retrieval is triggered by deterministic flags. Output must separate:

- deterministic facts;
- retrieved supporting evidence;
- retrieved contradicting evidence;
- AI interpretation;
- historical analog candidates;
- uncertainty and missing evidence;
- next research questions;
- citations.

The confirmed schema is:

- `risk_state`
- `triggered_metrics`
- `supporting_evidence`
- `contradicting_evidence`
- `historical_analogs`
- `research_questions`
- `citations`
- `confidence`
- `limitations`

Current archive cutoff, hash-binding, exact-passage grounding, and
fail-closed behavior remain mandatory. No multi-agent system is needed.

## 8. Explicit limitations accepted for the MVP

- Public point-in-time S&P 500 membership may be unavailable within the time
  budget. A frozen current S&P 500 snapshot is acceptable only when visibly
  labeled survivorship-biased.
- Realized beta is acceptable in place of production ex-ante beta.
- Public fundamentals may be sparse or restated. They may be disabled without
  blocking the deterministic price/risk monitor.
- Existing broad US market returns may serve as a clearly labeled benchmark
  fallback; they must not be called the S&P 500.
- Evidence may be unavailable. Unavailable is not benign.
- This remains a research prototype, not a trading or position-sizing system.

## 9. Deferred work

- new ML regime or crash classifiers;
- a single optimized crash probability;
- CRSP/Compustat-quality survivorship-free history;
- production factor-risk covariance models;
- large fundamental libraries;
- extensive alternative-data scraping;
- automated trade recommendations;
- agent orchestration frameworks.

## 10. Phase 0 interpretation

The confirmed request calls for a review after every phase. Accordingly, Phase
0 changes documentation only. Phase 1 begins only after review of:

- `docs/confirmed_design.md`;
- `docs/development_plan.md`;
- this feedback record.
