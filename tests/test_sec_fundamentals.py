from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data import sec_edgar
from src.data import sec_fundamentals as module
from src.data.sec_fundamentals import (
    _quarterly_series,
    acquisition_completeness,
    acquire_distinct_ciks,
    audit_company_facts_payload,
    build_eligible_universe,
    coverage_status,
    first_trading_day_after,
    leg_coverage_status,
    leg_coverage_table,
    margin_applicability,
    metric_coverage_table,
    missing_diagnostics_table,
    peer_group_status,
    sector_coverage_table,
)
from src.data.sp500 import classification_snapshot_from_nasdaq
from src.utils.http import FetchResult


def _observation(
    *,
    start: str,
    end: str,
    filed: str,
    value: float,
    form: str = "10-Q",
) -> dict[str, object]:
    return {
        "start": start,
        "end": end,
        "filed": filed,
        "val": value,
        "form": form,
        "accn": f"accn-{end}-{filed}",
    }


def _six_quarters(values: list[float]) -> list[dict[str, object]]:
    periods = (
        ("2024-10-01", "2024-12-31", "2025-02-01"),
        ("2025-01-01", "2025-03-31", "2025-05-01"),
        ("2025-04-01", "2025-06-30", "2025-08-01"),
        ("2025-07-01", "2025-09-30", "2025-11-01"),
        ("2025-10-01", "2025-12-31", "2026-02-01"),
        ("2026-01-01", "2026-03-31", "2026-05-01"),
    )
    return [
        _observation(start=start, end=end, filed=filed, value=value)
        for (start, end, filed), value in zip(periods, values, strict=True)
    ]


