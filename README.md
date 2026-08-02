<p align="center">
  <a href="docs/methodology.md"><img src="https://img.shields.io/badge/Docs-methodology-FFD700?style=for-the-badge" alt="Documentation"></a>
  <a href="docs/demo_walkthrough.md"><img src="https://img.shields.io/badge/Demo-15--20%20min-0A7A3E?style=for-the-badge" alt="Demo walkthrough"></a>
  <a href="notebooks/final_mvp_demo.ipynb"><img src="https://img.shields.io/badge/Notebook-final__mvp__demo-1f6feb?style=for-the-badge" alt="Demo notebook"></a>
  <a href="#limitations-read-this"><img src="https://img.shields.io/badge/Not-financial%20advice-critical?style=for-the-badge" alt="Not financial advice"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11--3.14-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11-3.14">
  <img src="https://img.shields.io/badge/uv-package%20manager-DE5FE9?style=for-the-badge" alt="uv">
  <img src="https://img.shields.io/badge/tests-~175%20pytest-brightgreen?style=for-the-badge&logo=pytest&logoColor=white" alt="pytest">
  <img src="https://img.shields.io/badge/version-v0.1.0-blue?style=for-the-badge" alt="Version">
  <img src="https://img.shields.io/badge/status-research%20MVP-orange?style=for-the-badge" alt="Research MVP">
  <img src="https://img.shields.io/badge/score-deterministic%20%7C%20null-lightgrey?style=for-the-badge" alt="No aggregate score">
</p>

```text
╔══════════════════════════════════════════════════════════════════╗
║  MOMENTUM CRASH · tail-risk monitor for quant PMs                ║
║  ──────────────────────────────────────────────────────────────  ║
║  object_0 : PM momentum book     (S&P 12-1 L10/S10 default)      ║
║  object_1 : UMD / DM benchmark   (literature context only)       ║
║  invariant: layers never merge · deterministic_score = null      ║
╚══════════════════════════════════════════════════════════════════╝
```

**A decision-support monitor for quant PMs:** is *my* momentum book becoming fragile, how does that compare with published UMD / Daniel–Moskowitz market context, and what timestamped evidence supports or challenges the reading?

```text
NOT a trading system.
NOT a crash probability.
NOT investment advice.
≈ 20h research MVP — descriptive · deterministic · auditable.
```

---

## What a PM gets in one run

| Layer | Question it answers | Output |
|---|---|---|
| **UMD / DM benchmark** | What does the published momentum-factor backdrop look like? | `normal` / `bear_low_volatility` / `panic_elevated` + state-conditioned UMD tail-loss context |
| **PM book scorecard** | Is *my* 12-1 long/short book showing known stress channels? | 4 deterministic rows with prior-only thresholds |
| **Unwind monitor** | Which crash *mechanism* is lighting up? | 6-row structure + 3 independent scenarios |
| **Crowding monitor** | Is the book *structurally* tight / theme-crowded? | T0 proxies (concentration, breadth, theme unwind) + optional T1 FINRA/GDELT side notes |
| **Mechanical unwind** | Is there a factor-aligned / absorption-stress footprint? | Factor R², extreme turnover ratio, absorption proxy, rule-based state |
| **Evidence card** | What timestamped macro/news context fits this date? | Exact-date replay (optional LLM narrative; cannot change numbers) |
| **Research validation** | Do mechanisms leave distinct historical fingerprints? | Episode table + AI worksheet (interpretability only; not a backtest) |

```text
merge(layers) → FORBIDDEN
deterministic_score → null   # by design, not a bug
```

---

## Why this exists

Momentum crashes are rare and state-dependent. A rebound after a severe drawdown can hurt a recent-winner / short-loser book in ways a single vol number misses.

Most dashboards either:
- collapse everything into one opaque score, or
- show UMD factor stress and pretend it *is* your book.

This MVP keeps the objects separate and reviewable — so a PM can challenge the reading, not just accept a label.

```text
# failure modes we refuse
opaque_score(book)     # no
umd_state == my_book   # no
llm.write(triggers)    # no
```

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
   │ comparison     │          │ (S&P 10/10 def.) │          │ 3 mechanisms      │
   │────────────────│          │──────────────────│          │───────────────────│
   │ market state   │          │ 4-row scorecard  │          │ concentration     │
   │ panic / bear   │          │ leg risk decomp  │          │ breadth, reversal │
   │ UMD tail freq  │          │                  │          │ theme unwind, …   │
   └───────┬────────┘          └────────┬─────────┘          └─────────┬─────────┘
           │                            │                              │
           │                            │         ┌────────────────────┤
           │                            │         │ Crowding panel     │
           │                            │         │ T0 proxies + T1    │
           │                            │         │ FINRA/GDELT notes  │
           │                            │         └─────────┬──────────┘
           └────────────────────────────┴───────────────────┘
                                          │
                                          ▼
                          ┌── Deterministic Evidence Card ──┐
                          └───────────────┬─────────────────┘
                     ┌────────────────────┴────────────────────┐
                     ▼                                         ▼
          exact-date evidence                       optional constrained
          replay (default)                          LLM narrative
                     └────────────────────┬────────────────────┘
                                          ▼
                         charts · JSON · HTML · Markdown
                                          │
                                          ▼
                    ┌── research_validation (offline) ──┐
                    │ episode fingerprints · AI arms    │
                    │ reuse run_mvp · no new thresholds │
                    └───────────────────────────────────┘
