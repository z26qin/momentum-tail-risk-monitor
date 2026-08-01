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

# Momentum Crash

**A decision-support monitor for quant PMs:** is *my* momentum book becoming fragile, how does that compare with published UMD / Daniel–Moskowitz market context, and what timestamped evidence supports or challenges the reading?

Not a trading system. Not a crash probability. Not investment advice.
Roughly a 20-hour research MVP — descriptive, deterministic, and auditable.

---

## What a PM gets in one run

| Layer | Question it answers | Output |
|---|---|---|
| **UMD / DM benchmark** | What does the published momentum-factor backdrop look like? | `normal` / `bear_low_volatility` / `panic_elevated` + state-conditioned UMD tail-loss context |
| **PM book scorecard** | Is *my* 12-1 long/short book showing known stress channels? | 4 deterministic rows with prior-only thresholds |
| **Unwind monitor** | Which crash *mechanism* is lighting up? | 6-row structure + 3 independent scenarios |
| **Evidence card** | What timestamped macro/news context fits this date? | Exact-date replay (optional LLM narrative; cannot change numbers) |

These layers are **never merged**. `deterministic_score` is intentionally `null`.

---

## Why this exists

Momentum crashes are rare and state-dependent. A rebound after a severe drawdown can hurt a recent-winner / short-loser book in ways a single vol number misses.

Most dashboards either:
- collapse everything into one opaque score, or
- show UMD factor stress and pretend it *is* your book.

This MVP keeps the objects separate and reviewable — so a PM can challenge the reading, not just accept a label.

---

## System design

```text
                         MVPConfig
                    as_of · compare_to · horizon · LLM
                                  |
                                  v
                         run_mvp()   <-- single entry
                                  |
        +-------------------------+-------------------------+
        |                         |                         |
        v                         v                         v
 +--------------+      +------------------+      +-------------------+
 | UMD / DM     |      | PM momentum book |      | Unwind +          |
 | comparison   |      | (S&P 10/10 def.) |      | 3 mechanisms      |
 |              |      |                  |      |                   |
 | market state |      | 4-row scorecard  |      | concentration,    |
 | panic / bear |      | leg risk decomp  |      | breadth, reversal |
 | UMD tail freq|      |                  |      | theme unwind, ... |
 +------+-------+      +--------+---------+      +---------+---------+
        |                       |                          |
        +-----------------------+--------------------------+
                                |
                                v
                  Deterministic Evidence Card
                                |
               +----------------+----------------+
               |                                 |
               v                                 v
     exact-date evidence               optional constrained
     replay (default)                  LLM narrative
               |                                 |
               +----------------+----------------+
                                |
                                v
                 charts · JSON · HTML · Markdown
```

### Two objects, never blended

| Object | Role | Modules |
|---|---|---|
| **PM momentum portfolio** | Primary monitored book. Default: equal-weight S&P 500 12-1 **long-10 / short-10**. Framework is built so names/weights/universe can be swapped later. | `portfolio/`, `monitoring/scorecard.py`, `monitoring/unwind_structure.py`, `risk/leg_decomposition.py` |
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

### Evidence stack (cannot rewrite risk state)

```text
deterministic scorecard / unwind   ← source of truth
        ↓
exact-date research preview        ← default demo path (offline cache)
        ↓
optional LLM interpretation        ← narrative only, evidence-ID constrained
        ↓
optional GDELT + DeepSeek RAG      ← trigger-gated explanation layer (research)
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
uv run python -m src.mvp.demo_smoke_test    # expect "status": "ready"
uv run python -m pytest -q                  # ~175 tests
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
```

### Contrast dates worth reviewing

| Date | Why look |
|---|---|
| `2020-03-24` | `bear_market_recovery_crash` triggers |
| `2024-01-05` | default demo — recovery on watch, no confirmed theme unwind |
| `2026-05-29` | `crowded_theme_unwind` on a pre-event correlated cluster |

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
UMD comparison benchmark:     bear_low_volatility
PM scorecard triggers:        0
Active mechanism scenarios:   none
Evidence quality:             available

short_minus_long_beta_gap     not_triggered
portfolio_drawdown            not_triggered
short_loss_in_recovery        not_triggered

Fingerprint: 750f22225b7d9592
```

A PM reading this should conclude: *backdrop is soft-bear / low-vol; the customized book is not firing stress channels on this date* — not “crash probability = X%”.

---

## Repository map

```text
README.md
docs/
  methodology.md          # formulas, assumptions, decision boundary
  limitations.md          # what we deliberately do not claim
  demo_walkthrough.md     # 15–20 min reviewer path
notebooks/
  final_mvp_demo.ipynb    # single presentation notebook
src/
  mvp/                    # config · pipeline · evidence card · presentation
  monitoring/             # scorecard · unwind · contracts
  portfolio/ regime/ risk/ features/
  evidence/               # corpus · exact-date preview · optional GDELT/DeepSeek
  data/ utils/
tests/                    # smoke / integration / contract tests
data/processed/           # committed reproducibility inputs
outputs/example_risk_output/
```

Superseded phase docs / research modules live in Git history (`pre-mvp-consolidation` tag).

---

## Documentation

1. [Methodology](docs/methodology.md) — portfolio construction, scorecard, unwind rules
2. [Limitations](docs/limitations.md) — full honesty list
3. [Demo walkthrough](docs/demo_walkthrough.md) — 15–20 minute PM review script

---

## Limitations (read this)

- Default PM book uses **current SPY membership historically** → survivorship bias; not a plug-in for a live book yet.
- UMD header state ≠ score for the PM book. Do not blend the two layers.
- Evidence is **exact-date cached replay**, not institutional live retrieval.
- Mechanism scenarios are **descriptive rules** without OOS predictive validation.
- No leverage, financing, forced-selling, or order-flow observation.
- Optional LLM / RAG layers organize narrative only — they cannot change values, thresholds, triggers, or risk state.

Full list: [docs/limitations.md](docs/limitations.md).

---

## Future work

- Point-in-time membership and industry history
- Plug-in interface for a PM’s own holdings / weights
- Observed holdings / leverage / flow data
- Out-of-sample validation of the three mechanism rules
- Production-grade retrieval beyond offline preview
