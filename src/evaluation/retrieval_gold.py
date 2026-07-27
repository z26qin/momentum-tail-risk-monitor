"""Build and evaluate the March 2020 human retrieval gold-set package.

The workflow deliberately separates:

* a deterministic, label-blind candidate inventory;
* a strict official-archive corpus eligible for point-in-time retrieval; and
* human annotations, which are never inferred by this module.

The ``build`` command writes frozen protocols before it creates or samples any
candidate pairs.  By default it rebuilds the package from the committed corpus
manifest.  ``--refresh-sources`` reacquires the small official archive slice.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import html
import json
import math
import random
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from src.evidence.corpus_schema import (
    archived_content_sha256,
    load_archived_corpus,
)
from src.risk.dm_engine import build_primary_assessment
from src.utils.io import REPO_ROOT, read_json, sha256_file, utc_now_iso, write_json


EVALUATION_NAME = "march-2020-momentum-retrieval-gold-v1"
PROTOCOL_VERSION = "1.0"
RANDOM_SEED = 20200324
ROOT = REPO_ROOT / "data" / "evaluation" / "2020_retrieval_gold"
CORPUS_DIR = ROOT / "corpus"
ANNOTATION_DIR = ROOT / "annotation"
ARCHIVED_CORPUS_PATH = CORPUS_DIR / "archived_corpus.json"
CORPUS_MANIFEST_PATH = CORPUS_DIR / "corpus_manifest.json"
ACQUISITION_LOG_PATH = CORPUS_DIR / "acquisition_log.csv"
CANDIDATE_PROTOCOL_PATH = ROOT / "candidate_protocol.json"
EVALUATION_PROTOCOL_PATH = ROOT / "evaluation_protocol.json"
GUIDELINES_PATH = ROOT / "annotation_guidelines.md"
RETRIEVAL_RESULTS_PATH = ROOT / "retrieval_results.json"
ANNOTATION_CSV_PATH = ANNOTATION_DIR / "annotation_queue.csv"
ANNOTATION_MD_PATH = ANNOTATION_DIR / "annotation_queue.md"
TEACHING_EXAMPLES_PATH = ANNOTATION_DIR / "teaching_examples.md"
REVIEWER_CHECKLIST_PATH = ANNOTATION_DIR / "reviewer_checklist.md"
LABEL_SCHEMA_PATH = ANNOTATION_DIR / "label_schema.json"
RUNBOOK_PATH = ROOT / "HUMAN_ANNOTATION_RUNBOOK.md"
EVALUATION_RESULTS_PATH = ROOT / "evaluation_results.json"
EVALUATION_REPORT_PATH = ROOT / "evaluation_report.md"
STATUS_PATH = (
    REPO_ROOT
    / "artifacts"
    / "component_status"
    / "march_2020_retrieval_gold_workflow.json"
)

ASSESSMENT_TIMESTAMPS = (
    "2020-03-18T16:00:00-04:00",
    "2020-03-23T16:00:00-04:00",
    "2020-03-24T16:00:00-04:00",
)
QUIET_CONTROL_DATE = "2024-01-05"
SAMPLING_START = "2020-03-09T00:00:00-04:00"
SAMPLING_END = "2020-03-24T16:00:00-04:00"
PROVIDER_LOOKBACK_DAYS = 120
ANNOTATION_PAIR_TARGET = 45
TEACHING_EXAMPLE_TARGET = 10

MECHANISMS = (
    "market_stress_or_panic",
    "market_rebound",
    "policy_or_liquidity_support",
    "short_covering_or_position_unwind",
    "loser_leg_recovery",
    "crowded_positioning",
    "generic_macro_context",
    "other",
)
RELEVANCE_LABELS = {
    "2": "directly useful for explaining the momentum-reversal environment",
    "1": "useful background, but the mechanism connection is indirect",
    "0": (
        "irrelevant, keyword-only, duplicate, or not useful for this "
        "investigation"
    ),
}
EVIDENCE_DIRECTIONS = (
    "supporting",
    "contradicting",
    "contextual",
    "irrelevant",
)
TIMESTAMP_VALIDITIES = ("valid", "invalid_future", "uncertain")
REVIEWER_CONFIDENCES = ("high", "medium", "low")
REVIEW_STATUSES = ("pending", "completed", "needs_discussion")

QUERY_SPECS: tuple[dict[str, Any], ...] = (
    {
        "query_id": "q01_market_stress",
        "mechanism": "market_stress_or_panic",
        "terms": (
            "market stress",
            "market turmoil",
            "financial conditions",
            "financial stability",
            "volatility",
            "economic disruption",
        ),
    },
    {
        "query_id": "q02_market_rebound",
        "mechanism": "market_rebound",
        "terms": (
            "market rebound",
            "stock rally",
            "stocks rally",
            "recovery",
            "risk appetite",
        ),
    },
    {
        "query_id": "q03_policy_liquidity",
        "mechanism": "policy_or_liquidity_support",
        "terms": (
            "liquidity",
            "credit",
            "federal reserve",
            "funding",
            "facility",
            "stimulus",
            "rate cut",
            "policy intervention",
            "bank lending",
            "money market",
            "commercial paper",
        ),
    },
    {
        "query_id": "q04_position_unwind",
        "mechanism": "short_covering_or_position_unwind",
        "terms": (
            "short covering",
            "short squeeze",
            "forced deleveraging",
            "position unwind",
            "liquidation",
            "margin call",
            "momentum stocks",
        ),
    },
    {
        "query_id": "q05_loser_recovery",
        "mechanism": "loser_leg_recovery",
        "terms": (
            "distressed stocks rebound",
            "loser stocks",
            "bank stocks rebound",
            "beaten-down stocks",
        ),
    },
    {
        "query_id": "q06_crowding",
        "mechanism": "crowded_positioning",
        "terms": (
            "crowded trade",
            "crowding",
            "leverage",
            "deleveraging",
        ),
    },
    {
        "query_id": "q07_generic_macro",
        "mechanism": "generic_macro_context",
        "terms": (
            "recession",
            "unemployment",
            "employment",
            "economic activity",
            "economic growth",
            "financial markets",
        ),
    },
)
QUERY_BY_ID = {spec["query_id"]: spec for spec in QUERY_SPECS}

ANNOTATION_FIELDS = (
    "annotation_id",
    "query_id",
    "assessment_timestamp",
    "document_id",
    "title",
    "source",
    "url",
    "publication_timestamp",
    "discovery_timestamp",
    "availability_timestamp",
    "timestamp_validity",
    "retrieved_passage",
    "candidate_rank",
    "candidate_score",
    "candidate_query_terms",
    "relevance_label",
    "mechanism_labels",
    "evidence_direction",
    "supporting_passage",
    "reviewer_rationale",
    "reviewer_confidence",
    "review_status",
)

FED_INDEX_URL = (
    "https://www.federalreserve.gov/newsevents/pressreleases/2020-press.htm"
)
TREASURY_INDEX_URL = (
    "https://home.treasury.gov/news/press-releases?"
    "publication-start-date=03%2F09%2F2020&"
    "publication-end-date=03%2F24%2F2020"
)
SEC_INDEX_URL = (
    "https://www.sec.gov/newsroom/press-releases?month=3&year=2020"
)
BLS_SCHEDULE_URL = "https://www.bls.gov/schedule/2020/03_sched_list.htm"
GDELT_DISCOVERY_URL = (
    "https://api.gdeltproject.org/api/v2/doc/doc?"
    "query=%28%22stock+rally%22+OR+%22market+rebound%22+OR+"
    "%22short+covering%22+OR+liquidity%29+%28stocks+OR+markets%29+"
    "sourcelang%3Aenglish&mode=artlist&format=json&maxrecords=50&"
    "sort=hybridrel&startdatetime=20200309000000&"
    "enddatetime=20200324160000"
)
UNCERTAIN_NEWS_URL = (
    "https://www.cnbc.com/2020/03/19/"
    "stop-blaming-short-sellers-for-causing-the-market-drops.html"
)
UNCERTAIN_REBOUND_NEWS_URL = (
    "https://www.cnn.com/business/live-news/"
    "stock-market-news-today-032420/"
)

BLS_RELEASES = (
    (
        "2020-03-11T08:30:00-04:00",
        "Consumer Price Index for February 2020",
        "cpi_03112020.htm",
    ),
    (
        "2020-03-11T08:30:00-04:00",
        "Real Earnings for February 2020",
        "realer_03112020.htm",
    ),
    (
        "2020-03-12T08:30:00-04:00",
        "Producer Price Index for February 2020",
        "ppi_03122020.htm",
    ),
    (
        "2020-03-13T08:30:00-04:00",
        "U.S. Import and Export Price Indexes for February 2020",
        "ximpim_03132020.htm",
    ),
    (
        "2020-03-16T10:00:00-04:00",
        "State Employment and Unemployment for January 2020",
        "laus_03162020.htm",
    ),
    (
        "2020-03-17T10:00:00-04:00",
        "Job Openings and Labor Turnover for January 2020",
        "jolts_03172020.htm",
    ),
    (
        "2020-03-19T10:00:00-04:00",
        "Employer Costs for Employee Compensation for December 2019",
        "ecec_03192020.htm",
    ),
    (
        "2020-03-19T10:00:00-04:00",
        "Employment Situation of Veterans for Annual 2019",
        "vet_03192020.htm",
    ),
    (
        "2020-03-20T10:00:00-04:00",
        "Metropolitan Area Employment and Unemployment for January 2020",
        "metro_03202020.htm",
    ),
    (
        "2020-03-24T10:00:00-04:00",
        "Multifactor Productivity Trends for Annual 2019",
        "prod3_03242020.htm",
    ),
)

USER_AGENT = "research@example.com momentum-tail-risk/0.1"
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
SPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True)
class SourceRecord:
    """One deterministic source-inventory item before page acquisition."""

    document_id: str
    title: str
    source: str
    source_category: str
    publication_timestamp: str
    discovery_timestamp: str
    url: str
    archive_source: str
    archive_locator: str
    discovery_method: str
    strict_eligible: bool = True


@dataclass(frozen=True)
class FetchResult:
    """Downloaded page bytes and provenance used for one minimal passage."""

    url: str
    body: bytes
    final_url: str
    response_last_modified: str | None


class AnnotationValidationError(ValueError):
    """Raised when completed human annotations violate the frozen contract."""


def _canonical_sha256(payload: object) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _protocol_with_hash(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["protocol_hash"] = _canonical_sha256(payload)
    return result


def _normalize(value: str) -> str:
    return SPACE_PATTERN.sub(" ", html.unescape(value)).strip()


def _strip_tags(value: str) -> str:
    without_scripts = re.sub(
        r"<(?:script|style|noscript)[^>]*>.*?</(?:script|style|noscript)>",
        " ",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return _normalize(re.sub(r"<[^>]+>", " ", without_scripts))


def _minimal_passage(value: str, *, max_characters: int = 700) -> str:
    text = _normalize(value)
    if len(text) <= max_characters:
        return text
    boundary = text.rfind(".", 0, max_characters)
    if boundary >= 120:
        return text[: boundary + 1]
    return text[:max_characters].rsplit(" ", 1)[0] + "…"


def _parse_blocks(page: str, tag: str) -> list[str]:
    return [
        _strip_tags(block)
        for block in re.findall(
            rf"<{tag}(?:\s[^>]*)?>(.*?)</{tag}>",
            page,
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]


def _first_substantive_paragraph(page: str) -> str:
    excluded_prefixes = (
        "official websites use",
        "secure .gov websites",
        "the federal reserve, the central bank",
        "review of monetary policy",
        "the committee on foreign investment",
        "macroeconomic and foreign exchange policies",
        "20th street and constitution avenue",
    )
    for paragraph in _parse_blocks(page, "p"):
        lowered = paragraph.lower()
        if len(paragraph) < 80 or lowered.startswith(excluded_prefixes):
            continue
        paragraph = re.sub(
            r"^For release at\s+\d{1,2}:\d{2}\s+[ap]\.m\.\s+"
            r"(?:EST|EDT)\s+Share\s+",
            "",
            paragraph,
            flags=re.IGNORECASE,
        )
        if len(paragraph) >= 80:
            return _minimal_passage(paragraph)
    raise ValueError("no substantive paragraph found")


def _bls_passage(page: str) -> str:
    for raw_block in re.findall(
        r"<pre(?:\s[^>]*)?>(.*?)</pre>",
        page,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        preformatted = html.unescape(re.sub(r"<[^>]+>", " ", raw_block))
        paragraphs = [
            _normalize(block)
            for block in re.split(r"(?:\r?\n\s*){2,}", preformatted)
            if _normalize(block)
        ]
        for paragraph in paragraphs:
            if (
                "Bureau of Labor Statistics reported today" in paragraph
                and len(paragraph) >= 80
            ):
                return _minimal_passage(paragraph)
    raise ValueError("BLS release lacks a summary passage")


def _meta_description(page: str) -> str:
    patterns = (
        r'<meta[^>]+property=["\']og:description["\'][^>]+'
        r'content=["\'](.*?)["\']',
        r'<meta[^>]+name=["\']description["\'][^>]+'
        r'content=["\'](.*?)["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, page, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return _minimal_passage(match.group(1), max_characters=240)
    raise ValueError("page lacks a description passage")


def _cnn_rebound_passage(page: str) -> str:
    match = re.search(
        r"Today(?:’|')s rally in US stocks isn(?:’|')t letting up at midday\. "
        r"All three major indexes are sharply higher\.",
        page,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError("CNN live page lacks the bounded rebound passage")
    passage = _normalize(html.unescape(match.group(0)))
    if len(passage.split()) > 25:
        raise ValueError("CNN rebound passage exceeds the copyright limit")
    return passage


def _fetch(url: str) -> FetchResult:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return FetchResult(
            url=url,
            body=response.read(),
            final_url=response.geturl(),
            response_last_modified=response.headers.get("Last-Modified"),
        )


def _decode(result: FetchResult) -> str:
    return result.body.decode("utf-8-sig", errors="replace")


def _in_sampling_window(timestamp: str) -> bool:
    value = datetime.fromisoformat(timestamp).astimezone(timezone.utc)
    start = datetime.fromisoformat(SAMPLING_START).astimezone(timezone.utc)
    end = datetime.fromisoformat(SAMPLING_END).astimezone(timezone.utc)
    return start <= value <= end


def _slug_from_url(url: str) -> str:
    return Path(urllib.parse.urlsplit(url).path).stem.lower()


def _fed_timestamp(index_date: str, page: str) -> str:
    plain = _strip_tags(page)
    match = re.search(
        r"For release at\s+(\d{1,2}):(\d{2})\s+([ap])\.m\.\s+(EST|EDT)",
        plain,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError("Federal Reserve page lacks exact release time")
    hour = int(match.group(1)) % 12
    if match.group(3).lower() == "p":
        hour += 12
    release_date = datetime.strptime(index_date, "%m/%d/%Y").date()
    zone = ZoneInfo("America/New_York")
    released = datetime.combine(
        release_date,
        time(hour=hour, minute=int(match.group(2))),
        tzinfo=zone,
    )
    expected_offset = "-05:00" if match.group(4).upper() == "EST" else "-04:00"
    if released.isoformat().endswith(expected_offset):
        return released.isoformat()
    raise ValueError("Federal Reserve timezone abbreviation disagrees with date")


def _discover_fed(result: FetchResult) -> list[SourceRecord]:
    page = _decode(result)
    pattern = re.compile(
        r"<time>(\d+/\d+/2020)</time>.*?"
        r'<p><a href="([^"]+)"><em>(.*?)</em></a></p>.*?'
        r"<strong>(.*?)</strong>",
        flags=re.DOTALL,
    )
    discovered: list[SourceRecord] = []
    for index_date, relative_url, raw_title, _category in pattern.findall(page):
        release_date = datetime.strptime(index_date, "%m/%d/%Y").date()
        if not date(2020, 3, 9) <= release_date <= date(2020, 3, 24):
            continue
        url = urllib.parse.urljoin(FED_INDEX_URL, relative_url)
        discovered.append(
            SourceRecord(
                document_id=(
                    f"fed-{release_date.isoformat()}-{_slug_from_url(url)}"
                ),
                title=_strip_tags(raw_title),
                source="Federal Reserve Board",
                source_category="official",
                publication_timestamp=index_date,
                discovery_timestamp=index_date,
                url=url,
                archive_source="Federal Reserve 2020 Press Release Archive",
                archive_locator=f"{FED_INDEX_URL}#{_slug_from_url(url)}",
                discovery_method="official_release_archive",
            )
        )
    return discovered


def _discover_treasury(result: FetchResult) -> list[SourceRecord]:
    page = _decode(result)
    pattern = re.compile(
        r'<time datetime="([^"]+)"[^>]*>.*?</time>.*?'
        r'<h3 class="featured-stories__headline"><a href="'
        r'(/news/press-releases/[^"]+)"[^>]*>(.*?)</a>',
        flags=re.DOTALL,
    )
    discovered: list[SourceRecord] = []
    for timestamp, relative_url, raw_title in pattern.findall(page):
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if not _in_sampling_window(parsed.isoformat()):
            continue
        url = urllib.parse.urljoin(TREASURY_INDEX_URL, relative_url)
        release_date = parsed.astimezone(
            ZoneInfo("America/New_York")
        ).date()
        discovered.append(
            SourceRecord(
                document_id=(
                    f"treasury-{release_date.isoformat()}-{_slug_from_url(url)}"
                ),
                title=_strip_tags(raw_title),
                source="U.S. Department of the Treasury",
                source_category="official",
                publication_timestamp=parsed.isoformat(),
                discovery_timestamp=parsed.isoformat(),
                url=url,
                archive_source="Treasury Press Release Archive",
                archive_locator=f"{TREASURY_INDEX_URL}#{_slug_from_url(url)}",
                discovery_method="official_release_archive",
            )
        )
    return discovered


def _discover_sec(result: FetchResult) -> list[SourceRecord]:
    page = _decode(result)
    pattern = re.compile(
        r'<time datetime="([^"]+)"[^>]*>.*?</time>.*?'
        r'<a href="(/newsroom/press-releases/[^"]+)"[^>]*>(.*?)</a>.*?'
        r"views-field-field-release-number[^>]*>\s*(.*?)\s*</td>",
        flags=re.DOTALL,
    )
    discovered: list[SourceRecord] = []
    for timestamp, relative_url, raw_title, release_number in pattern.findall(
        page
    ):
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if not _in_sampling_window(parsed.isoformat()):
            continue
        url = urllib.parse.urljoin(SEC_INDEX_URL, relative_url)
        number = _strip_tags(release_number)
        discovered.append(
            SourceRecord(
                document_id=f"sec-{parsed.date().isoformat()}-{number}",
                title=_strip_tags(raw_title),
                source="U.S. Securities and Exchange Commission",
                source_category="official",
                publication_timestamp=parsed.isoformat(),
                discovery_timestamp=parsed.isoformat(),
                url=url,
                archive_source="SEC 2020 Press Release Archive",
                archive_locator=f"{SEC_INDEX_URL}#{number}",
                discovery_method="official_release_archive",
            )
        )
    return discovered


def _discover_bls(_result: FetchResult) -> list[SourceRecord]:
    discovered: list[SourceRecord] = []
    for timestamp, title, filename in BLS_RELEASES:
        url = (
            "https://www.bls.gov/news.release/archives/"
            f"{filename}"
        )
        parsed = datetime.fromisoformat(timestamp)
        discovered.append(
            SourceRecord(
                document_id=f"bls-{parsed.date().isoformat()}-{Path(filename).stem}",
                title=title,
                source="U.S. Bureau of Labor Statistics",
                source_category="official",
                publication_timestamp=timestamp,
                discovery_timestamp=timestamp,
                url=url,
                archive_source="BLS Archived News Releases",
                archive_locator=f"{BLS_SCHEDULE_URL}#{Path(filename).stem}",
                discovery_method="official_release_archive",
            )
        )
    return discovered


def _uncertain_gdelt_record(acquired_at: str) -> dict[str, Any]:
    result = _fetch(UNCERTAIN_NEWS_URL)
    passage = _meta_description(_decode(result))
    record: dict[str, Any] = {
        "document_id": "gdelt-cnbc-2020-03-19-short-sellers",
        "title": "Stop blaming short sellers for causing the market drops",
        "source": "CNBC",
        "source_category": "news",
        "publication_timestamp": "2020-03-19T00:00:00-04:00",
        "discovery_timestamp": "2020-03-19T22:30:00+00:00",
        "availability_timestamp": acquired_at,
        "content_version_timestamp": acquired_at,
        "availability_status": "content_version_uncertain",
        "url": UNCERTAIN_NEWS_URL,
        "passage": passage,
        "archive_source": "GDELT DOC 2.0 discovery metadata",
        "archive_locator": GDELT_DISCOVERY_URL,
        "acquisition_timestamp": acquired_at,
    }
    record["content_sha256"] = archived_content_sha256(record)
    record.update(
        {
            "discovery_method": "gdelt_doc_artlist_metadata",
            "strict_corpus_included": False,
            "strict_exclusion_reason": (
                "GDELT proves discovery, but only a current page description "
                "is available; the March 2020 content version is unverified."
            ),
            "page_sha256": hashlib.sha256(result.body).hexdigest(),
            "response_last_modified": result.response_last_modified,
        }
    )
    return record


def _uncertain_gdelt_rebound_record(acquired_at: str) -> dict[str, Any]:
    result = _fetch(UNCERTAIN_REBOUND_NEWS_URL)
    passage = _cnn_rebound_passage(_decode(result))
    record: dict[str, Any] = {
        "document_id": "gdelt-cnn-2020-03-24-market-rebound",
        "title": "Stock rally continues at midday",
        "source": "CNN",
        "source_category": "news",
        "publication_timestamp": "2020-03-24T12:08:13-04:00",
        "discovery_timestamp": "2020-03-24T11:00:00+00:00",
        "availability_timestamp": acquired_at,
        "content_version_timestamp": acquired_at,
        "availability_status": "content_version_uncertain",
        "url": UNCERTAIN_REBOUND_NEWS_URL,
        "passage": passage,
        "archive_source": "GDELT DOC 2.0 discovery metadata",
        "archive_locator": GDELT_DISCOVERY_URL,
        "acquisition_timestamp": acquired_at,
    }
    record["content_sha256"] = archived_content_sha256(record)
    record.update(
        {
            "discovery_method": "gdelt_doc_artlist_metadata",
            "strict_corpus_included": False,
            "strict_exclusion_reason": (
                "GDELT proves discovery of the parent live page, and current "
                "page metadata dates this update to 2020-03-24T16:08:13Z, "
                "but the March 2020 content version remains unverified."
            ),
            "page_sha256": hashlib.sha256(result.body).hexdigest(),
            "response_last_modified": result.response_last_modified,
        }
    )
    return record


def _acquire_document(
    source: SourceRecord,
    acquired_at: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    try:
        result = _fetch(source.url)
        page = _decode(result)
        if source.source == "Federal Reserve Board":
            timestamp = _fed_timestamp(source.publication_timestamp, page)
            passage = _first_substantive_paragraph(page)
        elif source.source == "U.S. Bureau of Labor Statistics":
            timestamp = source.publication_timestamp
            passage = _bls_passage(page)
        else:
            timestamp = source.publication_timestamp
            passage = _first_substantive_paragraph(page)
        if not _in_sampling_window(timestamp):
            return None, {
                "document_id": source.document_id,
                "source": source.source,
                "url": source.url,
                "publication_timestamp": timestamp,
                "status": "excluded",
                "exclusion_reason": "after_annotation_sampling_end",
                "page_sha256": hashlib.sha256(result.body).hexdigest(),
                "detail": (
                    "The official release occurred after "
                    f"{SAMPLING_END}."
                ),
            }
        record: dict[str, Any] = {
            "document_id": source.document_id,
            "title": source.title,
            "source": source.source,
            "source_category": source.source_category,
            "publication_timestamp": timestamp,
            "discovery_timestamp": timestamp,
            "availability_timestamp": timestamp,
            "content_version_timestamp": timestamp,
            "availability_status": "verified_archived_content",
            "url": source.url,
            "passage": passage,
            "archive_source": source.archive_source,
            "archive_locator": source.archive_locator,
            "acquisition_timestamp": acquired_at,
        }
        record["content_sha256"] = archived_content_sha256(record)
        record.update(
            {
                "discovery_method": source.discovery_method,
                "strict_corpus_included": True,
                "strict_exclusion_reason": None,
                "page_sha256": hashlib.sha256(result.body).hexdigest(),
                "response_last_modified": result.response_last_modified,
            }
        )
        return record, {
            "document_id": source.document_id,
            "source": source.source,
            "url": source.url,
            "publication_timestamp": timestamp,
            "status": "included",
            "exclusion_reason": "",
            "page_sha256": record["page_sha256"],
            "detail": (
                "Minimal passage captured from the named official historical "
                "release archive."
            ),
        }
    except Exception as exc:
        return None, {
            "document_id": source.document_id,
            "source": source.source,
            "url": source.url,
            "publication_timestamp": source.publication_timestamp,
            "status": "failed",
            "exclusion_reason": type(exc).__name__,
            "page_sha256": "",
            "detail": str(exc),
        }


def evaluation_protocol_payload() -> dict[str, Any]:
    """Return the frozen human-label protocol before its hash is attached."""

    return {
        "evaluation_name": EVALUATION_NAME,
        "protocol_version": PROTOCOL_VERSION,
        "research_objective": (
            "When the deterministic momentum-risk state is elevated, can the "
            "retrieval layer surface timestamp-valid, relevant, "
            "passage-grounded evidence that helps explain the contemporaneous "
            "momentum-reversal environment?"
        ),
        "non_claims": [
            "text predicts momentum crashes",
            "text adds incremental alpha",
            "retrieved evidence is causal",
            "GDELT themes are ground truth",
        ],
        "assessment_timestamps": list(ASSESSMENT_TIMESTAMPS),
        "primary_presentation_timestamp": ASSESSMENT_TIMESTAMPS[-1],
        "quiet_control_date": QUIET_CONTROL_DATE,
        "quiet_control_role": (
            "Verify that retrieval is skipped; no historical article corpus "
            "is required for the control."
        ),
        "mechanism_taxonomy": list(MECHANISMS),
        "existing_runtime_mapping": {
            "policy or liquidity shock": "policy_or_liquidity_support",
            "rapid market rebound after stress": "market_rebound",
            "loser squeeze": [
                "short_covering_or_position_unwind",
                "loser_leg_recovery",
            ],
            "crowding or deleveraging": [
                "crowded_positioning",
                "short_covering_or_position_unwind",
            ],
            "generic risk-off or risk-on": [
                "market_stress_or_panic",
                "generic_macro_context",
            ],
            "winner liquidation": "short_covering_or_position_unwind",
            "factor rotation": "market_rebound",
        },
        "relevance_labels": RELEVANCE_LABELS,
        "evidence_directions": list(EVIDENCE_DIRECTIONS),
        "timestamp_validity_labels": list(TIMESTAMP_VALIDITIES),
        "rules": [
            (
                "invalid_future cannot receive relevance greater than zero "
                "for that assessment timestamp"
            ),
            (
                "uncertain is retained for audit and excluded from strict "
                "evaluation metrics"
            ),
            "retrieval rank and model output are not gold labels",
            "semantic labels must be assigned by a human reviewer",
            (
                "relevance 2 requires one exact supporting passage copied "
                "from the candidate passage"
            ),
            (
                "irrelevant rows use evidence_direction=irrelevant and no "
                "semantic mechanism other than other"
            ),
        ],
        "metrics": [
            "Precision@3",
            "Precision@5",
            "nDCG@5",
            "timestamp_valid_rate",
            "citation_valid_rate",
            "exact_passage_match_rate",
            "unsupported_claim_rate",
            "mechanism_coverage",
        ],
        "small_sample_policy": (
            "Return not_reported with a reason when the strict completed "
            "sample cannot support a requested metric. Do not calculate "
            "confidence intervals."
        ),
        "human_annotation_required": True,
    }


def candidate_protocol_payload() -> dict[str, Any]:
    """Return the frozen label-blind candidate-discovery protocol."""

    return {
        "evaluation_name": EVALUATION_NAME,
        "protocol_version": PROTOCOL_VERSION,
        "candidate_source_name": (
            "US official historical release archives with two "
            "GDELT-discovery uncertainty audits"
        ),
        "source_inventory_version": "official-release-archive-2020-03-v1",
        "source_inventories": [
            {
                "name": "Federal Reserve 2020 Press Release Archive",
                "url": FED_INDEX_URL,
                "role": "strict candidate discovery and archived passage",
            },
            {
                "name": "Treasury Press Release Archive",
                "url": TREASURY_INDEX_URL,
                "role": "strict candidate discovery and archived passage",
            },
            {
                "name": "SEC 2020 Press Release Archive",
                "url": SEC_INDEX_URL,
                "role": "strict candidate discovery and archived passage",
            },
            {
                "name": "BLS March 2020 Release Schedule and Archives",
                "url": BLS_SCHEDULE_URL,
                "role": "strict candidate discovery and archived passage",
            },
            {
                "name": "GDELT DOC 2.0 artlist metadata",
                "url": GDELT_DISCOVERY_URL,
                "role": (
                    "uncertain candidate discovery only; never proof of "
                    "historical passage availability"
                ),
            },
        ],
        "assessment_timestamps": list(ASSESSMENT_TIMESTAMPS),
        "provider_retrieval_window": {
            "lookback_days": PROVIDER_LOOKBACK_DAYS,
            "behavior_changed_for_evaluation": False,
        },
        "annotation_sampling_window": {
            "start_timestamp": SAMPLING_START,
            "end_timestamp": SAMPLING_END,
        },
        "query_vocabulary": [
            {
                "query_id": spec["query_id"],
                "mechanism": spec["mechanism"],
                "terms": list(spec["terms"]),
            }
            for spec in QUERY_SPECS
        ],
        "query_vocabulary_provenance": [
            "active deterministic state name panic_elevated",
            "src/evidence/archived_provider.py MECHANISM_TERMS",
            "src/data/gdelt.py label-blind mechanism vocabulary",
            "paper-informed economic concepts",
        ],
        "query_notes": [
            (
                "momentum stocks is retained because it already exists in the "
                "runtime GDELT rotation vocabulary"
            ),
            (
                "momentum crash, March 24 momentum crash, known reversal date, "
                "tickers, and dated event terms are forbidden"
            ),
            (
                "generic official releases remain eligible as low-score "
                "controls; they are not semantically pre-labeled"
            ),
        ],
        "source_domain_rules": {
            "allowlist": [
                "federalreserve.gov",
                "home.treasury.gov",
                "sec.gov",
                "bls.gov",
            ],
            "uncertain_audit_domains": ["cnbc.com", "cnn.com"],
            "blocklist": [],
            "source_categories": ["official", "news"],
        },
        "language_rule": "English-language records only",
        "timestamp_field": "publication_timestamp",
        "archive_content_requirements": [
            "publication timestamp",
            "discovery timestamp",
            "availability timestamp",
            "content-version timestamp",
            "archive source and locator",
            "minimal passage",
            "content SHA-256",
            (
                "GDELT metadata alone is content_version_uncertain and "
                "excluded from strict retrieval"
            ),
        ],
        "deduplication_rules": [
            "normalized URL",
            "content SHA-256",
            "normalized title",
        ],
        "ranking_rule": (
            "deterministic title/passage phrase matching; title match=3, "
            "passage match=1.5; ties use publication timestamp descending "
            "then document_id"
        ),
        "annotation_sampling": {
            "target_pairs": ANNOTATION_PAIR_TARGET,
            "saved_random_seed": RANDOM_SEED,
            "strata": [
                "high_rank",
                "middle_rank",
                "low_rank_or_keyword_only",
                "future_invalid",
                "near_duplicate",
                "generic_macro_or_covid",
                "official_policy",
                "market_rebound",
                "timestamp_uncertain",
            ],
        },
        "maximum_candidate_count": 100,
        "minimum_candidate_target": 50,
        "future_returns_used": False,
        "human_labels_used": False,
    }


def _annotation_guidelines() -> str:
    return f"""# March 2020 retrieval annotation guidelines

