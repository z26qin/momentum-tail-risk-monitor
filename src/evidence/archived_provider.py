"""Deterministic retrieval from a strict historical archive corpus."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from src.evidence.corpus_schema import load_archived_corpus
from src.evidence.provider_contracts import (
    EvidenceProviderResult,
    ProviderExclusion,
    RetrievedDocument,
)
from src.mvp.contracts import PrimaryRiskAssessment


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
MECHANISM_TERMS = {
    "policy or liquidity shock": (
        "liquidity",
        "credit",
        "federal reserve",
        "funding",
        "financial system",
        "stimulus",
    ),
    "rapid market rebound after stress": (
        "market rebound",
        "stock rally",
        "recovery",
        "rate cut",
        "short covering",
    ),
    "loser squeeze": (
        "short covering",
        "short squeeze",
        "loser stocks",
        "bank stocks",
        "rebound",
    ),
    "crowding or deleveraging": (
        "crowding",
        "leverage",
        "deleveraging",
        "liquidation",
        "margin",
    ),
    "generic risk-off or risk-on": (
        "market stress",
        "stock market",
        "recession",
        "unemployment",
        "financial conditions",
        "volatility",
    ),
}


def _sha256(payload: object) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalized_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            parsed.query,
            "",
        )
    )


def _tokens(value: str) -> frozenset[str]:
    return frozenset(TOKEN_PATTERN.findall(value.lower()))


def _score(title: str, passage: str) -> tuple[float, tuple[str, ...]]:
    lowered_title = title.lower()
    lowered_passage = passage.lower()
    title_tokens = _tokens(title)
    passage_tokens = _tokens(passage)
    total = 0.0
    matched: list[str] = []
    for mechanism, terms in MECHANISM_TERMS.items():
        mechanism_score = 0.0
        for term in terms:
            term_tokens = _tokens(term)
            if term in lowered_title:
                mechanism_score += 3.0
            elif term_tokens and term_tokens.issubset(title_tokens):
                mechanism_score += 2.0
            if term in lowered_passage:
                mechanism_score += 1.5
            elif term_tokens and term_tokens.issubset(passage_tokens):
                mechanism_score += 1.0
        if mechanism_score > 0:
            total += mechanism_score
            matched.append(mechanism)
    return total, tuple(matched)


class ArchivedEvidenceProvider:
    """Retrieve only documents provably present in an archive by the cutoff."""

    name = "archived_evidence_provider_v1"
    mode = "archived_point_in_time"

    def __init__(
        self,
        *,
        corpus_path: Path,
        lookback_days: int = 120,
        max_documents: int = 8,
    ) -> None:
        if lookback_days <= 0 or max_documents <= 0:
            raise ValueError("lookback_days and max_documents must be positive")
        self.corpus_path = corpus_path
        self.lookback_days = lookback_days
        self.max_documents = max_documents

    def retrieve(
        self,
        primary: PrimaryRiskAssessment,
    ) -> EvidenceProviderResult:
        request_payload = {
            "provider": self.name,
            "mode": self.mode,
            "as_of_date": primary.as_of_date,
            "timestamp_cutoff": primary.as_of_timestamp,
            "lookback_days": self.lookback_days,
            "max_documents": self.max_documents,
            "mechanism_terms": MECHANISM_TERMS,
        }
        request_sha256 = _sha256(request_payload)
        if not self.corpus_path.is_file():
            result_payload = {
                **request_payload,
                "status": "unavailable",
                "reason": "strict_archive_corpus_missing",
            }
            return EvidenceProviderResult(
                provider_name=self.name,
                mode=self.mode,
                status="unavailable",
                as_of_date=primary.as_of_date,
                timestamp_cutoff=primary.as_of_timestamp,
                corpus_version=None,
                corpus_sha256=None,
                request_sha256=request_sha256,
                retrieval_sha256=_sha256(result_payload),
                documents=(),
                exclusions=(),
                detail=(
                    f"Strict archived corpus is missing: {self.corpus_path}. "
                    "No fixture fallback was used."
                ),
            )

        corpus = load_archived_corpus(self.corpus_path)
        cutoff = datetime.fromisoformat(primary.as_of_timestamp).astimezone(
            timezone.utc
        )
        lower_bound = cutoff - timedelta(days=self.lookback_days)
        exclusions: list[ProviderExclusion] = []
        candidates: list[RetrievedDocument] = []

        timestamp_fields = (
            ("publication_timestamp", "future_publication"),
            ("discovery_timestamp", "future_discovery"),
            ("availability_timestamp", "future_availability"),
            ("content_version_timestamp", "future_content_version"),
        )
        for document in corpus.documents:
            if document.availability_status != "verified_archived_content":
                exclusions.append(
                    ProviderExclusion(
                        document_id=document.document_id,
                        reason="uncertain_content_version",
                        detail=(
                            "The archive cannot prove that this content version "
                            "was available by the assessment cutoff."
                        ),
                    )
                )
                continue
            rejected = False
            for field, reason in timestamp_fields:
                value = datetime.fromisoformat(
                    getattr(document, field)
                ).astimezone(timezone.utc)
                if value > cutoff:
                    exclusions.append(
                        ProviderExclusion(
                            document_id=document.document_id,
                            reason=reason,
                            detail=(
                                f"{field}={getattr(document, field)} exceeds "
                                f"cutoff={primary.as_of_timestamp}."
                            ),
                        )
                    )
                    rejected = True
                    break
            if rejected:
                continue
            published = datetime.fromisoformat(
                document.publication_timestamp
            ).astimezone(timezone.utc)
            if published < lower_bound:
                exclusions.append(
                    ProviderExclusion(
                        document_id=document.document_id,
                        reason="outside_lookback_window",
                        detail=(
                            f"Publication predates the {self.lookback_days}-day "
                            "lookback window."
                        ),
                    )
                )
                continue
            if document.source_category not in {"official", "news"}:
                exclusions.append(
                    ProviderExclusion(
                        document_id=document.document_id,
                        reason="disallowed_source",
                        detail="Only official and news archive sources are allowed.",
                    )
                )
                continue
            score, mechanisms = _score(document.title, document.passage)
            if score <= 0:
                exclusions.append(
                    ProviderExclusion(
                        document_id=document.document_id,
                        reason="no_query_match",
                        detail="No frozen mechanism query term matched.",
                    )
                )
                continue
            candidates.append(
                RetrievedDocument(
                    document=document,
                    retrieval_score=score,
                    matched_mechanisms=mechanisms,
                )
            )

        candidates.sort(
            key=lambda item: (
                -item.retrieval_score,
                -datetime.fromisoformat(
                    item.document.publication_timestamp
                ).timestamp(),
                item.document.document_id,
            )
        )
        deduplicated: list[RetrievedDocument] = []
        urls: set[str] = set()
        hashes: set[str] = set()
        titles: set[str] = set()
        for item in candidates:
            url = _normalized_url(item.document.url)
            title = " ".join(TOKEN_PATTERN.findall(item.document.title.lower()))
            if (
                url in urls
                or item.document.content_sha256 in hashes
                or title in titles
            ):
                exclusions.append(
                    ProviderExclusion(
                        document_id=item.document.document_id,
                        reason="duplicate",
                        detail=(
                            "A higher-ranked record has the same normalized "
                            "URL, content hash, or title."
                        ),
                    )
                )
                continue
            urls.add(url)
            hashes.add(item.document.content_sha256)
            titles.add(title)
            deduplicated.append(item)

        returned = deduplicated[: self.max_documents]
        for item in deduplicated[self.max_documents :]:
            exclusions.append(
                ProviderExclusion(
                    document_id=item.document.document_id,
                    reason="top_k_truncation",
                    detail=f"Ranked below max_documents={self.max_documents}.",
                )
            )
        result_body = {
            **request_payload,
            "corpus_version": corpus.corpus_version,
            "corpus_sha256": corpus.sha256,
            "documents": [dataclasses.asdict(item) for item in returned],
            "exclusions": [dataclasses.asdict(item) for item in exclusions],
        }
        return EvidenceProviderResult(
            provider_name=self.name,
            mode=self.mode,
            status="available",
            as_of_date=primary.as_of_date,
            timestamp_cutoff=primary.as_of_timestamp,
            corpus_version=corpus.corpus_version,
            corpus_sha256=corpus.sha256,
            request_sha256=request_sha256,
            retrieval_sha256=_sha256(result_body),
            documents=tuple(returned),
            exclusions=tuple(exclusions),
            detail=(
                "Deterministic retrieval from a strict archive inventory; "
                "publication, discovery, availability, and content-version "
                "timestamps were all checked against the cutoff."
            ),
        )
