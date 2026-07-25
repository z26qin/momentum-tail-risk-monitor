# Blockers

One blocker, **downgraded**. It no longer prevents a deliverable; it limits
scope.

---

## B1 — GDELT DOC 2.0 API applied a sustained IP block

**Status: still in force, but worked around.** Verified 2026-07-25: HTTP 429
after roughly ten hours of near-silence at one request per five minutes.

**Effect on the deliverable — revised.** The narrative panel **now exists**,
built entirely from already-cached payloads with **zero further API calls**. See
`outputs/narrative_poc_review.md`. What the block costs is *scope*, not
existence:

| Missing | Requests needed |
|---|---:|
| `crowding` mechanism — the direct narrative counterpart of the positioning panel | 3 |
| Tone series (needs `timelinetone` + `timelinevolraw` for the weights) | 2 per query |
| `rotation`, `policy` mechanisms, and `narrative_breadth` | 3 each |
| Semantic sanity check / query precision flags | 4 |

**Two verified substitutions made the workaround sound**, rather than
convenient:

1. Volume intensity for `riskoff` is derived from `timelinevolraw` as
   `100 × value / norm`. Verified arithmetically against the API — the two modes
   are equivalent.
2. Archive availability uses a spare `timelinevolraw`'s `norm` instead of the
   dedicated coverage series. Verified directly: two entirely different queries
   returned byte-identical `norm` on all 366 overlapping days of 2020.

### Characterisation of the block

Worth carrying forward, because it dictates how to work with this API.

1. **Stateful and sticky.** Requests spaced 20 seconds apart — four times
   GDELT's own stated interval — were still refused.
2. **Retrying prolongs it.** The first driver retried with exponential backoff
   and kept the penalty continuously re-triggered for ~25 minutes. This was the
   single most costly mistake of the session.
3. **Going silent can clear it.** The first block lifted after one five-minute
   silence, which bought 16 usable requests.
4. **The second block did not.** After a five-request diagnostic burst it
   returned and survived ten consecutive probes at 1/60th of the stated
   allowance, then a further ~8 hours. This is an hours-to-days IP ban keyed to
   cumulative session volume.

**Deliberately not tried:** changing the User-Agent or otherwise disguising the
client. That would circumvent an access control the provider applied on
purpose — GDELT's own 429 body directs high-traffic users to its ngrams dataset
or to contacting the maintainer. The block was respected.

### What is not blocked

- The **positioning panel** is complete and never depended on GDELT.
- The **narrative pipeline** is complete and tested: mapping, tone weighting,
  confirmed-zero versus archive-gap disambiguation, PIT z-scores.
- 106 tests pass; the single remaining skip is the tone-dependent assertion.

### Correct usage from here

`acquire_timelines` is now fail-fast and resumable: one attempt per request,
stops on the first refusal, never caches a refusal. **Do not loop it.**

```bash
uv run python -m src.data.gdelt --queries crowding
```

Re-run occasionally; each attempt costs seconds and keeps whatever it wins.