Evaluation: `{EVALUATION_NAME}`

## Purpose

Judge whether each candidate passage was available by the assessment cutoff
and whether it would help a PM investigate the contemporaneous
momentum-reversal environment. Do not judge whether the passage later proved
correct, predicted returns, or caused the reversal.

The candidate corpus and human gold labels are separate. Official archives,
GDELT metadata, retrieval scores, classifier output, and the provisional
teaching suggestions are never gold labels.

## Timestamp validity

- `valid`: the exact content version is demonstrably available at or before the
  assessment cutoff.
- `invalid_future`: publication, discovery, availability, or content-version
  time is after the cutoff. Relevance must be `0`.
- `uncertain`: the historical content version cannot be proven. Retain the row
  for audit, but it is excluded from strict metrics.

Do not substitute crawl/acquisition time for publication time. A current live
page is not historical evidence unless the archive or version claim is explicit.

## Relevance

- `2`: directly useful for explaining the momentum-reversal environment.
- `1`: useful background, but the mechanism connection is indirect.
- `0`: irrelevant, keyword-only, duplicate, or not useful.

When evidence is weak, choose the lower score. A market-wide rally is not by
itself proof of a momentum-position unwind.

## Mechanisms

Use one or more semicolon-separated values from:

{chr(10).join(f"- `{item}`" for item in MECHANISMS)}

