"""Lightweight point-in-time GDELT title retrieval for optional PM explanation.

This module never participates in risk detection or scoring. It only filters
existing cached GDELT article-list records against already-active scorecard
triggers.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from src.utils.io import DEFAULT_RAW_DIR, REPO_ROOT

DEFAULT_GDELT_TITLES_DIR = DEFAULT_RAW_DIR / "gdelt_phase2"

# Retrieval defaults for the optional evidence layer.
DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_MAX_RECORDS = 30
MAX_RECORDS_RANGE = (20, 50)
DEFAULT_PARTIAL_RATIO = 0.70
# Configurable GDELT theme buckets (frozen phase-2 query labels).
DEFAULT_GDELT_THEMES: tuple[str, ...] = (
    "panic",
    "rotation",
    "policy",
    "crowding",
    "riskoff",
)

# Keywords are tuned to fields that exist in the cached GDELT artlist payload
# (primarily ``title``). Keys match SCORECARD_METRICS from the scorecard.
# Edit this map (or pass ``trigger_keywords=...``) to reconfigure theme terms.
TRIGGER_KEYWORDS: dict[str, list[str]] = {
    "high_volatility_recovery": [
        "recovery",
        "volatility",
        "risk-on",
        "rate cut",
        "rate cuts",
        "monetary easing",
        "market rebound",
        "stimulus",
        "risk on",
    ],
    "short_minus_long_beta_gap": [
        "factor rotation",
        "high beta",
        "cyclical rally",
        "market leadership",
        "sector rotation",
        "rotation",
    ],
    "portfolio_drawdown": [
        "market selloff",
        "selloff",
        "drawdown",
        "crash",
        "correction",
        "risk-off",
        "risk off",
        "recession",
        "equity losses",
    ],
    "short_loss_in_recovery": [
        "short squeeze",
        "heavily shorted",
        "short covering",
        "junk rally",
        "distressed stocks",
        "small-cap rally",
        "shorted",
    ],
    # Mechanism-gated triggers (structural state can activate the evidence layer).
    "bear_market_recovery_crash": [
        "market crash",
        "market panic",
        "forced selling",
        "margin call",
        "bear market",
        "recession",
        "selloff",
    ],
    "short_book_reversal_crash": [
        "short squeeze",
        "short covering",
        "heavily shorted",
        "junk rally",
        "small-cap rally",
        "shorted",
    ],
    "crowded_theme_unwind": [
        "crowded trade",
        "forced deleveraging",
        "quant unwind",
        "hedge fund selling",
        "position unwinding",
        "deleveraging",
        "crowded positioning",
    ],
}

#: Title-level exclusions for non-equity/commodity/crypto noise in the
#: lightweight GDELT evidence layer. Applied before keyword matching.
EXCLUDED_TITLE_TERMS = re.compile(
    r"\b(?:crypto|bitcoin|ethereum|blockchain|altcoin|dogecoin|nft|token|"
    r"stablecoin|forex|commodity|gold|oil|crude)\b",
    re.IGNORECASE,
)

# Soft prior: which frozen GDELT query bucket is most related to each trigger.
QUERY_TRIGGER_AFFINITY: dict[str, frozenset[str]] = {
    "panic": frozenset(
        {"high_volatility_recovery", "portfolio_drawdown", "bear_market_recovery_crash"}
    ),
    "rotation": frozenset({"short_minus_long_beta_gap"}),
    "policy": frozenset({"high_volatility_recovery", "bear_market_recovery_crash"}),
    "crowding": frozenset(
        {"short_loss_in_recovery", "short_book_reversal_crash", "crowded_theme_unwind"}
    ),
    "riskoff": frozenset({"portfolio_drawdown", "high_volatility_recovery"}),
}

_EVIDENCE_COLUMNS = (
    "evidence_id",
    "date",
    "timestamp",
    "title",
    "source",
    "url",
    "gdelt_query",
    "matched_trigger",
    "matched_keywords",
    "match_count",
    "recency_days",
    "rank_score",
)

_TITLE_FILE_PATTERN = re.compile(r"^q_(?P<query>[a-z]+)_titles\.json$")


def _as_date(value: date | datetime | str) -> date:
    """Normalize supported date-like inputs to a calendar date."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    return date.fromisoformat(text[:10])


