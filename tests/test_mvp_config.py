"""Config boundary checks for the MVP assessment entry point."""

from __future__ import annotations

import pytest

from src.mvp.config import MVPConfig, default_demo_config
from src.monitoring.scorecard import DEFAULT_CONFIG
from src.monitoring.unwind_structure import DEFAULT_UNWIND_CONFIG
from src.risk.theme_concentration import DEFAULT_THEME_CONFIG


def test_default_demo_config_is_frozen_and_scoped() -> None:
    config = default_demo_config()
    assert config.as_of_date == "2024-01-05"
    assert config.compare_to_date == "2023-12-01"
    assert config.threshold_profile == "default"
    assert config.horizon_days == 20
    assert config.use_llm is False
    assert config.scorecard_config == DEFAULT_CONFIG
    assert config.unwind_config == DEFAULT_UNWIND_CONFIG
    assert config.theme_config == DEFAULT_THEME_CONFIG
    payload = config.to_dict()
    assert payload["processed_dir"] == "data/processed"
    assert payload["scorecard_config"]["drawdown_window"] == 63


def test_compare_date_must_precede_as_of() -> None:
    with pytest.raises(ValueError, match="strictly before"):
        MVPConfig(as_of_date="2024-01-05", compare_to_date="2024-01-05")


def test_horizon_must_be_supported() -> None:
    with pytest.raises(ValueError, match="horizon_days"):
        MVPConfig(as_of_date="2024-01-05", horizon_days=10)