def _payload(
    *,
    revenue: list[dict[str, object]] | None = None,
    eps: list[dict[str, object]] | None = None,
    operating_income: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    gaap: dict[str, object] = {}
    if revenue is not None:
        gaap["RevenueFromContractWithCustomerExcludingAssessedTax"] = {
            "units": {"USD": revenue}
        }
    if eps is not None:
        gaap["EarningsPerShareDiluted"] = {"units": {"USD/shares": eps}}
    if operating_income is not None:
        gaap["OperatingIncomeLoss"] = {
            "units": {"USD": operating_income}
        }
    return {"cik": 1, "facts": {"us-gaap": gaap}}


def _calendar() -> pd.DatetimeIndex:
    return pd.bdate_range("2024-01-01", "2026-07-10")


def test_approved_coverage_boundaries() -> None:
    assert coverage_status(0.80) == "normal"
    assert coverage_status(0.799) == "degraded"
    assert coverage_status(0.60) == "degraded"
    assert coverage_status(0.599) == "insufficient"

    assert leg_coverage_status(8) == "normal"
    assert leg_coverage_status(7) == "degraded"
    assert leg_coverage_status(6) == "degraded"
    assert leg_coverage_status(5) == "insufficient"

    assert peer_group_status(10) == "normal"
    assert peer_group_status(9) == "degraded"
    assert peer_group_status(5) == "degraded"
    assert peer_group_status(4) == "unavailable"


def test_filing_becomes_visible_only_on_next_trading_day() -> None:
    calendar = pd.DatetimeIndex(
        [pd.Timestamp("2026-05-01"), pd.Timestamp("2026-05-04")]
    )
    assert first_trading_day_after(
        pd.Timestamp("2026-05-01"), calendar
    ) == pd.Timestamp("2026-05-04")
    assert first_trading_day_after(
        pd.Timestamp("2026-05-02"), calendar
    ) == pd.Timestamp("2026-05-04")


@pytest.mark.parametrize(
    ("sector", "industry"),
    [
        ("Finance", "Major Banks"),
        ("Finance", "Life Insurance"),
        ("Finance", "Investment Managers"),
        ("Real Estate", "Real Estate Investment Trusts"),
        ("Finance", "Real Estate"),
    ],
)
def test_margin_is_unavailable_for_incomparable_accounting_categories(
    sector: str,
    industry: str,
) -> None:
    applicable, reason = margin_applicability(sector, industry)
    assert not applicable
    assert reason.startswith("accounting_category_inapplicable")


def test_company_audit_constructs_three_current_signals() -> None:
    payload = _payload(
        revenue=_six_quarters([100, 105, 110, 115, 120, 135]),
        eps=_six_quarters([-1.0, -0.5, 0.0, 0.2, 0.5, 1.0]),
        operating_income=_six_quarters([10, 11, 12, 13, 14, 20]),
    )
    result = audit_company_facts_payload(
        payload,
        as_of_date=pd.Timestamp("2026-06-30"),
        trading_dates=_calendar(),
        sector="Technology",
        industry="Computer Software",
    )
    assert result["company_facts_status"] == "usable"
    assert result["revenue_status"] == "available"
    assert result["eps_status"] == "available"
    assert result["operating_margin_status"] == "available"
    assert result["valid_signal_count"] == 3
    assert result["two_of_three"]


def test_bank_margin_is_inapplicable_without_blocking_two_other_signals() -> None:
    payload = _payload(
        revenue=_six_quarters([100, 105, 110, 115, 120, 135]),
        eps=_six_quarters([1.0, 1.1, 1.2, 1.3, 1.5, 1.8]),
        operating_income=_six_quarters([10, 11, 12, 13, 14, 20]),
    )
    result = audit_company_facts_payload(
        payload,
        as_of_date=pd.Timestamp("2026-06-30"),
        trading_dates=_calendar(),
        sector="Finance",
        industry="Major Banks",
    )
    assert result["revenue_status"] == "available"
    assert result["eps_status"] == "available"
    assert result["operating_margin_status"].startswith(
        "accounting_category_inapplicable"
    )
    assert result["valid_signal_count"] == 2
    assert result["two_of_three"]


def test_future_filings_do_not_change_earlier_audit() -> None:
    original = _payload(
        revenue=_six_quarters([100, 105, 110, 115, 120, 135]),
        eps=_six_quarters([1.0, 1.1, 1.2, 1.3, 1.5, 1.8]),
        operating_income=_six_quarters([10, 11, 12, 13, 14, 20]),
    )
    future = _observation(
        start="2026-01-01",
        end="2026-03-31",
        filed="2026-07-15",
        value=999999,
    )
    changed = _payload(
        revenue=[*_six_quarters([100, 105, 110, 115, 120, 135]), future],
        eps=_six_quarters([1.0, 1.1, 1.2, 1.3, 1.5, 1.8]),
        operating_income=_six_quarters([10, 11, 12, 13, 14, 20]),
    )
    arguments = {
        "as_of_date": pd.Timestamp("2026-06-30"),
        "trading_dates": _calendar(),
        "sector": "Technology",
        "industry": "Computer Software",
    }
    left = audit_company_facts_payload(original, **arguments)
    right = audit_company_facts_payload(changed, **arguments)
    assert left == right


def test_future_only_tag_is_diagnosed_by_filing_filter() -> None:
    payload = _payload(
        revenue=[
            _observation(
                start="2026-01-01",
                end="2026-03-31",
                filed="2026-07-15",
                value=100,
            )
        ],
    )
    result = audit_company_facts_payload(
        payload,
        as_of_date=pd.Timestamp("2026-06-30"),
        trading_dates=_calendar(),
        sector="Technology",
        industry="Computer Software",
    )
    assert result["company_facts_status"] == "no_visible_filing_by_as_of"
    assert result["revenue_status"] == "no_visible_filing_by_as_of"


def test_impossible_period_is_rejected_and_diagnosed() -> None:
    payload = _payload(
        revenue=[
            _observation(
                start="2026-01-01",
                end="2026-03-31",
                filed="2026-02-15",
                value=100,
            )
        ],
    )
    result = audit_company_facts_payload(
        payload,
        as_of_date=pd.Timestamp("2026-06-30"),
        trading_dates=_calendar(),
        sector="Technology",
        industry="Computer Software",
    )
    assert result["company_facts_status"] == "invalid_period_dates"
    assert result["revenue_status"] == "invalid_period_dates"


def test_eps_never_uses_annual_minus_nine_month_derivation() -> None:
    frame = pd.DataFrame(
        [
            {
                "start_date": pd.Timestamp("2025-01-01"),
                "end_date": pd.Timestamp("2025-09-30"),
                "filed_date": pd.Timestamp("2025-11-01"),
                "available_date": pd.Timestamp("2025-11-03"),
                "value": 3.0,
                "duration_days": 272,
                "form": "10-Q",
                "accn": "nine-month",
            },
            {
                "start_date": pd.Timestamp("2025-01-01"),
                "end_date": pd.Timestamp("2025-12-31"),
                "filed_date": pd.Timestamp("2026-02-01"),
                "available_date": pd.Timestamp("2026-02-02"),
                "value": 5.0,
                "duration_days": 364,
                "form": "10-K",
                "accn": "annual",
            },
        ]
    )
    assert _quarterly_series(frame, additive=False).empty
    revenue_quarters = _quarterly_series(frame, additive=True)
    assert len(revenue_quarters) == 1
    assert revenue_quarters.iloc[0]["quarter_source"] == "derived_q4"
    assert revenue_quarters.iloc[0]["value"] == 2.0


def test_acquisition_deduplicates_and_sorts_ciks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[int] = []

    def fake_fetch(cik: int, *, raw_dir: Path) -> FetchResult:
        calls.append(cik)
        path = raw_dir / f"company_facts_CIK{cik:010d}.json"
        return FetchResult(
            path=path,
            metadata={"http_status": 200},
            from_cache=True,
        )

    monkeypatch.setattr(module, "fetch_company_facts_by_cik", fake_fetch)
    result = acquire_distinct_ciks(
        [2, 1, 2, 1],
        raw_dir=tmp_path,
    )
    assert calls == [1, 2]
    assert result["cik"].tolist() == [1, 2]


def test_acquisition_completeness_rejects_partial_or_transient_results() -> None:
    partial = pd.DataFrame(
        {
            "cik": [1, 2],
            "status": ["available", "transient_failure"],
        }
    )
    state = acquisition_completeness([1, 2, 3], partial)
    assert not state["complete"]
    assert state["unattempted_cik_count"] == 1
    assert state["nonterminal_cik_count"] == 2

    complete = pd.DataFrame(
        {"cik": [1, 2, 3], "status": ["available", "absent", "available"]}
    )
    assert acquisition_completeness([1, 2, 3], complete)["complete"]


def test_company_facts_cache_is_keyed_by_cik_and_keeps_headers_lazy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_cached_fetch(**kwargs: object) -> FetchResult:
        captured.update(kwargs)
        return FetchResult(
            path=Path(str(kwargs["cache_path"])),
            metadata={"http_status": 200},
            from_cache=True,
        )

    monkeypatch.setattr(sec_edgar, "cached_fetch", fake_cached_fetch)
    sec_edgar.fetch_company_facts_by_cik(123, raw_dir=tmp_path)
    assert captured["cache_path"] == (
        tmp_path / "company_facts_CIK0000000123.json"
    )
    assert callable(captured["headers"])


def test_margin_inapplicability_is_removed_from_applicable_denominator() -> None:
    company = pd.DataFrame(
        {
            "company_facts_status": ["usable", "usable"],
            "revenue_status": ["available", "available"],
            "eps_status": ["available", "available"],
            "operating_margin_status": [
                "available",
                "accounting_category_inapplicable:major banks",
            ],
            "two_of_three": [True, True],
        }
    )
    table = metric_coverage_table(company).set_index("metric")
    assert table.loc["operating_margin_change", "applicable_count"] == 1
    assert table.loc["operating_margin_change", "covered_count"] == 1


def test_coverage_audit_tables_keep_signal_and_leg_diagnostics() -> None:
    company = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "cik": pd.array([1, 2, 3], dtype="Int64"),
            "sector": ["Technology", "Technology", "Finance"],
            "leg": ["long", "long", "short"],
            "price_momentum_rank": [1, 2, 3],
            "company_facts_status": ["usable", "usable", "usable"],
            "revenue_status": ["available", "missing_tag", "available"],
            "eps_status": ["available", "available", "missing_tag"],
            "operating_margin_status": [
                "available",
                "missing_period_continuity",
                "accounting_category_inapplicable:finance",
            ],
            "two_of_three": [True, False, False],
        }
    )
    sectors = sector_coverage_table(company).set_index("sector")
    assert sectors.loc["Technology", "revenue_available"] == 1
    assert sectors.loc["Technology", "eps_available"] == 2
    assert sectors.loc["Finance", "operating_margin_applicable"] == 0

    legs = leg_coverage_table(company).set_index("leg")
    assert legs.loc["long", "covered_names"] == 1
    assert legs.loc["long", "missing_symbols"] == '["BBB"]'
    diagnostics = missing_diagnostics_table(company)
    assert (
        (diagnostics["metric"] == "revenue_acceleration")
        & (diagnostics["reason"] == "missing_tag")
    ).any()


