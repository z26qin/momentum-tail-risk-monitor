# Legacy research paths

This directory preserves prior prototype code for research history. Nothing
under `legacy/` is imported by the active `src.mvp.pipeline.run_mvp` workflow or
collected by the default test suite.

## B2 probability baseline

`b2/risk_state.py` is the replay adapter for the retired B0/B1/B2 fitted
probability experiment. Its generated predictions, coefficients, preprocessing
statistics, split manifests, and audits were intentionally removed in commit
`ae59f37` when the product moved to deterministic mechanism monitoring.

## Evidence-generation prototype

`evidence/` contains the earlier request → keyword retrieval → fixture
classification path and the standalone GDELT/DeepSeek experiment. The active
MVP instead replays validated exact-date classified evidence through
`src.evidence.research_preview` and constrains optional narrative providers at
the `src.mvp` boundary.

## Old notebook

`notebooks/final_mvp_demo_old.ipynb` documents the earlier standalone evidence
experiment. The supported notebook is `notebooks/final_mvp_demo.ipynb`.