def _parse_seendate(value: str) -> datetime | None:
    """Parse a GDELT ``seendate`` string such as ``20250421T103000Z``."""

    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def load_gdelt_titles(
    titles_dir: Path | None = None,
) -> pd.DataFrame:
    """Load cached GDELT artlist records into a flat DataFrame.

    Args:
        titles_dir: Directory containing ``q_*_titles.json`` files.

    Returns:
        One row per article with provenance fields present in the cache.
    """

    root = Path(titles_dir) if titles_dir is not None else DEFAULT_GDELT_TITLES_DIR
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("q_*_titles.json")):
        match = _TITLE_FILE_PATTERN.match(path.name)
        if match is None:
            continue
        query = match.group("query")
        payload = json.loads(path.read_text(encoding="utf-8"))
        articles = payload.get("articles") or []
        if not isinstance(articles, list):
            continue
        for article in articles:
            if not isinstance(article, Mapping):
                continue
            seen = _parse_seendate(str(article.get("seendate") or ""))
            if seen is None:
                continue
            title = str(article.get("title") or "").strip()
            url = str(article.get("url") or "").strip()
            if not title and not url:
                continue
            rows.append(
                {
                    "timestamp": seen,
                    "date": seen.date(),
                    "title": title,
                    "source": str(article.get("domain") or "").strip(),
                    "url": url,
                    "language": str(article.get("language") or "").strip(),
                    "sourcecountry": str(article.get("sourcecountry") or "").strip(),
                    "gdelt_query": query,
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "date",
                "title",
                "source",
                "url",
                "language",
                "sourcecountry",
                "gdelt_query",
            ]
        )
    frame = pd.DataFrame(rows)
    return frame.sort_values(["timestamp", "url"], kind="mergesort").reset_index(
        drop=True
    )


def _trigger_progress(
    *,
    current_value: float | None,
    threshold: float | None,
    direction: str | None,
) -> float | None:
    """Return proximity to the trigger threshold in ``[0, +inf)``.

    ``1.0`` means at/beyond the deterministic threshold. Values in
    ``[partial_ratio, 1.0)`` are treated as partial activations.
    """

    if current_value is None or threshold is None:
        return None
    try:
        value = float(current_value)
        barrier = float(threshold)
    except (TypeError, ValueError):
        return None
    if not (value == value and barrier == barrier):  # NaN guard
        return None

    normalized_direction = (direction or "greater_than_or_equal").strip()
    if normalized_direction == "less_than_or_equal":
        if barrier == 0.0:
            return 1.0 if value <= barrier else 0.0
        # Drawdown-style barriers are typically negative: -0.14 / -0.20 = 0.70.
        return value / barrier
    if barrier == 0.0:
        return 1.0 if value >= barrier else 0.0
    return value / barrier


def classify_trigger_activation(
    *,
    status: str,
    current_value: float | None,
    threshold: float | None,
    direction: str | None = None,
    include_partial: bool = True,
    partial_ratio: float = DEFAULT_PARTIAL_RATIO,
) -> str | None:
    """Classify a scorecard row as ``triggered``, ``partial``, or inactive.

    Partial activation does not alter deterministic scorecard status; it only
    gates the optional evidence layer.
    """

    if not 0.0 < partial_ratio <= 1.0:
        raise ValueError("partial_ratio must lie in (0, 1]")
    if status == "triggered":
        return "triggered"
    if status == "unavailable" or not include_partial:
        return None
    if status not in {"not_triggered", "partial", "watch"}:
        return None
    if status in {"partial", "watch"}:
        return "partial"
    progress = _trigger_progress(
        current_value=current_value,
        threshold=threshold,
        direction=direction,
    )
    if progress is None:
        return None
    if progress >= 1.0:
        # Directional edge case: treat as triggered for the evidence gate only.
        return "triggered"
    if progress >= partial_ratio:
        return "partial"
    return None


def active_triggers_from_signals(
    signals: Sequence[Any],
    *,
    include_partial: bool = True,
    partial_ratio: float = DEFAULT_PARTIAL_RATIO,
) -> list[dict[str, Any]]:
    """Extract triggered or partial scorecard rows for the evidence layer.

    Args:
        signals: Objects or mappings with ``name``, ``status``,
            ``current_value``, ``threshold``, and optionally ``direction``.
        include_partial: When True, also activate on near-threshold rows.
        partial_ratio: Fraction of the threshold treated as partial (default
            0.70).

    Returns:
        Compact trigger dictionaries with ``status`` of ``triggered`` or
        ``partial``. Deterministic scorecard values are never modified.
    """

    active: list[dict[str, Any]] = []
    for signal in signals:
        if isinstance(signal, Mapping):
            name = str(signal.get("name") or signal.get("trigger") or "")
            status = str(signal.get("status") or "")
            current_value = signal.get("current_value", signal.get("observed_value"))
            threshold = signal.get("threshold")
            direction = signal.get("direction")
        else:
            name = str(getattr(signal, "name", "") or "")
            status = str(getattr(signal, "status", "") or "")
            current_value = getattr(signal, "current_value", None)
            threshold = getattr(signal, "threshold", None)
            direction = getattr(signal, "direction", None)
        if not name:
            continue
        activation = classify_trigger_activation(
            status=status,
            current_value=current_value if current_value is None else float(current_value),
            threshold=threshold if threshold is None else float(threshold),
            direction=None if direction is None else str(direction),
            include_partial=include_partial,
            partial_ratio=partial_ratio,
        )
        if activation is None:
            continue
        progress = _trigger_progress(
            current_value=current_value if current_value is None else float(current_value),
            threshold=threshold if threshold is None else float(threshold),
            direction=None if direction is None else str(direction),
        )
        active.append(
            {
                "trigger": name,
                "observed_value": current_value,
                "threshold": threshold,
                "status": activation,
                "direction": None if direction is None else str(direction),
                "progress_to_threshold": progress,
            }
        )
    return active


