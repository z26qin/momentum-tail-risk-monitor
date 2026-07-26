"""Bounded fixture and archived evidence adapters for the streamlined MVP.

Evidence triggers only for an elevated primary state. The illustrative path
replays committed fixtures; the strict path requires a point-in-time corpus
and a retrieval-bound classifier response before emitting directional claims.
Neither path can write back to the primary risk assessment.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from pathlib import Path

from src.evidence.archived_provider import ArchivedEvidenceProvider
from src.evidence.versioned_classifier import validate_classifier_response
from src.mvp.contracts import EvidenceSnapshot, PrimaryRiskAssessment
from src.utils.io import DEFAULT_OUTPUT_DIR, REPO_ROOT, read_json


DEFAULT_ARCHIVED_CORPUS_PATH = (
    REPO_ROOT / "data" / "corpus" / "archived_momentum_evidence_v1.json"
)
FIXTURE_PROVIDER_NAME = "fixture_evidence_provider_v1"


def build_evidence_snapshot(
    *,
    primary: PrimaryRiskAssessment,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    provider_mode: str = "fixture",
    archived_corpus_path: Path = DEFAULT_ARCHIVED_CORPUS_PATH,
    classifier_response_path: Path | None = None,
) -> EvidenceSnapshot:
    """Route evidence through an explicit fixture or strict archive provider."""

    if provider_mode not in {"fixture", "archived"}:
        raise ValueError("provider_mode must be fixture or archived")
    mode = (
        "illustrative_fixture_replay"
        if provider_mode == "fixture"
        else "archived_point_in_time"
    )
    provider_name = (
        FIXTURE_PROVIDER_NAME
        if provider_mode == "fixture"
        else ArchivedEvidenceProvider.name
    )

    if not primary.elevated:
        return EvidenceSnapshot(
            as_of_date=primary.as_of_date,
            status="skipped_quiet_state",
            mode=mode,
            provider_name=provider_name,
            corpus_version=None,
            corpus_sha256=None,
            request_sha256=None,
            retrieved_documents=0,
            retrieved_document_ids=(),
            excluded_documents=0,
            exclusions=(),
            retrieval_sha256=None,
            classifier_input_sha256=None,
            prompt_version=None,
            model_identifier=None,
            classifier_mode=None,
            supporting_items=0,
            contradicting_items=0,
            contextual_items=0,
            citations=(),
            detail=(
                "Evidence retrieval is intentionally skipped because the "
                "primary DM state is not elevated."
            ),
        )

    if provider_mode == "archived":
        result = ArchivedEvidenceProvider(
            corpus_path=archived_corpus_path,
        ).retrieve(primary)
        if result.status == "unavailable":
            return EvidenceSnapshot(
                as_of_date=primary.as_of_date,
                status="unavailable",
                mode=result.mode,
                provider_name=result.provider_name,
                corpus_version=result.corpus_version,
                corpus_sha256=result.corpus_sha256,
                request_sha256=result.request_sha256,
                retrieved_documents=0,
                retrieved_document_ids=(),
                excluded_documents=len(result.exclusions),
                exclusions=tuple(
                    dataclasses.asdict(item) for item in result.exclusions
                ),
                retrieval_sha256=result.retrieval_sha256,
                classifier_input_sha256=None,
                prompt_version=None,
                model_identifier=None,
                classifier_mode=None,
                supporting_items=0,
                contradicting_items=0,
                contextual_items=0,
                citations=(),
                detail=result.detail,
            )
        if not result.documents:
            return EvidenceSnapshot(
                as_of_date=primary.as_of_date,
                status="unavailable",
                mode=result.mode,
                provider_name=result.provider_name,
                corpus_version=result.corpus_version,
                corpus_sha256=result.corpus_sha256,
                request_sha256=result.request_sha256,
                retrieved_documents=0,
                retrieved_document_ids=(),
                excluded_documents=len(result.exclusions),
                exclusions=tuple(
                    dataclasses.asdict(item) for item in result.exclusions
                ),
                retrieval_sha256=result.retrieval_sha256,
                classifier_input_sha256=None,
                prompt_version=None,
                model_identifier=None,
                classifier_mode=None,
                supporting_items=0,
                contradicting_items=0,
                contextual_items=0,
                citations=(),
                detail=(
                    f"{result.detail} No eligible archive documents matched; "
                    "this is unavailable evidence, not a low-risk signal."
                ),
            )
        if classifier_response_path is not None:
            if not classifier_response_path.is_file():
                raise FileNotFoundError(
                    "configured classifier response does not exist: "
                    f"{classifier_response_path}"
                )
            return validate_classifier_response(
                retrieval=result,
                response_path=classifier_response_path,
            )
        return EvidenceSnapshot(
            as_of_date=primary.as_of_date,
            status="retrieved_unclassified",
            mode=result.mode,
            provider_name=result.provider_name,
            corpus_version=result.corpus_version,
            corpus_sha256=result.corpus_sha256,
            request_sha256=result.request_sha256,
            retrieved_documents=len(result.documents),
            retrieved_document_ids=tuple(
                item.document.document_id for item in result.documents
            ),
            excluded_documents=len(result.exclusions),
            exclusions=tuple(
                dataclasses.asdict(item) for item in result.exclusions
            ),
            retrieval_sha256=result.retrieval_sha256,
            classifier_input_sha256=None,
            prompt_version=None,
            model_identifier=None,
            classifier_mode=None,
            supporting_items=0,
            contradicting_items=0,
            contextual_items=0,
            citations=(),
            detail=(
                f"{result.detail} Retrieved {len(result.documents)} candidate "
                "documents, but no versioned classifier response is configured; "
                "no directional evidence claims were emitted."
            ),
        )

    path = (
        output_dir
        / "debug"
        / f"classified_evidence_{primary.as_of_date}.json"
    )
    if not path.is_file():
        return EvidenceSnapshot(
            as_of_date=primary.as_of_date,
            status="unavailable",
            mode="illustrative_fixture_replay",
            provider_name=FIXTURE_PROVIDER_NAME,
            corpus_version="momentum-evidence-v1",
            corpus_sha256=None,
            request_sha256=None,
            retrieved_documents=0,
            retrieved_document_ids=(),
            excluded_documents=0,
            exclusions=(),
            retrieval_sha256=None,
            classifier_input_sha256=None,
            prompt_version=None,
            model_identifier=None,
            classifier_mode=None,
            supporting_items=0,
            contradicting_items=0,
            contextual_items=0,
            citations=(),
            detail=(
                "Primary state is elevated, but no cached illustrative "
                "classification fixture exists for this date."
            ),
        )

    payload = read_json(path)
    if payload.get("as_of_date") != primary.as_of_date:
        raise ValueError("evidence fixture does not match the primary date")
    cutoff = datetime.fromisoformat(primary.as_of_timestamp)
    citations: list[dict[str, object]] = []
    counts = {"supporting": 0, "contradicting": 0, "contextual": 0}
    for item in payload.get("items", []):
        classification = item.get("classification")
        if classification == "irrelevant":
            continue
        if classification not in counts:
            raise ValueError(f"unsupported evidence classification: {classification}")
        publication = datetime.fromisoformat(item["publication_timestamp"])
        if publication > cutoff:
            raise ValueError("evidence fixture contains a future publication")
        if not item.get("citation_valid"):
            raise ValueError("evidence fixture contains an invalid citation")
        passage = item.get("extracted_passage")
        if not passage:
            raise ValueError("relevant evidence fixture item lacks a passage")
        counts[classification] += 1
        citations.append(
            {
                "document_id": item["document_id"],
                "classification": classification,
                "mechanism": item["mechanism"],
                "source": item["source"],
                "title": item["title"],
                "publication_timestamp": item["publication_timestamp"],
                "citation_url": item["citation_url"],
                "extracted_passage": passage,
            }
        )
    return EvidenceSnapshot(
        as_of_date=primary.as_of_date,
        status="available",
        mode="illustrative_fixture_replay",
        provider_name=FIXTURE_PROVIDER_NAME,
        corpus_version="momentum-evidence-v1",
        corpus_sha256=None,
        request_sha256=str(payload["retrieval_request_sha256"]),
        retrieved_documents=len(payload.get("items", [])),
        retrieved_document_ids=tuple(
            str(item["document_id"]) for item in payload.get("items", [])
        ),
        excluded_documents=len(payload.get("exclusions", [])),
        exclusions=tuple(
            dict(item) for item in payload.get("exclusions", [])
        ),
        retrieval_sha256=str(payload["retrieval_result_sha256"]),
        classifier_input_sha256=str(payload["classifier_input_sha256"]),
        prompt_version=str(payload["prompt_version"]),
        model_identifier=str(payload["model_identifier"]),
        classifier_mode=str(payload["classifier_mode"]),
        supporting_items=counts["supporting"],
        contradicting_items=counts["contradicting"],
        contextual_items=counts["contextual"],
        citations=tuple(citations),
        detail=(
            "Validated replay of a small corpus curated after the historical "
            "assessment date. It demonstrates grounding controls, not a strict "
            "point-in-time text backtest."
        ),
    )
