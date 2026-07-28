# Phase 6A review — interactive PM Evidence Card

Phase 6A adds a date-driven, deterministic-first **PM Evidence Card** on top of
the frozen Phase 1–4 research code and the existing point-in-time evidence
replay. It reuses existing indicators, thresholds, scores, and retrieval; it does
not add a new model, database, retrieval system, or web application.

## Repository components reused (unchanged)

| Component | Location | Role |
|---|---|---|
| `build_primary_assessment` | `src/risk/dm_engine.py` | Headline `overall_risk_state` and descriptive conditional tail-loss frequency (PIT, in-memory). |
| `build_scorecard` / `ScorecardConfig` / `DEFAULT_CONFIG` | `src/monitoring/scorecard.py` | The four deterministic `QuantSignal` rows and the threshold-profile backing config. |
| `build_regime_history` | `src/regime/market_state.py` | Regime frame consumed by the scorecard. |
| `build_insurance_table` | `src/risk/dm_engine.py` | State-conditional tail-loss frequencies used for historical context. |
| `build_research_preview` | `src/evidence/research_preview.py` | Cutoff-enforced, cache-replay point-in-time evidence keyed to the selected date. |
| I/O helpers | `src/utils/io.py` | `parse_as_of_date`, `iso_date`, `write_json`, `DEFAULT_PROCESSED_DIR`, … |
| Frozen-dataclass validation convention | `src/mvp/contracts.py` | Pattern followed by the new schema (no Pydantic — the repo does not use it). |

## Files added

- `src/mvp/evidence_card.py` — the `EvidenceCard` / `QuantSignal` /
  `RetrievedEvidence` schema, the threshold-profile registry, the
  `build_evidence_card(...)` integration, rendering helpers, and a small offline
  CLI.
- `src/mvp/llm_synthesis.py` — the constrained narrative `Synthesizer` protocol,
  `SynthesisResult` (narrative-only, validated), and the offline
  `DeterministicSynthesizer` default.
- `notebooks/03_pm_evidence_card_demo.ipynb` — the single interactive demo
  notebook (ships pre-executed).
- `tests/test_evidence_card.py` — essential integration tests.
- `docs/phase_6a_review.md` — this handoff.

## Files modified

- `docs/demo_walkthrough.md` — appended the 20-minute Evidence Card walkthrough.
  No `src/` file from Phase 1–5 was modified.

## What works

- One reusable `build_evidence_card(as_of_date, threshold_profile, compare_to_date, use_llm, …)` entry point returning a validated `EvidenceCard`.
- The **selected date drives** the risk state and the four quantitative signals.
- The **comparison date drives** the per-signal `change_vs_comparison` and the
  `what_changed` list.
- Evidence retrieval respects the point-in-time cutoff (`data_cutoff` = the
  selected date's post-close timestamp); nothing published later is shown.
- The card is fully populated **without any LLM key** and without evidence.
- LLM/narrative synthesis **cannot alter any quantitative field**: numbers,
  thresholds, states, and the run id are identical with `use_llm=True` and
  `use_llm=False` (verified by test).
- Repeated runs with the same inputs return byte-identical cards.
- Existing Phase 1–5 artifacts are not modified (hash-checked in tests).

## What is unavailable / what is "mocked"

- **Point-in-time evidence exists for two cached dates only:** `2024-01-05`
  (3 supporting / 1 contradicting / 3 contextual) and `2009-03-06`
  (4 / 0 / 3). `2009-03-06` predates the leg-risk history (starts 2017-02-01),
  so a full card can only be built for `2024-01-05` among the two.
- For any other date (e.g. `2026-05-29`, `2020-03-24`) evidence fails safe to
  `evidence_quality = "unavailable"` with an explicit warning — this is
  uncertainty, not a benign finding.
- **No LLM is invoked.** `use_llm=True` runs the offline `DeterministicSynthesizer`
  by default. The evidence itself is a validated cache replay, not live
  retrieval (as documented in `BLOCKERS.md`).
- `deterministic_score` is intentionally `null`: the repository forbids a
  composite risk probability. The card reports the state, triggered-signal
  count, and the descriptive conditional tail-loss frequency instead.

## Commands

Deterministic card (offline, writes `outputs/demo/evidence_card_<date>.json`):

```bash
uv run python -m src.mvp.evidence_card --as-of-date 2024-01-05 --compare-to-date 2023-12-01
```

Open the interactive notebook (edit the parameter cell, then Run All):

```bash
uv run --with jupyterlab jupyter lab notebooks/03_pm_evidence_card_demo.ipynb
```

Run the Phase 6A tests (and the adjacent demo/evidence tests):

```bash
uv run --extra test python -m pytest -q tests/test_evidence_card.py tests/test_demo.py tests/test_research_preview.py
```

Run the full suite:

```bash
uv run --extra test python -m pytest -q
```

## Required environment variables

None. The entire path is offline and deterministic. No API key is required, now
or to reproduce the demo. A future real synthesizer (see below) would read its
own credentials from the environment and must still fall back deterministically.

## Deterministic fallback behavior

- No LLM key, no dependency: default `DeterministicSynthesizer` phrases narrative
  from structured facts. `synthesis_mode = "deterministic_no_llm"` (when
  `use_llm=False`) or `"deterministic_template"` (when `use_llm=True`, default
  synthesizer).
- Injected synthesizer that raises or returns an invalid object: the card falls
  back to the deterministic narrative, sets
  `synthesis_mode = "deterministic_fallback"`, and records a warning.
- Retrieval returns nothing for the date: `evidence_quality = "unavailable"`,
  evidence lists empty, `missing_or_uncertain_evidence` and a warning populated —
  no crash.
- Comparison date that cannot be computed: change analysis is skipped with a
  warning rather than raising.

## Known limitations

- Crowding/positioning proxies may not represent actual positions.
- Retrieval coverage is a small cached corpus and may be incomplete.
- Narrative synthesis organizes evidence; it does not prove causality.
- Thresholds are prior-only research rules, not optimized trading instructions.
- A sector selloff is not automatically a canonical UMD momentum crash.
- Historical cards use a survivorship-biased current-membership universe.

## Recommended Codex follow-up tasks

1. **Real constrained synthesizer** — implement a `Synthesizer` that calls a
   named model, reads its key from the environment, validates output against
   `SynthesisResult`, and keeps the deterministic fallback. Do not let it write
   any quantitative field. (Consult the `claude-api` guidance before wiring an
   Anthropic call.)
2. **More threshold profiles** — add named `ScorecardConfig` presets to
   `THRESHOLD_PROFILES` once a policy threshold is approved
   (see `NEXT_STEPS.md`, item 5). Keep `default` unchanged.
3. **Broader date-matched evidence** — add validated classification caches for
   more dates so evidence is available beyond `2024-01-05` / `2009-03-06`
   (depends on the archived-content corpus in `BLOCKERS.md`, B1).
4. **Point-in-time universe** — replace the survivorship-biased current-membership
   universe for historical cards (`NEXT_STEPS.md`, item 4).
5. **Optional sector case template** — only after the core notebook is accepted,
   draft the semiconductor / AI-infrastructure fragility appendix using data the
   repository already supports; do not acquire a new dataset.
