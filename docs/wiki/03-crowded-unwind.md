# 03 · Crowded unwind (Khandani–Lo)

What the PM sees on 29 May (memo §6 and PPT case slide):

| Card field | Reading |
|---|---|
| Structural unwind | `crowded_theme_unwind` **triggered**; **concentration triggered** |
| Correlated cluster | **CIEN–COHR–LITE · 30%** of the long book |
| Mechanical state | **FRAGILITY_BUILDING**; aligned turnover elevated |
| Liquidity / propagation | Absorption failure **false** — selling still absorbed |

PPT path: concentrated positions → correlated reduction → weak absorption → selling spreads. On 29 May the first two are on; absorption has not failed; selling has not gone factor-wide.

This is mechanism 2. It is not a recovery crash.

---

## 1. `portfolio_concentration`

Code: `src/risk/concentration.py`  
Value: effective bets \(1 / \sum w_i^2\) on gross-normalized weights. Equal-weight 20 names cap at 20; drift toward a few names pulls it down.

| | |
|---|---|
| Cutoff | Prior **20th percentile** (lower = more concentrated) |
| Direction | ≤ |

### Why we watch it

Khandani–Lo crowding: similar books stacked in similar names. Effective bets answers “is **this** book already too concentrated?” even before a theme cluster is named.

### Why this cutoff

Own-history 20th — more concentrated than this book usually is. A hard “effective bets < 8” would either never fire or stay on, because a 10/10 equal-weight book lives high on that scale.

### What a move means

Falling through the 20th: structural crowding elevated. Rising: rotation / rebalance. Does not by itself prove common ownership.

---

## 2. `crowded_theme_unwind` and the 30% cluster

Code: `src/risk/theme_concentration.py`  
Label: **`correlated_theme_proxy`**. Not a GICS theme, not observed crowded ownership.

Membership is frozen at **t−1** so we do not build the cluster out of today’s selloff. The 30% print on the card is `cluster_exposure_share` — cluster absolute weight / long-leg absolute weight. Three equal-weight names in a 10-long book **are** 30%.

| Gate | Cutoff | Role |
|---|---|---|
| Pre-event cluster | ≥ **3** names, pairwise residual corr ≥ max(**0.50**, 75th of this book’s pairs) | Who is in |
| Exposure | ≥ **30%** of the long leg | Large enough to matter |
| Event-window loss | Cluster 5d residual loss ≥ **its own** prior 80th | Being sold vs the market |
| Breadth | ≥ **70%** of cluster names down over 5d | Not one name |
| Confirm | Cluster ≥ **50%** of long-side losses **or** unusual-volume share ≥ **50%** | Pain / tape agrees |

No pre-event cluster → later legs are forced **false**. “They only started moving together today” is not a pre-existing theme.

### Why we watch it

This is the operable crowded-unwind channel. 29 May’s question is whether pressure is a **local long cluster**, not a market-wide loser squeeze. The memo’s mandate follows: maintain size; watch for cross-cluster contagion before de-risking.

### Why 30% (the number on the slides)

It is the equal-weight arithmetic of a three-name clique in a 10-name long book — the smallest cluster we will treat as “a piece of the book.” A pair is everyday correlation. A harder size rule would have missed CIEN–COHR–LITE.

The 0.50 correlation floor stops a weak 75th (longs barely co-moving) from being branded a theme. Residual vs the market, not raw return, so a bear tape does not make everything look like one theme.

### What a move means

30% and triggered, recovery crash dark: **localized crowding**, which is the 29 May read. Loss contribution rising (0.3 → 0.6): more of the book’s pain is this cluster. Cluster dissolving at t−1: a selloff today is ordinary long liquidation, not this mechanism.

Does **not** mean financing stress, forced selling, or an “optics / AI” economic label. Those are evidence-pack readings, not this metric.

---

## 3. Mechanical tape: fragility, turnover, absorption

Code: `src/monitoring/unwind_monitor.py`

Inspired by Khandani–Lo 2007. Infers **factor-aligned footprints**, not hedge-fund liquidations. Does not rewrite the four-row card. PM-facing copy for `FRAGILITY_BUILDING` is **potential momentum tail risk** (20-day horizon, elevated review — memo §6).

| Signal | Cutoff | 29 May |
|---|---|---|
| Aligned turnover | Extreme-leg volume / universe volume, prior **80th** | Elevated |
| Absorption failure | Next-day continuation of the lagged extreme basket, prior **80th** | **False** |
| `FRAGILITY_BUILDING` | ≥ **2** of 5 flags at the 80th (footprint R², \|momentum beta\|, turnover, book vol, \|beta gap\|) **and** not `ACTIVE_UNWIND` | On |
| `ACTIVE_UNWIND` | Losses **and** footprint **and** turnover **and** failed absorption | Off |

### Why we watch it

The six-row / cluster layer names *where*. This layer asks whether the **tape** looks like quant-crowding flow. PPT’s last two KL steps — weak absorption, selling spreading — live here.

### Why these cutoffs

- **80th** — same monitoring gate as the rest of the product, not a 99th-percentile crash line.
- **2 of 5 flags** — one high-vol day or one high-R² day is common. Two channels to leave `NORMAL`.
- **ACTIVE needs all four evidence types.** 29 May has turnover and a cluster, but absorption has not failed and losses have not gone factor-wide, so the state stays fragility, not active unwind.

### What a move means

| Move | Read |
|---|---|
| Fragility on, absorption false | Technical fragility, selling still absorbed — 29 May mandate: review, do not broad de-risk |
| Absorption flipping true | Liquidity providers not taking the flow; escalate toward propagation |
| Into `ACTIVE_UNWIND` | Losses and factor flow arriving together. Still not proof of forced liquidation |
| Back to `NORMAL` | Footprint no longer unusual versus own history |

---

## Reading the three product dates

| Date | Crowding read |
|---|---|
| 2026-05-29 | Partially supported: cluster + concentration + fragility; absorption intact |
| 2020-03-24 | Not the story — recovery crash dominates |
| 2024-01-05 | Not present; normal footprint, no scorecard triggers |
