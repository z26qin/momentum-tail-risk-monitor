"""Bounded evidence adapter for the streamlined MVP.

The current repository contains validated cached classifier outputs for two
illustrative dates.  This adapter triggers only for an elevated primary state,
re-checks cutoff and citation fields, and labels the result as fixture replay.
It never writes back to the primary risk assessment.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.mvp.contracts import EvidenceSnapshot, PrimaryRiskAssessment
from src.utils.io import DEFAULT_OUTPUT_DIR, read_json


def build_evidence_snapshot(
    *,
    primary: PrimaryRiskAssessment,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> EvidenceSnapshot:
    """Load a validated illustrative fixture only when primary risk is elevated."""

    if not primary.elevated:
        return EvidenceSnapshot(
            as_of_date=primary.as_of_date,
            status="skipped_quiet_state",
            mode="illustrative_fixture_replay",
            supporting_items=0,
            contradicting_items=0,
            contextual_items=0,
            citations=(),
            detail=(
                "Evidence retrieval is intentionally skipped because the "
                "primary DM state is not elevated."
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

