# Final MVP handoff

Status: final integration implemented on branch `final-mvp-integration`.

## Primary command

```bash
uv run python -m src.mvp.run_demo --as-of-date 2026-05-29
```

This is the unique primary demo entry. It is offline, reads existing artifacts,
and writes only `outputs/demo/`.

## Completed workflow

- Phase 1 — deterministic macro regime.
- Phase 2 — current-membership-proxy 12-1 momentum portfolio with named
  10-long and 10-short legs.
- Phase 3 — realized return, contribution, beta, conditional beta,
  volatility, and drawdown decomposition.
- Phase 4 — unchanged four-row deterministic scorecard.
- Phase 5A — one-per-CIK SEC Company Facts acquisition and coverage audit.
- Final MVP integration — date-safe current observation, reproducible 2023
  case, structured outputs, and a fail-closed evidence capability preview.

## Date contract

For the primary observation:

- observation date: `2026-05-29`;
- active risk-portfolio formation: `2026-04-30`;
- next rebalance formation: `2026-05-29`;
- macro latest date: `2026-05-29`;
- holdings, risk, and scorecard stores contain later June data, but those
  observations are not mixed into the current case;
- Phase 5A audit date: `2026-06-30`, shown only as feasibility metadata.

## Phase 5A freeze

Reviewed two-of-three coverage is 322/497, or 64.79%, with `degraded` status.
The final summary deliberately exposes:

- `alignment_status="future_work"`;
- `fundamental_ranks=null`;
- `spearman_alignment=null`;
- `long_short_fundamental_spread=null`;
- `alignment_flags=null`;
- `risk_conclusion=null`.

Raw Company Facts remain untracked. Only compact aggregate feasibility audit
files are committed. The issuer-level acquisition, company-coverage, and
taxonomy diagnostics remain local and ignored.

## Evidence boundary

`src/evidence/research_preview.py` is a Phase 8 capability preview, not Phase 8
completion. It can replay only exact-date, existing validated cached
classifications against the local versioned corpus. It cannot call a model or
network service, alter deterministic facts, introduce thresholds, or create a
risk score.

There is no exact-date validated cache for `2023-01-09`, so the demo returns
`unavailable` and three empty evidence arrays. The result is intentionally
fail-closed.

## Required integration tests

`tests/test_demo.py` contains exactly four tests:

1. date alignment;
2. Phase 5 metrics remain unavailable;
3. deterministic replay;
4. no modification of existing artifacts.

`tests/test_research_preview.py` contains exactly two tests:

1. deterministic facts are preserved;
2. missing evidence fails safely.

## Files added by final integration

- `src/mvp/run_demo.py`
- `src/evidence/research_preview.py`
- `tests/test_demo.py`
- `tests/test_research_preview.py`
- `docs/methodology.md`
- `docs/demo_walkthrough.md`
- `docs/handoff.md`
- four generated artifacts under `outputs/demo/`

`README.md`, `docs/confirmed_design.md`, and `docs/development_plan.md` are
updated to name the demo entry and preserve deferred scope.

## Known limitations

- Historical holdings use current S&P 500 membership and are
  survivorship-biased.
- Extreme momentum values may include corporate-action or ticker-history
  discontinuities.
- Phase 5A coverage is not fundamental alignment.
- The evidence corpus is small and lacks a date-matched 2023 classification.
- The monitor is descriptive, not causal, predictive, or a trading system.

## Deferred, not removed

- Phase 5B — production-grade historical SEC fundamentals.
- Phase 7 — Crowding Monitoring.
- Phase 8 — Full AI Research and Retrieval Layer.

No breadth, concentration, crowding, live news, vector database, website,
dashboard, deployment, new predictive model, or broad refactor was added.

## Git checkpoint sequence

1. `checkpoint: freeze phases 1-5 and phase 5A audit`
2. `feat: add deterministic MVP demo entry point`
3. `test: add minimal MVP safety tests`
4. `feat: add bounded research evidence preview`
5. `docs: add demo walkthrough and handoff`

## Final validation record

Run on 2026-07-28:

- primary demo command: passed;
- focused integration tests: 6 passed;
- complete suite: 215 collected, 211 passed, 4 skipped;
- skips: existing cache-dependent GDELT, price, narrative-rebuild, and FINRA
  rebuild checks;
- `git diff --check`: passed.

Generated SHA-256 hashes:

| Artifact | SHA-256 |
|---|---|
| `demo_summary_2026-05-29.json` | `6b3aeb878f18530adebfb79d920b8f3f7fc94f8a95499d2af038e48bd946f97f` |
| `demo_scorecard_2026-05-29.csv` | `6ced62f8e7c4cd025aae8321960e47ecbf6ba6f9003c82b33a9ad4e1460978a5` |
| `demo_portfolio_2026-05-29.csv` | `4f32db6cf4fab9a70aae42e0192f424e9ff24fd5623c87516e48911455aa5bdd` |
| `demo_report_2026-05-29.md` | `2a1d7b9d3dd8a6a4178e7c784c93a9fed3ab9027588b1d33253367ea4be601bc` |
