# Blockers and scope limits

Updated 2026-07-26.

No blocker prevents the streamlined MVP from running. Two limitations prevent
stronger production or historical-backtest claims.

## B1 — Strict provider exists; archived content corpus does not

The validated fixture corpus was curated after its historical assessment
dates. The code now has a separate strict archive schema and provider, but no
real archive-content corpus is committed. The fixture is not accepted by the
archived provider.

Current handling:

- evidence runs only when the primary DM state is elevated;
- default fixture results remain labeled `illustrative_fixture_replay`;
- archive mode checks publication, discovery, archive availability, and content
  version timestamps against the assessment cutoff;
- missing or empty archive retrieval returns `unavailable` and never falls back
  to fixture data;
- unclassified archive candidates return `retrieved_unclassified` with zero
  directional claims;
- a classifier response must name its model and prompt version, match the exact
  retrieval hash, cover each candidate once, and ground passages in archived
  content;
- missing fixtures produce `unavailable`, never a low-risk interpretation;
- evidence cannot alter the primary probability.

Production resolution: acquire archived article/WARC content with a
deterministic timestamped inventory. GDELT GKG can establish discovery for
2015 onward but does not itself retain original article bodies; 2009 requires
official release archives or another older archive. Keep a separate live
retrieval track for current use.

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
