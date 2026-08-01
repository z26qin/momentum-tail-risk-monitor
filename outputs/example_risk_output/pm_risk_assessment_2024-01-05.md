# Momentum Tail-Risk Assessment (Example Output)

**Assessment date:** 2024-01-05
**Comparison date:** 2023-12-01
**Risk horizon:** 20 trading days

## Overall context

- **UMD comparison benchmark (deterministic):** bear_low_volatility
- **PM portfolio scorecard triggers:** 0
- **Active mechanism scenarios:** none
- **Evidence quality:** available

## UMD comparison: tail-loss context (illustrative)

- **Conditional tail-loss frequency:** 8.2%
- *Label: state-conditioned UMD comparison frequency — not the PM book, not a trading forecast.*

## Long / short risk attribution (deterministic)

- **short_minus_long_beta_gap:** -0.5179249937441994 (threshold 0.711609768322202, status not_triggered)
- **portfolio_drawdown:** -0.0902711157867091 (threshold -0.2, status not_triggered)
- **short_loss_in_recovery:** 0.2038585894990823 (threshold 0.29052131059638037, status not_triggered)

## Dominant monitoring channels

- **Unwind completeness:** moderate
- **Legacy scenario label:** normal_drawdown

## Text evidence (timestamped replay)

- [supporting] Employment Situation, December 2023 (US Bureau of Labor Statistics, 2024-01-05T08:30:00-05:00)
- [supporting] Personal Income and Outlays, November 2023 (US Bureau of Economic Analysis, 2023-12-22T08:30:00-05:00)
- [supporting] Gross Domestic Product, Third Estimate, Third Quarter 2023 (US Bureau of Economic Analysis, 2023-12-21T08:30:00-05:00)
- [contradicting] Wall Street set for weak open after stronger jobs data (Reuters via MarketScreener, 2024-01-05T09:08:00-05:00)
- [contextual] Factors Affecting Reserve Balances, January 4, 2024 (Federal Reserve Board, 2024-01-04T16:30:00-05:00)
- [contextual] Job Openings and Labor Turnover, November 2023 (US Bureau of Labor Statistics, 2024-01-03T10:00:00-05:00)
- [contextual] FOMC statement, December 13, 2023 (Federal Reserve Board, 2023-12-13T14:00:00-05:00)

## PM interpretation (AI-assisted, evidence-constrained)

The supplied point-in-time evidence is mixed and should be treated as context rather than a causal conclusion.

## Suggested review actions

- Monitor: Do currently triggered conditions remain beyond their thresholds?
- Monitor: Do other monitored signals begin deteriorating together?
- Monitor: Does newly retrieved evidence support or contradict the monitored mechanism?

## Limitations

- Default PM book uses survivorship-biased current SPY membership; not full PIT universe.
- UMD is a comparison benchmark; the S&P 10/10 book is the customizable PM portfolio.
- Evidence is exact-date cached replay, not live retrieval.
- Mechanism scenarios are descriptive rules, not validated crash forecasts.

## Provenance

- Card run ID: `53c34aa57bb437fc`
- Full run fingerprint: `750f22225b7d9592`
- Data cutoff: 2024-01-05T16:00:00-05:00
- LLM requested/effective: False/False
