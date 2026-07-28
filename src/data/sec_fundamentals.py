"""Phase 5A SEC Company Facts acquisition and coverage feasibility audit.

This module stops before the Phase 5B production panel.  It does only four
things:

1. resolve the latest eligible 12-1 price-momentum universe;
2. fetch Company Facts once per distinct CIK, cache first;
3. test whether the approved PIT quarterly signals are constructible;
4. report coverage by metric, current sector, and current portfolio leg.

No historical alignment panel, normalization, threshold calibration, breadth
metric, or production risk flag is built here.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.data.sec_edgar import (
    CIK_OVERRIDES,
    DEFAULT_SEC_DIR,
    fetch_company_facts_by_cik,
    fetch_ticker_map,
    to_sec_ticker,
)
from src.data.sp500 import classification_snapshot_from_nasdaq
from src.data.trading_calendar import build_trading_calendar
from src.portfolio.momentum import build_momentum_signals
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    DEFAULT_RAW_DIR,
    atomic_write_bytes,
    read_json,
    write_json,
)


ALLOWED_FORMS = frozenset({"10-Q", "10-Q/A", "10-K", "10-K/A"})
DIRECT_QUARTER_DAYS = (70, 110)
YTD_NINE_MONTH_DAYS = (245, 300)
ANNUAL_DAYS = (330, 380)
CONSECUTIVE_QUARTER_DAYS = (70, 110)
YEAR_OVER_YEAR_DAYS = (330, 400)
STALENESS_DAYS = 180

REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)
EPS_TAGS = (
    "EarningsPerShareDiluted",
    "EarningsPerShareBasicAndDiluted",
    "EarningsPerShareBasic",
)
OPERATING_INCOME_TAGS = ("OperatingIncomeLoss",)

REVENUE_UNITS = ("USD",)
EPS_UNITS = ("USD/shares",)
OPERATING_INCOME_UNITS = ("USD",)

INAPPLICABLE_MARGIN_SECTORS = frozenset(
    {
        "finance",
        "financials",
        "real estate",
    }
)
INAPPLICABLE_MARGIN_INDUSTRY_TOKENS = (
    "bank",
    "insurance",
    "insurer",
    "investment banker",
    "investment manager",
    "real estate investment trust",
    "reit",
    "real estate",
    "finance: consumer services",
)

COMPANY_OUTPUT_COLUMNS = (
    "as_of_date",
    "symbol",
    "cik",
    "sector",
    "industry",
    "leg",
    "price_momentum",
    "price_momentum_rank",
    "membership_status",
    "survivorship_bias",
    "mapping_status",
    "company_facts_status",
    "company_facts_source",
    "revenue_status",
    "revenue_tag",
    "revenue_latest_period_end",
    "revenue_latest_available_date",
    "revenue_latest_quarter_source",
    "revenue_signal_value",
    "revenue_alternative_tags",
    "eps_status",
    "eps_tag",
    "eps_latest_period_end",
    "eps_latest_available_date",
    "eps_latest_quarter_source",
    "eps_signal_value",
    "eps_alternative_tags",
    "operating_margin_status",
    "operating_margin_revenue_tag",
    "operating_margin_tag",
    "operating_margin_latest_period_end",
    "operating_margin_latest_available_date",
    "operating_margin_revenue_quarter_source",
    "operating_margin_quarter_source",
    "operating_margin_signal_value",
    "operating_margin_alternative_tags",
    "valid_signal_count",
    "two_of_three",
    "coverage_reason",
)


@dataclass(frozen=True)
class TagCandidate:
    """One tag's visible PIT facts and parsing diagnostics."""

    priority: int
    tag: str
    quarterly: pd.DataFrame
    tag_present: bool
    expected_unit_present: bool
    eligible_observations: int
    visible_observations: int
    invalid_period_observations: int
    alternative_tags: tuple[str, ...]


def coverage_status(ratio: float) -> str:
    """Approved universe coverage policy."""

    if ratio >= 0.80:
        return "normal"
    if ratio >= 0.60:
        return "degraded"
    return "insufficient"


def leg_coverage_status(covered: int, expected: int = 10) -> str:
    """Approved 10-name portfolio-leg coverage policy."""

    if expected != 10:
        raise ValueError("Phase 5A leg coverage policy is defined for 10 names")
    if covered >= 8:
        return "normal"
    if covered >= 6:
        return "degraded"
    return "insufficient"


def peer_group_status(valid_companies: int) -> str:
    """Approved peer normalization status for later Phase 5B use."""

    if valid_companies >= 10:
        return "normal"
    if valid_companies >= 5:
        return "degraded"
    return "unavailable"


def first_trading_day_after(
    filed_date: pd.Timestamp,
    trading_dates: pd.DatetimeIndex,
) -> pd.Timestamp:
    """Conservatively make a filing visible on the following trading day."""

    dates = pd.DatetimeIndex(trading_dates).sort_values().normalize()
    position = dates.searchsorted(pd.Timestamp(filed_date).normalize(), side="right")
    if position >= len(dates):
        return pd.NaT
    return pd.Timestamp(dates[position])


def margin_applicability(sector: Any, industry: Any) -> tuple[bool, str]:
    """Reject accounting categories where operating margin is misleading."""

    sector_text = "" if pd.isna(sector) else str(sector).strip().lower()
    industry_text = "" if pd.isna(industry) else str(industry).strip().lower()
    if sector_text in INAPPLICABLE_MARGIN_SECTORS:
        return False, f"accounting_category_inapplicable:{sector_text}"
    if any(token in industry_text for token in INAPPLICABLE_MARGIN_INDUSTRY_TOKENS):
        return False, f"accounting_category_inapplicable:{industry_text}"
    return True, "applicable"