```

### Two objects, never blended

| Object | Role | Modules |
|---|---|---|
| **PM momentum portfolio** | Primary monitored book. Default: equal-weight S&P 500 12-1 **long-10 / short-10**. Framework is built so names/weights/universe can be swapped later. Crowding proxies attach to this book. | `portfolio/`, `monitoring/scorecard.py`, `monitoring/unwind_structure.py`, `risk/leg_decomposition.py`, `mvp/crowding_context.py` |
| **UMD comparison benchmark** | Literature backdrop only. Ken French UMD + Daniel–Moskowitz-inspired state. Answers “what does the published factor look like?”, **not** “how stressed is my book?”. | `risk/dm_engine.py`, `regime/market_state.py` |

### Monitoring panels (the actual PM surface)

**Four-row scorecard** (PM book):
1. `high_volatility_recovery` — early recovery + high realized vol (macro gate)
2. `short_minus_long_beta_gap` — short leg beta vs long leg
3. `portfolio_drawdown` — book drawdown
4. `short_loss_in_recovery` — short-leg pain in recovery

**Three independent crash mechanisms** (descriptive rules, not forecasts):
1. `bear_market_recovery_crash` — deep drawdown → fast recovery → high vol
2. `short_book_reversal_crash` — extreme short-minus-long reversal + broad loser rally
3. `crowded_theme_unwind` — correlated long cluster (`t-1`) + extreme broad selloff

**Crowding monitor** (book-structure proxies; no aggregate crowding score):
- T0 spine from unwind: portfolio concentration (effective bets / HHI), momentum breadth, correlated-theme unwind
- T1 side notes only: FINRA loser-leg short-interest z + GDELT crowding attention z (`confirm` / `contradict` / `neutral`)
- Proxies, not ownership / leverage / financing; side notes never change triggers

**Research validation** (thin offline layer; reuses `run_mvp`):
- Episode fingerprints on known dates — interpretability check that mechanisms differ (`aligned` / `partially_aligned` / `not_aligned`)
- AI value worksheet — quant-only vs `DeterministicSynthesizer` vs optional LLM (`not_run` without credentials; never fabricates)
- PM-book forward-outcome table **skipped** until historical mechanism/scorecard states are persisted
- Map: [`docs/architecture_to_value.md`](docs/architecture_to_value.md) · regen: `uv run python -m src.research_validation`

### Evidence stack (cannot rewrite risk state)

```text
[truth]  scorecard / unwind / crowding proxies
            │
            ▼
[cache]  exact-date research preview          # offline, fail-closed
            │
            ▼
[llm?]   constrained interpretation           # narrative only; ID-bound
            │
            ▼
[rag?]   GDELT + DeepSeek                     # trigger-gated; research path

# privilege model
evidence ⊬ rewrite(metric | threshold | trigger | risk_state)
```

Point-in-time rules of thumb:
- market / risk windows end on `as_of_date`
- theme-cluster membership stops at `t-1`
- evidence publication ≤ local cutoff (default 16:00 ET)
- missing stays `unavailable` — never invented

---

## Quick start

Python **3.11–3.14** and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync --locked --all-groups
uv run python -m src.mvp.demo_smoke_test    # → {"status": "ready"}
uv run python -m src.research_validation    # → outputs/research_validation/*
uv run python -m pytest -q                  # contract + smoke tests
```

Open the single demo notebook:

```bash
uv run --with jupyterlab jupyter lab notebooks/final_mvp_demo.ipynb
```

Edit only the parameter cell, then **Run All**:

```python
from src.mvp.config import MVPConfig
from src.mvp.pipeline import run_mvp

CONFIG = MVPConfig(
    as_of_date="2024-01-05",
    compare_to_date="2023-12-01",
    threshold_profile="default",
    horizon_days=20,
    use_llm=False,          # reliable offline path; full card still renders
)
result = run_mvp(CONFIG)
# result.unwind · result.deterministic_input · crowding via presentation
```

### Contrast dates worth reviewing

| Date | Why look |
|---|---|
| `2020-03-24` | `bear_market_recovery_crash` triggers (fingerprint: aligned) |
| `2020-11-02` | style-rotation prior; short reversal on **watch** (partially_aligned) |
| `2024-01-05` | default demo — recovery on watch, no confirmed theme unwind |
| `2026-05-29` | `crowded_theme_unwind` on a pre-event correlated cluster (aligned) |

Full fingerprint table: [`outputs/research_validation/episode_fingerprints.md`](outputs/research_validation/episode_fingerprints.md).

