<p align="center">
  <a href="docs/methodology.md"><img src="https://img.shields.io/badge/Docs-methodology-FFD700?style=for-the-badge" alt="Documentation"></a>
  <a href="docs/demo_walkthrough.md"><img src="https://img.shields.io/badge/Demo-15--20%20min-0A7A3E?style=for-the-badge" alt="Demo walkthrough"></a>
  <a href="notebooks/final_mvp_demo.ipynb"><img src="https://img.shields.io/badge/Notebook-final__mvp__demo-1f6feb?style=for-the-badge" alt="Demo notebook"></a>
  <a href="#what-it-will-not-do"><img src="https://img.shields.io/badge/Status-Research%20MVP-orange?style=for-the-badge" alt="Research MVP"></a>
</p>

# Momentum Tail-Risk Monitor

A morning risk note for a momentum book.

It helps a PM see **where the pressure is**, **which story is actually supported**, **what is still missing**, and **what to check next** — before acting.

It does **not** tell you when a crash will happen, give a crash probability, or tell you to trade.

### Start here

1. [`outputs/current_semi_unwind/pm_case_read.md`](outputs/current_semi_unwind/pm_case_read.md) — the 2026-05-29 note  
2. [`notebooks/final_mvp_demo.ipynb`](notebooks/final_mvp_demo.ipynb) — click through the same case  
3. WhatsApp — the same short note on a phone  
4. Engineers: [`src/agent.py`](src/agent.py) · [`docs/hermes_whatsapp_poc.md`](docs/hermes_whatsapp_poc.md) · [`docs/methodology.md`](docs/methodology.md)

---

## What a PM sees

A short morning note. Not a model dump, and not a trade.

The demo book is an equal-weight S&P 500 **12-1 long-10 / short-10** (a transparent proxy, not a live institutional portfolio). Frozen 2026-05-29 case — not a live call:

```text
Not a confirmed crowded unwind.

Observed: pressure in CIEN–COHR–LITE, not the whole book.
Inferred: localized crowding, not a market-wide unwind.
Against: liquidity is still absorbing; shorts are not being squeezed.
Not confirmed: forced selling / financing stress.
Next: watch whether selling spreads outside the cluster.
```

| PM question | Current read |
|---|---|
| Where is the risk? | A concentrated long-side cluster (`CIEN`–`COHR`–`LITE`) |
| Recovery crash? | Not confirmed |
| Crowded unwind? | Partially supported — local, not broad |
| What is missing? | Forced selling, liquidity failure, selling outside the cluster |
| What next? | Watch breadth, selling outside the cluster, and whether liquidity still holds |

Full write-up: [`outputs/current_semi_unwind/pm_case_read.md`](outputs/current_semi_unwind/pm_case_read.md). Offline mockup: [`docs/figures/dashboard_mockup.html`](docs/figures/dashboard_mockup.html).

<p align="center">
  <img src="docs/figures/dashboard_mockup_preview.png" alt="Momentum tail-risk monitor — PM workflow prototype" width="920">
</p>

Same rules on two other dates: [March 2020](outputs/march_2020_reference/pm_case_read.md) looks like a recovery-crash setup; [January 2024](outputs/quiet_control_2024/pm_case_read.md) does not escalate. Cross-case table: [`outputs/cross_case_comparison.md`](outputs/cross_case_comparison.md).

---

## How it works

```text
1. Measure the book
   Where losses sit, and how concentrated they are.
   These numbers are the source of truth. AI cannot rewrite them.

2. Investigate the story
   Look up what was already public that day. Does it support the
   crowding story, the recovery story, or neither? If the first
   pass is thin, ask one more specific question, then stop.

3. Write the note
   Where is the pressure, what is supported, what is still missing,
   what to check next. Notebook or WhatsApp — same read.
```

> **Numbers first. Investigation second. The note cannot place a trade.**

Only information that was already public by that day's close is used. If something is not in the record, the note says so. It does not invent it.

---

## What it will not do

- Call crash timing or publish a crash probability  
- Issue a trade, hedge, or de-gross instruction  
- Treat “hedge funds cut tech” as proof of forced deleveraging  
- Treat public short-interest / news volume as ownership or leverage  
- Pretend the demo 10/10 book is your live book  

