<p align="center">
  <a href="docs/methodology.md"><img src="https://img.shields.io/badge/Docs-methodology-FFD700?style=for-the-badge" alt="Documentation"></a>
  <a href="docs/demo_walkthrough.md"><img src="https://img.shields.io/badge/Demo-15--20%20min-0A7A3E?style=for-the-badge" alt="Demo walkthrough"></a>
  <a href="notebooks/final_mvp_demo.ipynb"><img src="https://img.shields.io/badge/Notebook-final__mvp__demo-1f6feb?style=for-the-badge" alt="Demo notebook"></a>
  <a href="#what-we-refuse-to-claim"><img src="https://img.shields.io/badge/Status-Research%20MVP-orange?style=for-the-badge" alt="Research MVP"></a>
</p>

# Momentum Tail-Risk Monitor

**An AI-assisted monitor that helps a PM recognize fragile momentum setups, locate risk in the book, and challenge the read with timestamp-valid evidence — before acting.**

This is an approximately **20-hour research MVP**. It does **not** predict crash timing, publish a calibrated crash probability, optimize a portfolio, or issue a trade instruction.

### Start here

1. [`notebooks/final_mvp_demo.ipynb`](notebooks/final_mvp_demo.ipynb) — step-by-step runbook for the PPT demo  
2. [`outputs/current_semi_unwind/pm_case_read.md`](outputs/current_semi_unwind/pm_case_read.md) — primary example (2026-05-29)  
3. [`docs/demo_walkthrough.md`](docs/demo_walkthrough.md) — 15–20 min review path  
4. [`docs/methodology.md`](docs/methodology.md) · [`docs/limitations.md`](docs/limitations.md) · [`docs/production_path.md`](docs/production_path.md)

---

## The problem

Momentum reversal risk is ambiguous. The same drawdown can be:

- ordinary noise(volatility mean reversion);
- a **recovery-driven reversal** (losers rebound harder than winners after a deep selloff);
- a **crowded-position unwind** (similar books exit the same names for liquidity).

The PM question is not “will momentum crash tomorrow?” It is:

> Where is the pressure, which mechanism is supported, what evidence challenges that read, and what should we check next?

Default monitored book: equal-weight S&P 500 **12-1 long-10 / short-10** (inspectable demo proxy, not a production portfolio). Ken French UMD / Daniel–Moskowitz market state is **comparison context only**. Construction, beta, and crowding proxy detail: [`docs/methodology.md`](docs/methodology.md).

---

## Two mechanisms

### 1. Recovery-driven momentum crash (Daniel–Moskowitz)

```text
Severe market drawdown
        ↓
Winners become relatively defensive
Losers become distressed / high beta
        ↓
Fast market recovery
        ↓
Losers rebound faster than winners
        ↓
The short leg loses heavily
        ↓
Momentum reverses sharply
```

Dangerous condition is not “the market is rising.” It is **deep prior drawdown → rapid recovery → loser rebound → short-leg pain**.

### 2. Crowded-position unwind (Khandani–Lo)

```text
Concentrated positions / narrow breadth / shared themes
        ↓
Similar investors reduce exposure
        ↓
One-sided selling or short covering
        ↓
Weak liquidity absorption
        ↓
Correlated losses propagate across books
```

Crowding is a **risk amplifier**, not proof of forced deleveraging. Escalate only when concentration, correlated selling, weak absorption, and positioning evidence begin to line up.

---

## Decision workflow

```text
1. Locate the pressure
   Long leg, short leg, market regime, or concentrated theme?

2. Identify the mechanism
   Recovery reversal, crowded unwind, or ordinary noise?

3. Challenge the read
   What supports it? What contradicts it? What is still missing?

4. Choose the next check
   Maintain monitoring, inspect exposures, request better positioning data,
   or discuss whether risk escalation deserves review.
```

Outputs stay separate and auditable. They are **not merged into one opaque risk score**. Deterministic metrics are the source of truth; AI organizes evidence only.

---

## Example reads

Interactive prototype of frozen research outputs in a PM workflow (Semi-unwind case as of 2026-05-29 — not a live market call):

<p align="center">
  <img src="docs/figures/dashboard_mockup_preview.png" alt="Momentum tail-risk monitor — PM workflow prototype" width="920">
</p>

Open [`docs/figures/dashboard_mockup.html`](docs/figures/dashboard_mockup.html) offline. Prototype only — not production investment advice.

