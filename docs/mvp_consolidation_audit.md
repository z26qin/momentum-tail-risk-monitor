# MVP consolidation audit

Date: 2026-07-30  
Branch: `refactor/mvp-consolidation`  
Audit checkpoint: `9ec60ed` (`Add independent momentum crash scenarios`)

> **Framing update (post-audit, documentation only):** the S&P 500 12-1
> long-10 / short-10 book is the default **customizable PM momentum
> portfolio** (primary monitored object). Ken French UMD / Daniel–Moskowitz
> state is a **comparison benchmark**, not a second peer proxy. Calculations
> described below are unchanged; only product language was clarified in the
> active README / methodology / notebook labels.

## Scope and conclusion

This is the Phase 0 audit only. No production logic, research calculation,
notebook, artifact, or configuration was changed.

The repository contains a credible deterministic momentum-monitoring MVP, but
the final presentation is assembled from several boundaries rather than one
authoritative run object:

1. the Evidence Card header state and conditional tail-loss frequency come
   from the Ken French UMD / Daniel–Moskowitz **comparison** path;
2. the four visible quantitative signals come from the PM momentum portfolio
   scorecard (default customization: S&P 500 long 10 / short 10);
3. the six-row unwind monitor and three mechanism scenarios are built by a
   separate call;
4. evidence is an exact-date replay of a small cached classification, not live
   retrieval;
5. the notebook directly reads additional Parquet files for portfolio and chart
   presentation;
6. the displayed run ID and data hash cover the Phase 1–4 Evidence Card input,
   but not the separately built unwind assessment, active holdings display, or
   evidence bytes.

The smallest safe consolidation is therefore not a package-wide rewrite. It is
to establish one immutable run configuration and one orchestration result that
compose the existing authoritative calculations without changing them. High
risk semantic boundaries—especially UMD versus the named S&P 500 proxy,
aggregate state versus scorecard signals, and “historical analogs” versus
state-conditional statistics—must remain explicit.

### Verified baseline

- Git worktree was clean before this audit.
- Tracked files: 826, including 80 source files, 40 test files, 25 files under
  `docs/`, 574 files under `data/`, and 95 files under `outputs/`.
- Repository size on disk is approximately 2.5 GB; approximately 2.0 GB is
  under `data/`. The tracked tree is approximately 122 MB because large local
  caches are ignored.
- `uv run python -m pytest -q`: 296 tests collected; 292 passed and 4 existing
  rebuild/cache-dependent tests skipped.
- In-memory clean-kernel execution:
  - `01_baseline_eda.ipynb`: pass, 6 code cells, 0 errors;
  - `02_pm_prototype_validation.ipynb`: pass, 7 code cells, 0 errors;
  - `03_pm_evidence_card_demo.ipynb`: pass, 12 code cells, 0 errors.
- `uv run python -m src.mvp.demo_smoke_test`: `status="ready"`, run ID
  `53c34aa57bb437fc`, seven evidence items, six unwind rows, and three mechanism
  scenarios.

Before an approved implementation phase removes files, create recoverable Git
references at the audited checkpoint. These commands are recommended but were
not executed:

```bash
git tag pre-mvp-consolidation 9ec60ed
git branch archive/pre-mvp-consolidation 9ec60ed
```

## A. Current repository map

```text
.
├── README.md                         current overview; partly current
├── pyproject.toml / uv.lock          environment and test configuration
├── config/
│   └── phase2_queries.yaml           legacy B3/GDELT experiment config
├── src/
│   ├── data/                         raw-source acquisition and parsing
│   ├── features/                     UMD labels/features and alternative panels
│   ├── portfolio/momentum.py         named S&P 500 proxy 12-1 portfolio
│   ├── regime/market_state.py        current macro/recovery state
│   ├── risk/                         DM state, leg risk, concentration, theme
│   ├── monitoring/                   scorecard, unwind, and legacy B2 adapters
│   ├── evidence/                     three partially overlapping evidence paths
│   ├── mvp/                          current adapter plus two older demo layers
│   ├── modeling/                     retained B0/B1/B2/B3 research
│   ├── evaluation/                   retrieval-gold workflow
│   └── pipeline.py                   retained pre-scorecard MVP entry point
├── notebooks/
│   ├── 01_baseline_eda.ipynb         exploratory UMD/model notebook
│   ├── 02_pm_prototype_validation…   legacy B2/domain-state review notebook
│   └── 03_pm_evidence_card_demo…     current PM-facing notebook
├── tests/                             broad PIT and contract suite
├── data/
│   ├── raw/                           source archives plus ignored local caches
│   ├── processed/                     committed reproducibility inputs
│   ├── corpus/                        small evidence fixture corpus
│   ├── fixtures/                      classifier response fixtures
│   └── evaluation/                    evidence evaluation workflow/artifacts
├── outputs/                           mixed current samples and historical builds
├── artifacts/                         retrieval workflow status
└── docs/                              current docs mixed with development history
```

### Material components

| Component | Purpose | Current MVP use | References | Classification |
|---|---|---|---|---|
| `src/portfolio/momentum.py` | Named, equal-weight, monthly 12-1 long 10 / short 10 S&P 500 proxy | Yes | Phase 5 breadth/fundamentals; tests; processed holdings/returns | Authoritative |
| `src/regime/market_state.py` | Drawdown, recovery, volatility, DM and rate context | Yes | Scorecard, unwind, Evidence Card notebook | Authoritative |
| `src/risk/leg_decomposition.py` | Long/short returns, signed contribution, beta, conditional beta, volatility and drawdown | Yes through `leg_risk_history.parquet` | Scorecard and notebook | Authoritative build module |
| `src/monitoring/scorecard.py` | Four-row deterministic scorecard | Yes | Evidence Card adapter and old `run_demo` | Authoritative |
| `src/monitoring/unwind_structure.py` | Six-row unwind monitor and scenario v2 | Yes | Notebook and smoke test | Authoritative but separately orchestrated |
| `src/risk/theme_concentration.py` | Prior-only correlated-theme proxy | Yes | Unwind monitor | Authoritative |
| `src/mvp/evidence_card.py` | Evidence Card schema, old card assembly, deterministic adapter and HTML helpers | Yes | Notebook, interpretation, tests | Current façade with duplicated layers |
| `src/mvp/evidence_interpretation.py` | Current constrained optional interpretation | Yes | Notebook and smoke test | Authoritative interpretation layer |
| `src/evidence/research_preview.py` | Exact-date cached evidence replay | Yes | Evidence Card adapter and old `run_demo` | Authoritative current runtime evidence boundary |
| `src/risk/dm_engine.py` | DM operational state and matured-label conditional frequency | Yes | Evidence Card header and “historical analog” payload | Authoritative for this narrower role |
| `src/mvp/run_demo.py` | Earlier read-only Phase 1–5A report generator | No longer the displayed notebook path | README CLI, tests, generated demo outputs | Superseded/stale |
| `src/pipeline.py` | Earlier DM + B2 + overlay + evidence assessment | No | CLI, legacy tests and docs | Retained research path |
| `src/modeling/` | Purged B0/B1/B2 and B3 text experiments | No runtime use | Old notebooks, tests, outputs | Historical research |
| `src/monitoring/risk_state.py`, `market_context.py`, `domain_risk.py` | Saved B2 probability and heuristic domain prototype | No final notebook use | Evidence-cache tooling, notebook 02, tests | Legacy/tooling boundary |
| `src/evidence/query_builder.py`, `retriever.py`, `classifier.py` | Generate cached classified evidence from the local curated corpus | Indirect: their output is replayed | Debug fixtures and tests | Production-supporting tooling |
| `src/evidence/archived_provider.py` and related contracts | Strict archive design with multi-timestamp gates | Not in final card runtime; archive corpus absent | Old pipeline and evaluation tests | Incomplete future path |
| `data/processed/` | Reproducibility inputs | Yes, selectively | Most current calculations | Mixed authoritative and stale |
| `outputs/debug/classified_evidence_*.json` | Exact-date validated classifications | Yes | `research_preview.py` | Required current fixture artifacts |
| Other `outputs/` | Model, phase, demo and review artifacts | Mostly no | Old docs/tests or no current reader | Generated/mixed |