def active_triggers_from_mechanisms(
    mechanisms: Sequence[Any],
) -> list[dict[str, Any]]:
    """Extract evidence-layer triggers from structural mechanism statuses.

    ``triggered`` maps to a full activation and ``watch`` maps to a partial
    activation, so the GDELT layer can be gated by the structural unwind state
    as well as by the quantitative scorecard. Deterministic mechanism states
    are never modified.
    """

    active: list[dict[str, Any]] = []
    for item in mechanisms:
        if isinstance(item, Mapping):
            name = str(item.get("scenario") or item.get("name") or "").strip()
            status = str(item.get("status") or "").strip()
        else:
            name = str(getattr(item, "scenario", "") or "").strip()
            status = str(getattr(item, "status", "") or "").strip()
        if not name:
            continue
        if status == "triggered":
            activation = "triggered"
        elif status == "watch":
            activation = "partial"
        else:
            continue
        active.append(
            {
                "trigger": name,
                "observed_value": None,
                "threshold": None,
                "status": activation,
                "direction": None,
                "progress_to_threshold": None,
            }
        )
    return active


def active_triggers_from_state(
    signals: Sequence[Any],
    mechanisms: Sequence[Any],
    *,
    include_partial: bool = True,
    partial_ratio: float = DEFAULT_PARTIAL_RATIO,
) -> list[dict[str, Any]]:
    """Combine quantitative-scorecard triggers with structural mechanism gates."""

    combined = active_triggers_from_signals(
        signals,
        include_partial=include_partial,
        partial_ratio=partial_ratio,
    )
    combined.extend(active_triggers_from_mechanisms(mechanisms))
    return combined


def _match_keywords(text: str, keywords: Iterable[str]) -> list[str]:
    lowered = text.lower()
    matched: list[str] = []
    for keyword in keywords:
        needle = keyword.strip().lower()
        if needle and needle in lowered:
            matched.append(keyword)
    return matched


def resolve_max_records(max_records: int | None = None) -> int:
    """Return a record cap inside the supported Top 20–50 band."""

    low, high = MAX_RECORDS_RANGE
    value = DEFAULT_MAX_RECORDS if max_records is None else int(max_records)
    if value < 1:
        raise ValueError("max_records must be at least 1")
    return max(low, min(high, value))