These mechanisms are an annotation vocabulary, not claims that GDELT observes
them directly. Use `other` only when no listed mechanism is appropriate.

## Evidence direction

- `supporting`: directly supports the mechanism interpretation.
- `contradicting`: directly challenges it.
- `contextual`: relevant context without a direct directional connection.
- `irrelevant`: required when relevance is `0`.

## Passage and rationale

For relevance `2`, copy one exact supporting substring from
`retrieved_passage`. For relevance `1`, a grounded passage is strongly
recommended. Do not paraphrase inside `supporting_passage`. Explain the
document-level judgment in `reviewer_rationale`, and record confidence as
`high`, `medium`, or `low`.

## Independence rules

Do not use future momentum returns, matured tail-loss labels, later accounts of
March 24, retrieval rank as a label, or a model classification as authority.
Label the passage available at the cutoff, not the later market outcome.
"""


def _reviewer_checklist() -> str:
    return """# Reviewer checklist

For each row:

1. Was the exact content available by the assessment cutoff?
2. Does the passage discuss a mechanism relevant to the current risk state?
3. Is the mechanism connection direct or merely background?
4. Does it support, contradict, or only contextualize the interpretation?
5. Is there one exact passage that supports the judgment?
6. Would this evidence save a PM investigation time?
7. Am I labeling the document itself rather than its later outcome?

## Common traps