### Important processed datasets

| Dataset family | Date coverage | Current role |
|---|---|---|
| French UMD/factors/portfolios | 1926–2026-05-29 | UMD labels, DM state, macro regime and rebuild support |
| `market_features.parquet` | 1926-11-03–2026-05-29 | Evidence Card DM state and label conditioning |
| UMD labels h5/h20 | 1926-11-03–2026-05-29 | Matured conditional tail-loss frequency |
| S&P 500 proxy universe/prices | current 503-name snapshot; prices 2016–2026-07-27 | Named portfolio and theme/unwind calculations |
| Named portfolio holdings/returns | formations 2017–2026-06-30 | Phase 2 and downstream risk |
| `leg_risk_history.parquet` | 2017-02-01–2026-06-30 | Four-row scorecard and notebook charts |
| `unwind_structure_history.parquet` | 2017-02-01–2026-06-30 | Generated copy; current assessment rebuilds it in memory |
| GDELT, narrative and positioning panels | 2017–2026 | Legacy B3/overlay research; not final notebook inputs |
| FINRA and SEC panels | mixed 2017–2026 | Legacy positioning and optional fundamental build support |

The processed sources have different latest dates. The Evidence Card adapter
rejects dates after `market_features.parquet` (2026-05-29), even though the
named portfolio, risk, benchmark and S&P 500 prices extend later. This is safe
but not represented by one declared data-availability contract.

## B. Current MVP execution path

### Intended entry point

The strongest and actual presentation entry point is:

```text
notebooks/03_pm_evidence_card_demo.ipynb
```

The reliable pre-demo gate is:

```bash
uv run python -m src.mvp.demo_smoke_test
```

`src.mvp.run_demo` is still documented as a CLI entry but does not include the
Phase 5B–5E unwind monitor or scenario v2 and contains stale limitations saying
those phases are deferred. `src.pipeline` is an earlier research path.

### Actual runtime flow

```text
Notebook parameter cell
  AS_OF_DATE / COMPARE_TO_DATE / THRESHOLD_PROFILE / USE_LLM
          |
          +--> build_deterministic_evidence_input(...)
          |      |
          |      +--> build_evidence_card(..., use_llm=False)
          |             |
          |             +--> build_primary_assessment(...)
          |             |      +--> market_features + matured UMD labels
          |             |
          |             +--> build_regime_history(French market factors)
          |             +--> build_scorecard(named-portfolio risk, regime)
          |             +--> build_research_preview(exact-date cache)
          |             +--> build_insurance_table(state-conditional outcomes)
          |
          +--> interpret_evidence_card(adapter result)
          |      +--> injected structured provider or deterministic fallback
          |
          +--> build_unwind_assessment(AS_OF_DATE)
          |      +--> rebuild constituent returns, concentration, breadth,
          |           fingerprint and correlated-theme snapshot in memory
          |
          +--> direct Parquet reads for active holdings, macro components,
                 trailing charts and comparison presentation
          |
          `--> notebook-defined HTML final card
```

### Exact reusable entry points

| Layer | Authoritative entry point | Contract/output |
|---|---|---|
| UMD data | `src.data.french.run_french_pipeline` | Processed French factor/portfolio Parquets |
| UMD legs | `src.features.legs.reconstruct_momentum_legs` | Aggregate winner/loser legs and UMD reconciliation |
| UMD labels | `src.features.labels.build_labels_for_horizon` | PIT matured 5/20-day tail-loss labels |
| UMD/market features | `src.features.market_features.build_market_features` | Model/DM feature history |
| Named momentum signals | `src.portfolio.momentum.build_momentum_signals` | Calendar-month 12-1 signals |
| Named holdings | `src.portfolio.momentum.build_momentum_holdings` | Long 10 / short 10 next-month holdings |
| Named portfolio returns | `src.portfolio.momentum.build_portfolio_returns` | Drifted-weight leg and portfolio returns |
| Macro regime | `src.regime.market_state.build_regime_history` | Daily macro/recovery history |
| Named leg risk | `src.risk.leg_decomposition.build_leg_risk_history` | Beta, conditional beta, vol, contribution and drawdown history |
| Four-row scorecard | `src.monitoring.scorecard.build_scorecard` | Four ordered threshold decisions |
| UMD DM assessment | `src.risk.dm_engine.build_primary_assessment` | Header state and conditional tail-loss frequency |
| Phase 5 unwind | `src.monitoring.unwind_structure.build_unwind_assessment` | Six rows plus three independent mechanism states |
| Theme proxy | `src.risk.theme_concentration.build_theme_concentration_snapshot` | `t-1` correlated cluster and event evidence |
| Current evidence | `src.evidence.research_preview.build_research_preview` | Exact-date fail-closed cached replay |
| Deterministic adapter | `src.mvp.evidence_card.build_deterministic_evidence_input` | Validated `DeterministicEvidenceInput` |
| Interpretation | `src.mvp.evidence_interpretation.interpret_evidence_card` | Validated narrative-only `EvidenceInterpretation` |

### Artifact build flow

There is no single current command that rebuilds the final MVP from raw inputs.
The current notebook assumes committed processed Parquets and caches.

```text
French raw archives
  -> src.data.french
  -> src.features.legs / labels / market_features

SPY holdings + public price caches
  -> src.data.sp500
  -> src.portfolio.momentum
  -> src.risk.leg_decomposition
  -> src.monitoring.scorecard
  -> src.monitoring.unwind_structure (rebuilds Phase 5 histories in memory)

Curated evidence corpus + saved B2/positioning states
  -> query_builder -> retriever -> classifier
  -> outputs/debug/classified_evidence_<date>.json
  -> research_preview exact-date replay
