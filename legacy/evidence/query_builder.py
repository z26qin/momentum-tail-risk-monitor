"""Build deterministic mechanism-aware retrieval requests from saved states."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from src.monitoring.contracts import (
    SCHEMA_VERSION,
    PositioningState,
    QuerySpec,
    RetrievalRequest,
    RiskState,
)
from src.utils.io import DEFAULT_OUTPUT_DIR, read_json, sha256_file, write_json


MECHANISM_ORDER = (
    "winner liquidation",
    "loser squeeze",
    "factor rotation",
    "crowding or deleveraging",
    "policy or liquidity shock",
    "rapid market rebound after stress",
    "generic risk-off or risk-on",
)
DRIVER_MECHANISMS = {
    "momentum_state": ("winner liquidation",),
    "panic_state": (
        "policy or liquidity shock",
        "generic risk-off or risk-on",
    ),
    "rebound_trigger": (
        "rapid market rebound after stress",
        "loser squeeze",
    ),
    "leg_structure": ("winner liquidation", "loser squeeze"),
    "beta_instability": ("factor rotation",),
}
QUERY_TERMS = {
    "winner liquidation": (
        "winner stocks",
        "technology",
        "selling",
        "selloff",
        "decline",
    ),
    "loser squeeze": (
        "loser stocks",
        "short covering",
        "bank stocks",
        "rally",
        "rebound",
    ),
    "factor rotation": (
        "factor rotation",
        "sector rotation",
        "technology",
        "defensive stocks",
        "stock market",
    ),
    "crowding or deleveraging": (
        "crowding",
        "leverage",
        "deleveraging",
        "liquidation",
        "market stress",
        "capital",
    ),
    "policy or liquidity shock": (
        "liquidity",
        "credit",
        "federal reserve",
        "financial system",
        "bank lending",
        "funding",
        "TALF",
    ),
    "rapid market rebound after stress": (
        "market rebound",
        "stock rally",
        "recovery",
        "stimulus",
        "rate cut",
        "short covering",
    ),
    "generic risk-off or risk-on": (
        "stock market",
        "employment",
        "job openings",
        "jobs",
        "unemployment",
        "growth",
        "GDP",
        "consumer spending",
        "inflation",
        "recession",
        "financial conditions",
    ),
}


def _append_unique(values: list[str], additions: Iterable[str]) -> None:
    for value in additions:
        if value not in values:
            values.append(value)


def _mechanisms_and_drivers(
    risk_state: RiskState,
    positioning_state: PositioningState,
) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    selected: list[str] = []
    drivers_by_mechanism: dict[str, list[str]] = {}
    all_driver_names = tuple(
        driver.feature for driver in risk_state.primary_market_drivers
    )

    for driver in risk_state.primary_market_drivers:
        mechanisms = DRIVER_MECHANISMS.get(
            driver.mechanism.strip().lower(),
            ("generic risk-off or risk-on",),
        )
        _append_unique(selected, mechanisms)
        for mechanism in mechanisms:
            drivers_by_mechanism.setdefault(mechanism, [])
            _append_unique(
                drivers_by_mechanism[mechanism],
                (driver.feature,),
            )

    if positioning_state.historical_percentile >= 0.75:
        mechanism = "crowding or deleveraging"
        _append_unique(selected, (mechanism,))
        drivers_by_mechanism.setdefault(mechanism, [])
        _append_unique(
            drivers_by_mechanism[mechanism],
            (positioning_state.proxy_name,),
        )

    generic = "generic risk-off or risk-on"
    _append_unique(selected, (generic,))
    drivers_by_mechanism.setdefault(generic, [])
    _append_unique(
        drivers_by_mechanism[generic],
        all_driver_names or (positioning_state.proxy_name,),
    )

    ordered = tuple(
        mechanism for mechanism in MECHANISM_ORDER if mechanism in selected
    )
    frozen_drivers = {
        mechanism: tuple(drivers_by_mechanism[mechanism])
        for mechanism in ordered
    }
    return ordered, frozen_drivers


def build_retrieval_request(
    *,
    risk_state: RiskState,
    positioning_state: PositioningState,
    risk_state_sha256: str,
    positioning_state_sha256: str,
    lookback_days: int = 120,
    max_documents: int = 8,
) -> RetrievalRequest:
    """Build search topics without adding facts or changing the risk signal."""

    if risk_state.as_of_date != positioning_state.as_of_date:
        raise ValueError("Risk and positioning states must share an as-of date")
    if risk_state.as_of_timestamp != positioning_state.as_of_timestamp:
        raise ValueError(
            "Risk and positioning states must share an as-of timestamp"
        )
    mechanisms, drivers_by_mechanism = _mechanisms_and_drivers(
        risk_state,
        positioning_state,
    )
    queries = tuple(
        QuerySpec(
            query_id=f"q{index:02d}",
            mechanism=mechanism,
            search_terms=QUERY_TERMS[mechanism],
            related_drivers=drivers_by_mechanism[mechanism],
            rationale=(
                "Search the cached point-in-time corpus for public context "
                f"related to the deterministic {mechanism} mechanism."
            ),
        )
        for index, mechanism in enumerate(mechanisms, start=1)
    )
    return RetrievalRequest(
        schema_version=SCHEMA_VERSION,
        as_of_date=risk_state.as_of_date,
        timestamp_cutoff=risk_state.as_of_timestamp,
        mechanisms=mechanisms,
        queries=queries,
        source_filters=("official", "news"),
        lookback_days=lookback_days,
        max_documents=max_documents,
        risk_state_sha256=risk_state_sha256,
        positioning_state_sha256=positioning_state_sha256,
        data_quality_flags=(
            "queries_are_deterministic_keyword_templates",
            "query_topics_do_not_change_the_deterministic_risk_probability",
            "retrieval_failure_must_not_be_interpreted_as_low_risk",
        ),
    )


def run_query_builder(
    *,
    risk_state_path: Path,
    positioning_state_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    max_documents: int = 8,
    lookback_days: int = 120,
) -> tuple[RetrievalRequest, Path]:
    """Load saved Gate 1 states and persist an independently replayable request."""

    risk_state = RiskState.from_dict(read_json(risk_state_path))
    positioning_state = PositioningState.from_dict(
        read_json(positioning_state_path)
    )
    request = build_retrieval_request(
        risk_state=risk_state,
        positioning_state=positioning_state,
        risk_state_sha256=sha256_file(risk_state_path),
        positioning_state_sha256=sha256_file(positioning_state_path),
        lookback_days=lookback_days,
        max_documents=max_documents,
    )
    path = (
        output_dir
        / "debug"
        / f"retrieval_request_{request.as_of_date}.json"
    )
    write_json(path, request.to_dict())
    return request, path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--risk-state", type=Path, required=True)
    parser.add_argument("--positioning-state", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-documents", type=int, default=8)
    parser.add_argument("--lookback-days", type=int, default=120)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    request, path = run_query_builder(
        risk_state_path=args.risk_state,
        positioning_state_path=args.positioning_state,
        output_dir=args.output_dir,
        lookback_days=args.lookback_days,
        max_documents=args.max_documents,
    )
    print(json.dumps(request.to_dict(), indent=2, sort_keys=True))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
