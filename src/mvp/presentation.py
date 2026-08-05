"""Presentation helpers for the PM-facing MVP demo.

Quantitative values are passed through unchanged from ``MVPRunResult``. This
module formats, charts, and exports them for notebook and file output.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.figure import Figure

from src.monitoring.unwind_monitor import MechanicalUnwindAssessment
from src.monitoring.unwind_structure import UnwindAssessment
from src.mvp.crowding_context import (
    build_narrative_snapshot,
    build_positioning_snapshot,
)
from src.mvp.evidence_card import (
    DeterministicEvidenceInput,
    QuantSignal,
    RetrievedEvidence,
)
from src.mvp.pipeline import MVPRunResult
from src.regime.market_state import (
    EARLY_RECOVERY_MAX_AGE,
    RECOVERY_FROM_TROUGH_THRESHOLD,
    SEVERE_DRAWDOWN_THRESHOLD,
    build_regime_history,
)
from src.utils.io import REPO_ROOT


def _fmt(value: float | None, *, signed: bool = False) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:+.4f}" if signed else f"{value:.4f}"


def _list_html(values: tuple[str, ...] | list[str], empty_text: str) -> str:
    return "".join(f"<li>{escape(value)}</li>" for value in values) or (
        f"<li>{escape(empty_text)}</li>"
    )


def build_macro_component_html(
    card: DeterministicEvidenceInput,
    *,
    processed_dir: Path | None = None,
) -> tuple[str, float, bool]:
    """Return macro recovery component HTML and summary flags."""

    root = processed_dir or (REPO_ROOT / "data" / "processed")
    factor_history = pd.read_parquet(
        root / "french_research_factors_daily.parquet",
        columns=["date", "mkt_total_return", "rf"],
    )
    factor_history["date"] = pd.to_datetime(factor_history["date"]).dt.normalize()
    factor_history = factor_history.loc[
        factor_history["date"].le(pd.Timestamp(card.as_of_date))
    ].copy()
    macro_history = build_regime_history(factor_history)
    selected_macro = macro_history.loc[
        macro_history["date"].eq(pd.Timestamp(card.as_of_date))
    ]
    if len(selected_macro) != 1:
        raise ValueError(f"Expected one macro state row for {card.as_of_date}")
    macro_row = selected_macro.iloc[0]

    recent_drawdown = float(macro_row["recent_min_drawdown_126d"])
    recovery = float(macro_row["recovery_from_trough_126d"])
    trough_age = int(macro_row["trough_age_trading_days"])
    realized_volatility = float(macro_row["realized_volatility_21d"])
    volatility_threshold = float(macro_row["realized_volatility_threshold_80pct"])
    macro_components = pd.DataFrame(
        [
            {
                "Component": "Recent market drawdown",
                "Current": f"{recent_drawdown:.1%}",
                "Gate": f"≤ {SEVERE_DRAWDOWN_THRESHOLD:.1%} within 126d",
                "Condition": (
                    "met"
                    if recent_drawdown <= SEVERE_DRAWDOWN_THRESHOLD
                    else "not met"
                ),
            },
            {
                "Component": "Recovery from trough",
                "Current": f"{recovery:.1%} · trough age {trough_age}d",
                "Gate": (
                    f"≥ {RECOVERY_FROM_TROUGH_THRESHOLD:.1%} and age "
                    f"1–{EARLY_RECOVERY_MAX_AGE}d"
                ),
                "Condition": (
                    "met"
                    if recovery >= RECOVERY_FROM_TROUGH_THRESHOLD
                    and 1 <= trough_age <= EARLY_RECOVERY_MAX_AGE
                    else "not met"
                ),
            },
            {
                "Component": "21d realized volatility",
                "Current": f"{realized_volatility:.1%}",
                "Gate": (
                    f"≥ {volatility_threshold:.1%} "
                    "(prior-only 80th percentile)"
                ),
                "Condition": (
                    "met"
                    if realized_volatility >= volatility_threshold
                    else "not met"
                ),
            },
        ]
    )
    macro_component_html = macro_components.to_html(
        index=False, border=0, escape=True
    )
    current_market_drawdown = float(macro_row["market_drawdown"])
    composite_triggered = bool(macro_row["high_volatility_recovery_state"])
    wrapped = (
        "<div style='border:1px solid #d0d7de;border-radius:8px;padding:10px 12px'>"
        f"<strong>Current market drawdown:</strong> {current_market_drawdown:.1%} "
        "&nbsp; <strong>Composite:</strong> "
        f"{'triggered' if composite_triggered else 'not triggered'}"
        + macro_component_html
        + "<small>Components explain the composite; they are not separate "
        "scorecard rows.</small></div>"
    )
    return wrapped, current_market_drawdown, composite_triggered


def _crowding_state_label(triggered: bool | None, severity: str) -> str:
    if triggered is None:
        return "unavailable"
    if triggered:
        return f"triggered · {severity}"
    return f"not triggered · {severity}"


def _fmt_share(value: object) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):.1%}"


def _fmt_z(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:+.2f}"


def build_crowding_panel_html(
    unwind: UnwindAssessment,
    *,
    processed_dir: Path | None = None,
    include_context_overlays: bool = True,
) -> str:
    """Render T0 crowding proxies from unwind, plus optional T1 side notes."""

    by_metric = {row.metric: row for row in unwind.scorecard}
    concentration = by_metric["portfolio_concentration"]
    breadth = by_metric["momentum_breadth_deterioration"]
    liquidity = by_metric["liquidity_amplification_proxy"]
    theme = unwind.theme_concentration
    crowded = next(
        item
        for item in unwind.mechanism_scenarios
        if item.scenario == "crowded_theme_unwind"
    )

    concentration_ctx = concentration.context
    breadth_ctx = breadth.context
    proxy_rows = [
        {
            "Channel": "Portfolio concentration",
            "Reading": _crowding_state_label(
                concentration.triggered, concentration.severity
            ),
            "Key levels": (
                f"effective bets={_fmt(concentration.current_value)} · "
                f"sector HHI={_fmt(concentration_ctx.get('sector_hhi'))} · "
                f"top5 exposure={_fmt_share(concentration_ctx.get('top5_abs_exposure_share'))}"
            ),
        },
        {
            "Channel": "Momentum breadth",
            "Reading": _crowding_state_label(breadth.triggered, breadth.severity),
            "Key levels": (
                f"positive 12-1 share={_fmt_share(breadth.current_value)} · "
                f"leadership HHI="
                f"{_fmt(breadth_ctx.get('positive_momentum_leadership_hhi'))} · "
                f"Δ vs prior="
                f"{_fmt(breadth_ctx.get('breadth_change_vs_previous'), signed=True)}"
            ),
        },
        {
            "Channel": "Liquidity amplification proxy",
            "Reading": _crowding_state_label(
                liquidity.triggered, liquidity.severity
            ),
            "Key levels": (
                f"downside abnormal volume share="
                f"{_fmt_share(liquidity.current_value)} · "
                f"Amihud={_fmt(liquidity.context.get('long_median_amihud_5d'))}"
            ),
        },
        {
            "Channel": "Correlated-theme unwind",
            "Reading": crowded.status.replace("_", " "),
            "Key levels": (
                f"proxy={theme.proxy_label.replace('_', ' ')} · "
                f"cluster={', '.join(theme.cluster_symbols) or 'none'} · "
                f"exposure={_fmt_share(theme.cluster_exposure_share)} · "
                f"cutoff={theme.cluster_definition_cutoff or '—'}"
            ),
        },
    ]
    proxy_html = pd.DataFrame(proxy_rows).to_html(
        index=False, border=0, escape=True
    )

    context_elevated = (
        crowded.status == "triggered"
        or concentration.triggered is True
        or breadth.triggered is True
    )
    overlay_html = ""
    if include_context_overlays:
        positioning = build_positioning_snapshot(
            as_of_date=unwind.as_of_date,
            context_elevated=context_elevated,
            processed_dir=processed_dir,
        )
        narrative = build_narrative_snapshot(
            as_of_date=unwind.as_of_date,
            context_elevated=context_elevated,
            processed_dir=processed_dir,
        )
        overlay_rows = [
            {
                "Side note": "FINRA positioning (loser-leg)",
                "Read": positioning.read,
                "Observation": positioning.observation_date or "—",
                "Levels": (
                    f"SI z={_fmt_z(positioning.short_interest_ratio_z)} · "
                    f"utilisation z="
                    f"{_fmt_z(positioning.short_interest_utilisation_z)} · "
                    f"short-vol z={_fmt_z(positioning.short_volume_share_z)}"
                ),
            },
            {
                "Side note": "GDELT narrative crowding",
                "Read": narrative.read,
                "Observation": narrative.observation_date or "—",
                "Levels": (
                    f"crowding vol z={_fmt_z(narrative.crowding_volume_z)} · "
                    f"panic vol z={_fmt_z(narrative.panic_volume_z)} · "
                    f"risk-off vol z={_fmt_z(narrative.riskoff_volume_z)}"
                ),
            },
        ]
        overlay_table = pd.DataFrame(overlay_rows).to_html(
            index=False, border=0, escape=True
        )
        overlay_html = (
            "<h4>T1 context side notes</h4>"
            f"{overlay_table}"
            "<small>Side notes are fail-closed public-data overlays. They do "
            "not enter mechanism rules or change any deterministic trigger."
            "</small>"
        )

    return f"""
