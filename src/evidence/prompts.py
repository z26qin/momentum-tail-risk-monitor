"""Versioned prompt and structured input for evidence classification."""

from __future__ import annotations

from typing import Any

from src.monitoring.contracts import (
    RetrievalRequest,
    RetrievalResult,
    RiskState,
)


PROMPT_VERSION = "momentum-evidence-classifier-v1"
CLASSIFIER_MODE = "codex_assisted_cached_fixture"
SYSTEM_PROMPT = """\
You classify only the supplied candidate passages relative to a deterministic
momentum tail-risk state.

Allowed classifications:
- supporting: the passage aligns with the current deterministic risk severity
  through an explicit allowed mechanism.
- contradicting: the passage challenges the current deterministic risk
  severity through an explicit allowed mechanism.
- contextual: relevant background, mixed direction, or no clear direction
  relative to the risk state.
- irrelevant: no defensible connection to an allowed momentum-risk mechanism.

Rules:
1. Never change or recalculate the risk probability.
2. Use only facts present in the supplied passage.
3. Copy extracted_passage exactly from the supplied passage.
4. Do not invent timestamps, URLs, sources, drivers, or document IDs.
5. Assign specificity as momentum_specific, mechanism_proxy,
   generic_context, or not_applicable.
6. Use momentum_specific only when the passage explicitly concerns momentum
   portfolios, momentum winners/losers, or the momentum factor.
7. Use mechanism_proxy when the passage directly describes an allowed
   mechanism, such as liquidity stress or sector rotation, without explicitly
   identifying momentum.
8. Use generic_context for broad macro or market conditions with no direct
   mechanism evidence. Generic context is not momentum-specific.
9. Every non-irrelevant item needs one allowed mechanism, one allowed related
   driver, and an extracted passage.
10. An irrelevant item uses mechanism="other", specificity="not_applicable",
    null driver and passage, and a concise exclusion_reason.
11. Add one concise classification_rationale explaining why the passage has
    that direction and specificity. Do not add facts absent from the passage
    or deterministic state.
12. Classify every supplied document exactly once.

Return only a JSON object matching the response schema.
"""

RESPONSE_ITEM_FIELDS = frozenset(
    {
        "document_id",
        "classification",
        "mechanism",
        "related_driver",
        "extracted_passage",
        "confidence",
        "specificity",
        "classification_rationale",
        "exclusion_reason",
    }
)
RESPONSE_FIELDS = frozenset(
    {
        "schema_version",
        "as_of_date",
        "prompt_version",
        "model_identifier",
        "classifier_mode",
        "temperature",
        "items",
    }
)


def build_classifier_input(
    *,
    risk_state: RiskState,
    request: RetrievalRequest,
    retrieval_result: RetrievalResult,
) -> dict[str, Any]:
    """Expose only deterministic state and cached candidate facts."""

    queries = {
        query.query_id: {
            "mechanism": query.mechanism,
            "related_drivers": list(query.related_drivers),
        }
        for query in request.queries
    }
    return {
        "prompt_version": PROMPT_VERSION,
        "risk_state": {
            "as_of_date": risk_state.as_of_date,
            "timestamp_cutoff": risk_state.as_of_timestamp,
            "risk_horizon_trading_days": (
                risk_state.risk_horizon_trading_days
            ),
            "risk_probability": risk_state.risk_probability,
            "risk_severity": risk_state.risk_severity,
            "historical_percentile": risk_state.historical_percentile,
            "primary_market_drivers": [
                {
                    "feature": driver.feature,
                    "mechanism": driver.mechanism,
                    "risk_direction": driver.risk_direction,
                }
                for driver in risk_state.primary_market_drivers
            ],
        },
        "allowed_queries": queries,
        "candidate_documents": [
            {
                "document_id": document.document_id,
                "title": document.title,
                "source": document.source,
                "publication_timestamp": document.publication_timestamp,
                "url": document.url_or_source_id,
                "passage": document.snippet_or_passage,
                "matched_query_ids": list(document.matched_query_ids),
            }
            for document in retrieval_result.documents
        ],
    }
