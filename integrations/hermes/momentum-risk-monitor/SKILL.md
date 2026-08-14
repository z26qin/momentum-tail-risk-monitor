---
name: momentum-risk-monitor
description: Run the repository's deterministic momentum tail-risk monitor, compare it with the previous assessment, return [SILENT] when nothing material changed, and otherwise investigate timestamp-valid evidence and send a concise PM-facing WhatsApp alert. Use for monitor runs, cron, score questions such as "What is the current momentum risk score?", and follow-ups such as "Why is this not a Khandani–Lo unwind?"
version: 1.2.0
metadata:
  hermes:
    tags: [momentum, risk, whatsapp, monitor]
    category: research
    requires_toolsets: [terminal]
---

# Momentum tail-risk monitor

Deterministic calculations in this repository are the authority for risk state, triggers, structural flags, and the 0–100 monitoring severity score. You may investigate, explain, challenge a hypothesis, preserve context, and communicate. You must not calculate or override deterministic triggers, invent or recalculate the monitoring score, invent a crash probability, or issue a trade recommendation.

Run every command from the **momentum-tail-risk-monitor repository root**. If the working directory is unknown, ask once, then reuse it.

## When to use

- A user or cron job asks to run the momentum risk monitor.
- WhatsApp questions about the current momentum risk score.
- WhatsApp follow-ups about the latest assessment (mechanism, evidence, why not unwind).
- Weekday monitoring after the 16:00 ET cutoff.

## Procedure

1. Run the existing monitor CLI (offline, `use_llm=False` inside the adapter):

   ```bash
   python scripts/run_monitor.py \
     --as-of-date 2026-05-29 \
     --evidence-cutoff "2026-05-29 16:00 ET" \
     --output-json outputs/latest_assessment.json
   ```

   For a live dated run, pass the configured assessment date instead of the frozen demo date. Do not change thresholds or data sources.

2. Read `outputs/latest_assessment.json`. Core fields come from `run_mvp()` plus a PM-facing score overlay: `overall_risk_state` (UMD/DM comparison only), `pm_posture` / `risk_state`, `deterministic_trigger_count`, `triggered_channels`, `structural_flags`, `mechanism_statuses`, `book_read`, `monitoring_severity_score`, `score_label`, `severity_emoji`, `primary_driver`, `mechanism_scores`, `score_is_probability`, evidence IDs.

3. Compare with the previous assessment:

   ```bash
   python scripts/compare_monitor_state.py \
     --current outputs/latest_assessment.json \
     --previous runtime_state/previous_assessment.json \
     --output-json outputs/latest_comparison.json
   ```

4. If the comparison stdout is exactly `[SILENT]`, or `material_change` is false (including the initial baseline), **respond with exactly** `[SILENT]`. Do not send a state-change alert because a baseline was created. Integer score drift inside the same band is not an alert.

5. Investigate evidence only when there is a material change **or** the user explicitly asks for an explanation. Follow [investigation_policy.md](investigation_policy.md). Use only timestamp-valid evidence available by `evidence_cutoff` / `data_cutoff`. Prefer:

   - retrieved items already in the compact JSON;
   - the repository evidence pipeline (`outputs/evidence_cache/`, `data/corpus/`);
   - the frozen case pack pointed to by `frozen_case_pack` (for 2026-05-29: `outputs/current_semi_unwind/` and `data/evaluation/current_semi_unwind/`).

6. Separate supporting evidence, contradicting evidence, and missing confirmation. Map to Daniel–Moskowitz, Khandani–Lo, or fundamental repricing only when the supplied evidence justifies it. Label each claim `observed`, `inferred`, or `not confirmed`.

7. If a material change requires an alert, write only the concise PM-facing messages in [alert_template.md](alert_template.md). Lead with the JSON score. Do not attach the full JSON.

## Score (do not recalculate)

`monitoring_severity_score` is a PM-facing summary of prior-only percentiles. It is **not** a crash probability and **not** a replacement for mechanism-level analysis. `score_is_probability` is always false.

Copy the number from JSON. Do not average, re-rank, override, or invent a score. If a mechanism is `null`, say **Not available** and use `unavailable_mechanism_reasons`. Do not impute.

Bands (emoji is presentation-only; always also send the text label and number):

- 🟢 0–39 Low
- 🟡 40–59 Watch
- 🟠 60–79 Elevated
- 🔴 80–100 High

Use only that one severity emoji. No decorative emojis.

## Follow-up questions

A PM is reading this on a phone. Answer first, then at most five supporting lines. Do not write a research memo.

### What is the current momentum risk score?

If `outputs/latest_assessment.json` is missing, run `scripts/run_monitor.py` silently first. Then send only this card. Fill every number from JSON. The opening emoji must be `severity_emoji`.

