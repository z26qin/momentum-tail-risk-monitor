<p align="center">
  <a href="docs/methodology.md"><img src="https://img.shields.io/badge/Docs-methodology-FFD700?style=for-the-badge" alt="Documentation"></a>
  <a href="docs/demo_walkthrough.md"><img src="https://img.shields.io/badge/Demo-15--20%20min-0A7A3E?style=for-the-badge" alt="Demo walkthrough"></a>
  <a href="notebooks/final_mvp_demo.ipynb"><img src="https://img.shields.io/badge/Notebook-final__mvp__demo-1f6feb?style=for-the-badge" alt="Demo notebook"></a>
  <a href="#limitations-and-assumptions"><img src="https://img.shields.io/badge/Research-MVP-orange?style=for-the-badge" alt="Research MVP"></a>
</p>

# Momentum Crash Monitor

**An AI-assisted decision-support prototype for understanding when a momentum book may be vulnerable to a sharp reversal.**

The system does not try to predict the exact crash date. It helps a PM answer four practical questions:

1. **What kind of momentum stress is forming?**
2. **Where is the risk in the book: the long leg, the short leg, or a crowded cluster?**
3. **Does the current setup resemble a recovery-driven crash or a crowded unwind?**
4. **What evidence supports, contradicts, or is still missing from that interpretation?**

```text
PM book risk          Market regime          Crowding structure        Evidence
Where is the pain?  + Why now?             + Can it propagate?       + What confirms it?
```

This is a **research MVP**, not a trading system, crash probability, or portfolio optimizer.

---

## The momentum-crash logic in one minute

A momentum portfolio is typically long recent winners and short recent losers.

That trade can become vulnerable in two different ways.

### 1. Recovery-driven reversal

During a bear market, recent winners often behave more defensively and can have lower market beta, while recent losers may be distressed, cyclical, or high beta.

When the market suddenly rebounds:

```text
Bear market
    ↓
Winners become relatively defensive
Losers become distressed / high beta
    ↓
Sharp market recovery
    ↓
High-beta losers rebound faster than low-beta winners
    ↓
The short leg loses heavily
    ↓
Momentum portfolio can crash
```

This is the Daniel–Moskowitz mechanism. The important point is not simply that “the market is up.” The dangerous setup is:

> **A severe prior drawdown, followed by a fast recovery, with a strong loser-stock rebound and short-leg pain.**

The monitor therefore checks the market state, recovery speed, long-versus-short beta, short-leg losses, and portfolio drawdown together.

### 2. Crowded-position unwind

A momentum book can also be fragile when many investors own similar winners, short similar losers, or concentrate in the same themes.

When those positions are reduced at the same time:

```text
Similar portfolios
    ↓
Concentrated holdings / narrow breadth / shared themes
    ↓
One-sided selling or covering
    ↓
Weak liquidity absorption
    ↓
Correlated losses spread across books
```

This is the Khandani–Lo mechanism. A crowded selloff is not automatically forced deleveraging. The system only treats crowding as a **risk amplifier** unless positioning, liquidity, and propagation evidence become stronger.

---

## What the prototype monitors

| PM question | What the system looks at | Why it matters |
|---|---|---|
| Is the market in a dangerous recovery state? | Prior drawdown, volatility, recovery speed, UMD context | Recovery crashes are state-dependent |
| Is the short leg becoming dangerous? | Short-leg return, loser rebound, short-versus-long beta | Momentum crashes often come through the short book |
| Is the book concentrated? | Effective number of bets, HHI, theme clusters | Fewer independent bets make exits more correlated |
| Is momentum breadth narrowing? | Share of the universe supporting the signal | A narrow trade is easier to crowd and reverse |
| Is selling propagating? | Correlated selloff, turnover, absorption proxies | Distinguishes local weakness from a wider unwind |
| Does outside evidence agree? | Timestamped news, positioning notes, short-interest context | Helps challenge the quantitative reading |

The output remains a set of **separate, auditable signals**. They are not merged into one opaque crash score.

