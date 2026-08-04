"""DeepSeek-backed ``EvidenceInterpreter`` for the Evidence Card path."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from src.evidence.deepseek_explainer import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    _extract_json_object,
    _load_dotenv_if_present,
    _post_chat_completion,
)
from src.mvp.evidence_interpretation import MODEL_OUTPUT_FIELDS


class DeepSeekEvidenceInterpreter:
    """Structured Evidence Card interpreter using the shared DeepSeek client."""

    def __init__(
        self,
        *,
        environment: Mapping[str, str] | None = None,
        load_dotenv: bool = True,
        transport: Any | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 45.0,
    ) -> None:
        self._environment = environment
        self._load_dotenv = load_dotenv
        self._transport = transport
        self._model = model
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self.last_context: dict[str, Any] | None = None
        self.last_instructions: str | None = None

    def _resolved_environment(self) -> dict[str, str]:
        if self._load_dotenv:
            _load_dotenv_if_present()
        return dict(os.environ if self._environment is None else self._environment)

    def interpret(
        self,
        *,
        context: Mapping[str, Any],
        instructions: str,
    ) -> dict[str, Any]:
        env = self._resolved_environment()
        api_key = str(env.get("DEEPSEEK_API_KEY") or "").strip()
        if not api_key:
            raise ValueError("Missing DEEPSEEK_API_KEY")

        model = (
            self._model
            or str(env.get("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL).strip()
            or DEFAULT_DEEPSEEK_MODEL
        )
        base_url = (
            self._base_url
            or str(env.get("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL).strip()
            or DEFAULT_DEEPSEEK_BASE_URL
        )
        self.last_context = dict(context)
        self.last_instructions = instructions

        system = (
            f"{instructions}\n\n"
            "Respond with a single JSON object using exactly these keys: "
            f"{', '.join(sorted(MODEL_OUTPUT_FIELDS))}. "
            "narrative_changes, supporting_evidence_ids, "
            "contradicting_evidence_ids, missing_or_uncertain_evidence, "
            "monitoring_questions, and invalidation_conditions must be JSON "
            "arrays of strings."
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(
                    context,
                    ensure_ascii=True,
                    sort_keys=True,
                    default=str,
                ),
            },
        ]
        if self._transport is not None:
            content = self._transport(
                api_key=api_key,
                model=model,
                messages=messages,
                base_url=base_url,
                temperature=0.2,
            )
        else:
            content = _post_chat_completion(
                api_key=api_key,
                model=model,
                messages=messages,
                base_url=base_url,
                temperature=0.2,
                timeout_seconds=self._timeout_seconds,
            )
        parsed = _extract_json_object(content)
        missing = MODEL_OUTPUT_FIELDS.difference(parsed)
        extra = set(parsed).difference(MODEL_OUTPUT_FIELDS)
        if missing or extra:
            raise ValueError(
                "DeepSeek response fields do not match the schema "
                f"(missing={sorted(missing)}, extra={sorted(extra)})"
            )
        return parsed
