# Legacy research paths

This directory preserves prior prototype code for research history. Nothing
under `legacy/` is imported by the active `src.mvp.pipeline.run_mvp` workflow or
collected by the default test suite.

## B2 probability baseline

`b2/risk_state.py` is the replay adapter for the retired B0/B1/B2 fitted
probability experiment. Its generated predictions, coefficients, preprocessing
statistics, split manifests, and audits were intentionally removed in commit
`ae59f37` when the product moved to deterministic mechanism monitoring.

## Retired evidence-generation prototype

`evidence/` contains the earlier request → keyword retrieval → fixture
classification path. GDELT retrieval and DeepSeek/OpenAI risk-state
interpretation are active capabilities under `src/evidence/` and are shown in
the supported final notebook.

## Old notebook

`notebooks/final_mvp_demo_old.ipynb` documents the earlier standalone evidence
experiment. The supported notebook is `notebooks/final_mvp_demo.ipynb`.