def build_eligible_universe(
    universe: pd.DataFrame,
    prices: pd.DataFrame,
    ticker_map: dict[str, int],
    *,
    classifications: pd.DataFrame | None = None,
    as_of_date: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Resolve the full price-eligible universe and map each symbol to a CIK."""

    if "symbol" not in universe:
        raise KeyError("universe missing required column: symbol")
    allowed = set(universe["symbol"].astype(str))
    signals = build_momentum_signals(
        prices.loc[prices["symbol"].astype(str).isin(allowed)].copy()
    )
    if signals.empty:
        raise ValueError("no 12-1 price momentum signals are available")
    dates = pd.DatetimeIndex(signals["formation_date"].drop_duplicates()).sort_values()
    if as_of_date is None:
        formation_date = pd.Timestamp(dates[-1])
    else:
        candidates = dates[dates <= pd.Timestamp(as_of_date)]
        if not len(candidates):
            raise ValueError("no formation date exists on or before as_of_date")
        formation_date = pd.Timestamp(candidates[-1])

    selected = signals.loc[signals["formation_date"].eq(formation_date)].copy()
    selected = selected.sort_values(
        ["momentum_return", "symbol"],
        ascending=[False, True],
    ).reset_index(drop=True)
    selected["price_momentum_rank"] = np.arange(1, len(selected) + 1)
    selected = selected.rename(columns={"momentum_return": "price_momentum"})

    universe_columns = [
        column
        for column in (
            "symbol",
            "membership_status",
            "survivorship_bias",
            "sector",
        )
        if column in universe
    ]
    result = selected.loc[
        :, ["formation_date", "symbol", "price_momentum", "price_momentum_rank"]
    ].merge(
        universe.loc[:, universe_columns].drop_duplicates("symbol"),
        on="symbol",
        how="left",
        validate="one_to_one",
    )

    if classifications is not None and not classifications.empty:
        classification = classifications.loc[
            :,
            [
                column
                for column in ("symbol", "sector", "industry")
                if column in classifications
            ],
        ].drop_duplicates("symbol")
        result = result.merge(
            classification,
            on="symbol",
            how="left",
            validate="one_to_one",
            suffixes=("", "_classification"),
        )
        if "sector_classification" in result:
            result["sector"] = result["sector_classification"].combine_first(
                result.get("sector")
            )
            result = result.drop(columns="sector_classification")
    if "sector" not in result:
        result["sector"] = pd.NA
    if "industry" not in result:
        result["industry"] = pd.NA

    ciks: list[Any] = []
    mapping_status: list[str] = []
    for symbol in result["symbol"].astype(str):
        cik = CIK_OVERRIDES.get(symbol, ticker_map.get(to_sec_ticker(symbol)))
        if cik is None:
            ciks.append(pd.NA)
            mapping_status.append("unmapped")
        else:
            ciks.append(int(cik))
            mapping_status.append("mapped")
    result["cik"] = pd.array(ciks, dtype="Int64")
    result["mapping_status"] = mapping_status
    return result, formation_date


def _discover_alternative_tags(
    payload: dict[str, Any],
    *,
    approved: Iterable[str],
    tokens: Iterable[str],
) -> tuple[str, ...]:
    gaap = payload.get("facts", {}).get("us-gaap", {})
    approved_set = set(approved)
    lowered = tuple(token.lower() for token in tokens)
    return tuple(
        sorted(
            tag
            for tag in gaap
            if tag not in approved_set
            and any(token in tag.lower() for token in lowered)
        )
    )


def _visible_tag_observations(
    payload: dict[str, Any],
    *,
    tag: str,
    expected_units: tuple[str, ...],
    as_of_date: pd.Timestamp,
    trading_dates: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, bool, bool, int, int, int]:
    gaap = payload.get("facts", {}).get("us-gaap", {})
    fact = gaap.get(tag)
    if not fact:
        return pd.DataFrame(), False, False, 0, 0, 0
    units = fact.get("units", {})
    unit_present = any(unit in units for unit in expected_units)
    records: list[dict[str, Any]] = []
    eligible_observations = 0
    invalid_period_observations = 0
    for unit in expected_units:
        for observation in units.get(unit, []):
            if observation.get("form") not in ALLOWED_FORMS:
                continue
            if any(key in observation for key in ("segment", "dimensions")):
                continue
            required = {"start", "end", "filed", "val"}
            if not required.issubset(observation):
                continue
            start = pd.to_datetime(observation["start"], errors="coerce")
            end = pd.to_datetime(observation["end"], errors="coerce")
            filed = pd.to_datetime(observation["filed"], errors="coerce")
            value = pd.to_numeric(observation["val"], errors="coerce")
            if pd.isna(start) or pd.isna(end) or pd.isna(filed) or pd.isna(value):
                continue
            if start > end or end > filed:
                invalid_period_observations += 1
                continue
            eligible_observations += 1
            available = first_trading_day_after(filed, trading_dates)
            if pd.isna(available) or available > as_of_date:
                continue
            records.append(
                {
                    "start_date": pd.Timestamp(start),
                    "end_date": pd.Timestamp(end),
                    "filed_date": pd.Timestamp(filed),
                    "available_date": pd.Timestamp(available),
                    "value": float(value),
                    "duration_days": int((end - start).days),
                    "form": observation["form"],
                    "accn": observation.get("accn"),
                }
            )
    if not records:
        return (
            pd.DataFrame(),
            True,
            unit_present,
            eligible_observations,
            0,
            invalid_period_observations,
        )
    frame = pd.DataFrame(records).sort_values(
        ["start_date", "end_date", "filed_date"]
    )
    frame = frame.drop_duplicates(["start_date", "end_date"], keep="last")
    return (
        frame.reset_index(drop=True),
        True,
        unit_present,
        eligible_observations,
        len(frame),
        invalid_period_observations,
    )


def _quarterly_series(frame: pd.DataFrame, *, additive: bool) -> pd.DataFrame:
    columns = (
        "end_date",
        "available_date",
        "value",
        "quarter_source",
    )
    if frame.empty:
        return pd.DataFrame(columns=columns)
    low, high = DIRECT_QUARTER_DAYS
    direct = frame.loc[frame["duration_days"].between(low, high)].copy()
    direct["quarter_source"] = "direct_quarter"
    quarters = direct.loc[:, columns]

    if additive:
        annual = frame.loc[
            frame["duration_days"].between(*ANNUAL_DAYS)
        ]
        nine_month = frame.loc[
            frame["duration_days"].between(*YTD_NINE_MONTH_DAYS)
        ]
        derived: list[dict[str, Any]] = []
        for annual_row in annual.itertuples():
            candidates = nine_month.loc[
                nine_month["start_date"].eq(annual_row.start_date)
                & nine_month["end_date"].lt(annual_row.end_date)
            ].copy()
            if candidates.empty:
                continue
            gap = (annual_row.end_date - candidates["end_date"]).dt.days
            candidates = candidates.loc[
                gap.between(*CONSECUTIVE_QUARTER_DAYS)
            ]
            if candidates.empty:
                continue
            nine_month_row = candidates.sort_values("end_date").iloc[-1]
            derived.append(
                {
                    "end_date": annual_row.end_date,
                    "available_date": max(
                        annual_row.available_date,
                        nine_month_row["available_date"],
                    ),
                    "value": annual_row.value - nine_month_row["value"],
                    "quarter_source": "derived_q4",
                }
            )
        if derived:
            quarters = pd.concat(
                [quarters, pd.DataFrame(derived)],
                ignore_index=True,
            )

    if quarters.empty:
        return pd.DataFrame(columns=columns)
    quarters["source_priority"] = quarters["quarter_source"].map(
        {"derived_q4": 0, "direct_quarter": 1}
    )
    return (
        quarters.sort_values(
            ["end_date", "available_date", "source_priority"]
        )
        .drop_duplicates("end_date", keep="last")
        .drop(columns="source_priority")
        .sort_values("end_date")
        .reset_index(drop=True)
    )


def _tag_candidates(
    payload: dict[str, Any],
    *,
    tags: tuple[str, ...],
    units: tuple[str, ...],
    additive: bool,
    alternative_tokens: tuple[str, ...],
    as_of_date: pd.Timestamp,
    trading_dates: pd.DatetimeIndex,
) -> list[TagCandidate]:
    alternatives = _discover_alternative_tags(
        payload,
        approved=tags,
        tokens=alternative_tokens,
    )
    candidates: list[TagCandidate] = []
    for priority, tag in enumerate(tags):
        (
            observations,
            present,
            unit_present,
            eligible_count,
            visible_count,
            invalid_period_count,
        ) = (
            _visible_tag_observations(
                payload,
                tag=tag,
                expected_units=units,
                as_of_date=as_of_date,
                trading_dates=trading_dates,
            )
        )
        candidates.append(
            TagCandidate(
                priority=priority,
                tag=tag,
                quarterly=_quarterly_series(observations, additive=additive),
                tag_present=present,
                expected_unit_present=unit_present,
                eligible_observations=eligible_count,
                visible_observations=visible_count,
                invalid_period_observations=invalid_period_count,
                alternative_tags=alternatives,
            )
        )
    return candidates


def _acceleration(
    quarters: pd.DataFrame,
    *,
    revenue: bool,
) -> tuple[pd.Timestamp, pd.Timestamp, str, float] | None:
    """Return the latest strictly sequential YoY acceleration observation."""

    if len(quarters) < 6:
        return None
    ordered = quarters.sort_values("end_date").reset_index(drop=True)
    for index in range(len(ordered) - 1, 4, -1):
        window = ordered.iloc[index - 5 : index + 1]
        gaps = window["end_date"].diff().dt.days.dropna()
        if not gaps.between(*CONSECUTIVE_QUARTER_DAYS).all():
            continue
        current = ordered.iloc[index]
        previous = ordered.iloc[index - 1]
        year_ago = ordered.iloc[index - 4]
        previous_year_ago = ordered.iloc[index - 5]
        if not (
            YEAR_OVER_YEAR_DAYS[0]
            <= (current["end_date"] - year_ago["end_date"]).days
            <= YEAR_OVER_YEAR_DAYS[1]
            and YEAR_OVER_YEAR_DAYS[0]
            <= (previous["end_date"] - previous_year_ago["end_date"]).days
            <= YEAR_OVER_YEAR_DAYS[1]
        ):
            continue
        values = [
            current["value"],
            previous["value"],
            year_ago["value"],
            previous_year_ago["value"],
        ]
        if revenue:
            if min(values) <= 0:
                continue
            value = (
                current["value"] / year_ago["value"] - 1.0
                - (previous["value"] / previous_year_ago["value"] - 1.0)
            )
        else:
            current_denominator = abs(current["value"]) + abs(year_ago["value"])
            previous_denominator = (
                abs(previous["value"]) + abs(previous_year_ago["value"])
            )
            if current_denominator == 0 or previous_denominator == 0:
                continue
            value = (
                2.0
                * (current["value"] - year_ago["value"])
                / current_denominator
                - 2.0
                * (previous["value"] - previous_year_ago["value"])
                / previous_denominator
            )
        return (
            pd.Timestamp(current["end_date"]),
            pd.Timestamp(current["available_date"]),
            str(current["quarter_source"]),
            float(value),
        )
    return None


def _candidate_failure_status(candidates: list[TagCandidate]) -> str:
    if not any(candidate.tag_present for candidate in candidates):
        return "missing_tag"
    if not any(candidate.expected_unit_present for candidate in candidates):
        return "missing_unit"
    if not any(candidate.eligible_observations for candidate in candidates):
        if any(candidate.invalid_period_observations for candidate in candidates):
            return "invalid_period_dates"
        return "no_eligible_filing_observations"
    if not any(candidate.visible_observations for candidate in candidates):
        return "no_visible_filing_by_as_of"
    if not any(len(candidate.quarterly) for candidate in candidates):
        return "missing_quarterly_periods"
    return "missing_period_continuity"


def _best_acceleration(
    candidates: list[TagCandidate],
    *,
    revenue: bool,
    as_of_date: pd.Timestamp,
) -> dict[str, Any]:
    valid: list[tuple[pd.Timestamp, int, str, pd.Timestamp, str, float]] = []
    for candidate in candidates:
        result = _acceleration(candidate.quarterly, revenue=revenue)
        if result is not None:
            period_end, available_date, quarter_source, value = result
            valid.append(
                (
                    period_end,
                    -candidate.priority,
                    candidate.tag,
                    available_date,
                    quarter_source,
                    value,
                )
            )
    alternatives = sorted(
        {tag for candidate in candidates for tag in candidate.alternative_tags}
    )
    if not valid:
        visible_quarters: list[
            tuple[pd.Timestamp, int, str, pd.Timestamp, str]
        ] = []
        for candidate in candidates:
            if candidate.quarterly.empty:
                continue
            latest = candidate.quarterly.sort_values("end_date").iloc[-1]
            visible_quarters.append(
                (
                    pd.Timestamp(latest["end_date"]),
                    -candidate.priority,
                    candidate.tag,
                    pd.Timestamp(latest["available_date"]),
                    str(latest["quarter_source"]),
                )
            )
        if visible_quarters:
            (
                fallback_period_end,
                _,
                fallback_tag,
                fallback_available_date,
                fallback_quarter_source,
            ) = max(visible_quarters, key=lambda item: (item[0], item[1]))
        else:
            fallback_period_end = None
            fallback_tag = None
            fallback_available_date = None
            fallback_quarter_source = None
        return {
            "status": _candidate_failure_status(candidates),
            "tag": fallback_tag,
            "latest_period_end": fallback_period_end,
            "latest_available_date": fallback_available_date,
            "latest_quarter_source": fallback_quarter_source,
            "signal_value": None,
            "alternative_tags": alternatives,
        }
    period_end, _, tag, available_date, quarter_source, value = max(
        valid,
        key=lambda item: (item[0], item[1]),
    )
    if (as_of_date - period_end).days > STALENESS_DAYS:
        return {
            "status": "stale",
            "tag": tag,
            "latest_period_end": period_end,
            "latest_available_date": available_date,
            "latest_quarter_source": quarter_source,
            "signal_value": None,
            "alternative_tags": alternatives,
        }
    return {
        "status": "available",
        "tag": tag,
        "latest_period_end": period_end,
        "latest_available_date": available_date,
        "latest_quarter_source": quarter_source,
        "signal_value": value,
        "alternative_tags": alternatives,
    }


def _best_margin_change(
    revenue_candidates: list[TagCandidate],
    operating_candidates: list[TagCandidate],
    *,
    as_of_date: pd.Timestamp,
    sector: Any,
    industry: Any,
) -> dict[str, Any]:
    applicable, applicability_reason = margin_applicability(sector, industry)
    alternatives = sorted(
        {
            tag
            for candidate in operating_candidates
            for tag in candidate.alternative_tags
        }
    )
    if not applicable:
        return {
            "status": applicability_reason,
            "revenue_tag": None,
            "operating_tag": None,
            "latest_period_end": None,
            "latest_available_date": None,
            "revenue_quarter_source": None,
            "operating_quarter_source": None,
            "signal_value": None,
            "alternative_tags": alternatives,
        }

    valid: list[
        tuple[pd.Timestamp, int, int, str, str, pd.Timestamp, str, str, float]
    ] = []
    for revenue_candidate in revenue_candidates:
        for operating_candidate in operating_candidates:
            joined = revenue_candidate.quarterly.merge(
                operating_candidate.quarterly,
                on="end_date",
                suffixes=("_revenue", "_operating"),
            ).sort_values("end_date")
            if len(joined) < 2:
                continue
            for index in range(len(joined) - 1, 0, -1):
                current = joined.iloc[index]
                prior = joined.loc[
                    (
                        current["end_date"] - joined["end_date"]
                    ).dt.days.between(*YEAR_OVER_YEAR_DAYS)
                ]
                if prior.empty:
                    continue
                year_ago = prior.iloc[-1]
                if current["value_revenue"] <= 0 or year_ago["value_revenue"] <= 0:
                    continue
                value = (
                    current["value_operating"] / current["value_revenue"]
                    - year_ago["value_operating"] / year_ago["value_revenue"]
                )
                valid.append(
                    (
                        pd.Timestamp(current["end_date"]),
                        -revenue_candidate.priority,
                        -operating_candidate.priority,
                        revenue_candidate.tag,
                        operating_candidate.tag,
                        max(
                            pd.Timestamp(current["available_date_revenue"]),
                            pd.Timestamp(current["available_date_operating"]),
                        ),
                        str(current["quarter_source_revenue"]),
                        str(current["quarter_source_operating"]),
                        float(value),
                    )
                )
                break

    if not valid:
        if _candidate_failure_status(operating_candidates) != "missing_period_continuity":
            failure = _candidate_failure_status(operating_candidates)
        elif _candidate_failure_status(revenue_candidates) != "missing_period_continuity":
            failure = f"revenue_{_candidate_failure_status(revenue_candidates)}"
        else:
            failure = "missing_period_continuity"
        return {
            "status": failure,
            "revenue_tag": None,
            "operating_tag": None,
            "latest_period_end": None,
            "latest_available_date": None,
            "revenue_quarter_source": None,
            "operating_quarter_source": None,
            "signal_value": None,
            "alternative_tags": alternatives,
        }
    (
        period_end,
        _,
        _,
        revenue_tag,
        operating_tag,
        available_date,
        revenue_quarter_source,
        operating_quarter_source,
        value,
    ) = max(
        valid,
        key=lambda item: (item[0], item[1], item[2]),
    )
    if (as_of_date - period_end).days > STALENESS_DAYS:
        return {
            "status": "stale",
            "revenue_tag": revenue_tag,
            "operating_tag": operating_tag,
            "latest_period_end": period_end,
            "latest_available_date": available_date,
            "revenue_quarter_source": revenue_quarter_source,
            "operating_quarter_source": operating_quarter_source,
            "signal_value": None,
            "alternative_tags": alternatives,
        }
    return {
        "status": "available",
        "revenue_tag": revenue_tag,
        "operating_tag": operating_tag,
        "latest_period_end": period_end,
        "latest_available_date": available_date,
        "revenue_quarter_source": revenue_quarter_source,
        "operating_quarter_source": operating_quarter_source,
        "signal_value": value,
        "alternative_tags": alternatives,
    }


def _usable_filing_status(
    payload: dict[str, Any],
    *,
    as_of_date: pd.Timestamp,
    trading_dates: pd.DatetimeIndex,
) -> str:
    """Classify whether the payload contains a valid, visible 10-Q/K fact."""

    gaap = payload.get("facts", {}).get("us-gaap", {})
    if not gaap:
        return "no_us_gaap"
    allowed_observation = False
    valid_period = False
    for fact in gaap.values():
        for observations in (fact.get("units") or {}).values():
            for observation in observations:
                if observation.get("form") not in ALLOWED_FORMS:
                    continue
                allowed_observation = True
                required = {"end", "filed", "val"}
                if not required.issubset(observation):
                    continue
                end = pd.to_datetime(observation["end"], errors="coerce")
                filed = pd.to_datetime(observation["filed"], errors="coerce")
                value = pd.to_numeric(observation["val"], errors="coerce")
                start = pd.to_datetime(observation.get("start"), errors="coerce")
                if pd.isna(end) or pd.isna(filed) or pd.isna(value):
                    continue
                if end > filed or (pd.notna(start) and start > end):
                    continue
                valid_period = True
                available = first_trading_day_after(filed, trading_dates)
                if pd.notna(available) and available <= as_of_date:
                    return "usable"
    if not allowed_observation:
        return "no_allowed_filing_observations"
    if not valid_period:
        return "invalid_period_dates"
    return "no_visible_filing_by_as_of"


def audit_company_facts_payload(
    payload: dict[str, Any],
    *,
    as_of_date: pd.Timestamp,
    trading_dates: pd.DatetimeIndex,
    sector: Any,
    industry: Any,
) -> dict[str, Any]:
    """Diagnose whether one issuer supports the three approved signals."""

    company_facts_status = _usable_filing_status(
        payload,
        as_of_date=as_of_date,
        trading_dates=trading_dates,
    )
    if company_facts_status == "no_us_gaap":
        margin_is_applicable, margin_reason = margin_applicability(
            sector,
            industry,
        )
        return {
            "company_facts_status": company_facts_status,
            "revenue_status": "no_us_gaap",
            "eps_status": "no_us_gaap",
            "operating_margin_status": (
                "no_us_gaap" if margin_is_applicable else margin_reason
            ),
            "valid_signal_count": 0,
            "two_of_three": False,
        }

    revenue_candidates = _tag_candidates(
        payload,
        tags=REVENUE_TAGS,
        units=REVENUE_UNITS,
        additive=True,
        alternative_tokens=("revenue", "sales"),
        as_of_date=as_of_date,
        trading_dates=trading_dates,
    )
    eps_candidates = _tag_candidates(
        payload,
        tags=EPS_TAGS,
        units=EPS_UNITS,
        additive=False,
        alternative_tokens=("earningspershare",),
        as_of_date=as_of_date,
        trading_dates=trading_dates,
    )
    operating_candidates = _tag_candidates(
        payload,
        tags=OPERATING_INCOME_TAGS,
        units=OPERATING_INCOME_UNITS,
        additive=True,
        alternative_tokens=("operatingincome", "operatingloss"),
        as_of_date=as_of_date,
        trading_dates=trading_dates,
    )
    revenue = _best_acceleration(
        revenue_candidates,
        revenue=True,
        as_of_date=as_of_date,
    )
    eps = _best_acceleration(
        eps_candidates,
        revenue=False,
        as_of_date=as_of_date,
    )
    margin = _best_margin_change(
        revenue_candidates,
        operating_candidates,
        as_of_date=as_of_date,
        sector=sector,
        industry=industry,
    )
    valid_count = sum(
        result["status"] == "available" for result in (revenue, eps, margin)
    )
    return {
        "company_facts_status": company_facts_status,
        "revenue_status": revenue["status"],
        "revenue_tag": revenue["tag"],
        "revenue_latest_period_end": revenue["latest_period_end"],
        "revenue_latest_available_date": revenue["latest_available_date"],
        "revenue_latest_quarter_source": revenue["latest_quarter_source"],
        "revenue_signal_value": revenue["signal_value"],
        "revenue_alternative_tags": revenue["alternative_tags"],
        "eps_status": eps["status"],
        "eps_tag": eps["tag"],
        "eps_latest_period_end": eps["latest_period_end"],
        "eps_latest_available_date": eps["latest_available_date"],
        "eps_latest_quarter_source": eps["latest_quarter_source"],
        "eps_signal_value": eps["signal_value"],
        "eps_alternative_tags": eps["alternative_tags"],
        "operating_margin_status": margin["status"],
        "operating_margin_revenue_tag": margin["revenue_tag"],
        "operating_margin_tag": margin["operating_tag"],
        "operating_margin_latest_period_end": margin["latest_period_end"],
        "operating_margin_latest_available_date": margin["latest_available_date"],
        "operating_margin_revenue_quarter_source": margin[
            "revenue_quarter_source"
        ],
        "operating_margin_quarter_source": margin["operating_quarter_source"],
        "operating_margin_signal_value": margin["signal_value"],
        "operating_margin_alternative_tags": margin["alternative_tags"],
        "valid_signal_count": valid_count,
        "two_of_three": valid_count >= 2,
    }


def _canonical_company_facts_path(raw_dir: Path, cik: int) -> Path:
    return raw_dir / f"company_facts_CIK{cik:010d}.json"


def _legacy_company_facts_path(
    raw_dir: Path,
    *,
    cik: int,
    symbols: Iterable[str],
) -> Path | None:
    for symbol in sorted(set(symbols)):
        path = raw_dir / f"company_facts_{symbol}.json"
        if not path.is_file():
            continue
        payload = read_json(path)
        try:
            payload_cik = int(str(payload.get("cik", "")).lstrip("0") or "0")
        except ValueError:
            continue
        if payload_cik == cik:
            return path
    return None


def resolve_company_facts_path(
    raw_dir: Path,
    *,
    cik: int,
    symbols: Iterable[str],
) -> tuple[Path | None, str]:
    """Use the canonical CIK cache, with old symbol caches for diagnosis only."""

    canonical = _canonical_company_facts_path(raw_dir, cik)
    if canonical.is_file():
        return canonical, "cik_cache"
    metadata_path = canonical.with_name(f"{canonical.name}.metadata.json")
    if metadata_path.is_file() and read_json(metadata_path).get("absent"):
        return None, "cached_absent"
    legacy = _legacy_company_facts_path(raw_dir, cik=cik, symbols=symbols)
    if legacy is not None:
        return legacy, "legacy_symbol_cache"
    return None, "not_acquired"


def acquisition_completeness(
    expected_ciks: Iterable[int],
    acquisition: pd.DataFrame,
) -> dict[str, Any]:
    """State whether every expected issuer reached a terminal fetch result."""

    expected = {int(value) for value in expected_ciks}
    if acquisition.empty:
        attempted: set[int] = set()
        terminal: set[int] = set()
    else:
        attempted = set(
            acquisition.loc[
                ~acquisition["status"].eq("unattempted"),
                "cik",
            ].astype(int)
        )
        terminal = set(
            acquisition.loc[
                acquisition["status"].isin(["available", "absent"]),
                "cik",
            ].astype(int)
        )
    return {
        "expected_cik_count": len(expected),
        "attempted_cik_count": len(attempted),
        "terminal_cik_count": len(terminal),
        "unattempted_cik_count": len(expected - attempted),
        "nonterminal_cik_count": len(expected - terminal),
        "complete": expected == terminal,
    }


def cached_acquisition_status(
    ciks: Iterable[int],
    *,
    raw_dir: Path,
) -> pd.DataFrame:
    """Inspect canonical payload and negative caches without network access."""

    records: list[dict[str, Any]] = []
    for cik in sorted({int(value) for value in ciks}):
        path = _canonical_company_facts_path(raw_dir, cik)
        metadata_path = path.with_name(f"{path.name}.metadata.json")
        metadata = read_json(metadata_path) if metadata_path.is_file() else {}
        if path.is_file():
            status = "available"
        elif metadata.get("absent"):
            status = "absent"
        else:
            status = "unattempted"
        records.append(
            {
                "cik": cik,
                "status": status,
                "from_cache": True,
                "path": str(path) if path.is_file() else None,
                "http_status": metadata.get("http_status"),
                "retrieval_timestamp_utc": metadata.get(
                    "retrieval_timestamp_utc"
                ),
            }
        )
    return pd.DataFrame(records)


def acquire_distinct_ciks(
    ciks: Iterable[int],
    *,
    raw_dir: Path = DEFAULT_SEC_DIR,
    keep_going: bool = False,
) -> pd.DataFrame:
    """Fetch each distinct CIK exactly once; stop safely on a transient failure."""

    records: list[dict[str, Any]] = []
    for cik in sorted({int(value) for value in ciks}):
        result = fetch_company_facts_by_cik(cik, raw_dir=raw_dir)
        if result.transient_failure:
            status = "transient_failure"
        elif result.absent:
            status = "absent"
        else:
            status = "available"
        records.append(
            {
                "cik": cik,
                "status": status,
                "from_cache": bool(result.from_cache),
                "path": None if result.path is None else str(result.path),
                "http_status": result.metadata.get("http_status"),
                "retrieval_timestamp_utc": result.metadata.get(
                    "retrieval_timestamp_utc"
                ),
            }
        )
        if status == "transient_failure" and not keep_going:
            break
    return pd.DataFrame(records)


def build_company_coverage(
    eligible: pd.DataFrame,
    holdings: pd.DataFrame,
    *,
    as_of_date: pd.Timestamp,
    trading_dates: pd.DatetimeIndex,
    raw_dir: Path = DEFAULT_SEC_DIR,
) -> pd.DataFrame:
    """Audit each issuer once, then map the result back to eligible securities."""

    active = holdings.loc[
        holdings["formation_date"].eq(as_of_date),
        ["symbol", "leg"],
    ].drop_duplicates("symbol")
    base = eligible.merge(active, on="symbol", how="left", validate="one_to_one")
    analyses: dict[int, tuple[dict[str, Any], str]] = {}
    for cik_value, group in base.dropna(subset=["cik"]).groupby("cik", sort=True):
        cik = int(cik_value)
        symbols = group["symbol"].astype(str).tolist()
        path, source = resolve_company_facts_path(
            raw_dir,
            cik=cik,
            symbols=symbols,
        )
        if path is None:
            representative = group.iloc[0]
            margin_is_applicable, margin_reason = margin_applicability(
                representative.get("sector"),
                representative.get("industry"),
            )
            missing_status = (
                "cached_absent" if source == "cached_absent" else "not_acquired"
            )
            analyses[cik] = (
                {
                    "company_facts_status": missing_status,
                    "revenue_status": missing_status,
                    "eps_status": missing_status,
                    "operating_margin_status": (
                        missing_status
                        if margin_is_applicable
                        else margin_reason
                    ),
                    "valid_signal_count": 0,
                    "two_of_three": False,
                },
                source,
            )
            continue
        payload = read_json(path)
        representative = group.iloc[0]
        analyses[cik] = (
            audit_company_facts_payload(
                payload,
                as_of_date=as_of_date,
                trading_dates=trading_dates,
                sector=representative.get("sector"),
                industry=representative.get("industry"),
            ),
            source,
        )

    records: list[dict[str, Any]] = []
    for row in base.to_dict(orient="records"):
        cik_value = row.get("cik")
        if pd.isna(cik_value):
            margin_is_applicable, margin_reason = margin_applicability(
                row.get("sector"),
                row.get("industry"),
            )
            audit = {
                "company_facts_status": "unmapped",
                "revenue_status": "unmapped",
                "eps_status": "unmapped",
                "operating_margin_status": (
                    "unmapped" if margin_is_applicable else margin_reason
                ),
                "valid_signal_count": 0,
                "two_of_three": False,
            }
            source = "unmapped"
        else:
            audit, source = analyses[int(cik_value)]
        record = {
            "as_of_date": as_of_date,
            "symbol": row["symbol"],
            "cik": cik_value,
            "sector": row.get("sector"),
            "industry": row.get("industry"),
            "leg": row.get("leg"),
            "price_momentum": row.get("price_momentum"),
            "price_momentum_rank": row.get("price_momentum_rank"),
            "membership_status": row.get("membership_status"),
            "survivorship_bias": row.get("survivorship_bias"),
            "mapping_status": row.get("mapping_status"),
            "company_facts_source": source,
            **audit,
        }
        unavailable = [
            name
            for name in ("revenue", "eps", "operating_margin")
            if record.get(f"{name}_status") != "available"
        ]
        record["coverage_reason"] = (
            "two_of_three_available"
            if record["two_of_three"]
            else "insufficient_signals:" + ",".join(unavailable)
        )
        records.append(record)

    result = pd.DataFrame(records)
    for column in (
        "revenue_alternative_tags",
        "eps_alternative_tags",
        "operating_margin_alternative_tags",
    ):
        if column not in result:
            result[column] = [[] for _ in range(len(result))]
        def serialize_tags(value: Any) -> str:
            if isinstance(value, (list, tuple)):
                tags = list(value)
            elif value is None or (not isinstance(value, str) and pd.isna(value)):
                tags = []
            else:
                tags = [str(value)]
            return json.dumps(tags, separators=(",", ":"))

        result[column] = result[column].map(serialize_tags)
    for column in COMPANY_OUTPUT_COLUMNS:
        if column not in result:
            result[column] = pd.NA
    return result.loc[:, COMPANY_OUTPUT_COLUMNS].sort_values(
        "price_momentum_rank"
    ).reset_index(drop=True)


def _with_issuer_key(company: pd.DataFrame) -> pd.DataFrame:
    frame = company.copy()
    if "symbol" in frame:
        fallback = "unmapped:" + frame["symbol"].astype(str)
    else:
        fallback = pd.Series(
            [f"row:{index}" for index in frame.index],
            index=frame.index,
        )
    if "cik" in frame:
        frame["_issuer_key"] = frame["cik"].astype("string").fillna(fallback)
    else:
        frame["_issuer_key"] = fallback
    return frame


def metric_coverage_table(company: pd.DataFrame) -> pd.DataFrame:
    """Summarize the approved seven-stage fundamental coverage funnel."""

    frame = _with_issuer_key(company)
    issuer = frame.drop_duplicates("_issuer_key", keep="first")
    eligible_security_count = int(len(frame))
    eligible_issuer_count = int(len(issuer))
    applicable_margin = ~company["operating_margin_status"].astype(str).str.startswith(
        "accounting_category_inapplicable"
    )
    specifications = (
        (
            "usable_company_facts",
            company["company_facts_status"].eq("usable"),
            pd.Series(True, index=company.index),
        ),
        (
            "revenue_acceleration",
            company["revenue_status"].eq("available"),
            pd.Series(True, index=company.index),
        ),
        (
            "eps_acceleration",
            company["eps_status"].eq("available"),
            pd.Series(True, index=company.index),
        ),
        (
            "operating_margin_change",
            company["operating_margin_status"].eq("available"),
            applicable_margin,
        ),
        (
            "two_of_three",
            company["two_of_three"].fillna(False).astype(bool),
            pd.Series(True, index=company.index),
        ),
    )
    rows: list[dict[str, Any]] = []
    for metric, covered_mask, applicable_mask in specifications:
        security_covered = int(covered_mask.sum())
        security_applicable = int(applicable_mask.sum())
        issuer_covered = int(
            issuer.loc[covered_mask.loc[issuer.index], "_issuer_key"].nunique()
        )
        issuer_applicable = int(
            issuer.loc[applicable_mask.loc[issuer.index], "_issuer_key"].nunique()
        )
        ratio = (
            issuer_covered / eligible_issuer_count
            if eligible_issuer_count
            else np.nan
        )
        applicable_ratio = (
            issuer_covered / issuer_applicable if issuer_applicable else np.nan
        )
        rows.append(
            {
                "metric": metric,
                "eligible_universe_count": eligible_security_count,
                "eligible_issuer_count": eligible_issuer_count,
                "applicable_count": issuer_applicable,
                "applicable_security_count": security_applicable,
                "covered_count": issuer_covered,
                "covered_security_count": security_covered,
                "coverage_ratio": ratio,
                "applicable_coverage_ratio": applicable_ratio,
                "coverage_status": (
                    coverage_status(ratio)
                    if eligible_issuer_count
                    else "insufficient"
                ),
            }
        )
    return pd.DataFrame(rows)


def sector_coverage_table(company: pd.DataFrame) -> pd.DataFrame:
    """Report metric and two-of-three coverage within each current sector."""

    frame = _with_issuer_key(company)
    frame["sector"] = frame["sector"].fillna("UNCLASSIFIED")
    rows: list[dict[str, Any]] = []
    for sector, group in frame.groupby("sector", sort=True):
        issuer = group.drop_duplicates("_issuer_key", keep="first")
        eligible = int(len(issuer))
        covered = int(issuer["two_of_three"].fillna(False).sum())
        revenue_available = int(issuer["revenue_status"].eq("available").sum())
        eps_available = int(issuer["eps_status"].eq("available").sum())
        margin_available = int(
            issuer["operating_margin_status"].eq("available").sum()
        )
        rows.append(
            {
                "sector": sector,
                "eligible_count": eligible,
                "eligible_security_count": int(len(group)),
                "usable_company_facts": int(
                    issuer["company_facts_status"].eq("usable").sum()
                ),
                "revenue_available": revenue_available,
                "eps_available": eps_available,
                "operating_margin_applicable": int(
                    (
                        ~issuer["operating_margin_status"]
                        .astype(str)
                        .str.startswith("accounting_category_inapplicable")
                    ).sum()
                ),
                "operating_margin_available": margin_available,
                "two_of_three_covered": covered,
                "two_of_three_ratio": covered / eligible,
                "universe_coverage_status": coverage_status(covered / eligible),
                "revenue_peer_group_status": peer_group_status(
                    revenue_available
                ),
                "eps_peer_group_status": peer_group_status(eps_available),
                "operating_margin_peer_group_status": peer_group_status(
                    margin_available
                ),
            }
        )
    return pd.DataFrame(rows)


def leg_coverage_table(company: pd.DataFrame) -> pd.DataFrame:
    """Report current long and short coverage plus exact missing symbols."""

    rows: list[dict[str, Any]] = []
    for leg in ("long", "short"):
        group = company.loc[company["leg"].eq(leg)].sort_values(
            "price_momentum_rank"
        )
        covered_mask = group["two_of_three"].fillna(False).astype(bool)
        covered = int(covered_mask.sum())
        expected = int(len(group))
        missing = group.loc[~covered_mask, "symbol"].astype(str).tolist()
        rows.append(
            {
                "leg": leg,
                "expected_names": expected,
                "covered_names": covered,
                "coverage_ratio": covered / expected if expected else np.nan,
                "coverage_status": (
                    leg_coverage_status(covered, expected)
                    if expected == 10
                    else "invalid_leg_size"
                ),
                "missing_symbols": json.dumps(missing, separators=(",", ":")),
            }
        )
    return pd.DataFrame(rows)


def missing_diagnostics_table(company: pd.DataFrame) -> pd.DataFrame:
    """Count why each metric is unavailable, including accounting categories."""

    records: list[dict[str, Any]] = []
    for metric, column in (
        ("company_facts", "company_facts_status"),
        ("revenue_acceleration", "revenue_status"),
        ("eps_acceleration", "eps_status"),
        ("operating_margin_change", "operating_margin_status"),
    ):
        counts = company[column].fillna("unavailable").value_counts()
        for reason, count in counts.items():
            records.append(
                {
                    "metric": metric,
                    "reason": reason,
                    "security_count": int(count),
                }
            )
    return pd.DataFrame(records).sort_values(
        ["metric", "security_count", "reason"],
        ascending=[True, False, True],
    ).reset_index(drop=True)


def taxonomy_diagnostics_table(company: pd.DataFrame) -> pd.DataFrame:
    """Aggregate selected and discovered alternative taxonomy tags by metric."""

    frame = _with_issuer_key(company)
    records: list[dict[str, Any]] = []
    specifications = (
        (
            "revenue_acceleration",
            "revenue_status",
            "revenue_tag",
            "revenue_alternative_tags",
        ),
        (
            "eps_acceleration",
            "eps_status",
            "eps_tag",
            "eps_alternative_tags",
        ),
        (
            "operating_margin_change",
            "operating_margin_status",
            "operating_margin_tag",
            "operating_margin_alternative_tags",
        ),
    )
    for metric, status_column, tag_column, alternative_column in specifications:
        grouped = frame.assign(
            selected_tag=frame[tag_column].fillna("NONE").astype(str)
        ).groupby([status_column, "selected_tag"], dropna=False)
        for (status, selected_tag), group in grouped:
            records.append(
                {
                    "metric": metric,
                    "diagnostic_type": "selected_tag",
                    "status": status,
                    "tag": selected_tag,
                    "issuer_count": int(group["_issuer_key"].nunique()),
                    "security_count": int(len(group)),
                }
            )
        alternatives: dict[str, set[str]] = {}
        security_counts: dict[str, int] = {}
        for row in frame[["_issuer_key", alternative_column]].itertuples(
            index=False
        ):
            try:
                tags = json.loads(row[1]) if pd.notna(row[1]) else []
            except (TypeError, json.JSONDecodeError):
                tags = []
            for tag in tags:
                alternatives.setdefault(str(tag), set()).add(str(row[0]))
                security_counts[str(tag)] = security_counts.get(str(tag), 0) + 1
        for tag, issuers in sorted(alternatives.items()):
            records.append(
                {
                    "metric": metric,
                    "diagnostic_type": "unapproved_alternative_tag",
                    "status": "discovered",
                    "tag": tag,
                    "issuer_count": len(issuers),
                    "security_count": security_counts[tag],
                }
            )
    return pd.DataFrame(records).sort_values(
        ["metric", "diagnostic_type", "issuer_count", "tag"],
        ascending=[True, True, False, True],
    ).reset_index(drop=True)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    atomic_write_bytes(
        path,
        frame.to_csv(index=False, lineterminator="\n").encode("utf-8"),
    )


def run_phase5a(
    *,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    raw_dir: Path = DEFAULT_RAW_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR / "fundamental_alignment",
    as_of_date: pd.Timestamp | None = None,
    acquire: bool = False,
    keep_going: bool = False,
) -> dict[str, Any]:
    """Run the bounded acquisition and coverage audit, then stop."""

    universe = pd.read_parquet(processed_dir / "sp500_universe.parquet")
    prices = pd.read_parquet(processed_dir / "sp500_prices.parquet")
    holdings = pd.read_parquet(
        processed_dir / "momentum_portfolio_holdings.parquet"
    )
    sec_raw_dir = raw_dir / "sec"
    ticker_map = fetch_ticker_map(raw_dir=sec_raw_dir)
    screener_path = raw_dir / "positioning" / "nasdaq_screener.json"
    classifications = (
        classification_snapshot_from_nasdaq(read_json(screener_path))
        if screener_path.is_file()
        else pd.DataFrame(columns=["symbol", "sector", "industry"])
    )
    eligible, formation_date = build_eligible_universe(
        universe,
        prices,
        ticker_map,
        classifications=classifications,
        as_of_date=as_of_date,
    )
    mapped_ciks = eligible["cik"].dropna().astype(int)
    if acquire:
        acquisition = acquire_distinct_ciks(
            mapped_ciks,
            raw_dir=sec_raw_dir,
            keep_going=keep_going,
        )
    else:
        acquisition = cached_acquisition_status(
            mapped_ciks,
            raw_dir=sec_raw_dir,
        )
    acquisition_state = acquisition_completeness(mapped_ciks, acquisition)

    calendar = build_trading_calendar(
        processed_dir=processed_dir,
        end=formation_date + pd.Timedelta(days=10),
    )
    company = build_company_coverage(
        eligible,
        holdings,
        as_of_date=formation_date,
        trading_dates=calendar.dates,
        raw_dir=sec_raw_dir,
    )
    metrics = metric_coverage_table(company)
    sectors = sector_coverage_table(company)
    legs = leg_coverage_table(company)
    missing = missing_diagnostics_table(company)
    taxonomy = taxonomy_diagnostics_table(company)
    feasibility_status = (
        "assessable"
        if acquisition_state["complete"]
        else "not_assessable_incomplete_acquisition"
    )
    for frame in (metrics, sectors, legs):
        frame["acquisition_complete"] = acquisition_state["complete"]
        frame["feasibility_status"] = feasibility_status

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "company_coverage": output_dir / "phase_5a_company_coverage.csv",
        "metric_coverage": output_dir / "phase_5a_metric_coverage.csv",
        "sector_coverage": output_dir / "phase_5a_sector_coverage.csv",
        "portfolio_leg_coverage": (
            output_dir / "phase_5a_portfolio_leg_coverage.csv"
        ),
        "missing_diagnostics": (
            output_dir / "phase_5a_missing_diagnostics.csv"
        ),
        "taxonomy_diagnostics": (
            output_dir / "phase_5a_taxonomy_diagnostics.csv"
        ),
    }
    for key, frame in (
        ("company_coverage", company),
        ("metric_coverage", metrics),
        ("sector_coverage", sectors),
        ("portfolio_leg_coverage", legs),
        ("missing_diagnostics", missing),
        ("taxonomy_diagnostics", taxonomy),
    ):
        _write_csv(frame, paths[key])
    acquisition_path = output_dir / "phase_5a_acquisition_status.csv"
    _write_csv(acquisition, acquisition_path)
    paths["acquisition_status"] = acquisition_path

    two_of_three_row = metrics.loc[metrics["metric"].eq("two_of_three")].iloc[0]
    audit = {
        "phase": "5A",
        "scope": "acquisition_and_coverage_feasibility_only",
        "as_of_date": formation_date.date().isoformat(),
        "eligible_security_count": int(len(eligible)),
        "mapped_security_count": int(eligible["cik"].notna().sum()),
        "distinct_mapped_cik_count": int(mapped_ciks.nunique()),
        "acquisition_requested": bool(acquire),
        "acquisition_complete": bool(acquisition_state["complete"]),
        "acquisition_expected_cik_count": int(
            acquisition_state["expected_cik_count"]
        ),
        "acquisition_ciks_attempted_or_inspected": int(len(acquisition)),
        "acquisition_unattempted_cik_count": int(
            acquisition_state["unattempted_cik_count"]
        ),
        "acquisition_nonterminal_cik_count": int(
            acquisition_state["nonterminal_cik_count"]
        ),
        "acquisition_status_counts": (
            {
                str(key): int(value)
                for key, value in acquisition["status"].value_counts().items()
            }
            if not acquisition.empty
            else {}
        ),
        "two_of_three_covered_count": int(two_of_three_row["covered_count"]),
        "two_of_three_coverage_ratio": float(two_of_three_row["coverage_ratio"]),
        "two_of_three_coverage_status": str(
            two_of_three_row["coverage_status"]
            if acquisition_state["complete"]
            else "not_assessable_incomplete_acquisition"
        ),
        "raw_two_of_three_coverage_status": str(
            two_of_three_row["coverage_status"]
        ),
        "membership_status": (
            str(eligible["membership_status"].dropna().iloc[0])
            if eligible["membership_status"].notna().any()
            else "unavailable"
        ),
        "survivorship_bias": bool(
            eligible["survivorship_bias"].fillna(True).all()
        ),
        "classification_status": "current_snapshot_proxy",
        "staleness_days": STALENESS_DAYS,
        "filing_availability": "first_trading_day_after_filed_date",
        "operating_margin_exclusions": (
            "banks, insurers, REITs, and other listed inapplicable industries"
        ),
        "phase_5b_authorized": False,
        "outputs": {key: str(path) for key, path in paths.items()},
    }
    write_json(output_dir / "phase_5a_audit.json", audit)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "fundamental_alignment",
    )
    parser.add_argument("--as-of-date", type=pd.Timestamp, default=None)
    parser.add_argument(
        "--acquire",
        action="store_true",
        help="fetch missing Company Facts once per distinct eligible CIK",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="continue after transient SEC failures instead of stopping safely",
    )
    args = parser.parse_args()
    audit = run_phase5a(
        processed_dir=args.processed_dir,
        raw_dir=args.raw_dir,
        output_dir=args.output_dir,
        as_of_date=args.as_of_date,
        acquire=args.acquire,
        keep_going=args.keep_going,
    )
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
