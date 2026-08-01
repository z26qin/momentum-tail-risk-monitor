# Future To-Do — PM imagination space

This file is intentionally forward-looking. It records what the research MVP
does **not** claim yet, and where a production path could go once a PM wants
their own book, true crowding, and operational workflow.

Nothing here changes current deterministic triggers, thresholds, or Evidence
Card contracts.

---

## Already shipped (do not rebuild)

| Layer | What it is |
|---|---|
| **T0 Crowding panel** | Book-structure proxies: effective bets / sector HHI, momentum breadth, correlated-theme unwind — rendered as a separate Crowding monitor |
| **T1 Context side notes** | Optional FINRA loser-leg short-interest z + GDELT crowding attention z — presentation only, never enter mechanism rules |

These are **proxies**. They are not ownership, leverage, financing, or
forced-selling observation.

---

## Near-term product path

### T2 — Plug-in for a PM’s own holdings / weights

**Why it matters:** The default S&P 10/10 equal-weight book is a stand-in.
Crowding and unwind only become “my book” when names and target weights are
injectable.

**Sketch:**
- `HoldingsProvider` Protocol (CSV / parquet / OMS export)
- Validate `formation_date · symbol · leg · weight`
- Rebuild `returns → leg_risk → concentration / theme / unwind`
- Keep scorecard / Evidence Card shell unchanged

**Imagination:** A PM drops last night’s live book and sees the same Crowding
and mechanism panels without touching research code.

---

### T3 — Observed crowding / positioning

**Why it matters:** Return-correlation themes and HHI answer “is the book
structurally tight?” They do **not** answer “is the world crowded in the same
theme?”

**Candidates (any subset):**
- 13F / aggregated ownership overlap with the active long cluster
- Prime-broker / borrow utilisation and hard-to-borrow flags
- Short interest at the theme / sector level (not only loser-leg panel)
- ETF / factor crowdfunding and creation-redemption stress
- Options / dealer gamma as an amplifier, not a score

**Product rule to preserve:** overlays may **confirm or challenge** the reading;
they must not rewrite deterministic values or invent a blended crash
probability.

**Imagination:** Side-by-side — *book structure crowded?* vs *street
positioning crowded?* — two columns, never one opaque number.

---

### T4 — Leverage, financing, and flow (forced-selling surface)

**Why it matters:** Many real momentum air-pockets are financing events:
gross/net limits, margin calls, risk-parity de-grossing, CTA / vol-control
flow — invisible to prices alone.

**Candidates:**
- Fund-level gross / net / leverage time series (PM private data)
- Financing / haircut / locate stress flags
- Observed order-flow or execution toxicity around losers/winners
- Cross-asset de-risking coincidence (equity + credit + FX carry)

**Imagination:** A “fragility surface” that asks: *if the book is tight and
the street is crowded, is there also a financing reason someone must sell?*

---

## Broader production backlog

These remain valuable independent of the crowding stack:

1. **Point-in-time membership and industry history** — retire current-SPY
   survivorship bias; make sector HHI historically honest.
2. **Out-of-sample validation** of the three mechanism rules
   (`bear_market_recovery_crash`, `short_book_reversal_crash`,
   `crowded_theme_unwind`).
3. **Production-grade retrieval** beyond offline exact-date preview
   (institutional news / filings with hard cutoffs).
4. **Daily orchestration** — scheduled as-of runs, audit retention,
   alerting on mechanism transitions only (not on a composite score).
5. **Multi-book / multi-sleeve** — same monitor shell across several PM
   momentum variants with labeled separation from UMD comparison.
6. **Human challenge workflow** — annotate “disagree / stale / wrong cluster”
   without mutating quantitative state; feed review into next research cycle.

---

## What we deliberately will not do

- Collapse crowding into a single probability or traffic-light score.
- Let LLM / RAG / GDELT change a metric, threshold, or trigger.
- Pretend UMD / Daniel–Moskowitz state **is** the PM book.
- Claim causality from narrative attention to unwind events.

---

## Suggested sequencing for a later PM engagement

```text
T2  PM holdings plug-in          →  “monitor my book”
T3  Observed crowding overlays   →  “is the street with me?”
T4  Leverage / financing / flow  →  “who is forced to sell?”
+   PIT membership + OOS checks  →  research credibility
+   Ops / retrieval / multi-book →  production readiness
```

Use this file as a conversation starter with PMs — not as a commitment
calendar. Scope and data access decide which branch comes first.
