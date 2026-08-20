"""Tests for the deterministic macro and market-regime monitor."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.regime.market_state import (
    OUTPUT_COLUMNS,
    build_regime_history,
    build_regime_table,
    run_regime_assessment,
)
from src.utils.io import DEFAULT_PROCESSED_DIR


def _synthetic_recovery() -> pd.DataFrame:
    dates = pd.bdate_range("2000-01-03", periods=720)
    calm = np.where(np.arange(700) % 2 == 0, 0.0005, -0.0004)
    crash = np.full(10, -0.03)
    recovery = np.full(10, 0.03)
    returns = np.concatenate([calm, crash, recovery])
    return pd.DataFrame(
        {
            "date": dates,
            "mkt_total_return": returns,
            "rf": np.full(len(dates), 0.0001),
        }
    )


def _real_factors() -> pd.DataFrame:
    return pd.read_parquet(
        DEFAULT_PROCESSED_DIR / "french_research_factors_daily.parquet",
        columns=["date", "mkt_total_return", "rf"],
    )


def test_synthetic_history_transitions_from_crash_to_high_vol_recovery() -> None:
    history = build_regime_history(_synthetic_recovery())
    calm = history.iloc[699]
    trough = history.iloc[709]
    recovered = history.iloc[711]

    assert bool(calm["crash_state"]) is False
    assert bool(calm["early_recovery_state"]) is False
    assert bool(trough["crash_state"]) is True
    assert bool(trough["early_recovery_state"]) is False
    assert bool(recovered["early_recovery_state"]) is True
    assert bool(recovered["high_volatility_recovery_state"]) is True


def test_future_source_changes_cannot_change_an_earlier_table() -> None:
    factors = _real_factors()
    cutoff = pd.Timestamp("2020-03-24")
    perturbed = factors.copy()
    future = perturbed["date"].gt(cutoff)
    perturbed.loc[future, "mkt_total_return"] = np.where(
        np.arange(future.sum()) % 2 == 0,
        0.25,
        -0.25,
    )
    perturbed.loc[future, "rf"] = 0.05

    baseline = build_regime_table(factors, as_of_date=cutoff)
    after = build_regime_table(perturbed, as_of_date=cutoff)
    pd.testing.assert_frame_equal(baseline, after, check_exact=True)


def test_fixed_as_of_date_is_deterministic_and_has_the_required_schema() -> None:
    factors = _real_factors()
    cutoff = pd.Timestamp("2020-03-24")
    first = build_regime_table(factors, as_of_date=cutoff)
    second = build_regime_table(factors, as_of_date=cutoff)

    pd.testing.assert_frame_equal(first, second, check_exact=True)
    assert tuple(first.columns) == OUTPUT_COLUMNS
    assert first["as_of_date"].eq("2020-03-24").all()
    assert first["metric"].is_unique
    assert set(
        [
            "market_drawdown",
            "recovery_from_trough",
            "realized_volatility",
            "crash_state",
            "early_recovery_state",
            "high_volatility_recovery_state",
            "rate_policy_proxy",
        ]
    ).issubset(first["metric"])


def test_2020_case_separates_crash_from_recovery_transition() -> None:
    factors = _real_factors()
    crash = build_regime_table(
        factors,
        as_of_date=pd.Timestamp("2020-03-16"),
    ).set_index("metric")
    recovery = build_regime_table(
        factors,
        as_of_date=pd.Timestamp("2020-03-24"),
    ).set_index("metric")

    assert bool(crash.loc["crash_state", "triggered"]) is True
    assert bool(crash.loc["early_recovery_state", "triggered"]) is False
    assert bool(recovery.loc["crash_state", "triggered"]) is True
    assert bool(recovery.loc["early_recovery_state", "triggered"]) is True
    assert bool(
        recovery.loc["high_volatility_recovery_state", "triggered"]
    ) is True


def test_liquidity_is_explicitly_unavailable_not_false() -> None:
    table = build_regime_table(
        _real_factors(),
        as_of_date=pd.Timestamp("2020-03-24"),
    ).set_index("metric")
    liquidity = table.loc["liquidity_proxy"]

    assert liquidity["state"] == "unavailable"
    assert pd.isna(liquidity["value"])
    assert pd.isna(liquidity["threshold"])
    assert pd.isna(liquidity["triggered"])


def test_runner_writes_a_reproducible_csv(tmp_path: Path) -> None:
    table, path = run_regime_assessment(
        as_of_date=pd.Timestamp("2020-03-24"),
        output_dir=tmp_path,
    )
    first_payload = path.read_bytes()
    second, second_path = run_regime_assessment(
        as_of_date=pd.Timestamp("2020-03-24"),
        output_dir=tmp_path,
    )

    assert path == second_path
    assert path.name == "regime_state_2020-03-24.csv"
    assert path.read_bytes() == first_payload
    pd.testing.assert_frame_equal(table, second, check_exact=True)
