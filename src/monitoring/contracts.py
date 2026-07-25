"""Typed, dependency-light contracts for monitoring state artifacts."""

from __future__ import annotations

import dataclasses
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping
from urllib.parse import urlparse


SCHEMA_VERSION = "1.0"
RISK_SEVERITIES = frozenset({"low", "moderate", "elevated", "high"})
RISK_DIRECTIONS = frozenset(
    {"increases_risk", "decreases_risk", "neutral"}
)
PREDICTION_STATUSES = frozenset({"saved_out_of_sample_prediction"})
EVIDENCE_MECHANISMS = frozenset(
    {
        "winner liquidation",
        "loser squeeze",
        "factor rotation",
        "crowding or deleveraging",
        "policy or liquidity shock",
        "rapid market rebound after stress",
        "generic risk-off or risk-on",
    }
)
TIMESTAMP_STATUSES = frozenset(
    {
        "verified_exact",
        "verified_scheduled",
        "conservative_date_only",
        "uncertain_content_version",
    }
)
AVAILABILITY_STATUSES = frozenset(
    {
        "publicly_available_at_publication_timestamp",
        "content_version_uncertain",
    }
)
EXCLUSION_REASONS = frozenset(
    {
        "future_publication",
        "uncertain_content_version",
        "disallowed_source",
        "duplicate",
        "no_query_match",
        "outside_lookback_window",
        "top_k_truncation",
    }
)
EVIDENCE_CLASSIFICATIONS = frozenset(
    {"supporting", "contradicting", "contextual", "irrelevant"}
)
EVIDENCE_ITEM_MECHANISMS = EVIDENCE_MECHANISMS.union({"other"})
EVIDENCE_SPECIFICITIES = frozenset(
    {
        "momentum_specific",
        "mechanism_proxy",
        "generic_context",
        "not_applicable",
    }
)
CLASSIFICATION_EXCLUSION_REASONS = frozenset(
    {
        "candidate_not_classified",
        "invalid_classifier_record",
        "irrelevant_to_momentum_risk",
    }
)
DOMAIN_RISK_STATES = frozenset(
    {
        "normal",
        "stressed_precondition",
        "reversal_watch",
        "active_reversal",
    }
)
DOMAIN_COMPONENT_CATEGORIES = frozenset(
    {"precondition", "trigger", "confirmation", "proxy"}
)
DOMAIN_COMPARISONS = frozenset(
    {
        "less_than_or_equal",
        "greater_than_or_equal",
        "absolute_greater_than_or_equal",
    }
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _require_nonempty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_iso_date(value: str, field_name: str) -> None:
    _require_nonempty(value, field_name)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must use YYYY-MM-DD")


def _require_aware_timestamp(value: str, field_name: str) -> None:
    _require_nonempty(value, field_name)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")


def _require_http_url(value: str, field_name: str) -> None:
    _require_nonempty(value, field_name)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be an HTTP(S) URL")


def _require_finite(
    value: float | int | None,
    field_name: str,
    *,
    nullable: bool = False,
) -> None:
    if value is None:
        if nullable:
            return
        raise ValueError(f"{field_name} cannot be null")
    if isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite")


def _require_probability(
    value: float | None,
    field_name: str,
    *,
    nullable: bool = False,
) -> None:
    _require_finite(value, field_name, nullable=nullable)
    if value is not None and not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{field_name} must lie in [0, 1]")


def _optional_numeric_fields(instance: object, names: tuple[str, ...]) -> None:
    for name in names:
        _require_finite(
            getattr(instance, name),
            name,
            nullable=True,
        )


@dataclass(frozen=True)
class ArtifactProvenance:
    """One immutable local input used to construct a state object."""

    role: str
    path: str
    sha256: str

    def __post_init__(self) -> None:
        _require_nonempty(self.role, "role")
        _require_nonempty(self.path, "path")
        if not _SHA256_PATTERN.fullmatch(self.sha256):
            raise ValueError("sha256 must be a lowercase 64-character digest")


@dataclass(frozen=True)
class DriverContribution:
    """One exact standardized-logit contribution from the frozen B2 model."""

    feature: str
    mechanism: str
    raw_value: float | None
    imputed_value: float
    standardized_value: float
    coefficient: float
    log_odds_contribution: float
    risk_direction: str

    def __post_init__(self) -> None:
        _require_nonempty(self.feature, "feature")
        _require_nonempty(self.mechanism, "mechanism")
        _optional_numeric_fields(self, ("raw_value",))
        for name in (
            "imputed_value",
            "standardized_value",
            "coefficient",
            "log_odds_contribution",
        ):
            _require_finite(getattr(self, name), name)
        if self.risk_direction not in RISK_DIRECTIONS:
            raise ValueError(
                f"risk_direction must be one of {sorted(RISK_DIRECTIONS)}"
            )


@dataclass(frozen=True)
class LegState:
    """Trailing return and volatility summary for one momentum leg."""

    leg: str
    return_1d: float | None
    return_5d: float | None
    return_20d: float | None
    volatility_21d: float | None
    relative_to_other_volatility_21d: float | None

    def __post_init__(self) -> None:
        if self.leg not in {"winner", "loser"}:
            raise ValueError("leg must be winner or loser")
        _optional_numeric_fields(
            self,
            (
                "return_1d",
                "return_5d",
                "return_20d",
                "volatility_21d",
                "relative_to_other_volatility_21d",
            ),
        )
        if self.volatility_21d is not None and self.volatility_21d < 0.0:
            raise ValueError("volatility_21d cannot be negative")


@dataclass(frozen=True)
class MarketRegimeState:
    """Selected interpretable market and factor-regime observations."""

    vix_close: float | None
    bear_state: bool | None
    market_return_1d: float | None
    market_return_5d: float | None
    market_return_20d: float | None
    market_return_504d: float | None
    market_volatility_percentile_126d: float | None
    stress_rebound: float | None
    momentum_market_beta_126d: float | None
    momentum_market_correlation_126d: float | None
    beta_change_21d: float | None

    def __post_init__(self) -> None:
        _optional_numeric_fields(
            self,
            (
                "vix_close",
                "market_return_1d",
                "market_return_5d",
                "market_return_20d",
                "market_return_504d",
                "market_volatility_percentile_126d",
                "stress_rebound",
                "momentum_market_beta_126d",
                "momentum_market_correlation_126d",
                "beta_change_21d",
            ),
        )
        _require_probability(
            self.market_volatility_percentile_126d,
            "market_volatility_percentile_126d",
            nullable=True,
        )
        if self.momentum_market_correlation_126d is not None and not (
            -1.0 <= self.momentum_market_correlation_126d <= 1.0
        ):
            raise ValueError("momentum_market_correlation_126d left [-1, 1]")
        if self.bear_state is not None and not isinstance(self.bear_state, bool):
            raise ValueError("bear_state must be boolean or null")


@dataclass(frozen=True)
class RiskState:
    """Normalized deterministic momentum tail-risk assessment."""

    schema_version: str
    as_of_date: str
    as_of_timestamp: str
    earliest_action_date: str | None
    earliest_action_convention: str
    risk_horizon_trading_days: int
    risk_probability: float
    reconstructed_probability: float
    probability_reconciliation_error: float
    model_log_odds: float
    model_intercept: float
    risk_severity: str
    historical_percentile: float
    percentile_reference: str
    previous_as_of_date: str | None
    change_from_previous: float | None
    primary_market_drivers: tuple[DriverContribution, ...]
    winner_leg_state: LegState
    loser_leg_state: LegState
    market_regime_state: MarketRegimeState
    model_baseline: str
    model_scope: str
    model_split_id: str
    model_specification_hash: str
    data_vintage: str
    prediction_status: str
    calibration_limitations: tuple[str, ...]
    data_quality_flags: tuple[str, ...]
    provenance: tuple[ArtifactProvenance, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _require_iso_date(self.as_of_date, "as_of_date")
        _require_aware_timestamp(self.as_of_timestamp, "as_of_timestamp")
        if self.earliest_action_date is not None:
            _require_iso_date(self.earliest_action_date, "earliest_action_date")
        _require_nonempty(
            self.earliest_action_convention,
            "earliest_action_convention",
        )
        if self.risk_horizon_trading_days not in {5, 20}:
            raise ValueError("risk_horizon_trading_days must be 5 or 20")
        _require_probability(self.risk_probability, "risk_probability")
        _require_probability(
            self.reconstructed_probability,
            "reconstructed_probability",
        )
        for name in (
            "probability_reconciliation_error",
            "model_log_odds",
            "model_intercept",
        ):
            _require_finite(getattr(self, name), name)
        if self.probability_reconciliation_error < 0.0:
            raise ValueError("probability_reconciliation_error cannot be negative")
        if self.risk_severity not in RISK_SEVERITIES:
            raise ValueError(
                f"risk_severity must be one of {sorted(RISK_SEVERITIES)}"
            )
        _require_probability(
            self.historical_percentile,
            "historical_percentile",
        )
        _require_nonempty(self.percentile_reference, "percentile_reference")
        if self.previous_as_of_date is not None:
            _require_iso_date(self.previous_as_of_date, "previous_as_of_date")
        _require_finite(
            self.change_from_previous,
            "change_from_previous",
            nullable=True,
        )
        if (self.previous_as_of_date is None) != (
            self.change_from_previous is None
        ):
            raise ValueError(
                "previous_as_of_date and change_from_previous must both be set or null"
            )
        if not self.primary_market_drivers:
            raise ValueError("primary_market_drivers cannot be empty")
        for name in (
            "model_baseline",
            "model_scope",
            "model_split_id",
            "data_vintage",
        ):
            _require_nonempty(getattr(self, name), name)
        if not _SHA256_PATTERN.fullmatch(self.model_specification_hash):
            raise ValueError("model_specification_hash must be a SHA256 digest")
        _require_iso_date(self.data_vintage, "data_vintage")
        if self.prediction_status not in PREDICTION_STATUSES:
            raise ValueError(
                f"prediction_status must be one of {sorted(PREDICTION_STATUSES)}"
            )
        if not self.calibration_limitations:
            raise ValueError("calibration_limitations cannot be empty")
        if not self.data_quality_flags:
            raise ValueError("data_quality_flags cannot be empty")
        if not self.provenance:
            raise ValueError("provenance cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RiskState:
        values = dict(payload)
        values["primary_market_drivers"] = tuple(
            DriverContribution(**item)
            for item in values["primary_market_drivers"]
        )
        values["winner_leg_state"] = LegState(**values["winner_leg_state"])
        values["loser_leg_state"] = LegState(**values["loser_leg_state"])
        values["market_regime_state"] = MarketRegimeState(
            **values["market_regime_state"]
        )
        values["calibration_limitations"] = tuple(
            values["calibration_limitations"]
        )
        values["data_quality_flags"] = tuple(values["data_quality_flags"])
        values["provenance"] = tuple(
            ArtifactProvenance(**item) for item in values["provenance"]
        )
        return cls(**values)


@dataclass(frozen=True)
class PositioningState:
    """One explicitly limited public-data proxy for momentum crowding."""

    schema_version: str
    as_of_date: str
    as_of_timestamp: str
    proxy_name: str
    value: float
    historical_percentile: float
    historical_observation_count: int
    construction_window_trading_days: int
    construction: str
    interpretation: str
    is_observed_positioning: bool
    limitations: tuple[str, ...]
    production_replacements: tuple[str, ...]
    data_quality_flags: tuple[str, ...]
    provenance: tuple[ArtifactProvenance, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _require_iso_date(self.as_of_date, "as_of_date")
        _require_aware_timestamp(self.as_of_timestamp, "as_of_timestamp")
        _require_nonempty(self.proxy_name, "proxy_name")
        _require_finite(self.value, "value")
        if self.value < 0.0:
            raise ValueError("value cannot be negative")
        _require_probability(
            self.historical_percentile,
            "historical_percentile",
        )
        if self.historical_observation_count <= 0:
            raise ValueError("historical_observation_count must be positive")
        if self.construction_window_trading_days <= 0:
            raise ValueError(
                "construction_window_trading_days must be positive"
            )
        for name in ("construction", "interpretation"):
            _require_nonempty(getattr(self, name), name)
        if self.is_observed_positioning:
            raise ValueError(
                "This contract is reserved for a calculated proxy, not observed positioning"
            )
        for name in (
            "limitations",
            "production_replacements",
            "data_quality_flags",
            "provenance",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PositioningState:
        values = dict(payload)
        for name in (
            "limitations",
            "production_replacements",
            "data_quality_flags",
        ):
            values[name] = tuple(values[name])
        values["provenance"] = tuple(
            ArtifactProvenance(**item) for item in values["provenance"]
        )
        return cls(**values)


@dataclass(frozen=True)
class ContextChange:
    """One factual change from the prior momentum assessment date."""

    metric: str
    current_value: float | None
    previous_value: float | None
    delta: float | None

    def __post_init__(self) -> None:
        _require_nonempty(self.metric, "metric")
        _optional_numeric_fields(
            self,
            ("current_value", "previous_value", "delta"),
        )
        if self.current_value is None or self.previous_value is None:
            if self.delta is not None:
                raise ValueError(
                    "delta must be null when either endpoint is unavailable"
                )
        elif self.delta is None:
            raise ValueError(
                "delta is required when both endpoints are available"
            )


@dataclass(frozen=True)
class StructuredMarketContext:
    """Concise point-in-time market and momentum facts for PM review."""

    schema_version: str
    as_of_date: str
    as_of_timestamp: str
    previous_as_of_date: str | None
    market_return_504d: float | None
    market_volatility_percentile_126d: float | None
    vix_close: float | None
    market_return_1d: float | None
    market_return_5d: float | None
    market_return_20d: float | None
    momentum_return_21d: float | None
    momentum_return_63d: float | None
    momentum_drawdown_252d: float | None
    winner_return_5d: float | None
    winner_return_20d: float | None
    loser_return_5d: float | None
    loser_return_20d: float | None
    loser_minus_winner_return_5d: float | None
    loser_minus_winner_return_20d: float | None
    winner_volatility_21d: float | None
    loser_volatility_21d: float | None
    momentum_market_beta_126d: float | None
    momentum_market_correlation_126d: float | None
    beta_change_21d: float | None
    positioning_proxy_name: str
    positioning_proxy_percentile: float | None
    positioning_is_observed: bool
    changes: tuple[ContextChange, ...]
    data_quality_flags: tuple[str, ...]
    provenance: tuple[ArtifactProvenance, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _require_iso_date(self.as_of_date, "as_of_date")
        _require_aware_timestamp(self.as_of_timestamp, "as_of_timestamp")
        if self.previous_as_of_date is not None:
            _require_iso_date(
                self.previous_as_of_date,
                "previous_as_of_date",
            )
        numeric_fields = (
            "market_return_504d",
            "market_volatility_percentile_126d",
            "vix_close",
            "market_return_1d",
            "market_return_5d",
            "market_return_20d",
            "momentum_return_21d",
            "momentum_return_63d",
            "momentum_drawdown_252d",
            "winner_return_5d",
            "winner_return_20d",
            "loser_return_5d",
            "loser_return_20d",
            "loser_minus_winner_return_5d",
            "loser_minus_winner_return_20d",
            "winner_volatility_21d",
            "loser_volatility_21d",
            "momentum_market_beta_126d",
            "momentum_market_correlation_126d",
            "beta_change_21d",
            "positioning_proxy_percentile",
        )
        _optional_numeric_fields(self, numeric_fields)
        _require_probability(
            self.market_volatility_percentile_126d,
            "market_volatility_percentile_126d",
            nullable=True,
        )
        _require_probability(
            self.positioning_proxy_percentile,
            "positioning_proxy_percentile",
            nullable=True,
        )
        _require_nonempty(
            self.positioning_proxy_name,
            "positioning_proxy_name",
        )
        if not isinstance(self.positioning_is_observed, bool):
            raise ValueError("positioning_is_observed must be boolean")
        change_names = [change.metric for change in self.changes]
        if len(change_names) != len(set(change_names)):
            raise ValueError("Context change metrics must be unique")
        if not self.data_quality_flags:
            raise ValueError("data_quality_flags cannot be empty")
        if not self.provenance:
            raise ValueError("provenance cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> StructuredMarketContext:
        values = dict(payload)
        values["changes"] = tuple(
            ContextChange(**item) for item in values["changes"]
        )
        values["data_quality_flags"] = tuple(values["data_quality_flags"])
        values["provenance"] = tuple(
            ArtifactProvenance(**item) for item in values["provenance"]
        )
        return cls(**values)


@dataclass(frozen=True)
class DomainRiskComponent:
    """One transparent threshold check in the domain-risk state."""

    component: str
    category: str
    value: float | None
    threshold: float
    comparison: str
    unit: str
    available: bool
    triggered: bool
    previous_triggered: bool | None
    rationale: str

    def __post_init__(self) -> None:
        _require_nonempty(self.component, "component")
        if self.category not in DOMAIN_COMPONENT_CATEGORIES:
            raise ValueError(
                "category must be one of "
                f"{sorted(DOMAIN_COMPONENT_CATEGORIES)}"
            )
        _require_finite(self.value, "value", nullable=True)
        _require_finite(self.threshold, "threshold")
        if self.comparison not in DOMAIN_COMPARISONS:
            raise ValueError(
                "comparison must be one of "
                f"{sorted(DOMAIN_COMPARISONS)}"
            )
        _require_nonempty(self.unit, "unit")
        for name in ("available", "triggered"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        if self.previous_triggered is not None and not isinstance(
            self.previous_triggered,
            bool,
        ):
            raise ValueError("previous_triggered must be boolean or null")
        if self.available != (self.value is not None):
            raise ValueError("available must agree with value availability")
        if not self.available and self.triggered:
            raise ValueError("An unavailable component cannot trigger")
        _require_nonempty(self.rationale, "rationale")


@dataclass(frozen=True)
class DomainRiskState:
    """Transparent Daniel-Moskowitz-inspired monitoring state."""

    schema_version: str
    as_of_date: str
    as_of_timestamp: str
    state: str
    previous_state: str | None
    state_changed: bool
    component_count: int
    max_components: int
    components: tuple[DomainRiskComponent, ...]
    mechanisms: tuple[str, ...]
    interpretation: str
    legacy_benchmark_name: str | None
    legacy_benchmark_probability: float | None
    legacy_benchmark_severity: str | None
    legacy_benchmark_limitations: tuple[str, ...]
    limitations: tuple[str, ...]
    data_quality_flags: tuple[str, ...]
    provenance: tuple[ArtifactProvenance, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _require_iso_date(self.as_of_date, "as_of_date")
        _require_aware_timestamp(self.as_of_timestamp, "as_of_timestamp")
        if self.state not in DOMAIN_RISK_STATES:
            raise ValueError(
                f"state must be one of {sorted(DOMAIN_RISK_STATES)}"
            )
        if self.previous_state is not None and (
            self.previous_state not in DOMAIN_RISK_STATES
        ):
            raise ValueError("previous_state is unsupported")
        if not isinstance(self.state_changed, bool):
            raise ValueError("state_changed must be boolean")
        if self.previous_state is not None and self.state_changed != (
            self.previous_state != self.state
        ):
            raise ValueError("state_changed is inconsistent")
        if self.max_components != len(self.components):
            raise ValueError(
                "max_components must equal the component count"
            )
        if self.component_count != sum(
            component.triggered for component in self.components
        ):
            raise ValueError(
                "component_count must equal triggered components"
            )
        component_names = [
            component.component for component in self.components
        ]
        if len(component_names) != len(set(component_names)):
            raise ValueError("Domain component names must be unique")
        if set(self.mechanisms).difference(EVIDENCE_MECHANISMS):
            raise ValueError("Domain mechanisms contain unsupported values")
        _require_nonempty(self.interpretation, "interpretation")
        benchmark_fields = (
            self.legacy_benchmark_name,
            self.legacy_benchmark_probability,
            self.legacy_benchmark_severity,
        )
        if any(value is None for value in benchmark_fields) and not all(
            value is None for value in benchmark_fields
        ):
            raise ValueError(
                "Legacy benchmark name, probability, and severity must "
                "all be set or all be null"
            )
        _require_probability(
            self.legacy_benchmark_probability,
            "legacy_benchmark_probability",
            nullable=True,
        )
        if self.legacy_benchmark_probability is not None:
            if self.legacy_benchmark_severity not in RISK_SEVERITIES:
                raise ValueError("legacy_benchmark_severity is unsupported")
            if not self.legacy_benchmark_limitations:
                raise ValueError(
                    "A legacy benchmark requires explicit limitations"
                )
        for name in (
            "limitations",
            "data_quality_flags",
            "provenance",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> DomainRiskState:
        values = dict(payload)
        values["components"] = tuple(
            DomainRiskComponent(**item) for item in values["components"]
        )
        for name in (
            "mechanisms",
            "legacy_benchmark_limitations",
            "limitations",
            "data_quality_flags",
        ):
            values[name] = tuple(values[name])
        values["provenance"] = tuple(
            ArtifactProvenance(**item) for item in values["provenance"]
        )
        return cls(**values)


@dataclass(frozen=True)
class QuerySpec:
    """One deterministic mechanism-oriented search specification."""

    query_id: str
    mechanism: str
    search_terms: tuple[str, ...]
    related_drivers: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        _require_nonempty(self.query_id, "query_id")
        if self.mechanism not in EVIDENCE_MECHANISMS:
            raise ValueError(
                f"mechanism must be one of {sorted(EVIDENCE_MECHANISMS)}"
            )
        if not self.search_terms:
            raise ValueError("search_terms cannot be empty")
        if any(not value.strip() for value in self.search_terms):
            raise ValueError("search_terms cannot contain blank values")
        if not self.related_drivers:
            raise ValueError("related_drivers cannot be empty")
        if any(not value.strip() for value in self.related_drivers):
            raise ValueError("related_drivers cannot contain blank values")
        _require_nonempty(self.rationale, "rationale")


@dataclass(frozen=True)
class RetrievalRequest:
    """Deterministic request connecting market mechanisms to corpus search."""

    schema_version: str
    as_of_date: str
    timestamp_cutoff: str
    mechanisms: tuple[str, ...]
    queries: tuple[QuerySpec, ...]
    source_filters: tuple[str, ...]
    lookback_days: int
    max_documents: int
    risk_state_sha256: str
    positioning_state_sha256: str
    data_quality_flags: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _require_iso_date(self.as_of_date, "as_of_date")
        _require_aware_timestamp(self.timestamp_cutoff, "timestamp_cutoff")
        if not self.mechanisms:
            raise ValueError("mechanisms cannot be empty")
        invalid_mechanisms = set(self.mechanisms).difference(
            EVIDENCE_MECHANISMS
        )
        if invalid_mechanisms:
            raise ValueError(
                f"Unsupported mechanisms: {sorted(invalid_mechanisms)}"
            )
        if not self.queries:
            raise ValueError("queries cannot be empty")
        query_ids = [query.query_id for query in self.queries]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("query IDs must be unique")
        if set(query.mechanism for query in self.queries).difference(
            self.mechanisms
        ):
            raise ValueError("Every query mechanism must appear in mechanisms")
        if not self.source_filters:
            raise ValueError("source_filters cannot be empty")
        if not 1 <= self.lookback_days <= 3650:
            raise ValueError("lookback_days must lie in [1, 3650]")
        if not 1 <= self.max_documents <= 100:
            raise ValueError("max_documents must lie in [1, 100]")
        for name in ("risk_state_sha256", "positioning_state_sha256"):
            if not _SHA256_PATTERN.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a SHA256 digest")
        if not self.data_quality_flags:
            raise ValueError("data_quality_flags cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RetrievalRequest:
        values = dict(payload)
        values["mechanisms"] = tuple(values["mechanisms"])
        values["queries"] = tuple(
            QuerySpec(
                query_id=item["query_id"],
                mechanism=item["mechanism"],
                search_terms=tuple(item["search_terms"]),
                related_drivers=tuple(item["related_drivers"]),
                rationale=item["rationale"],
            )
            for item in values["queries"]
        )
        values["source_filters"] = tuple(values["source_filters"])
        values["data_quality_flags"] = tuple(values["data_quality_flags"])
        return cls(**values)


@dataclass(frozen=True)
class CandidateDocument:
    """Timestamped raw retrieval candidate with no evidence direction."""

    schema_version: str
    document_id: str
    title: str
    source: str
    source_category: str
    publication_timestamp: str
    timestamp_status: str
    availability_status: str
    url_or_source_id: str
    snippet_or_passage: str
    retrieval_score: float
    matched_query_ids: tuple[str, ...]
    content_sha256: str
    raw_metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        for name in (
            "document_id",
            "title",
            "source",
            "source_category",
            "snippet_or_passage",
        ):
            _require_nonempty(getattr(self, name), name)
        _require_aware_timestamp(
            self.publication_timestamp,
            "publication_timestamp",
        )
        if self.timestamp_status not in TIMESTAMP_STATUSES:
            raise ValueError(
                f"timestamp_status must be one of {sorted(TIMESTAMP_STATUSES)}"
            )
        if self.availability_status not in AVAILABILITY_STATUSES:
            raise ValueError(
                "availability_status must be one of "
                f"{sorted(AVAILABILITY_STATUSES)}"
            )
        if (
            self.timestamp_status == "uncertain_content_version"
            and self.availability_status != "content_version_uncertain"
        ):
            raise ValueError(
                "An uncertain content version requires uncertain availability"
            )
        _require_http_url(self.url_or_source_id, "url_or_source_id")
        _require_finite(self.retrieval_score, "retrieval_score")
        if self.retrieval_score < 0.0:
            raise ValueError("retrieval_score cannot be negative")
        if len(self.matched_query_ids) != len(set(self.matched_query_ids)):
            raise ValueError("matched_query_ids cannot contain duplicates")
        if not _SHA256_PATTERN.fullmatch(self.content_sha256):
            raise ValueError("content_sha256 must be a SHA256 digest")
        if not isinstance(self.raw_metadata, Mapping):
            raise ValueError("raw_metadata must be a mapping")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CandidateDocument:
        values = dict(payload)
        values["matched_query_ids"] = tuple(values["matched_query_ids"])
        values["raw_metadata"] = dict(values["raw_metadata"])
        return cls(**values)


@dataclass(frozen=True)
class RetrievalExclusion:
    """One deterministic reason a corpus record was not returned."""

    document_id: str
    reason: str
    detail: str

    def __post_init__(self) -> None:
        _require_nonempty(self.document_id, "document_id")
        if self.reason not in EXCLUSION_REASONS:
            raise ValueError(
                f"reason must be one of {sorted(EXCLUSION_REASONS)}"
            )
        _require_nonempty(self.detail, "detail")


@dataclass(frozen=True)
class RetrievalResult:
    """Inspectable retrieval output and exclusion audit."""

    schema_version: str
    as_of_date: str
    timestamp_cutoff: str
    request_sha256: str
    documents: tuple[CandidateDocument, ...]
    exclusions: tuple[RetrievalExclusion, ...]
    corpus_document_count: int
    returned_document_count: int
    data_quality_flags: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _require_iso_date(self.as_of_date, "as_of_date")
        _require_aware_timestamp(self.timestamp_cutoff, "timestamp_cutoff")
        if not _SHA256_PATTERN.fullmatch(self.request_sha256):
            raise ValueError("request_sha256 must be a SHA256 digest")
        if self.corpus_document_count < 0:
            raise ValueError("corpus_document_count cannot be negative")
        if self.returned_document_count != len(self.documents):
            raise ValueError(
                "returned_document_count must equal the document count"
            )
        document_ids = [item.document_id for item in self.documents]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("Returned document IDs must be unique")
        if not self.data_quality_flags:
            raise ValueError("data_quality_flags cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RetrievalResult:
        values = dict(payload)
        values["documents"] = tuple(
            CandidateDocument.from_dict(item) for item in values["documents"]
        )
        values["exclusions"] = tuple(
            RetrievalExclusion(**item) for item in values["exclusions"]
        )
        values["data_quality_flags"] = tuple(values["data_quality_flags"])
        return cls(**values)


@dataclass(frozen=True)
class EvidenceItem:
    """One grounded classification linked to a retrieved candidate."""

    document_id: str
    title: str
    source: str
    publication_timestamp: str
    citation_url: str
    classification: str
    mechanism: str
    related_driver: str | None
    extracted_passage: str | None
    confidence: float
    specificity: str
    classification_rationale: str
    citation_valid: bool
    exclusion_reason: str | None

    def __post_init__(self) -> None:
        for name in ("document_id", "title", "source"):
            _require_nonempty(getattr(self, name), name)
        _require_aware_timestamp(
            self.publication_timestamp,
            "publication_timestamp",
        )
        _require_http_url(self.citation_url, "citation_url")
        if self.classification not in EVIDENCE_CLASSIFICATIONS:
            raise ValueError(
                "classification must be one of "
                f"{sorted(EVIDENCE_CLASSIFICATIONS)}"
            )
        if self.mechanism not in EVIDENCE_ITEM_MECHANISMS:
            raise ValueError(
                f"mechanism must be one of {sorted(EVIDENCE_ITEM_MECHANISMS)}"
            )
        if self.related_driver is not None:
            _require_nonempty(self.related_driver, "related_driver")
        if self.extracted_passage is not None:
            _require_nonempty(self.extracted_passage, "extracted_passage")
        _require_probability(self.confidence, "confidence")
        if self.specificity not in EVIDENCE_SPECIFICITIES:
            raise ValueError(
                "specificity must be one of "
                f"{sorted(EVIDENCE_SPECIFICITIES)}"
            )
        _require_nonempty(
            self.classification_rationale,
            "classification_rationale",
        )
        if not isinstance(self.citation_valid, bool):
            raise ValueError("citation_valid must be boolean")

        if self.classification == "irrelevant":
            if self.specificity != "not_applicable":
                raise ValueError(
                    "irrelevant evidence requires not_applicable specificity"
                )
            if self.exclusion_reason is None:
                raise ValueError(
                    "irrelevant evidence requires an exclusion_reason"
                )
        else:
            if self.specificity == "not_applicable":
                raise ValueError(
                    "non-irrelevant evidence requires an applicable specificity"
                )
            if self.related_driver is None:
                raise ValueError(
                    "non-irrelevant evidence requires a related_driver"
                )
            if self.extracted_passage is None:
                raise ValueError(
                    "non-irrelevant evidence requires an extracted_passage"
                )
            if self.exclusion_reason is not None:
                raise ValueError(
                    "non-irrelevant evidence cannot have an exclusion_reason"
                )
        if self.classification == "supporting" and not self.citation_valid:
            raise ValueError("supporting evidence requires a valid citation")


@dataclass(frozen=True)
class ClassificationExclusion:
    """One candidate omitted from a valid classifier response."""

    document_id: str
    reason: str
    detail: str

    def __post_init__(self) -> None:
        _require_nonempty(self.document_id, "document_id")
        if self.reason not in CLASSIFICATION_EXCLUSION_REASONS:
            raise ValueError(
                "reason must be one of "
                f"{sorted(CLASSIFICATION_EXCLUSION_REASONS)}"
            )
        _require_nonempty(self.detail, "detail")


@dataclass(frozen=True)
class ClassificationResult:
    """Validated evidence classifications with replay provenance."""

    schema_version: str
    as_of_date: str
    timestamp_cutoff: str
    prompt_version: str
    model_identifier: str
    classifier_mode: str
    temperature: float | None
    risk_state_sha256: str
    retrieval_request_sha256: str
    retrieval_result_sha256: str
    classifier_input_sha256: str
    items: tuple[EvidenceItem, ...]
    exclusions: tuple[ClassificationExclusion, ...]
    schema_validation_passed: bool
    coverage_notes: tuple[str, ...]
    data_quality_flags: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _require_iso_date(self.as_of_date, "as_of_date")
        _require_aware_timestamp(self.timestamp_cutoff, "timestamp_cutoff")
        for name in ("prompt_version", "model_identifier", "classifier_mode"):
            _require_nonempty(getattr(self, name), name)
        _require_finite(
            self.temperature,
            "temperature",
            nullable=True,
        )
        if self.temperature is not None and self.temperature < 0.0:
            raise ValueError("temperature cannot be negative")
        for name in (
            "risk_state_sha256",
            "retrieval_request_sha256",
            "retrieval_result_sha256",
            "classifier_input_sha256",
        ):
            if not _SHA256_PATTERN.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a SHA256 digest")
        if not self.items:
            raise ValueError("items cannot be empty")
        item_ids = [item.document_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("Evidence item IDs must be unique")
        excluded_ids = [item.document_id for item in self.exclusions]
        if len(excluded_ids) != len(set(excluded_ids)):
            raise ValueError("Classification exclusion IDs must be unique")
        if set(item_ids).intersection(excluded_ids):
            raise ValueError(
                "A document cannot be both classified and excluded"
            )
        if not self.schema_validation_passed:
            raise ValueError(
                "Only schema-valid classification results may be persisted"
            )
        if not self.coverage_notes:
            raise ValueError("coverage_notes cannot be empty")
        if not self.data_quality_flags:
            raise ValueError("data_quality_flags cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ClassificationResult:
        values = dict(payload)
        values["items"] = tuple(
            EvidenceItem(**item) for item in values["items"]
        )
        values["exclusions"] = tuple(
            ClassificationExclusion(**item)
            for item in values["exclusions"]
        )
        values["coverage_notes"] = tuple(values["coverage_notes"])
        values["data_quality_flags"] = tuple(values["data_quality_flags"])
        return cls(**values)
