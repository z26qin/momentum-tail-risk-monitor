---
name: momentum-risk-monitor
description: Run the repository's deterministic momentum tail-risk monitor, compare it with the previous assessment, return [SILENT] when nothing material changed, and otherwise investigate timestamp-valid evidence and send a concise PM-facing WhatsApp alert. Use for monitor runs, cron, and follow-ups such as "Why is this not a Khandani–Lo unwind?"
version: 1.1.0
metadata:
  hermes:
    tags: [momentum, risk, whatsapp, monitor]
    category: research
    requires_toolsets: [terminal]
---

# Momentum tail-risk monitor

Deterministic calculations in this repository are the authority for risk state, triggers, and structural flags. You may investigate, explain, challenge a hypothesis, preserve context, and communicate. You must not calculate or override deterministic triggers, invent a crash probability, or issue a trade recommendation.

Run every command from the **momentum-tail-risk-monitor repository root**. If the working directory is unknown, ask once, then reuse it.

## When to use

- A user or cron job asks to run the momentum risk monitor.
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

2. Read `outputs/latest_assessment.json`. Core fields come from `run_mvp()`: `overall_risk_state` (UMD/DM comparison only), `pm_posture` / `risk_state`, `deterministic_trigger_count`, `triggered_channels`, `structural_flags`, `mechanism_statuses`, `book_read`, evidence IDs.

3. Compare with the previous assessment:

   ```bash
   python scripts/compare_monitor_state.py \
     --current outputs/latest_assessment.json \
     --previous runtime_state/previous_assessment.json \
     --output-json outputs/latest_comparison.json
   ```

4. If the comparison stdout is exactly `[SILENT]`, or `material_change` is false (including the initial baseline), **respond with exactly** `[SILENT]`. Do not send a state-change alert because a baseline was created.

5. Investigate evidence only when there is a material change **or** the user explicitly asks for an explanation. Follow [investigation_policy.md](investigation_policy.md). Use only timestamp-valid evidence available by `evidence_cutoff` / `data_cutoff`. Prefer:

   - retrieved items already in the compact JSON;
   - the repository evidence pipeline (`outputs/evidence_cache/`, `data/corpus/`);
   - the frozen case pack pointed to by `frozen_case_pack` (for 2026-05-29: `outputs/current_semi_unwind/` and `data/evaluation/current_semi_unwind/`).

6. Separate supporting evidence, contradicting evidence, and missing confirmation. Map to Daniel–Moskowitz, Khandani–Lo, or fundamental repricing only when the supplied evidence justifies it. Label each claim `observed`, `inferred`, or `not confirmed`.

7. If a material change requires an alert, write only the concise PM-facing message in [alert_template.md](alert_template.md). Lead with the deterministic state. Do not attach the full JSON.

## Follow-up questions

A PM is reading this on a phone. Answer first, then at most five supporting lines. Do not write a research memo.

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

Do not rerun the monitor if that JSON already exists, unless the user asks for a fresh date. Never change `risk_state`, triggers, or flags.

On follow-ups, read only `outputs/latest_assessment.json`. Do not open `src/`, `pm_case_read.md`, evidence packs, or positioning modules unless the user says "show the detail".

## WhatsApp delivery

Send **one** final message. Hard cap: **8 lines** and **~700 characters**. If a draft is longer, cut it before sending.

Never send:

- recap of tools or "what I pulled"
- progress chatter ("file is missing", "let me check", "monitor ran")
- `read_file` / `execute_code` / paths / JSON
- wiki names, R², z-scores, threshold tables, ticker laundry lists
- "it IS the KL channel" — say **not confirmed** first
- Self-improvement / skill-created notices
- **book 4/4** unless `deterministic_trigger_count` is actually 4

Do not create, edit, or “improve” skills during a WhatsApp session.

## Hard rules

- Never change the deterministic risk state.
- Never issue an autonomous trade recommendation or execution instruction.
- Never invent ownership, leverage, financing stress, or forced deleveraging.
- Never use evidence later than the assessment cutoff.
- Never behave as a generic news summarizer.
- If cached processed data are missing, report the CLI error and stop.

## Verification

- CLI exits 0 and writes valid JSON with `schema_version: hermes-monitor-v1`.
- A second unchanged compare prints `[SILENT]`.
- Alerts fit a phone screen and include contrary evidence plus a next check.
