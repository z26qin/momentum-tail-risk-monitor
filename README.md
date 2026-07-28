# Momentum Tail-Risk Monitoring MVP

This repository is a transparent research prototype for monitoring conditions
associated with US equity momentum crashes. Its source of truth is a
deterministic, top-down workflow:

1. macro and market regime;
2. synthetic S&P 500 12-1 momentum portfolio;
3. realized long/short risk decomposition;
4. four-row deterministic scorecard;
5. SEC fundamental-data feasibility, currently frozen at Phase 5A.

The project is not a trading system, investment recommendation, causal model,
or production point-in-time backtest.

## Run the final MVP demo

Python 3.11–3.14 and [`uv`](https://docs.astral.sh/uv/) are required.

```bash
uv sync --locked --extra test
uv run python -m src.mvp.run_demo --as-of-date 2026-05-29
```

This is the only primary demo command. It runs offline, reads the existing
Phase 1–4 processed artifacts and compact Phase 5A aggregate audit, and writes
only:

- `outputs/demo/demo_summary_2026-05-29.json`
- `outputs/demo/demo_scorecard_2026-05-29.csv`
- `outputs/demo/demo_portfolio_2026-05-29.csv`
- `outputs/demo/demo_report_2026-05-29.md`

The observation date is intentionally `2026-05-29`, the latest complete date
shared by the macro and realized-risk inputs. On that date:

- the risk-bearing portfolio was formed on `2026-04-30`;
- the next portfolio was formed at the `2026-05-29` close;
- later June data are shown only as module freshness metadata.

The two portfolios are separately labeled. A newly formed portfolio is never
used to explain risk realized by the previously active portfolio.

## Current demo contents

| Section | Status | Authority |
|---|---|---|
| Phase 1 macro regime | Complete | Deterministic |
| Phase 2 named 10-long/10-short portfolio | Complete | Deterministic |
| Phase 3 contribution, beta, conditional beta, drawdown | Complete | Deterministic |
| Phase 4 four-row scorecard | Complete and unchanged | Deterministic source of truth |
| Phase 5A SEC coverage audit | Complete; 64.79% coverage, degraded | Feasibility only |
| January–February 2023 case | Reproducible historical proxy | Descriptive, not causal |
| Evidence preview | Bounded offline capability preview | Cannot change deterministic facts |

Phase 5A has no fundamental ranks, Spearman alignment, long-short fundamental
spread, or alignment flags. Those fields are explicitly `null`, with
`alignment_status="future_work"`. Coverage never becomes a safe or low-risk
fundamental conclusion.

The 2023 case uses `2023-01-09` as a relative elevated-risk/high-volatility
recovery precursor and `2023-02-02` as the realized stress observation. It is
not labeled a formal `panic_elevated` alert, a proven crash forecast, or proof
of a causal Fed-repricing mechanism.

## Evidence boundary

`src/evidence/research_preview.py` is labeled:

> Phase 8 capability preview — not the completed Phase 8 implementation.

It can only replay the versioned local corpus and an exact-date, already
validated cached classification. It makes no network or model call, creates no
threshold or risk probability, and cannot write back to deterministic facts.
When reliable date-matched evidence is absent, it returns `unavailable` and
empty supporting, contradicting, and contextual lists.

## Data and point-in-time controls

- Market and risk windows end on or before the observation date.
- Portfolio signal endpoints, formation dates, effective months, and
  observation dates are separate fields.
- Long weights sum to `+1`; short weights sum to `-1`.
- Short-underlying returns and signed short contributions use explicit,
  opposite signs.
- SEC feasibility uses filing availability rather than fiscal-period end and
  applies a staleness gate.
- Missing values remain unavailable and never silently pass a threshold.
- Evidence publications and cached classifications must satisfy the local
  cutoff and provenance checks.

The portfolio uses a current SPY membership snapshot as a historical proxy and
is survivorship-biased. Public-vendor price histories can contain ticker or
corporate-action discontinuities; extreme momentum observations should be
investigated before economic interpretation.

## Tests

```bash
uv run python -m pytest -q
git diff --check
```

The final integration adds exactly four focused demo tests and two focused
evidence-preview tests. They protect date alignment, unavailable Phase 5
alignment, deterministic replay, upstream artifact immutability, evidence
immutability, and fail-closed missing evidence.

## Deferred roadmap

The following work remains explicitly deferred, not cancelled or completed:

- Phase 5B — production-grade historical SEC fundamentals and universe-level
  fundamental alignment;
- Phase 7 — Crowding Monitoring;
- Phase 8 — Full AI Research and Retrieval Layer.

Breadth, concentration, crowding, live news, vector databases, new predictive
models, dashboards, deployment, and production infrastructure are not part of
this final integration.

## Documentation

- [Methodology](docs/methodology.md)
- [Demo walkthrough](docs/demo_walkthrough.md)
- [Final handoff](docs/handoff.md)
- [Confirmed design](docs/confirmed_design.md)
- [Development plan](docs/development_plan.md)
- [Phase 5A handoff](docs/handoff_phase5.md)

The earlier Daniel–Moskowitz conditional-frequency pipeline remains available
through `python -m src.pipeline` as a retained research path. It is not the
primary final-MVP entry point and does not replace the deterministic Phase 1–4
scorecard.
