"""DeepSeek Responses API helper for the narrative-shift POC.

Existing GDELT / Evidence Card / PM interpreters keep using Chat Completions
in ``src.evidence.deepseek_explainer``. This module only wraps
``client.responses.create`` with server-side ``web_search``.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.evidence.deepseek_explainer import DEFAULT_DEEPSEEK_BASE_URL
from src.utils.io import load_dotenv_if_present

DEFAULT_RESPONSES_MODEL = "deepseek-v4-flash"
RESPONSES_ENV_MODEL = "DEEPSEEK_RESPONSES_MODEL"
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = (1.0, 2.0)
_TRANSIENT_STATUS = frozenset({408, 429, 500, 502, 503, 504})
_TRANSIENT_NAMES = frozenset(
    {"RateLimitError", "APITimeoutError", "APIConnectionError", "InternalServerError"}
)


class DeepSeekResponsesError(Exception):
    """Base error for the DeepSeek Responses API helper."""


class MissingAPIKeyError(DeepSeekResponsesError):
    """Raised when ``DEEPSEEK_API_KEY`` is absent."""


class TransientError(DeepSeekResponsesError):
    """Rate-limit, timeout, or other retryable API failure."""


@dataclass(frozen=True)
class DeepSeekResponsesResult:
    output_text: str
    model: str
    status: str
    usage: dict[str, Any]


def resolve_responses_model(
    environment: Mapping[str, str] | None = None,
    model: str | None = None,
) -> str:
    if model is not None and str(model).strip():
        return str(model).strip()
    env = os.environ if environment is None else environment
    return str(env.get(RESPONSES_ENV_MODEL) or "").strip() or DEFAULT_RESPONSES_MODEL


def api_key_is_present(
    environment: Mapping[str, str] | None = None,
    *,
    load_dotenv: bool = True,
) -> bool:
    if load_dotenv:
        load_dotenv_if_present()
    env = os.environ if environment is None else environment
    return bool(str(env.get("DEEPSEEK_API_KEY") or "").strip())


def require_api_key(
    environment: Mapping[str, str] | None = None,
    *,
    load_dotenv: bool = True,
) -> str:
    if load_dotenv:
        load_dotenv_if_present()
    env = os.environ if environment is None else environment
    api_key = str(env.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        raise MissingAPIKeyError(
            "Missing DEEPSEEK_API_KEY. Set it in the environment or a local "
            ".env file before calling the DeepSeek Responses API."
        )
    return api_key


def _responses_create(client: Any) -> Any:
    create = getattr(getattr(client, "responses", None), "create", None)
    if not callable(create):
        raise DeepSeekResponsesError(
            "Installed openai SDK does not expose client.responses.create. "
            "Install the POC extra with `uv sync --group poc`."
        )
    return create


def build_deepseek_responses_client(
    *,
    api_key: str,
    base_url: str = DEFAULT_DEEPSEEK_BASE_URL,
    timeout_seconds: float = 120.0,
) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise DeepSeekResponsesError(
            "The openai package is required for the DeepSeek Responses API. "
            "Install it with `uv sync --group poc`."
        ) from exc
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds)
    _responses_create(client)
    return client


def _usage_payload(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    payload: dict[str, Any] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = getattr(usage, key, None)
        if value is not None:
            payload[key] = value
    return payload


def _classify_sdk_error(exc: BaseException) -> DeepSeekResponsesError:
    status = getattr(exc, "status_code", None)
    if type(exc).__name__ in _TRANSIENT_NAMES or status in _TRANSIENT_STATUS:
        return TransientError(f"Transient DeepSeek Responses API failure: {exc}")
    return DeepSeekResponsesError(str(exc))


def create_web_search_response(
    *,
    instructions: str,
    input_text: str,
    model: str | None = None,
    environment: Mapping[str, str] | None = None,
    load_dotenv: bool = True,
    client: Any | None = None,
    timeout_seconds: float = 120.0,
    max_output_tokens: int = 6000,
) -> DeepSeekResponsesResult:
    """Call DeepSeek Responses API with server-side web search enabled."""

    env = dict(os.environ if environment is None else environment)
    selected_model = resolve_responses_model(env, model)
    if client is None:
        client = build_deepseek_responses_client(
            api_key=require_api_key(env, load_dotenv=load_dotenv),
            timeout_seconds=timeout_seconds,
        )
    create = _responses_create(client)
    request = {
        "model": selected_model,
        "instructions": instructions,
        "input": input_text,
        "tools": [{"type": "web_search"}],
        "tool_choice": {"type": "web_search"},
        "max_output_tokens": max_output_tokens,
    }

    last_error: DeepSeekResponsesError | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = create(**request)
        except DeepSeekResponsesError:
            raise
        except Exception as exc:
            mapped = _classify_sdk_error(exc)
            if not isinstance(mapped, TransientError) or attempt + 1 >= _MAX_ATTEMPTS:
                raise mapped from exc
            last_error = mapped
            time.sleep(_RETRY_BACKOFF_SECONDS[min(attempt, 1)])
            continue

        status = str(getattr(response, "status", "") or "completed").strip() or "completed"
        if status == "failed":
            raise DeepSeekResponsesError(
                "DeepSeek Responses API returned a failed response."
            )
        if status == "incomplete":
            raise DeepSeekResponsesError(
                "DeepSeek Responses API returned an incomplete response."
            )
        if status not in {"completed", "ok"}:
            raise DeepSeekResponsesError(
                f"DeepSeek Responses API returned status {status!r}."
            )
        output_text = str(getattr(response, "output_text", "") or "").strip()
        if not output_text:
            raise DeepSeekResponsesError(
                "DeepSeek Responses API returned empty output_text."
            )
        return DeepSeekResponsesResult(
            output_text=output_text,
            model=str(getattr(response, "model", None) or selected_model),
            status=status,
            usage=_usage_payload(getattr(response, "usage", None)),
        )

    raise last_error or DeepSeekResponsesError(
        "DeepSeek Responses API failed after retries."
    )