---

## Portfolio construction: why L10 / S10?

The default demo portfolio is an equal-weight S&P 500 **12-1 momentum long-10 / short-10** book.

This is deliberately a small, readable research portfolio—not a claim that institutional momentum funds trade only 20 names.

### What institutional implementations usually do

A production quant portfolio would more commonly:

- rank the full investable universe by momentum;
- select percentile or decile portfolios;
- hold many more names;
- neutralize market, industry, country, size, and other factor exposures;
- apply liquidity, borrow, turnover, and risk constraints;
- optimize weights rather than use simple equal weights.

### Why this MVP uses 10 long and 10 short names

The L10/S10 design was chosen because it makes the prototype easy to inspect:

- a PM can see every name and weight;
- long- and short-leg attribution is transparent;
- cluster and concentration diagnostics are intuitive;
- the demo runs quickly using public data;
- failures are easier to trace than in a 300-name optimized portfolio.

The core monitoring logic is **portfolio-agnostic**. The intended production path is:

```text
Demo:
S&P 500 → 12-1 rank → top 10 / bottom 10 → equal weight

Production:
PM universe → momentum signal → percentile selection
→ risk neutralization → liquidity / borrow constraints
→ optimized weights → same monitoring framework
```

So L10/S10 should be read as a **test harness for the monitoring system**, not the proposed final portfolio construction method.

---

## Beta: what is used and why?

Beta is not a fixed company characteristic. It changes with the estimation window, market regime, data frequency, outliers, and risk model.

Institutional risk systems may use:

- historical market beta;
- shrinkage or Bayesian beta;
- multi-factor exposures;
- robust regressions that reduce the effect of extreme observations;
- vendor risk models;
- portfolio optimization that targets near-zero aggregate factor exposure.

### MVP choice

This prototype uses a transparent historical realized beta estimate for each stock and then aggregates it using portfolio weights.

```text
stock beta ≈ covariance(stock return, market return)
             ---------------------------------------
                    variance(market return)

portfolio beta ≈ sum(weight × stock beta)
```

The purpose is not to replace a production risk model. It is to answer a narrower question:

> **Does the current short basket behave materially more like a high-beta recovery trade than the long basket?**

This matters because the recovery-crash mechanism becomes more plausible when the short leg has greater upside sensitivity during a rebound.

### Why this choice is acceptable for the MVP

- It is reproducible with public data.
- The PM can inspect the calculation.
- It directly maps to the economic mechanism being tested.
- It avoids pretending that a simple prototype has access to a full institutional risk model.

### Known limitations

Raw historical beta can be unstable. Extreme returns, changing business exposures, and short samples may distort the estimate.

A production version should therefore:

1. use a longer and explicitly chosen estimation window;
2. winsorize or robustly down-weight extreme observations;
3. shrink stock betas toward industry or market priors;
4. estimate multiple factor exposures, not only market beta;
5. calculate portfolio-level exposure from actual PM weights;
6. compare ex-ante risk-model beta with realized up-market and down-market beta.

In other words, the current beta is a **diagnostic lens**, not a portfolio-neutralization engine.

---

## How crowding is monitored

Crowding cannot be observed from one number. It is better treated as a chain:

```text
Position overlap
    + Concentration
    + Limited liquidity
    + One-sided flow
    + Weak market absorption
    = Higher unwind risk
```

The MVP separates what can be measured from public data from what would require institutional or vendor data.

### Available in the MVP

| Crowding dimension | MVP proxy | PM interpretation |
|---|---|---|
| Portfolio concentration | HHI and effective number of bets | Is risk dominated by a few names? |
| Momentum breadth | Share of names supporting the momentum signal | Is the trade broad or increasingly narrow? |
| Cluster exposure | Correlated names and shared themes | Could several positions move together? |
| Theme unwind | Pre-existing cluster followed by broad correlated selling | Is pressure spreading beyond one stock? |
| Liquidity absorption | Turnover and price-impact-style proxies | Is the market absorbing the selling cleanly? |
| Short interest | Public FINRA-based context where available | Is the loser leg visibly crowded on the short side? |
| Narrative attention | Timestamped public news context | Are investors discussing the same crowded trade? |