```

The evidence-cache generation flow is not called by the notebook. The strict
archive provider is a separate path and cannot run successfully because
`archived_momentum_evidence_v1.json` is intentionally absent.

## C. Duplicate logic inventory

| Concept | Implementations | Actual behavioral differences | Call sites | Proposed canonical version | Risk |
|---|---|---|---|---|---|
| Momentum return | Published Ken French `umd_return`; `reconstructed_umd_return` in `features/legs.py`; named S&P proxy `portfolio_return` in `portfolio/momentum.py` | UMD is a published broad-universe, size-balanced factor. The named portfolio is current-SPY-membership, equal-weight long 10 / short 10, monthly held and survivorship-biased. They are not interchangeable. | DM labels/header use UMD; scorecard/unwind use named portfolio | Keep both, but name the universe/factor in every contract | High |
| Winner/loser legs | French six-portfolio legs in `features/legs.py`; named security baskets in `portfolio/momentum.py` | French legs average small/big high/low portfolios. Named legs select ten securities each and distinguish short-underlying return from signed short contribution. | Legacy features versus current Phase 2–5 | Keep both with explicit prefixes/contracts | High |
| Tail-loss labels | `features.labels.build_labels_for_horizon`; no named-portfolio label implementation | Labels are forward UMD returns with matured prior quantiles. The final named portfolio scorecard has no forward crash label. | `dm_engine`, modeling | Keep the single implementation; do not imply it labels the named portfolio | High |
| 504-day bear/126-day variance state | `features.market_features.build_market_features`; `regime.market_state.build_regime_history`; `dm_engine.build_state_history` | The calculations match exactly after sufficient shared history. Regime starts on the longer research-factor calendar, producing 101 additional early rows through 1928-07-11. On 2009, 2020, 2024 and 2026 sample dates the DM states and intensities match to floating tolerance. | Header, regime, legacy B2 | `regime.market_state` for current macro history; retain `dm_engine.build_state_history` as the state rule | Medium |
| Volatility/panic state | `market_features.mkt_vol_percentile_126d`; regime 21-day annualized volatility versus prior-only 80th percentile; DM bear-variance intensity | These measure different windows and reference sets. The regime high-vol gate is not the legacy B2 percentile or DM state. | Scorecard, domain prototype, header | Keep distinct and label exact metric | High |
| Reversal checklist | `experiments/reversal_checklist.py`; `monitoring/domain_risk.py` | Six core thresholds and state precedence are duplicated exactly; domain risk adds previous-state logic, detailed components, positioning proxy and mechanisms. Neither is current scenario v2. | Old pipeline and notebook 02 | Remove both from final runtime; preserve in Git history | Medium |
| Risk scoring/state | DM `PrimaryRiskAssessment`; saved B2 `RiskState`; four-row scorecard; six-row unwind and scenario v2 | DM produces a categorical state and conditional UMD tail frequency. B2 produces a fitted probability. Scorecard and unwind intentionally produce no aggregate probability. | Multiple old/current entry points | Preserve scorecard + scenario decisions; retain DM only as explicitly labeled context | High |
| Threshold classification | `ScorecardConfig`; `UnwindMonitorConfig`; `ThemeConcentrationConfig`; regime constants; legacy domain constants | Different metrics, history requirements, fallbacks and structural gates. `THRESHOLD_PROFILE="default"` currently selects only `ScorecardConfig`; it does not configure Phase 5. | Notebook and current modules | One run config containing unchanged nested configs; no threshold merging | High |
| Drawdown | `features.market_features.rolling_drawdown` (UMD 252-day); regime since-inception and 126-day recent market drawdown; scorecard recomputed named-portfolio 63-day drawdown; leg risk since-inception portfolio drawdown | Different asset, horizon and peak definition. | Header/context, scorecard, scenario | Keep all with asset and window in names | High |
| Narrative aggregation | `features/gdelt.py`; `features/narrative_panel.py`; `overlays/snapshots.py`; cached evidence corpus | GDELT modules aggregate daily attention/tone with different interval rules; evidence cache contains document records. None feeds final interpretation except the cache. | Legacy B3/overlay versus current preview | Current cache only for MVP; move GDELT/B3 out of visible MVP | Medium |
| Evidence retrieval/ranking | `evidence/retriever.py`; `ArchivedEvidenceProvider`; `research_preview.py` | Curated retriever ranks by request-term scores; archive provider has stricter multi-timestamp/content-version gates; preview performs no retrieval or ranking and replays validated items in cache order. | Tooling, old pipeline, final card | `research_preview` for demo; retain one clearly isolated evaluation/generation path only if approved | High |
| Evidence classification | `classifier.py` + `classification_validation.py`; `versioned_classifier.py`; `research_preview` validation | The first validates the current curated corpus schema; the versioned classifier binds to the strict archive provider; preview performs a smaller provenance/cutoff replay validation. | Two evidence stacks plus final replay | Current curated contract for demo; strict archive stack marked future/evaluation | High |
| Historical analogs | `_historical_analogs` in `mvp/evidence_card.py`; `dm_engine.build_insurance_table`; 2023 hardcoded case in `run_demo.py` | `_historical_analogs` merely serializes aggregate state-conditional outcomes. It returns no analog dates, features, distances or nearest-neighbor ranking. `run_demo` hardcodes a descriptive 2023 case. | Evidence Card and old CLI | Rename to state-conditioned historical outcomes; true analog retrieval is absent | High |
| Interpretation | `mvp/llm_synthesis.py`; `mvp/evidence_interpretation.py` | The former is a five-field narrative embedded in old `EvidenceCard`; the latter is the current eight-field evidence-ID-constrained schema and validates provider claims. | Adapter wrapper versus notebook | `evidence_interpretation.py` | Medium |
| Presentation/scoreboard | `mvp/run_demo.py`; HTML helpers in `mvp/evidence_card.py`; notebook-defined HTML | `run_demo` stops at Phase 5A and writes artifacts; Evidence Card HTML omits scenario v2; notebook includes scenario v2 and direct data panels. | CLI, tests, notebook | One presentation module used by the one notebook | Medium |
| Plotting | Notebooks 01, 02 and 03 each define Matplotlib styling and plots inline | The plots answer different historical questions. Notebook 03’s trailing scorecard plot is current; notebooks 01/02 visualize superseded model/domain research. There is no shared plot API. | Notebook-only | Keep only notebook 03’s small current visuals, moved to presentation helpers only where useful | Low |
| Date filtering | Parquet filters in `dm_engine`; frame clipping in feature pipelines; exact-row selectors in scorecard/unwind; evidence 4 p.m. cutoff | Rules are individually safe but use different calendars/latest dates and are not expressed by one run contract. | Throughout | Shared run config plus unchanged module-local PIT rules | High |
| Train/test validation | `modeling.validation.PurgedExpandingWalkForward`; `make_purged_holdout`; Phase 2’s `PurgedSplit` use | These are complementary development walk-forward and final holdout utilities, not competing current-MVP scoring paths. They protect historical B2/B3 studies only. | Historical modeling/tests | Preserve in Git history if the modeling package leaves the MVP branch | Medium |
| Configuration loading | `config/phase2_queries.yaml`; dataclass defaults; module constants; notebook globals | YAML config controls only the legacy text ablation. Current demo uses Python globals and default dataclasses. | Separate paths | Small frozen `MVPConfig`; no forced YAML migration | Medium |

### Semantic disagreement requiring approval

The final notebook labels `card.overall_risk_state` as the deterministic risk
state, but that field is the DM state from `build_primary_assessment`, while the
signals immediately below it are the named-portfolio Phase 4 scorecard. This is
not a calculation bug, but it is not one aggregate score either.

Likewise, `historical_analogs` is not an analog-retrieval result. Selecting a
new analog algorithm would change research meaning and is outside safe
consolidation. The recommended change is naming/documentation only.

## D. Global state and configuration audit

### Run-level controls

| Control | Defined/read today | Multiple definitions | Propagation | Recommendation |
|---|---|---|---|---|
| `AS_OF_DATE` | Notebook 03; fixed smoke/demo dates; many CLI arguments | Yes | Adapter, interpretation and unwind receive it; direct notebook reads use it. Old demo has separate fixed dates. | One `MVPConfig.as_of_date` |
| comparison date | Notebook and Evidence Card only | No equivalent in unwind | Changes Phase 4 deltas only | Keep optional and state its scope |
| `THRESHOLD_PROFILE` | Notebook; `THRESHOLD_PROFILES` in `evidence_card.py` | Only one approved profile | Changes Phase 4 `ScorecardConfig` only, not unwind/theme/regime | Either label `phase4_threshold_profile`, or bind unchanged nested configs in one run config |
| risk threshold | No aggregate risk threshold exists | Many metric thresholds exist | Not applicable | Do not invent an aggregate threshold |
| crash threshold | UMD 5% PIT label quantile; regime -20% drawdown; scorecard/unwind metric gates | Yes, intentionally different | Module-local | Keep distinct names and provenance |
| horizon | Adapter/DM default 20; labels support 5 and 20 | Notebook does not expose it | Changes DM frequency/header, not scorecard or unwind | Include only if reviewer needs it; otherwise freeze and record 20 |
| lookbacks | Portfolio 12/1 months; regime 21/63/126/504; scorecard 21/63; unwind 5/21/63; evidence 120 days | Many, intentional | Module-local | Keep inside frozen component configs |
| top-k | Archived/current retrievers default 8; no active preview top-k; no analog top-k | Multiple inactive paths | Notebook cannot control it | Do not add until a real retriever exists |
| random seed | B2 `0`; B3 `20260724`; retrieval-gold `20200324` | Yes, separate experiments | No current deterministic calculation uses randomness | Leave in historical/evaluation modules only |
| data paths | `src.utils.io.DEFAULT_*`; notebook `ROOT`; optional function args | Mostly centralized | Current calls usually rely on defaults | Put `processed_dir`, evidence cache/corpus and output path in config |
| output path | `DEFAULT_OUTPUT_DIR`, module-specific subdirs | Yes | Notebook is read-only; CLIs write different families | One optional run output root |

### Module-level mutable state

| Location | State | Risk |
|---|---|---|
| `src.utils.http.NETWORK_ENABLED` | Mutable global used by offline tests | A prior cell/test can change acquisition behavior |
| `src.features.gdelt._LAST_REQUEST_MONOTONIC` | Process-global request throttle | Legacy acquisition depends on process history |
| `src.data.finra._US_FEDERAL_HOLIDAYS` | Lazy mutable holiday cache | Low; deterministic after initialization |
| Notebook `INJECTED_INTERPRETER = globals().get(...)` | Optional hidden kernel hook | Clean kernel is safe (`None`), but rerun behavior can depend on prior kernel state |
| Notebook dataframes/functions/style globals | Sequential cell state | `Run All` is safe; individual out-of-order execution is not |

### Environment-dependent values

- `SEC_CONTACT_EMAIL` is required only for SEC acquisition.
- `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are credential-presence checks for
  the optional interpreter; no vendor client is installed.
