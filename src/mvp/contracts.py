"""Small, explicit contracts for the active MVP assessment path.

The legacy monitoring contracts remain available for historical replay.  These
contracts define the one current path: a literature-anchored primary state,
optional shadow and experimental views, deterministic overlays, bounded
evidence, and one PM-facing assessment.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


SCHEMA_VERSION = "mvp-v1"
PRIMARY_STATES = frozenset(
    {"normal", "bear_low_volatility", "panic_elevated"}
)
OVERLAY_READS = frozenset(
    {"confirm", "contradict", "neutral", "unavailable"}
)
EVIDENCE_STATUSES = frozenset(
    {
        "skipped_quiet_state",
        "available",
        "retrieved_unclassified",
        "unavailable",
    }
)


def _date(value: str, name: str) -> None:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{name} must be YYYY-MM-DD")


def _timestamp(value: str, name: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a UTC offset")


def _finite(value: float | None, name: str, *, nullable: bool = False) -> None:
    if value is None:
        if nullable:
            return
        raise ValueError(f"{name} cannot be null")
    if isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")


def _probability(
    value: float | None,
    name: str,
    *,
    nullable: bool = False,
) -> None:
    _finite(value, name, nullable=nullable)
    if value is not None and not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True)
class ProvenanceRef:
    role: str
    path: str
    sha256: str

    def __post_init__(self) -> None:
        if not self.role or not self.path or len(self.sha256) != 64:
            raise ValueError("provenance requires role, path, and SHA-256")


@dataclass(frozen=True)
class PrimaryRiskAssessment:
    schema_version: str
    method: str
    as_of_date: str
    as_of_timestamp: str
    horizon_days: int
    state: str
    elevated: bool
    bear_state: bool
    market_return_504d: float
    market_variance_126d: float
    panic_intensity: float | None
    elevation_rule: str
    tail_loss_probability: float
    conditioning_sample_size: int
    conditional_mean_forward_return: float
    conditional_fifth_percentile: float
    unconditional_tail_loss_probability: float
    unconditional_sample_size: int
    label_maturity_cutoff_date: str
    limitations: tuple[str, ...]
    provenance: tuple[ProvenanceRef, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported schema version")
        if self.method != "dm_pit_conditional_frequency":
            raise ValueError("primary method must be dm_pit_conditional_frequency")
        _date(self.as_of_date, "as_of_date")
        _timestamp(self.as_of_timestamp, "as_of_timestamp")
        _date(self.label_maturity_cutoff_date, "label_maturity_cutoff_date")
        if self.horizon_days not in {5, 20}:
            raise ValueError("horizon_days must be 5 or 20")
        if self.state not in PRIMARY_STATES:
            raise ValueError(f"unsupported primary state: {self.state}")
        if self.elevated != (self.state == "panic_elevated"):
            raise ValueError("elevated must agree with state")
        for name in (
            "market_return_504d",
            "market_variance_126d",
            "conditional_mean_forward_return",
            "conditional_fifth_percentile",
        ):
            _finite(getattr(self, name), name)
        _finite(self.panic_intensity, "panic_intensity", nullable=True)
        _probability(self.tail_loss_probability, "tail_loss_probability")
        _probability(
            self.unconditional_tail_loss_probability,
            "unconditional_tail_loss_probability",
        )
        if self.conditioning_sample_size <= 0 or self.unconditional_sample_size <= 0:
            raise ValueError("sample sizes must be positive")
        if not self.elevation_rule or not self.limitations or not self.provenance:
            raise ValueError("rule, limitations, and provenance are required")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class ShadowBenchmark:
    name: str
    status: str
    shadow_probability: float | None
    shadow_percentile: float | None
    agrees_with_primary: bool | None
    detail: str

    def __post_init__(self) -> None:
        if not self.name or self.status not in {"available", "unavailable"}:
            raise ValueError("shadow benchmark name/status is invalid")
        _probability(
            self.shadow_probability,
            "shadow_probability",
            nullable=True,
        )
        _probability(
            self.shadow_percentile,
            "shadow_percentile",
            nullable=True,
        )
        if not self.detail:
            raise ValueError("shadow benchmark detail is required")


@dataclass(frozen=True)
class ReversalConditions:
    status: str
    triggered_conditions: tuple[str, ...]
    total_conditions: int
    research_only: bool
    detail: str

    def __post_init__(self) -> None:
        if self.status not in {
            "normal",
            "stressed_precondition",
            "reversal_watch",
            "active_reversal",
        }:
            raise ValueError("unsupported experimental status")
        if self.total_conditions <= 0 or not self.research_only or not self.detail:
            raise ValueError("invalid experimental conditions")


@dataclass(frozen=True)
class PositioningSnapshot:
    as_of_date: str
    observation_date: str | None
    read: str
    short_interest_ratio_z: float | None
    short_interest_utilisation_z: float | None
    short_volume_share_z: float | None
    stale_trading_days: int | None
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        _date(self.as_of_date, "as_of_date")
        if self.observation_date is not None:
            _date(self.observation_date, "observation_date")
        if self.read not in OVERLAY_READS:
            raise ValueError("unsupported positioning read")
        for name in (
            "short_interest_ratio_z",
            "short_interest_utilisation_z",
            "short_volume_share_z",
        ):
            _finite(getattr(self, name), name, nullable=True)
        if not self.limitations:
            raise ValueError("positioning limitations are required")


@dataclass(frozen=True)
class NarrativeSnapshot:
    as_of_date: str
    observation_date: str | None
    read: str
    panic_volume_z: float | None
    crowding_volume_z: float | None
    riskoff_volume_z: float | None
    stale_trading_days: int | None
    available_mechanisms: tuple[str, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        _date(self.as_of_date, "as_of_date")
        if self.observation_date is not None:
            _date(self.observation_date, "observation_date")
        if self.read not in OVERLAY_READS:
            raise ValueError("unsupported narrative read")
        for name in (
            "panic_volume_z",
            "crowding_volume_z",
            "riskoff_volume_z",
        ):
            _finite(getattr(self, name), name, nullable=True)
        if not self.limitations:
            raise ValueError("narrative limitations are required")


@dataclass(frozen=True)
class EvidenceSnapshot:
    as_of_date: str
    status: str
    mode: str
    provider_name: str
    corpus_version: str | None
    corpus_sha256: str | None
    request_sha256: str | None
    retrieved_documents: int
    retrieved_document_ids: tuple[str, ...]
    excluded_documents: int
    exclusions: tuple[dict[str, Any], ...]
    retrieval_sha256: str | None
    classifier_input_sha256: str | None
    prompt_version: str | None
    model_identifier: str | None
    classifier_mode: str | None
    supporting_items: int
    contradicting_items: int
    contextual_items: int
    citations: tuple[dict[str, Any], ...]
    detail: str

    def __post_init__(self) -> None:
        _date(self.as_of_date, "as_of_date")
        if self.status not in EVIDENCE_STATUSES:
            raise ValueError("unsupported evidence status")
        if self.mode not in {
            "illustrative_fixture_replay",
            "archived_point_in_time",
        }:
            raise ValueError("unsupported evidence mode")
        if not self.provider_name:
            raise ValueError("provider_name is required")
        if min(self.retrieved_documents, self.excluded_documents) < 0:
            raise ValueError("retrieval counts cannot be negative")
        for name in (
            "corpus_sha256",
            "request_sha256",
            "retrieval_sha256",
            "classifier_input_sha256",
        ):
            value = getattr(self, name)
            if value is not None and len(value) != 64:
                raise ValueError(f"{name} must be a SHA-256 digest")
        if self.retrieved_documents != len(self.retrieved_document_ids):
            raise ValueError("retrieved_documents must match retrieved_document_ids")
        if len(set(self.retrieved_document_ids)) != len(
            self.retrieved_document_ids
        ):
            raise ValueError("retrieved_document_ids must be unique")
        if self.excluded_documents != len(self.exclusions):
            raise ValueError("excluded_documents must match exclusions")
        if min(
            self.supporting_items,
            self.contradicting_items,
            self.contextual_items,
        ) < 0:
            raise ValueError("evidence counts cannot be negative")
        if self.status == "available" and not self.model_identifier:
            raise ValueError(
                "available classified evidence requires a model identifier"
            )
        if self.status == "available" and (
            not self.retrieval_sha256
            or not self.classifier_input_sha256
            or not self.prompt_version
            or not self.classifier_mode
        ):
            raise ValueError(
                "available classified evidence requires retrieval and "
                "classifier metadata"
            )
        if len(self.citations) != (
            self.supporting_items
            + self.contradicting_items
            + self.contextual_items
        ):
            raise ValueError("directional evidence counts must match citations")
        if self.status in {
            "skipped_quiet_state",
            "retrieved_unclassified",
            "unavailable",
        } and (
            self.supporting_items
            or self.contradicting_items
            or self.contextual_items
            or self.citations
        ):
            raise ValueError(
                "unavailable, unclassified, or skipped evidence cannot emit claims"
            )
        if self.retrieved_documents and not self.retrieval_sha256:
            raise ValueError("retrieved evidence requires a retrieval hash")
        if (
            self.mode == "archived_point_in_time"
            and self.corpus_version is not None
            and (not self.corpus_sha256 or not self.request_sha256)
        ):
            raise ValueError(
                "an identified archive corpus requires corpus and request hashes"
            )
        if not self.detail:
            raise ValueError("evidence detail is required")


@dataclass(frozen=True)
class MvpAssessment:
    schema_version: str
    primary: PrimaryRiskAssessment
    shadow_benchmarks: tuple[ShadowBenchmark, ...]
    experimental_conditions: ReversalConditions
    positioning: PositioningSnapshot
    narrative: NarrativeSnapshot
    evidence: EvidenceSnapshot

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported schema version")
        dates = {
            self.primary.as_of_date,
            self.positioning.as_of_date,
            self.narrative.as_of_date,
            self.evidence.as_of_date,
        }
        if len(dates) != 1:
            raise ValueError("all MVP components must share one as-of date")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)