<div style='border:1px solid #d0d7de;border-radius:8px;padding:10px 12px'>
  <strong>Crowding monitor · book-structure proxies</strong>
  <small style='display:block;margin:4px 0 8px'>
    Not observed ownership, leverage, financing, or forced selling.
    Spine: portfolio concentration · momentum breadth · correlated-theme unwind.
  </small>
  {proxy_html}
  {overlay_html}
  <small>No aggregate crowding score is defined; channels remain separate.</small>
</div>
"""


def build_mechanical_unwind_panel_html(
    mechanical: MechanicalUnwindAssessment,
) -> str:
    """Render the Liquidity / Mechanical Unwind supplemental panel."""

    def _pct(value: float | None) -> str:
        if value is None or pd.isna(value):
            return "—"
        return f"{value:.0%}"

    def _num(value: float | None) -> str:
        if value is None or pd.isna(value):
            return "—"
        return f"{value:.4f}"

    absorption = mechanical.liquidity_absorption_failure
    absorption_reading = (
        "—"
        if absorption is None
        else ("failure" if absorption else "absorbing / reversing")
    )
    rows = [
        {
            "Signal": "Factor footprint",
            "Current Reading": _num(mechanical.factor_footprint_r2),
            "Historical Percentile": _pct(mechanical.factor_footprint_percentile),
            "Interpretation": (
                f"cross-sectional R² · controls={mechanical.control_spec}"
            ),
        },
        {
            "Signal": "Momentum-aligned turnover",
            "Current Reading": _num(mechanical.extreme_turnover_ratio),
            "Historical Percentile": _pct(mechanical.extreme_turnover_percentile),
            "Interpretation": "extreme (L10∪S10) abnormal volume / universe",
        },
        {
            "Signal": "Market absorption",
            "Current Reading": absorption_reading,
            "Historical Percentile": _pct(mechanical.absorption_percentile),
            "Interpretation": (
                f"continuation={_num(mechanical.continuation_pressure)} · "
                f"reversal={_num(mechanical.short_horizon_reversal)}"
            ),
        },
        {
            "Signal": "Unwind state",
            "Current Reading": mechanical.unwind_state.replace("_", " "),
            "Historical Percentile": "—",
            "Interpretation": mechanical.interpretation,
        },
    ]
    table_html = pd.DataFrame(rows).to_html(index=False, border=0, escape=True)
    warning_html = "".join(
        f"<li>{escape(item)}</li>" for item in mechanical.warnings
    ) or "<li>None.</li>"
    return f"""
