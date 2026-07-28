# Phase 5A handoff

Date: 2026-07-28

Status: stopped at operator request. Phase 5B is not authorized. No SEC
acquisition or parsing process is running.

## 1. Files created or modified

Tracked files modified but not committed:

- `.gitignore`
- `docs/confirmed_design.md`
- `docs/development_plan.md`
- `docs/meeting_feedback.md`
- `docs/phase_reviews/README.md`
- `docs/phase_reviews/phase_5_review.md`
- `src/data/sec_edgar.py`
- `src/data/sp500.py`

Untracked source, test, and handoff files:

- `src/data/sec_fundamentals.py`
- `tests/test_sec_fundamentals.py`
- `docs/handoff_phase5.md`

Untracked generated Phase 5A artifacts:

- `outputs/fundamental_alignment/phase_5a_acquisition_status.csv`
- `outputs/fundamental_alignment/phase_5a_audit.json`
- `outputs/fundamental_alignment/phase_5a_company_coverage.csv`
- `outputs/fundamental_alignment/phase_5a_metric_coverage.csv`
- `outputs/fundamental_alignment/phase_5a_missing_diagnostics.csv`
- `outputs/fundamental_alignment/phase_5a_portfolio_leg_coverage.csv`
- `outputs/fundamental_alignment/phase_5a_sector_coverage.csv`
- `outputs/fundamental_alignment/phase_5a_taxonomy_diagnostics.csv`

Ignored local SEC cache files were also generated:

- 497 payloads matching
  `data/raw/sec/company_facts_CIK*.json`;
- 497 provenance sidecars matching
  `data/raw/sec/company_facts_CIK*.json.metadata.json`.

The exact CIK and local path for every payload are recorded in
`phase_5a_acquisition_status.csv`. The raw payloads and sidecars are excluded
by `.gitignore` and must not be added to Git.

## 2. Commands executed

The material execution commands were:

```bash
pytest -q tests/test_sec_fundamentals.py
python -m src.data.sec_fundamentals --as-of-date 2026-06-30
/opt/homebrew/bin/python3.11 -m src.data.sec_fundamentals \
  --as-of-date 2026-06-30 --acquire
.venv/bin/python -m py_compile src/data/sec_fundamentals.py
.venv/bin/pytest -q tests/test_sec_fundamentals.py
.venv/bin/pytest
SEC_CONTACT_EMAIL='<operator-provided email>' \
  .venv/bin/python -m src.data.sec_fundamentals \
  --as-of-date 2026-06-30 --acquire
```

The plain `python` command failed immediately because `python` was not on
`PATH`; it did not fetch, parse, or write an audit.

The first acquisition command was already running when this handoff session
was inspected. It completed 497/497 canonical CIK caches and wrote an initial
audit. The final environment-qualified command was a cache-first rerun after
the main audit corrections; it completed successfully and produced the
artifacts timestamped 2026-07-28 11:39:12.

Read-only inspection commands also used `git status`, `git diff`,
`git diff --check`, `rg`, `sed`, `find`, `ps`, `lsof`, and short Pandas scripts
to inspect Parquet/CSV inputs and outputs. No commit, push, branch change,
deletion, or destructive Git command was executed.

The operator email is deliberately redacted here so that a personal contact
address is not committed to a public repository. It was passed only through
the runtime environment.

## 3. Issuers fetched and parsed

- Current S&P 500 proxy snapshot: 503 securities.
- Securities with a valid 12-1 signal at 2026-06-30: 500.
- Excluded for insufficient price history: `FDXF`, `HONA`, and `Q`.
- Mapped securities: 500/500.
- Distinct mapped issuers: 497.
- Company Facts terminal results: 497 available, 0 absent, 0 transient,
  0 unattempted.
- Issuers parsed by the completed audit: 497/497.

The difference between 500 securities and 497 issuers is caused by
GOOG/GOOGL, FOX/FOXA, and NWS/NWSA sharing issuer CIKs.

Membership and sector/industry classifications are current-snapshot proxies,
not production point-in-time history. The completed audit records
`survivorship_bias=true`.

## 4. Current coverage results

Issuer-level coverage at 2026-06-30:

| Stage | Covered | Denominator | Ratio | Status |
|---|---:|---:|---:|---|
| Usable Company Facts filing | 497 | 497 | 100.00% | normal |
| Revenue-growth acceleration | 449 | 497 | 90.34% | normal |
| EPS-growth acceleration | 23 | 497 | 4.63% | insufficient |
| Operating-margin change, full universe denominator | 324 | 497 | 65.19% | degraded |
| Operating-margin change, applicable denominator | 324 | 401 | 80.80% | normal on applicable names |
| Two-of-three composite eligibility | 322 | 497 | 64.79% | degraded |