### Important data that is not directly available

A stronger production crowding monitor would add:

- institutional holdings and prime-broker crowding;
- ETF ownership and creation/redemption flows;
- retail flow;
- options positioning;
- dealer gamma exposure;
- borrow utilization and stock-loan cost;
- fund leverage and financing pressure;
- actual order-book liquidity and market impact;
- cross-manager position overlap.

These inputs answer different questions:

| Data | What it would tell the PM |
|---|---|
| Short interest / borrow cost | How crowded and expensive the short side is |
| Institutional holdings | Whether ownership is concentrated among similar investors |
| ETF flows | Whether passive or thematic vehicles may transmit selling |
| Retail flow | Whether speculative participation is amplifying the move |
| Options / dealer gamma | Whether hedging flows may accelerate or dampen price moves |
| Prime-broker data | Whether multiple funds hold the same trade |
| Liquidity and market impact | Whether the market can absorb an exit |
| Leverage / financing | Whether losses may force position reduction |

The current prototype therefore does **not** claim to observe true ownership or forced selling. It flags where crowding risk appears structurally plausible and where additional data should be requested.

---

## Extending the framework to industry-level momentum

The same monitoring logic can be applied above the stock level.

### Equity industry momentum

For industries within one country:

1. group stocks by a stable point-in-time industry classification;
2. construct industry returns using liquid, investable constituents;
3. rank industries using a 12-1 or alternative momentum signal;
4. go long stronger industries and short weaker industries;
5. neutralize market and country exposure;
6. monitor industry breadth, concentration, beta asymmetry, and cross-industry reversal.

The PM question becomes:

> Are strong industries becoming crowded and narrow, while weak high-beta industries are positioned for a sharp recovery?

A production implementation should avoid using today’s industry membership historically and should account for sector reclassifications.

### Country and index momentum

At the index level, implementation would more naturally use:

- country equity-index futures;
- liquid index ETFs;
- currency-hedged or explicitly unhedged returns;
- country and regional risk controls.

A simple structure would be:

```text
Country/index universe
→ rank by medium-term momentum
→ long stronger indices / short weaker indices
→ neutralize global equity beta, region, and currency risk
→ monitor recovery, crowding, liquidity, and cross-market reversal
```

Additional risks become important:

- different trading hours;
- holidays and stale prices;
- FX exposure;
- futures rolls and basis;
- country concentration;
- capital controls;
- geopolitical jumps;
- differences in index composition.

The architecture remains the same: **portfolio risk first, regime second, crowding third, evidence last.**

---

## Two objects, never blended

The system keeps the PM book and the academic benchmark separate.

| Object | Role |
|---|---|
| **PM momentum portfolio** | The primary object being monitored. In the demo, this is the S&P 500 L10/S10 portfolio. |
| **Ken French UMD / Daniel–Moskowitz context** | A published factor and market-state reference used to understand the broader momentum backdrop. |

UMD is not treated as the PM book, and its historical tail frequency is not presented as the PM portfolio’s crash probability.

---

## One PM decision workflow

```text
1. Locate the risk
   Long leg, short leg, concentration, or market regime?

2. Identify the mechanism
   Recovery-driven reversal, crowded unwind, or ordinary noise?

3. Challenge the interpretation
   What evidence supports it? What contradicts it? What is missing?

4. Decide the next check
   Maintain monitoring, inspect exposures, request better positioning data,
   or discuss whether risk reduction deserves review.
```

The prototype does not issue a trade ticket. It organizes the evidence needed for a PM discussion.

---

## Product demo: three cases

Open [`notebooks/final_mvp_demo.ipynb`](notebooks/final_mvp_demo.ipynb).

The recommended review order is:

1. **Current semiconductor case** — primary product example;
2. **March 2020** — historical recovery-crash validation;
3. **January 2024** — quiet control.