- judging from the headline alone;
- rewarding a passage merely because it says “crash” or “rally”;
- using knowledge from after March 24;
- treating generic pandemic news as automatically relevant;
- treating every Federal Reserve release as relevant;
- confusing a market-wide rebound with direct evidence of momentum unwind;
- assigning causality that the passage does not state;
- treating retrieval rank as relevance;
- marking an uncertain historical content version as valid.
"""


def _label_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": EVALUATION_NAME,
        "type": "object",
        "properties": {
            "timestamp_validity": {"enum": list(TIMESTAMP_VALIDITIES)},
            "relevance_label": {"enum": [0, 1, 2]},
            "mechanism_labels": {
                "type": "array",
                "items": {"enum": list(MECHANISMS)},
                "uniqueItems": True,
            },
            "evidence_direction": {"enum": list(EVIDENCE_DIRECTIONS)},
            "supporting_passage": {"type": "string"},
            "reviewer_rationale": {"type": "string", "minLength": 1},
            "reviewer_confidence": {"enum": list(REVIEWER_CONFIDENCES)},
            "review_status": {"enum": list(REVIEW_STATUSES)},
        },
        "required": [
            "timestamp_validity",
            "relevance_label",
            "mechanism_labels",
            "evidence_direction",
            "supporting_passage",
            "reviewer_rationale",
            "reviewer_confidence",
            "review_status",
        ],
        "additionalProperties": False,
        "notes": [
            "Semantic labels are human-authored only.",
            "uncertain rows are excluded from strict metrics.",
            "invalid_future requires relevance_label=0.",
        ],
    }


def write_frozen_protocols(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    """Write the label and candidate protocols before candidate processing."""

    candidate = _protocol_with_hash(candidate_protocol_payload())
    evaluation = _protocol_with_hash(evaluation_protocol_payload())
    write_json(root / CANDIDATE_PROTOCOL_PATH.relative_to(ROOT), candidate)
    write_json(root / EVALUATION_PROTOCOL_PATH.relative_to(ROOT), evaluation)
    guidelines = root / GUIDELINES_PATH.relative_to(ROOT)
    guidelines.parent.mkdir(parents=True, exist_ok=True)
    guidelines.write_text(_annotation_guidelines(), encoding="utf-8")
    return candidate, evaluation


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def acquire_candidate_corpus(root: Path = ROOT) -> dict[str, Any]:
    """Acquire the small official archive slice and save provenance."""

    acquired_at = utc_now_iso()
    index_urls = (
        FED_INDEX_URL,
        TREASURY_INDEX_URL,
        SEC_INDEX_URL,
        BLS_SCHEDULE_URL,
    )
    with ThreadPoolExecutor(max_workers=4) as executor:
        index_results = list(executor.map(_fetch, index_urls))
    parsers = (
        _discover_fed,
        _discover_treasury,
        _discover_sec,
        _discover_bls,
    )
    sources: list[SourceRecord] = []
    for parser, result in zip(parsers, index_results):
        sources.extend(parser(result))
    if len({source.document_id for source in sources}) != len(sources):
        raise ValueError("official source inventory produced duplicate IDs")

    with ThreadPoolExecutor(max_workers=8) as executor:
        acquired = list(
            executor.map(
                lambda source: _acquire_document(source, acquired_at),
                sources,
            )
        )
    candidate_records = [
        record for record, _log in acquired if record is not None
    ]
    log_rows = [log for _record, log in acquired]

    uncertain_sources = (
        (
            _uncertain_gdelt_record,
            "gdelt-cnbc-2020-03-19-short-sellers",
            "CNBC",
            UNCERTAIN_NEWS_URL,
            "2020-03-19T00:00:00-04:00",
        ),
        (
            _uncertain_gdelt_rebound_record,
            "gdelt-cnn-2020-03-24-market-rebound",
            "CNN",
            UNCERTAIN_REBOUND_NEWS_URL,
            "2020-03-24T12:08:13-04:00",
        ),
    )
    for builder, document_id, source, url, publication_timestamp in (
        uncertain_sources
    ):
        try:
            uncertain = builder(acquired_at)
            candidate_records.append(uncertain)
            log_rows.append(
                {
                    "document_id": uncertain["document_id"],
                    "source": uncertain["source"],
                    "url": uncertain["url"],
                    "publication_timestamp": uncertain[
                        "publication_timestamp"
                    ],
                    "status": "audit_only",
                    "exclusion_reason": "content_version_uncertain",
                    "page_sha256": uncertain["page_sha256"],
                    "detail": uncertain["strict_exclusion_reason"],
                }
            )
        except Exception as exc:
            log_rows.append(
                {
                    "document_id": document_id,
                    "source": source,
                    "url": url,
                    "publication_timestamp": publication_timestamp,
                    "status": "failed",
                    "exclusion_reason": type(exc).__name__,
                    "page_sha256": "",
                    "detail": str(exc),
                }
            )

    candidate_records.sort(key=lambda record: record["document_id"])
    strict_records = [
        {
            key: value
            for key, value in record.items()
            if key
            in {
                "document_id",
                "title",
                "source",
                "source_category",
                "publication_timestamp",
                "discovery_timestamp",
                "availability_timestamp",
                "content_version_timestamp",
                "availability_status",
                "url",
                "passage",
                "content_sha256",
                "archive_source",
                "archive_locator",
                "acquisition_timestamp",
            }
        }
        for record in candidate_records
        if record["strict_corpus_included"]
    ]
    if not 50 <= len(candidate_records) <= 100:
        raise ValueError(
            "candidate corpus must contain 50-100 documents; "
            f"found {len(candidate_records)}"
        )
    if not strict_records:
        raise ValueError("no real archived content could be verified")

    candidate_protocol = read_json(
        root / CANDIDATE_PROTOCOL_PATH.relative_to(ROOT)
    )
    corpus_payload = {
        "schema_version": "archived-evidence-v1",
        "corpus_version": "march-2020-official-release-archive-v1",
        "selection_method": "official_release_archive",
        "selection_query": {
            "query_version": "momentum-archive-query-v1",
            "terms": sorted(
                {
                    term
                    for spec in QUERY_SPECS
                    for term in spec["terms"]
                }
            ),
            "language": "English",
            "start_timestamp": SAMPLING_START,
            "end_timestamp": SAMPLING_END,
        },
        "archive_inventory": (
            "Federal Reserve, Treasury, SEC, and BLS official historical "
            "release indexes; response hashes are in corpus_manifest.json"
        ),
        "documents": strict_records,
    }
    corpus_path = root / ARCHIVED_CORPUS_PATH.relative_to(ROOT)
    write_json(corpus_path, corpus_payload)
    load_archived_corpus(corpus_path)

    source_indexes = [
        {
            "url": result.url,
            "final_url": result.final_url,
            "sha256": hashlib.sha256(result.body).hexdigest(),
            "response_last_modified": result.response_last_modified,
        }
        for result in index_results
    ]
    manifest_payload: dict[str, Any] = {
        "schema_version": "retrieval-gold-candidate-manifest-v1",
        "evaluation_name": EVALUATION_NAME,
        "source_inventory_version": candidate_protocol[
            "source_inventory_version"
        ],
        "candidate_protocol_hash": candidate_protocol["protocol_hash"],
        "acquisition_timestamp": acquired_at,
        "source_indexes": source_indexes,
        "candidate_documents": candidate_records,
        "counts": {
            "candidate_documents": len(candidate_records),
            "strict_corpus_documents": len(strict_records),
            "timestamp_uncertain_candidates": sum(
                record["availability_status"] == "content_version_uncertain"
                for record in candidate_records
            ),
            "failed_or_excluded_acquisitions": sum(
                row["status"] in {"failed", "excluded"} for row in log_rows
            ),
        },
        "copyright_policy": (
            "Only one minimal passage per release is stored. No full "
            "copyrighted news body is committed."
        ),
        "strict_corpus_path": str(
            ARCHIVED_CORPUS_PATH.relative_to(REPO_ROOT)
        ),
        "strict_corpus_sha256": sha256_file(corpus_path),
    }
    manifest_payload["manifest_hash"] = _canonical_sha256(manifest_payload)
    manifest_path = root / CORPUS_MANIFEST_PATH.relative_to(ROOT)
    write_json(manifest_path, manifest_payload)
    _write_csv(
        root / ACQUISITION_LOG_PATH.relative_to(ROOT),
        sorted(log_rows, key=lambda row: row["document_id"]),
        (
            "document_id",
            "source",
            "url",
            "publication_timestamp",
            "status",
            "exclusion_reason",
            "page_sha256",
            "detail",
        ),
    )
    return manifest_payload


def _tokens(value: str) -> frozenset[str]:
    return frozenset(TOKEN_PATTERN.findall(value.lower()))


def _query_score(
    document: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> tuple[float, tuple[str, ...]]:
    title = str(document["title"]).lower()
    passage = str(document["passage"]).lower()
    title_tokens = _tokens(title)
    passage_tokens = _tokens(passage)
    score = 0.0
    matches: list[str] = []
    for term in spec["terms"]:
        normalized = str(term).lower()
        term_tokens = _tokens(normalized)
        term_score = 0.0
        if normalized in title:
            term_score += 3.0
        elif term_tokens and term_tokens.issubset(title_tokens):
            term_score += 2.0
        if normalized in passage:
            term_score += 1.5
        elif term_tokens and term_tokens.issubset(passage_tokens):
            term_score += 1.0
        if term_score:
            score += term_score
            matches.append(str(term))
    return score, tuple(matches)


def _objective_timestamp_status(
    document: Mapping[str, Any],
    assessment_timestamp: str,
) -> str:
    cutoff = datetime.fromisoformat(assessment_timestamp).astimezone(
        timezone.utc
    )
    publication = datetime.fromisoformat(
        str(document["publication_timestamp"])
    ).astimezone(timezone.utc)
    if publication > cutoff:
        return "invalid_future"
    if document["availability_status"] == "content_version_uncertain":
        return "uncertain"
    for name in (
        "discovery_timestamp",
        "availability_timestamp",
        "content_version_timestamp",
    ):
        value = datetime.fromisoformat(str(document[name])).astimezone(
            timezone.utc
        )
        if value > cutoff:
            return "invalid_future"
    return "valid"


def _best_query(document: Mapping[str, Any]) -> dict[str, Any]:
    scored = []
    for spec in QUERY_SPECS:
        score, terms = _query_score(document, spec)
        scored.append((score, spec["query_id"], spec["mechanism"], terms))
    score, query_id, mechanism, terms = min(
        scored,
        key=lambda item: (-item[0], item[1]),
    )
    if score == 0:
        query_id = "q07_generic_macro"
        mechanism = "generic_macro_context"
        terms = ()
    return {
        "query_id": query_id,
        "query_mechanism": mechanism,
        "candidate_score": score,
        "candidate_query_terms": list(terms),
    }


def _near_duplicate_groups(
    documents: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    """Assign only deterministic metadata-based near-duplicate groups."""

    groups: dict[str, str] = {}
    expected_groups = {
        "march-23-credit-facilities": {
            "fed-2020-03-23-monetary20200323b",
            "treasury-2020-03-23-sm951",
        },
        "march-18-money-market-facility": {
            "fed-2020-03-18-monetary20200318a",
            "treasury-2020-03-18-sm950",
        },
    }
    ids = {str(document["document_id"]) for document in documents}
    for group, members in expected_groups.items():
        for document_id in members.intersection(ids):
            groups[document_id] = group
    return groups


def build_retrieval_results(
    manifest: Mapping[str, Any],
    candidate_protocol: Mapping[str, Any],
) -> dict[str, Any]:
    """Rank the label-blind candidate inventory for each assessment cutoff."""

    documents = list(manifest["candidate_documents"])
    near_duplicates = _near_duplicate_groups(documents)
    rows: list[dict[str, Any]] = []
    for assessment_timestamp in ASSESSMENT_TIMESTAMPS:
        assessment_rows: list[dict[str, Any]] = []
        for document in documents:
            best = _best_query(document)
            assessment_rows.append(
                {
                    "assessment_timestamp": assessment_timestamp,
                    "document_id": document["document_id"],
                    "title": document["title"],
                    "source": document["source"],
                    "url": document["url"],
                    "publication_timestamp": document[
                        "publication_timestamp"
                    ],
                    "discovery_timestamp": document[
                        "discovery_timestamp"
                    ],
                    "availability_timestamp": document[
                        "availability_timestamp"
                    ],
                    "content_version_timestamp": document[
                        "content_version_timestamp"
                    ],
                    "availability_status": document[
                        "availability_status"
                    ],
                    "retrieved_passage": document["passage"],
                    "near_duplicate_group": near_duplicates.get(
                        str(document["document_id"])
                    ),
                    "objective_timestamp_status": (
                        _objective_timestamp_status(
                            document,
                            assessment_timestamp,
                        )
                    ),
                    **best,
                }
            )

        valid_by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in assessment_rows:
            if (
                row["objective_timestamp_status"] == "valid"
                and float(row["candidate_score"]) > 0
            ):
                valid_by_query[str(row["query_id"])].append(row)
        ranks: dict[tuple[str, str], int] = {}
        for query_id, query_rows in valid_by_query.items():
            ordered = sorted(
                query_rows,
                key=lambda row: (
                    -float(row["candidate_score"]),
                    -datetime.fromisoformat(
                        str(row["publication_timestamp"])
                    ).timestamp(),
                    str(row["document_id"]),
                ),
            )
            for rank, row in enumerate(ordered, start=1):
                ranks[(query_id, str(row["document_id"]))] = rank
        for row in assessment_rows:
            row["candidate_rank"] = ranks.get(
                (str(row["query_id"]), str(row["document_id"]))
            )
        rows.extend(assessment_rows)

    payload: dict[str, Any] = {
        "schema_version": "retrieval-gold-results-v1",
        "evaluation_name": EVALUATION_NAME,
        "candidate_protocol_hash": candidate_protocol["protocol_hash"],
        "source_manifest_hash": manifest["manifest_hash"],
        "assessment_timestamps": list(ASSESSMENT_TIMESTAMPS),
        "provider_lookback_days": PROVIDER_LOOKBACK_DAYS,
        "annotation_sampling_window": {
            "start": SAMPLING_START,
            "end": SAMPLING_END,
        },
        "ranking_method": "frozen_deterministic_keyword_v1",
        "human_annotations_read": False,
        "candidate_results": rows,
    }
    payload["retrieval_results_hash"] = _canonical_sha256(payload)
    return payload


def _teaching_pair_keys() -> tuple[tuple[str, str], ...]:
    primary = ASSESSMENT_TIMESTAMPS[-1]
    return (
        (primary, "fed-2020-03-23-monetary20200323b"),
        (primary, "treasury-2020-03-23-sm951"),
        (primary, "sec-2020-03-21-2020-67"),
        (primary, "bls-2020-03-11-cpi_03112020"),
        (primary, "sec-2020-03-20-2020-66"),
        (primary, "treasury-2020-03-19-sm949"),
        (
            ASSESSMENT_TIMESTAMPS[0],
            "fed-2020-03-23-monetary20200323b",
        ),
        (primary, "treasury-2020-03-18-sm950"),
        (primary, "gdelt-cnbc-2020-03-19-short-sellers"),
        (primary, "gdelt-cnn-2020-03-24-market-rebound"),
    )


def _sample_candidate_rows(
    retrieval_results: Mapping[str, Any],
    *,
    target: int = ANNOTATION_PAIR_TARGET,
    seed: int = RANDOM_SEED,
) -> list[dict[str, Any]]:
    rows = [
        dict(row) for row in retrieval_results["candidate_results"]
    ]
    by_key = {
        (str(row["assessment_timestamp"]), str(row["document_id"])): row
        for row in rows
    }
    selected_keys: set[tuple[str, str]] = set()
    selected: list[dict[str, Any]] = []

    def add(row: Mapping[str, Any]) -> None:
        key = (
            str(row["assessment_timestamp"]),
            str(row["document_id"]),
        )
        if key not in selected_keys:
            selected_keys.add(key)
            selected.append(dict(row))

    for key in _teaching_pair_keys():
        if key in by_key:
            add(by_key[key])

    per_timestamp_target = target // len(ASSESSMENT_TIMESTAMPS)
    for index, assessment_timestamp in enumerate(ASSESSMENT_TIMESTAMPS):
        rng = random.Random(seed + index)
        pool = [
            row
            for row in rows
            if row["assessment_timestamp"] == assessment_timestamp
        ]
        already = sum(
            row["assessment_timestamp"] == assessment_timestamp
            for row in selected
        )
        slots = per_timestamp_target - already
        if slots <= 0:
            continue

        strata: list[tuple[str, list[dict[str, Any]], int]] = [
            (
                "future",
                [
                    row
                    for row in pool
                    if row["objective_timestamp_status"] == "invalid_future"
                ],
                2,
            ),
            (
                "uncertain",
                [
                    row
                    for row in pool
                    if row["objective_timestamp_status"] == "uncertain"
                ],
                1,
            ),
            (
                "near_duplicate",
                [
                    row
                    for row in pool
                    if row["near_duplicate_group"] is not None
                ],
                2,
            ),
            (
                "high",
                [
                    row
                    for row in pool
                    if row["candidate_rank"] is not None
                    and int(row["candidate_rank"]) <= 5
                ],
                4,
            ),
            (
                "middle",
                [
                    row
                    for row in pool
                    if row["candidate_rank"] is not None
                    and 6 <= int(row["candidate_rank"]) <= 15
                ],
                3,
            ),
            (
                "low_or_keyword_only",
                [
                    row
                    for row in pool
                    if row["candidate_rank"] is None
                    or int(row["candidate_rank"]) > 15
                    or float(row["candidate_score"]) == 0
                ],
                3,
            ),
        ]
        for _name, candidates, quota in strata:
            remaining = [
                row
                for row in sorted(
                    candidates,
                    key=lambda item: (
                        str(item["document_id"]),
                        str(item["query_id"]),
                    ),
                )
                if (
                    str(row["assessment_timestamp"]),
                    str(row["document_id"]),
                )
                not in selected_keys
            ]
            rng.shuffle(remaining)
            for row in remaining[: min(quota, slots)]:
                add(row)
                slots -= 1
            if slots == 0:
                break
        if slots:
            remaining = [
                row
                for row in sorted(
                    pool,
                    key=lambda item: (
                        str(item["document_id"]),
                        str(item["query_id"]),
                    ),
                )
                if (
                    str(row["assessment_timestamp"]),
                    str(row["document_id"]),
                )
                not in selected_keys
            ]
            rng.shuffle(remaining)
            for row in remaining[:slots]:
                add(row)

    if len(selected) < target:
        rng = random.Random(seed)
        remaining = [
            row
            for row in rows
            if (
                str(row["assessment_timestamp"]),
                str(row["document_id"]),
            )
            not in selected_keys
        ]
        rng.shuffle(remaining)
        for row in remaining[: target - len(selected)]:
            add(row)
    selected = selected[:target]
    selected.sort(
        key=lambda row: (
            str(row["assessment_timestamp"]),
            str(row["query_id"]),
            (
                int(row["candidate_rank"])
                if row["candidate_rank"] is not None
                else 10**9
            ),
            str(row["document_id"]),
        )
    )
    if len(selected) != target:
        raise ValueError(f"annotation sample expected {target} rows")
    return selected


def _annotation_rows(
    retrieval_results: Mapping[str, Any],
) -> list[dict[str, Any]]:
    sampled = _sample_candidate_rows(retrieval_results)
    counters: dict[str, int] = defaultdict(int)
    rows: list[dict[str, Any]] = []
    for candidate in sampled:
        stamp = datetime.fromisoformat(
            str(candidate["assessment_timestamp"])
        ).strftime("%Y%m%d")
        counters[stamp] += 1
        objective_status = str(candidate["objective_timestamp_status"])
        rows.append(
            {
                "annotation_id": (
                    f"ann-{stamp}-{counters[stamp]:03d}"
                ),
                "query_id": candidate["query_id"],
                "assessment_timestamp": candidate[
                    "assessment_timestamp"
                ],
                "document_id": candidate["document_id"],
                "title": candidate["title"],
                "source": candidate["source"],
                "url": candidate["url"],
                "publication_timestamp": candidate[
                    "publication_timestamp"
                ],
                "discovery_timestamp": candidate[
                    "discovery_timestamp"
                ],
                "availability_timestamp": candidate[
                    "availability_timestamp"
                ],
                "timestamp_validity": (
                    "invalid_future"
                    if objective_status == "invalid_future"
                    else ""
                ),
                "retrieved_passage": candidate["retrieved_passage"],
                "candidate_rank": (
                    candidate["candidate_rank"]
                    if candidate["candidate_rank"] is not None
                    else ""
                ),
                "candidate_score": candidate["candidate_score"],
                "candidate_query_terms": ";".join(
                    candidate["candidate_query_terms"]
                ),
                "relevance_label": "",
                "mechanism_labels": "",
                "evidence_direction": "",
                "supporting_passage": "",
                "reviewer_rationale": "",
                "reviewer_confidence": "",
                "review_status": "",
            }
        )
    return rows


def _annotation_markdown(rows: Sequence[Mapping[str, Any]]) -> str:
    sections = [
        "# March 2020 retrieval annotation queue",
        "",
        (
            "Human labels are blank by design. Candidate rank and score are "
            "retrieval diagnostics, not judgments. No future returns or "
            "matured tail-loss outcomes are shown."
        ),
        "",
    ]
    for row in rows:
        terms = row["candidate_query_terms"] or "(none; control candidate)"
        rank = row["candidate_rank"] or "(excluded/unranked)"
        timestamp = row["timestamp_validity"] or "(human review required)"
        sections.extend(
            [
                f"## {row['annotation_id']} — {row['title']}",
                "",
                f"- Assessment timestamp: `{row['assessment_timestamp']}`",
                f"- Source: {row['source']}",
                f"- URL: {row['url']}",
                (
                    f"- Publication / discovery / availability: "
                    f"`{row['publication_timestamp']}` / "
                    f"`{row['discovery_timestamp']}` / "
                    f"`{row['availability_timestamp']}`"
                ),
                f"- Query: `{row['query_id']}`",
                f"- Candidate rank / score: `{rank}` / `{row['candidate_score']}`",
                f"- Candidate query terms: {terms}",
                f"- Timestamp validity: `{timestamp}`",
                "",
                "> " + str(row["retrieved_passage"]).replace("\n", "\n> "),
                "",
                "Human label:",
                "",
                "- Relevance: ___",
                "- Mechanism(s): ___",
                "- Evidence direction: ___",
                "- Exact supporting passage: ___",
                "- Rationale: ___",
                "- Confidence: ___",
                "",
            ]
        )
    return "\n".join(sections).rstrip() + "\n"


TEACHING_SPECS: tuple[dict[str, Any], ...] = (
    {
        "document_id": "fed-2020-03-23-monetary20200323b",
        "assessment_timestamp": ASSESSMENT_TIMESTAMPS[-1],
        "why": (
            "A high-ranked official policy release directly documents credit "
            "and liquidity support during the stressed state, yet it does not "
            "state that momentum positions unwound."
        ),
        "relevance": "2",
        "mechanism": "policy_or_liquidity_support",
        "direction": "supporting",
        "alternative": (
            "Relevance 1 / contextual if the reviewer requires an explicit "
            "cross-sectional or momentum connection."
        ),
        "human_decision": (
            "Does direct evidence about market-wide credit support save enough "
            "investigation time to be directly useful for this environment?"
        ),
    },
    {
        "document_id": "treasury-2020-03-23-sm951",
        "assessment_timestamp": ASSESSMENT_TIMESTAMPS[-1],
        "why": (
            "This is a near-duplicate policy account from a second official "
            "archive. It tests whether duplicate information should be "
            "discounted even when its grounding is excellent."
        ),
        "relevance": "2",
        "mechanism": "policy_or_liquidity_support",
        "direction": "supporting",
        "alternative": (
            "Relevance 0 as a near-duplicate of the Federal Reserve release, "
            "or relevance 1 because it adds Treasury authorization context."
        ),
        "human_decision": (
            "Does the Treasury-specific passage add useful information beyond "
            "the higher-ranked Federal Reserve release?"
        ),
    },
    {
        "document_id": "sec-2020-03-21-2020-67",
        "assessment_timestamp": ASSESSMENT_TIMESTAMPS[-1],
        "why": (
            "Electronic-auction continuity is evidence of extraordinary "
            "market operating conditions, but its mechanism link to momentum "
            "reversal is indirect."
        ),
        "relevance": "1",
        "mechanism": "market_stress_or_panic",
        "direction": "contextual",
        "alternative": (
            "Relevance 0 if trading-floor operations would not help the PM "
            "investigate the reversal environment."
        ),
        "human_decision": (
            "Is market-functioning context useful background, or merely a "
            "pandemic-era operational detail?"
        ),
    },
    {
        "document_id": "bls-2020-03-11-cpi_03112020",
        "assessment_timestamp": ASSESSMENT_TIMESTAMPS[-1],
        "why": (
            "The release is timestamp-clean and macroeconomic, but describes "
            "February inflation rather than a reversal mechanism."
        ),
        "relevance": "1",
        "mechanism": "generic_macro_context",
        "direction": "contextual",
        "alternative": (
            "Relevance 0 because the passage predates the shock and does not "
            "help explain the contemporaneous reversal."
        ),
        "human_decision": (
            "Would this macro background actually reduce investigation time?"
        ),
    },
    {
        "document_id": "sec-2020-03-20-2020-66",
        "assessment_timestamp": ASSESSMENT_TIMESTAMPS[-1],
        "why": (
            "An official release can be fully timestamp-valid yet completely "
            "irrelevant to the economic mechanism under review."
        ),
        "relevance": "0",
        "mechanism": "other",
        "direction": "irrelevant",
        "alternative": (
            "No plausible higher label unless the archived passage contains "
            "market-mechanism content not visible in the selected passage."
        ),
        "human_decision": (
            "Can the reviewer avoid rewarding official provenance when the "
            "passage itself is unrelated?"
        ),
    },
    {
        "document_id": "treasury-2020-03-19-sm949",
        "assessment_timestamp": ASSESSMENT_TIMESTAMPS[-1],
        "why": (
            "Sanctions and petroleum-market wording can create keyword overlap "
            "without explaining the US equity momentum-reversal environment."
        ),
        "relevance": "0",
        "mechanism": "other",
        "direction": "irrelevant",
        "alternative": (
            "Relevance 1 only if the exact passage contains a defensible "
            "market-stress connection; headline association is insufficient."
        ),
        "human_decision": (
            "Is any mechanism connection present in the passage rather than "
            "in outside knowledge?"
        ),
    },
    {
        "document_id": "fed-2020-03-23-monetary20200323b",
        "assessment_timestamp": ASSESSMENT_TIMESTAMPS[0],
        "why": (
            "The same strong policy document becomes an objective future "
            "negative at the March 18 cutoff."
        ),
        "relevance": "0",
        "mechanism": "policy_or_liquidity_support",
        "direction": "irrelevant",
        "alternative": (
            "None for strict evaluation: invalid_future forces relevance 0 "
            "regardless of later economic usefulness."
        ),
        "human_decision": (
            "Can the reviewer keep economic relevance separate from "
            "timestamp validity?"
        ),
    },
    {
        "document_id": "treasury-2020-03-18-sm950",
        "assessment_timestamp": ASSESSMENT_TIMESTAMPS[-1],
        "why": (
            "This release overlaps the Federal Reserve MMLF announcement but "
            "adds Treasury credit-protection details, making deduplication a "
            "substantive rather than purely textual judgment."
        ),
        "relevance": "2",
        "mechanism": "policy_or_liquidity_support",
        "direction": "supporting",
        "alternative": (
            "Relevance 1 or 0 if the higher-ranked facility announcement "
            "already supplies everything the PM needs."
        ),
        "human_decision": (
            "Does the Treasury-specific detail justify retaining this "
            "near-duplicate?"
        ),
    },
    {
        "document_id": "gdelt-cnbc-2020-03-19-short-sellers",
        "assessment_timestamp": ASSESSMENT_TIMESTAMPS[-1],
        "why": (
            "GDELT proves discovery, and the current snippet challenges a "
            "short-selling explanation, but the exact March 2020 page version "
            "cannot be proven."
        ),
        "relevance": "1 (conditional on timestamp validity)",
        "mechanism": "short_covering_or_position_unwind",
        "direction": "contradicting",
        "alternative": (
            "Timestamp uncertain and excluded from strict metrics; semantic "
            "relevance 0 is also plausible because short selling is not the "
            "same as momentum-position unwind."
        ),
        "human_decision": (
            "Separate the potentially useful contradiction from the failed "
            "historical content-version proof."
        ),
    },
    {
        "document_id": "gdelt-cnn-2020-03-24-market-rebound",
        "assessment_timestamp": ASSESSMENT_TIMESTAMPS[-1],
        "why": (
            "The passage directly documents an extraordinary market rebound, "
            "but GDELT only proves discovery of the evolving live page; the "
            "retrieved content version is not historically verified."
        ),
        "relevance": "2 (conditional on timestamp validity)",
        "mechanism": "market_rebound",
        "direction": "supporting",
        "alternative": (
            "Timestamp uncertain and excluded from strict metrics; semantic "
            "relevance 1 is plausible if a broad-index rebound alone is only "
            "context for the momentum reversal."
        ),
        "human_decision": (
            "Separate strong semantic usefulness from the unresolved "
            "historical content-version proof."
        ),
    },
)


def _teaching_rows(
    annotation_rows: Sequence[Mapping[str, Any]],
) -> list[tuple[dict[str, Any], Mapping[str, Any]]]:
    by_key = {
        (str(row["assessment_timestamp"]), str(row["document_id"])): row
        for row in annotation_rows
    }
    selected: list[tuple[dict[str, Any], Mapping[str, Any]]] = []
    for spec in TEACHING_SPECS:
        key = (
            str(spec["assessment_timestamp"]),
            str(spec["document_id"]),
        )
        if key not in by_key:
            raise ValueError(f"teaching example is absent from queue: {key}")
        selected.append((dict(spec), by_key[key]))
    return selected


def _teaching_markdown(
    annotation_rows: Sequence[Mapping[str, Any]],
) -> str:
    sections = [
        "# Teaching examples",
        "",
        (
            "**NOT GOLD — FOR TRAINING DISCUSSION ONLY.** These provisional "
            "suggestions must not be copied into the annotation queue without "
            "human review."
        ),
        "",
    ]
    for index, (spec, row) in enumerate(
        _teaching_rows(annotation_rows),
        start=1,
    ):
        timestamp_note = (
            "The official archive metadata is cutoff-valid."
            if row["timestamp_validity"] != "invalid_future"
            and not str(row["document_id"]).startswith("gdelt-")
            else (
                "The publication is after this assessment cutoff."
                if row["timestamp_validity"] == "invalid_future"
                else (
                    "Discovery is historical, but the exact historical page "
                    "version is unproven."
                )
            )
        )
        sections.extend(
            [
                f"## Example {index:02d}: {row['title']}",
                "",
                f"- Example ID: `teach-{index:02d}`",
                f"- Assessment timestamp: `{row['assessment_timestamp']}`",
                (
                    f"- Document metadata: {row['source']}; published "
                    f"`{row['publication_timestamp']}`; "
                    f"[source]({row['url']})"
                ),
                "",
                "> " + str(row["retrieved_passage"]).replace("\n", "\n> "),
                "",
                f"Why this is useful: {spec['why']}",
                "",
                "**NOT GOLD — FOR TRAINING DISCUSSION ONLY**",
                "",
                (
                    f"- Provisional label suggestion: relevance "
                    f"`{spec['relevance']}`; mechanism "
                    f"`{spec['mechanism']}`; direction "
                    f"`{spec['direction']}`."
                ),
                f"- Alternative plausible label: {spec['alternative']}",
                f"- What the human must decide: {spec['human_decision']}",
                "",
                "Dimension check:",
                "",
                (
                    "- Economic relevance: judge whether the passage helps "
                    "explain the environment, not whether the source is famous."
                ),
                f"- Timestamp validity: {timestamp_note}",
                (
                    f"- Evidence direction: `{spec['direction']}` is "
                    "provisional and must follow the passage, not the headline."
                ),
                (
                    "- Strength of grounding: any supporting passage must be "
                    "copied exactly from the block quote above."
                ),
                "",
            ]
        )
    return "\n".join(sections).rstrip() + "\n"


def _runbook() -> str:
    return """# Human annotation runbook

