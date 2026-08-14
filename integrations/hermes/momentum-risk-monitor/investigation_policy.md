# Investigation policy

The deterministic layer remains the authority. This policy governs how Hermes reads timestamp-valid evidence around that layer. It does not create a second risk score.

## Reasoning pattern

Use this sequence every time you investigate. Do not skip the contrary or missing steps.

```text
Initial hypothesis
→ Evidence supporting it
→ Evidence contradicting it
→ Missing confirmation
→ Updated interpretation
→ Next observable check
```

## How to form the initial hypothesis

Start from the compact JSON, not from headlines.

- If `crowded_theme_unwind` is in `structural_flags` or `supported_mechanisms`, the initial hypothesis is localized crowding / correlated-theme pressure in the long book.
- If `bear_market_recovery_crash` or `short_book_reversal_crash` is triggered, the initial hypothesis is a Daniel–Moskowitz recovery crash (loser rebound hurting the short leg).
- If only `overall_risk_state` is soft and book triggers are zero, the initial hypothesis is ordinary monitoring, not an unwind.
- Do not promote a Prime Book or news item into the hypothesis until the deterministic flags exist.

## Evidence classes (keep them separate)

| Class | What it can support | What it cannot prove |
| --- | --- | --- |
| Observed book structure | Concentration, cluster, scorecard triggers | Ownership, leverage, forced selling |
| Public positioning proxies | Crowding is *plausible* | Hedge-fund identity, covering, financing |
| Reported prime-book / flow commentary | Localized exposure reduction as *inferred* context | System-wide deleveraging |
| Market footprint | Turnover, absorption, factor alignment | Causality |
| Company operating results | Fundamental or sector repricing lens | A momentum crash |

Label every material claim:

- **observed** — in the JSON or a cutoff-valid evidence record;
- **inferred** — a bounded reading of observed facts;
- **not confirmed** — still missing.

## Mechanism mapping

Map evidence to a literature lens only when justified by the supplied items:

1. **Daniel–Moskowitz market recovery** — needs panic/drawdown context, loser-leg rebound, and short-leg loss. Untriggered `short_loss_in_recovery` / `high_volatility_recovery` means this sequence is **not confirmed**.
2. **Khandani–Lo crowded unwind** — needs concentration plus correlated selling, weak absorption, and positioning evidence that lines up. A single prime-book technology reduction is **not** a confirmed system-wide unwind.
3. **Fundamental repricing** — needs completed valuation/earnings revision in the names that are actually in the book. Strong operating prints **contradict** a broad deterioration story.

Contextual items may be discussed. They cannot be treated as stance-confirmed support unless the compact JSON lists them under `supporting_evidence_ids`.

## Timestamp rule

Use only evidence with publication timestamp ≤ `data_cutoff` (US close on `as_of_date`). If an item is later, drop it. Prefer IDs already returned by the repository pipeline.

For the frozen 2026-05-29 case, also read `outputs/current_semi_unwind/pm_case_read.md` and `data/evaluation/current_semi_unwind/candidate_evidence.json` when those paths exist. They are cutoff-valid curated packs. They still cannot rewrite triggers.

## Output of an investigation

Write the six-step pattern in short PM language, then (if this is an alert) compress it into the WhatsApp template. Example *style* for a crowded-theme monitor day — derive the actual sentences from the JSON and evidence; do not paste this paragraph as a canned answer:

```text
Initial hypothesis:
The move may reflect a crowded technology unwind.

Supporting:
Evidence indicates an unusually large reduction in hedge-fund technology exposure.

Against:
The portfolio drawdown, short-leg behavior, and beta structure do not confirm broad forced liquidation.

Missing:
There is no verified evidence of system-wide deleveraging.

Interpretation:
Localized crowding is supported; a broad Khandani–Lo-style unwind is not confirmed.

Next check:
Watch for a loser-leg rebound, wider prime-book deleveraging, and deterioration across multiple clusters.
```

## Follow-up: “Why is this not a Khandani–Lo unwind?”

Answer the question. Do not rerun the monitor unless asked.

1. Restate what *is* observed (cluster, structural flag, any prime-book item).
2. State what a Khandani–Lo confirmation would require (breadth, absorption failure, financing/forced selling).
3. Show which of those are missing in the current JSON.
4. Keep the deterministic state unchanged.

## Prohibited behavior

- Generic news roundup.
- Recalculating drawdown, beta, or triggers.
- Overriding `risk_state` / `pm_posture`.
- Trade, hedge, or de-gross instructions.
- Claiming forced deleveraging without direct evidence.