Fuller list: [`docs/limitations.md`](docs/limitations.md).

---

## Agent loop

For a reviewer. A PM can skip this.

The agent sits on top of the numbers. It never changes them.

```text
Read the current book state
        ↓
Choose what to look up next
  (crowding, recovery, or fundamentals)
        ↓
Read dated public evidence
        ↓
If the first pass is thin, ask one narrower question
        ↓
Stop and write the note
```

Code: `run_investigation_loop` in [`src/agent.py`](src/agent.py).

```python
from src.agent import run_investigation_agent

result = run_investigation_agent(as_of_date="2026-05-29", max_steps=4, verbose=True)
print(result.report)
```

On the 2026-05-29 case: it looked up crowding evidence, found a tech-exposure cut that did not prove a broad unwind, asked one follow-up, and stopped.

---

## WhatsApp (Hermes)

The same note, on a phone. Hermes does not recompute the book. Setup: [`docs/hermes_whatsapp_poc.md`](docs/hermes_whatsapp_poc.md).

- A 0–100 monitoring band may appear in the note. It is **not** a crash probability.  
- Claims are labeled **observed / inferred / not confirmed**.  
- “Should I cut the longs overnight?” is refused.

---

## System design

For a reviewer.

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
   └───────┬────────┘          └────────┬─────────┘          └─────────┬─────────┘
           │                            │                              │
           └────────────────────────────┴──────────────────────────────┘
                                          │
                                          ▼
                              Deterministic risk read
                              (immutable source of truth)
                                          │
                                          ▼
                         Investigation agent loop
                                          │
                           ┌──────────────┴──────────────┐
                           ▼                             ▼
                  Notebook report               WhatsApp note
```

1. **Book and market state first.**  
2. **The agent investigates; it does not score.**  
3. **AI cannot change the numbers.**  
4. **Missing evidence stays missing.**  
5. **Only information that was public by the selected close is allowed.**

---

## How to run

Requirements: Python **3.11–3.14** and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync --locked --all-groups
uv run python -m src.mvp.demo_smoke_test
uv run python -m pytest -q
uv run --with jupyterlab jupyter lab notebooks/final_mvp_demo.ipynb
uv run python scripts/run_monitor.py --as-of-date 2026-05-29 --evidence-cutoff "2026-05-29 16:00 ET"
```

```python
from src.mvp.config import MVPConfig
from src.mvp.pipeline import run_mvp
from src.agent import run_investigation_agent

config = MVPConfig(
    as_of_date="2026-05-29",
    compare_to_date="2026-04-30",
    threshold_profile="default",
    horizon_days=20,
    use_llm=False,  # library default; notebook demo uses True
)
result = run_mvp(config)
agent = run_investigation_agent(
    as_of_date=config.as_of_date,
    max_steps=4,
    verbose=True,
    mvp_result=result,
)
print(agent.report)
```

**Date note:** the primary frozen product pack is **2026-05-29**. `demo_smoke_test` / `default_demo_config()` currently use **2026-06-30** (bundled panel coverage). Frozen packs do not change with the notebook `CONFIG`; the live `run_mvp` cell does.

### Hermes + WhatsApp quick setup

Local Mac only. Do not commit `~/.hermes/`, phone numbers, or QR sessions. Symlink **this repo’s** skill (not a copy under `~/integrations`). Full steps: [`docs/hermes_whatsapp_poc.md`](docs/hermes_whatsapp_poc.md).

```bash
uv sync --locked --all-groups
uv run python scripts/run_monitor.py \
  --as-of-date 2026-05-29 \
  --evidence-cutoff "2026-05-29 16:00 ET" \
  --output-json outputs/latest_assessment.json

mkdir -p ~/.hermes/skills
ln -sfn "$(pwd)/integrations/hermes/momentum-risk-monitor" \
  ~/.hermes/skills/momentum-risk-monitor
```

In `~/.hermes/config.yaml` (quote `"off"`):

```yaml
display:
  tool_progress: "off"
  show_reasoning: false
  personality: concise
  platforms:
    whatsapp:
      tool_progress: "off"
      show_reasoning: false
      streaming: false
whatsapp:
  reply_prefix: ""
```

```bash
hermes gateway setup    # pick WhatsApp, scan QR (dedicated number)
hermes gateway run      # no -v
```