## Step 1 — Generate or refresh the candidate pool

From the repository root:

```bash
# Rebuild from the committed, hashed candidate manifest.
uv run python -m src.evaluation.retrieval_gold build

# Intentionally reacquire the small official archive slice.
uv run python -m src.evaluation.retrieval_gold build --refresh-sources
```

Refreshing sources refuses to overwrite an annotated queue unless
`--overwrite-annotations` is supplied intentionally. The production provider
still uses its 120-day window; March 9–24 is only the annotation sampling
window.

## Step 2 — Review the teaching examples

Open `annotation/teaching_examples.md`. Discuss the provisional examples, but
remember that every suggestion is marked **NOT GOLD**.

## Step 3 — Fill the CSV

Edit `annotation/annotation_queue.csv` in batches of 10. Do not change the
candidate metadata columns. For each completed row fill:

`timestamp_validity`, `relevance_label`, `mechanism_labels`,
`evidence_direction`, `supporting_passage`, `reviewer_rationale`,
`reviewer_confidence`, and set `review_status=completed`.

Use semicolons between multiple mechanism labels. Leave unreviewed rows blank.

## Step 4 — Validate each completed batch

```bash
uv run python -m src.evaluation.retrieval_gold validate \
  --annotations data/evaluation/2020_retrieval_gold/annotation/annotation_queue.csv
```

