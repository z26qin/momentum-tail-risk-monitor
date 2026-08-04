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
- **Scenario classification:** normal_drawdown

## Crowding monitor (book-structure proxies)

- Channels: portfolio concentration, momentum breadth, correlated-theme unwind; optional FINRA / GDELT side notes.
- *Proxy only — not observed ownership, leverage, or flow. No aggregate crowding score.*

## Liquidity / Mechanical Unwind

- **State:** NORMAL
- **Factor footprint R²:** 0.011881610212604143
- **Momentum-aligned turnover ratio:** 0.987505226604063
- **Absorption failure:** False
- *Detects factor-aligned trading footprints, not actual hedge-fund liquidations.*

## Text evidence (timestamped replay)

- [supporting] Employment Situation, December 2023 (US Bureau of Labor Statistics, 2024-01-05T08:30:00-05:00)
- [supporting] Personal Income and Outlays, November 2023 (US Bureau of Economic Analysis, 2023-12-22T08:30:00-05:00)
- [supporting] Gross Domestic Product, Third Estimate, Third Quarter 2023 (US Bureau of Economic Analysis, 2023-12-21T08:30:00-05:00)
- [contradicting] Wall Street set for weak open after stronger jobs data (Reuters via MarketScreener, 2024-01-05T09:08:00-05:00)
- [contextual] Factors Affecting Reserve Balances, January 4, 2024 (Federal Reserve Board, 2024-01-04T16:30:00-05:00)
- [contextual] Job Openings and Labor Turnover, November 2023 (US Bureau of Labor Statistics, 2024-01-03T10:00:00-05:00)
- [contextual] FOMC statement, December 13, 2023 (Federal Reserve Board, 2023-12-13T14:00:00-05:00)

## PM interpretation (Evidence-assisted, deterministic fallback)

The supplied point-in-time evidence is mixed and should be treated as context rather than a causal conclusion. Lens read: DM recovery crash remains watch on structural channels and not confirmed for short-book reversal; Khandani-Lo crowded unwind is not confirmed; fundamental repricing stays unconfirmed without a structured fundamental anchor. Mechanical state is NORMAL, with liquidity absorption failure absent.

## PM response (decision support)

**Current posture:** Monitor more closely. Watch channels are active, but portfolio stress is not yet confirmed.

**Main vulnerability:** The clearest risk is broader strategy drawdown rather than a single isolated channel.

**What would change the reading:**

- The setup would become more fragile if a recovery regime is accompanied by rising short-leg losses, adverse beta movement, or broader portfolio drawdown.
- Watch for: short_book_reversal_crash moves from watch/not_confirmed to triggered.
- Watch for: short_loss_in_recovery triggers during a recovery regime.
- Watch for: short_minus_long_beta_gap widens into a triggered state.

**Conditional portfolio response:**

- Run a loser-rally stress scenario
- Consider a temporary beta hedge if the recovery signal confirms, subject to PM review
- Consider reducing short exposure if losses broaden across the basket, subject to PM review
- Consider reducing gross if stress moves from one leg to the overall strategy, subject to PM review
- Maintain the current posture and monitor the short basket
- Review rebound-sensitive shorts if a recovery move confirms
- Identify the largest short-side loss contributors
- Check whether short concentration is amplifying the move

**Why not act yet:** Broad de-risking would be premature because the relevant PM-book stress channels remain unconfirmed.

- Bounded categories: maintain_and_monitor, review_rebound_sensitive_shorts, run_loser_rally_stress, review_short_loss_contributors, review_short_concentration, review_unintended_beta, consider_temporary_beta_hedge, consider_reducing_short_exposure, consider_reducing_gross_subject_to_pm_review, pause_incremental_risk_subject_to_pm_review
- PM response LLM: False (deterministic-pm-response-v1)

## Suggested review actions

- Monitor: Does factor footprint or aligned turnover broaden beyond the active structural channel?
- Monitor: Does liquidity absorption fail while losses remain synchronized?
- Monitor: Do retrieved evidence stances shift from contextual or mixed toward clearer support or contradiction?

## Limitations

- Default PM book uses survivorship-biased current SPY membership; not full PIT universe.
- UMD is a comparison benchmark; the S&P 10/10 book is the customizable PM portfolio.
- Evidence is exact-date cached replay, not live retrieval.
- Mechanism scenarios are descriptive rules, not validated crash forecasts.
- PM response categories are bounded decision-support labels, not trade instructions.

## Provenance

- Card run ID: `53c34aa57bb437fc`
- Full run fingerprint: `240fa2bb30fabdf4`
- Data cutoff: 2024-01-05T16:00:00-05:00
- LLM requested/effective: False/False
