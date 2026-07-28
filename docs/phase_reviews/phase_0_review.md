# Phase 0 review: repository audit and re-scope

Date: 2026-07-27

Status: complete

## Objective

Audit the existing momentum tail-risk repository and define a realistic path
to a transparent, top-down risk-monitoring MVP without rewriting working
components.

## Files created

- `docs/confirmed_design.md`
- `docs/development_plan.md`
- `docs/meeting_feedback.md`
- this review and the phase-review index were added immediately after the
  Phase 1 review request so that subsequent phases have a permanent journal.

No feature code was implemented in Phase 0.

## Main repository findings

The repository already contained several strong components:

- a Daniel–Moskowitz-inspired point-in-time market state;
- matured forward labels with explicit availability dates;
- purged expanding validation;
- training-fold-only preprocessing for legacy models;
- FINRA short-interest joins based on publication date;
- SEC shares-outstanding joins based on filing date;
- prior-only normalization for narrative features;
- strict evidence publication cutoffs, retrieval hashes, and passage grounding;
- an active pipeline that prevents overlays and AI evidence from modifying the
  primary deterministic assessment.

The central problem was not lack of infrastructure. It was a mismatch between
the current product and the confirmed product direction:

- the active system centered on a DM conditional tail-loss frequency;
- the portfolio was a published aggregate Ken French factor, not a named
  S&P 500 portfolio;
- the separate security-level positioning proxy used a current top-200
  large-cap universe and only constructed a loser leg;
- there was no explicit long/short beta and contribution decomposition;
- there was no row-oriented deterministic scorecard;
- breadth, concentration, IC, and quality exposures were missing.

## Architecture decision

The new sequence is:

1. macro regime;
2. synthetic S&P 500 momentum portfolio;
3. long/short risk decomposition;
4. deterministic threshold scorecard;
5. breadth, concentration, quality, profitability, and distress;
6. bounded evidence retrieval and AI research assistance;
7. reproducible demo.

The deterministic layer remains the source of truth.

## Reuse decisions

Reuse:

- date, hashing, atomic I/O, and PIT rolling utilities;
- Ken French and VIX acquisition and processed histories;
- DM bear/variance mechanics;
- symbol, price, and trading-calendar utilities;
- FINRA publication-date and SEC filing-date controls;
- archived evidence cutoff, grounding, and hash-binding logic;
- future-data perturbation and fixed-date reproducibility test patterns.

Retain only as reference:

- B0 and B1 historical validation;
- the frozen B2 model as a shadow benchmark;
- B2c/B3 text ablations;
- the current top-200 loser leg as a survivorship-biased FINRA overlay.

Deferred:

- a new ML crash or regime classifier;
- ex-ante risk modeling;
- CRSP/Compustat-grade historical membership;
- a large fundamental factor library;
- fragile alternative-data scrapers;
- automated trading and multi-agent orchestration.

## Test result

At the Phase 0 review:

- 151 tests passed;
- 4 rebuild/integration tests were skipped because their raw payload
  prerequisites were absent;
- the worktree was clean before the three Phase 0 documents were added.

## Development lessons

### 1. Preserve controls, replace product shape

The repository's strongest work is in point-in-time discipline and evidence
isolation. Rewriting it would increase risk without solving the main product
gap. The efficient path is to add the missing top-down portfolio and scorecard
layers around those controls.

### 2. Aggregate factor legs and security portfolios are different products

Ken French winner/loser returns are useful literature and historical
benchmarks. They cannot answer which stocks are held, which leg contributes
risk, or whether a junk rally is concentrated in distressed names.

### 3. Universe labels must be literal

The current top-200 Nasdaq screen cannot be described as the S&P 500. If a
point-in-time S&P 500 history cannot be obtained within the budget, a frozen
current S&P 500 snapshot is acceptable only with an explicit survivorship-bias
flag.

### 4. Missing evidence must remain missing

The existing evidence layer correctly treats unavailable or unclassified
information as unavailable, not benign. The same rule should govern
fundamentals, liquidity, sectors, and scorecard metrics.

## Limitations

- The Phase 0 plan estimates implementation time; actual data acquisition may
  move the Phase 2 budget.
- Point-in-time S&P 500 membership and public filing-aligned fundamentals were
  not yet proven feasible.
- Existing committed outputs include historical research artifacts that should
  not be confused with the new active design.

## Consequence for Phase 1

Phase 1 should reuse the DM and broad-market history, add explicit drawdown and
recovery states, avoid a new classifier, and preserve the existing active
pipeline until final integration.