```text
{severity_emoji} Momentum monitoring severity: {monitoring_severity_score}/100 — {Score label}
Primary driver: {Primary driver label}
DM recovery: {dm_recovery or Not available}
Crowded unwind: {crowded_unwind or Not available}
Fundamental repricing: {fundamental_repricing or Not available}
Book vulnerability: {book_vulnerability or Not available}
Deterministic triggers: {deterministic_trigger_count}/4
This is a relative monitoring score based on prior-only percentiles, not a {monitoring_severity_score}% crash probability.
```

Driver labels: `dm_recovery` → DM recovery; `crowded_unwind` → Crowded unwind; `fundamental_repricing` → Fundamental repricing; `book_vulnerability` → Book vulnerability.

### Why is the score {N}?

Do not recompute. Name `primary_driver`, then the input in `mechanism_score_components` that matches that mechanism's max percentile. Quote the actual current value and threshold from those components or from `book_read` / `mechanism_statuses`. Mention `deterministic_trigger_count` so the score is not confused with 0/4 triggers.

Shape:

```text
The {N} headline is the max of available mechanism scores. {Primary driver} is {N} because {input name} is at the {percentile}rd prior-only percentile (current {value} vs {threshold}). Other channels: DM recovery {x}; fundamental {Not available or n}; book {y}. Deterministic book triggers remain {n}/4. Not a crash probability.
```

### Is {N} the probability of a crash?

```text
No. {N} is a relative monitoring score from prior-only percentiles, not a {N}% crash probability. score_is_probability is false. Deterministic book triggers are {deterministic_trigger_count}/4.
```

### Which mechanism is driving the score?

```text
{Primary driver label} (`primary_driver`). Headline {N} equals that mechanism's score. The other available mechanism scores are lower or not available.
```

### What would move the score higher?

Name the actual inputs on the primary driver from `mechanism_score_components` (and the unused DM recovery-from-trough gate if asked about DM). Do not invent a new model.

```text
The headline rises only if a mechanism score rises. {Primary driver} is the max of its prior-only input percentiles. It would move higher if {input} becomes more extreme versus its own prior history (example: cluster residual loss vs its prior 80th percentile, or turnover vs its prior distribution). Crossing a deterministic trigger is a separate 0/4 readout.
```

If the user asks `Why is this not a Khandani–Lo unwind?`, copy this shape. Fill `{cluster}` from `theme_cluster`. Fill `book n/4` from **`deterministic_trigger_count` only** (how many of the 4 book scorecard channels are *triggered*). On the 2026-05-29 frozen case that integer is **0**, so write **book 0/4**. Empty `triggered_channels` means 0. Never use the count of metrics, mechanisms, evidence items, or scorecard rows as `n`.

```text
Not a confirmed Khandani–Lo unwind.

Observed: CIEN–COHR–LITE crowding; crowded_theme_unwind triggered; book 0/4.
Inferred: localized theme pressure, not a system-wide unwind.
Against: absorption still works; no factor-wide footprint; no short-leg squeeze.
Not confirmed: forced deleveraging / financing stress.
State unchanged: Escalate for review.
Next: watch absorption failure or selling outside the cluster.
```

If `outputs/latest_assessment.json` is missing, run `scripts/run_monitor.py` silently, then send only those seven lines. Do not tell the user the file was missing, that you are checking README, or that the monitor is running.

Do not rerun the monitor if that JSON already exists, unless the user asks for a fresh date. Never change `risk_state`, triggers, flags, or the monitoring score.

On follow-ups, read only `outputs/latest_assessment.json`. Do not open `src/`, `pm_case_read.md`, evidence packs, or positioning modules unless the user says "show the detail".

## WhatsApp delivery

Score card: **one** final message.

Material-change alert: **two** consecutive messages from [alert_template.md](alert_template.md), then stop.

Hard cap per message: **10 lines** and **~700 characters**. If a draft is longer, cut it before sending.

Never send:

- recap of tools or "what I pulled"
- progress chatter ("file is missing", "let me check", "monitor ran")
- `read_file` / `execute_code` / paths / JSON
- wiki names, R², z-scores, threshold tables, ticker laundry lists
- "it IS the KL channel" — say **not confirmed** first
- Self-improvement / skill-created notices
- **book 4/4** unless `deterministic_trigger_count` is actually 4
- extra emojis beyond the single severity-band emoji
- a homemade score that is not in the JSON

Do not create, edit, or “improve” skills during a WhatsApp session.

## Hard rules

- Never change the deterministic risk state.
- Never recalculate, override, or invent `monitoring_severity_score`.
- Never treat the score as a crash probability.
- Never issue an autonomous trade recommendation or execution instruction.
- Never invent ownership, leverage, financing stress, or forced deleveraging.
- Never use evidence later than the assessment cutoff.
- Never behave as a generic news summarizer.
- If cached processed data are missing, report the CLI error and stop.

## Verification

- CLI exits 0 and writes valid JSON with `schema_version: hermes-monitor-v1` including `monitoring_severity_score` and `score_is_probability: false`.
- A second unchanged compare prints `[SILENT]`.
- Alerts fit a phone screen, use one severity emoji, and include contrary evidence plus a next check.