<div style='border:1px solid #d0d7de;border-radius:8px;padding:10px 12px'>
  <strong>Liquidity / Mechanical Unwind</strong>
  <small style='display:block;margin:4px 0 8px'>
    Factor-aligned trading footprint proxy (Khandani–Lo inspired). Not observed
    hedge-fund positions, leverage, or forced liquidation. Separate from macro
    regime and the four-row PM scorecard.
  </small>
  {table_html}
  <details style='margin-top:8px'><summary><small>Proxy limitations</small></summary>
    <ul style='font-size:12px'>{warning_html}</ul>
  </details>
</div>
"""


def build_unwind_summary_html(unwind: UnwindAssessment) -> str:
    """Render the mechanism and six-row unwind monitor summary."""

    def _unwind_value(value: object) -> str:
        if value is None or pd.isna(value):
            return "—"
        if isinstance(value, float):
            return f"{value:.4f}"
        return str(value).replace("_", " ")

    unwind_rows = []
    for row in unwind.scorecard:
        state = (
            "unavailable"
            if row.triggered is None
            else ("triggered" if row.triggered else "not triggered")
        )
        unwind_rows.append(
            {
                "Monitor": row.metric.replace("_", " ").title(),
                "Current": _unwind_value(row.current_value),
                "Threshold": _unwind_value(row.threshold),
                "State": state,
                "Severity": row.severity,
                "Threshold provenance": row.threshold_provenance.replace("_", " "),
            }
        )
    unwind_scorecard_html = pd.DataFrame(unwind_rows).to_html(
        index=False, border=0, escape=True
    )
    mechanism_rows = []
    for mechanism in unwind.mechanism_scenarios:
        met = [
            item.name.replace("_", " ")
            for item in mechanism.conditions
            if item.met is True
        ]
        missing = [
            item.name.replace("_", " ")
            for item in mechanism.conditions
            if item.required and item.met is None
        ]
        mechanism_rows.append(
            {
                "Mechanism": mechanism.scenario.replace("_", " ").title(),
                "Status": mechanism.status.replace("_", " "),
                "Conditions met": ", ".join(met) or "none",
                "Missing": ", ".join(missing) or "none",
            }
        )
    mechanism_table_html = pd.DataFrame(mechanism_rows).to_html(
        index=False, border=0, escape=True
    )
    theme = unwind.theme_concentration
    theme_symbols = ", ".join(theme.cluster_symbols) or "no qualifying cluster"
    theme_detail = (
        f"Correlated-theme proxy: {theme.status.replace('_', ' ')} · "
        f"cluster={theme_symbols} · definition cutoff="
        f"{theme.cluster_definition_cutoff or '—'}"
    )
    unwind_support_html = "".join(
        f"<li>{escape(item.replace('_', ' '))}</li>"
        for item in unwind.supporting_evidence
    ) or "<li>None triggered.</li>"
    unwind_contradictory_html = "".join(
        f"<li>{escape(item.replace('_', ' '))}</li>"
        for item in unwind.contradictory_evidence
    ) or "<li>None available.</li>"
    unwind_missing_html = "".join(
        f"<li>{escape(item.replace('_', ' '))}</li>"
        for item in unwind.missing_evidence
    ) or "<li>None.</li>"
    return f"""
