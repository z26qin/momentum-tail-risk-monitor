# 02 · Recovery crash (Daniel–Moskowitz)

What the PM sees: memo **“Daniel–Moskowitz recovery crash — not confirmed”** on 29 May; PPT path **prior stress → fast recovery → elevated vol → loser rebound → short-leg loss**; 2020-03-24 as the known recovery episode (**panic + rapid rebound, severe short-leg pressure**).

This is **environment + confirmation** for mechanism 1. It is not a score for crowding.

Code: `src/regime/market_state.py`, `src/risk/dm_engine.py`, `bear_market_recovery_crash` in `src/monitoring/unwind_structure.py`.

```text
SEVERE_DRAWDOWN_THRESHOLD      = -0.20
RECOVERY_FROM_TROUGH_THRESHOLD =  0.05
EARLY_RECOVERY_MAX_AGE         = 63
HIGH_VOLATILITY_QUANTILE       =  0.80   # 21-day ann. vol, expanding prior, min 252d
DM_RETURN_WINDOW               = 504     # ~24 months
```

---

## Macro legs (PPT steps 1–3)

### `market_drawdown` ≤ **−20%**

Wealth vs all-time peak. −20% is the usual bear integer, labeled demo — not a fitted UMD optimum. −10% would count ordinary corrections as crash preconditions.

More negative = further from the peak. Repairing (less negative) is **not** early recovery until bounce size and trough age also clear.

### Recovery off the trough ≥ **+5%**, age **1–63** days

Bounce vs the lowest wealth in the last **126** days. Early recovery also requires that a ≤−20% drawdown occurred inside that window.

**+5%** is large enough to say we left the low, small enough to still call it early. A 10–20% repair is already mid-recovery; much of the squeeze has often already printed. **63-day** age drops “a bear two years ago, a slow bull now.” Age 1 drops “today *is* the trough.”

Age 60 → 64 turns early recovery **off** even if the bounce is still >5%.

### `realized_volatility` ≥ prior **80th**

21-day annualized vol versus an expanding, one-day-shifted 80th (min 252 days). High vol is the second DM pillar. We do not use a fixed VIX print: “high” is versus this market’s own history.

---

## Mechanism: `bear_market_recovery_crash`

Triggers only when **all three** macro legs are true. One leg is `watch`. That is why 29 May can show crowding without a recovery-crash flag: the hole / bounce / vol stack was not there.

Whether **this book** is realizing the squeeze is still the four-row beta gap and short-leg loss. Environment and realization stay separate so “the book hasn’t lost yet” is not read as “the mechanism isn’t there.”

---

## DM / UMD backdrop (not a book score)

| State | Rule | Memo validation |
|---|---|---|
| `normal` | 504d market return ≥ 0 | UMD tail-loss rate **3.4%** |
| `bear_low_volatility` | Bear, intensity < 1 | **8.2%** |
| `panic_elevated` | Bear, and 126d variance ≥ expanding **bear-state** mean | **23.9%** |

Daniel–Moskowitz define a **continuous** bear × variance variable. Intensity ≥ 1 (“at least average bear variance”) is this repo’s daily operationalization, not a cut from the paper.

These frequencies are **descriptive** matured-UMD rates in that state. They are not this book’s crash probability, and they are not a live trigger. PPT uses them as the 2020 contrast: panic + rebound, then escalate / hedge review.

---

## What a move means on 29 May vs 24 Mar

| Date | Recovery-crash read | Why |
|---|---|---|
| 2020-03-24 | Strongly present | Deep hole, young bounce, high vol, short-leg pressure in the book |
| 2026-05-29 | Not confirmed | Scorecard 0 of 4; crowding is a different mechanism |
| 2024-01-05 | Not present | Quiet control — same rules stay dark |

Does **not** mean UMD falls tomorrow. Does **not** mean a crowded long cluster is being sold.
