"""Bounded, offline evidence preview for the final MVP.

This is intentionally not a research agent. It can only replay an existing
validated classification cache against the versioned local corpus. Missing,
date-mismatched, or inconsistent material fails closed to ``unavailable``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.evidence.corpus import DEFAULT_CORPUS_PATH, load_corpus
from src.utils.io import REPO_ROOT, read_json


DEFAULT_CLASSIFICATION_DIR = REPO_ROOT / "outputs" / "evidence_cache"
COMPONENT_LABEL = (
    "Phase 8 capability preview — not the completed Phase 8 implementation."
)


def _facts_sha256(deterministic_summary: dict[str, Any]) -> str:
    payload = json.dumps(
        deterministic_summary,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _unavailable(
    *,
    deterministic_summary: dict[str, Any],
    evidence_case_date: pd.Timestamp,
    reason: str,
) -> dict[str, Any]:
    return {
        "component": COMPONENT_LABEL,
        "status": "unavailable",
        "evidence_label": "historical_proxy",
        "evidence_case_date": evidence_case_date.date().isoformat(),
        "deterministic_facts_sha256": _facts_sha256(deterministic_summary),
        "deterministic_facts_unchanged": True,
        "supporting": [],
        "contradicting": [],
        "contextual": [],
        "research_questions": [
            "Which point-in-time evidence would distinguish a broad rebound from a momentum-specific short squeeze?",
            "Did loser-leg beta and short-side losses rise before or only during the realized stress?",
            "What evidence would contradict the high-volatility-recovery interpretation?",
        ],
        "uncertainty": reason,
        "limitations": [
            "Evidence status is unavailable because no reliable date-matched validated cache exists; no evidence conclusion is produced.",
            "The evidence layer cannot change deterministic metrics, thresholds, triggered states, or create a risk score.",
        ],
    }


def _validated_cached_items(
    *,
    evidence_case_date: pd.Timestamp,
    corpus_path: Path,
    classification_dir: Path,
) -> list[dict[str, Any]]:
    cache_path = (
        classification_dir
        / f"classified_evidence_{evidence_case_date.date().isoformat()}.json"
    )
    if not cache_path.is_file():
        raise FileNotFoundError("no exact-date validated classification cache")
    payload = read_json(cache_path)
    if payload.get("schema_validation_passed") is not True:
        raise ValueError("classification cache is not marked schema-valid")
    if payload.get("as_of_date") != evidence_case_date.date().isoformat():
        raise ValueError("classification cache date does not match evidence date")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("classification cache items are malformed")

    corpus = {document.document_id: document for document in load_corpus(corpus_path)}
    cutoff = pd.Timestamp(evidence_case_date).tz_localize("America/New_York")
    cutoff = cutoff + pd.Timedelta(hours=16)
    validated: list[dict[str, Any]] = []
    for item in items:
        document = corpus.get(item.get("document_id"))
        if document is None:
            raise ValueError("cached classification is absent from local corpus")
        publication = pd.Timestamp(
            datetime.fromisoformat(document.publication_timestamp)
        )
        if publication > cutoff:
            raise ValueError("cached evidence was not available by the cutoff")
        if (
            item.get("title") != document.title
            or item.get("source") != document.source
            or item.get("citation_url") != document.url_or_source_id
        ):
            raise ValueError("cached evidence provenance differs from local corpus")
        passage = item.get("extracted_passage")
        if passage is not None and passage not in document.snippet_or_passage:
            raise ValueError("cached evidence passage is not grounded in the corpus")
        validated.append(dict(item))
    return validated


def _preview_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": item["document_id"],
        "title": item["title"],
        "source": item["source"],
        "publication_timestamp": item["publication_timestamp"],
        "citation_url": item["citation_url"],
        "classification": item["classification"],
        "mechanism": item["mechanism"],
        "specificity": item["specificity"],
        "extracted_passage": item["extracted_passage"],
        "classification_rationale": item["classification_rationale"],
        "citation_valid": bool(item["citation_valid"]),
    }


def build_research_preview(
    *,
    deterministic_summary: dict[str, Any],
    evidence_case_date: pd.Timestamp,
    corpus_path: Path = DEFAULT_CORPUS_PATH,
    classification_dir: Path = DEFAULT_CLASSIFICATION_DIR,
) -> dict[str, Any]:
    """Replay exact-date local evidence without mutating deterministic facts."""

    evidence_case_date = pd.Timestamp(evidence_case_date).normalize()
    try:
        items = _validated_cached_items(
            evidence_case_date=evidence_case_date,
            corpus_path=corpus_path,
            classification_dir=classification_dir,
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        return _unavailable(
            deterministic_summary=deterministic_summary,
            evidence_case_date=evidence_case_date,
            reason=f"Reliable evidence unavailable: {exc}.",
        )

    grouped = {
        "supporting": [],
        "contradicting": [],
        "contextual": [],
    }
    for item in items:
        classification = item.get("classification")
        if classification in grouped and bool(item.get("citation_valid")):
            grouped[classification].append(_preview_item(item))

    if not any(grouped.values()):
        return _unavailable(
            deterministic_summary=deterministic_summary,
            evidence_case_date=evidence_case_date,
            reason="Reliable evidence unavailable: no usable classified items.",
        )
    return {
        "component": COMPONENT_LABEL,
        "status": "sample_only",
        "evidence_label": "historical_proxy",
        "evidence_case_date": evidence_case_date.date().isoformat(),
        "deterministic_facts_sha256": _facts_sha256(deterministic_summary),
        "deterministic_facts_unchanged": True,
        **grouped,
        "research_questions": [
            "Which sources are momentum-specific rather than generic macro context?",
            "What contemporaneous evidence contradicts the deterministic stress interpretation?",
            "Would the evidence have been public before the next trading session?",
        ],
        "uncertainty": (
            "This is a replay of a small cached classification fixture, not "
            "live retrieval or completed Phase 8 research."
        ),
        "limitations": [
            "The cached corpus is small and may omit relevant contradictory evidence.",
            "Generic macro context does not establish momentum-specific causality.",
            "Evidence cannot change deterministic metrics, thresholds, triggered states, or create a risk score.",
        ],
    }