<div style='border:1px solid #d0d7de;border-radius:8px;padding:10px 12px'>
  <strong>Independent mechanism scenarios (v2)</strong>
  {mechanism_table_html}
  <small>{escape(theme_detail)}. This is a return-correlation proxy, not observed ownership.</small>
  <h4>Retained six-row deterministic inputs</h4>
  <small>Compatibility classification: {escape(unwind.scenario_classification.replace('_', ' ').title())} · {escape(unwind.scenario_rule)}</small>
  <strong>Completeness:</strong> {escape(unwind.completeness_confidence)}<br>
  {unwind_scorecard_html}
  <div style='display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px'>
    <div><strong>Supporting</strong><ul>{unwind_support_html}</ul></div>
    <div><strong>Contradictory</strong><ul>{unwind_contradictory_html}</ul></div>
    <div><strong>Missing</strong><ul>{unwind_missing_html}</ul></div>
  </div>
  <small>Public data do not directly observe leverage, forced selling, or proprietary crowding.</small>
</div>
"""


def build_comparison_html(
    card: DeterministicEvidenceInput,
    *,
    signals: tuple[QuantSignal, ...] | None = None,
) -> str:
    """Render the largest supported comparison changes."""

    if signals is None:
        signals = (
            card.triggered_quant_signals + card.non_triggered_relevant_signals
        )
    comparison_rows = []
    if card.comparison_date is not None:
        for signal in signals:
            if signal.current_value is None or signal.change_vs_comparison is None:
                continue
            comparison_rows.append(
                {
                    "Indicator": signal.name.replace("_", " ").title(),
                    f"Before ({card.comparison_date})": (
                        signal.current_value - signal.change_vs_comparison
                    ),
                    f"After ({card.as_of_date})": signal.current_value,
                    "Change": signal.change_vs_comparison,
                    "Current state": signal.status.replace("_", " "),
                    "_magnitude": abs(signal.change_vs_comparison),
                }
            )
    if not comparison_rows:
        return "<p><em>No supported comparison changes are available.</em></p>"
    comparison_table = (
        pd.DataFrame(comparison_rows)
        .sort_values("_magnitude", ascending=False)
        .drop(columns="_magnitude")
        .head(4)
    )
    comparison_display = comparison_table.copy()
    for column in comparison_display.columns[1:4]:
        comparison_display[column] = comparison_display[column].map(
            lambda value: f"{value:+.4f}"
        )
    return comparison_display.to_html(index=False, border=0, escape=True)


def _evidence_item(item: RetrievedEvidence) -> str:
    locator = item.citation_or_locator
    locator_html = ""
    if locator:
        safe_locator = escape(locator, quote=True)
        locator_html = f' · <a href="{safe_locator}" target="_blank">source</a>'
    return (
        f"<li><strong>{escape(item.headline_or_summary)}</strong><br>"
        f"<small>{escape(item.source)} · {escape(item.timestamp)}"
        f"{locator_html}</small></li>"
    )


def _evidence_list(
    evidence_ids: tuple[str, ...],
    evidence_by_id: dict[str, RetrievedEvidence],
    empty_text: str,
) -> str:
    selected = [
        evidence_by_id[item_id]
        for item_id in evidence_ids
        if item_id in evidence_by_id
    ]
    return "".join(_evidence_item(item) for item in selected) or (
        f"<li>{escape(empty_text)}</li>"
    )


def _signal_rows(items: tuple[QuantSignal, ...]) -> str:
    if not items:
        return (
            '<tr><td colspan="5"><em>No quantitative signals are '
            "triggered.</em></td></tr>"
        )
    return "".join(
        "<tr>"
        f"<td>{escape(item.name.replace('_', ' ').title())}</td>"
        f"<td>{_fmt(item.current_value)}</td>"
        f"<td>{_fmt(item.threshold)}</td>"
        f"<td>{escape(item.status.replace('_', ' '))}</td>"
        f"<td>{_fmt(item.change_vs_comparison, signed=True)}</td>"
        "</tr>"
        for item in items
    )


def plot_trailing_risk_chart(
    result: MVPRunResult,
    *,
    output_path: Path | None = None,
) -> Figure:
    """Plot trailing portfolio drawdown and beta gap through the as-of date."""

    card = result.deterministic_input
    signals = card.triggered_quant_signals + card.non_triggered_relevant_signals
    signal_by_name = {signal.name: signal for signal in signals}
    risk_history = pd.read_parquet(
        result.config.processed_dir / "leg_risk_history.parquet",
        columns=["date", "portfolio_drawdown", "beta_gap_short_minus_long_126d"],
    )
    risk_history["date"] = pd.to_datetime(risk_history["date"])
    risk_history = risk_history.loc[
        risk_history["date"].le(pd.Timestamp(card.as_of_date))
    ].tail(252)

    fig, axes = plt.subplots(2, 1, figsize=(10, 5), sharex=True)
    plot_specs = [
        ("portfolio_drawdown", "portfolio_drawdown", "Portfolio drawdown"),
        (
            "beta_gap_short_minus_long_126d",
            "short_minus_long_beta_gap",
            "Short-minus-long beta gap",
        ),
    ]
    for axis, (column, signal_name, title) in zip(axes, plot_specs):
        axis.plot(
            risk_history["date"],
            risk_history[column],
            color="#285f8f",
            linewidth=1.5,
        )
        threshold = signal_by_name[signal_name].threshold
        if threshold is not None:
            axis.axhline(
                threshold,
                color="#b54a4a",
                linestyle="--",
                linewidth=1,
                label="selected-date threshold",
            )
        axis.axvline(pd.Timestamp(card.as_of_date), color="#222222", linewidth=1)
        if card.comparison_date is not None:
            axis.axvline(
                pd.Timestamp(card.comparison_date),
                color="#777777",
                linestyle=":",
                linewidth=1,
            )
        axis.set_title(title, loc="left", fontsize=10)
        axis.grid(alpha=0.2)
    axes[0].legend(loc="lower left", frameon=False, fontsize=8)
    fig.suptitle(
        f"Trailing 252 observations through {card.as_of_date}",
        x=0.01,
        ha="left",
        fontsize=12,
    )
    fig.tight_layout()
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=120, bbox_inches="tight")
    return fig


def _render_pm_response_html(result: MVPRunResult) -> str:
    """Render the bounded PM decision-support readout."""

    pm = result.pm_response
    llm_status = "enabled" if pm.use_llm else "disabled / deterministic fallback"
    return f"""
  <h3>PM Response <span class="eyebrow">DECISION SUPPORT · LLM {escape(llm_status.upper())}</span></h3>
  <div class="panel">
    <h4>Current state</h4>
    <p>{escape(pm.current_state)}</p>
    <h4>Main vulnerability</h4>
    <p>{escape(pm.main_vulnerability)}</p>
    <h4>What would change the reading</h4>
    <ul>{_list_html(pm.what_would_change_the_reading, 'None reported.')}</ul>
    <h4>Conditional portfolio response</h4>
    <ul>{_list_html(pm.conditional_response, 'None reported.')}</ul>
    <h4>Why not act yet</h4>
    <p>{escape(pm.why_not_act_yet)}</p>
    <p><small>Bounded categories: {escape(', '.join(pm.response_categories))}. Conditional language only — not an execution instruction.</small></p>
  </div>
