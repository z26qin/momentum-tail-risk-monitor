"""Thin, deterministic integration that assembles a PM Evidence Card.

The card composes existing Phase 1--4 deterministic components for one selected
date, an optional comparison date, and a supported threshold profile, then adds
point-in-time evidence and an optional, constrained narrative synthesis. It does
not reimplement any indicator, threshold, score, or retrieval mechanism.

Design guarantees (see ``tests/mvp/test_evidence_card.py``):

* every quantitative value comes from the frozen Phase 1--4 code paths;
* narrative synthesis is optional, offline by default, and can never write a
  quantitative field;
* the card is fully populated with no language-model key, no retrieved
  evidence, and no comparison date;
* future ``as_of_date`` values and comparison dates on or after ``as_of_date``
  are rejected.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.evidence.research_preview import build_research_preview
from src.monitoring.scorecard import (
    DEFAULT_CONFIG,
    ScorecardConfig,
    build_scorecard,
)
from src.mvp.llm_synthesis import (
    DeterministicSynthesizer,
    SynthesisResult,
    Synthesizer,
)
from src.regime.market_state import build_regime_history
from src.risk.dm_engine import build_insurance_table, build_primary_assessment
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    REPO_ROOT,
    iso_date,
    parse_as_of_date,
    sha256_file,
    write_json,
)


SCHEMA_VERSION = "evidence-card-v1"
DETERMINISTIC_INPUT_SCHEMA_VERSION = "deterministic-evidence-input-v1"

RISK_STATES = frozenset({"normal", "bear_low_volatility", "panic_elevated"})
SIGNAL_STATUSES = frozenset({"triggered", "not_triggered", "unavailable"})
SIGNAL_DIRECTIONS = frozenset({"greater_than_or_equal", "less_than_or_equal"})
EVIDENCE_STANCES = frozenset({"supporting", "contradicting", "contextual"})
EVIDENCE_QUALITIES = frozenset({"available", "unavailable"})
SYNTHESIS_MODES = frozenset(
    {
        "deterministic_no_llm",
        "deterministic_template",
        "external_synthesizer",
        "deterministic_fallback",
    }
)

#: Supported threshold profiles. Each maps to a frozen ``ScorecardConfig``. Only
#: ``default`` is published; unsupported names are rejected rather than guessed.
THRESHOLD_PROFILES: dict[str, ScorecardConfig] = {"default": DEFAULT_CONFIG}

FACTORS_FILE = "french_research_factors_daily.parquet"
RISK_FILE = "leg_risk_history.parquet"
FEATURES_FILE = "market_features.parquet"

DEFAULT_EVIDENCE_CARD_DIR = DEFAULT_OUTPUT_DIR / "demo"
QUANT_MODEL_FAMILY = "phase-1-4-deterministic-v1"
DATA_VERSION_FILES = (
    FEATURES_FILE,
    RISK_FILE,
    FACTORS_FILE,
    "momentum_labels_h5.parquet",
    "momentum_labels_h20.parquet",
)


def resolve_threshold_profile(name: str) -> ScorecardConfig:
    """Return the config for a supported profile or reject an unsupported one."""

    try:
        return THRESHOLD_PROFILES[name]
    except (KeyError, TypeError):
        supported = ", ".join(sorted(THRESHOLD_PROFILES))
        raise ValueError(
            f"unsupported threshold profile {name!r}; supported profiles: {supported}"
        ) from None


def _clean_float(value: Any) -> float | None:
    if value is None or value is pd.NA or pd.isna(value):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _fmt(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "unavailable"
    return f"{value:+.4f}" if signed else f"{value:.4f}"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuantSignal:
    """One deterministic risk decision. All numbers originate from Phase 1--4."""

    name: str
    current_value: float | None
    threshold: float | None
    status: str
    direction: str | None
    change_vs_comparison: float | None
    interpretation: str
    source_component: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("signal name is required")
        if self.status not in SIGNAL_STATUSES:
            raise ValueError(f"unsupported signal status: {self.status}")
        if self.direction is not None and self.direction not in SIGNAL_DIRECTIONS:
            raise ValueError(f"unsupported signal direction: {self.direction}")
        for value, field in (
            (self.current_value, "current_value"),
            (self.threshold, "threshold"),
            (self.change_vs_comparison, "change_vs_comparison"),
        ):
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"{field} must be finite or null")
        if self.status != "unavailable" and self.current_value is None:
            raise ValueError("available signals require a current value")
        if not self.interpretation or not self.source_component:
            raise ValueError("signal interpretation and source are required")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class RetrievedEvidence:
    """One point-in-time evidence item. Never establishes causality."""

    evidence_id: str
    timestamp: str
    source: str
    headline_or_summary: str
    relevance_reason: str | None
    stance: str | None
    citation_or_locator: str | None

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.timestamp:
            raise ValueError("evidence id and timestamp are required")
        if not self.source or not self.headline_or_summary:
            raise ValueError("evidence source and headline are required")
        if self.stance is not None and self.stance not in EVIDENCE_STANCES:
            raise ValueError(f"unsupported evidence stance: {self.stance}")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class DeterministicEvidenceInput:
    """Validated, narrative-free input for an Evidence Card.

    This is a projection of the existing deterministic card assembly. It keeps
    the repository's established ``QuantSignal`` and ``RetrievedEvidence``
    contracts rather than introducing parallel indicator or evidence models.
    """

    schema_version: str
    as_of_date: str
    comparison_date: str | None
    overall_risk_state: str
    deterministic_score: float | None

    triggered_quant_signals: tuple[QuantSignal, ...]
    non_triggered_relevant_signals: tuple[QuantSignal, ...]

    retrieved_evidence: tuple[RetrievedEvidence, ...]
    historical_analogs: tuple[dict[str, Any], ...]
    data_warnings: tuple[str, ...]

    threshold_profile: str
    data_cutoff: str
    run_id: str
    audit_metadata: dict[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != DETERMINISTIC_INPUT_SCHEMA_VERSION:
            raise ValueError("unsupported deterministic evidence-input schema")
        _require_iso_date(self.as_of_date, "as_of_date")
        if self.comparison_date is not None:
            _require_iso_date(self.comparison_date, "comparison_date")
            if self.comparison_date >= self.as_of_date:
                raise ValueError("comparison_date must be strictly before as_of_date")
        if self.overall_risk_state not in RISK_STATES:
            raise ValueError(f"unsupported risk state: {self.overall_risk_state}")
        if self.deterministic_score is not None and not math.isfinite(
            float(self.deterministic_score)
        ):
            raise ValueError("deterministic_score must be finite or null")
        for signal in self.triggered_quant_signals:
            if signal.status != "triggered":
                raise ValueError("triggered_quant_signals must all be triggered")
        for signal in self.non_triggered_relevant_signals:
            if signal.status == "triggered":
                raise ValueError(
                    "non_triggered_relevant_signals cannot contain a trigger"
                )
        signal_names = [
            signal.name
            for signal in (
                self.triggered_quant_signals
                + self.non_triggered_relevant_signals
            )
        ]
        if len(signal_names) != len(set(signal_names)):
            raise ValueError("deterministic signal names must be unique")
        if not self.threshold_profile or not self.run_id or not self.data_cutoff:
            raise ValueError("profile, cutoff, and run_id are required")
        cutoff = _require_iso_datetime(self.data_cutoff, "data_cutoff")
        evidence_ids: list[str] = []
        for item in self.retrieved_evidence:
            publication = _require_iso_datetime(
                item.timestamp, f"evidence {item.evidence_id} timestamp"
            )
            if publication > cutoff:
                raise ValueError(
                    f"evidence {item.evidence_id} is later than data_cutoff"
                )
            evidence_ids.append(item.evidence_id)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("retrieved evidence IDs must be unique")
        if any(
            not isinstance(item, dict) for item in self.historical_analogs
        ):
            raise ValueError("historical_analogs must contain dictionaries")
        if any(
            not isinstance(item, str) or not item.strip()
            for item in self.data_warnings
        ):
            raise ValueError("data_warnings must contain non-empty strings")
        if not isinstance(self.audit_metadata, dict):
            raise ValueError("audit_metadata must be a dictionary")
        if (
            self.audit_metadata.get("adapter_version")
            != DETERMINISTIC_INPUT_SCHEMA_VERSION
        ):
            raise ValueError("audit_metadata adapter_version is missing or invalid")
        try:
            json.dumps(
                {
                    "historical_analogs": self.historical_analogs,
                    "audit_metadata": self.audit_metadata,
                },
                sort_keys=True,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "historical analogs and audit metadata must be strict JSON"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class EvidenceCard:
    """PM-facing card. Deterministic facts are separate from narrative text."""

    schema_version: str
    as_of_date: str
    comparison_date: str | None

    overall_risk_state: str
    deterministic_score: float | None
    tail_loss_frequency: float | None
    tail_loss_horizon_days: int | None
    evidence_quality: str

    triggered_quant_signals: tuple[QuantSignal, ...]
    non_triggered_relevant_signals: tuple[QuantSignal, ...]

    narrative_state: str
    what_changed: tuple[str, ...]

    supporting_evidence: tuple[RetrievedEvidence, ...]
    contradicting_evidence: tuple[RetrievedEvidence, ...]
    contextual_evidence: tuple[RetrievedEvidence, ...]
    missing_or_uncertain_evidence: tuple[str, ...]

    historical_analogs: tuple[dict[str, Any], ...]

    pm_interpretation: str
    monitoring_questions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]

    threshold_profile: str
    data_version: str
    quant_model_version: str
    data_cutoff: str
    run_id: str
    llm_enabled: bool
    synthesis_mode: str
    model_or_prompt_version: str | None
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported evidence-card schema version")
        _require_iso_date(self.as_of_date, "as_of_date")
        if self.comparison_date is not None:
            _require_iso_date(self.comparison_date, "comparison_date")
            if self.comparison_date >= self.as_of_date:
                raise ValueError("comparison_date must be strictly before as_of_date")
        if self.overall_risk_state not in RISK_STATES:
            raise ValueError(f"unsupported risk state: {self.overall_risk_state}")
        if self.evidence_quality not in EVIDENCE_QUALITIES:
            raise ValueError(f"unsupported evidence quality: {self.evidence_quality}")
        if self.synthesis_mode not in SYNTHESIS_MODES:
            raise ValueError(f"unsupported synthesis mode: {self.synthesis_mode}")
        for value, field in (
            (self.deterministic_score, "deterministic_score"),
            (self.tail_loss_frequency, "tail_loss_frequency"),
        ):
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"{field} must be finite or null")
        if self.tail_loss_frequency is not None and not 0.0 <= self.tail_loss_frequency <= 1.0:
            raise ValueError("tail_loss_frequency must be a probability in [0, 1]")
        for signal in self.triggered_quant_signals:
            if signal.status != "triggered":
                raise ValueError("triggered_quant_signals must all be triggered")
        for signal in self.non_triggered_relevant_signals:
            if signal.status == "triggered":
                raise ValueError("non_triggered_relevant_signals cannot be triggered")
        if not self.narrative_state or not self.pm_interpretation:
            raise ValueError("narrative_state and pm_interpretation are required")
        if not all(
            (
                self.run_id,
                self.data_cutoff,
                self.threshold_profile,
                self.data_version,
                self.quant_model_version,
            )
        ):
            raise ValueError(
                "run_id, cutoff, threshold profile, data version, and model "
                "version are required"
            )
        cutoff = _require_iso_datetime(self.data_cutoff, "data_cutoff")
        for item in (
            self.supporting_evidence
            + self.contradicting_evidence
            + self.contextual_evidence
        ):
            publication = _require_iso_datetime(
                item.timestamp, f"evidence {item.evidence_id} timestamp"
            )
            if publication > cutoff:
                raise ValueError(
                    f"evidence {item.evidence_id} is later than data_cutoff"
                )

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _require_iso_date(value: str, name: str) -> None:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{name} must be YYYY-MM-DD")


def _require_iso_datetime(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone offset")
    return parsed


def _normalise_input_date(value: Any, name: str) -> pd.Timestamp:
    """Normalize a date-like input while preserving its stated calendar date."""

    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a valid date") from exc
    if pd.isna(parsed):
        raise ValueError(f"{name} must be a valid date")
    if parsed.tzinfo is not None:
        parsed = parsed.tz_localize(None)
    return parsed.normalize()


def _data_version(processed_dir: Path) -> str:
    payload = {
        name: sha256_file(processed_dir / name)
        for name in DATA_VERSION_FILES
    }
    seed = json.dumps(payload, sort_keys=True)
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _quant_model_version(config: ScorecardConfig) -> str:
    seed = json.dumps(dataclasses.asdict(config), sort_keys=True, allow_nan=False)
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"{QUANT_MODEL_FAMILY}:{digest}"


# ---------------------------------------------------------------------------
# Deterministic assembly helpers
# ---------------------------------------------------------------------------


def _scorecard_values(table: pd.DataFrame) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for _, row in table.iterrows():
        available = str(row["status"]) == "available"
        values[str(row["metric"])] = (
            _clean_float(row["current_value"]) if available else None
        )
    return values


def _signal_from_row(
    row: pd.Series,
    *,
    change: float | None,
) -> QuantSignal:
    available = str(row["status"]) == "available"
    triggered = (
        bool(row["triggered"])
        if available and not pd.isna(row["triggered"])
        else None
    )
    if not available:
        status = "unavailable"
    elif triggered:
        status = "triggered"
    else:
        status = "not_triggered"
    return QuantSignal(
        name=str(row["metric"]),
        current_value=_clean_float(row["current_value"]) if available else None,
        threshold=_clean_float(row["threshold"]),
        status=status,
        direction=str(row["direction"]),
        change_vs_comparison=change,
        interpretation=str(row["explanation"]),
        source_component=str(row["source_module"]),
    )


def _evidence_items(
    raw_items: list[dict[str, Any]],
    stance: str,
) -> tuple[RetrievedEvidence, ...]:
    items: list[RetrievedEvidence] = []
    for raw in raw_items:
        reason = raw.get("classification_rationale") or raw.get("mechanism") or ""
        locator = raw.get("citation_url") or ""
        items.append(
            RetrievedEvidence(
                evidence_id=str(raw["document_id"]),
                timestamp=str(raw["publication_timestamp"]),
                source=str(raw["source"]),
                headline_or_summary=str(raw["title"]),
                relevance_reason=str(reason) or None,
                stance=stance,
                citation_or_locator=str(locator) or None,
            )
        )
    return tuple(items)


def _historical_analogs(
    *,
    as_of_date: pd.Timestamp,
    horizon: int,
    processed_dir: Path,
) -> tuple[dict[str, Any], ...]:
    table = build_insurance_table(as_of_date=as_of_date, processed_dir=processed_dir)
    selected = table.loc[table["horizon_days"].eq(horizon)]
    analogs: list[dict[str, Any]] = []
    for _, row in selected.iterrows():
        analogs.append(
            {
                "state": str(row["state"]),
                "horizon_days": int(row["horizon_days"]),
                "sample_size": int(row["sample_size"]),
                "tail_loss_frequency": _clean_float(row["tail_loss_frequency"]),
                "mean_forward_return": _clean_float(row["mean_forward_return"]),
                "fifth_percentile_forward_return": _clean_float(
                    row["fifth_percentile_forward_return"]
                ),
                "latest_label_available_date": str(row["latest_label_available_date"]),
                "note": (
                    "Descriptive state-conditional tail-loss frequency, not a "
                    "forecast that history will repeat."
                ),
            }
        )
    return tuple(analogs)


def _run_id(
    *,
    as_of_date: pd.Timestamp,
    comparison_date: pd.Timestamp | None,
    threshold_profile: str,
    horizon: int,
    state: str,
    signals: tuple[QuantSignal, ...],
    data_version: str,
    quant_model_version: str,
) -> str:
    seed = {
        "as_of_date": iso_date(as_of_date),
        "comparison_date": None if comparison_date is None else iso_date(comparison_date),
        "threshold_profile": threshold_profile,
        "horizon": horizon,
        "overall_risk_state": state,
        "signals": {signal.name: signal.current_value for signal in signals},
        "data_version": data_version,
        "quant_model_version": quant_model_version,
    }
    payload = json.dumps(seed, sort_keys=True, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Public integration entry point
# ---------------------------------------------------------------------------


def build_evidence_card(
    *,
    as_of_date: pd.Timestamp,
    threshold_profile: str = "default",
    compare_to_date: pd.Timestamp | None = None,
    use_llm: bool = True,
    horizon: int = 20,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    synthesizer: Synthesizer | None = None,
    evidence_builder: Callable[..., dict[str, Any]] | None = None,
) -> EvidenceCard:
    """Assemble the deterministic-first Evidence Card for one selected date.

    Quantitative fields are identical regardless of ``use_llm``; the language
    model, when supplied, only phrases narrative text.
    """

    config = resolve_threshold_profile(threshold_profile)
    as_of_date = _normalise_input_date(as_of_date, "as_of_date")
    warnings: list[str] = []

    features = pd.read_parquet(processed_dir / FEATURES_FILE, columns=["date"])
    max_date = pd.to_datetime(features["date"]).max().normalize()
    if as_of_date > pd.Timestamp(date.today()):
        raise ValueError(
            f"as_of_date {iso_date(as_of_date)} is in the future; future dates "
            "are rejected"
        )
    if as_of_date > max_date:
        raise ValueError(
            f"as_of_date {iso_date(as_of_date)} is beyond available data "
            f"({iso_date(max_date)}); future dates are rejected"
        )

    comparison_date: pd.Timestamp | None = None
    if compare_to_date is not None:
        comparison_date = _normalise_input_date(compare_to_date, "compare_to_date")
        if comparison_date >= as_of_date:
            raise ValueError("compare_to_date must be strictly before as_of_date")

    factors = pd.read_parquet(processed_dir / FACTORS_FILE)
    risk = pd.read_parquet(processed_dir / RISK_FILE)
    regime = build_regime_history(factors)

    primary = build_primary_assessment(
        as_of_date=as_of_date,
        horizon=horizon,
        processed_dir=processed_dir,
    )
    scorecard = build_scorecard(risk, regime, as_of_date=as_of_date, config=config)

    comparison_values: dict[str, float | None] = {}
    if comparison_date is not None:
        try:
            comparison_table = build_scorecard(
                risk, regime, as_of_date=comparison_date, config=config
            )
            comparison_values = _scorecard_values(comparison_table)
        except (ValueError, KeyError) as exc:
            warnings.append(
                f"comparison date {iso_date(comparison_date)} could not be "
                f"computed ({exc}); change analysis was skipped"
            )
            comparison_date = None

    current_values = _scorecard_values(scorecard)
    signals: list[QuantSignal] = []
    signal_changes: list[dict[str, Any]] = []
    for _, row in scorecard.iterrows():
        metric = str(row["metric"])
        change: float | None = None
        current = current_values.get(metric)
        prior = comparison_values.get(metric)
        if comparison_date is not None and current is not None and prior is not None:
            change = current - prior
            signal_changes.append(
                {
                    "name": metric,
                    "from_text": _fmt(prior),
                    "to_text": _fmt(current),
                    "delta_text": _fmt(change, signed=True),
                    "abs_delta": abs(change),
                }
            )
        signals.append(_signal_from_row(row, change=change))
    signal_changes.sort(key=lambda item: item["abs_delta"], reverse=True)

    triggered_signals = tuple(s for s in signals if s.status == "triggered")
    non_triggered_signals = tuple(s for s in signals if s.status != "triggered")
    if any(s.status == "unavailable" for s in signals):
        unavailable = [s.name for s in signals if s.status == "unavailable"]
        warnings.append(
            "unavailable scorecard signals were reported without a trigger: "
            + ", ".join(unavailable)
        )

    facts_seed = {
        "as_of_date": iso_date(as_of_date),
        "overall_risk_state": primary.state,
        "threshold_profile": threshold_profile,
        "triggered_metrics": sorted(s.name for s in triggered_signals),
    }
    builder = evidence_builder or build_research_preview
    try:
        evidence = builder(
            deterministic_summary=facts_seed,
            evidence_case_date=as_of_date,
            classification_dir=output_dir / "evidence_cache",
        )
    except Exception as exc:  # noqa: BLE001 - retrieval must fail closed
        evidence = {
            "status": "unavailable",
            "uncertainty": f"Point-in-time evidence retrieval failed: {exc}.",
            "limitations": [],
        }
        warnings.append(
            "evidence retrieval failed closed; deterministic quantitative facts "
            f"remain available ({exc})"
        )
    supporting: tuple[RetrievedEvidence, ...] = ()
    contradicting: tuple[RetrievedEvidence, ...] = ()
    contextual: tuple[RetrievedEvidence, ...] = ()
    missing: list[str] = []
    if str(evidence.get("status")) == "unavailable":
        evidence_quality = "unavailable"
        missing.append(
            str(evidence.get("uncertainty", "Point-in-time evidence is unavailable."))
        )
        missing.extend(str(item) for item in evidence.get("limitations", []))
        warnings.append(
            f"no date-matched evidence for {iso_date(as_of_date)}; the card "
            "shows deterministic quantitative facts only"
        )
    else:
        evidence_quality = "available"
        try:
            supporting = _evidence_items(
                evidence.get("supporting", []), "supporting"
            )
            contradicting = _evidence_items(
                evidence.get("contradicting", []), "contradicting"
            )
            contextual = _evidence_items(
                evidence.get("contextual", []), "contextual"
            )
            cutoff = _require_iso_datetime(primary.as_of_timestamp, "data_cutoff")
            for item in supporting + contradicting + contextual:
                if (
                    _require_iso_datetime(item.timestamp, "evidence timestamp")
                    > cutoff
                ):
                    raise ValueError(
                        f"evidence {item.evidence_id} is later than the data cutoff"
                    )
        except (KeyError, TypeError, ValueError) as exc:
            evidence_quality = "unavailable"
            supporting = ()
            contradicting = ()
            contextual = ()
            missing.append(f"Point-in-time evidence was rejected: {exc}.")
            warnings.append(
                "evidence failed cutoff/schema validation and was excluded"
            )
        if not contradicting:
            missing.append(
                "No contradicting point-in-time evidence was retrieved at this "
                "cutoff; absence of contradiction is not confirmation."
            )
        missing.extend(str(item) for item in evidence.get("limitations", []))

    historical_analogs = _historical_analogs(
        as_of_date=as_of_date,
        horizon=horizon,
        processed_dir=processed_dir,
    )

    context = {
        "as_of_date": iso_date(as_of_date),
        "comparison_date": None if comparison_date is None else iso_date(comparison_date),
        "overall_risk_state": primary.state,
        "triggered_signal_names": [s.name for s in triggered_signals],
        "total_signals": len(signals),
        "available_signals": sum(1 for s in signals if s.status != "unavailable"),
        "evidence_quality": evidence_quality,
        "signal_changes": signal_changes,
        "tail_loss_frequency": _clean_float(primary.tail_loss_probability),
    }

    if use_llm and synthesizer is not None:
        try:
            result = synthesizer.synthesize(context=context)
            if not isinstance(result, SynthesisResult):
                raise TypeError("synthesizer did not return a SynthesisResult")
            synthesis_mode = "external_synthesizer"
        except Exception as exc:  # noqa: BLE001 - any failure falls back safely
            result = DeterministicSynthesizer().synthesize(context=context)
            synthesis_mode = "deterministic_fallback"
            warnings.append(
                f"narrative synthesis failed and fell back to deterministic "
                f"text: {exc}"
            )
    elif use_llm:
        result = DeterministicSynthesizer().synthesize(context=context)
        synthesis_mode = "deterministic_fallback"
        warnings.append(
            "LLM synthesis was requested, but no external synthesizer or API "
            "configuration is installed; deterministic text was used"
        )
    else:
        result = DeterministicSynthesizer().synthesize(context=context)
        synthesis_mode = "deterministic_no_llm"

    data_version = _data_version(processed_dir)
    quant_model_version = _quant_model_version(config)
    run_id = _run_id(
        as_of_date=as_of_date,
        comparison_date=comparison_date,
        threshold_profile=threshold_profile,
        horizon=horizon,
        state=primary.state,
        signals=tuple(signals),
        data_version=data_version,
        quant_model_version=quant_model_version,
    )

    return EvidenceCard(
        schema_version=SCHEMA_VERSION,
        as_of_date=iso_date(as_of_date),
        comparison_date=None if comparison_date is None else iso_date(comparison_date),
        overall_risk_state=primary.state,
        deterministic_score=None,
        tail_loss_frequency=_clean_float(primary.tail_loss_probability),
        tail_loss_horizon_days=horizon,
        evidence_quality=evidence_quality,
        triggered_quant_signals=triggered_signals,
        non_triggered_relevant_signals=non_triggered_signals,
        narrative_state=result.narrative_state,
        what_changed=result.what_changed,
        supporting_evidence=supporting,
        contradicting_evidence=contradicting,
        contextual_evidence=contextual,
        missing_or_uncertain_evidence=tuple(missing),
        historical_analogs=historical_analogs,
        pm_interpretation=result.pm_interpretation,
        monitoring_questions=result.monitoring_questions,
        invalidation_conditions=result.invalidation_conditions,
        threshold_profile=threshold_profile,
        data_version=data_version,
        quant_model_version=quant_model_version,
        data_cutoff=primary.as_of_timestamp,
        run_id=run_id,
        llm_enabled=bool(use_llm),
        synthesis_mode=synthesis_mode,
        model_or_prompt_version=result.model_or_prompt_version,
        warnings=tuple(warnings),
    )


def build_deterministic_evidence_input(
    *,
    as_of_date: pd.Timestamp,
    threshold_profile: str = "default",
    compare_to_date: pd.Timestamp | None = None,
    horizon: int = 20,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    evidence_builder: Callable[..., dict[str, Any]] | None = None,
) -> DeterministicEvidenceInput:
    """Return the validated deterministic and PIT-evidence card input.

    The existing Evidence Card builder remains the single integration path for
    Phase 1--4 calculations and point-in-time evidence. Setting ``use_llm`` to
    false guarantees that no external synthesizer is invoked. This adapter
    removes all narrative fields and makes unavailable upstream components
    explicit in ``data_warnings``.
    """

    card = build_evidence_card(
        as_of_date=as_of_date,
        threshold_profile=threshold_profile,
        compare_to_date=compare_to_date,
        use_llm=False,
        horizon=horizon,
        processed_dir=processed_dir,
        output_dir=output_dir,
        evidence_builder=evidence_builder,
    )
    if card.synthesis_mode != "deterministic_no_llm":
        raise AssertionError("deterministic adapter unexpectedly enabled LLM synthesis")

    retrieved_evidence = (
        card.supporting_evidence
        + card.contradicting_evidence
        + card.contextual_evidence
    )
    warnings = [
        *card.missing_or_uncertain_evidence,
        *card.warnings,
        (
            "No composite deterministic score is defined; the adapter preserves "
            "the four indicator states and leaves deterministic_score null."
        ),
        (
            "The legacy Phase 6 adapter contract contains Phase 5A feasibility "
            "metadata only and does not embed the separate Phase 5 unwind "
            "scorecard; the notebook renders that deterministic assessment "
            "alongside this card. Its fundamental row remains unavailable "
            "unless exact-date company coverage is supplied."
        ),
    ]
    unique_warnings: list[str] = []
    for warning in warnings:
        if warning not in unique_warnings:
            unique_warnings.append(warning)

    audit_metadata = {
        "adapter_version": DETERMINISTIC_INPUT_SCHEMA_VERSION,
        "source_card_schema_version": card.schema_version,
        "source_entry_point": "src.mvp.evidence_card.build_evidence_card",
        "tail_loss_frequency": card.tail_loss_frequency,
        "tail_loss_horizon_days": card.tail_loss_horizon_days,
        "evidence_quality": card.evidence_quality,
        "data_version": card.data_version,
        "quant_model_version": card.quant_model_version,
        "quantitative_signal_count": len(
            card.triggered_quant_signals
            + card.non_triggered_relevant_signals
        ),
        "retrieved_evidence_count": len(retrieved_evidence),
        "phase_5_alignment_status": "unavailable_unapproved",
        "llm_invoked": False,
    }
    return DeterministicEvidenceInput(
        schema_version=DETERMINISTIC_INPUT_SCHEMA_VERSION,
        as_of_date=card.as_of_date,
        comparison_date=card.comparison_date,
        overall_risk_state=card.overall_risk_state,
        deterministic_score=card.deterministic_score,
        triggered_quant_signals=card.triggered_quant_signals,
        non_triggered_relevant_signals=card.non_triggered_relevant_signals,
        retrieved_evidence=retrieved_evidence,
        historical_analogs=card.historical_analogs,
        data_warnings=tuple(unique_warnings),
        threshold_profile=card.threshold_profile,
        data_cutoff=card.data_cutoff,
        run_id=card.run_id,
        audit_metadata=audit_metadata,
    )


def save_evidence_card(
    card: EvidenceCard,
    *,
    output_dir: Path = DEFAULT_EVIDENCE_CARD_DIR,
) -> Path:
    """Persist the card as deterministic JSON and return the written path."""

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"evidence_card_{card.as_of_date}.json"
    write_json(path, card.to_dict())
    return path


# ---------------------------------------------------------------------------
# Rendering (Task 7): minimal, dependency-free HTML for the notebook
# ---------------------------------------------------------------------------


def _escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _signal_rows_html(signals: tuple[QuantSignal, ...]) -> str:
    if not signals:
        return "<tr><td colspan='5'><em>No signals.</em></td></tr>"
    rows: list[str] = []
    for signal in signals:
        operator = "&ge;" if signal.direction == "greater_than_or_equal" else "&le;"
        display_name = signal.name.replace("_", " ").title()
        rows.append(
            "<tr>"
            f"<td>{_escape(display_name)}</td>"
            f"<td style='text-align:right'>{_fmt(signal.current_value)}</td>"
            f"<td style='text-align:right'>{operator} {_fmt(signal.threshold)}</td>"
            f"<td>{_escape(signal.status)}</td>"
            f"<td style='text-align:right'>{_fmt(signal.change_vs_comparison, signed=True)}</td>"
            "</tr>"
        )
    return "".join(rows)


def render_signal_table_html(card: EvidenceCard) -> str:
    """Render the deterministic quantitative signal table."""

    header = (
        "<tr><th>Indicator</th><th>Current</th><th>Trigger rule</th><th>Status</th>"
        "<th>&Delta; vs compare</th></tr>"
    )
    body = _signal_rows_html(
        card.triggered_quant_signals + card.non_triggered_relevant_signals
    )
    return (
        "<table style='border-collapse:collapse;width:100%;font-size:13px'>"
        f"{header}{body}</table>"
    )


def _evidence_list_html(items: tuple[RetrievedEvidence, ...]) -> str:
    if not items:
        return "<p><em>None retrieved at this cutoff.</em></p>"
    parts: list[str] = ["<ul>"]
    for item in items:
        locator = (
            f" &mdash; <code>{_escape(item.citation_or_locator)}</code>"
            if item.citation_or_locator
            else ""
        )
        parts.append(
            "<li>"
            f"<strong>{_escape(item.headline_or_summary)}</strong><br>"
            f"<small>{_escape(item.source)} &middot; {_escape(item.timestamp)}{locator}</small>"
            "</li>"
        )
    parts.append("</ul>")
    return "".join(parts)


def _list_html(items: tuple[str, ...]) -> str:
    if not items:
        return "<p><em>None.</em></p>"
    return "<ul>" + "".join(f"<li>{_escape(item)}</li>" for item in items) + "</ul>"


def render_evidence_card_html(card: EvidenceCard) -> str:
    """Render a readable, self-contained PM Evidence Card as HTML."""

    triggered = ", ".join(s.name for s in card.triggered_quant_signals) or "none"
    tail = (
        "unavailable"
        if card.tail_loss_frequency is None
        else f"{card.tail_loss_frequency:.2%}"
    )
    sections = [
        "<div style='border:1px solid #8884;border-radius:8px;padding:16px;"
        "max-width:900px;font-family:system-ui,-apple-system,sans-serif'>",
        f"<h2 style='margin:0 0 4px'>PM Evidence Card &mdash; {_escape(card.as_of_date)}</h2>",
        (
            "<p style='margin:0 0 12px;font-size:12px;opacity:0.75'>"
            f"state <strong>{_escape(card.overall_risk_state)}</strong>"
            f" &middot; triggered: {_escape(triggered)}"
            f" &middot; {card.tail_loss_horizon_days}-day conditional tail-loss frequency (descriptive): {tail}"
            f" &middot; profile {_escape(card.threshold_profile)}"
            f" &middot; LLM requested: {'yes' if card.llm_enabled else 'no'}"
            f"; result: {_escape(card.synthesis_mode)}"
            f" &middot; run {_escape(card.run_id)}"
            "</p>"
        ),
        f"<p>{_escape(card.narrative_state)}</p>",
        "<h3>Quantitative signals</h3>",
        render_signal_table_html(card),
        "<h3>What changed"
        + (f" vs {_escape(card.comparison_date)}" if card.comparison_date else "")
        + "</h3>",
        _list_html(card.what_changed),
        "<h3>Supporting evidence</h3>",
        _evidence_list_html(card.supporting_evidence),
        "<h3>Contradicting or moderating evidence</h3>",
        _evidence_list_html(card.contradicting_evidence),
        "<h3>Contextual evidence</h3>",
        _evidence_list_html(card.contextual_evidence),
        "<h3>Missing or uncertain evidence</h3>",
        _list_html(card.missing_or_uncertain_evidence),
        "<h3>PM interpretation</h3>",
        f"<p>{_escape(card.pm_interpretation)}</p>",
        "<h3>Monitoring questions</h3>",
        _list_html(card.monitoring_questions),
        "<h3>What would invalidate this warning</h3>",
        _list_html(card.invalidation_conditions),
    ]
    if card.warnings:
        sections.append("<h3>Run warnings</h3>")
        sections.append(_list_html(card.warnings))
    sections.append("</div>")
    return "".join(sections)


# ---------------------------------------------------------------------------
# CLI (parity with the other MVP entry points; offline and read-only)
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the offline PM Evidence Card for one selected date."
    )
    parser.add_argument("--as-of-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--compare-to-date", metavar="YYYY-MM-DD", default=None)
    parser.add_argument("--threshold-profile", default="default")
    parser.add_argument("--horizon", type=int, choices=(5, 20), default=20)
    parser.add_argument("--no-llm", action="store_true")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    card = build_evidence_card(
        as_of_date=parse_as_of_date(args.as_of_date),
        threshold_profile=args.threshold_profile,
        compare_to_date=(
            parse_as_of_date(args.compare_to_date) if args.compare_to_date else None
        ),
        use_llm=not args.no_llm,
        horizon=args.horizon,
    )
    path = save_evidence_card(card)
    print(
        json.dumps(
            {
                "status": "complete",
                "as_of_date": card.as_of_date,
                "overall_risk_state": card.overall_risk_state,
                "run_id": card.run_id,
                "output": str(path.relative_to(REPO_ROOT)),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