- Network acquisition defaults to enabled in `src.utils.http`; the demo itself
  is offline.
- Current raw SEC/GDELT/price/FINRA caches are partly ignored. A fresh clone can
  run the demo from committed processed artifacts but cannot reproduce every
  raw acquisition without new downloads.

### Hardcoded dates

- Notebook 03 parameter default: 2024-01-05, comparison 2023-12-01.
- Notebook 03 recomputation assertions also build 2026-05-29 and 2020-03-24
  every run.
- `mvp/run_demo.py`: 2026-05-29 and the 2023-01-09 / 2023-02-02 case.
- Smoke test: 2024-01-05 and 2020-03-24 pairs.
- Retrieval-gold workflow: March 2020 dates.
- GDELT acquisition/config dates: 2017 through 2026-06-30.

Fixed regression dates are appropriate in tests. Presentation/runtime dates
should flow from one config, while historical examples should be explicitly
test/demo fixtures rather than module defaults.

## E. Notebook audit

| Notebook | Purpose/type | Source duplication/hidden state | Clean-kernel result | Proposed action |
|---|---|---|---|---|
| `01_baseline_eda.ipynb` | Exploratory validation of UMD labels and B0/B1/B2 outputs | Directly loads processed/model artifacts and recreates charts/summaries; no source research formula beyond descriptive aggregation | Pass | Remove from MVP branch; preserve in Git history |
| `02_pm_prototype_validation.ipynb` | Presentation-facing review of legacy B2/domain prototype | Depends on saved debug states and legacy contracts; recreates scenario tables; not current scenario v2 | Pass | Remove from MVP branch |
| `03_pm_evidence_card_demo.ipynb` | Current PM/researcher demo | Uses current adapter and interpretation, but separately calls unwind; directly selects holdings, rebuilds macro display conditions and charts, and defines final HTML. Optional interpreter uses prior kernel global if present. | Pass | Retain and simplify after one orchestration/presentation boundary exists |

Notebook 03 is the clear single demo candidate. It has one visible parameter
cell and sequential execution counts 1–12. It can run from the repository root
or `notebooks/`. Its primary reliability risks are:

1. it receives no single object guaranteeing that header state, scorecard,
   unwind, holdings, evidence and presentation share one config/hash;
2. the run ID omits the separately displayed Phase 5 result;
3. threshold profile scope is visually broader than its actual Phase 4 scope;
4. LLM interpretation does not receive the Phase 5 mechanism scenarios;
5. the smoke test searches notebook source markers but does not itself execute
   the notebook;
6. hardcoded recomputation examples add runtime and are validation logic inside
   the presentation notebook.

## F. Documentation audit

