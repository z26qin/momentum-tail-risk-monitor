# WhatsApp alert template

Keep the message short enough to read on a phone. WhatsApp markdown: `*bold*`, no headings. Do not include trading instructions or methodology.

If there is no material change, do **not** use this template. Reply with exactly:

```text
[SILENT]
```

Use **one** severity-band emoji (🟢 🟡 🟠 🔴) in each message. No decorative emojis. Always include the text label and numeric score so meaning does not depend on color.

Copy `monitoring_severity_score`, `score_label`, `severity_emoji`, `primary_driver`, and `mechanism_scores` from the compact JSON. Do not recalculate them.

---

## Score question

User: `What is the current momentum risk score?`

Send **one** message. Fill from JSON. `{severity_emoji}` must match the current band.

```text
{severity_emoji} Momentum monitoring severity: {monitoring_severity_score}/100 — {Score label}
Primary driver: {Primary driver label}
DM recovery: {mechanism_scores.dm_recovery or Not available}
Crowded unwind: {mechanism_scores.crowded_unwind or Not available}
Fundamental repricing: {mechanism_scores.fundamental_repricing or Not available}
Book vulnerability: {mechanism_scores.book_vulnerability or Not available}
Deterministic triggers: {deterministic_trigger_count}/4
This is a relative monitoring score based on prior-only percentiles, not a {monitoring_severity_score}% crash probability.
```

Score labels: `low` → Low, `watch` → Watch, `elevated` → Elevated, `high` → High.

Driver labels: `dm_recovery` → DM recovery, `crowded_unwind` → Crowded unwind, `fundamental_repricing` → Fundamental repricing, `book_vulnerability` → Book vulnerability.

---

## Material-change alert (two messages)

Send **two** consecutive short messages. No extra chatter between them.

### Message 1

```text
{severity_emoji} MOMENTUM RISK — {SCORE LABEL UPPERCASE}
Severity: {monitoring_severity_score}/100
Primary driver: {Primary driver label}
Deterministic triggers: {deterministic_trigger_count}/4
```

### Message 2

```text
What changed:
{one or two sentences from comparison.changes, in PM language}

What argues against escalation:
{contrary book evidence or why_not_act_yet}

Next check:
{one or two monitoring questions from next_checks}

Not a crash probability.
```

---

## Field mapping

| Line | Source |
| --- | --- |
| Emoji / band | `severity_emoji` and `score_label` (🟢 0–39 Low, 🟡 40–59 Watch, 🟠 60–79 Elevated, 🔴 80–100 High) |
| Severity | `monitoring_severity_score` out of 100; not a probability (`score_is_probability` is always false) |
| Primary driver | `primary_driver` |
| Deterministic triggers | `deterministic_trigger_count` out of 4 book scorecard channels |
| What changed | Discrete comparison changes, including a severity-band or primary-driver change; not raw integer drift |
| Against | Untriggered book channels, healthy absorption, or contradicting evidence |
| Next check | `next_checks[0]` (and optionally `[1]`) |

---

## Style checks

- Lead with the JSON score and band. Do not invent a number.
- Include contrary evidence.
- Say what remains unconfirmed.
- Give one or two monitoring questions.
- No trade, hedge, or de-risk orders.
- No long literature review.
- Do not paste JSON, fingerprints, or file paths.
- Do not use a second emoji.

## Approximate filled example

Message 1:

```text
🟠 MOMENTUM RISK — ELEVATED
Severity: 78/100
Primary driver: Crowded unwind
Deterministic triggers: 0/4
```

Message 2:

```text
What changed:
Crowding evidence strengthened, but portfolio-level forced liquidation remains unconfirmed.

What argues against escalation:
Short-leg behavior and drawdown remain below escalation levels.

Next check:
Watch for loser-leg rebound and broader prime-book deleveraging.

Not a crash probability.
```

Fill every line from the actual compact JSON for that run. The 78 / Elevated numbers above are format only, not the frozen 2026-05-29 result.
