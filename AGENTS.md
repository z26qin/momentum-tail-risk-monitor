# AGENTS.md

## Cursor Cloud specific instructions

This repository is the **Momentum Tail-Risk Monitor** (`momentum-crash`), a self-contained Python
research MVP. It is a data-science library + CLI + demo notebook — there is **no web server, no
database, and no long-running service**. Everything runs in-process against bundled local Parquet
panels under `data/processed/`, fully offline and deterministically.

### Tooling
- Python project managed by [`uv`](https://docs.astral.sh/uv/). The `uv` binary lives at
  `~/.local/bin/uv` (on `PATH`). Dependencies are installed by the startup update script via
  `uv sync --locked --all-groups` into a project-local `.venv` (git-ignored).
- Standard run/test commands are documented in `README.md` ("How to run"). Prefix them with `uv run`.

### Running / testing (non-obvious caveats)
- Smoke test: `uv run python -m src.mvp.demo_smoke_test`. It runs three full `run_mvp` passes and is
  **slow (~2 minutes)**; a healthy run ends with `"status": "ready"`.
- A single `run_mvp(config)` is CPU-heavy (~40s). Budget generous timeouts when scripting it.
- Test suite: `uv run python -m pytest -q`. The full suite is **slow (~9 minutes / 194 tests)**.
- **Known pre-existing failures (not environment issues):** 4 tests currently fail because they hold
  stale hard-coded expected values that no longer match the bundled data — `test_mvp_run_coherence`
  (hard-coded `full_run_fingerprint`), plus evidence-retrieval expectations in `test_corpus`,
  `test_deterministic_evidence_input`, and `test_evidence_card`. The pipeline itself runs correctly
  (the failing fingerprint test's "actual" value matches the smoke-test output). Do not "fix" these
  by touching setup; they are data/test drift in the committed repo.

### Lint
- There is **no lint tooling configured** (no ruff/flake8/black/mypy in `pyproject.toml` or the lock).
  Treat `pytest` as the automated check.

### Optional LLM path
- LLM interpretation is optional and off by default (`use_llm=False`). To enable the live path, add
  `DEEPSEEK_API_KEY` (and optionally `ANTHROPIC_API_KEY`) to a `.env` in the repo root. Missing/invalid
  keys fail closed to deterministic text — the LLM can never change metrics, thresholds, or risk state,
  so it is never required for tests or the smoke test.