| Document | Classification | Finding/action |
|---|---|---|
| `README.md` | Current user-facing, partly current | Notebook commands and scenario v2 are current; it still advertises the stale `run_demo` CLI and retained DM pipeline. Modify. |
| `docs/methodology.md` | Current methodology, stale after Phase 5A | Stops at Phase 5A and omits unwind/theme/scenario v2. Rewrite around authoritative current methods. |
| `docs/demo_walkthrough.md` | Current user-facing runbook | Current and useful; retain, shorten after notebook consolidation. |
| `docs/ARCHIVED_EVIDENCE.md` | Current limitation/method detail | Merge the relevant evidence boundary into methodology/limitations. |
| `BLOCKERS.md` | Current limitations for older evidence path | Merge current facts into `docs/limitations.md`; remove root file. |
| `NEXT_STEPS.md` | Development history/obsolete roadmap | Describes the old streamlined MVP as current. Remove from MVP branch after merging any live risks. |
| `docs/confirmed_design.md` | Obsolete plan/current conflict | Calls `run_demo` unique and says Phase 5B/crowding deferred. Remove. |
| `docs/development_plan.md` | Obsolete plan/current conflict | Same stale phase status. Remove. |
| `docs/phase_6_implementation_plan.md` | Development history | Completed session log, not reviewer documentation. Remove. |
| `phase_6_review.md` | Current implementation review, too historical | Source of useful facts; merge into methodology/limitations/report, then remove. |
| `docs/handoff.md` | Obsolete handoff | Old branch and Phase 5A-only path. Remove. |
| `docs/handoff_phase5.md` | Development history | Preserve in Git history, remove. |
| `docs/handoff_phase5_unwind.md` | Current technical handoff | Merge current commands/limitations into README/methodology, then remove. |
| `docs/phase_6a_review.md` | Development history | Superseded. Remove. |
| `docs/DECISIONS.md` | Long research/development journal | Useful history but overwhelms MVP reviewer path; preserve in Git history, remove from branch. |
| `docs/PROJECT_PLAN_v3.md` | Obsolete plan | Remove. |
| `docs/meeting_feedback.md` | Development history | Remove. |
| `docs/phase_reviews/*` | Development history | Remove the directory from MVP branch after current facts are consolidated. |
| `docs/history/README_legacy.md` | Explicit legacy documentation | Git already preserves it; remove visible history directory. |
| `docs/sp500_universe.md` | Generated data documentation/list | Large constituent listing; replace with a concise data-source/limitation section. |
| `docs/universe.md` | Legacy top-200 universe documentation | Not the final named portfolio universe. Remove. |
| `data/evaluation/2020_retrieval_gold/**/*.md` | Evaluation protocol/runbook | Current only if the retrieval-gold workflow is retained; otherwise preserve in Git history. |
| `outputs/*.md` and nested generated reports | Generated reports | Mixed old Phase 1/2/model and stale demo output; not authoritative documentation. Remove with their generating paths. |

The tracked `.html` files are FINRA publication-schedule source snapshots under
`data/raw/finra/schedule/`, not user documentation. They belong to the raw-data
artifact decision, not the documentation set.

The target documentation set should be:

```text
README.md
docs/methodology.md
docs/limitations.md
docs/demo_walkthrough.md
docs/mvp_consolidation_audit.md
docs/mvp_consolidation_report.md      # after implementation
```

## G. Dead code and unused file audit

Static import results were treated only as evidence, not proof of dead code.
CLI build modules with no imports were checked for artifact provenance before
classification.

### Strong removal candidates

| Candidate | Evidence |
|---|---|
| `notebooks/01_baseline_eda.ipynb` | Exploratory UMD/model notebook; not linked from current runtime |
| `notebooks/02_pm_prototype_validation.ipynb` | Uses superseded B2/domain state and old debug artifacts |
| `src/mvp/run_demo.py` | Omits implemented Phase 5B–5E/scenario v2; stale limitations; notebook uses a different adapter |
| `src/mvp/llm_synthesis.py` | Old five-field interpretation used only by the wrapper inside `evidence_card.py`; notebook uses `evidence_interpretation.py` |
| `src/pipeline.py`, `src/benchmarks/`, `src/overlays/`, `src/reporting/`, `src/experiments/reversal_checklist.py` | Form the retained pre-scorecard pipeline, not the final notebook path |
| `src/modeling/` | B0/B1/B2/B3 research is absent from the final runtime |
| `src/features/gdelt.py`, `narrative_panel.py`, `positioning_panel.py` | Build legacy alternative-data panels not read by the final notebook |
| `src/data/gdelt.py`, `gdelt_sanity.py`, `finra.py`, `universe.py` | Acquisition support for the above legacy panels; no final runtime reader |
| Most `outputs/*.csv`, `*.parquet`, reports and old `outputs/mvp/` | Generated model/phase artifacts; current adapter rebuilds scorecard in memory |
| `outputs/demo/*` | Generated by stale `run_demo`; not the notebook’s final card |
| `outputs/unwind_structure/*` | Sample output only; current notebook rebuilds the assessment |
| Obsolete docs identified in section F | Git history already preserves them |

### Review-required candidates

| Candidate | Why not classified dead yet |
|---|---|
| `src/monitoring/contracts.py`, `risk_state.py`, `positioning.py`, `market_context.py`, `domain_risk.py` | Not final runtime, but current classified-evidence fixtures were generated from these contracts and tests validate replay |
| `src/evidence/query_builder.py`, `retriever.py`, `classifier.py`, prompts and validation | They generate the exact cache replayed by the final card, although the notebook does not call them |
| `src/evidence/archived_provider.py`, `provider_contracts.py`, `corpus_schema.py`, `versioned_classifier.py`, `evidence/mvp.py` | Strict archive design is incomplete but provides evidence-governance tests |
| `src/evaluation/retrieval_gold.py` and `data/evaluation/2020_retrieval_gold/` | Not runtime; may be retained as the evidence-layer validation artifact |
| `data/raw/` | Some files are necessary to rebuild committed core processed data; others support removed experiments |
| `data/processed/sec_shares_outstanding.parquet` and Phase 5A outputs | Optional fundamental reproducibility support, not default runtime |

### Local and cached files

- `.DS_Store`, `.pytest_cache/`, `__pycache__/`, egg-info and notebook
  checkpoints are already ignored, although local copies exist.
- No tracked `_old`, `_new`, `_fixed`, `_backup`, or editor-backup files were
  found. Names containing `v2` are active schema/version names, not backups.
- Large ignored raw caches explain most of the 2.5 GB workspace size.
- `.gitignore` already covers the major Python/Jupyter caches and selected raw
  data. It should be reviewed only after the approved artifact set is chosen.

## H. Test coverage and reproducibility audit

### Existing protection

