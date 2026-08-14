---
name: momentum-risk-monitor
description: Run the repository's deterministic momentum tail-risk monitor, compare it with the previous assessment, return [SILENT] when nothing material changed, and otherwise investigate timestamp-valid evidence and send a concise PM-facing WhatsApp alert. Use for monitor runs, cron, and follow-ups such as "Why is this not a Khandani–Lo unwind?"
version: 1.0.0
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

Preserve the latest assessment as context. If the user asks `Why is this not a Khandani–Lo unwind?`, challenge the crowded-unwind hypothesis with the investigation policy. Do not rerun numbers unless the user asks for a fresh date. Never change `risk_state`, triggers, or flags in your reply.

On follow-ups, read only:

- `outputs/latest_assessment.json`
- `outputs/latest_comparison.json` if present
- `outputs/current_semi_unwind/pm_case_read.md` when `as_of_date` is `2026-05-29`

Do **not** search `src/`, open Python modules, or re-derive thresholds from code. The compact JSON already contains the authoritative states.

## WhatsApp delivery

Send **one** final user-visible message. Do not narrate tool use. Do not paste:

- `read_file` / `search_files` / `execute_code` / paths
- Python snippets
- JSON dumps
- “Self-improvement review” or skill-created notices

Keep follow-ups under ~12 short lines so WhatsApp does not truncate. Use the six-step investigation pattern, compressed:

```text
Observed: …
Inferred: …
Against: …
Not confirmed: …
State unchanged: …
Next: …
```

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