Validation permits the remaining blank rows but rejects malformed completed
rows, duplicate IDs, unsupported mechanisms, ungrounded passages, and
future/relevance conflicts.

## Step 5 — Resolve difficult cases

- choose the lower relevance score when evidence is weak;
- use timestamp `uncertain` when availability cannot be proven;
- use `contextual` instead of `supporting` when the passage does not directly
  connect to the mechanism;
- do not infer momentum-position unwinds from a generic market rally;
- record disagreement with `review_status=needs_discussion` rather than forcing
  certainty.

Resolve disagreements in a second pass and record the final rationale. Never
use future returns, later event summaries, retrieval rank, or a model label.

## Step 6 — Run the final retrieval evaluation

Only after all rows are completed:

```bash
uv run python -m src.evaluation.retrieval_gold evaluate \
  --annotations data/evaluation/2020_retrieval_gold/annotation/annotation_queue.csv \
  --retrieval-results data/evaluation/2020_retrieval_gold/retrieval_results.json
```

## Step 7 — Interpret conservatively

Precision and nDCG describe this small, deliberately sampled March 2020 slice,
not production performance or incremental alpha. Timestamp and passage metrics
are control checks. Mechanism coverage is breadth of human-labeled evidence,
not proof that every mechanism occurred. `not_reported` is the correct result
when the strict sample is too small.
"""


def _awaiting_results(annotation_rows: int) -> dict[str, Any]:
    reason = "Human annotation is incomplete."
    return {
        "evaluation_name": EVALUATION_NAME,
        "status": "AWAITING HUMAN ANNOTATION",
        "annotation_rows": annotation_rows,
        "completed_rows": 0,
        "strict_metric_rows": 0,
        "metrics": {
            metric: {"status": "not_reported", "reason": reason}
            for metric in (
                "Precision@3",
                "Precision@5",
                "nDCG@5",
                "timestamp_valid_rate",
                "citation_valid_rate",
                "exact_passage_match_rate",
                "unsupported_claim_rate",
                "mechanism_coverage",
            )
        },
        "confidence_intervals": {
            "status": "not_reported",
            "reason": "Tiny-sample confidence intervals are not calculated.",
        },
    }


def _evaluation_report(results: Mapping[str, Any]) -> str:
    lines = [
        "# March 2020 retrieval evaluation",
        "",
        f"STATUS: {results['status']}",
        "",
        (
            f"Completed rows: {results['completed_rows']} / "
            f"{results['annotation_rows']}. Strict metric rows: "
            f"{results['strict_metric_rows']}."
        ),
        "",
        "## Metrics",
        "",
        "| Metric | Result |",
        "|---|---|",
    ]
    for metric, value in results["metrics"].items():
        if isinstance(value, Mapping) and value.get("status") == "not_reported":
            rendered = f"not_reported — {value['reason']}"
        else:
            rendered = json.dumps(value, sort_keys=True)
        lines.append(f"| {metric} | {rendered} |")
    lines.extend(
        [
            "",
            (
                "These results evaluate a small, human-adjudicated retrieval "
                "slice. They do not establish prediction, causality, or "
                "incremental alpha."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _has_human_labels(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open(encoding="utf-8", newline="") as handle:
        return any(
            any(
                str(row.get(field, "")).strip()
                for field in ANNOTATION_FIELDS[
                    ANNOTATION_FIELDS.index("relevance_label") :
                ]
            )
            for row in csv.DictReader(handle)
        )


def write_annotation_package(
    retrieval_results: Mapping[str, Any],
    *,
    root: Path = ROOT,
    overwrite_annotations: bool = False,
) -> list[dict[str, Any]]:
    annotation_path = root / ANNOTATION_CSV_PATH.relative_to(ROOT)
    if _has_human_labels(annotation_path) and not overwrite_annotations:
        raise ValueError(
            "annotation queue contains human labels; refusing to overwrite. "
            "Use --overwrite-annotations only after preserving the reviewed file."
        )
    rows = _annotation_rows(retrieval_results)
    _write_csv(annotation_path, rows, ANNOTATION_FIELDS)
    annotation_md = root / ANNOTATION_MD_PATH.relative_to(ROOT)
    annotation_md.parent.mkdir(parents=True, exist_ok=True)
    annotation_md.write_text(_annotation_markdown(rows), encoding="utf-8")
    (root / TEACHING_EXAMPLES_PATH.relative_to(ROOT)).write_text(
        _teaching_markdown(rows),
        encoding="utf-8",
    )
    (root / REVIEWER_CHECKLIST_PATH.relative_to(ROOT)).write_text(
        _reviewer_checklist(),
        encoding="utf-8",
    )
    write_json(root / LABEL_SCHEMA_PATH.relative_to(ROOT), _label_schema())
    (root / RUNBOOK_PATH.relative_to(ROOT)).write_text(
        _runbook(),
        encoding="utf-8",
    )
    awaiting = _awaiting_results(len(rows))
    write_json(
        root / EVALUATION_RESULTS_PATH.relative_to(ROOT),
        awaiting,
    )
    (root / EVALUATION_REPORT_PATH.relative_to(ROOT)).write_text(
        _evaluation_report(awaiting),
        encoding="utf-8",
    )
    return rows


def read_annotations(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != ANNOTATION_FIELDS:
            raise AnnotationValidationError(
                "annotation CSV fields or order differ from the frozen schema"
            )
        return [
            {
                field: str(value or "")
                for field, value in row.items()
            }
            for row in reader
        ]


def _manifest_by_id(
    manifest_path: Path = CORPUS_MANIFEST_PATH,
) -> dict[str, dict[str, Any]]:
    manifest = read_json(manifest_path)
    return {
        str(record["document_id"]): dict(record)
        for record in manifest["candidate_documents"]
    }


def _mechanism_values(value: str) -> tuple[str, ...]:
    return tuple(
        item.strip()
        for item in value.split(";")
        if item.strip()
    )


def validate_annotation_rows(
    rows: Sequence[Mapping[str, str]],
    *,
    manifest_by_id: Mapping[str, Mapping[str, Any]],
    require_complete: bool = False,
) -> dict[str, Any]:
    """Validate immutable metadata and all completed human judgments."""

    errors: list[str] = []
    annotation_ids = [str(row["annotation_id"]).strip() for row in rows]
    duplicate_ids = sorted(
        {
            annotation_id
            for annotation_id in annotation_ids
            if annotation_ids.count(annotation_id) > 1
        }
    )
    if duplicate_ids:
        errors.append(f"duplicate annotation IDs: {duplicate_ids}")

    completed = 0
    discussion = 0
    for index, row in enumerate(rows, start=2):
        annotation_id = row["annotation_id"].strip() or f"CSV line {index}"
        required_metadata = (
            "annotation_id",
            "query_id",
            "assessment_timestamp",
            "document_id",
            "title",
            "source",
            "url",
            "publication_timestamp",
            "discovery_timestamp",
            "availability_timestamp",
            "retrieved_passage",
            "candidate_score",
        )
        for field in required_metadata:
            if not row[field].strip():
                errors.append(f"{annotation_id}: blank required field {field}")

        document_id = row["document_id"].strip()
        document = manifest_by_id.get(document_id)
        if document is None:
            errors.append(f"{annotation_id}: unknown document_id {document_id}")
            continue
        immutable_mapping = {
            "title": "title",
            "source": "source",
            "url": "url",
            "publication_timestamp": "publication_timestamp",
            "discovery_timestamp": "discovery_timestamp",
            "availability_timestamp": "availability_timestamp",
            "retrieved_passage": "passage",
        }
        for csv_field, manifest_field in immutable_mapping.items():
            if row[csv_field] != str(document[manifest_field]):
                errors.append(
                    f"{annotation_id}: immutable {csv_field} differs from "
                    "candidate manifest"
                )

        semantic_fields = (
            "relevance_label",
            "mechanism_labels",
            "evidence_direction",
            "supporting_passage",
            "reviewer_rationale",
            "reviewer_confidence",
        )
        status = row["review_status"].strip()
        any_semantic = any(row[field].strip() for field in semantic_fields)
        if status == "needs_discussion":
            discussion += 1
            continue
        if status in {"", "pending"}:
            if any_semantic:
                errors.append(
                    f"{annotation_id}: partial labels require "
                    "review_status=completed or needs_discussion"
                )
            continue
        if status != "completed":
            errors.append(
                f"{annotation_id}: unsupported review_status {status!r}"
            )
            continue
        completed += 1

        timestamp_validity = row["timestamp_validity"].strip()
        if timestamp_validity not in TIMESTAMP_VALIDITIES:
            errors.append(
                f"{annotation_id}: invalid timestamp_validity "
                f"{timestamp_validity!r}"
            )
        objective = _objective_timestamp_status(
            document,
            row["assessment_timestamp"],
        )
        if objective == "invalid_future" and (
            timestamp_validity != "invalid_future"
        ):
            errors.append(
                f"{annotation_id}: objectively future document must be "
                "invalid_future"
            )
        if objective == "uncertain" and timestamp_validity == "valid":
            errors.append(
                f"{annotation_id}: unverified content version cannot be valid"
            )

        relevance_text = row["relevance_label"].strip()
        if relevance_text not in RELEVANCE_LABELS:
            errors.append(
                f"{annotation_id}: relevance_label must be 0, 1, or 2"
            )
            relevance = None
        else:
            relevance = int(relevance_text)
        if timestamp_validity == "invalid_future" and relevance not in {
            None,
            0,
        }:
            errors.append(
                f"{annotation_id}: invalid_future requires relevance 0"
            )

        mechanisms = _mechanism_values(row["mechanism_labels"])
        if not mechanisms:
            errors.append(f"{annotation_id}: mechanism_labels is blank")
        invalid_mechanisms = sorted(set(mechanisms).difference(MECHANISMS))
        if invalid_mechanisms:
            errors.append(
                f"{annotation_id}: invalid mechanisms {invalid_mechanisms}"
            )
        if len(mechanisms) != len(set(mechanisms)):
            errors.append(
                f"{annotation_id}: mechanism_labels contains duplicates"
            )
        if relevance == 0 and mechanisms != ("other",):
            errors.append(
                f"{annotation_id}: relevance 0 requires mechanism other"
            )
        if relevance in {1, 2} and "other" in mechanisms:
            errors.append(
                f"{annotation_id}: relevant rows cannot use mechanism other"
            )

        direction = row["evidence_direction"].strip()
        if direction not in EVIDENCE_DIRECTIONS:
            errors.append(
                f"{annotation_id}: invalid evidence_direction {direction!r}"
            )
        if relevance == 0 and direction != "irrelevant":
            errors.append(
                f"{annotation_id}: irrelevant rows require "
                "evidence_direction=irrelevant"
            )
        if relevance in {1, 2} and direction == "irrelevant":
            errors.append(
                f"{annotation_id}: relevant row cannot be marked irrelevant"
            )

        supporting = row["supporting_passage"].strip()
        archived_passage = str(document["passage"])
        if supporting and supporting not in archived_passage:
            errors.append(
                f"{annotation_id}: supporting passage is not an exact "
                "substring of the archived passage"
            )
        if relevance == 2 and not supporting:
            errors.append(
                f"{annotation_id}: relevance 2 requires a grounded passage"
            )
        if relevance == 0 and supporting:
            errors.append(
                f"{annotation_id}: relevance 0 must not claim a supporting "
                "passage"
            )
        if not row["reviewer_rationale"].strip():
            errors.append(
                f"{annotation_id}: completed row requires reviewer_rationale"
            )
        if row["reviewer_confidence"].strip() not in REVIEWER_CONFIDENCES:
            errors.append(
                f"{annotation_id}: reviewer_confidence must be high, medium, "
                "or low"
            )

    if require_complete and completed != len(rows):
        errors.append(
            f"all rows must be completed; completed={completed}, total={len(rows)}"
        )
    if errors:
        preview = "\n".join(f"- {error}" for error in errors[:30])
        if len(errors) > 30:
            preview += f"\n- … {len(errors) - 30} additional errors"
        raise AnnotationValidationError(
            f"annotation validation failed ({len(errors)} errors):\n{preview}"
        )
    return {
        "status": (
            "complete" if completed == len(rows) else "awaiting_annotation"
        ),
        "rows": len(rows),
        "completed_rows": completed,
        "needs_discussion_rows": discussion,
        "pending_rows": len(rows) - completed - discussion,
    }


def validate_annotations(
    annotations_path: Path,
    *,
    manifest_path: Path = CORPUS_MANIFEST_PATH,
    require_complete: bool = False,
) -> dict[str, Any]:
    rows = read_annotations(annotations_path)
    report = validate_annotation_rows(
        rows,
        manifest_by_id=_manifest_by_id(manifest_path),
        require_complete=require_complete,
    )
    return {
        **report,
        "annotations_path": str(annotations_path),
        "annotations_sha256": sha256_file(annotations_path),
    }


def _not_reported(reason: str) -> dict[str, str]:
    return {"status": "not_reported", "reason": reason}


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _precision_at(
    grouped_rows: Mapping[tuple[str, str], Sequence[Mapping[str, str]]],
    k: int,
) -> float | dict[str, str]:
    values = []
    for rows in grouped_rows.values():
        ordered = sorted(
            rows,
            key=lambda row: (
                int(row["candidate_rank"])
                if row["candidate_rank"].strip()
                else 10**9,
                -float(row["candidate_score"]),
                row["document_id"],
            ),
        )
        if len(ordered) < k:
            continue
        values.append(
            sum(int(row["relevance_label"]) >= 1 for row in ordered[:k]) / k
        )
    if not values:
        return _not_reported(
            f"No strict assessment-query group has at least {k} labeled rows."
        )
    return round(_mean(values), 6)


def _ndcg_at(
    grouped_rows: Mapping[tuple[str, str], Sequence[Mapping[str, str]]],
    k: int,
) -> float | dict[str, str]:
    values = []
    for rows in grouped_rows.values():
        if len(rows) < k:
            continue
        ordered = sorted(
            rows,
            key=lambda row: (
                int(row["candidate_rank"])
                if row["candidate_rank"].strip()
                else 10**9,
                -float(row["candidate_score"]),
                row["document_id"],
            ),
        )[:k]
        gains = [2 ** int(row["relevance_label"]) - 1 for row in ordered]
        ideal = sorted(gains, reverse=True)
        dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
        idcg = sum(
            gain / math.log2(index + 2)
            for index, gain in enumerate(ideal)
        )
        if idcg > 0:
            values.append(dcg / idcg)
    if not values:
        return _not_reported(
            f"No strict assessment-query group has {k} rows with nonzero ideal gain."
        )
    return round(_mean(values), 6)


def evaluate_annotations(
    *,
    annotations_path: Path,
    retrieval_results_path: Path,
    manifest_path: Path = CORPUS_MANIFEST_PATH,
    results_path: Path = EVALUATION_RESULTS_PATH,
    report_path: Path = EVALUATION_REPORT_PATH,
) -> dict[str, Any]:
    """Calculate metrics only after every human annotation is complete."""

    rows = read_annotations(annotations_path)
    manifest_by_id = _manifest_by_id(manifest_path)
    validation = validate_annotation_rows(
        rows,
        manifest_by_id=manifest_by_id,
        require_complete=False,
    )
    retrieval = read_json(retrieval_results_path)
    if retrieval.get("human_annotations_read") is not False:
        raise ValueError("retrieval results are not independent of human labels")
    candidate_protocol = read_json(CANDIDATE_PROTOCOL_PATH)
    if retrieval.get("candidate_protocol_hash") != candidate_protocol.get(
        "protocol_hash"
    ):
        raise ValueError("retrieval results do not match candidate protocol")

    if validation["completed_rows"] != len(rows):
        results = _awaiting_results(len(rows))
        results["completed_rows"] = validation["completed_rows"]
        results["strict_metric_rows"] = sum(
            row["review_status"] == "completed"
            and row["timestamp_validity"] == "valid"
            for row in rows
        )
        results["annotations_sha256"] = sha256_file(annotations_path)
        results["retrieval_results_sha256"] = sha256_file(
            retrieval_results_path
        )
        write_json(results_path, results)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(_evaluation_report(results), encoding="utf-8")
        return results

    strict_rows = [
        row for row in rows if row["timestamp_validity"] == "valid"
    ]
    grouped: dict[tuple[str, str], list[Mapping[str, str]]] = defaultdict(list)
    for row in strict_rows:
        grouped[
            (row["assessment_timestamp"], row["query_id"])
        ].append(row)

    timestamp_denominator = [
        row for row in rows if row["timestamp_validity"] != "uncertain"
    ]
    relevant_strict = [
        row for row in strict_rows if int(row["relevance_label"]) >= 1
    ]
    if timestamp_denominator:
        timestamp_valid_rate: Any = round(
            sum(
                row["timestamp_validity"] == "valid"
                for row in timestamp_denominator
            )
            / len(timestamp_denominator),
            6,
        )
    else:
        timestamp_valid_rate = _not_reported(
            "Every completed timestamp judgment is uncertain."
        )

    if relevant_strict:
        grounded = [
            bool(row["supporting_passage"].strip())
            and row["supporting_passage"].strip()
            in row["retrieved_passage"]
            for row in relevant_strict
        ]
        citation_valid_rate: Any = round(
            sum(
                is_grounded and bool(row["url"].strip())
                for row, is_grounded in zip(relevant_strict, grounded)
            )
            / len(relevant_strict),
            6,
        )
        exact_passage_match_rate: Any = round(
            sum(grounded) / len(grounded),
            6,
        )
        unsupported_claim_rate: Any = round(
            sum(not value for value in grounded) / len(grounded),
            6,
        )
    else:
        reason = "No strict timestamp-valid row has relevance 1 or 2."
        citation_valid_rate = _not_reported(reason)
        exact_passage_match_rate = _not_reported(reason)
        unsupported_claim_rate = _not_reported(reason)

    covered = sorted(
        {
            mechanism
            for row in relevant_strict
            for mechanism in _mechanism_values(row["mechanism_labels"])
            if mechanism != "other"
        }
    )
    possible = [mechanism for mechanism in MECHANISMS if mechanism != "other"]
    mechanism_coverage: Any
    if relevant_strict:
        mechanism_coverage = {
            "covered_mechanisms": covered,
            "covered_count": len(covered),
            "possible_count": len(possible),
            "coverage_rate": round(len(covered) / len(possible), 6),
        }
    else:
        mechanism_coverage = _not_reported(
            "No strict relevant rows are available."
        )

    results = {
        "evaluation_name": EVALUATION_NAME,
        "status": "COMPLETE — HUMAN LABELS EVALUATED",
        "annotation_rows": len(rows),
        "completed_rows": len(rows),
        "strict_metric_rows": len(strict_rows),
        "uncertain_rows_excluded": sum(
            row["timestamp_validity"] == "uncertain" for row in rows
        ),
        "metrics": {
            "Precision@3": _precision_at(grouped, 3),
            "Precision@5": _precision_at(grouped, 5),
            "nDCG@5": _ndcg_at(grouped, 5),
            "timestamp_valid_rate": timestamp_valid_rate,
            "citation_valid_rate": citation_valid_rate,
            "exact_passage_match_rate": exact_passage_match_rate,
            "unsupported_claim_rate": unsupported_claim_rate,
            "mechanism_coverage": mechanism_coverage,
        },
        "confidence_intervals": {
            "status": "not_reported",
            "reason": "Tiny-sample confidence intervals are not calculated.",
        },
        "annotations_sha256": sha256_file(annotations_path),
        "retrieval_results_sha256": sha256_file(retrieval_results_path),
        "interpretation_limits": [
            "small human-adjudicated March 2020 slice",
            "no predictive or causal claim",
            "no incremental-alpha claim",
            "sampled query-document pairs are not a population estimate",
        ],
    }
    write_json(results_path, results)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_evaluation_report(results), encoding="utf-8")
    return results


def _workflow_file_paths(root: Path = ROOT) -> list[Path]:
    return [
        root / GUIDELINES_PATH.relative_to(ROOT),
        root / EVALUATION_PROTOCOL_PATH.relative_to(ROOT),
        root / CANDIDATE_PROTOCOL_PATH.relative_to(ROOT),
        root / ARCHIVED_CORPUS_PATH.relative_to(ROOT),
        root / CORPUS_MANIFEST_PATH.relative_to(ROOT),
        root / ACQUISITION_LOG_PATH.relative_to(ROOT),
        root / RETRIEVAL_RESULTS_PATH.relative_to(ROOT),
        root / ANNOTATION_CSV_PATH.relative_to(ROOT),
        root / ANNOTATION_MD_PATH.relative_to(ROOT),
        root / TEACHING_EXAMPLES_PATH.relative_to(ROOT),
        root / REVIEWER_CHECKLIST_PATH.relative_to(ROOT),
        root / LABEL_SCHEMA_PATH.relative_to(ROOT),
        root / RUNBOOK_PATH.relative_to(ROOT),
        root / EVALUATION_RESULTS_PATH.relative_to(ROOT),
        root / EVALUATION_REPORT_PATH.relative_to(ROOT),
        REPO_ROOT / "src" / "evaluation" / "__init__.py",
        REPO_ROOT / "src" / "evaluation" / "retrieval_gold.py",
        REPO_ROOT / "tests" / "test_retrieval_gold.py",
        STATUS_PATH,
    ]


def write_component_status(
    *,
    manifest: Mapping[str, Any],
    retrieval_results: Mapping[str, Any],
    annotation_rows: Sequence[Mapping[str, Any]],
    candidate_protocol: Mapping[str, Any],
    tests_run: Sequence[str] = (),
    tests_passed: bool = False,
    blockers: Sequence[str] = (),
    human_annotation_status: str = "awaiting_human_annotation",
) -> dict[str, Any]:
    candidates = list(manifest["candidate_documents"])
    result_rows = list(retrieval_results["candidate_results"])
    primary_timestamp = ASSESSMENT_TIMESTAMPS[-1]
    primary_rows = [
        row
        for row in result_rows
        if row["assessment_timestamp"] == primary_timestamp
    ]
    future_ids = {
        row["document_id"]
        for row in result_rows
        if row["objective_timestamp_status"] == "invalid_future"
    }
    payload = {
        "component": "march_2020_retrieval_gold_workflow",
        "status": (
            "awaiting_human_annotation"
            if not blockers
            else "blocked"
        ),
        "protocol_version": PROTOCOL_VERSION,
        "protocol_hash": candidate_protocol["protocol_hash"],
        "candidate_documents": len(candidates),
        "annotation_pairs": len(annotation_rows),
        "teaching_examples": len(TEACHING_SPECS),
        "strict_timestamp_valid_candidates": sum(
            row["objective_timestamp_status"] == "valid"
            for row in primary_rows
        ),
        "timestamp_uncertain_candidates": sum(
            document["availability_status"] == "content_version_uncertain"
            for document in candidates
        ),
        "future_invalid_candidates": len(future_ids),
        "files_created": [
            str(path.relative_to(REPO_ROOT))
            for path in _workflow_file_paths()
            if path.is_file()
        ],
        "files_modified": [],
        "tests_run": list(tests_run),
        "tests_passed": tests_passed,
        "human_annotation_status": human_annotation_status,
        "blockers": list(blockers),
        "quiet_control": {
            "as_of_date": QUIET_CONTROL_DATE,
            "expected_evidence_status": "skipped_quiet_state",
            "verified": True,
        },
        "candidate_manifest_hash": manifest["manifest_hash"],
        "retrieval_results_hash": retrieval_results[
            "retrieval_results_hash"
        ],
    }
    write_json(STATUS_PATH, payload)
    return payload


def record_test_status(
    *,
    tests_run: Sequence[str],
    tests_passed: bool,
) -> dict[str, Any]:
    """Update only the test fields after the tracked commands complete."""

    payload = read_json(STATUS_PATH)
    payload["tests_run"] = list(tests_run)
    payload["tests_passed"] = bool(tests_passed)
    payload["files_created"] = [
        str(path.relative_to(REPO_ROOT))
        for path in _workflow_file_paths()
        if path.is_file() or path == STATUS_PATH
    ]
    write_json(STATUS_PATH, payload)
    return payload


def build_workflow(
    *,
    root: Path = ROOT,
    refresh_sources: bool = False,
    overwrite_annotations: bool = False,
) -> dict[str, Any]:
    """Build protocols, corpus package, deterministic sample, and handoff."""

    candidate_protocol, evaluation_protocol = write_frozen_protocols(root)
    manifest_path = root / CORPUS_MANIFEST_PATH.relative_to(ROOT)
    corpus_path = root / ARCHIVED_CORPUS_PATH.relative_to(ROOT)
    if refresh_sources or not (
        manifest_path.is_file() and corpus_path.is_file()
    ):
        manifest = acquire_candidate_corpus(root)
    else:
        manifest = read_json(manifest_path)
        if manifest["candidate_protocol_hash"] != candidate_protocol[
            "protocol_hash"
        ]:
            raise ValueError(
                "committed candidate manifest does not match the frozen "
                "protocol; refresh sources intentionally"
            )
        load_archived_corpus(corpus_path)

    retrieval_results = build_retrieval_results(
        manifest,
        candidate_protocol,
    )
    retrieval_path = root / RETRIEVAL_RESULTS_PATH.relative_to(ROOT)
    write_json(retrieval_path, retrieval_results)
    annotation_rows = write_annotation_package(
        retrieval_results,
        root=root,
        overwrite_annotations=overwrite_annotations,
    )

    from src.evidence.mvp import build_evidence_snapshot

    quiet_primary = build_primary_assessment(
        as_of_date=pd.Timestamp(QUIET_CONTROL_DATE),
        horizon=20,
    )
    quiet_evidence = build_evidence_snapshot(
        primary=quiet_primary,
        provider_mode="archived",
        archived_corpus_path=corpus_path,
    )
    if quiet_evidence.status != "skipped_quiet_state":
        raise ValueError("quiet-state control did not skip evidence retrieval")

    if root == ROOT:
        status = write_component_status(
            manifest=manifest,
            retrieval_results=retrieval_results,
            annotation_rows=annotation_rows,
            candidate_protocol=candidate_protocol,
        )
    else:
        status = {
            "component": "march_2020_retrieval_gold_workflow",
            "status": "awaiting_human_annotation",
        }
    return {
        "evaluation_name": EVALUATION_NAME,
        "candidate_protocol_hash": candidate_protocol["protocol_hash"],
        "evaluation_protocol_hash": evaluation_protocol["protocol_hash"],
        "candidate_documents": len(manifest["candidate_documents"]),
        "strict_corpus_documents": manifest["counts"][
            "strict_corpus_documents"
        ],
        "annotation_pairs": len(annotation_rows),
        "teaching_examples": len(TEACHING_SPECS),
        "quiet_control_status": quiet_evidence.status,
        "human_annotation_status": status["status"],
    }


def representative_teaching_examples(
    annotations_path: Path = ANNOTATION_CSV_PATH,
    *,
    limit: int = 5,
) -> list[dict[str, str]]:
    rows = read_annotations(annotations_path)
    teaching = _teaching_rows(rows)
    representative_indexes = (0, 2, 4, 6, 8)
    selected = [
        teaching[index]
        for index in representative_indexes
        if index < len(teaching)
    ][:limit]
    return [
        {
            "title": str(row["title"]),
            "source": str(row["source"]),
            "assessment_timestamp": str(row["assessment_timestamp"]),
            "publication_timestamp": str(row["publication_timestamp"]),
            "passage": str(row["retrieved_passage"]),
            "provisional_relevance": str(spec["relevance"]),
            "provisional_mechanism": str(spec["mechanism"]),
            "why_instructive": str(spec["why"]),
        }
        for spec, row in selected
    ]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser(
        "build",
        help="Build or refresh the candidate and annotation package.",
    )
    build_parser.add_argument(
        "--refresh-sources",
        action="store_true",
        help="Reacquire the frozen official archive inventory.",
    )
    build_parser.add_argument(
        "--overwrite-annotations",
        action="store_true",
        help="Intentionally replace a queue that already contains labels.",
    )

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate completed rows while allowing untouched pending rows.",
    )
    validate_parser.add_argument(
        "--annotations",
        type=Path,
        default=ANNOTATION_CSV_PATH,
    )
    validate_parser.add_argument(
        "--require-complete",
        action="store_true",
    )

    evaluate_parser = subparsers.add_parser(
        "evaluate",
        help="Evaluate only after every human row is complete.",
    )
    evaluate_parser.add_argument(
        "--annotations",
        type=Path,
        default=ANNOTATION_CSV_PATH,
    )
    evaluate_parser.add_argument(
        "--retrieval-results",
        type=Path,
        default=RETRIEVAL_RESULTS_PATH,
    )

    examples_parser = subparsers.add_parser(
        "show-examples",
        help="Print representative NOT-GOLD teaching candidates.",
    )
    examples_parser.add_argument("--limit", type=int, default=5)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.command == "build":
        result = build_workflow(
            refresh_sources=args.refresh_sources,
            overwrite_annotations=args.overwrite_annotations,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    if args.command == "validate":
        result = validate_annotations(
            args.annotations,
            require_complete=args.require_complete,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    if args.command == "evaluate":
        result = evaluate_annotations(
            annotations_path=args.annotations,
            retrieval_results_path=args.retrieval_results,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    examples = representative_teaching_examples(
        limit=max(1, min(args.limit, 5))
    )
    print(json.dumps(examples, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
