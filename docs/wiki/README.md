# Risk metric threshold wiki

These notes cover **only** the risk metrics that appear on the live repo path **and** on the research memo / distribution PPT — the objects a PM actually reads on the card.

Each note answers three questions:

1. **Why we watch it**
2. **Why this cutoff**
3. **What a move means** (and what it does not mean)

Deterministic metrics are the source of truth. Evidence and the LLM cannot change a value, threshold, trigger, or risk state.

## Product metrics

| What the PM sees | Repo object | Cutoff in the code | What does it indicate |
|---|---|---|---|
| Quant scorecard, 0 of 4 | Four-row PM card | Any of the four rows below on — see [01](01-pm-scorecard.md) | Whether **this book** looks like a recovery-crash setup. **0 of 4** means none of the four lights is on. |
| High-vol recovery gate | `high_volatility_recovery` | Early recovery **and** high vol both true | The market just climbed out of a deep hole and is still jumpy — the usual backdrop for a loser rally. On only when **both** are true; vol alone or a bounce alone does not fire it. |
| Short-side beta | `short_minus_long_beta_gap` | Gap ≥ this book’s prior **80th** (or **0.25** if <252 days); never below **0** | Recent losers (the shorts) are more sensitive to the market than the longs, so a bounce hurts the short leg more. Fires in the top fifth of this book’s own history. A negative gap does **not** fire — that is not a squeeze. |
| Book drawdown | `portfolio_drawdown` | 63-day drawdown ≤ this book’s prior **20th**; live line always between **−20%** and **−5%** | How far the book is below its recent peak — is the pain large enough to escalate? Fires in the worst fifth of this book’s usual drawdowns. A 3% dip will not fire; a hole deeper than 20% always can. |
| Short-leg loss | `short_loss_in_recovery` | 21-day short losses ≥ prior **80th** (or **10%** of the book if <252 days) **and** early recovery on | The shorts are already losing money **during a rebound**, not in a grinding bear. Both must be true: unusual short-leg losses **and** the recovery gate above. |
| Recovery-crash mechanism | `bear_market_recovery_crash` | All three: market ≥**20%** off the peak recently, bounced ≥**5%** off the low within **63** days, vol at its prior **80th** | The full Daniel–Moskowitz tape. Fires only when the hole, the young bounce, and high vol are **all** present. One or two legs is a watch, not a trigger. |
| DM / UMD backdrop | `dm_bear_state` / `panic_elevated` | Bear: 2-year market return **< 0**. Panic: bear **and** 126-day variance ≥ the average of past bear periods | How fragile the **published momentum factor** tape is — not a score for this book. Bear = market has lost money over ~two years. Panic = that, plus volatility already at typical bear-market levels. |
| Concentration | `portfolio_concentration` | Effective bets ≤ this book’s prior **20th** | Risk is piled into fewer names than usual. Fires when the book is in the most concentrated fifth of its own history. Lower effective bets = more concentrated. |
| Crowded-theme channel | `crowded_theme_unwind` | Pre-event cluster of ≥**3** names **and** ≥**30%** of the long book, then unusual cluster losses, ≥**70%** of names down, plus loss or volume confirm | A group of longs that were already moving together is now being sold. The **30%** print is “this cluster is a real piece of the book” (three equal-weight names in a 10-name long book). No pre-existing cluster → does not fire. |
| Mechanical state | `FRAGILITY_BUILDING` | ≥**2** of 5 flow/vol/beta flags at the prior **80th**, and not a full active unwind | The tape looks crowded — extra turnover, factor-like days, jumpy beta — but the book has **not** confirmed a full unwind. Potential tail risk; closer review, not automatic de-risking. |
| Aligned turnover | `extreme_turnover` elevated | Momentum-extreme volume / universe volume ≥ prior **80th** | The names at the momentum extremes are trading busier than the rest of the market — a crowding-flow footprint. Fires in the top fifth of that ratio’s history. |
| Liquidity / absorption | `liquidity_absorption_failure` | Next-day continuation of the extreme basket ≥ prior **80th** | After a shock, is the move still going instead of bouncing back? **True** = the bid is not absorbing the selling. **False** (29 May) = selling is still being absorbed; a broader forced unwind is not confirmed. |

Horizon on the card is **20 trading days** (memo). Thresholds are prior-only.

## Notes

| Note | Product question |
|---|---|
| [00 · Conventions](00-conventions.md) | How to read a cutoff |
| [01 · PM scorecard](01-pm-scorecard.md) | Is **this book** under stress? (the 0-of-4 card) |
| [02 · Recovery crash](02-recovery-crash.md) | Daniel–Moskowitz path: macro + short-leg |
| [03 · Crowded unwind](03-crowded-unwind.md) | Khandani–Lo path: cluster, concentration, mechanical tape |

## Left out on purpose

These exist in code but **do not** appear as PM metrics on the memo or PPT, so they are not documented here: rate-policy proxy, momentum-breadth row, fundamental-anchor row, UMD 5th-percentile label construction, and the legacy domain checklist.

## What we refuse to do

- Blend the two mechanisms into one score.
- Treat public turnover / correlation / FINRA proxies as ownership, leverage, or forced selling.
- Retune cutoffs after looking at the episode table.