### Current semiconductor case: 2026-05-29

> The evidence supports localized crowding and structural pressure, but does not confirm a broad recovery-driven momentum crash or forced deleveraging.

| PM question | Read |
|---|---|
| Where is the risk? | Concentrated and correlated long-side semiconductor exposure |
| Recovery-crash mechanism? | Weak / incomplete |
| Crowded-unwind mechanism? | Partially supported |
| What is not confirmed? | Broad propagation, liquidity failure, forced deleveraging |
| What next? | Monitor breadth, selling propagation, absorption, and stronger positioning evidence |

Full case: [`outputs/current_semi_unwind/pm_case_read.md`](outputs/current_semi_unwind/pm_case_read.md)

### Historical validation: 2020-03-24

The system identifies a coherent recovery-crash footprint:

- severe prior market drawdown;
- panic-elevated state;
- rapid recovery;
- short-leg and beta-gap pressure;
- recovery-crash mechanism triggered.

This is an interpretability check, not a claim of predictive backtest performance.

Full case: [`outputs/march_2020_reference/pm_case_read.md`](outputs/march_2020_reference/pm_case_read.md)

### Quiet control: 2024-01-05

The same rules produce no escalation:

- soft bear / low-volatility backdrop;
- zero scorecard triggers;
- no confirmed crowded unwind;
- recovery mechanism incomplete.

This demonstrates that the framework does not label every weak momentum period as a crash setup.

Full case: [`outputs/quiet_control_2024/pm_case_read.md`](outputs/quiet_control_2024/pm_case_read.md)

---

## What a PM gets in one run

| Output | PM use |
|---|---|
| Market-state context | Understand whether the market is in panic, bear, recovery, or normal conditions |
| Long/short leg decomposition | See where P&L pressure is coming from |
| Beta comparison | Assess whether the short book is exposed to a rebound |
| Drawdown and short-loss checks | Identify whether bounded stress thresholds are breached |
| Concentration and breadth | See whether the trade is narrow or dominated by a cluster |
| Unwind mechanism read | Separate recovery risk from crowded-position risk |
| Evidence card | Review timestamp-valid supporting and contradicting evidence |
| Missing-data statement | Understand what cannot be concluded from public data |

---

## System design

```text
                         ┌──────────── MVPConfig ────────────┐
                         │ as_of · compare_to · horizon · LLM │
                         └────────────────┬──────────────────┘
                                          │
                                          ▼
                                   run_mvp()  ◄── single entry
                                          │
            ┌─────────────────────────────┼─────────────────────────────┐
            │                             │                             │
            ▼                             ▼                             ▼
   ┌────────────────┐          ┌──────────────────┐          ┌───────────────────┐
   │ UMD / DM       │          │ PM momentum book │          │ Unwind +          │
   │ comparison     │          │ (S&P 10/10 demo) │          │ mechanism monitor │
   │────────────────│          │──────────────────│          │───────────────────│
   │ market state   │          │ leg attribution  │          │ recovery reversal │
   │ panic / bear   │          │ beta comparison  │          │ crowding / breadth│
   │ UMD context    │          │ bounded triggers │          │ propagation       │
   └───────┬────────┘          └────────┬─────────┘          └─────────┬─────────┘
           │                            │                              │
           └────────────────────────────┴──────────────────────────────┘
                                          │
                                          ▼
                              Deterministic risk read
                                          │
                           ┌──────────────┴──────────────┐
                           ▼                             ▼
                 exact-date evidence            optional constrained
                 replay and retrieval           LLM interpretation
                           └──────────────┬──────────────┘
                                          ▼
                               PM-facing evidence card
                                          │
                                          ▼
                               charts · JSON · Markdown
```

### Design principles

1. **The PM book is the main object.** UMD is market context only.
2. **Mechanisms remain separate.** Recovery risk and crowded unwind are not collapsed into one score.
3. **AI cannot change the numbers.** It only organizes evidence and explains the read.
4. **Missing data stays missing.** The system does not infer ownership, leverage, or forced selling without evidence.
5. **Every output is point-in-time.** Features and evidence must have been available by the selected date.

