"""Optional DeepSeek synthesis over retrieved GDELT evidence.

The LLM explains an already-triggered momentum-risk state. It must not
recompute scores, assert causality, or issue trading recommendations.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from src.utils.io import DEFAULT_OUTPUT_DIR, REPO_ROOT, read_json, write_json

DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_CACHE_DIR = DEFAULT_OUTPUT_DIR / "gdelt_evidence_cache"
LLM_UNAVAILABLE_MESSAGE = (
    "LLM synthesis was unavailable. Retrieved GDELT evidence is shown without "
    "model narrative synthesis."
)

_REQUIRED_RESULT_KEYS = (
    "trigger_summary",
    "recent_narrative",
    "momentum_mechanism",
    "key_evidence_ids",
    "limitations",
    "pm_takeaway",
)


def _as_iso_date(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    return date.fromisoformat(text[:10]).isoformat()


def _load_dotenv_if_present(env_path: Path | None = None) -> None:
    """Load simple KEY=VALUE pairs from a local ``.env`` without new deps."""

    path = env_path if env_path is not None else REPO_ROOT / ".env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def _cache_key(
    *,
    as_of_date: str,
    active_triggers: Sequence[Mapping[str, Any]],
    evidence: pd.DataFrame,
    model: str,
) -> str:
    payload = {
        "as_of_date": as_of_date,
        "active_triggers": list(active_triggers),
        "evidence": evidence.to_dict(orient="records") if evidence is not None else [],
        "model": model,
        "prompt_version": "gdelt-deepseek-explainer-v1",
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return digest[:24]


def _evidence_payload(evidence: pd.DataFrame) -> list[dict[str, Any]]:
    if evidence is None or evidence.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, row in evidence.iterrows():
        rows.append(
            {
                "evidence_id": str(row.get("evidence_id") or ""),
                "date": str(row.get("date") or ""),
                "title": str(row.get("title") or ""),
                "source": str(row.get("source") or ""),
                "url": str(row.get("url") or ""),
                "matched_trigger": str(row.get("matched_trigger") or ""),
                "matched_keywords": str(row.get("matched_keywords") or ""),
            }
        )
    return rows


def _build_messages(
    *,
    as_of_date: str,
    active_triggers: Sequence[Mapping[str, Any]],
    evidence_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    system = (
        "You are assisting a portfolio manager with a momentum tail-risk "
        "monitor. The deterministic system has already identified the risk "
        "state. Explain that state using only the supplied GDELT records. "
        "Do not recalculate any risk score. Do not claim causality. Do not "
        "give trading recommendations. Cite evidence with simple IDs such as "
        "[E1] or [E2]. If evidence is weak or insufficient, say so clearly. "
        "Keep the total narrative around 200-350 words. Respond with a single "
        "JSON object using exactly these keys: trigger_summary, "
        "recent_narrative, momentum_mechanism, key_evidence_ids, limitations, "
        "pm_takeaway. key_evidence_ids must be an array of evidence ID strings."
    )
    user = {
        "as_of_date": as_of_date,
        "active_triggers": list(active_triggers),
        "gdelt_evidence": list(evidence_rows),
        "instructions": (
            "Write a concise PM-facing explanation of the already fully or "
            "partially triggered momentum-risk state using only these "
            "contemporaneous public-news records. Treat status=partial as "
            "near-threshold monitoring context, not a confirmed alert."
        ),
    }
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(user, ensure_ascii=True, sort_keys=True),
        },
    ]


def _validate_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    missing = [key for key in _REQUIRED_RESULT_KEYS if key not in payload]
    if missing:
        raise ValueError(f"DeepSeek response missing keys: {missing}")
    evidence_ids = payload["key_evidence_ids"]
    if not isinstance(evidence_ids, list):
        raise ValueError("key_evidence_ids must be a list")
    return {
        "trigger_summary": str(payload["trigger_summary"]).strip(),
        "recent_narrative": str(payload["recent_narrative"]).strip(),
        "momentum_mechanism": str(payload["momentum_mechanism"]).strip(),
        "key_evidence_ids": [str(item).strip() for item in evidence_ids],
        "limitations": str(payload["limitations"]).strip(),
        "pm_takeaway": str(payload["pm_takeaway"]).strip(),
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    content = text.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(content[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("DeepSeek response is not a JSON object")
    return parsed


def _post_chat_completion(
    *,
    api_key: str,
    model: str,
    messages: Sequence[Mapping[str, str]],
    base_url: str,
    timeout_seconds: float = 45.0,
) -> str:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": list(messages),
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("DeepSeek response contained no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        raise ValueError("DeepSeek response contained empty content")
    return str(content)


def explain_risk_with_deepseek(
    active_triggers: list[dict[str, Any]],
    evidence: pd.DataFrame,
    as_of_date: date | datetime | str,
    *,
    cache_dir: Path | None = None,
    environment: Mapping[str, str] | None = None,
    load_dotenv: bool = True,
    transport: Any | None = None,
) -> dict[str, Any]:
    """Synthesize a concise PM explanation from triggers and GDELT evidence.

    Args:
        active_triggers: Already-triggered scorecard rows.
        evidence: Ranked GDELT evidence table with ``evidence_id`` values.
        as_of_date: Assessment date.
        cache_dir: Optional JSON cache directory for successful responses.
        environment: Optional env mapping; defaults to ``os.environ``.
        load_dotenv: When True, load repository ``.env`` keys if absent.
        transport: Optional callable ``(api_key, model, messages, base_url)``
            used by tests to mock the HTTP client.

    Returns:
        Structured result with explanation fields plus ``status`` /
        ``message`` metadata describing success or fallback.
    """

    if load_dotenv:
        _load_dotenv_if_present()
    env = dict(os.environ if environment is None else environment)
    as_of = _as_iso_date(as_of_date)
    evidence_rows = _evidence_payload(evidence)
    base_result = {
        "as_of_date": as_of,
        "trigger_summary": "",
        "recent_narrative": "",
        "momentum_mechanism": "",
        "key_evidence_ids": [],
        "limitations": "",
        "pm_takeaway": "",
        "model": env.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL).strip()
        or DEFAULT_DEEPSEEK_MODEL,
        "cached": False,
    }

    if not active_triggers:
        return {
            **base_result,
            "status": "inactive",
            "message": (
                "Evidence layer not activated because no configured "
                "momentum-risk trigger is fully or partially active."
            ),
        }
    if not evidence_rows:
        return {
            **base_result,
            "status": "no_evidence",
            "message": (
                "No sufficiently relevant GDELT evidence was found for the "
                "selected date and window."
            ),
        }

    api_key = str(env.get("DEEPSEEK_API_KEY") or "").strip()
    model = base_result["model"]
    cache_root = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
    key = _cache_key(
        as_of_date=as_of,
        active_triggers=active_triggers,
        evidence=evidence,
        model=model,
    )
    cache_path = cache_root / f"{as_of}_{key}.json"
    if cache_path.exists():
        try:
            cached = read_json(cache_path)
            validated = _validate_result(cached)
            return {
                **base_result,
                **validated,
                "status": "ok",
                "message": "Loaded cached DeepSeek explanation.",
                "cached": True,
            }
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

    if not api_key:
        return {
            **base_result,
            "status": "llm_unavailable",
            "message": LLM_UNAVAILABLE_MESSAGE,
        }

    messages = _build_messages(
        as_of_date=as_of,
        active_triggers=active_triggers,
        evidence_rows=evidence_rows,
    )
    base_url = (
        str(env.get("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL).strip()
        or DEFAULT_DEEPSEEK_BASE_URL
    )
    try:
        if transport is not None:
            content = transport(
                api_key=api_key,
                model=model,
                messages=messages,
                base_url=base_url,
            )
        else:
            content = _post_chat_completion(
                api_key=api_key,
                model=model,
                messages=messages,
                base_url=base_url,
            )
        validated = _validate_result(_extract_json_object(content))
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
        KeyError,
        OSError,
    ) as exc:
        return {
            **base_result,
            "status": "llm_unavailable",
            "message": f"{LLM_UNAVAILABLE_MESSAGE} ({exc.__class__.__name__})",
        }

    write_json(
        cache_path,
        {
            **validated,
            "as_of_date": as_of,
            "model": model,
        },
    )
    return {
        **base_result,
        **validated,
        "status": "ok",
        "message": "DeepSeek explanation generated.",
        "cached": False,
    }
