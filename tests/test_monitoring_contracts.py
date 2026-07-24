"""Contract validation tests for deterministic monitoring artifacts."""

from __future__ import annotations

import pytest

from src.monitoring.contracts import (
    SCHEMA_VERSION,
    ArtifactProvenance,
    MarketRegimeState,
    PositioningState,
)


def _positioning_state(*, observed: bool = False) -> PositioningState:
    return PositioningState(
        schema_version=SCHEMA_VERSION,
        as_of_date="2009-03-06",
        as_of_timestamp="2009-03-06T16:00:00-05:00",
        proxy_name="test_proxy",
        value=0.02,
        historical_percentile=0.75,
        historical_observation_count=300,
        construction_window_trading_days=21,
        construction="Synthetic test construction.",
        interpretation="Synthetic test interpretation.",
        is_observed_positioning=observed,
        limitations=("Not observed positioning.",),
        production_replacements=("Institutional positioning.",),
        data_quality_flags=("synthetic_fixture",),
        provenance=(
            ArtifactProvenance(
                role="fixture",
                path="fixture.parquet",
                sha256="0" * 64,
            ),
        ),
    )


def test_positioning_contract_round_trip_and_observed_guardrail() -> None:
    state = _positioning_state()

    assert PositioningState.from_dict(state.to_dict()) == state
    with pytest.raises(ValueError, match="calculated proxy"):
        _positioning_state(observed=True)


def test_market_regime_rejects_invalid_correlation() -> None:
    with pytest.raises(ValueError, match="correlation"):
        MarketRegimeState(
            vix_close=25.0,
            bear_state=False,
            market_return_1d=0.01,
            market_return_5d=0.02,
            market_return_20d=0.03,
            market_return_504d=0.10,
            market_volatility_percentile_126d=0.80,
            stress_rebound=0.0,
            momentum_market_beta_126d=-0.2,
            momentum_market_correlation_126d=1.01,
            beta_change_21d=0.1,
        )

