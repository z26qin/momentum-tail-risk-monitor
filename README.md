# Momentum Tail-Risk Monitoring MVP

A research prototype that helps a quant PM answer:

> Is **my** momentum book becoming fragile, how does that compare with the
> published UMD / Daniel–Moskowitz market context, and what timestamped
> evidence supports or challenges the reading?

It is intentionally limited: about a 20-hour take-home. It is **not** a trading
system, investment recommendation, causal model, or production backtest.

## Portfolio vs comparison benchmark

| Layer | Role |
|---|---|
| **S&P 500 12-1 long-10 / short-10** | The PM-facing momentum portfolio. In this MVP it is an equal-weight, monthly 12-1 book on a current SPY membership snapshot — a transparent stand-in for a **customizable** PM momentum portfolio (names, weights, and universe can be replaced later without changing the monitoring framework). |
| **Ken French UMD + Daniel–Moskowitz state** | A **comparison benchmark**, not the PM book. It supplies literature-aligned market context and state-conditioned UMD outcome statistics so the customized book can be read against a published factor backdrop. |

These layers are never merged into one aggregate risk score.
`deterministic_score` remains null by design.

## Motivation

Momentum crashes are rare and state-dependent. A rebound after a severe
drawdown can hurt a recent-winner / short-loser book in ways a single volatility
summary misses. This MVP keeps those measurements separate and auditable:

1. UMD / Daniel–Moskowitz comparison context;
2. the customizable S&P 500 proxy momentum portfolio (default: long 10 / short 10);
3. realized long/short risk decomposition for that book;
4. a four-row deterministic scorecard on the book;
5. a six-row unwind monitor with three independent crash-mechanism scenarios;
6. exact-date evidence replay plus optional constrained interpretation.

## System overview

```text
MVPConfig
  → run_mvp()
       → UMD / DM comparison context (benchmark)
       → PM momentum portfolio scorecard (S&P 10/10 default)
       → unwind monitor + mechanism scenarios
       → exact-date evidence replay
       → optional constrained interpretation
  → presentation (charts + PM Evidence Card)
```

## Repository structure

```text
README.md
docs/
  methodology.md          # research methods and assumptions
  limitations.md          # what the MVP does not claim
  demo_walkthrough.md     # 15–20 minute reviewer path
notebooks/
  final_mvp_demo.ipynb    # single presentation notebook
src/
  mvp/                    # config, orchestration, card, presentation
  monitoring/             # scorecard, unwind, contracts
  regime/ risk/ portfolio/ features/
  evidence/               # corpus + exact-date research preview
  data/ utils/            # loaders and shared I/O
tests/                    # MVP smoke / integration / contract tests
data/processed/           # committed reproducibility inputs
outputs/
  example_risk_output/    # sample PM card export
  figures/                # demo chart export
  debug/                  # evidence fixtures (+ risk/positioning for regen)
  fundamental_alignment/  # SEC Phase 5A feasibility audits
```

Superseded phase docs and research modules remain available via Git history
(tag `pre-mvp-consolidation`).

## How to run

Python 3.11–3.14 and [`uv`](https://docs.astral.sh/uv/) are required.

```bash
uv sync --locked --all-groups
uv run python -m src.mvp.demo_smoke_test
uv run python -m pytest -q
```

Open the presentation notebook:

```bash
uv run --with jupyterlab jupyter lab notebooks/final_mvp_demo.ipynb
```

Edit only the parameter cell, then Run All:

```python
CONFIG = MVPConfig(
    as_of_date="2024-01-05",
    compare_to_date="2023-12-01",
    threshold_profile="default",
    horizon_days=20,
    use_llm=False,
)
```

`use_llm=False` is the reliable offline path and still renders the full card.

Validated contrast dates:

| Date | Why it matters |
|---|---|
| `2020-03-24` | `bear_market_recovery_crash` triggers |
| `2024-01-05` | default demo; recovery on watch, no confirmed theme unwind |
| `2026-05-29` | `crowded_theme_unwind` for a pre-event correlated cluster |

## Point-in-time controls

- Market and risk windows end on or before the as-of date.
- Portfolio formation, effective month, and observation dates are separate fields.
- Theme-cluster membership stops at `t-1`.
- Evidence publications must satisfy the local cutoff; missing values stay unavailable.
- Threshold profile `"default"` configures the Phase 4 scorecard only.

## Documentation

1. [Methodology](docs/methodology.md)
2. [Limitations](docs/limitations.md)
3. [Demo walkthrough](docs/demo_walkthrough.md)

## Limitations (summary)

- The default PM book uses current SPY membership historically → survivorship bias.
- UMD comparison context and the PM portfolio scorecard are not interchangeable.
- Evidence is exact-date cached replay, not live institutional retrieval.
- Mechanism scenarios are descriptive rules without predictive validation.
- No leverage, financing, forced-selling, or order-flow observation.

See [docs/limitations.md](docs/limitations.md) for the full list.

## Future work

- Point-in-time membership and industry history.
- Plug-in interface for a PM’s own customized momentum holdings.
- Observed holdings / leverage / flow data.
- Out-of-sample validation of the three mechanism rules.
- Full AI research and retrieval layer (beyond the offline preview).
