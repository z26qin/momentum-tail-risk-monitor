# PM case read — 2026-05-29 (deterministic + DeepSeek interpretation)

**Assessment date:** 2026-05-29
**Evidence cutoff:** 2026-05-29 16:00 America/New_York
**Risk horizon:** 20 trading days
**Deterministic state:** normal
**Run id:** `a50849f357c07e76` · **Fingerprint:** `a3fed64fc1d0d687`

**Staleness warning:** Historical as-of 2026-05-29 snapshot; not a current 2026-08-12 assessment.

**Interpretation:** DeepSeek-assisted (`evidence-interpretation-prompt-v8` · `pm-response-prompt-v5`); pipeline evidence replay of the human-reviewed CSU pack (15 items).

## Current read

Crowded momentum unwind watch; no confirmed mechanical unwind; fundamental repricing possible.

Quantitative scorecard triggers are inactive, but `crowded_theme_unwind` is **triggered**: the CIEN/COHR/LITE cluster shows concentrated losses and elevated turnover. The short-book reversal crash is not confirmed, the fundamental anchor is unavailable, and liquidity-absorption failure is absent.

## LLM evidence interpretation

- **Narrative state:** Crowded momentum unwind watch; no confirmed mechanical unwind; fundamental repricing possible.
- **Changes:** - Short-side crowding is plausible in the loser basket, but active covering or forced deleveraging is not established.
- The structural scenario is classified as crowded momentum unwind, but the mechanical unwind is not confirmed.
- Fundamental earnings reports from key tech names are contradicting the unwind narrative, suggesting a possible fundamental repricing.
- **PM interpretation:** The structural scenario is crowded momentum unwind, with the crowded_theme_unwind triggered and bear_market_recovery_crash on watch. However, the mechanical unwind is not confirmed: factor footprint is not elevated, and liquidity absorption failure is false. Public short-interest proxies are elevated in the loser basket, suggesting short-side crowding is plausible, but this does not establish active covering or forced deleveraging. Contradicting evidence from major tech earnings suggests a fundamental repricing may be underway, potentially explaining the drawdown. The high-volatility recovery signal remains untriggered, so the recovery-crash scenario is not active. Overall, the situation warrants monitoring for a potential momentum tail risk, but no broad mechanical unwind is confirmed.
- **Supporting ids:** csu-2026-05-29-013
- **Contradicting ids:** csu-2026-05-29-001, csu-2026-05-29-006, csu-2026-05-29-007, csu-2026-05-29-008, csu-2026-05-29-009, csu-2026-05-29-010, csu-2026-05-29-011, csu-2026-05-29-012
- **Missing/uncertain:** - No direct evidence on leverage, margin, or financing stress; forced deleveraging remains unconfirmed.
- No observed book-level positioning data; public proxies do not identify investor identity or common ownership.
- No evidence on factor propagation beyond the tech sector; breadth of unwind across factors is unknown.
- **Monitoring questions:** - Is the elevated short-interest proxy in the loser basket accompanied by rising short-volume share, suggesting active short-side activity?
- Does the elevated aligned turnover persist alongside a rising factor footprint, indicating broader market participation?
- Are the fundamental earnings reports from major tech names being revised downward, which could shift the narrative from crowding to fundamentals?
- **Invalidation conditions:** - If the short-loss-in-recovery signal triggers while the high-volatility-recovery signal remains untriggered, the recovery-crash scenario becomes more plausible.
- If the factor-footprint status becomes elevated while aligned turnover remains elevated, a broad mechanical unwind would be confirmed.
- If the short-interest or utilisation proxies decline from elevated while the loser basket outperforms, active short covering would be suggested.

## PM response (LLM)

**Current state:** No deterministic escalation signals are active; maintain posture and monitor. The crowded theme unwind mechanism is triggered, but no broad momentum unwind is confirmed.

**Main vulnerability:** The primary vulnerability is rebound-sensitive, potentially crowded shorts in the momentum loser basket, supported by elevated short-interest proxies; this path is not active today but warrants close monitoring.

**Why not act yet:** No deterministic signals have triggered, and the short book reversal crash is not confirmed. The elevated short-interest proxy is contextual but not proof of covering or forced deleveraging. We maintain posture and monitor for confirmation before considering any de-risking.

**What would change:** - If the short book reversal crash mechanism moves from watch to triggered, or if short losses in a recovery trigger, the reading would shift to active short-side stress.
- If the short-minus-long beta gap widens into a triggered state, or portfolio drawdown breaches its threshold, we would escalate to PM review.
- If recovery signals strengthen, we would run a loser-rally stress scenario and review rebound-sensitive shorts.