Recommended order: **2026-05-29 primary → 2020 validation → 2024 quiet control**.

Frozen packs do not change with the notebook `CONFIG`. The live `run_mvp` cell recomputes a dated assessment when you change date / horizon / LLM flag.

### Primary Example — 2026-05-29 correlated cluster

> Localized crowding and structural pressure are supported; a broad recovery-driven crash or forced deleveraging is **not** confirmed.

| PM question | Current read |
|---|---|
| Where is the risk? | Concentrated long-side cluster (`CIEN`–`COHR`–`LITE`); economic theme attribution unavailable |
| Risk horizon | 20 trading days |
| Monitoring severity | Potential momentum tail risk; focused review, not a crash probability |
| Recovery-crash mechanism? | Weak / incomplete |
| Crowded-unwind mechanism? | Partially supported |
| What is not confirmed? | Broad propagation, liquidity failure, forced deleveraging |
| What next? | Monitor breadth, selling propagation, absorption, and stronger positioning evidence |

**Evidence note:** Quantitative fields come from the deterministic pipeline. `CSU-*` text is a separately curated, cutoff-valid pack. Exact-date classification-cache replay is unavailable for 2026-05-29 — curated text challenges the snapshot but does not alter triggers or risk state.

Full read: [`outputs/current_semi_unwind/pm_case_read.md`](outputs/current_semi_unwind/pm_case_read.md)

### 2020-03-24 — historical validation

- Panic-recovery footprint: severe prior drawdown, elevated volatility, rapid recovery.
- Short-leg and beta-gap pressure active in the PM book.
- Recovery-crash mechanism triggered — interpretability check, not a forecast claim.

[`outputs/march_2020_reference/pm_case_read.md`](outputs/march_2020_reference/pm_case_read.md)

### 2024-01-05 — quiet control

- Soft bear / low-vol context; zero PM scorecard triggers.
- No confirmed crowded unwind; recovery mechanism incomplete.
- Same rules stay selective — not every soft momentum period escalates.

[`outputs/quiet_control_2024/pm_case_read.md`](outputs/quiet_control_2024/pm_case_read.md) · secondary card: [`outputs/quiet_control_example_risk_output/`](outputs/quiet_control_example_risk_output/)

Cross-case table: [`outputs/cross_case_comparison.md`](outputs/cross_case_comparison.md)

---

## What we refuse to claim

- Exact crash timing or a calibrated crash probability  
- Trade instructions or automatic de-risking  
- Forced deleveraging without direct evidence  
- That public crowding / turnover / FINRA–GDELT proxies equal ownership, leverage, or financing stress  
- That the L10/S10 demo book is an institutional production portfolio  
- That historical case coherence equals out-of-sample predictive skill  

Full list: [`docs/limitations.md`](docs/limitations.md).

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
   │ comparison     │          │ (S&P 10/10 demo) │          │ crowding monitor  │
   │────────────────│          │──────────────────│          │───────────────────│
   │ market state   │          │ leg attribution  │          │ recovery reversal │
   │ panic / bear   │          │ beta comparison  │          │ concentration     │
   │ UMD context    │          │ bounded triggers │          │ breadth / spread  │
   └───────┬────────┘          └────────┬─────────┘          └─────────┬─────────┘
           │                            │                              │
           └────────────────────────────┴──────────────────────────────┘
                                          │
                                          ▼
                              Deterministic risk read
                                          │
                           ┌──────────────┴──────────────┐
                           ▼                             ▼
                 exact-date evidence            LLM interpretation
                 cache replay                 OpenAI/Deepseek/Claude
                           └──────────────┬──────────────┘
                                          ▼
                               PM-facing evidence card
                                          │
                                          ▼
                    notebook views · Markdown case packs · optional HTML/JSON
```

1. **Macro risk state and PM book first.**  
2. **Mechanisms stay separate.** Recovery risk and crowded unwind are not one score.  
3. **AI cannot change the numbers.** It organizes and challenges evidence only.  
4. **Missing evidence stays missing.** No hallucinated ownership, leverage, or forced selling.  
5. **Point-in-time discipline.** Features and evidence must have been available by the selected date (complete PIT membership remains a limitation).

---

## How to run

Requirements: Python **3.11–3.14** and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync --locked --all-groups
uv run python -m src.mvp.demo_smoke_test
uv run python -m pytest -q
uv run --with jupyterlab jupyter lab notebooks/final_mvp_demo.ipynb
```

