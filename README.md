<p align="center">
  <a href="docs/methodology.md"><img src="https://img.shields.io/badge/Docs-methodology-FFD700?style=for-the-badge" alt="Documentation"></a>
  <a href="docs/demo_walkthrough.md"><img src="https://img.shields.io/badge/Demo-15--20%20min-0A7A3E?style=for-the-badge" alt="Demo walkthrough"></a>
  <a href="notebooks/final_mvp_demo.ipynb"><img src="https://img.shields.io/badge/Notebook-final__mvp__demo-1f6feb?style=for-the-badge" alt="Demo notebook"></a>
  <a href="#what-we-refuse-to-claim"><img src="https://img.shields.io/badge/Status-Research%20MVP-orange?style=for-the-badge" alt="Research MVP"></a>
</p>

# Momentum Tail-Risk Monitor

**An AI-assisted monitor that helps a PM recognize fragile momentum setups, locate risk in the book, and challenge the read with timestamp-valid evidence — before acting.**

This is an approximately **20-hour research MVP**. It does **not** predict crash timing, publish a calibrated crash probability, optimize a portfolio, or issue a trade instruction.

The architectural split is:

> **The deterministic quantitative engine owns the risk state. The agent owns the investigation loop.**

### Start here

1. [`src/agent.py`](src/agent.py) — hand-written investigation loop (`run_investigation_loop`)  
2. [`integrations/hermes/momentum-risk-monitor/`](integrations/hermes/momentum-risk-monitor/) — Hermes WhatsApp skill  
3. [`notebooks/final_mvp_demo.ipynb`](notebooks/final_mvp_demo.ipynb) — step-by-step runbook (Step 8 is the agent)  
4. [`outputs/current_semi_unwind/pm_case_read.md`](outputs/current_semi_unwind/pm_case_read.md) — primary example (2026-05-29)  
5. [`docs/hermes_whatsapp_poc.md`](docs/hermes_whatsapp_poc.md) · [`docs/methodology.md`](docs/methodology.md) · [`docs/limitations.md`](docs/limitations.md)

---

## The problem

Momentum reversal risk is ambiguous. The same drawdown can be ordinary noise, a recovery-driven reversal, or a crowded-position unwind. The PM question is not “will momentum crash tomorrow?” It is:

> Where is the pressure, which mechanism is supported, what evidence challenges that read, and what should we check next?

