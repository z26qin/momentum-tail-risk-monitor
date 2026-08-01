# MVP consolidation report

Date: 2026-08-01  
Branch: `refactor/mvp-consolidation`  
Baseline tag: `pre-mvp-consolidation` (`9ec60ed`)

## 1. Summary

The repository was consolidated into a single PM/researcher-facing MVP path:

`MVPConfig` → `run_mvp()` → presentation notebook / Evidence Card.

Product framing (documentation / display labels; calculations unchanged):

- **S&P 500 12-1 long-10 / short-10** = default **customizable PM momentum portfolio**
  (primary monitored book);
- **Ken French UMD / Daniel–Moskowitz state** = **comparison benchmark** only.

No research formulas, thresholds, labels, or scenario rules were intentionally
changed. The default demo fingerprint remains `750f22225b7d9592` and the card
run ID remains `53c34aa57bb437fc`.

## 2. Files removed / archived

Removed from the active tree (recoverable from tag `pre-mvp-consolidation`
and ordinary Git history; no visible `archive/` directory):

### Documentation

- Root: `BLOCKERS.md`, `NEXT_STEPS.md`, `phase_6_review.md`
- `docs/` phase plans, handoffs, reviews, decisions journal, universe dumps,
  `ARCHIVED_EVIDENCE.md`, `confirmed_design.md`, `development_plan.md`, etc.

### Notebooks

- `01_baseline_eda.ipynb`
- `02_pm_prototype_validation.ipynb`
- `03_pm_evidence_card_demo.ipynb` (logic migrated into `final_mvp_demo.ipynb`
  + `src/mvp/presentation.py`)

### Legacy source

- `src/pipeline.py`, `src/mvp/run_demo.py`
- `src/benchmarks/`, `src/experiments/`, `src/overlays/`, `src/reporting/`
- `src/modeling/`, `src/evaluation/`
- GDELT / FINRA / narrative / positioning feature and data modules
- Old evidence stacks (classifier, retriever, archived provider, etc.)
- Legacy monitoring adapters (`domain_risk`, `market_context`, `positioning`)
- `config/phase2_queries.yaml`, `src/utils/pit.py`

### Tests tied to archived modules

About 20 obsolete test modules (pipeline, GDELT, positioning, retrieval-gold,
archived evidence, etc.).

## 3. Files merged / added

| File | Role |
|---|---|
| `src/mvp/config.py` | Single frozen run config |
| `src/mvp/pipeline.py` | Composition-only orchestration + full-run fingerprint |
| `src/mvp/presentation.py` | Charts / HTML / Markdown / JSON export |
| `notebooks/final_mvp_demo.ipynb` | Single presentation notebook |
| `docs/limitations.md` | Consolidated limitation source |
| `tests/test_mvp_config.py` | Config boundary smoke |
| `tests/test_mvp_run_coherence.py` | Unified-run coherence / fingerprint |

Presentation helpers were moved out of the old notebook cells without changing
quantitative values.

## 4. Documentation removed from the active tree

All phase reviews, handoffs, development plans, meeting notes, and large
universe dumps. Active docs are now:

- `README.md`
- `docs/methodology.md`
- `docs/limitations.md`
- `docs/demo_walkthrough.md`
- `docs/mvp_consolidation_audit.md` (Phase 0 audit)
- `docs/mvp_consolidation_report.md` (this file)

## 5. Repository structure changes

- One notebook entry point instead of three.
- One orchestration entry (`src.mvp.pipeline.run_mvp`) instead of competing
  `run_demo` / root `pipeline` / notebook-local wiring.
- Legacy research paths removed from the active tree; recoverable from Git history.
- README rewritten for a Quant PM / researcher audience.
- Evidence generation path restored (`query_builder` / `retriever` / `classifier`).

## 6. Testing simplifications

Kept MVP smoke / integration / contract tests for:

- config + unified run coherence;
- Evidence Card / interpretation / research preview;
- scorecard, unwind/scenarios, theme concentration;
- regime, portfolio, leg risk, fundamentals.

Removed tests whose only purpose was archived research paths.

## 7. Remaining technical debt

- `src/mvp/evidence_card.py` still contains an older `EvidenceCard` /
  `llm_synthesis` assembly path used internally by the deterministic adapter.
  Safe to thin later; not required for demo clarity.
- `src/monitoring/contracts.py` and `risk_state.py` still carry legacy contract
  surface used by corpus / timestamp helpers.
- Visible `archive/` was removed; recovery is via tag `pre-mvp-consolidation`.
- Evidence generation path (`query_builder` / `retriever` / `classifier` plus
  `positioning` inputs) was restored in `src/evidence/`.
- `outputs/` trimmed to demo examples, evidence fixtures
  (`classified_evidence_*` plus risk/positioning states for regeneration),
  `retrieval_evaluation.csv`, and SEC Phase 5A audits. Legacy B2/model and
  phase-review artifacts removed from the active tree (recoverable from
  `pre-mvp-consolidation`).

## 8. Assumptions made during cleanup

1. Frozen processed Parquets + evidence caches are sufficient for review; live
   GDELT/FINRA acquisition is out of MVP scope.
2. Rebuild CLIs (`french`, `labels`, `legs`, `leg_decomposition`, SEC loaders)
   should remain for reproducibility even though the notebook does not import
   them at runtime.
3. Prefer archiving over silent deletion so prior phase work stays inspectable.
4. Dual-universe labeling (UMD vs named proxy) is presentation/documentation
   only — calculations unchanged.
5. Matching the pre-existing full-run fingerprint is the regression oracle that
   consolidation did not alter research outputs.
