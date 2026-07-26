# Momentum Tail-Risk Monitoring MVP

This repository produces one auditable daily assessment of US equity momentum
tail risk. The primary risk number is a point-in-time historical conditional
frequency anchored to the panic-state mechanism in Daniel and Moskowitz
(2016). A frozen B2 logistic model is retained only as a shadow benchmark, and
the earlier reversal checklist is retained only as a research explanation.
Neither can replace or average into the primary result.

The MVP is a research prototype, not a trading system or investment
recommendation.

## Active system

```text
Ken French market and momentum data
        |
        v
DM-inspired PIT state + matured-label conditional frequency  [PRIMARY]
        |
        +--> frozen B2 OOS probability                        [SHADOW]
        +--> reversal conditions                              [EXPERIMENT]
        +--> FINRA loser-leg crowding                         [OVERLAY]
        +--> GDELT panic/crowding/risk-off attention          [OVERLAY]
        |
        v  only when primary state is elevated
validated illustrative evidence fixture                      [AI / HUMAN REVIEW]
        |
        v
one JSON assessment + one Markdown PM brief
```

The paper defines a negative cumulative market return over the prior 24 months
and interacts that bear indicator with variance from the prior 126 daily market
returns. Its panic variable is continuous, not a published binary alert. The
MVP operationalizes `panic_elevated` as a bear state whose 126-day variance is
at least the expanding point-in-time mean variance observed in bear states.
That boundary is explicitly an implementation convention, not a threshold
claimed by the paper.

## Run the MVP

Python 3.11–3.14 and [`uv`](https://docs.astral.sh/uv/) are required:

```bash
uv sync --locked --extra test
uv run python -m src.pipeline --as-of-date 2020-03-24 --horizon 20
uv run python -m pytest
```

Outputs are written under `outputs/mvp/`:

- `assessment_<date>_h<horizon>.json`: the complete machine-readable result;
- `risk_state_<date>_h<horizon>.json`: the primary DM/PIT assessment only;
- `insurance_table_<date>.csv`: unconditional versus state-conditional
  frequencies for 5- and 20-day horizons;
- `pm_brief_<date>_h<horizon>.md`: the PM-facing daily artifact.

Committed demonstrations cover:

- `2009-03-06`: elevated state with illustrative grounded evidence, but no
  post-2017 alternative-data overlays;
- `2020-03-24`: elevated state with FINRA and GDELT overlays;
- `2024-01-05`: quiet/non-elevated control with evidence correctly skipped.

## What each component is allowed to do

| Component | Role | May change primary probability? |
|---|---|---:|
| DM/PIT engine | Official state and conditional tail-loss frequency | Yes — it defines it |
| B2 logistic | Frozen research-only shadow comparison | No |
| Reversal checklist | Experimental preconditions and triggers | No |
| FINRA positioning | Confirm, contradict, or remain neutral | No |
| GDELT narrative | Confirm, contradict, or remain neutral | No |
| Evidence fixture | Supply timestamped, passage-grounded context | No |

The active entry point is `src/pipeline.py`. The small active contracts live in
`src/mvp/contracts.py`. Earlier modeling and monitoring modules remain in place
for historical replay and are documented in `docs/history/README_legacy.md`;
they are not called by the active pipeline.

## Data and point-in-time controls

- Market state uses only feature rows through the assessment date.
- Conditional frequencies use only labels whose full forward windows have
  matured by that date.
- FINRA short interest enters on publication date, not settlement date.
- SEC shares outstanding enter on filing date.
- GDELT calendar buckets map into the next complete trading-date information
  set and use prior-only rolling normalization.
- Evidence publications must not postdate the assessment timestamp.
- Relevant evidence must carry a valid URL and grounded source passage.

The FINRA panel is based on a current large-cap universe applied historically
and is survivorship-biased. FINRA daily short volume is off-exchange flow, not
a consolidated position measure. The GDELT panel currently contains three
volume-only mechanisms (`panic`, `crowding`, and `riskoff`); tone and
five-mechanism breadth are unavailable.

## Evidence scope

The current evidence output is deliberately labeled
`illustrative_fixture_replay`. Its per-document timestamps and passages are
validated, but the small corpus was curated after the historical assessment
dates. It demonstrates grounding and control flow, not a strict historical
text backtest. A production implementation requires an archived point-in-time
corpus or live retrieval track.

## Tests and reproducibility

The default suite covers:

- label maturity and future-data invariance;
- DM/PIT state construction and the insurance-table separation;
- publication-date positioning joins;
- prior-only normalization and GDELT information mapping;
- primary/shadow/experimental isolation;
- overlay immutability of the primary probability;
- elevated-state evidence gating and citation cutoffs;
- quiet and elevated end-to-end artifacts.

Processed panels are committed and immediately readable. Large raw FINRA,
price, and GDELT payload caches are not fully committed. Rebuild-only tests
skip when their required raw payloads are absent; this is different from
claiming that every processed artifact can be regenerated from a fresh clone
without network access.

## Current versus historical modules

Current:

- `src/risk/dm_engine.py`
- `src/benchmarks/b2_shadow.py`
- `src/experiments/reversal_checklist.py`
- `src/overlays/snapshots.py`
- `src/evidence/mvp.py`
- `src/reporting/pm_brief.py`
- `src/pipeline.py`

Historical but retained:

- `src/modeling/`
- `src/monitoring/risk_state.py`
- `src/monitoring/domain_risk.py`
- `src/monitoring/positioning.py`
- `src/monitoring/market_context.py`
- `src/modeling/phase2.py` and the older aggregate-news model ablation

See `docs/DECISIONS.md` for data judgments and
`docs/history/README_legacy.md` for the original Phase 1/2 reproduction
instructions.
