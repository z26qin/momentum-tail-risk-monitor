# WhatsApp alert template

Keep the message short enough to read on a phone. WhatsApp markdown: `*bold*`, no headings. Do not include trading instructions or methodology.

The daily brief CLI (`scripts/run_daily_brief.py`) already prints `[SILENT]`, the two-message alert, or a stale-data notice. On run/cron, send that stdout as-is. Stale panels are not `[SILENT]`.

If there is no material change, do **not** use this template. Reply with exactly:

```text
[SILENT]
```

Use the 🟢 🟡 🟠 🔴 band emoji next to **every 0–100 score**, including the headline and each mechanism number. Do not add decorative emojis. `Not available` lines and `Deterministic Macro State Change triggers: n/4` have no score, so they get no band emoji. Always include the text label and numeric score so meaning does not depend on color.

Copy `monitoring_severity_score`, `score_label`, `severity_emoji`, `primary_driver`, and `mechanism_scores` from the compact JSON. Do not recalculate them.

---

## Score question

User: `What is the current momentum risk score?`

Send **one** message. Fill from JSON. `{severity_emoji}` must match the current band.

```text
{severity_emoji} Momentum monitoring severity: {monitoring_severity_score}/100 — {Score label}
As of: {as_of_date}
Primary driver: {Primary driver label}
DM recovery: {band emoji} {mechanism_scores.dm_recovery}
Crowded unwind: {band emoji} {mechanism_scores.crowded_unwind}
Fundamental repricing: Not available
Book vulnerability: {band emoji} {mechanism_scores.book_vulnerability}
Deterministic Macro State Change triggers: {deterministic_trigger_count}/4
This is a relative monitoring score based on prior-only percentiles, not a {monitoring_severity_score}% crash probability.
```

Put each mechanism's own band emoji immediately before its number (`🟢 25`, `🟡 55`, `🟠 78`, `🔴 96`). If that mechanism is null, write `Not available` with no emoji.

Filled score-card example (numbers are format only):

```text
🟠 Momentum monitoring severity: 78/100 — Elevated
As of: 2026-05-29
Primary driver: Crowded unwind
DM recovery: 🟢 25
Crowded unwind: 🟠 78
Fundamental repricing: Not available
Book vulnerability: 🟡 55
Deterministic Macro State Change triggers: 0/4
This is a relative monitoring score based on prior-only percentiles, not a 78% crash probability.
```

Score labels: `low` → Low, `watch` → Watch, `elevated` → Elevated, `high` → High.

Driver labels: `dm_recovery` → DM recovery, `crowded_unwind` → Crowded unwind, `fundamental_repricing` → Fundamental repricing, `book_vulnerability` → Book vulnerability.

---

## Material-change alert (two messages)

Send **two** consecutive short messages. No extra chatter between them.

### Message 1

```text
{severity_emoji} MOMENTUM RISK — {SCORE LABEL UPPERCASE}
As of: {as_of_date}
Severity: {severity_emoji} {monitoring_severity_score}/100
Primary driver: {Primary driver label}
Deterministic Macro State Change triggers: {deterministic_trigger_count}/4
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
| As of | `as_of_date` — never omit; never call it today's close unless it is |
| Severity | `monitoring_severity_score` out of 100; not a probability (`score_is_probability` is always false) |
| Primary driver | `primary_driver` |
| Deterministic Macro State Change triggers | `deterministic_trigger_count` out of 4 book scorecard channels |
| What changed | Discrete comparison changes, including a severity-band or primary-driver change; not raw integer drift |
| Against | Untriggered book channels, healthy absorption, or contradicting evidence |
| Next check | `next_checks[0]` (and optionally `[1]`) |

---

## Style checks

- Lead with the JSON score, band, and `as_of_date`. Do not invent a number.
- Include contrary evidence.
- Say what remains unconfirmed.
- Give one or two monitoring questions.
- No trade, hedge, or de-risk orders.
- No long literature review.
- Do not paste JSON, fingerprints, or file paths.
- Band emojis only next to 0–100 scores; no decorative emojis.

## Approximate filled example

Message 1:

```text
🟠 MOMENTUM RISK — ELEVATED
As of: 2026-05-29
Severity: 🟠 78/100
Primary driver: Crowded unwind
Deterministic Macro State Change triggers: 0/4
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
