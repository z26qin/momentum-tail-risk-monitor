"""Frozen run configuration for the momentum tail-risk MVP.

Research assumptions (lookbacks, label quantiles, portfolio sizes) live in
component modules and are not duplicated here. This module holds operational
settings that a reviewer or PM demo should be able to change consistently.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.monitoring.scorecard import DEFAULT_CONFIG, ScorecardConfig
from src.monitoring.unwind_monitor import (
    DEFAULT_MECHANICAL_UNWIND_CONFIG,
    MechanicalUnwindConfig,
)
from src.monitoring.unwind_structure import DEFAULT_UNWIND_CONFIG, UnwindMonitorConfig
from src.risk.theme_concentration import DEFAULT_THEME_CONFIG, ThemeConcentrationConfig
from src.utils.io import DEFAULT_OUTPUT_DIR, DEFAULT_PROCESSED_DIR, REPO_ROOT

DEFAULT_AS_OF_DATE = "2026-06-30"
DEFAULT_COMPARE_TO_DATE = "2026-05-29"
DEFAULT_THRESHOLD_PROFILE = "default"
DEFAULT_HORIZON_DAYS = 20
DEFAULT_USE_LLM = False
REGRESSION_AS_OF_DATE = "2020-03-24"
REGRESSION_COMPARE_TO_DATE = "2020-02-24"
HISTORICAL_EXAMPLE_DATE = "2026-05-29"


@dataclass(frozen=True)
class MVPConfig:
    """Immutable configuration for one MVP assessment run."""

    as_of_date: str
    compare_to_date: str | None = None
    threshold_profile: str = DEFAULT_THRESHOLD_PROFILE
    horizon_days: int = DEFAULT_HORIZON_DAYS
    use_llm: bool = DEFAULT_USE_LLM
    processed_dir: Path = DEFAULT_PROCESSED_DIR
    output_dir: Path = DEFAULT_OUTPUT_DIR

    def __post_init__(self) -> None:
        pd.Timestamp(self.as_of_date)
        if self.compare_to_date is not None:
            compare = pd.Timestamp(self.compare_to_date)
            if compare >= pd.Timestamp(self.as_of_date):
                raise ValueError("compare_to_date must be strictly before as_of_date")
        if self.horizon_days not in frozenset({5, 20}):
            raise ValueError("horizon_days must be 5 or 20")
        if not self.processed_dir.is_dir():
            raise FileNotFoundError(
                f"processed data directory not found: {self.processed_dir}"
            )

    @property
    def as_of_timestamp(self) -> pd.Timestamp:
        return pd.Timestamp(self.as_of_date)

    @property
    def compare_to_timestamp(self) -> pd.Timestamp | None:
        if self.compare_to_date is None:
            return None
        return pd.Timestamp(self.compare_to_date)

    @property
    def scorecard_config(self) -> ScorecardConfig:
        from src.mvp.evidence_card import resolve_threshold_profile

        return resolve_threshold_profile(self.threshold_profile)

    @property
    def unwind_config(self) -> UnwindMonitorConfig:
        return DEFAULT_UNWIND_CONFIG

    @property
    def mechanical_unwind_config(self) -> MechanicalUnwindConfig:
        return DEFAULT_MECHANICAL_UNWIND_CONFIG

    @property
    def theme_config(self) -> ThemeConcentrationConfig:
        return DEFAULT_THEME_CONFIG

    def to_dict(self) -> dict[str, object]:
        return {
            "as_of_date": self.as_of_date,
            "compare_to_date": self.compare_to_date,
            "threshold_profile": self.threshold_profile,
            "horizon_days": self.horizon_days,
            "use_llm": self.use_llm,
            "processed_dir": str(self.processed_dir.relative_to(REPO_ROOT)),
            "output_dir": str(self.output_dir.relative_to(REPO_ROOT)),
            "scorecard_config": dataclasses.asdict(self.scorecard_config),
            "unwind_config": dataclasses.asdict(self.unwind_config),
            "mechanical_unwind_config": dataclasses.asdict(
                self.mechanical_unwind_config
            ),
            "theme_config": dataclasses.asdict(self.theme_config),
        }


def default_demo_config() -> MVPConfig:
    """Return the repository's default PM demo configuration."""

    return MVPConfig(
        as_of_date=DEFAULT_AS_OF_DATE,
        compare_to_date=DEFAULT_COMPARE_TO_DATE,
        threshold_profile=DEFAULT_THRESHOLD_PROFILE,
        horizon_days=DEFAULT_HORIZON_DAYS,
        use_llm=DEFAULT_USE_LLM,
    )
