"""Provider-neutral contracts for point-in-time evidence retrieval."""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

from src.mvp.contracts import PrimaryRiskAssessment


ARCHIVE_SCHEMA_VERSION = "archived-evidence-v1"
SELECTION_METHODS = frozenset(
    {"gdelt_gkg_inventory", "official_release_archive"}
)
AVAILABILITY_STATUSES = frozenset(
    {"verified_archived_content", "content_version_uncertain"}
)


def _aware(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a UTC offset")
    return parsed


def _date(value: str, name: str) -> None:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{name} must be YYYY-MM-DD")


@dataclass(frozen=True)
class ArchivedDocument:
    document_id: str
    title: str
    source: str
    source_category: str
    publication_timestamp: str
    discovery_timestamp: str
    availability_timestamp: str
    content_version_timestamp: str
    availability_status: str
    url: str
    passage: str
    content_sha256: str
    archive_source: str
    archive_locator: str
    acquisition_timestamp: str

    def __post_init__(self) -> None:
        for name in (
            "document_id",
            "title",
            "source",
            "source_category",
            "url",
            "passage",
            "archive_source",
            "archive_locator",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} cannot be blank")
        parsed_url = urlsplit(self.url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("url must be an absolute HTTP(S) URL")
        parsed_timestamps = {
            name: _aware(getattr(self, name), name)
            for name in (
                "publication_timestamp",
                "discovery_timestamp",
                "availability_timestamp",
                "content_version_timestamp",
                "acquisition_timestamp",
            )
        }
        if (
            parsed_timestamps["availability_timestamp"]
            > parsed_timestamps["acquisition_timestamp"]
        ):
            raise ValueError("archive acquisition cannot predate availability")
        if (
            parsed_timestamps["content_version_timestamp"]
            > parsed_timestamps["acquisition_timestamp"]
        ):
            raise ValueError("archive acquisition cannot predate the content version")
        if self.availability_status not in AVAILABILITY_STATUSES:
            raise ValueError("unsupported availability_status")
        if (
            not isinstance(self.content_sha256, str)
            or len(self.content_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.content_sha256
            )
        ):
            raise ValueError("content_sha256 must be a SHA-256 digest")


@dataclass(frozen=True)
class ProviderExclusion:
    document_id: str
    reason: str
    detail: str

    def __post_init__(self) -> None:
        if not self.document_id or not self.reason or not self.detail:
            raise ValueError("provider exclusion fields cannot be blank")


@dataclass(frozen=True)
class RetrievedDocument:
    document: ArchivedDocument
    retrieval_score: float
    matched_mechanisms: tuple[str, ...]

    def __post_init__(self) -> None:
        if not math.isfinite(self.retrieval_score) or self.retrieval_score <= 0:
            raise ValueError("retrieval_score must be positive")
        if not self.matched_mechanisms:
            raise ValueError("matched_mechanisms cannot be empty")


@dataclass(frozen=True)
class EvidenceProviderResult:
    provider_name: str
    mode: str
    status: str
    as_of_date: str
    timestamp_cutoff: str
    corpus_version: str | None
    corpus_sha256: str | None
    request_sha256: str
    retrieval_sha256: str
    documents: tuple[RetrievedDocument, ...]
    exclusions: tuple[ProviderExclusion, ...]
    detail: str

    def __post_init__(self) -> None:
        if self.mode not in {
            "illustrative_fixture_replay",
            "archived_point_in_time",
        }:
            raise ValueError("unsupported provider mode")
        if self.status not in {"available", "unavailable"}:
            raise ValueError("unsupported provider status")
        _date(self.as_of_date, "as_of_date")
        _aware(self.timestamp_cutoff, "timestamp_cutoff")
        for name in ("request_sha256", "retrieval_sha256"):
            if len(getattr(self, name)) != 64:
                raise ValueError(f"{name} must be a SHA-256 digest")
        if self.corpus_sha256 is not None and len(self.corpus_sha256) != 64:
            raise ValueError("corpus_sha256 must be a SHA-256 digest")
        if self.status == "unavailable" and self.documents:
            raise ValueError("unavailable retrieval cannot return documents")
        if self.status == "available" and (
            not self.corpus_version or not self.corpus_sha256
        ):
            raise ValueError("available retrieval requires corpus provenance")
        if not self.provider_name or not self.detail:
            raise ValueError("provider name and detail are required")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class EvidenceProvider(Protocol):
    name: str
    mode: str

    def retrieve(
        self,
        primary: PrimaryRiskAssessment,
    ) -> EvidenceProviderResult:
        """Return a deterministic retrieval result for one primary state."""
