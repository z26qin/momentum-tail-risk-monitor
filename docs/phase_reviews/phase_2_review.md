# Phase 2 review: S&P 500 proxy momentum portfolio

Date: 2026-07-27

Status: complete, awaiting phase review

## Objective

Build a transparent security-level S&P 500 momentum demonstration with:

- a dated and auditable universe;
- a 12-1 signal that skips the most recent month;
- monthly top-10 long and bottom-10 short holdings;
- equal `+1` and `-1` gross leg weights;
- correctly signed, post-formation daily returns;
- explicit survivorship and missing-data treatment.

## Files created or modified

Created:

- `src/data/sp500.py`
- `src/portfolio/__init__.py`
- `src/portfolio/momentum.py`
- `tests/test_momentum_portfolio.py`
- `docs/sp500_universe.md`
- `docs/phase_reviews/phase_2_review.md`
- `data/raw/sp500/holdings-daily-us-en-spy.xlsx`
- `data/raw/sp500/holdings-daily-us-en-spy.xlsx.metadata.json`
- `data/raw/sp500/universe_report.json`
- `data/raw/sp500/price_acquisition_report.json`
- `data/processed/sp500_universe.parquet`
- `data/processed/sp500_price_coverage.parquet`
- `data/processed/sp500_prices.parquet`
- `data/processed/momentum_portfolio_holdings.parquet`
- `data/processed/momentum_portfolio_returns.parquet`
- `outputs/portfolio/portfolio_audit.json`
- `outputs/portfolio/momentum_holdings_2023-12-29.csv`

Modified:

- `.gitignore`
- `docs/confirmed_design.md`
- `docs/development_plan.md`
- `docs/meeting_feedback.md`
- `docs/phase_reviews/README.md`

The existing top-200 positioning data, Phase 1 regime module, active pipeline,
DM engine, and evidence paths were not modified.

## Data acquisition and coverage

The universe is the State Street SPY daily holdings workbook:

- holdings as of 2026-07-24;
- 503 retained equity holdings;
- 99.924362% of source ETF weight retained;
- cash and the nonstandard `CONTRA` corporate-action row excluded;
- class tickers normalized to the project's price-vendor convention;
- current Nasdaq sector labels matched for 500 of 503 names.

The workbook is parsed with the Python standard library. No Excel dependency
was added.

Price acquisition reused 194 histories from the existing processed top-200
panel and downloaded 309 missing histories into a separate cache:

| Item | Result |
|---|---:|
| Requested symbols | 503 |
| Reused histories | 194 |
| Newly downloaded histories | 309 |
| Covered symbols | 503 |
| Coverage | 100% |
| Price rows | 1,293,310 |
| First date | 2016-01-04 |
| Latest acquired date | 2026-07-27 |

The adjusted close used by the signal and portfolio return includes splits and
dividends.

## Portfolio convention

For formation month `m`:

```text
signal(m) = adjusted_close(m-1) / adjusted_close(m-12) - 1
```

This is the project's explicit 12-1 convention:

- no price in month `m` enters the signal value;
- the ranking is finalized after the last trading close of month `m`;
- selected weights apply only in month `m+1`;
- an incomplete current month cannot become a formation month;
- signal endpoints are joined by calendar month rather than shifted by row, so
  a missing calendar month cannot silently shorten the lookback.

Ranking ties use ticker ascending as the deterministic secondary key.
Defaults are configurable `n_long=10` and `n_short=10`. Long weights are
`+0.1`; short weights are `-0.1`.

Each leg is reset to equal gross-one weights at the start of its holding
month. Constituent weights then drift with relative wealth until the next
monthly rebalance. They are not reset to equal weights every day.

Daily output distinguishes:

- `long_basket_return`;
- `short_basket_underlying_return`;
- `long_contribution`;
- `short_contribution`, with the opposite sign of the short underlying return;
- `portfolio_return = long_contribution + short_contribution`;
- cumulative return and drawdown.

If any selected constituent lacks a daily return, that leg and the portfolio
return are null from that date through month-end because later drifted weights
cannot be reconstructed without imputation. There is no zero fill or hidden
reweighting.

## Built output

| Item | Result |
|---|---:|
| First formation date | 2017-01-31 |
| Last completed formation date | 2026-06-30 |
| Monthly formations | 114 |
| Holdings rows | 2,280 |
| Daily portfolio-return rows | 2,365 |
| Complete daily-return rows | 2,365 |
| Maximum arithmetic reconciliation error | `2.78e-17` |

The frozen portfolio artifacts were regenerated twice and their SHA-256 hashes
were identical.

## Representative formation: 2023-12-29

These holdings apply during January 2024.

Long leg:

| Rank | Symbol | 12-1 signal |
|---:|---|---:|
| 1 | CVNA | 560.76% |
| 2 | APP | 255.94% |
| 3 | COIN | 252.42% |
| 4 | SMCI | 233.09% |
| 5 | NVDA | 220.15% |
| 6 | VRT | 219.62% |
| 7 | PLTR | 212.31% |
| 8 | META | 171.85% |
| 9 | UBER | 127.98% |
| 10 | CRWD | 125.08% |

