# Mechanism comparison — March 2020 reference

**Frozen assessment:** 2020-03-24, 16:00 America/New_York  
**Comparison date:** 2020-02-28  
**Interpretation layer:** `deterministic-evidence-interpretation-v2` / prompt `evidence-interpretation-prompt-v2`  
**Scope:** Small historical reference pack. Not a full March 2020 research study.

**Evidence-layer note:** `M20-*` records come from the separately curated,
cutoff-valid historical reference pack. Exact-date classification-cache replay
is unavailable on this date, and the curated text cannot change deterministic
metrics or mechanism states.

| Lens | Structured support | Text support | Missing evidence | Current read |
| --- | --- | --- | --- | --- |
| Daniel–Moskowitz | Market state `panic_elevated`. Severe prior drawdown met (`≈-34%` vs `-20%` gate), high realized volatility met, rapid recovery-from-trough met. `bear_market_recovery_crash` **triggered**. Quant triggers: `high_volatility_recovery`, `short_loss_in_recovery`, `short_minus_long_beta_gap`. `short_book_reversal_crash` is **watch**. Scenario class: `panic_recovery_momentum_crash`. | Fed credit-market support and FOMC-linked actions (`M20-2020-001`); Fed pandemic-hardship package aimed at limiting losses and promoting recovery (`M20-2020-005`). Liquidity/market-functioning facilities are contextual (`M20-2020-002`, `003`, `007`). | No contemporaneous desk report of named loser-leg rebound or short covering in this pack; short-book reversal remains watch rather than triggered. | **supported** (partial on short-book completion) |
| Khandani–Lo | `crowded_theme_unwind` **not_confirmed**. Mechanical state `FRAGILITY_BUILDING` with elevated factor footprint, but aligned turnover not elevated and liquidity-absorption failure false. Portfolio concentration is triggered, but that alone does not establish crowded thematic liquidation. | Dollar swaps, PDCF, and discount-window language show funding/liquidity strain (`M20-2020-002`, `003`, `007`), not crowded positioning. Rising discount-window borrowing (`M20-2020-004`) weakens a forced-quant-deleveraging claim. | No direct crowded ownership, synchronized systematic selling, or forced hedge-fund liquidation evidence in the reused official corpus. | **weak / unconfirmed** |
| Fundamental repricing | Repository fundamental anchor unavailable / not confirmatory for a completed valuation reprice. | Pandemic economic disruption and recovery-oriented policy (`M20-2020-005`); Treasury/IRS tax-day delay under COVID emergency (`M20-2020-006`). | No timestamp-valid earnings-revision or sector-reprice series tied to the PM momentum book. | **partial** (macro shock present; completed reprice not shown) |

## Explicit answers

- **Prior broad-market panic?** Yes in structured outputs (`panic_elevated`; severe drawdown and high volatility conditions met).
- **Broad recovery?** Yes: recovery-from-trough condition met; `high_volatility_recovery` triggered; Fed text on 2020-03-23 targets a swift recovery (`M20-2020-005`).
- **Loser-leg rebound risk visible?** Yes in the book via triggered `short_loss_in_recovery` and beta-gap; structural short-book reversal remains **watch**, and the text pack lacks direct loser-leg journalism.
- **Direct crowding or deleveraging evidence?** No. Liquidity facilities ≠ confirmed crowded unwind (`M20-2020-004` limits that claim).
- **Broader than generic pandemic news?** Yes for DM: panic + recovery + short-leg loss triggers are book/mechanism-specific, not only virus headlines.

## Cross-lens conclusion

March 24, 2020 is primarily a **Daniel–Moskowitz panic-recovery reference**: structured DM channels are active, while KL crowded unwind is not confirmed and fundamental evidence remains a pandemic macro overlay rather than a completed security-level reprice. No probability, causality claim, or trade recommendation is produced.
