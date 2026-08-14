# WhatsApp alert template

Keep the message short enough to read on a phone. WhatsApp markdown: `*bold*`, no headings. Do not include trading instructions or methodology.

If there is no material change, do **not** use this template. Reply with exactly:

```text
[SILENT]
```

## Template

```text
MOMENTUM RISK — STATE CHANGE
As of: {evidence_cutoff}

State: {short posture from pm_posture}
Book triggers: {deterministic_trigger_count}/4
New flag: {new or leading structural flag}

What changed:
{one or two sentences from comparison.changes, in PM language}

Against the hypothesis:
{contrary book evidence or why_not_act_yet}

Next check:
{one monitoring question from next_checks}
```

## Field mapping

| Line | Source |
| --- | --- |
| State | Short label of `pm_posture` / `risk_state` (`Monitor`, `Investigate`, `Escalate for review`). UMD/DM `overall_risk_state` is comparison context only — do not present it as the PM-book state. |
| Book triggers | `deterministic_trigger_count` out of 4 scorecard channels |
| New flag | First added `structural_flags` item; for `crowded_theme_unwind` you may say technology concentration and name `theme_cluster` |
| What changed | Discrete comparison changes, not raw numeric drift |
| Against | Untriggered book channels, healthy absorption, or contradicting evidence |
| Next check | `next_checks[0]` (and optionally `[1]`) |

## Style checks

- Lead with the deterministic state.
- Include contrary evidence.
- Say what remains unconfirmed.
- Give one or two monitoring questions.
- No trade, hedge, or de-risk orders.
- No long literature review.
- Do not paste JSON, fingerprints, or file paths.

## Approximate length target

```text
MOMENTUM RISK — STATE CHANGE
As of: 2026-05-29 16:00 ET

State: Monitor
Book triggers: 0/4
New flag: Technology concentration

What changed:
Crowding evidence strengthened, but portfolio-level forced liquidation remains unconfirmed.

Against the hypothesis:
Short-leg behavior and drawdown remain below escalation levels.

Next check:
Watch for loser-leg rebound and broader prime-book deleveraging.
```

Fill every line from the actual compact JSON for that run. If `pm_posture` is `escalate_for_pm_review`, say `Escalate for review` rather than forcing the word Monitor.
