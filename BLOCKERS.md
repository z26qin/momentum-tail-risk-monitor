# Blockers and scope limits

Updated 2026-07-26.

No blocker prevents the streamlined MVP from running. Two limitations prevent
stronger production or historical-backtest claims.

## B1 — Historical text selection is illustrative

The validated evidence corpus was curated after its historical assessment
dates. Publication cutoffs and passage grounding are enforced, but document
selection itself is not a strict point-in-time archive.

Current handling:

- evidence runs only when the primary DM state is elevated;
- every result is labeled `illustrative_fixture_replay`;
- missing fixtures produce `unavailable`, never a low-risk interpretation;
- evidence cannot alter the primary probability.

Production resolution: archived GDELT GKG or another timestamped historical
corpus for backtests, plus a separate live retrieval track for current use.

## B2 — GDELT panel is partial

The processed narrative panel exists and is consumed by the MVP. It currently
contains volume intensity for three mechanisms:

- `panic`
- `crowding`
- `riskoff`

Tone is unavailable and five-mechanism narrative breadth is undefined. Large
raw GDELT payloads are not committed, so a fresh clone can read the processed
panel but cannot rebuild it without reacquisition. Rebuild-only tests therefore
skip when those payloads are absent.

This limits scope but does not block daily assessment generation.