def test_eligible_universe_ranks_all_stocks_before_portfolio_selection() -> None:
    dates = pd.date_range("2024-01-31", periods=15, freq="ME")
    prices = pd.DataFrame(
        [
            {
                "date": date,
                "symbol": symbol,
                "close_total_return_adjusted": 100 + index * slope,
            }
            for symbol, slope in (("AAA", 1.0), ("BBB", 2.0), ("CCC", 3.0))
            for index, date in enumerate(dates)
        ]
    )
    universe = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "membership_status": ["current_snapshot_proxy"] * 3,
            "survivorship_bias": [True] * 3,
            "sector": ["Technology"] * 3,
        }
    )
    classifications = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "sector": ["Technology"] * 3,
            "industry": ["Software"] * 3,
        }
    )
    result, _ = build_eligible_universe(
        universe,
        prices,
        {"AAA": 1, "BBB": 1, "CCC": 3},
        classifications=classifications,
    )
    assert len(result) == 3
    assert result.sort_values("price_momentum_rank")["symbol"].tolist() == [
        "CCC",
        "BBB",
        "AAA",
    ]
    assert result["cik"].nunique() == 2


def test_classification_snapshot_includes_industry_and_missing_values() -> None:
    payload = {
        "data": {
            "rows": [
                {
                    "symbol": "BRK/B",
                    "sector": "Finance",
                    "industry": "Insurance",
                },
                {"symbol": "AAA", "sector": "", "industry": ""},
            ]
        }
    }
    frame = classification_snapshot_from_nasdaq(payload).set_index("symbol")
    assert frame.loc["BRK-B", "industry"] == "Insurance"
    assert pd.isna(frame.loc["AAA", "sector"])