### Optional env vars

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Evidence-card LLM narrative |
| `DEEPSEEK_API_KEY` | Optional GDELT RAG explainer |
| `SEC_CONTACT_EMAIL` | SEC EDGAR fetch (fundamental anchor) |

---

## Example output (2024-01-05)

From [`outputs/example_risk_output/pm_risk_assessment_2024-01-05.md`](outputs/example_risk_output/pm_risk_assessment_2024-01-05.md):

```text
$ run_mvp --as-of 2024-01-05
────────────────────────────────────────────────────────
UMD comparison benchmark:     bear_low_volatility
PM scorecard triggers:        0
Active mechanism scenarios:   none
Crowding (T0):                concentration / breadth normal; theme not_confirmed
Crowding (T1 side notes):     FINRA neutral · GDELT narrative neutral
Evidence quality:             available
────────────────────────────────────────────────────────
short_minus_long_beta_gap     not_triggered
portfolio_drawdown            not_triggered
short_loss_in_recovery        not_triggered
────────────────────────────────────────────────────────
Fingerprint: 750f22225b7d9592
deterministic_score: null
```

A PM reading this should conclude: *backdrop is soft-bear / low-vol; the customized book is not firing stress or crowding channels on this date* — not “crash probability = X%”.

Research-validation side panel (same date as negative control):

```text
$ python -m src.research_validation
────────────────────────────────────────────────────────
episode fingerprints     → outputs/research_validation/episode_fingerprints.md
ai value worksheet       → ai_value_review.csv  (LLM arm: not_run w/o keys)
pm-book forward outcomes → skipped (no historical mechanism series yet)
architecture → value     → docs/architecture_to_value.md
────────────────────────────────────────────────────────
# priors never enter computation · no threshold retune after the table
```

---

## Repository map

```text
momentum_crash/
├── README.md
├── Future_To_DO.md              # PM imagination space (T2–T4+)
├── docs/
│   ├── methodology.md           # formulas, assumptions, decision boundary
│   ├── limitations.md           # what we deliberately do not claim
│   ├── demo_walkthrough.md      # 15–20 min reviewer path
│   └── architecture_to_value.md # component → PM question → evidence
├── notebooks/
│   └── final_mvp_demo.ipynb     # single presentation notebook
├── src/
│   ├── mvp/                     # config · pipeline · card · crowding · present
│   ├── research_validation.py   # episode fingerprints · AI arms · writers
│   ├── monitoring/              # scorecard · unwind · contracts
│   ├── portfolio/ regime/ risk/ features/
│   ├── evidence/                # corpus · preview · optional GDELT/DeepSeek
│   └── data/ utils/
├── tests/                       # smoke / integration / contract tests
├── data/processed/              # committed reproducibility inputs
└── outputs/
    ├── example_risk_output/     # PM card snapshot
    └── research_validation/     # fingerprints · AI worksheet · skip note
```

Superseded phase docs / research modules live in Git history (`pre-mvp-consolidation` tag).

---

## Documentation

1. [Methodology](docs/methodology.md) — portfolio construction, scorecard, unwind rules
2. [Limitations](docs/limitations.md) — full honesty list
3. [Demo walkthrough](docs/demo_walkthrough.md) — 15–20 minute PM review script
4. [Architecture to value](docs/architecture_to_value.md) — component → PM question → current evidence

---

## Limitations (read this)

- Default PM book uses **current SPY membership historically** → survivorship bias; not a plug-in for a live book yet.
- UMD header state ≠ score for the PM book. Do not blend the two layers.
- Evidence is **exact-date cached replay**, not institutional live retrieval.
- Mechanism scenarios are **descriptive rules** without OOS predictive validation.
- Episode fingerprints are **interpretability checks**, not predictive backtests; priors never retune thresholds.
- No persisted historical mechanism/scorecard state series yet → descriptive PM-book forward-outcome table is deferred.
- No leverage, financing, forced-selling, or order-flow observation.
- Crowding is **book-structure proxy** (+ optional FINRA/GDELT side notes), not observed ownership or street positioning.
- Optional LLM / RAG layers organize narrative only — they cannot change values, thresholds, triggers, or risk state. Incremental LLM analyst value remains unscored until reviewed runs.

Full list: [docs/limitations.md](docs/limitations.md).

---

## Future work

See **[Future_To_DO.md](Future_To_DO.md)** for the PM-facing roadmap (T2 holdings
plug-in, T3 observed crowding, T4 leverage / financing / flow, and broader
production imagination). Short list:

- Point-in-time membership and industry history
- Plug-in interface for a PM’s own holdings / weights
- Observed holdings / leverage / flow / street crowding
- Persist mechanism/scorecard history → descriptive 5d/20d PM-book forward outcomes
- Out-of-sample validation of the three mechanism rules
- Production-grade retrieval beyond offline preview
- Human-reviewed LLM arm scores in `ai_value_review.csv`
