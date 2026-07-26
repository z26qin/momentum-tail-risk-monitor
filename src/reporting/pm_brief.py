"""Render one concise PM brief from a complete MVP assessment."""

from __future__ import annotations

from src.mvp.contracts import MvpAssessment


def _pct(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.1%}"


def _number(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:+.2f}"


def _shadow_line(assessment: MvpAssessment) -> str:
    shadow = assessment.shadow_benchmarks[0]
    if shadow.status == "unavailable":
        return "B2 shadow: unavailable for this date."
    agreement = "agrees" if shadow.agrees_with_primary else "disagrees"
    return (
        f"B2 shadow: {_pct(shadow.shadow_probability)} "
        f"({shadow.shadow_percentile:.1%} split percentile), {agreement} "
        "with the primary elevated/not-elevated classification."
    )


def _evidence_lines(assessment: MvpAssessment) -> list[str]:
    evidence = assessment.evidence
    lines = [
        f"Evidence status: `{evidence.status}`; {evidence.detail}",
    ]
    for item in evidence.citations:
        lines.append(
            "- "
            f"**{item['classification']} — {item['mechanism']}**: "
            f"[{item['source']}, {item['title']}]({item['citation_url']}) "
            f"({item['publication_timestamp']}). "
            f"Grounded passage: “{item['extracted_passage']}”"
        )
    return lines


def render_pm_brief(assessment: MvpAssessment) -> str:
    """Return deterministic Markdown suitable for daily PM review."""

    primary = assessment.primary
    positioning = assessment.positioning
    narrative = assessment.narrative
    experimental = assessment.experimental_conditions
    invalidation = (
        "The assessment would de-escalate if the trailing market return leaves "
        "the bear state or 126-day variance falls below its PIT bear-state "
        "reference mean."
        if primary.elevated
        else "The assessment would escalate if the trailing 24-month market "
        "return turns negative while 126-day variance rises above its PIT "
        "bear-state reference mean."
    )
    lines = [
        f"# Momentum tail-risk brief — {primary.as_of_date}",
        "",
        "## Primary assessment",
        "",
        f"- Horizon: {primary.horizon_days} trading days",
        f"- State: **{primary.state}**",
        (
            "- PIT conditional tail-loss probability: "
            f"**{_pct(primary.tail_loss_probability)}** "
            f"(n={primary.conditioning_sample_size:,})"
        ),
        (
            "- Unconditional comparison: "
            f"{_pct(primary.unconditional_tail_loss_probability)} "
            f"(n={primary.unconditional_sample_size:,})"
        ),
        (
            "- Conditional forward-return severity: "
            f"mean {_pct(primary.conditional_mean_forward_return)}, "
            f"5th percentile {_pct(primary.conditional_fifth_percentile)}"
        ),
        (
            "- Market state: trailing 504-day return "
            f"{_pct(primary.market_return_504d)}; panic intensity "
            f"{_number(primary.panic_intensity)}"
        ),
        "",
        "## Independent views",
        "",
        f"- {_shadow_line(assessment)}",
        (
            "- Experimental reversal checklist: "
            f"`{experimental.status}`; triggered "
            f"{len(experimental.triggered_conditions)}/{experimental.total_conditions}."
        ),
        (
            "- FINRA positioning overlay: "
            f"`{positioning.read}`; short-interest ratio z "
            f"{_number(positioning.short_interest_ratio_z)}, utilisation z "
            f"{_number(positioning.short_interest_utilisation_z)}, short-volume "
            f"share z {_number(positioning.short_volume_share_z)}."
        ),
        (
            "- GDELT narrative overlay: "
            f"`{narrative.read}`; panic z {_number(narrative.panic_volume_z)}, "
            f"crowding z {_number(narrative.crowding_volume_z)}, risk-off z "
            f"{_number(narrative.riskoff_volume_z)}."
        ),
        "",
        "## Evidence",
        "",
        *_evidence_lines(assessment),
        "",
        "## What would change this assessment",
        "",
        invalidation,
        "",
        "## Required human review",
        "",
        "- Review primary/shadow disagreements rather than averaging the numbers.",
        "- Treat overlay contradictions as investigation prompts, not probability adjustments.",
        "- Evidence is illustrative fixture replay unless a production archive is explicitly configured.",
        "",
        "_Research prototype; not an investment recommendation._",
        "",
    ]
    return "\n".join(lines)

