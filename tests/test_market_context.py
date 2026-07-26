"""Point-in-time and historical-case tests for structured market context."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.monitoring.contracts import StructuredMarketContext
from src.monitoring.market_context import (
    FEATURE_COLUMNS,
    build_structured_market_context,
)
from src.monitoring.positioning import DECILE_COLUMNS
from src.utils.io import DEFAULT_PROCESSED_DIR, write_parquet


def _without_provenance(context: StructuredMarketContext) -> dict[str, object]:
    payload = context.to_dict()
    payload.pop("provenance")
    return payload


def test_2009_context_exposes_auditable_market_and_leg_facts() -> None:
    context = build_structured_market_context(
        as_of_date=pd.Timestamp("2009-03-06"),
    )
    changes = {change.metric: change for change in context.changes}

    assert context.previous_as_of_date == "2009-03-05"
    assert context.market_return_504d == pytest.approx(
        -0.4790279277461014
    )
    assert context.market_volatility_percentile_126d == pytest.approx(
        0.9999539021804269
    )
    assert context.winner_return_5d == pytest.approx(
        -0.06383142185544755
    )
    assert context.loser_return_5d == pytest.approx(
        -0.14165959708054232
    )
    assert context.loser_minus_winner_return_5d == pytest.approx(
        -0.07782817522509487
    )
    assert context.positioning_is_observed is False
    assert (
        changes["market_return_5d"].current_value
        == context.market_return_5d
    )
    assert changes["market_return_5d"].delta == pytest.approx(
        changes["market_return_5d"].current_value
        - changes["market_return_5d"].previous_value
    )
    assert StructuredMarketContext.from_dict(context.to_dict()) == context


def test_context_is_invariant_to_future_source_changes(
    tmp_path: Path,
) -> None:
    cutoff = pd.Timestamp("2009-03-06")
    processed_dir = tmp_path / "processed"
    sources = {
        "market_features.parquet": FEATURE_COLUMNS[1:],
        "momentum_leg_structure.parquet": (
            "winner_leg_return",
            "loser_leg_return",
        ),
        "french_10_momentum_portfolios_daily.parquet": DECILE_COLUMNS,
    }

    for filename, explicit_columns in sources.items():
        frame = pd.read_parquet(DEFAULT_PROCESSED_DIR / filename)
        future = frame["date"].gt(cutoff)
        frame.loc[future, list(explicit_columns)] = 0.123
        write_parquet(frame, processed_dir / filename)

    original = build_structured_market_context(as_of_date=cutoff)
    perturbed = build_structured_market_context(
        as_of_date=cutoff,
        processed_dir=processed_dir,
    )

    assert _without_provenance(perturbed) == _without_provenance(original)