def retrieve_gdelt_evidence(
    gdelt_data: pd.DataFrame,
    as_of_date: date | datetime | str,
    active_triggers: list[str] | list[dict[str, Any]],
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    max_records: int = DEFAULT_MAX_RECORDS,
    trigger_keywords: Mapping[str, Sequence[str]] | None = None,
    themes: Sequence[str] | None = None,
    clamp_max_records: bool = True,
) -> pd.DataFrame:
    """Filter and rank GDELT titles for already-active momentum-risk triggers.

    Args:
        gdelt_data: Article-level GDELT frame from :func:`load_gdelt_titles`.
        as_of_date: Inclusive assessment date (point-in-time cutoff).
        active_triggers: Trigger names or compact trigger dictionaries.
        lookback_days: Exclusive lower bound window length in calendar days.
        max_records: Target Top-N size (default 30; supported band 20–50).
        trigger_keywords: Optional override for the default keyword map.
        themes: Optional GDELT theme/query filter (e.g. ``panic``,
            ``crowding``). ``None`` keeps :data:`DEFAULT_GDELT_THEMES`.
        clamp_max_records: When True, clamp ``max_records`` into 20–50.

    Returns:
        Ranked evidence table with provenance and match metadata. Empty when
        no trigger is active or no in-window matches exist.
    """

    if lookback_days < 1:
        raise ValueError("lookback_days must be at least 1")
    if max_records < 1:
        raise ValueError("max_records must be at least 1")
    selected_max = (
        resolve_max_records(max_records) if clamp_max_records else int(max_records)
    )

    as_of = _as_date(as_of_date)
    start_exclusive = as_of - timedelta(days=lookback_days)
    keywords_map = {
        key: list(values)
        for key, values in (trigger_keywords or TRIGGER_KEYWORDS).items()
    }
    selected_themes = {
        str(theme).strip().lower()
        for theme in (DEFAULT_GDELT_THEMES if themes is None else themes)
        if str(theme).strip()
    }

    trigger_names: list[str] = []
    for item in active_triggers:
        if isinstance(item, Mapping):
            name = str(item.get("trigger") or item.get("name") or "").strip()
        else:
            name = str(item).strip()
        if name and name not in trigger_names:
            trigger_names.append(name)

    empty = pd.DataFrame(columns=list(_EVIDENCE_COLUMNS))
    if not trigger_names or gdelt_data is None or gdelt_data.empty:
        return empty
    if not selected_themes:
        return empty

    working = gdelt_data.copy()
    if "date" not in working.columns:
        if "timestamp" not in working.columns:
            return empty
        working["date"] = pd.to_datetime(working["timestamp"], utc=True).dt.date
    else:
        working["date"] = working["date"].map(_as_date)

    if "gdelt_query" in working.columns:
        working = working[
            working["gdelt_query"].astype(str).str.lower().isin(selected_themes)
        ].copy()

    in_window = working[
        (working["date"] > start_exclusive) & (working["date"] <= as_of)
    ].copy()
    if in_window.empty:
        return empty

    ranked_rows: list[dict[str, Any]] = []
    for _, row in in_window.iterrows():
        title = str(row.get("title") or "")
        if EXCLUDED_TITLE_TERMS.search(title):
            continue
        source = str(row.get("source") or "")
        query = str(row.get("gdelt_query") or "")
        haystack = f"{title} {source} {query}"
        best_trigger = ""
        best_keywords: list[str] = []
        best_count = 0
        for trigger in trigger_names:
            matched = _match_keywords(haystack, keywords_map.get(trigger, ()))
            count = len(matched)
            if query in QUERY_TRIGGER_AFFINITY and trigger in QUERY_TRIGGER_AFFINITY[query]:
                # Soft affinity: keep keyword matches primary; affinity only
                # breaks ties / boosts already-relevant query buckets.
                if count > 0:
                    count += 1
                    if query not in matched:
                        matched = [*matched, f"query:{query}"]
            if count > best_count:
                best_count = count
                best_trigger = trigger
                best_keywords = matched
        if best_count <= 0:
            continue
        event_date = _as_date(row["date"])
        recency_days = (as_of - event_date).days
        rank_score = float(best_count) * 10.0 - float(recency_days)
        ranked_rows.append(
            {
                "date": event_date.isoformat(),
                "timestamp": (
                    row["timestamp"].isoformat()
                    if hasattr(row.get("timestamp"), "isoformat")
                    else str(row.get("timestamp") or "")
                ),
                "title": title,
                "source": source,
                "url": str(row.get("url") or ""),
                "gdelt_query": query,
                "matched_trigger": best_trigger,
                "matched_keywords": ", ".join(best_keywords),
                "match_count": int(best_count),
                "recency_days": int(recency_days),
                "rank_score": rank_score,
            }
        )

    if not ranked_rows:
        return empty

    ranked = pd.DataFrame(ranked_rows)
    ranked = ranked.sort_values(
        ["rank_score", "match_count", "date", "url"],
        ascending=[False, False, False, True],
        kind="mergesort",
    )
    # Deduplicate on non-empty URL first, then normalized title (mirror stories).
    ranked["_url_key"] = ranked["url"].astype(str).str.strip().str.lower()
    ranked["_title_key"] = ranked["title"].astype(str).str.lower().str.strip()
    has_url = ranked["_url_key"].str.len() > 0
    ranked = pd.concat(
        [
            ranked.loc[has_url].drop_duplicates(subset=["_url_key"], keep="first"),
            ranked.loc[~has_url],
        ],
        ignore_index=True,
    )
    ranked = ranked.sort_values(
        ["rank_score", "match_count", "date", "url"],
        ascending=[False, False, False, True],
        kind="mergesort",
    )
    ranked = ranked.drop_duplicates(subset=["_title_key"], keep="first")
    ranked = ranked.drop(columns=["_url_key", "_title_key"]).head(int(selected_max)).copy()
    ranked.insert(
        0,
        "evidence_id",
        [f"E{index}" for index in range(1, len(ranked) + 1)],
    )
    return ranked.reset_index(drop=True)


def no_active_trigger_message() -> str:
    """Return the standard inactive-layer message."""

    return (
        "Evidence layer not activated because no configured momentum-risk "
        "trigger is fully or partially active."
    )


def no_evidence_message() -> str:
    """Return the standard empty-retrieval message."""

    return (
        "No sufficiently relevant GDELT evidence was found for the selected "
        "date and window."
    )


def repo_gdelt_titles_path() -> Path:
    """Return the default on-disk GDELT titles directory."""

    return REPO_ROOT / "data" / "raw" / "gdelt_phase2"
