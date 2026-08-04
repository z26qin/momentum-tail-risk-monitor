"""Deterministically filter, rank, and deduplicate cached evidence."""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

from src.evidence.corpus import DEFAULT_CORPUS_PATH, load_corpus
from src.monitoring.contracts import (
    CandidateDocument,
    RetrievalExclusion,
    RetrievalRequest,
    RetrievalResult,
    SCHEMA_VERSION,
)
from src.utils.io import DEFAULT_OUTPUT_DIR, read_json, sha256_file, write_json


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _normalized_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.query,
            "",
        )
    )


def _tokens(value: str) -> frozenset[str]:
    return frozenset(TOKEN_PATTERN.findall(value.lower()))


def _query_score(
    document: CandidateDocument,
    request: RetrievalRequest,
) -> tuple[float, tuple[str, ...]]:
    title = document.title.lower()
    passage = document.snippet_or_passage.lower()
    title_tokens = _tokens(title)
    passage_tokens = _tokens(passage)
    total = 0.0
    matched: list[str] = []
    for query in request.queries:
        query_score = 0.0
        for term in query.search_terms:
            normalized_term = term.strip().lower()
            term_tokens = _tokens(normalized_term)
            if normalized_term in title:
                query_score += 3.0
            elif term_tokens and term_tokens.issubset(title_tokens):
                query_score += 2.0
            if normalized_term in passage:
                query_score += 1.5
            elif term_tokens and term_tokens.issubset(passage_tokens):
                query_score += 1.0
        if query_score > 0.0:
            matched.append(query.query_id)
            total += query_score
    return total, tuple(matched)


def _sort_key(document: CandidateDocument) -> tuple[float, float, str]:
    timestamp = datetime.fromisoformat(
        document.publication_timestamp
    ).astimezone(timezone.utc)
    return (
        -document.retrieval_score,
        -timestamp.timestamp(),
        document.document_id,
    )


def _duplicate_key(document: CandidateDocument) -> tuple[str, str, str]:
    normalized_title = " ".join(TOKEN_PATTERN.findall(document.title.lower()))
    return (
        _normalized_url(document.url_or_source_id),
        document.content_sha256,
        normalized_title,
    )


def _duplicate_of(
    document: CandidateDocument,
    seen_urls: set[str],
    seen_hashes: set[str],
    seen_titles: set[str],
) -> bool:
    url, content_hash, title = _duplicate_key(document)
    return (
        url in seen_urls
        or content_hash in seen_hashes
        or title in seen_titles
    )


def _remember_duplicate_keys(
    document: CandidateDocument,
    seen_urls: set[str],
    seen_hashes: set[str],
    seen_titles: set[str],
) -> None:
    url, content_hash, title = _duplicate_key(document)
    seen_urls.add(url)
    seen_hashes.add(content_hash)
    seen_titles.add(title)


