"""DeepSeek Responses API adapter (separate from the Chat Completions path).

The existing GDELT / Evidence Card / PM interpreters continue to use
``src.evidence.deepseek_explainer`` Chat Completions. This module is only for
exploratory callers that need server-side ``web_search`` through
``client.responses.create``.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.evidence.deepseek_explainer import (
    DEFAULT_DEEPSEEK_BASE_URL,
    _load_dotenv_if_present,
)

DEFAULT_RESPONSES_MODEL = "deepseek-v4-flash"
DEFAULT_RESPONSES_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_OUTPUT_TOKENS = 6000
RESPONSES_ENV_MODEL = "DEEPSEEK_RESPONSES_MODEL"
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = (1.0, 2.0)
_TRANSIENT_HTTP_STATUS = frozenset({408, 429, 500, 502, 503, 504})


class DeepSeekResponsesError(Exception):
    """Base error for the DeepSeek Responses API adapter."""


class MissingAPIKeyError(DeepSeekResponsesError):
    """Raised when ``DEEPSEEK_API_KEY`` is absent."""


class UnsupportedSDKError(DeepSeekResponsesError):
    """Raised when the installed OpenAI SDK cannot call Responses."""


class AuthenticationFailureError(DeepSeekResponsesError):
    """Raised on authentication or permission failures. Not retried."""


class InvalidRequestError(DeepSeekResponsesError):
    """Raised on client-side invalid requests. Not retried."""


class RateLimitFailureError(DeepSeekResponsesError):
    """Raised after retries are exhausted on rate-limit responses."""


class TimeoutFailureError(DeepSeekResponsesError):
    """Raised after retries are exhausted on timeouts or connection errors."""


class EmptyOutputError(DeepSeekResponsesError):
    """Raised when the Responses API returns no ``output_text``."""


class IncompleteResponseError(DeepSeekResponsesError):
    """Raised when the response status is ``incomplete``."""


class FailedResponseError(DeepSeekResponsesError):
    """Raised when the response status is ``failed``."""


@dataclass(frozen=True)
class DeepSeekResponsesResult:
    """Minimal Responses API result used by the narrative-shift POC."""

    output_text: str
    model: str
    status: str
    usage: dict[str, Any]


def resolve_responses_model(
    environment: Mapping[str, str] | None = None,
    model: str | None = None,
) -> str:
    """Return the Responses model, defaulting to ``deepseek-v4-flash``."""

    if model is not None and str(model).strip():
        return str(model).strip()
    env = os.environ if environment is None else environment
    configured = str(env.get(RESPONSES_ENV_MODEL) or "").strip()
    return configured or DEFAULT_RESPONSES_MODEL


def api_key_is_present(
    environment: Mapping[str, str] | None = None,
    *,
    load_dotenv: bool = True,
) -> bool:
    """Return whether ``DEEPSEEK_API_KEY`` is set without exposing the value."""

    if load_dotenv:
        _load_dotenv_if_present()
    env = os.environ if environment is None else environment
    return bool(str(env.get("DEEPSEEK_API_KEY") or "").strip())


def require_api_key(
    environment: Mapping[str, str] | None = None,
    *,
    load_dotenv: bool = True,
) -> str:
    """Return the DeepSeek API key or raise ``MissingAPIKeyError``."""

    if load_dotenv:
        _load_dotenv_if_present()
    env = os.environ if environment is None else environment
    api_key = str(env.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        raise MissingAPIKeyError(
            "Missing DEEPSEEK_API_KEY. Set it in the environment or a local "
            ".env file before calling the DeepSeek Responses API."
        )
    return api_key


def require_responses_create(client: Any) -> Any:
    """Return ``client.responses.create`` or raise ``UnsupportedSDKError``."""

    create = getattr(getattr(client, "responses", None), "create", None)
    if not callable(create):
        raise UnsupportedSDKError(
            "Installed openai SDK does not expose client.responses.create. "
            "This repository pins openai==3.1.0 for the DeepSeek Responses API."
        )
    return create


def build_deepseek_responses_client(
    *,
    api_key: str,
    base_url: str = DEFAULT_DEEPSEEK_BASE_URL,
    timeout_seconds: float = DEFAULT_RESPONSES_TIMEOUT_SECONDS,
) -> Any:
    """Construct an OpenAI SDK client pointed at DeepSeek."""

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise UnsupportedSDKError(
            "The openai package is required for the DeepSeek Responses API. "
            "Install repository dependencies with `uv sync --locked`."
        ) from exc

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout_seconds,
    )
    require_responses_create(client)
    return client


def _usage_payload(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    payload: dict[str, Any] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = getattr(usage, key, None)
        if value is not None:
            payload[key] = value
    details = getattr(usage, "output_tokens_details", None)
    reasoning = getattr(details, "reasoning_tokens", None) if details is not None else None
    if reasoning is not None:
        payload["reasoning_tokens"] = reasoning
    return payload


def _response_error_message(response: Any) -> str:
    error = getattr(response, "error", None)
    if error is None:
        return "DeepSeek Responses API returned a failed response."
    message = getattr(error, "message", None) or str(error)
    return f"DeepSeek Responses API failed: {message}"


def _classify_sdk_error(exc: BaseException) -> DeepSeekResponsesError:
    try:
        from openai import (
            APIConnectionError,
            APIStatusError,
            APITimeoutError,
            AuthenticationError,
            BadRequestError,
            PermissionDeniedError,
            RateLimitError,
            UnprocessableEntityError,
        )
    except ImportError:
        return DeepSeekResponsesError(str(exc))

    if isinstance(exc, AuthenticationError) or isinstance(exc, PermissionDeniedError):
        return AuthenticationFailureError(
            "DeepSeek authentication failed. Check DEEPSEEK_API_KEY."
        )
    if isinstance(exc, (BadRequestError, UnprocessableEntityError)):
        return InvalidRequestError(f"DeepSeek rejected the Responses request: {exc}")
    if isinstance(exc, RateLimitError):
        return RateLimitFailureError(
            "DeepSeek rate limit reached while calling the Responses API."
        )
    if isinstance(exc, (APITimeoutError, APIConnectionError)):
        return TimeoutFailureError(
            "DeepSeek Responses API timed out or could not be reached."
        )
    if isinstance(exc, APIStatusError):
        status = getattr(exc, "status_code", None)
        if status in {401, 403}:
            return AuthenticationFailureError(
                "DeepSeek authentication failed. Check DEEPSEEK_API_KEY."
            )
        if status in {400, 422}:
            return InvalidRequestError(
                f"DeepSeek rejected the Responses request: {exc}"
            )
        if status == 429:
            return RateLimitFailureError(
                "DeepSeek rate limit reached while calling the Responses API."
            )
        if status in _TRANSIENT_HTTP_STATUS:
            return TimeoutFailureError(
                f"DeepSeek Responses API returned transient HTTP {status}."
            )
    return DeepSeekResponsesError(str(exc))


def _is_retryable(error: DeepSeekResponsesError) -> bool:
    return isinstance(error, (RateLimitFailureError, TimeoutFailureError))


def create_web_search_response(
    *,
    instructions: str,
    input_text: str,
    model: str | None = None,
    environment: Mapping[str, str] | None = None,
    load_dotenv: bool = True,
    client: Any | None = None,
    timeout_seconds: float = DEFAULT_RESPONSES_TIMEOUT_SECONDS,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> DeepSeekResponsesResult:
    """Call DeepSeek Responses API with server-side web search enabled.

    Does not use ``previous_response_id``, ``conversation``, or background
    mode. Does not fall back to a request without web search.
    """

    env = dict(os.environ if environment is None else environment)
    selected_model = resolve_responses_model(env, model)
    if client is None:
        api_key = require_api_key(env, load_dotenv=load_dotenv)
        client = build_deepseek_responses_client(
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    else:
        require_responses_create(client)

    create = require_responses_create(client)
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
            if not _is_retryable(mapped) or attempt + 1 >= _MAX_ATTEMPTS:
                raise mapped from exc
            last_error = mapped
            time.sleep(
                _RETRY_BACKOFF_SECONDS[
                    min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)
                ]
            )
            continue

        status = str(getattr(response, "status", "") or "completed").strip() or "completed"
        if status == "failed":
            raise FailedResponseError(_response_error_message(response))
        if status == "incomplete":
            raise IncompleteResponseError(
                "DeepSeek Responses API returned an incomplete response "
                "(truncated or unfinished)."
            )
        if status not in {"completed", "ok"}:
            raise FailedResponseError(
                f"DeepSeek Responses API returned status {status!r}."
            )

        output_text = str(getattr(response, "output_text", "") or "").strip()
        if not output_text:
            raise EmptyOutputError(
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
