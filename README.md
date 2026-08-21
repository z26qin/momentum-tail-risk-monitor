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

1. [`outputs/current_semi_unwind/pm_case_read.md`](outputs/current_semi_unwind/pm_case_read.md) — what the product looks like (2026-05-29)  
2. [`notebooks/final_mvp_demo.ipynb`](notebooks/final_mvp_demo.ipynb) — click through the same case  
3. WhatsApp — a seven-line note, or silence if nothing material changed  
4. Engineers: [`src/agent.py`](src/agent.py) · [`docs/hermes_whatsapp_poc.md`](docs/hermes_whatsapp_poc.md) · [`docs/methodology.md`](docs/methodology.md)

---

## What a PM sees

The demo book is an equal-weight S&P 500 **12-1 long-10 / short-10** (a transparent proxy, not a live institutional portfolio).

On a quiet day, **nothing is sent**. On a material change, or if you ask, you get a short note like this (frozen 2026-05-29 case — not a live call):

```text
Not a confirmed crowded unwind.

Observed: CIEN–COHR–LITE cluster; crowding flag on; book 0/4 scorecard triggers.
Inferred: localized theme pressure, not a system-wide unwind.
Against: liquidity is still absorbing; no book-wide footprint; no short-leg squeeze.
Not confirmed: forced deleveraging / financing stress.
Next: watch whether selling spreads outside the cluster.
```

Same read in one table:

| PM question | Current read |
|---|---|
| Where is the risk? | Concentrated long-side cluster (`CIEN`–`COHR`–`LITE`) |
| Recovery crash? | Not confirmed |
| Crowded unwind? | Partially supported — local, not broad |
| What is missing? | Forced deleveraging, liquidity failure, propagation |
| What next? | Watch breadth, selling outside the cluster, absorption |

Full write-up: [`outputs/current_semi_unwind/pm_case_read.md`](outputs/current_semi_unwind/pm_case_read.md). Offline mockup: [`docs/figures/dashboard_mockup.html`](docs/figures/dashboard_mockup.html).

<p align="center">
  <img src="docs/figures/dashboard_mockup_preview.png" alt="Momentum tail-risk monitor — PM workflow prototype" width="920">
</p>

Two other frozen dates, same rules: [March 2020](outputs/march_2020_reference/pm_case_read.md) looks like a recovery-crash setup; [January 2024](outputs/quiet_control_2024/pm_case_read.md) stays quiet. Cross-case table: [`outputs/cross_case_comparison.md`](outputs/cross_case_comparison.md).

---

## How it works

Three layers. Only the first one can change the risk numbers.

```text
1. Rules engine
   Computes the book state: regime, drawdown, legs, crowding flags.
   This is the source of truth. AI cannot rewrite it.

2. Investigation agent
   If a flag is on, it looks up dated news / positioning / filings
   and asks: does public evidence support, contradict, or still miss
   the story? If the first pass is thin, it asks one narrower
   follow-up. Then it stops.

3. Short PM note
   Notebook report, or WhatsApp. If nothing material changed
   since the last check, WhatsApp stays silent.
```

The split in one sentence:

> **The rules engine owns the risk state. The agent owns the investigation. The note cannot place a trade.**

Evidence must already have been public by the assessment close. Missing facts stay missing — the agent is not allowed to fill gaps.

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

For a reviewer who wants the mechanics. A PM can skip this section.

The agent sits **on top of** the rules engine. It never writes thresholds, triggers, scores, or portfolio calculations.

```text
Observe the current risk flags
        ↓
Decide the next search
  (crowding, recovery, or fundamentals —
   or a narrower follow-up on the open question)
        ↓
Retrieve dated evidence
        ↓
Remember what was already asked
        ↓
Stop when the story is clear, still missing, or the budget is used
```

The function to point at is `run_investigation_loop` in [`src/agent.py`](src/agent.py).

Next action is **not** a fixed pipeline. It depends on the flags, evidence already in hand, which story has been checked, and remaining steps (default 4):

1. Nothing to investigate → stop  
2. Current story still mixed / thin → one narrower follow-up on **that same** story  
3. Otherwise check the next uninvestigated story: crowding → recovery → fundamentals  
4. Stop  

Failed retrieval is not treated as supporting evidence. The same query is not searched twice. Anything published after the cutoff is discarded.

```python
from src.agent import run_investigation_agent

result = run_investigation_agent(as_of_date="2026-05-29", max_steps=4, verbose=True)
print(result.report)
```

On the 2026-05-29 crowding case the path looks like:

```text
[Agent 0] loaded the risk flags
[Agent 1] searched crowding / positioning evidence
[Agent 1] mixed — tech exposure cut, but not a broad unwind
[Agent 2] asked a narrower follow-up on deleveraging
[Agent 2] stopped: still not established
```

---

## WhatsApp agent (Hermes)

Same monitor, delivered on a phone. Hermes does not recompute the book. Setup: [`docs/hermes_whatsapp_poc.md`](docs/hermes_whatsapp_poc.md).

```text
You (or a scheduled job) ask for the latest read
        ↓
The rules engine writes a compact snapshot
        ↓
Compare with yesterday
        ↓
Nothing material changed?  →  silence
You asked a question, or the state changed?
        ↓
Investigate dated evidence, then send a seven-line note
```

Rules that matter on WhatsApp:

- The 0–100 number is a **monitoring band**, not a crash probability. Copy it; do not invent one.  
- Silence is the default. Score wiggling inside the same band is not an alert.  
- Claims are labeled **observed / inferred / not confirmed**.  
- “Should I cut the longs overnight?” is refused.

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
                    observe → decide → tool → memory → stop
                                          │
                           ┌──────────────┴──────────────┐
                           ▼                             ▼
                  PM-facing report              WhatsApp skill
                  (notebook)                    short note or silence
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

Expect a seven-line PM note with **book 0/4** (triggered book channels, not “four metrics exist”). Score questions (`What is the current momentum risk score?`) copy the JSON 0–100 monitoring score and must not call it a crash probability. Unchanged cron ticks return `[SILENT]` and send nothing.

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
│   ├── compare_monitor_state.py # previous-state compare → [SILENT] or diff
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