Short leg:

| Rank | Symbol | 12-1 signal |
|---:|---|---:|
| 486 | INCY | -32.35% |
| 487 | PODD | -35.77% |
| 488 | RVTY | -36.45% |
| 489 | ECHO | -37.23% |
| 490 | PFE | -37.84% |
| 491 | AES | -38.20% |
| 492 | ALB | -43.75% |
| 493 | DG | -46.12% |
| 494 | EL | -47.73% |
| 495 | MRNA | -56.74% |

There were 495 rankable current constituents on this formation date. The
other eight did not yet have the required price endpoints.

The latest completed formation has also been frozen separately at
`outputs/portfolio/momentum_portfolio_2026-06-30.md`. It records the July 2026
long and short baskets, exact signal window, weights, current-snapshot status,
and the need to review extreme corporate-action-sensitive signals before
investment interpretation.

## Tests

Phase 2 targeted suite after the Phase 3 pre-audit correction:

- 8 passed.

Full repository suite at the original Phase 2 gate:

- 164 passed;
- 4 skipped for the existing raw-payload prerequisites.

After the monthly-drift correction and Phase 3 additions, the full suite is
172 passed and the same 4 existing skips.

Tests cover:

- parsing the official workbook while excluding cash and corporate actions;
- the exact `P[m-1] / P[m-12] - 1` signal;
- invariance of an earlier formation to future price changes;
- deterministic ticker tie-breaking;
- next-month weight application and signed long/short weights;
- month-start equal weights and intra-month weight drift;
- exclusion of an incomplete latest month from portfolio formation;
- exact long/short contribution reconciliation;
- explicit null output when a constituent return is missing.

## Main findings and lessons

### 1. A full named portfolio was feasible without a new paid source

The official SPY workbook supplied a clean dated current snapshot, and all 503
names obtained usable price histories. Phase 3 can therefore operate on actual
named long and short baskets rather than aggregate French factor legs.

### 2. The membership limitation is material

The 2026 membership snapshot is applied throughout the 2017–2026
demonstration. It includes later entrants before they joined the index and
excludes companies that left the index. The strong historical cumulative
portfolio result is therefore not a valid strategy-performance claim.

### 3. Calendar joins are safer than row shifts

Using row offsets for monthly prices can silently turn a missing month into a
shorter lookback. Joining explicitly to `m-12` and `m-1` preserves the stated
signal contract.

### 4. Formation and signal endpoint are different concepts

The signal endpoint is month `m-1`, but the portfolio is not formed until the
close of month `m` and is not active until month `m+1`. Carrying all three
dates prevents an apparently harmless one-month alignment error.

### 5. Short-basket return and short contribution need separate labels

When the underlying short basket loses 2%, the short portfolio contribution is
+2%. Storing both values prevents sign confusion in the coming beta and
recovery-window attribution phase.

### 6. Missing returns must be visible

Equal-weighting only the names that happen to report a return would change the
portfolio without a rebalance decision. The strict completeness rule is more
auditable and did not cost any rows in the built sample.

### 7. Phase 3 pre-audit corrected an implicit daily-rebalance assumption

The first Phase 2 implementation reapplied the equal target weights on every
daily return. That is daily rebalancing, despite the intended monthly
rebalance contract. The Phase 3 pre-audit detected and corrected it before any
beta or recovery attribution was built.

The difference was material: 2,252 of 2,365 daily returns changed, average
absolute daily difference was 11.3 basis points, maximum daily difference was
5.20%, and annualized tracking error between the two conventions was 3.82%.
The corrected portfolio sets equal weights once at month start and lets them
drift. This finding is why each later phase must audit economic conventions,
not only date alignment and arithmetic identities.

## Limitations

- Membership is a frozen 2026-07-24 snapshot, not PIT constituent history.
- Current Nasdaq sector labels are applied historically and are not PIT.
- Yahoo adjusted prices are a public-vendor research input, not a licensed
  institutional total-return database.
- Delisted former constituents are absent by construction.
- The portfolio ignores transaction costs, turnover, borrow availability,
  short fees, taxes, execution delay, and capacity.
- Gross exposure is 2.0 and net exposure is zero; cumulative returns should
  not be compared with a long-only index without adjusting for this.
- No beta, conditional beta, volatility attribution, breadth, fundamental
  alignment, or scorecard rule is added in Phase 2.
- The new portfolio remains separate from the active legacy pipeline until
  final integration.

## Consequence for Phase 3

Phase 3 can use:

- fixed dated holdings;
- separate long and short underlying returns;
- signed long and short contribution;
- a complete 2017-02 through 2026-06 daily portfolio history.

It should add rolling and conditional beta, volatility, beta gap, leg
contribution, portfolio drawdown, and short-leg loss contribution during the
Phase 1 recovery states. The current-constituent bias must remain attached to
every derived historical interpretation.
