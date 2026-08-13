# 00 · Conventions

Short rules that apply to every product metric below.

## Three objects, never blended

The memo’s four lenses collapse to three on the card:

1. **The PM book** (default S&P 500 12-1 long-10 / short-10) — four-row scorecard, concentration, theme cluster.
2. **Daniel–Moskowitz / UMD backdrop** — is the *tape* a recovery-crash setup? Not a score for this book.
3. **Khandani–Lo mechanical tape** — factor-aligned turnover and absorption. Does not rewrite the four-row.

## Timing

Every daily number is a **post-close fact**. Earliest use is the next session. “Historical” means observations **strictly before** as-of.

## Where a cutoff comes from

| Label | Meaning |
|---|---|
| Historical quantile | This series’ own past, used only with enough prior days (usually **252**) |
| `demo_threshold` | Labeled stand-in, or a quantile that a floor/ceiling overrode |
| Literature structure | Matches Daniel–Moskowitz (24-month bear, 126-day variance). Not a trading threshold from the paper |

Missing stays `unavailable`. That is not “untriggered,” and it is not evidence that risk is low.

## Why 80 / 20, not 99 / 1

Product gates are **monitoring lines**, not crash definitions. About one historical day in five would clear an 80th/20th. That is why the 29 May card can show crowding without calling a crash, and why the 2024 quiet control can print zero scorecard triggers.

Right-tail pressure (beta gap, short loss, vol, turnover) uses the **80th**. Left-tail pressure (drawdown, effective bets) uses the **20th**.

## How to read a move

- **Through the line** — escalate attention. Not a trade instruction.
- **Close but inside** — “has not cleared the escalation line,” not “no risk.”
- **A rising percentile** — more extreme versus **this series’ own past**, not versus another book.
