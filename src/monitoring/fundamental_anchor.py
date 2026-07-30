"""Lightweight fundamental anchor built on preserved Phase 5A infrastructure."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.sec_edgar import fetch_ticker_map
from src.data.sec_fundamentals import (
    build_company_coverage,
    build_eligible_universe,
    leg_coverage_status,
)
from src.data.sp500 import classification_snapshot_from_nasdaq
from src.data.trading_calendar import build_trading_calendar
from src.utils.io import (
    DEFAULT_PROCESSED_DIR,
    DEFAULT_RAW_DIR,
    read_json,
)


FUNDAMENTAL_STATES = frozenset(
    {"supportive", "mixed", "deteriorating", "unavailable"}
)

COMPANY_STATE_COLUMNS = (
    "as_of_date",
    "symbol",
    "leg",
    "company_state",
    "valid_measure_count",
    "positive_measure_count",
    "negative_measure_count",
    "neutral_measure_count",
    "available_components",
    "missing_components",
)


@dataclass(frozen=True)
class FundamentalAnchor:
    """Coverage-gated, sign-based portfolio fundamental context."""

    as_of_date: str
    formation_date: str
    status: str
    triggered: bool | None
    long_covered_count: int
    short_covered_count: int
    long_coverage_status: str
    short_coverage_status: str
    long_support_share: float | None
    short_improving_share: float | None
    revenue_support_share: float | None
    margin_support_share: float | None
    contradiction_names: tuple[str, ...]
    missing_names: tuple[str, ...]
    company_states: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in FUNDAMENTAL_STATES:
            raise ValueError(f"unsupported fundamental status: {self.status}")
        if self.status == "unavailable" and self.triggered is not None:
            raise ValueError("unavailable fundamental anchor requires null trigger")
        if self.status != "unavailable" and self.triggered is None:
            raise ValueError("available fundamental anchor requires a trigger")
        for value in (
            self.long_support_share,
            self.short_improving_share,
            self.revenue_support_share,
            self.margin_support_share,
        ):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError("fundamental shares must lie between zero and one")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _component_vote(status: Any, value: Any) -> int | None:
    if str(status) != "available" or pd.isna(value):
        return None
    numeric = float(value)
    if not np.isfinite(numeric):
        return None
    if numeric > 0.0:
        return 1
    if numeric < 0.0:
        return -1
    return 0


def build_company_fundamental_states(
    company_coverage: pd.DataFrame,
) -> pd.DataFrame:
    """Convert Phase 5A raw signal signs into company-level states.

    At least two economically valid measures are required. Raw values are
    never averaged across different units.
    """

    required = {
        "as_of_date",
        "symbol",
        "leg",
        "revenue_status",
        "revenue_signal_value",
        "eps_status",
        "eps_signal_value",
        "operating_margin_status",
        "operating_margin_signal_value",
    }
    missing = sorted(required - set(company_coverage.columns))
    if missing:
        raise KeyError(f"company coverage missing required columns: {missing}")
    frame = company_coverage.copy()
    if frame["symbol"].astype(str).duplicated().any():
        raise ValueError("company coverage contains duplicate symbols")

    records: list[dict[str, Any]] = []
    specifications = (
        ("revenue", "revenue_status", "revenue_signal_value"),
        ("eps", "eps_status", "eps_signal_value"),
        (
            "operating_margin",
            "operating_margin_status",
            "operating_margin_signal_value",
        ),
    )
    for row in frame.to_dict(orient="records"):
        votes: dict[str, int] = {}
        missing_components: list[str] = []
        for name, status_column, value_column in specifications:
            vote = _component_vote(row.get(status_column), row.get(value_column))
            if vote is None:
                missing_components.append(
                    f"{name}:{row.get(status_column, 'unavailable')}"
                )
            else:
                votes[name] = vote
        positive = sum(value > 0 for value in votes.values())
        negative = sum(value < 0 for value in votes.values())
        neutral = sum(value == 0 for value in votes.values())
        if len(votes) < 2:
            state = "unavailable"
        elif positive > negative:
            state = "supportive"
        elif negative > positive:
            state = "deteriorating"
        else:
            state = "mixed"
        records.append(
            {
                "as_of_date": str(row["as_of_date"]),
                "symbol": str(row["symbol"]),
                "leg": (
                    None if pd.isna(row.get("leg")) else str(row.get("leg"))
                ),
                "company_state": state,
                "valid_measure_count": len(votes),
                "positive_measure_count": positive,
                "negative_measure_count": negative,
                "neutral_measure_count": neutral,
                "available_components": json.dumps(
                    sorted(votes),
                    separators=(",", ":"),
                ),
                "missing_components": json.dumps(
                    sorted(missing_components),
                    separators=(",", ":"),
                ),
            }
        )
    return pd.DataFrame(records, columns=COMPANY_STATE_COLUMNS)


def _support_share(
    company_coverage: pd.DataFrame,
    *,
    status_column: str,
    value_column: str,
) -> float | None:
    available = company_coverage.loc[
        company_coverage[status_column].eq("available"),
        value_column,
    ]
    available = pd.to_numeric(available, errors="coerce").dropna()
    if available.empty:
        return None
    return float(available.gt(0.0).mean())


def unavailable_fundamental_anchor(
    *,
    as_of_date: pd.Timestamp,
    formation_date: pd.Timestamp | None = None,
    warning: str,
) -> FundamentalAnchor:
    """Return an explicit unavailable anchor."""

    selected_formation = (
        pd.Timestamp(as_of_date)
        if formation_date is None
        else pd.Timestamp(formation_date)
    )
    return FundamentalAnchor(
        as_of_date=pd.Timestamp(as_of_date).date().isoformat(),
        formation_date=selected_formation.date().isoformat(),
        status="unavailable",
        triggered=None,
        long_covered_count=0,
        short_covered_count=0,
        long_coverage_status="insufficient",
        short_coverage_status="insufficient",
        long_support_share=None,
        short_improving_share=None,
        revenue_support_share=None,
        margin_support_share=None,
        contradiction_names=(),
        missing_names=(),
        company_states=(),
        warnings=(warning,),
    )


def build_fundamental_anchor(
    company_coverage: pd.DataFrame,
    *,
    as_of_date: pd.Timestamp,
    formation_date: pd.Timestamp,
) -> FundamentalAnchor:
    """Build the lightweight long/short fundamental anchor."""

    states = build_company_fundamental_states(company_coverage)
    portfolio_states = states.loc[states["leg"].isin(["long", "short"])].copy()
    long = portfolio_states.loc[portfolio_states["leg"].eq("long")]
    short = portfolio_states.loc[portfolio_states["leg"].eq("short")]
    long_covered = long.loc[long["company_state"].ne("unavailable")]
    short_covered = short.loc[short["company_state"].ne("unavailable")]
    long_count = int(len(long_covered))
    short_count = int(len(short_covered))
    long_status = leg_coverage_status(long_count)
    short_status = leg_coverage_status(short_count)

    long_support = (
        None
        if long_count == 0
        else float(long_covered["company_state"].eq("supportive").mean())
    )
    short_improving = (
        None
        if short_count == 0
        else float(short_covered["company_state"].eq("supportive").mean())
    )
    sufficient = long_count >= 6 and short_count >= 6
    if not sufficient:
        status = "unavailable"
        triggered = None
    elif long_support is not None and short_improving is not None:
        if long_support <= 0.40 or short_improving >= 0.60:
            status = "deteriorating"
            triggered = True
        elif long_support >= 0.60 and short_improving < 0.40:
            status = "supportive"
            triggered = False
        else:
            status = "mixed"
            triggered = False
    else:
        status = "unavailable"
        triggered = None

    contradictions = tuple(
        sorted(
            [
                *long.loc[
                    long["company_state"].eq("deteriorating"),
                    "symbol",
                ].tolist(),
                *short.loc[
                    short["company_state"].eq("supportive"),
                    "symbol",
                ].tolist(),
            ]
        )
    )
    missing_names = tuple(
        sorted(
            portfolio_states.loc[
                portfolio_states["company_state"].eq("unavailable"),
                "symbol",
            ].tolist()
        )
    )
    warnings = (
        "Fundamental classifications use current membership and current sector "
        "or industry proxies.",
        "EPS acceleration is optional and has low Phase 5A coverage; it never "
        "blocks an otherwise valid revenue-plus-margin assessment.",
    )
    return FundamentalAnchor(
        as_of_date=pd.Timestamp(as_of_date).date().isoformat(),
        formation_date=pd.Timestamp(formation_date).date().isoformat(),
        status=status,
        triggered=triggered,
        long_covered_count=long_count,
        short_covered_count=short_count,
        long_coverage_status=long_status,
        short_coverage_status=short_status,
        long_support_share=long_support,
        short_improving_share=short_improving,
        revenue_support_share=_support_share(
            company_coverage.loc[company_coverage["leg"].isin(["long", "short"])],
            status_column="revenue_status",
            value_column="revenue_signal_value",
        ),
        margin_support_share=_support_share(
            company_coverage.loc[company_coverage["leg"].isin(["long", "short"])],
            status_column="operating_margin_status",
            value_column="operating_margin_signal_value",
        ),
        contradiction_names=contradictions,
        missing_names=missing_names,
        company_states=tuple(
            portfolio_states.sort_values(["leg", "symbol"]).to_dict(
                orient="records"
            )
        ),
        warnings=warnings,
    )


def build_exact_date_company_coverage(
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    raw_dir: Path = DEFAULT_RAW_DIR,
) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Build an in-memory Phase 5A coverage snapshot without acquisition."""

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
        as_of_date=pd.Timestamp(as_of_date),
    )
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
    return company, formation_date


def build_fundamental_anchor_for_date(
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    raw_dir: Path = DEFAULT_RAW_DIR,
    company_coverage: pd.DataFrame | None = None,
) -> FundamentalAnchor:
    """Build an exact-date anchor, failing closed when local inputs are absent."""

    as_of_date = pd.Timestamp(as_of_date).normalize()
    try:
        if company_coverage is None:
            company_coverage, formation_date = build_exact_date_company_coverage(
                as_of_date=as_of_date,
                processed_dir=processed_dir,
                raw_dir=raw_dir,
            )
        else:
            if company_coverage.empty:
                return unavailable_fundamental_anchor(
                    as_of_date=as_of_date,
                    warning="No exact-date Phase 5A company coverage was supplied.",
                )
            formation_date = pd.to_datetime(
                company_coverage["as_of_date"]
            ).max().normalize()
        return build_fundamental_anchor(
            company_coverage,
            as_of_date=as_of_date,
            formation_date=formation_date,
        )
    except Exception as exc:  # noqa: BLE001 - optional anchor must fail closed
        return unavailable_fundamental_anchor(
            as_of_date=as_of_date,
            warning=(
                "Exact-date fundamental anchor is unavailable; the unwind "
                f"monitor remains usable without it ({exc})."
            ),
        )