The corresponding security-level two-of-three count is 324/500.

Current portfolio-leg coverage:

| Leg | Covered | Status | Missing |
|---|---:|---|---|
| Long | 8/10 | normal | `LITE`, `COHR` |
| Short | 7/10 | degraded | `ZTS`, `CSGP`, `FISV` |

Sector-level two-of-three issuer coverage:

| Sector | Covered / eligible | Ratio | Status |
|---|---:|---:|---|
| Basic Materials | 4/5 | 80.00% | normal |
| Consumer Discretionary | 77/101 | 76.24% | degraded |
| Consumer Staples | 11/19 | 57.89% | insufficient |
| Energy | 6/16 | 37.50% | insufficient |
| Finance | 1/68 | 1.47% | insufficient |
| Health Care | 45/54 | 83.33% | normal |
| Industrials | 67/83 | 80.72% | normal |
| Real Estate | 3/28 | 10.71% | insufficient |
| Technology | 66/74 | 89.19% | normal |
| Telecommunications | 8/9 | 88.89% | normal |
| Unclassified | 2/3 | 66.67% | degraded |
| Utilities | 32/37 | 86.49% | normal |

The main feasibility finding is that revenue acceleration is viable, while
the approved quarterly EPS-acceleration construction is not. At security
level, EPS has 24 available, 359 stale, 111 with missing period continuity,
5 missing the approved tags, and 1 missing quarterly periods. Finance and Real
Estate are intentionally not forced through an economically inappropriate
operating-margin calculation, so their two-of-three coverage collapses when
EPS is unavailable.

This supports a degraded, not normal, feasibility conclusion. It does not
authorize Phase 5B.

## 5. Tests already run

Completed test results:

- Initial targeted Phase 5A suite: 16 passed.
- Full repository suite in the project virtual environment:
  201 passed, 4 skipped.
- After the main audit corrections, targeted suite: 16 passed.
- After adding coverage, acquisition-completeness, impossible-period, and
  accounting-category tests: 20 passed.
- `git diff --check`: passed when last run.

One intermediate targeted run failed because a newly added issuer-count helper
expected `cik` in a minimal unit-test fixture. The helper was corrected and
the subsequent targeted runs passed.

Important verification boundary: after the last 20-test pass, one additional
small edit was made to preserve the latest visible quarter provenance when an
acceleration signal fails period continuity. The stop request arrived before
that final edit was retested or used to regenerate outputs.

## 6. Incomplete operations and partially written artifacts

There are no active acquisition or parsing processes and no known truncated
SEC payloads. All 497 payloads have matching metadata sidecars. The completed
audit marks acquisition as complete with zero nonterminal CIKs.

No output is known to be partially written; output writers use atomic writes.
All eight Phase 5A output files are present.

The remaining inconsistency is version alignment:

- the generated artifacts correspond to the completed code state immediately
  before the final provenance-only source edit;
- the current `src/data/sec_fundamentals.py` includes that final untested edit;
- `phase_5a_taxonomy_diagnostics.csv` contains the already generated broad
  taxonomy diagnostic expansion, which was not subsequently simplified;
- the phase review documents contain the approved plan but do not yet contain
  a polished final Phase 5A conclusion beyond this handoff.

No historical fundamental panel, calibration history, breadth module,
production alignment flags, or Fundamental Alignment Scorecard was built.

## 7. Current runnable state

The pre-existing Phase 1-4 pipeline remains runnable and was not coupled to
the Phase 5A audit.

The Phase 5A implementation was runnable at the last completed audit and its
main corrected state passed 20 targeted tests. The working tree as it stands
is not fully re-verified because of the final untested provenance-only edit
described above. It should therefore be treated as a preserved handoff, not
as a commit-ready or production-ready state.

The repository is on `main`, aligned with `origin/main` before these
uncommitted changes. Nothing has been staged, committed, or pushed.

## 8. Minimum cleanup for a consistent working tree

Do not perform this cleanup as part of the stopped handoff. The minimum future
review should:

1. review the final provenance-only edit and either keep it or revert only
   that edit;
2. run `git diff --check` and
   `.venv/bin/pytest -q tests/test_sec_fundamentals.py`;
3. if the edit is kept, run one cache-only Phase 5A audit to align the
   generated CSV/JSON artifacts with the source version;
4. decide whether the broad taxonomy diagnostic output belongs in the bounded
   Phase 5A artifact set or should be reduced;
5. review the full diff and intentionally stage only the approved Phase 5A
   source, tests, documentation, and small audit outputs;
6. keep all raw Company Facts payloads and sidecars ignored.

No cleanup is required to protect or restore the Phase 1-4 pipeline.
