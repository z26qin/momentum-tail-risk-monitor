# PM-book forward outcomes — skipped

This deliverable is intentionally **not** implemented as a full
descriptive outcome table.

## What already exists

- Daily synthetic PM-book returns:
  `data/processed/momentum_portfolio_returns.parquet`
  (`portfolio_return`, long/short contributions).
- Trailing risk history:
  `data/processed/leg_risk_history.parquet`.

## What is missing

- No precomputed historical **scorecard state** series.
- No precomputed historical **mechanism status** series
  (`triggered` / `watch` / `not_confirmed`).
- `unwind_structure_history.parquet` stores fingerprint inputs,
  not mechanism outcomes.

## Why the stop-rule applies

Generating mechanism states across history requires repeated
`build_unwind_assessment` (prices, holdings, theme path).
That is new infrastructure, not a thin extract from existing
artifacts. A partial but trustworthy MVP prefers documenting
the gap over inventing a backtest engine.

## Next step (out of scope here)

1. Persist point-in-time mechanism/scorecard history once.
2. Join matured forward PM-book returns at 5d / 20d.
3. Publish a descriptive frequency table with overlapping-window
   dependence clearly stated — no regression, no threshold tuning.