"""


def render_pm_card_html(result: MVPRunResult) -> str:
    """Render the final PM Evidence Card as self-contained HTML."""

    card = result.deterministic_input
    interpretation = result.interpretation
    unwind = result.unwind
    mechanical = result.mechanical_unwind
    evidence_quality = card.audit_metadata.get("evidence_quality", "unavailable")
    macro_component_html, _, _ = build_macro_component_html(
        card, processed_dir=result.config.processed_dir
    )
    unwind_summary_html = build_unwind_summary_html(unwind)
    crowding_panel_html = build_crowding_panel_html(
        unwind, processed_dir=result.config.processed_dir
    )
    mechanical_panel_html = build_mechanical_unwind_panel_html(mechanical)
    comparison_html = build_comparison_html(card)
    evidence_by_id = {item.evidence_id: item for item in card.retrieved_evidence}
    contextual_evidence = [
        item for item in card.retrieved_evidence if item.stance == "contextual"
    ]
    contextual_html = "".join(
        _evidence_item(item) for item in contextual_evidence
    ) or "<li>No contextual evidence retrieved.</li>"
    mechanism_missing = tuple(
        f"{item.scenario}: {name}"
        for item in unwind.mechanism_scenarios
        for name in item.missing_evidence
    )
    missing_items = tuple(
        dict.fromkeys(
            (
                *interpretation.missing_or_uncertain_evidence,
                *card.data_warnings,
                *unwind.missing_evidence,
                *mechanism_missing,
            )
        )
    )
    warning_items = tuple(
        dict.fromkeys(
            (*interpretation.warnings, *card.data_warnings, *unwind.warnings)
        )
    )
    score = (
        "Unavailable"
        if card.deterministic_score is None
        else f"{card.deterministic_score:.4f}"
    )
    llm_status = (
        "enabled" if interpretation.use_llm else "disabled / deterministic fallback"
    )
    header_label = result.display_labels["header_state_label"].upper()
    scorecard_label = escape(result.display_labels["scorecard_label"].upper())
    return f"""