def retrieve(
    *,
    request: RetrievalRequest,
    corpus: Iterable[CandidateDocument],
    request_sha256: str,
) -> RetrievalResult:
    """Return ranked candidates and a complete reason-coded exclusion audit."""

    documents = tuple(corpus)
    cutoff = datetime.fromisoformat(request.timestamp_cutoff).astimezone(
        timezone.utc
    )
    lower_bound = cutoff - timedelta(days=request.lookback_days)
    exclusions: list[RetrievalExclusion] = []
    scored: list[CandidateDocument] = []

    for document in documents:
        published = datetime.fromisoformat(
            document.publication_timestamp
        ).astimezone(timezone.utc)
        if (
            document.timestamp_status == "uncertain_content_version"
            or document.availability_status == "content_version_uncertain"
        ):
            exclusions.append(
                RetrievalExclusion(
                    document_id=document.document_id,
                    reason="uncertain_content_version",
                    detail=(
                        "The cached passage may reflect a later page update, "
                        "so historical availability is not asserted."
                    ),
                )
            )
            continue
        if published > cutoff:
            exclusions.append(
                RetrievalExclusion(
                    document_id=document.document_id,
                    reason="future_publication",
                    detail=(
                        f"Publication {document.publication_timestamp} is after "
                        f"cutoff {request.timestamp_cutoff}."
                    ),
                )
            )
            continue
        if published < lower_bound:
            exclusions.append(
                RetrievalExclusion(
                    document_id=document.document_id,
                    reason="outside_lookback_window",
                    detail=(
                        f"Publication {document.publication_timestamp} is "
                        f"earlier than the {request.lookback_days}-day "
                        "lookback window."
                    ),
                )
            )
            continue
        if document.source_category not in request.source_filters:
            exclusions.append(
                RetrievalExclusion(
                    document_id=document.document_id,
                    reason="disallowed_source",
                    detail=(
                        f"Source category {document.source_category!r} is not "
                        f"in {list(request.source_filters)!r}."
                    ),
                )
            )
            continue
        score, matched_query_ids = _query_score(document, request)
        if score <= 0.0:
            exclusions.append(
                RetrievalExclusion(
                    document_id=document.document_id,
                    reason="no_query_match",
                    detail="No deterministic query term matched the record.",
                )
            )
            continue
        scored.append(
            dataclasses.replace(
                document,
                retrieval_score=score,
                matched_query_ids=matched_query_ids,
            )
        )

    ranked = sorted(scored, key=_sort_key)
    deduplicated: list[CandidateDocument] = []
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()
    seen_titles: set[str] = set()
    for document in ranked:
        if _duplicate_of(
            document,
            seen_urls,
            seen_hashes,
            seen_titles,
        ):
            exclusions.append(
                RetrievalExclusion(
                    document_id=document.document_id,
                    reason="duplicate",
                    detail=(
                        "A higher-ranked record has the same normalized URL, "
                        "content hash, or title."
                    ),
                )
            )
            continue
        _remember_duplicate_keys(
            document,
            seen_urls,
            seen_hashes,
            seen_titles,
        )
        deduplicated.append(document)

    returned = deduplicated[: request.max_documents]
    for document in deduplicated[request.max_documents :]:
        exclusions.append(
            RetrievalExclusion(
                document_id=document.document_id,
                reason="top_k_truncation",
                detail=(
                    f"Document ranked below max_documents="
                    f"{request.max_documents}."
                ),
            )
        )

    return RetrievalResult(
        schema_version=SCHEMA_VERSION,
        as_of_date=request.as_of_date,
        timestamp_cutoff=request.timestamp_cutoff,
        request_sha256=request_sha256,
        documents=tuple(returned),
        exclusions=tuple(
            sorted(
                exclusions,
                key=lambda item: (item.document_id, item.reason),
            )
        ),
        corpus_document_count=len(documents),
        returned_document_count=len(returned),
        data_quality_flags=(
            "retrieval_is_keyword_based_not_semantic",
            "historical_corpus_was_curated_after_the_assessment_date",
            "date_only_sources_use_a_conservative_next_day_cutoff",
            "retrieval_failure_must_not_be_interpreted_as_low_risk",
        ),
    )


def run_retriever(
    *,
    request_path: Path,
    corpus_path: Path = DEFAULT_CORPUS_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[RetrievalResult, Path]:
    """Replay retrieval from a saved request and cached corpus."""

    request = RetrievalRequest.from_dict(read_json(request_path))
    result = retrieve(
        request=request,
        corpus=load_corpus(corpus_path),
        request_sha256=sha256_file(request_path),
    )
    path = (
        output_dir
        / "debug"
        / f"retrieved_documents_{result.as_of_date}.json"
    )
    write_json(path, result.to_dict())
    return result, path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    result, path = run_retriever(
        request_path=args.request,
        corpus_path=args.corpus,
        output_dir=args.output_dir,
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
