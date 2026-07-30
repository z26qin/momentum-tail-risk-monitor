from __future__ import annotations

import numpy as np
import pandas as pd

from src.monitoring.fundamental_anchor import (
    build_company_fundamental_states,
    build_fundamental_anchor,
    build_fundamental_anchor_for_date,
)


def _company_coverage(
    *,
    long_sign: float,
    short_sign: float,
    long_count: int = 10,
    short_count: int = 10,
) -> pd.DataFrame:
    records = []
    for leg, count, sign in (
        ("long", long_count, long_sign),
        ("short", short_count, short_sign),
    ):
        for index in range(count):
            records.append(
                {
                    "as_of_date": "2026-06-30",
                    "symbol": f"{leg[0].upper()}{index:02d}",
                    "leg": leg,
                    "revenue_status": "available",
                    "revenue_signal_value": sign * (index + 1),
                    "eps_status": "missing_period_continuity",
                    "eps_signal_value": np.nan,
                    "operating_margin_status": "available",
                    "operating_margin_signal_value": sign * 0.01,
                }
            )
    return pd.DataFrame(records)


def test_company_state_uses_sign_votes_without_averaging_units() -> None:
    company = _company_coverage(long_sign=1.0, short_sign=-1.0)
    states = build_company_fundamental_states(company)
    assert states.loc[states["leg"].eq("long"), "company_state"].eq(
        "supportive"
    ).all()
    assert states.loc[states["leg"].eq("short"), "company_state"].eq(
        "deteriorating"
    ).all()
    assert states["valid_measure_count"].eq(2).all()


def test_eps_is_optional_when_revenue_and_margin_are_valid() -> None:
    company = _company_coverage(long_sign=1.0, short_sign=-1.0)
    assert company["eps_signal_value"].isna().all()
    states = build_company_fundamental_states(company)
    assert states["company_state"].ne("unavailable").all()


def test_financial_margin_exclusion_can_use_revenue_and_eps() -> None:
    company = _company_coverage(long_sign=1.0, short_sign=-1.0).head(1)
    company["operating_margin_status"] = (
        "accounting_category_inapplicable:finance"
    )
    company["operating_margin_signal_value"] = np.nan
    company["eps_status"] = "available"
    company["eps_signal_value"] = 0.5
    state = build_company_fundamental_states(company).iloc[0]
    assert state["valid_measure_count"] == 2
    assert state["company_state"] == "supportive"


def test_anchor_supportive_and_deteriorating_boundaries() -> None:
    supportive = build_fundamental_anchor(
        _company_coverage(long_sign=1.0, short_sign=-1.0),
        as_of_date=pd.Timestamp("2026-06-30"),
        formation_date=pd.Timestamp("2026-06-30"),
    )
    assert supportive.status == "supportive"
    assert supportive.triggered is False
    assert supportive.long_support_share == 1.0
    assert supportive.short_improving_share == 0.0

    deteriorating = build_fundamental_anchor(
        _company_coverage(long_sign=-1.0, short_sign=1.0),
        as_of_date=pd.Timestamp("2026-06-30"),
        formation_date=pd.Timestamp("2026-06-30"),
    )
    assert deteriorating.status == "deteriorating"
    assert deteriorating.triggered is True
    assert len(deteriorating.contradiction_names) == 20


def test_anchor_requires_at_least_six_covered_names_per_leg() -> None:
    anchor = build_fundamental_anchor(
        _company_coverage(
            long_sign=1.0,
            short_sign=-1.0,
            long_count=5,
            short_count=5,
        ),
        as_of_date=pd.Timestamp("2026-06-30"),
        formation_date=pd.Timestamp("2026-06-30"),
    )
    assert anchor.status == "unavailable"
    assert anchor.triggered is None
    assert anchor.long_coverage_status == "insufficient"
    assert anchor.short_coverage_status == "insufficient"


def test_empty_supplied_coverage_fails_closed() -> None:
    anchor = build_fundamental_anchor_for_date(
        as_of_date=pd.Timestamp("2024-01-05"),
        company_coverage=pd.DataFrame(),
    )
    assert anchor.status == "unavailable"
    assert anchor.triggered is None
    assert any("No exact-date" in warning for warning in anchor.warnings)