<style>
.pm-card {{border:1px solid #c9d1d9;border-radius:12px;padding:18px 22px;font-family:Arial,sans-serif;line-height:1.35;color:#17212b}}
.pm-card h3 {{margin:18px 0 7px;font-size:16px}}
.pm-card h4 {{margin:7px 0 4px;font-size:13px}}
.pm-card table {{border-collapse:collapse;width:100%;font-size:12px}}
.pm-card th,.pm-card td {{border-bottom:1px solid #e5e7eb;padding:6px;text-align:left;vertical-align:top}}
.pm-card .header {{display:flex;justify-content:space-between;gap:20px;border-bottom:2px solid #394b59;padding-bottom:12px}}
.pm-card .state {{font-size:25px;font-weight:700}}
.pm-card .eyebrow {{font-size:11px;color:#59636e;letter-spacing:.05em}}
.pm-card .grid3 {{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}}
.pm-card .grid2 {{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}}
.pm-card .panel {{background:#f6f8fa;border-radius:7px;padding:9px 11px;font-size:12px}}
.pm-card .narrative {{border-left:4px solid #7a5af8;background:#f7f5ff;padding:10px 13px}}
.pm-card ul {{margin:4px 0 8px;padding-left:18px}}
.pm-card li {{margin-bottom:5px}}
@media (max-width:800px) {{.pm-card .grid3,.pm-card .grid2 {{grid-template-columns:1fr}}}}
</style>
<div class="pm-card">
  <div class="header">
    <div><div class="eyebrow">{escape(header_label)}</div><div class="state">{escape(card.overall_risk_state.replace('_', ' ').title())}</div><div>As of {escape(card.as_of_date)}</div></div>
    <div style="text-align:right;font-size:12px">Evidence: <strong>{escape(str(evidence_quality).title())}</strong><br>Score: {escape(score)}<br>Profile: {escape(card.threshold_profile)}<br>Run: <code>{escape(card.run_id)}</code><br>Full fingerprint: <code>{escape(result.full_run_fingerprint)}</code></div>
  </div>

  <h3>Triggered Quantitative Signals <span class="eyebrow">{scorecard_label}</span></h3>
  <table><thead><tr><th>Signal</th><th>Current</th><th>Threshold</th><th>State</th><th>Change</th></tr></thead><tbody>{_signal_rows(card.triggered_quant_signals)}</tbody></table>

  <h3>High-Volatility Recovery Components <span class="eyebrow">DETERMINISTIC · AUDIT DETAIL, NOT EXTRA SIGNALS</span></h3>
  {macro_component_html}

  <h3>Momentum Crash Mechanisms <span class="eyebrow">DETERMINISTIC · MULTI-LABEL V2 + RETAINED SIX-ROW INPUTS</span></h3>
  {unwind_summary_html}

  <h3>Crowding Monitor <span class="eyebrow">T0 PROXIES · OPTIONAL T1 SIDE NOTES · NO AGGREGATE SCORE</span></h3>
  {crowding_panel_html}

  <h3>Liquidity / Mechanical Unwind <span class="eyebrow">FACTOR FOOTPRINT · ALIGNED TURNOVER · ABSORPTION PROXY</span></h3>
  {mechanical_panel_html}

  <h3>What Changed <span class="eyebrow">DETERMINISTIC · {escape(card.comparison_date or 'NO COMPARISON')}</span></h3>
  {comparison_html}

  <h3>Narrative Evidence <span class="eyebrow">VALIDATED EVIDENCE IDs ONLY</span></h3>
  <div class="grid3">
    <div class="panel"><h4>Supporting elevated risk</h4><ul>{_evidence_list(interpretation.supporting_evidence_ids, evidence_by_id, 'No supporting evidence selected.')}</ul></div>
    <div class="panel"><h4>Contradicting / moderating</h4><ul>{_evidence_list(interpretation.contradicting_evidence_ids, evidence_by_id, 'No contradicting evidence selected.')}</ul></div>
    <div class="panel"><h4>Contextual / uncertain</h4><ul>{contextual_html}</ul><h4>Known missing data</h4><ul>{_list_html(missing_items, 'None reported.')}</ul></div>
  </div>

  <h3>PM Interpretation <span class="eyebrow">LLM {escape(llm_status.upper())}</span></h3>
  <div class="narrative"><p>{escape(interpretation.pm_interpretation)}</p></div>

  {_render_pm_response_html(result)}

  <div class="grid2">
    <div><h3>What to Monitor Next</h3><ul>{_list_html(interpretation.monitoring_questions[:5], 'No monitoring questions available.')}</ul></div>
    <div><h3>Invalidation Conditions</h3><ul>{_list_html(interpretation.invalidation_conditions[:4], 'No invalidation conditions available.')}</ul></div>
  </div>

  <details><summary><strong>Audit and Limitations</strong></summary>
    <p><small>Data cutoff: {escape(card.data_cutoff)} · Prompt/model: {escape(interpretation.model_or_prompt_version)} · LLM requested/effective: {result.config.use_llm}/{interpretation.use_llm}</small></p>
    <h4>Warnings</h4><ul>{_list_html(warning_items, 'None reported.')}</ul>
    <p><small>Quantitative fields, evidence records, cutoff, and run ID are immutable inputs to interpretation. Evidence is contextual and does not establish causality.</small></p>
  </details>
</div>
"""


def render_pm_risk_markdown(result: MVPRunResult) -> str:
    """Render a PM-facing risk summary suitable for file export."""

    card = result.deterministic_input
    interpretation = result.interpretation
    unwind = result.unwind
    interpretation_heading = (
        "AI-assisted, evidence-constrained"
        if interpretation.use_llm
        else "Evidence-assisted, deterministic fallback"
    )
    signals = card.triggered_quant_signals + card.non_triggered_relevant_signals
    tail_loss = card.audit_metadata.get("tail_loss_frequency")
    horizon = card.audit_metadata.get(
        "tail_loss_horizon_days", result.config.horizon_days
    )
    if isinstance(tail_loss, (int, float)):
        tail_loss_line = f"- **Conditional tail-loss frequency:** {tail_loss:.1%}"
    else:
        tail_loss_line = "- **Conditional tail-loss frequency:** unavailable"

    lines = [
        "# Momentum Tail-Risk Assessment (Example Output)",
        "",
        f"**Assessment date:** {card.as_of_date}",
        f"**Comparison date:** {card.comparison_date or 'None'}",
        f"**Risk horizon:** {horizon} trading days",
        "",
        "## Overall context",
        "",
        f"- **UMD comparison benchmark (deterministic):** {card.overall_risk_state}",
        f"- **PM portfolio scorecard triggers:** {len(card.triggered_quant_signals)}",
        "- **Active mechanism scenarios:** "
        + (", ".join(unwind.active_scenarios) or "none"),
        f"- **Evidence quality:** {card.audit_metadata.get('evidence_quality', 'unavailable')}",
        "",
        "## UMD comparison: tail-loss context (illustrative)",
        "",
        tail_loss_line,
        "- *Label: state-conditioned UMD comparison frequency — not the PM book, not a trading forecast.*",
        "",
        "## Long / short risk attribution (deterministic)",
        "",
    ]
    for signal in signals:
        if any(token in signal.name for token in ("beta", "drawdown", "short")):
            lines.append(
                f"- **{signal.name}:** {signal.current_value} "
                f"(threshold {signal.threshold}, status {signal.status})"
            )
    lines.extend(
        [
            "",
            "## Dominant monitoring channels",
            "",
            f"- **Unwind completeness:** {unwind.completeness_confidence}",
            f"- **Scenario classification:** {unwind.scenario_classification}",
            "",
            "## Crowding monitor (book-structure proxies)",
            "",
            "- Channels: portfolio concentration, momentum breadth, "
            "correlated-theme unwind; optional FINRA / GDELT side notes.",
            "- *Proxy only — not observed ownership, leverage, or flow. "
            "No aggregate crowding score.*",
            "",
            "## Liquidity / Mechanical Unwind",
            "",
            f"- **State:** {result.mechanical_unwind.unwind_state}",
            f"- **Factor footprint R²:** {result.mechanical_unwind.factor_footprint_r2}",
            "- **Momentum-aligned turnover ratio:** "
            f"{result.mechanical_unwind.extreme_turnover_ratio}",
            "- **Absorption failure:** "
            f"{result.mechanical_unwind.liquidity_absorption_failure}",
            "- *Detects factor-aligned trading footprints, not actual "
            "hedge-fund liquidations.*",
            "",
            "## Text evidence (timestamped replay)",
            "",
        ]
    )
    for item in card.retrieved_evidence:
        lines.append(
            f"- [{item.stance or 'unclassified'}] {item.headline_or_summary} "
            f"({item.source}, {item.timestamp})"
        )
    pm = result.pm_response
    lines.extend(
        [
            "",
            f"## PM interpretation ({interpretation_heading})",
            "",
            interpretation.pm_interpretation,
            "",
            "## PM response (decision support)",
            "",
            f"**Current state:** {pm.current_state}",
            "",
            f"**Main vulnerability:** {pm.main_vulnerability}",
            "",
            "**What would change the reading:**",
            "",
        ]
    )
    for item in pm.what_would_change_the_reading:
        lines.append(f"- {item}")
    lines.extend(["", "**Conditional portfolio response:**", ""])
    for item in pm.conditional_response:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            f"**Why not act yet:** {pm.why_not_act_yet}",
            "",
            f"- Bounded categories: {', '.join(pm.response_categories)}",
            f"- PM response LLM: {pm.use_llm} ({pm.model_or_prompt_version})",
            "",
            "## Suggested review actions",
            "",
        ]
    )
    for question in interpretation.monitoring_questions[:5]:
        lines.append(f"- Monitor: {question}")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- Default PM book uses survivorship-biased current SPY membership; not full PIT universe.",
            "- UMD is a comparison benchmark; the S&P 10/10 book is the customizable PM portfolio.",
            "- Evidence is exact-date cached replay, not live retrieval.",
            "- Mechanism scenarios are descriptive rules, not validated crash forecasts.",
            "- PM response categories are bounded decision-support labels, not trade instructions.",
            "",
            "## Provenance",
            "",
            f"- Card run ID: `{card.run_id}`",
            f"- Full run fingerprint: `{result.full_run_fingerprint}`",
            f"- Data cutoff: {card.data_cutoff}",
            f"- LLM requested/effective: {result.config.use_llm}/{interpretation.use_llm}",
            "",
        ]
    )
    return "\n".join(lines)


def save_pm_outputs(
    result: MVPRunResult,
    *,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    """Write example PM-facing HTML and Markdown outputs."""

    root = output_dir or (REPO_ROOT / "outputs" / "quiet_control_example_risk_output")
    root.mkdir(parents=True, exist_ok=True)
    stem = f"pm_risk_assessment_{result.config.as_of_date}"
    html_path = root / f"{stem}.html"
    md_path = root / f"{stem}.md"
    json_path = root / f"{stem}.json"
    html_path.write_text(render_pm_card_html(result), encoding="utf-8")
    md_path.write_text(render_pm_risk_markdown(result), encoding="utf-8")
    json_path.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    return {"html": html_path, "md": md_path, "json": json_path}
