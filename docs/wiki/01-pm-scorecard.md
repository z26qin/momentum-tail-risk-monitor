# 01 · PM four-row scorecard

Code: `src/monitoring/scorecard.py`  
What the PM sees: memo §6 **“Quant scorecard — 0 of 4 triggered”**; PPT **“No triggers / recovery crash.”**

Four independent decisions on **this book**, not UMD. They are not blended into a probability.

---

## 1. `high_volatility_recovery`

Is the market in the window the PPT labels **prior stress + fast recovery + elevated vol**?

| | |
|---|---|
| Value | 0/1 composite |
| Cutoff | **1** = `early_recovery_state` **and** `high_volatility` |
| Provenance | Composite demo rule; legs defined in [02](02-recovery-crash.md) |

### Why we watch it

A Daniel–Moskowitz crash is not “the market is up.” It is a deep hole, a young bounce, and still-high vol — the on-ramp to a loser rally that hurts the short leg. One composite row so the desk does not escalate on vol alone or on a shallow bounce alone.

### Why this cutoff

No fitted cut. `1` only means both legs are true. The −20% / +5% / 63-day / vol-80th numbers live in the macro layer so this row cannot disagree with the recovery-crash mechanism.

### What a move means

0 → 1: macro gate opens. Stays 1: keep reading beta gap and short-leg loss. 1 → 0: bounce aged out, vol cooled, or the deep-drawdown memory lapsed. `unavailable` is not “gate closed.”

Does **not** mean the book is already losing money.

---

## 2. `short_minus_long_beta_gap`

PPT: **“Monitor macro state and beta gap.”** Memo: **“rising short-side beta.”**

| | |
|---|---|
| Value | 126d beta of short underlyings − 126d beta of longs |
| Cutoff | Prior **80th**; **0.25** if <252 days; floor **0** |
| Direction | ≥ |

### Why we watch it

In a recovery crash, losers go high-beta and winners go defensive. A large positive gap means the same market bounce lifts the shorts more than the longs. Book beta can rise on both legs together and still be roughly net-neutral; the **gap** is the squeeze exposure.

### Why this cutoff

- **80th** — squeeze-like versus *this* book’s own history, not “largest gap on record.”
- **0.25 demo** — shorts about a quarter-beta hotter than longs. A 10% bounce costs ~2.5 points of relative contribution on gross 2. Round, discussable, labeled.
- **Floor 0** — a negative 80th would flag “shorts are more defensive” as a squeeze. That is economically backwards.

### What a move means

Gap up: bounce is more dangerous for the short leg. Through the line: structure looks like a squeeze setup; still want the macro gate and realized short losses. Gap < 0: **not** a DM squeeze structure. Beta is exposure, not realized P&L.

---

## 3. `portfolio_drawdown`

Memo: **“the book drawdown deepens”** as confirmation that a recovery reversal is escalating.

| | |
|---|---|
| Value | Wealth vs 63-day rolling peak |
| Cutoff | Prior **20th**; **−20%** if <252 days |
| Band | Live cutoff always in **[−20%, −5%]** |
| Direction | ≤ |

Inception-to-date drawdown is context only. It does not trigger.

### Why we watch it

First PM question: is the book hurting? A 63-day window catches *recent* pain. A book that cratered years ago and then went sideways should not sit on a red light forever. This row does not name the mechanism; it only escalates attention onto this book.

### Why this cutoff

- **20th** — deeper than this book’s usual drawdown.
- **−20% demo** — same severe-drawdown integer as the macro hole, so the demo speaks with one voice.
- **Floor −20%** — a historical 20th of −30% would make monitoring too late.
- **Ceiling −5%** — a historical 20th of −2% would fire on noise.

### What a move means

More negative: escalate. Through the line: recent left tail. Deep since-inception, shallow 63-day: old scar, quiet quarter — **this row stays dark**. Compared on portfolio wealth (gross 2), not a de-grossed equivalent.

---

## 4. `short_loss_in_recovery`

PPT: **“Short-leg loss confirmation.”** Memo: **“early losses in recent losers.”**

| | |
|---|---|
| Value | Sum of `max(−short_contribution, 0)` over 21 days |
| Cutoff | Prior **80th**; **0.10** if <252 days |
| Extra gate | Triggers only if early recovery is on |
| Direction | ≥ |

Winning short days count as 0. They do not net off.

### Why we watch it

The beta gap says a squeeze *could* happen. This row says the shorts are *already* hurting. Restricted to early recovery because short-leg losses in a grinding bear are normal momentum life, not a crash.

### Why this cutoff

- **80th** — unusual versus this book’s own 21-day short-loss history.
- **0.10 demo** — ten points of book contribution; material on equal-weight 10/10; labeled, not fitted.
- **Early-recovery AND** — without the macro gate this row stays untriggered even if the loss number is large. You still see the number; we will not brand it a recovery crash.

### What a move means

Through the line **and** early recovery: realized side supports DM. Through the line **outside** recovery: does **not** trigger (trend running the shorts, or a different mechanism). Does not mean the longs are liquidating — that is the crowding notes.
