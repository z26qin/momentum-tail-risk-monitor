from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from src.mvp.run_demo import (
    DEFAULT_PHASE5_AUDIT_PATH,
    DEFAULT_SCORECARD_DIR,
    PRIMARY_AS_OF_DATE,
    run_demo,
)
from src.utils.io import DEFAULT_PROCESSED_DIR


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _run_in_tmp(tmp_path: Path) -> tuple[dict, Path]:
    output_dir = tmp_path / "outputs" / "demo"
    summary = run_demo(
        as_of_date=PRIMARY_AS_OF_DATE,
        output_dir=output_dir,
    )
    return summary, output_dir


def test_demo_date_alignment(tmp_path: Path) -> None:
    summary, output_dir = _run_in_tmp(tmp_path)

    assert summary["metadata"]["observation_date"] == "2026-05-29"
    assert (
        summary["metadata"]["active_risk_portfolio_formation_date"]
        == "2026-04-30"
    )
    assert (
        summary["metadata"]["next_rebalance_formation_date"]
        == "2026-05-29"
    )
    assert (
        summary["current_observation"][
            "active_risk_portfolio_formation_date"
        ]
        != summary["current_observation"]["next_rebalance_formation_date"]
    )

    portfolio = pd.read_csv(
        output_dir / "demo_portfolio_2026-05-29.csv"
    )
    dates_by_role = (
        portfolio.groupby("portfolio_role")["formation_date"]
        .unique()
        .map(list)
        .to_dict()
    )
    assert dates_by_role == {
        "active_risk_portfolio": ["2026-04-30"],
        "next_rebalance_portfolio": ["2026-05-29"],
    }
    assert "2026-06-30" not in set(portfolio["formation_date"])


def test_phase5_metrics_remain_unavailable(tmp_path: Path) -> None:
    summary, _ = _run_in_tmp(tmp_path)
    phase5 = summary["phase_5a_fundamental_feasibility"]

    assert phase5["coverage_ratio"] == 0.647887323943662
    assert phase5["coverage_percent"] == 64.79
    assert phase5["coverage_status"] == "degraded"
    assert phase5["alignment_status"] == "future_work"
    assert phase5["fundamental_ranks"] is None
    assert phase5["spearman_alignment"] is None
    assert phase5["long_short_fundamental_spread"] is None
    assert phase5["alignment_flags"] is None
    assert phase5["risk_conclusion"] is None
    assert "cannot imply safe, low, or high risk" in phase5["interpretation"]


def test_demo_is_repeatable(tmp_path: Path) -> None:
    first, output_dir = _run_in_tmp(tmp_path)
    first_bytes = (
        output_dir / "demo_summary_2026-05-29.json"
    ).read_bytes()
    second = run_demo(
        as_of_date=PRIMARY_AS_OF_DATE,
        output_dir=output_dir,
    )
    second_bytes = (
        output_dir / "demo_summary_2026-05-29.json"
    ).read_bytes()

    assert first == second
    assert first_bytes == second_bytes
    assert json.loads(first_bytes) == json.loads(second_bytes)


def test_demo_does_not_modify_existing_artifacts(tmp_path: Path) -> None:
    protected = [
        DEFAULT_PROCESSED_DIR / "french_research_factors_daily.parquet",
        DEFAULT_PROCESSED_DIR / "momentum_portfolio_holdings.parquet",
        DEFAULT_PROCESSED_DIR / "momentum_portfolio_returns.parquet",
        DEFAULT_PROCESSED_DIR / "leg_risk_history.parquet",
        DEFAULT_SCORECARD_DIR / "scorecard_2026-05-29.csv",
        DEFAULT_PHASE5_AUDIT_PATH,
    ]
    before = {path: _sha256(path) for path in protected}
    _, output_dir = _run_in_tmp(tmp_path)
    after = {path: _sha256(path) for path in protected}

    assert before == after
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "demo_portfolio_2026-05-29.csv",
        "demo_report_2026-05-29.md",
        "demo_scorecard_2026-05-29.csv",
        "demo_summary_2026-05-29.json",
    ]
    assert set(tmp_path.rglob("*.*")) == set(output_dir.iterdir())