WhatsApp, in order:

```text
/verbose off
/sethome
/new now
/momentum-risk-monitor Why is this not a Khandani–Lo unwind? Short version only.
```

Expect the same short PM note as above. Setup and operator details: [`docs/hermes_whatsapp_poc.md`](docs/hermes_whatsapp_poc.md).

---

## LLM interpretation (DeepSeek)

Deterministic metrics, thresholds, triggers, and risk state are always computed first. The LLM is an interpretation layer only — including inside the investigation agent.

| Mode | How to run | Behavior |
|---|---|---|
| **Offline deterministic** | `use_llm=False` (`MVPConfig` library default) | No API call. Evidence Card + PM narrative use calibrated deterministic text. The agent uses a heuristic classifier. |
| **Live DeepSeek-assisted** | `notebooks/demo_setup.py` sets `USE_LLM=True` + `DEEPSEEK_API_KEY` in `.env` | `final_mvp_demo.ipynb` injects `DeepSeekEvidenceInterpreter` and `DeepSeekPMResponseInterpreter` into `run_mvp`. Missing key, HTTP failure, or schema validation fails closed to deterministic text. |

The demo runbook is configured for the live path (`USE_LLM=True` in `notebooks/demo_setup.py`). Without a key it still runs via fail-closed deterministic fallback and never rewrites metrics.

The LLM cannot rewrite: metric · threshold · trigger · risk state.

To enable the live path, create `.env` in the repository root with:

    DEEPSEEK_API_KEY=sk-your-key
    ANTHROPIC_API_KEY=xxxx

A separate, optional **public narrative-shift POC** uses the DeepSeek
Responses API with server-side web search. It is exploratory only and does
not change the scorecard. Install the extra with `uv sync --group poc`.
See [`docs/narrative_shift_poc.md`](docs/narrative_shift_poc.md).

---

## Mechanisms

The same drawdown can be ordinary noise, a **recovery-driven reversal**, or a **crowded-position unwind**. The agent investigates these lenses separately; it does not merge them into one score.

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

## Repository map

```text
momentum-tail-risk-monitor/
├── README.md
├── docs/
│   ├── methodology.md           # technical methodology
│   ├── wiki/                    # per-metric threshold wiki (why / cutoff / what a move means)
│   ├── limitations.md
│   ├── demo_walkthrough.md
│   ├── hermes_whatsapp_poc.md   # Hermes + unofficial WhatsApp Baileys setup
│   ├── narrative_shift_poc.md   # exploratory public-narrative POC (not scorecard)
│   ├── narrative_shift_poc_simulated.md  # simulated POC report (not a live API result)
│   ├── production_path.md       # production path (not an internal todo list)
│   ├── architecture_to_value.md # component → PM question map
│   └── figures/                 # offline PM workflow prototype
├── prompts/
│   └── narrative_shift_poc.txt  # editable user prompt for the narrative POC
├── notebooks/
│   └── final_mvp_demo.ipynb     # step-by-step runbook for the PPT demo
├── scripts/
│   ├── run_monitor.py           # compact JSON CLI over run_mvp()
│   ├── compare_monitor_state.py # previous-state compare for scheduled runs
│   └── run_narrative_shift_poc.py  # exploratory DeepSeek Responses narrative POC
├── integrations/hermes/         # Hermes skill (copy/symlink into ~/.hermes/skills)
├── src/
│   ├── agent.py                 # hand-written investigation loop (does not change risk state)
│   ├── agent_prompts.py
│   ├── mvp/                     # config, run_mvp, evidence card, PM response
│   ├── monitoring/              # scorecard, unwind, crowding proxies
│   ├── portfolio/               # 12-1 L10/S10 construction
│   ├── regime/                  # market-state classification
│   ├── risk/                    # beta, legs, concentration
│   ├── evidence/                # timestamped evidence + optional LLM
│   ├── features/
│   ├── data/
│   └── utils/
├── tests/                       # regression guards, grouped to match src/
│   ├── agent/
│   ├── data/
│   ├── evidence/
│   ├── features/
│   ├── monitoring/
│   ├── mvp/
│   ├── portfolio/
│   ├── regime/
│   ├── research/
│   └── risk/
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
