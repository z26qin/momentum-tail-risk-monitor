"""Read-only, deterministic integration entry point for the final MVP.

The runner composes the frozen Phase 1--4 processed artifacts and the compact
Phase 5A feasibility audit. It never performs data acquisition, rewrites an
upstream artifact, or treats fundamental-data coverage as an alignment signal.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from src.monitoring.scorecard import build_scorecard, validate_scorecard
from src.regime.market_state import build_regime_history
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    REPO_ROOT,
    atomic_write_bytes,
    iso_date,
    parse_as_of_date,
    read_json,
    write_json,
)


PRIMARY_AS_OF_DATE = pd.Timestamp("2026-05-29")
HISTORICAL_PRECURSOR_DATE = pd.Timestamp("2023-01-09")
HISTORICAL_STRESS_DATE = pd.Timestamp("2023-02-02")

DEFAULT_DEMO_OUTPUT_DIR = DEFAULT_OUTPUT_DIR / "demo"
DEFAULT_PHASE5_AUDIT_PATH = (
    DEFAULT_OUTPUT_DIR / "fundamental_alignment" / "phase_5a_audit.json"
)
DEFAULT_SCORECARD_DIR = DEFAULT_OUTPUT_DIR / "scorecard"

HOLDINGS_FILE = "momentum_portfolio_holdings.parquet"
RISK_FILE = "leg_risk_history.parquet"
FACTORS_FILE = "french_research_factors_daily.parquet"


def _clean(value: Any) -> Any:
    """Convert pandas/numpy values into strict deterministic JSON values."""

    if value is None or value is pd.NA:
        return None
    if isinstance(value, pd.Timestamp):
        return iso_date(value)
    if isinstance(value, pd.Period):
        return str(value)
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else float(value)
    if pd.isna(value):
        return None
    return value


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {column: _clean(value) for column, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def _exact_row(
    frame: pd.DataFrame,
    *,
    date_column: str,
    selected_date: pd.Timestamp,
    label: str,
) -> pd.Series:
    selected = frame.loc[
        pd.to_datetime(frame[date_column]).dt.normalize().eq(selected_date)
    ]
    if len(selected) != 1:
        raise ValueError(
            f"{label} must contain exactly one row on {iso_date(selected_date)}"
        )
    return selected.iloc[0]


def _market_stage(row: pd.Series) -> str:
    """Presentation-only label with fixed, documented precedence."""

    if bool(row.get("high_volatility_recovery_state", False)):
        return "high_volatility_recovery"
    if bool(row.get("crash_state", False)):
        return "crash"
    if bool(row.get("early_recovery_state", False)):
        return "early_recovery"
    if bool(row.get("high_volatility", False)):
        return "high_volatility"
    dm_state = row.get("dm_state")
    return "unavailable" if pd.isna(dm_state) else str(dm_state)


def _module_latest_dates(
    *,
    factors: pd.DataFrame,
    risk: pd.DataFrame,
    holdings: pd.DataFrame,
    scorecard_dir: Path,
    phase5_audit: dict[str, Any],
) -> dict[str, str | None]:
    scorecard_dates: list[pd.Timestamp] = []
    for path in scorecard_dir.glob("scorecard_*.csv"):
        try:
            scorecard_dates.append(pd.Timestamp(path.stem.removeprefix("scorecard_")))
        except ValueError:
            continue
    return {
        "phase_1_macro": iso_date(pd.to_datetime(factors["date"]).max()),
        "phase_2_holdings_formation": iso_date(
            pd.to_datetime(holdings["formation_date"]).max()
        ),
        "phase_3_realized_risk": iso_date(pd.to_datetime(risk["date"]).max()),
        "phase_4_scorecard_artifacts": (
            iso_date(max(scorecard_dates)) if scorecard_dates else None
        ),
        "phase_5a_coverage_audit": phase5_audit.get("as_of_date"),
    }


def _load_scorecard(
    *,
    as_of_date: pd.Timestamp,
    risk: pd.DataFrame,
    regime: pd.DataFrame,
    scorecard_dir: Path,
) -> tuple[pd.DataFrame, str]:
    artifact_path = scorecard_dir / f"scorecard_{iso_date(as_of_date)}.csv"
    if artifact_path.is_file():
        table = pd.read_csv(artifact_path)
        table["triggered"] = table["triggered"].astype("boolean")
        validate_scorecard(table)
        return table, f"outputs/scorecard/{artifact_path.name}"
    return (
        build_scorecard(risk, regime, as_of_date=as_of_date),
        "calculated_in_memory_with_frozen_phase_4_rules",
    )


def _scorecard_contract(table: pd.DataFrame, source: str) -> dict[str, Any]:
    rows = _records(table)
    return {
        "source": source,
        "definition": "unchanged_phase_4_four_row_scorecard",
        "rows": rows,
        "triggered_metrics": [
            row["metric"] for row in rows if row["triggered"] is True
        ],
        "unavailable_metrics": [
            row["metric"] for row in rows if row["status"] == "unavailable"
        ],
    }


def _portfolio_dates(
    *,
    as_of_date: pd.Timestamp,
    risk_row: pd.Series,
    holdings: pd.DataFrame,
) -> tuple[pd.Timestamp, pd.Timestamp | None]:
    active_formation = pd.Timestamp(risk_row["formation_date"]).normalize()
    available = (
        pd.to_datetime(holdings["formation_date"]).dt.normalize().drop_duplicates()
    )
    candidates = available.loc[available.ge(as_of_date)]
    next_formation = None if candidates.empty else pd.Timestamp(candidates.min())
    if next_formation is not None and next_formation < as_of_date:
        raise AssertionError("next rebalance formation precedes observation date")
    if active_formation >= as_of_date:
        raise ValueError(
            "active risk portfolio must have formed before the observation date"
        )
    return active_formation, next_formation


def _selected_holdings(
    holdings: pd.DataFrame,
    *,
    formation_date: pd.Timestamp,
    portfolio_role: str,
) -> pd.DataFrame:
    selected = holdings.loc[
        pd.to_datetime(holdings["formation_date"])
        .dt.normalize()
        .eq(formation_date)
    ].copy()
    if selected.empty:
        raise ValueError(
            f"holdings unavailable for formation {iso_date(formation_date)}"
        )
    selected.insert(0, "portfolio_role", portfolio_role)
    columns = [
        "portfolio_role",
        "formation_date",
        "effective_month",
        "symbol",
        "leg",
        "weight",
        "momentum_return",
        "price_momentum_rank",
        "signal_start_date",
        "signal_end_date",
        "rankable_universe",
        "membership_status",
        "survivorship_bias",
    ]
    return selected.loc[:, columns].sort_values(
        ["portfolio_role", "leg", "price_momentum_rank", "symbol"]
    )


def _macro_contract(row: pd.Series) -> dict[str, Any]:
    fields = (
        "dm_state",
        "market_drawdown",
        "recent_min_drawdown_126d",
        "recovery_from_trough_126d",
        "realized_volatility_21d",
        "realized_volatility_threshold_80pct",
        "bear_state",
        "high_volatility",
        "crash_state",
        "early_recovery_state",
        "high_volatility_recovery_state",
        "panic_intensity",
        "rate_regime",
    )
    result = {field: _clean(row.get(field)) for field in fields}
    result["market_stage"] = _market_stage(row)
    result["market_stage_definition"] = (
        "presentation adapter only; precedence is high-volatility recovery, "
        "crash, early recovery, high volatility, then the frozen DM state"
    )
    return result


def _risk_contract(row: pd.Series) -> dict[str, Any]:
    fields = (
        "portfolio_return",
        "long_contribution",
        "short_contribution",
        "portfolio_contribution_21d",
        "long_contribution_21d",
        "short_contribution_21d",
        "portfolio_drawdown",
        "portfolio_volatility_21d",
        "long_beta_126d",
        "short_underlying_beta_126d",
        "beta_gap_short_minus_long_126d",
        "portfolio_beta_126d",
        "long_up_beta_126d",
        "short_underlying_up_beta_126d",
        "portfolio_up_beta_126d",
        "long_down_beta_126d",
        "short_underlying_down_beta_126d",
        "portfolio_down_beta_126d",
        "benchmark_source",
        "benchmark_status",
        "risk_timing",
    )
    return {field: _clean(row.get(field)) for field in fields}


def _phase5_contract(audit: dict[str, Any]) -> dict[str, Any]:
    ratio = float(audit["two_of_three_coverage_ratio"])
    status = str(audit["two_of_three_coverage_status"])
    if not np.isclose(ratio, 0.647887323943662):
        raise ValueError("Phase 5A aggregate coverage differs from reviewed audit")
    if status != "degraded":
        raise ValueError("Phase 5A reviewed coverage status must remain degraded")
    return {
        "phase": "5A",
        "scope": "coverage_feasibility_only",
        "artifact_as_of_date": audit.get("as_of_date"),
        "coverage_ratio": ratio,
        "coverage_percent": round(ratio * 100.0, 2),
        "covered_issuers": int(audit["two_of_three_covered_count"]),
        "eligible_issuers": int(audit["distinct_mapped_cik_count"]),
        "coverage_status": "degraded",
        "alignment_status": "future_work",
        "fundamental_ranks": None,
        "spearman_alignment": None,
        "long_short_fundamental_spread": None,
        "alignment_flags": None,
        "risk_conclusion": None,
        "interpretation": (
            "Acquisition coverage is visible for feasibility only. It is not "
            "fundamental alignment and cannot imply safe, low, or high risk."
        ),
    }


def _observation(
    *,
    as_of_date: pd.Timestamp,
    risk: pd.DataFrame,
    regime: pd.DataFrame,
    holdings: pd.DataFrame,
    scorecard_dir: Path,
    include_holdings: bool,
) -> tuple[dict[str, Any], pd.DataFrame]:
    risk_row = _exact_row(
        risk,
        date_column="date",
        selected_date=as_of_date,
        label="Phase 3 risk history",
    )
    regime_row = _exact_row(
        regime,
        date_column="date",
        selected_date=as_of_date,
        label="Phase 1 regime history",
    )
    active_formation, next_formation = _portfolio_dates(
        as_of_date=as_of_date,
        risk_row=risk_row,
        holdings=holdings,
    )
    scorecard, scorecard_source = _load_scorecard(
        as_of_date=as_of_date,
        risk=risk,
        regime=regime,
        scorecard_dir=scorecard_dir,
    )

    portfolio_rows: list[pd.DataFrame] = []
    if include_holdings:
        portfolio_rows.append(
            _selected_holdings(
                holdings,
                formation_date=active_formation,
                portfolio_role="active_risk_portfolio",
            )
        )
        if next_formation is not None:
            portfolio_rows.append(
                _selected_holdings(
                    holdings,
                    formation_date=next_formation,
                    portfolio_role="next_rebalance_portfolio",
                )
            )
    selected = (
        pd.concat(portfolio_rows, ignore_index=True)
        if portfolio_rows
        else pd.DataFrame()
    )
    result = {
        "observation_date": iso_date(as_of_date),
        "active_risk_portfolio_formation_date": iso_date(active_formation),
        "next_rebalance_formation_date": (
            None if next_formation is None else iso_date(next_formation)
        ),
        "date_alignment_note": (
            "Realized risk uses the portfolio active on the observation date. "
            "The next rebalance is separately labeled and is not used to "
            "attribute already-realized risk."
        ),
        "macro_regime": _macro_contract(regime_row),
        "risk_decomposition": _risk_contract(risk_row),
        "deterministic_scorecard": _scorecard_contract(
            scorecard,
            scorecard_source,
        ),
    }
    return result, selected


def _historical_case(
    *,
    risk: pd.DataFrame,
    regime: pd.DataFrame,
    holdings: pd.DataFrame,
    scorecard_dir: Path,
) -> dict[str, Any]:
    precursor, _ = _observation(
        as_of_date=HISTORICAL_PRECURSOR_DATE,
        risk=risk,
        regime=regime,
        holdings=holdings,
        scorecard_dir=scorecard_dir,
        include_holdings=False,
    )
    stress, _ = _observation(
        as_of_date=HISTORICAL_STRESS_DATE,
        risk=risk,
        regime=regime,
        holdings=holdings,
        scorecard_dir=scorecard_dir,
        include_holdings=False,
    )
    return {
        "status": "historical_proxy",
        "title": "January-to-February 2023 relative elevated-risk case",
        "permitted_description": [
            "relative elevated-risk",
            "stress precursor",
            "high-volatility recovery example",
        ],
        "precursor": precursor,
        "realized_stress_observation": stress,
        "interpretation": (
            "January 9 is a relative stress precursor, not a formal "
            "panic_elevated alert or a proven prediction. February 2 records "
            "realized portfolio pressure; temporal ordering does not establish "
            "that Fed repricing or any other narrative caused the loss."
        ),
        "limitations": [
            "The historical portfolio uses current S&P 500 membership and is survivorship-biased.",
            "The macro and risk states are deterministic descriptions, not causal estimates.",
            "The precursor and realized-stress dates use different active monthly portfolios.",
        ],
    }


def _unavailable_evidence() -> dict[str, Any]:
    return {
        "component": (
            "Phase 8 capability preview — not the completed Phase 8 implementation."
        ),
        "status": "unavailable",
        "supporting": [],
        "contradicting": [],
        "contextual": [],
        "research_questions": [],
        "uncertainty": "Reliable date-matched evidence is unavailable.",
        "limitations": [
            "Evidence does not modify deterministic facts, thresholds, or triggered states."
        ],
    }


def _build_evidence(
    deterministic_summary: dict[str, Any],
    *,
    builder: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if builder is None:
        try:
            from src.evidence.research_preview import build_research_preview
        except ImportError:
            return _unavailable_evidence()
        builder = build_research_preview
    return builder(
        deterministic_summary=deterministic_summary,
        evidence_case_date=HISTORICAL_PRECURSOR_DATE,
    )


def _format_percent(value: Any) -> str:
    return "unavailable" if value is None else f"{float(value):.2%}"


def _format_number(value: Any) -> str:
    return "unavailable" if value is None else f"{float(value):.4f}"


def _markdown_report(summary: dict[str, Any]) -> str:
    metadata = summary["metadata"]
    current = summary["current_observation"]
    macro = current["macro_regime"]
    risk = current["risk_decomposition"]
    phase5 = summary["phase_5a_fundamental_feasibility"]
    case = summary["historical_case_2023"]
    evidence = summary["evidence_preview"]

    active = summary["portfolios"]["active"]
    next_portfolio = summary["portfolios"]["next_rebalance"]

    lines = [
        "# Momentum Tail-Risk Monitor — Final MVP Demo",
        "",
        "## 1. Date and data alignment",
        "",
        f"- Observation date: `{metadata['observation_date']}`",
        (
            "- Active risk-portfolio formation date: "
            f"`{metadata['active_risk_portfolio_formation_date']}`"
        ),
        (
            "- Next rebalance formation date: "
            f"`{metadata['next_rebalance_formation_date']}`"
        ),
        "- Module latest dates:",
    ]
    lines.extend(
        f"  - {name}: `{date}`"
        for name, date in metadata["module_latest_data_dates"].items()
    )
    lines.extend(
        [
            "",
            (
                "The realized return, contribution, beta, and scorecard values "
                "belong to the active portfolio. The separately labeled next "
                "rebalance is not used to explain already-realized risk."
            ),
            "",
            "## 2. Macro regime",
            "",
            f"- Presentation stage: `{macro['market_stage']}`",
            f"- Frozen DM state: `{macro['dm_state']}`",
            f"- Market drawdown: {_format_percent(macro['market_drawdown'])}",
            f"- Early recovery: `{macro['early_recovery_state']}`",
            f"- High volatility: `{macro['high_volatility']}`",
            (
                "- High-volatility recovery: "
                f"`{macro['high_volatility_recovery_state']}`"
            ),
            f"- Rate regime: `{macro['rate_regime']}`",
            "",
            "## 3. Portfolio",
            "",
            (
                f"- Active portfolio ({active['formation_date']}): "
                f"{', '.join(active['long_symbols'])} / short "
                f"{', '.join(active['short_symbols'])}"
            ),
            (
                f"- Next rebalance ({next_portfolio['formation_date']}): "
                f"{', '.join(next_portfolio['long_symbols'])} / short "
                f"{', '.join(next_portfolio['short_symbols'])}"
            ),
            "- Membership: current S&P 500 snapshot proxy; historical results are survivorship-biased.",
            "",
            "## 4. Return, contribution, and beta",
            "",
            f"- Daily portfolio return: {_format_percent(risk['portfolio_return'])}",
            f"- Daily long contribution: {_format_percent(risk['long_contribution'])}",
            f"- Daily short contribution: {_format_percent(risk['short_contribution'])}",
            (
                "- Trailing 21-day portfolio contribution: "
                f"{_format_percent(risk['portfolio_contribution_21d'])}"
            ),
            f"- Long beta: {_format_number(risk['long_beta_126d'])}",
            (
                "- Short-underlying beta: "
                f"{_format_number(risk['short_underlying_beta_126d'])}"
            ),
            (
                "- Short-minus-long beta gap: "
                f"{_format_number(risk['beta_gap_short_minus_long_126d'])}"
            ),
            f"- Portfolio up-market beta: {_format_number(risk['portfolio_up_beta_126d'])}",
            (
                "- Portfolio down-market beta: "
                f"{_format_number(risk['portfolio_down_beta_126d'])}"
            ),
            "",
            "## 5. Unchanged Phase 4 deterministic scorecard",
            "",
            "| Metric | Value | Threshold | Triggered | Status |",
            "|---|---:|---:|:---:|---|",
        ]
    )
    for row in current["deterministic_scorecard"]["rows"]:
        lines.append(
            f"| {row['metric']} | {_format_number(row['current_value'])} | "
            f"{_format_number(row['threshold'])} | {row['triggered']} | "
            f"{row['status']} |"
        )
    lines.extend(
        [
            "",
            "## 6. Phase 5A fundamental feasibility",
            "",
            f"- Coverage: {phase5['coverage_percent']:.2f}%",
            f"- Coverage status: `{phase5['coverage_status']}`",
            f"- Alignment status: `{phase5['alignment_status']}`",
            "- Fundamental ranks: `null`",
            "- Spearman alignment: `null`",
            "- Long-short fundamental spread: `null`",
            "- Alignment flags: `null`",
            "",
            (
                "Coverage only shows that the SEC acquisition route is partly "
                "feasible. It does not support a safe, low-risk, or high-risk "
                "fundamental conclusion."
            ),
            "",
            "## 7. 2023 historical case",
            "",
            f"- Precursor observation: `{case['precursor']['observation_date']}`",
            (
                "- Precursor stage: "
                f"`{case['precursor']['macro_regime']['market_stage']}`"
            ),
            (
                "- Realized stress observation: "
                f"`{case['realized_stress_observation']['observation_date']}`"
            ),
            (
                "- Realized stress daily portfolio return: "
                f"{_format_percent(case['realized_stress_observation']['risk_decomposition']['portfolio_return'])}"
            ),
            (
                "- Realized stress 21-day long / short contribution: "
                f"{_format_percent(case['realized_stress_observation']['risk_decomposition']['long_contribution_21d'])} / "
                f"{_format_percent(case['realized_stress_observation']['risk_decomposition']['short_contribution_21d'])}"
            ),
            "",
            case["interpretation"],
            "",
            "## 8. Evidence preview and limitations",
            "",
            f"- Component: {evidence['component']}",
            f"- Evidence status: `{evidence['status']}`",
            f"- Supporting items: {len(evidence['supporting'])}",
            f"- Contradicting items: {len(evidence['contradicting'])}",
            f"- Contextual items: {len(evidence['contextual'])}",
            f"- Uncertainty: {evidence['uncertainty']}",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in summary["limitations"])
    return "\n".join(lines) + "\n"


def _portfolio_summary(
    rows: pd.DataFrame,
    *,
    role: str,
) -> dict[str, Any]:
    selected = rows.loc[rows["portfolio_role"].eq(role)]
    if selected.empty:
        return {
            "formation_date": None,
            "long_symbols": [],
            "short_symbols": [],
        }
    return {
        "formation_date": iso_date(pd.Timestamp(selected["formation_date"].iloc[0])),
        "effective_month": str(selected["effective_month"].iloc[0]),
        "long_symbols": selected.loc[selected["leg"].eq("long"), "symbol"].tolist(),
        "short_symbols": selected.loc[
            selected["leg"].eq("short"), "symbol"
        ].tolist(),
    }


def run_demo(
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_DEMO_OUTPUT_DIR,
    phase5_audit_path: Path = DEFAULT_PHASE5_AUDIT_PATH,
    scorecard_dir: Path = DEFAULT_SCORECARD_DIR,
    evidence_builder: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose and persist the final MVP without mutating upstream artifacts."""

    as_of_date = pd.Timestamp(as_of_date).normalize()
    factors = pd.read_parquet(processed_dir / FACTORS_FILE)
    risk = pd.read_parquet(processed_dir / RISK_FILE)
    holdings = pd.read_parquet(processed_dir / HOLDINGS_FILE)
    for frame, column in (
        (factors, "date"),
        (risk, "date"),
        (holdings, "formation_date"),
    ):
        frame[column] = pd.to_datetime(frame[column]).dt.normalize()
    phase5_audit = read_json(phase5_audit_path)
    regime = build_regime_history(factors)

    current, portfolio_rows = _observation(
        as_of_date=as_of_date,
        risk=risk,
        regime=regime,
        holdings=holdings,
        scorecard_dir=scorecard_dir,
        include_holdings=True,
    )
    phase5 = _phase5_contract(phase5_audit)
    deterministic_summary = {
        "demo_contract_version": "final_mvp_v1",
        "metadata": {
            "observation_date": current["observation_date"],
            "active_risk_portfolio_formation_date": current[
                "active_risk_portfolio_formation_date"
            ],
            "next_rebalance_formation_date": current[
                "next_rebalance_formation_date"
            ],
            "module_latest_data_dates": _module_latest_dates(
                factors=factors,
                risk=risk,
                holdings=holdings,
                scorecard_dir=scorecard_dir,
                phase5_audit=phase5_audit,
            ),
            "execution_mode": "offline_read_only",
        },
        "current_observation": current,
        "portfolios": {
            "active": _portfolio_summary(
                portfolio_rows,
                role="active_risk_portfolio",
            ),
            "next_rebalance": _portfolio_summary(
                portfolio_rows,
                role="next_rebalance_portfolio",
            ),
        },
        "phase_5a_fundamental_feasibility": phase5,
        "historical_case_2023": _historical_case(
            risk=risk,
            regime=regime,
            holdings=holdings,
            scorecard_dir=scorecard_dir,
        ),
        "limitations": [
            "The synthetic portfolio uses a current-membership S&P 500 proxy and is survivorship-biased.",
            "All risk values are post-close observations, not intraday forecasts or trade instructions.",
            "Extreme price-momentum signals may reflect corporate actions or ticker-history discontinuities.",
            "Phase 5A is a June 30 feasibility audit and is not a date-aligned fundamental signal for May 29.",
            "Phase 5B, Phase 7 crowding, and the full Phase 8 AI research layer remain deferred.",
        ],
    }
    evidence = _build_evidence(
        deterministic_summary,
        builder=evidence_builder,
    )
    summary = {**deterministic_summary, "evidence_preview": evidence}

    date_label = iso_date(as_of_date)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / f"demo_summary_{date_label}.json", summary)

    source_scorecard = scorecard_dir / f"scorecard_{date_label}.csv"
    scorecard_bytes = (
        source_scorecard.read_bytes()
        if source_scorecard.is_file()
        else pd.DataFrame(
            current["deterministic_scorecard"]["rows"]
        ).to_csv(index=False).encode("utf-8")
    )
    atomic_write_bytes(
        output_dir / f"demo_scorecard_{date_label}.csv",
        scorecard_bytes,
    )
    atomic_write_bytes(
        output_dir / f"demo_portfolio_{date_label}.csv",
        portfolio_rows.to_csv(index=False).encode("utf-8"),
    )
    atomic_write_bytes(
        output_dir / f"demo_report_{date_label}.md",
        _markdown_report(summary).encode("utf-8"),
    )
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the offline final MVP integration demo."
    )
    parser.add_argument(
        "--as-of-date",
        required=True,
        help="Exact observation date, for example 2026-05-29.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    as_of_date = parse_as_of_date(args.as_of_date)
    summary = run_demo(as_of_date=as_of_date)
    output_path = (
        DEFAULT_DEMO_OUTPUT_DIR
        / f"demo_summary_{iso_date(as_of_date)}.json"
    )
    print(
        json.dumps(
            {
                "status": "complete",
                "observation_date": summary["metadata"]["observation_date"],
                "output": str(output_path.relative_to(REPO_ROOT)),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