**Conditional response:** - If a recovery move confirms, review rebound-sensitive shorts and run a loser-rally stress scenario.
- If short losses broaden across the basket, consider reducing short exposure subject to PM review.
- If the recovery signal confirms, consider a temporary beta hedge subject to PM review.

**Categories:** maintain_and_monitor, review_rebound_sensitive_shorts, run_loser_rally_stress

## Deterministic PM-book scorecard

| metric | current_value | threshold | triggered | status |
| --- | --- | --- | --- | --- |
| portfolio_concentration | 19.518834600609683 | 19.788818762157902 | True | available |
| momentum_breadth_deterioration | 0.658 | 0.5557851239669421 | False | available |
| synchronous_winner_liquidation | -0.005880475274267424 | 0.01921979353915349 | False | available |
| cross_sectional_reversal | -0.03471090006488575 | 0.03311335289481359 | False | available |
| liquidity_amplification_proxy | 0.3 | 0.5 | False | available |
| fundamental_anchor | None | coverage-gated sign-vote rule | None | unavailable |

## Unwind mechanism status

- bear_market_recovery_crash: **watch**
- short_book_reversal_crash: **not_confirmed**
- crowded_theme_unwind: **triggered**

Theme proxy: CIEN/COHR/LITE, exposure 0.30, trigger **True** (correlation 0.726, 5d loss 7.4%).

## Mechanical unwind

| field | value |
| --- | --- |
| unwind_state | FRAGILITY_BUILDING |
| factor_footprint_r2 | 0.12513372366209508 |
| factor_footprint_percentile | 0.7689243027888446 |
| extreme_turnover_ratio | 1.1125299392810475 |
| extreme_turnover_percentile | 0.8565737051792829 |
| liquidity_absorption_failure | False |
| absorption_percentile | 0.27091633466135456 |

## Retrieved evidence (pipeline replay, 15 items)

- **Tech stocks see largest hedge fund selloff in decade: Goldman Sachs** (Investing.com reporting Goldman Sachs Prime Book data, 2026-05-04T00:00:00-04:00) — stance: `supporting`
- **NVIDIA Announces Financial Results for First Quarter Fiscal 2027** (NVIDIA Investor Relations, 2026-05-20T00:00:00-04:00) — stance: `contradicting`
- **Cisco Reports Third Quarter Earnings** (Cisco Investor Relations, 2026-05-13T00:00:00-04:00) — stance: `contradicting`
- **Arista Networks Reports First Quarter 2026 Financial Results** (Arista Networks Investor Relations, 2026-05-05T00:00:00-04:00) — stance: `contradicting`
- **Coherent Reports Third Quarter Fiscal 2026 Results** (Coherent Investor Relations, 2026-05-06T00:00:00-04:00) — stance: `contradicting`
- **Lumentum Announces Third Quarter Fiscal 2026 Financial Results** (Lumentum Investor Relations, 2026-05-05T00:00:00-04:00) — stance: `contradicting`
- **Applied Materials Announces Second Quarter 2026 Results** (Applied Materials Investor Relations, 2026-05-14T00:00:00-04:00) — stance: `contradicting`
- **Lam Research Reports Financial Results for Quarter Ended March 29, 2026** (Lam Research Investor Relations, 2026-04-22T00:00:00-04:00) — stance: `contradicting`
- **TSMC April 2026 Revenue Report** (TSMC, 2026-05-08T00:00:00-04:00) — stance: `contradicting`
- **Microsoft Fiscal Year 2026 Third Quarter Earnings Conference Call** (Microsoft Investor Relations, 2026-04-29T00:00:00-04:00) — stance: `contextual`
- **Meta Reports First Quarter 2026 Results** (Meta Investor Relations, 2026-04-29T00:00:00-04:00) — stance: `contextual`
- **Amazon.com Announces First Quarter Results** (Amazon Investor Relations, 2026-04-29T00:00:00-04:00) — stance: `contextual`
- **Will Rising Capex Test Hyperscalers’ Credit Strength?** (S&P Global Ratings, 2026-05-14T13:02:00-04:00) — stance: `contextual`
- **Hedge Funds Pile Back Into AI and Tech Stocks** (HedgeCo Insights reporting Goldman Sachs Prime Brokerage data, 2026-05-26T00:00:00-04:00) — stance: `contextual`
- **MacroMemo — May 5–25, 2026** (RBC Global Asset Management, 2026-05-25T00:00:00-04:00) — stance: `contextual`

## Known gaps

- Fundamental anchor unavailable.
- Sector-adjusted residual return and industry classification unavailable.
- Correlated cluster is a statistical proxy, not observed ownership.
- Evidence passages are minimal close paraphrases.

---
*Deterministic fields from `run_mvp`; LLM narrative is an overlay and cannot change metrics. No risk score created.*
