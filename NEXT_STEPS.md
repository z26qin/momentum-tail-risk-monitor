# Next steps

Updated 2026-07-26 after the streamlined MVP implementation.

## Completed

- One primary risk engine: DM-inspired PIT state plus matured-label
  conditional frequency and severity.
- Unconditional-versus-conditional insurance table for 5- and 20-day horizons.
- Frozen B2 model isolated as a shadow benchmark.
- Earlier reversal checklist isolated as research-only experimental conditions.
- Real FINRA positioning and GDELT narrative panels wired into the assessment.
- Evidence gated on elevated primary state and explicitly labeled as
  illustrative fixture replay.
- Provider-neutral evidence contract plus a strict archived point-in-time
  provider with cutoff, uncertainty, deduplication, and no-fallback gates.
- Versioned classifier-response validation tied to the exact retrieval hash,
  with exact archived-passage grounding before directional claims are emitted.
- One pipeline entry point and generated PM briefs for elevated and quiet dates.
- Default test suite passes; rebuild-only tests skip when raw caches are absent.
- README now describes the active system first; Phase 1/2 instructions are
  retained under `docs/history/`.

## Remaining production-path work

1. Obtain or build the actual archived point-in-time content corpus. The schema,
   provider, and classifier gate now exist, but the repository deliberately
   does not relabel the post-date curated fixture as archive data.
2. Connect a named model invocation that writes the approved response schema
   if operation beyond externally supplied deterministic responses is needed.
   Model/network errors must remain `retrieved_unclassified`.
3. Expand independently reviewed evidence labels beyond the small developer
   review set.
4. Replace the survivorship-biased current equity universe with point-in-time
   constituents.
5. Decide whether production alert governance should use the current
   above-mean-bear-variance operational boundary or a separately approved
   policy threshold. Do not attribute that binary boundary to Daniel and
   Moskowitz.
6. Produce the final memo and presentation from the generated PM briefs.

Implementation and corpus acquisition are deliberately separate. GDELT 2.0
provides a timestamped discovery inventory only from 2015 onward and its GKG
metadata does not preserve the original article body. A strict content track
therefore still needs archived page/WARC bytes; the 2009 episode needs official
release archives or another source predating GDELT 2.0.

## Do not reintroduce

- Multiple competing fields named `risk_probability`.
- Overlay-driven probability adjustments.
- A heuristic threshold presented as a literature result.
- Historical text retrieval from a live present-day index.
- Tone or narrative breadth claims while those columns remain unavailable.