| Material risk | Existing protection | Assessment |
|---|---|---|
| Point-in-time joins | Narrative interval tests, FINRA publication-date tests, SEC filing tests, theme `t-1` tests, future-row invariance across regime/portfolio/risk/scorecard | Strong |
| Label maturity | Forward-window alignment, matured-threshold future invariance, immature-label exclusion | Strong for UMD labels |
| Feature determinism | Fixed-date rebuild, byte-identical cache rebuilds where raw caches exist | Strong |
| Threshold behavior | Scorecard boundary/fallback/floor/ceiling tests; unwind prior-only thresholds; scenario rule tests | Strong at component level |
| Configuration propagation | Custom `ScorecardConfig` unit tests; default profile recorded | Weak end to end; profile does not cover Phase 5 |
| Model reproducibility | Purged split/manifests and baseline artifacts | Strong for historical models, irrelevant to final runtime |
| Clean-kernel notebook | Manual/in-memory audit passes; smoke only checks source markers/dependencies | Missing as an automated repository test |
| Scoreboard consistency | Adapter run ID, date, evidence cutoff and deterministic repeatability; unwind date equality in smoke | Incomplete because run ID omits unwind/holdings/evidence bytes |
| Evidence ranking | Curated and archive retriever tests | Strong for tooling, but final preview does no ranking |
| Evidence cutoff/grounding | Multiple fixture, archive, classifier and card tests | Strong |
| Analog retrieval | Insurance-table tests only | No true analog retrieval or distance test exists |

### Minimum safety net before consolidation

Only four additional tests are recommended:

1. **Unified run coherence:** one result must assert identical as-of/config
   identity across DM context, scorecard, unwind, active holdings, evidence and
   display metadata.
2. **Config propagation and scope:** changing a supported config input must
   change every intended dependent field and leave unrelated research
   calculations unchanged. Until multiple profiles exist, explicitly test that
   the default profile binds the unchanged Phase 4, unwind and theme configs.
3. **Full-run fingerprint:** a deterministic run hash must include the
   scorecard, unwind/scenario contract, active formation, evidence/corpus hash
   and immutable config.
4. **Automated clean-kernel notebook execution:** execute the single retained
   notebook in memory or a temporary copy and fail on any error output.

A fifth characterization test is recommended before renaming historical
outputs: assert that the current `historical_analogs` records contain aggregate
state outcomes and no analog date/distance, so consolidation cannot silently
introduce a new method.

## Proposed target repository structure

This keeps the current package layout and does not create empty architecture.

```text
momentum_crash/
├── README.md
├── pyproject.toml
├── uv.lock
├── src/
│   ├── data/                         core French/SPY/price/SEC loaders only
│   ├── features/                     UMD labels/features + momentum breadth
│   ├── portfolio/momentum.py
│   ├── regime/market_state.py
│   ├── risk/
│   │   ├── dm_engine.py
│   │   ├── leg_decomposition.py
│   │   ├── concentration.py
│   │   └── theme_concentration.py
│   ├── monitoring/
│   │   ├── scorecard.py
│   │   ├── unwind_structure.py
│   │   └── fundamental_anchor.py
│   ├── evidence/
│   │   ├── corpus.py
│   │   └── research_preview.py
│   └── mvp/
│       ├── config.py                 small frozen run config
│       ├── pipeline.py               composition only
│       ├── contracts.py              one final run contract
│       ├── evidence_interpretation.py
│       └── presentation.py
├── notebooks/
│   └── momentum_risk_monitor_demo.ipynb
├── tests/
│   ├── component tests retained from current suite
│   ├── test_mvp_run_coherence.py
│   ├── test_mvp_config.py
│   └── test_demo_notebook.py
├── data/
│   ├── corpus/
│   ├── fixtures/
│   ├── processed/                    only required reproducibility inputs
│   └── raw/                          only sources required for those inputs
├── artifacts/
│   └── sample_output/                one intentional deterministic sample
└── docs/
    ├── methodology.md
    ├── limitations.md
    ├── demo_walkthrough.md
    ├── mvp_consolidation_audit.md
    └── mvp_consolidation_report.md
```

The proposed `src/mvp/pipeline.py` is not a redesign of calculations. It would
only compose existing functions and replace the stale root `src/pipeline.py`
and `src/mvp/run_demo.py` as the one MVP boundary.

## File-by-file action table

Actions below are proposals only. No action has been executed.

### Root, notebooks and documentation

| File | Action | Reason | Risk | Replacement/canonical source |
|---|---|---|---|---|
| `README.md` | MODIFY | Remove competing entry points and development diary | Low | Current notebook + final pipeline |
| `pyproject.toml`, `uv.lock` | KEEP | Reproducible locked environment works | Low | Existing |
| `.gitignore` | MODIFY | Only after final artifact inventory | Low | Existing |
| `config/phase2_queries.yaml` | DELETE_FROM_MVP_BRANCH | Configures the removed B3/GDELT ablation, not the final run | Medium | Git history |
| `BLOCKERS.md`, `NEXT_STEPS.md` | MERGE | Current limitations mixed with obsolete roadmap | Low | `docs/limitations.md` |
| `phase_6_review.md` | MERGE | Current facts mixed with session history | Low | methodology/report |
| `notebooks/01_baseline_eda.ipynb` | DELETE_FROM_MVP_BRANCH | Exploratory historical model notebook | Low | Git history |
| `notebooks/02_pm_prototype_validation.ipynb` | DELETE_FROM_MVP_BRANCH | Superseded domain/B2 presentation | Low | Git history |
| `notebooks/03_pm_evidence_card_demo.ipynb` | MODIFY/MOVE | Single demo candidate; remove direct orchestration duplication | Medium | `notebooks/momentum_risk_monitor_demo.ipynb` |
| `docs/methodology.md` | MODIFY | Add current Phase 5/scenario/evidence truth | Low | Current source contracts |
| `docs/demo_walkthrough.md` | MODIFY | Retain concise reviewer runbook | Low | Final notebook |
| `docs/ARCHIVED_EVIDENCE.md` | MERGE | Important limitation, not separate user path | Low | methodology/limitations |
| `docs/confirmed_design.md`, `docs/development_plan.md`, `docs/PROJECT_PLAN_v3.md`, `docs/meeting_feedback.md` | DELETE_FROM_MVP_BRANCH | Obsolete plans/current conflicts | Low | Git history |
| `docs/handoff.md`, `docs/handoff_phase5.md`, `docs/handoff_phase5_unwind.md` | MERGE | Preserve only current commands/limits | Low | README/methodology/report |
| `docs/phase_6_implementation_plan.md`, `docs/phase_6a_review.md` | DELETE_FROM_MVP_BRANCH | Completed session history | Low | Git history |
| `docs/DECISIONS.md` | DELETE_FROM_MVP_BRANCH | Valuable journal but not a five-minute reviewer path | Medium | Git history; selected facts in methodology |
| `docs/phase_reviews/` | DELETE_FROM_MVP_BRANCH | Development journal | Low | Git history |
| `docs/history/README_legacy.md` | DELETE_FROM_MVP_BRANCH | Visible archive unnecessary | Low | Git history |
| `docs/sp500_universe.md`, `docs/universe.md` | DELETE_FROM_MVP_BRANCH | Generated/legacy constituent documentation | Low | concise methodology limitation |
| `docs/limitations.md` | ADD | One current limitation source is missing | Low | Merge current limitations |
| `docs/mvp_consolidation_report.md` | ADD | Required final consolidation record | Low | Phase 7 deliverable |

### Current quantitative and orchestration source