Default monitored book: equal-weight S&P 500 **12-1 long-10 / short-10** (inspectable demo proxy, not a production portfolio). Ken French UMD / Daniel–Moskowitz market state is **comparison context only**. Mechanism detail is [below](#mechanisms); construction detail: [`docs/methodology.md`](docs/methodology.md).

---

## Agent loop

The investigation agent sits **on top of** `run_mvp()`. It never writes thresholds, triggers, scores, or portfolio calculations.

```text
state["risk"] = run_deterministic_monitor(...)   # immutable

while not done:
    observation = observe(state)
    action      = decide_next_action(observation)
    result      = execute_tool(action)
    state       = update_memory(state, action, result)
    done        = should_stop(state)

return build_pm_report(state)
```

The function to point at is `run_investigation_loop` in [`src/agent.py`](src/agent.py): observe → decide → execute a tool → update episode memory → classify **mechanism-scoped** evidence → stop or continue.

### What the next action depends on

Not a fixed pipeline. `decide_next_action` uses the current risk state, evidence already collected, which mechanisms have been investigated, and remaining budget:

1. No meaningful risk signal → `FINISH`
2. Current mechanism is still `insufficient` / `mixed` → one narrower `FOLLOWUP_SEARCH` on **that same** mechanism
3. Else the next uninvestigated mechanism: crowding (`SEARCH_KL_CROWDING`) → DM recovery (`SEARCH_DM_RECOVERY`) → fundamentals (`SEARCH_FUNDAMENTALS`)
4. Otherwise stop

Tools stay small: `local_evidence`, `search_news`, `search_positioning_evidence`. Duplicate queries are skipped. Evidence with `published_at` after `assessment_cutoff` is discarded.

### Stopping and fail-closed behavior

Stop when any of these holds: no investigation needed; evidence is sufficient; evidence remains insufficient (do not hallucinate); `max_steps = 4`; tool failure. A failed tool is **not** supporting evidence. Missing evidence stays missing. LLM `confidence` is evidence quality, not a crash probability, and cannot trigger a portfolio action.

```python
from src.agent import run_investigation_agent

result = run_investigation_agent(
    as_of_date="2026-05-29",
    max_steps=4,
    verbose=True,
)
print(result.report)
```

Notebook Step 8 calls `run_investigation_demo(result)` on an already-computed `run_mvp` result.

Example path on the frozen 2026-05-29 crowding case:

```text
[Agent 0] deterministic state loaded: 1/4 triggers
[Agent 1] action=SEARCH_KL_CROWDING
[Agent 1] assessment=MIXED
[Agent 1] next_question='Is there evidence of broad deleveraging?'
[Agent 2] action=FOLLOWUP_SEARCH
[Agent 2] stop=EVIDENCE_INSUFFICIENT
```

Localized crowding can be supported without confirming broad forced deleveraging. That does **not** escalate the deterministic risk state.

---

## Hermes agent design

Hermes is a thin WhatsApp / cron wrapper around the **same** deterministic monitor. It does not recalculate triggers or the 0–100 monitoring score. The unofficial Baileys WhatsApp bridge is a delivery channel only. Full setup: [`docs/hermes_whatsapp_poc.md`](docs/hermes_whatsapp_poc.md).

```text
cron / WhatsApp
      │
      ▼
scripts/run_monitor.py  →  compact JSON  (run_mvp, use_llm=False)
      │
      ▼
compare with previous assessment
      │
      ├── no material change → reply exactly [SILENT]
      └── material change or explicit PM question
                │
                ▼
         investigation policy
         (support / contradict / missing)
                │
                ▼
         seven-line PM note on WhatsApp
```

Design rules, from [`integrations/hermes/momentum-risk-monitor/SKILL.md`](integrations/hermes/momentum-risk-monitor/SKILL.md) and [`investigation_policy.md`](integrations/hermes/momentum-risk-monitor/investigation_policy.md):

- Compact JSON is the source of truth. Copy `monitoring_severity_score`; never present it as a crash probability (`score_is_probability` is always false).
- Investigate only on a material state change **or** an explicit explanation request. Integer score drift inside the same band is not an alert.
- Use only evidence with publication timestamp ≤ `evidence_cutoff` (US close on `as_of_date`).
- Label claims **observed** / **inferred** / **not confirmed**. A Prime Book technology reduction is not a confirmed system-wide Khandani–Lo unwind.
- Follow-ups stay phone-sized. Trade, hedge, or de-gross instructions are refused.

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
                              (immutable source of truth)
                                          │
                           ┌──────────────┴──────────────┐
                           ▼                             ▼
                 exact-date evidence            LLM interpretation
                 cache replay                 OpenAI/Deepseek/Claude
                           └──────────────┬──────────────┘
                                          ▼
                         Investigation agent loop
                    observe → decide → tool → memory → stop
                                          │
                           ┌──────────────┴──────────────┐
                           ▼                             ▼
                  PM-facing report              Hermes WhatsApp skill
                  (notebook Step 8)             compact JSON · [SILENT]
```

1. **Macro risk state and PM book first.**  
2. **The agent investigates; it does not score.** Recovery risk and crowded unwind stay separate.  
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

**Date note:** the primary frozen product pack is **2026-05-29**. `demo_smoke_test` / `default_demo_config()` currently use **2026-06-30** (bundled panel coverage).

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

## Mechanisms

The same drawdown can be ordinary noise, a **recovery-driven reversal**, or a **crowded-position unwind**. The agent investigates these lenses separately; it does not merge them into one score.

### Decision workflow

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

Outputs stay separate and auditable. Deterministic metrics are the source of truth; AI organizes evidence only.

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