```python
from src.mvp.config import MVPConfig
from src.mvp.pipeline import run_mvp

config = MVPConfig(
    as_of_date="2024-01-05",
    compare_to_date="2023-12-01",
    threshold_profile="default",
    horizon_days=20,
    use_llm=False,  # library default; notebook demo uses True (below)
)
result = run_mvp(config)
```

**Date note:** the primary frozen product pack is **2026-05-29**. `demo_smoke_test` / `default_demo_config()` currently use **2026-06-30** (bundled panel coverage).

---

## LLM interpretation (DeepSeek)

Deterministic metrics, thresholds, triggers, and risk state are always computed first. The LLM is an interpretation layer only.

| Mode | How to run | Behavior |
|---|---|---|
| **Offline deterministic** | `use_llm=False` (`MVPConfig` library default) | No API call. Evidence Card + PM narrative use calibrated deterministic text. |
| **Live DeepSeek-assisted** | Notebook `CONFIG.use_llm=True` + `DEEPSEEK_API_KEY` in `.env` | `final_mvp_demo.ipynb` injects `DeepSeekEvidenceInterpreter` and `DeepSeekPMResponseInterpreter` into `run_mvp`. Missing key, HTTP failure, or schema validation fails closed to deterministic text. |

The final demo notebook is configured for the live path (`use_llm=True`). Without a key it still runs via fail-closed deterministic fallback and never rewrites metrics.

The LLM cannot rewrite: metric · threshold · trigger · risk state.

To enable the live path, create `.env` in the repository root with:

    DEEPSEEK_API_KEY=sk-your-key
    ANTHROPIC_API_KEY=xxxx
---

## Repository map

```text
momentum-tail-risk-monitor/
├── README.md
├── docs/
│   ├── methodology.md           # technical methodology
│   ├── limitations.md
│   ├── demo_walkthrough.md
│   ├── production_path.md       # production path (not an internal todo list)
│   ├── architecture_to_value.md # component → PM question map
│   └── figures/                 # offline PM workflow prototype
├── notebooks/
│   └── final_mvp_demo.ipynb     # step-by-step runbook for the PPT demo
├── src/
│   ├── mvp/                     # config, run_mvp, evidence card, PM response
│   ├── monitoring/              # scorecard, unwind, crowding proxies
│   ├── portfolio/               # 12-1 L10/S10 construction
│   ├── regime/                  # market-state classification
│   ├── risk/                    # beta, legs, concentration
│   ├── evidence/                # timestamped evidence + optional LLM
│   ├── features/
│   ├── data/
│   └── utils/
├── tests/                       # regression guards for the MVP path
├── data/
│   ├── processed/               # bundled public processed panels
│   ├── corpus/                  # versioned evidence corpus
│   └── evaluation/              # frozen case evidence packs
└── outputs/
    ├── current_semi_unwind/                 # PRIMARY example PM output (2026-05-29)
    ├── march_2020_reference/                # historical validation
    ├── quiet_control_2024/                  # quiet control case pack
    ├── quiet_control_example_risk_output/   # generated quiet-control card (2024-01-05)
    ├── cross_case_comparison.md
    ├── evidence_cache/                      # exact-date validated classification caches
    └── research_validation/                 # episode fingerprints / AI-value summary
```

---

## Production extensions

If extending beyond the 20-hour research MVP:

1. Plug in actual PM holdings, weights, and constraints.  
2. Replace L10/S10 with percentile-based, risk-neutralized construction.  
3. Harden point-in-time universe / industry history and live data adapters.  
4. Add institutional holdings, borrow, ETF/options flow, and liquidity inputs — then reuse the same monitoring workflow (including industry / country / index-futures momentum).

Also retained for a fuller build-out: multi-factor risk exposures and a service layer to serve the PM front end (e.g. FastAPI + SSE).

Broader path: [`docs/production_path.md`](docs/production_path.md).

---

## References

1. **Daniel, K., & Moskowitz, T. J. (2016).** *Momentum Crashes.*  
   Recovery-driven momentum-crash mechanism.

2. **Khandani, A. E., & Lo, A. W. (2007; 2011).** *What Happened to the Quants in August 2007?*  
   Crowded-position and quant-unwind mechanism.

3. **Ken French Data Library.**  
   UMD and market-factor data used as published comparison context.