### Evidence privilege model

```text
Deterministic metrics and thresholds
                ↓
Mechanism interpretation
                ↓
Timestamp-valid evidence retrieval
                ↓
Optional LLM summary

LLM output cannot rewrite:
metric | threshold | trigger | portfolio state
```

---

## Quick start

Requirements: Python **3.11–3.14** and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync --locked --all-groups
uv run python -m src.mvp.demo_smoke_test
uv run python -m pytest -q
```

Open the demo notebook:

```bash
uv run --with jupyterlab jupyter lab notebooks/final_mvp_demo.ipynb
```

Run the pipeline directly:

```python
from src.mvp.config import MVPConfig
from src.mvp.pipeline import run_mvp

config = MVPConfig(
    as_of_date="2024-01-05",
    compare_to_date="2023-12-01",
    threshold_profile="default",
    horizon_days=20,
    use_llm=False,
)

result = run_mvp(config)
```

---

## Repository map

```text
momentum_crash/
├── README.md
├── Future_To_DO.md
├── docs/
│   ├── methodology.md
│   ├── limitations.md
│   ├── demo_walkthrough.md
│   └── architecture_to_value.md
├── notebooks/
│   └── final_mvp_demo.ipynb
├── src/
│   ├── mvp/                     # configuration, pipeline, PM presentation
│   ├── monitoring/              # scorecard and unwind logic
│   ├── portfolio/               # portfolio construction
│   ├── regime/                  # market-state classification
│   ├── risk/                    # beta and leg decomposition
│   ├── evidence/                # timestamped evidence and optional LLM layer
│   ├── features/
│   ├── data/
│   └── utils/
├── tests/
├── data/processed/
└── outputs/
    ├── current_semi_unwind/
    ├── march_2020_reference/
    ├── quiet_control_2024/
    ├── cross_case_comparison.md
    └── research_validation/
```

---

## Limitations and assumptions

- The L10/S10 portfolio is a transparent demo portfolio, not an institutional construction recommendation.
- Historical S&P membership is not fully point-in-time in the current prototype.
- Beta is a public-data realized estimate, not a vendor or production multi-factor risk model.
- The system does not currently optimize the portfolio to zero factor exposure.
- Crowding metrics are proxies and do not observe true manager overlap, leverage, financing, or forced selling.
- Public short-interest and news data are incomplete and may arrive with delays.
- Historical cases test whether the mechanism read is economically coherent; they do not establish predictive performance.
- The LLM layer organizes and challenges evidence but cannot change deterministic risk outputs.
- UMD context is not the PM book’s loss probability.
- No output should be interpreted as investment advice.

See [`docs/limitations.md`](docs/limitations.md) for the full list.

---

## Production roadmap

The highest-value extensions are:

1. plug in actual PM holdings, weights, and constraints;
2. replace L10/S10 with percentile-based, risk-neutralized portfolio construction;
3. use point-in-time universe and industry membership;
4. add robust multi-factor beta and risk-model exposures;
5. add institutional holdings, ETF flows, borrow, options, dealer gamma, and liquidity data;
6. persist daily mechanism states for out-of-sample outcome analysis;
7. extend the same framework to industry, country, and index-futures momentum;
8. upgrade evidence retrieval while preserving the rule that AI cannot alter the risk state.

See [`Future_To_DO.md`](Future_To_DO.md) for the broader roadmap.

---

## References

1. **Daniel, K., & Moskowitz, T. J. (2016).** Momentum Crashes.  
   *Journal of Financial Economics*, 122(2), 221–247.  
   Recovery-driven momentum-crash mechanism.

2. **Khandani, A. E., & Lo, A. W. (2007; 2011).** What Happened to the Quants in August 2007?  
   Crowded-position and quant-unwind mechanism.

3. **Ken French Data Library.**  
   UMD and market-factor data used as published comparison context.