| File | Action | Reason | Risk | Replacement/canonical source |
|---|---|---|---|---|
| `src/portfolio/momentum.py` | KEEP | Authoritative named portfolio | High | Existing |
| `src/regime/market_state.py` | KEEP | Authoritative macro/recovery state | High | Existing |
| `src/risk/leg_decomposition.py` | KEEP | Authoritative named leg-risk build | High | Existing |
| `src/risk/concentration.py` | KEEP | Authoritative concentration calculations | High | Existing |
| `src/risk/theme_concentration.py` | KEEP | Authoritative PIT theme proxy | High | Existing |
| `src/risk/dm_engine.py` | MODIFY | Keep state/frequency role; remove dependency on legacy B2 module for timestamp helper | Medium | Same calculations |
| `src/monitoring/scorecard.py` | KEEP | Authoritative four-row decisions | High | Existing |
| `src/monitoring/unwind_structure.py` | KEEP | Authoritative six-row/scenario v2 | High | Existing |
| `src/monitoring/fundamental_anchor.py` | KEEP | Current fail-closed fundamental row | High | Existing |
| `src/mvp/evidence_card.py` | MERGE | Contains schema, two orchestration layers and obsolete HTML/LLM path | Medium | final contracts + pipeline + presentation |
| `src/mvp/evidence_interpretation.py` | KEEP | Current constrained interpretation | Medium | Existing |
| `src/mvp/llm_synthesis.py` | DELETE_FROM_MVP_BRANCH | Superseded interpretation schema | Low | `evidence_interpretation.py` |
| `src/mvp/demo_smoke_test.py` | MODIFY | Point it at one run object and execute notebook path | Low | final pipeline |
| `src/mvp/run_demo.py` | DELETE_FROM_MVP_BRANCH | Stale Phase 5A-only presentation | Medium | final pipeline |
| `src/mvp/config.py` | ADD | Single immutable run boundary | Medium | New composition-only module |
| `src/mvp/pipeline.py` | ADD | Compose existing calculations once | Medium | Replaces competing entry points |
| `src/mvp/presentation.py` | ADD | Move notebook HTML/presentation only | Low | Notebook cells |
| `src/mvp/contracts.py` | MODIFY | Retain `PrimaryRiskAssessment`; add/merge final run contract carefully | Medium | One contract source |

### Build-support source

| File(s) | Action | Reason | Risk | Replacement/canonical source |
|---|---|---|---|---|
| `src/data/french.py`, `prices.py`, `sp500.py`, `symbols.py`, `trading_calendar.py`, `vix.py` | KEEP | Rebuild core French/SPY/price inputs | Medium | Existing |
| `src/data/sec_edgar.py`, `sec_fundamentals.py` | KEEP | Optional fundamental reproducibility | Medium | Existing |
| `src/features/labels.py`, `legs.py`, `market_features.py`, `momentum_breadth.py` | KEEP | Core UMD and Phase 5 build support | High | Existing |
| `src/utils/io.py`, `http.py` | KEEP | Shared I/O/acquisition | Medium | Existing |
| `src/utils/pit.py` | REVIEW_REQUIRED | Needed only if narrative/positioning panels are retained | Low | — |
| All package `__init__.py` files | KEEP/MODIFY | Retain only for surviving packages | Low | — |

### Legacy research and alternative-data source

| File(s) | Action | Reason | Risk | Replacement/canonical source |
|---|---|---|---|---|
| `src/pipeline.py` | DELETE_FROM_MVP_BRANCH | Competing old MVP entry | Medium | `src/mvp/pipeline.py` |
| `src/benchmarks/b2_shadow.py` | DELETE_FROM_MVP_BRANCH | Old B2 shadow only | Low | Git history |
| `src/experiments/reversal_checklist.py` | DELETE_FROM_MVP_BRANCH | Superseded scenario logic | Medium | scenario v2 |
| `src/overlays/snapshots.py` | DELETE_FROM_MVP_BRANCH | Old pipeline only | Low | Current evidence warnings |
| `src/reporting/pm_brief.py` | DELETE_FROM_MVP_BRANCH | Old pipeline report | Low | presentation module |
| `src/modeling/audit.py`, `baselines.py`, `phase2.py`, `validation.py` | DELETE_FROM_MVP_BRANCH | Historical model research, no final runtime use | Medium | Git history |
| `src/features/gdelt.py`, `narrative_panel.py`, `positioning_panel.py` | DELETE_FROM_MVP_BRANCH | Not final MVP inputs | Medium | Git history |
| `src/data/gdelt.py`, `gdelt_sanity.py`, `finra.py`, `universe.py` | DELETE_FROM_MVP_BRANCH | Support removed alternative panels | Medium | Git history |
| `src/monitoring/domain_risk.py`, `market_context.py`, `positioning.py`, `risk_state.py`, `contracts.py` | REVIEW_REQUIRED | Legacy runtime, but evidence-cache generation depends on these contracts | High | Decide evidence-tooling boundary first |

### Evidence and evaluation source

| File(s) | Action | Reason | Risk | Replacement/canonical source |
|---|---|---|---|---|
| `src/evidence/corpus.py`, `research_preview.py` | KEEP | Current exact-date replay | High | Existing |
| `src/evidence/query_builder.py`, `retriever.py`, `classifier.py`, `classification_validation.py`, `prompts.py` | REVIEW_REQUIRED | Generate current cache but not called by demo | High | Retain as isolated tooling or remove with frozen cache |
| `src/evidence/archived_provider.py`, `provider_contracts.py`, `corpus_schema.py`, `versioned_classifier.py`, `mvp.py` | REVIEW_REQUIRED | Strict but incomplete second evidence stack | High | Evaluation/future branch |
| `src/evaluation/retrieval_gold.py` | REVIEW_REQUIRED | Evidence validation value; no runtime use | Medium | Optional `evaluation/` package |

### Tests

| Files | Action | Reason | Risk | Replacement/canonical source |
|---|---|---|---|---|
| Portfolio/regime/scorecard/leg/concentration/theme/unwind/fundamental tests | KEEP | Protect current research meaning and PIT rules | High | Existing |
| Evidence Card/adapter/interpretation/research-preview tests | MODIFY | Bind to one final run and current interpretation | High | final pipeline contracts |
| `test_demo_smoke_test.py` | MODIFY | Add actual clean-kernel execution outside fast smoke if needed | Medium | new notebook test |
| Modeling/B2/domain/positioning/GDELT tests | DELETE_FROM_MVP_BRANCH with removed modules | No final runtime role | Medium | Git history |
| Archive/retrieval-gold tests | REVIEW_REQUIRED | Keep only if evidence evaluation/tooling remains | Medium | approved evidence boundary |
| `test_mvp_run_coherence.py`, `test_mvp_config.py`, `test_demo_notebook.py` | ADD | Minimum consolidation safety net | High | New tests |

### Data, artifacts and outputs

