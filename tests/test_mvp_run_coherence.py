"""End-to-end coherence checks for one MVP run object."""

from __future__ import annotations

from src.mvp.config import default_demo_config
from src.mvp.pipeline import MVP_RUN_SCHEMA_VERSION, run_mvp


def test_unified_run_shares_one_as_of_and_fingerprint() -> None:
    config = default_demo_config()
    result = run_mvp(config)
    assert result.schema_version == MVP_RUN_SCHEMA_VERSION
    assert result.deterministic_input.as_of_date == config.as_of_date
    assert result.unwind.as_of_date == config.as_of_date
    assert result.full_run_fingerprint == "750f22225b7d9592"
    assert result.deterministic_input.run_id == "53c34aa57bb437fc"
    assert "UMD comparison benchmark" in result.display_labels["header_state_label"]
    assert "PM momentum portfolio scorecard" in result.display_labels["scorecard_label"]
    assert "customization" in result.display_labels["scorecard_label"]
    # historical_analogs remains state-conditional aggregates, not analog retrieval.
    for item in result.deterministic_input.historical_analogs:
        assert "state" in item
        assert "tail_loss_frequency" in item
        assert "analog_date" not in item
        assert "distance" not in item


def test_second_run_is_byte_identical() -> None:
    first = run_mvp(default_demo_config()).to_dict()
    second = run_mvp(default_demo_config()).to_dict()
    assert first == second
