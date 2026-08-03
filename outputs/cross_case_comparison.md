# Cross-case comparison

Derived from repository case packs and `run_mvp` outputs. Mechanism labels are descriptive reads, not crash probabilities.

| Question | Current semi case (2026-05-29) | 2020 validation (2020-03-24) | 2024 quiet control (2024-01-05) |
| --- | --- | --- | --- |
| Recovery mechanism (Daniel–Moskowitz) | Partial / watch — recovery text without panic, loser rebound, or short-loss confirmation | Strongly present — `bear_market_recovery_crash` triggered; panic, severe drawdown, high vol, recovery aligned | Not present as a completed setup — recovery precondition only; severe drawdown and high vol unmet |
| Crowded unwind evidence (Khandani–Lo) | Contextual / partially supported — `crowded_theme_unwind` triggered; concentration and mechanical fragility without absorption failure | Secondary / unconfirmed — liquidity facilities ≠ crowded positioning | Limited — crowded-theme scenario not confirmed; mechanical state `NORMAL` |
| Short-leg pressure | Contained on scorecard; risk sits more in long-side crowding | Severe — `short_loss_in_recovery` and beta-gap triggered; short-book reversal on watch | Contained — short-loss, beta-gap, and short-book reversal not triggered |
| Evidence confidence | Mixed — localized crowding supported; broad crash and forced unwind unconfirmed | Historically coherent — mechanism indicators line up with a known reversal episode | Low-risk / quiet — ordinary macro context; no confirmed crash channel |
| PM workflow | Monitor and investigate concentrated / theme exposures | Escalate review of recovery-crash and short-basket channels | Maintain monitoring — escalation not justified |

## How to read the table

1. **Current semi** is the primary live-style product demo: localized crowding pressure without a completed recovery crash.
2. **2020** shows that when a historically important momentum reversal occurred, the recovery-crash indicators behaved coherently.
3. **2024** shows the same rules staying quiet when the mechanism is incomplete.

Sources:

- `outputs/current_semi_unwind/pm_case_read.md`
- `outputs/current_semi_unwind/mechanism_comparison.md`
- `outputs/march_2020_reference/pm_case_read.md`
- `outputs/march_2020_reference/mechanism_comparison.md`
- `outputs/quiet_control_2024/pm_case_read.md`
- `outputs/quiet_control_2024/mechanism_comparison.md`
- `outputs/research_validation/episode_fingerprints.md`