| File/family | Action | Reason | Risk | Replacement/canonical source |
|---|---|---|---|---|
| Core French raw/processed inputs | KEEP | DM/macro/label reproducibility | High | Existing |
| S&P universe/prices/benchmark, portfolio holdings/returns, leg risk | KEEP | Current named portfolio/runtime | High | Existing |
| `data/processed/momentum_breadth_history.parquet`, `unwind_structure_history.parquet`, `recovery_attribution.parquet` | REVIEW_REQUIRED | Generated and not read by current default assessment | Low | Rebuild in memory or one sample artifact |
| GDELT/FINRA/top-200 raw and processed families | DELETE_FROM_MVP_BRANCH if legacy path approved for removal | Not current demo inputs | Medium | Git history/local reacquisition |
| SEC raw/processed and Phase 5A compact audits | REVIEW_REQUIRED | Optional fundamental reproducibility; default row unavailable | Medium | Keep minimal audit or remove |
| `data/corpus/momentum_evidence_corpus_v1.json`, manifest and current classifier fixtures | KEEP | Current evidence replay | High | Existing |
| `data/evaluation/` | REVIEW_REQUIRED | Evaluation only | Medium | Optional retained evaluation artifact |
| `outputs/debug/classified_evidence_2009-03-06.json`, `classified_evidence_2024-01-05.json` | KEEP/MOVE | Required exact-date replay fixtures | High | `artifacts/sample_output/evidence/` |
| Other `outputs/debug/*` | REVIEW_REQUIRED | Needed only to regenerate/validate classifications | Medium | Evidence tooling decision |
| Model, phase, scorecard, old MVP and old demo outputs | DELETE_FROM_MVP_BRANCH | Generated/stale and reproducible from kept inputs where relevant | Low | One final sample output |
| `artifacts/component_status/*` | REVIEW_REQUIRED | Retrieval evaluation status only | Low | Consolidation report or evaluation package |

## Prioritized phased implementation plan

### Phase 1 — Safety net

Files intended:

- add `tests/test_mvp_run_coherence.py`;
- add `tests/test_mvp_config.py`;
- add `tests/test_demo_notebook.py`;
- add a characterization assertion for the current state-conditioned history
  payload.

Invariant:

- no value, threshold, label, timing rule, state or scenario result changes.

Checkpoint:

- full suite and notebook clean-kernel execution.

### Phase 2 — Single configuration and run contract

Files intended:

- add `src/mvp/config.py`;
- add or revise the final contract in `src/mvp/contracts.py`;
- add `src/mvp/pipeline.py`;
- minimally adapt `src/mvp/evidence_card.py` and
  `src/mvp/demo_smoke_test.py`.

Invariant:

- existing component functions and default configs are called unchanged;
- profile scope is explicit;
- the full run hash covers every displayed deterministic/evidence component.

Checkpoint:

- compare serialized component values for 2024-01-05, 2020-03-24 and
  2026-05-29 before/after.

### Phase 3 — Approved duplicate consolidation

Files intended:

- remove the obsolete `llm_synthesis`/old `EvidenceCard` assembly after the
  current adapter no longer depends on it;
- remove `run_demo.py` and the root legacy pipeline only if approved;
- resolve the evidence-tooling boundary before touching legacy monitoring
  contracts.

Invariant:

- no research behavior changes;
- current cache replay and interpretation validation remain byte/value
  equivalent.

Checkpoint:

- focused contract/PIT tests after each small removal.

### Phase 4 — One notebook and presentation layer

Files intended:

- add `src/mvp/presentation.py`;
- rename/modify notebook 03;
- remove notebooks 01 and 02 from the MVP branch.

Invariant:

- the default displayed values, statuses, scenario states, evidence and
  limitations remain identical;
- notebook becomes orchestration/presentation only.

Checkpoint:

- clean-kernel run at a normal, comparison and missing-evidence date.

### Phase 5 — Documentation and artifact consolidation

Files intended:

- rewrite `README.md`, `docs/methodology.md`,
  `docs/demo_walkthrough.md`;
- add `docs/limitations.md`;
- remove approved plans/handoffs/reviews;
- retain one intentional sample output and only necessary processed/corpus
  artifacts.

Invariant:

- research limitations are not softened;
- removed material remains reachable at the pre-consolidation Git checkpoint.

### Phase 6 — Final validation and report

Files intended:

- add `docs/mvp_consolidation_report.md`;
- update `.gitignore` only if the final artifact policy requires it.

Validation:

- full tests;
- import checks for retained packages;
- clean-kernel notebook;
- changed date and comparison date;
- full-run deterministic hash;
- stale reference, hardcoded date/threshold and broken-link searches;
- final Git diff and fresh-environment README command check.

## Decisions requiring approval

1. **Dual research universe:** approve retaining UMD/DM as explicitly labeled
   macro/factor context while the Phase 2–5 scorecard uses the named S&P 500
   proxy. The alternative—relabeling the named portfolio with UMD labels—would
   be a research-method change and is not recommended during consolidation.
2. **Meaning of the header:** approve renaming the current
   `overall_risk_state` display to `DM market state` or similarly explicit
   wording. Do not present it as an aggregate of the four scorecard rows.
3. **No aggregate deterministic score:** approve keeping
   `deterministic_score=None` and describing the product as a deterministic
   scorecard/scenario monitor. Creating a score would change research meaning.
4. **Historical context naming:** approve renaming `historical_analogs` to
   state-conditioned historical outcomes in the presentation/next schema.
   True analog retrieval is absent and should not be invented here.
5. **Threshold profile scope:** approve one `MVPConfig` that records the
   unchanged Phase 4, unwind and theme defaults. Decide whether the user-facing
   name remains `threshold_profile` or becomes `phase4_threshold_profile`.
6. **Legacy model/pipeline removal:** approve removing B0/B1/B2/B3 modeling,
   the root pipeline, old demo runner, overlays, domain prototype and their
   visible outputs/docs from the MVP branch.
7. **Evidence tooling boundary:** choose one:
   - retain curated corpus generation/classification plus retrieval-gold
     evaluation as clearly isolated tooling; move the strict archive design out
     of the MVP branch; or
   - retain both evidence stacks under an explicitly non-runtime
     `evaluation/` boundary.
   The audit recommends the first option.
8. **Alternative-data removal:** approve removing GDELT/FINRA/top-200
   positioning panels and related acquisition code from the MVP branch because
   they do not feed the final notebook.
9. **SEC/fundamental artifacts:** approve retaining only the minimal Phase 5A
   coverage audit and current fail-closed fundamental code, or remove the
   optional fundamental path entirely. The recommendation is to retain the
   calculation/tests and one compact coverage audit, not issuer-level outputs.
10. **Git safety references:** authorize the recommended tag and archive branch
    before Phase 1 deletion work.

## Expected behavior changes

For the proposed consolidation:

```text
No intended research behavior changes.
```

Expected non-research changes, subject to approval:

- one authoritative entry point and run hash;
- explicit UMD versus S&P 500 proxy labels;
- explicit Phase 4 threshold-profile scope;
- “historical analogs” renamed to what the current records actually are;
- one notebook and a shorter reviewer path;
- old research, plans and generated artifacts removed from the visible MVP
  branch but retained in Git history.

Any disagreement discovered between serialized pre/post component results must
stop the relevant implementation phase for review.
