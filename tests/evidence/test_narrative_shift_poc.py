"""Tests for the isolated narrative-shift POC (mocked API only)."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from src.evidence.deepseek_explainer import (
    DEFAULT_DEEPSEEK_MODEL,
    explain_risk_with_deepseek,
)
from src.evidence.deepseek_responses import (
    DEFAULT_RESPONSES_MODEL,
    DeepSeekResponsesError,
    MissingAPIKeyError,
    create_web_search_response,
)
from src.evidence.narrative_shift_poc import (
    DEFAULT_CASE,
    FROZEN_CASE_CUTOFF,
    METADATA_FILENAME,
    REPORT_FILENAME,
    SYSTEM_INSTRUCTIONS,
    OutputExistsError,
    dry_run_summary,
    format_dry_run,
    load_user_prompt_template,
    prompt_values,
    render_user_prompt,
    run_narrative_shift_poc,
    unresolved_placeholders,
)
from src.utils.io import read_json


def _fake_response(**overrides):
    payload = {
        "output_text": "# Public Narrative Shift POC\n\nlimited shift",
        "status": "completed",
        "model": DEFAULT_RESPONSES_MODEL,
        "usage": SimpleNamespace(input_tokens=11, output_tokens=22, total_tokens=33),
        "error": None,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


class FakeResponsesClient:
    def __init__(self, response=None) -> None:
        self.calls: list[dict[str, object]] = []
        self._response = response if response is not None else _fake_response()
        self.responses = SimpleNamespace(create=self.create)

    def create(self, **kwargs: object):
        self.calls.append(kwargs)
        return self._response


def test_prompt_variables_are_filled_and_cutoff_is_present() -> None:
    template = load_user_prompt_template()
    prompt = render_user_prompt()
    values = prompt_values(DEFAULT_CASE)

    assert DEFAULT_CASE.case_name in prompt
    assert DEFAULT_CASE.theme in prompt
    assert "NVIDIA Corporation" in prompt
    assert "Ciena Corporation" in prompt
    assert values["baseline_start"] in prompt
    assert values["recent_end"] in prompt
    assert FROZEN_CASE_CUTOFF in prompt
    assert DEFAULT_CASE.case_cutoff == "2026-05-29"
    assert unresolved_placeholders(prompt) == []
    assert "{case_cutoff}" in template
    assert unresolved_placeholders(template)


def test_missing_api_key_raises_clear_error(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(MissingAPIKeyError, match="DEEPSEEK_API_KEY"):
        create_web_search_response(
            instructions=SYSTEM_INSTRUCTIONS,
            input_text="test",
            environment={},
            load_dotenv=False,
        )


def test_dry_run_does_not_call_the_api() -> None:
    client = FakeResponsesClient()
    summary = dry_run_summary(environment={}, load_dotenv=False)

    assert summary["dry_run"] is True
    assert summary["model"] == DEFAULT_RESPONSES_MODEL
    assert summary["case_cutoff"] == "2026-05-29"
    assert summary["theme"] == DEFAULT_CASE.theme
    assert "NVIDIA Corporation" in summary["entities"]
    assert summary["api_key_present"] is False
    assert summary["approximate_prompt_length"] > 1000
    assert client.calls == []
    assert "no API call" in format_dry_run(summary)


def test_response_text_is_written_to_expected_path(tmp_path) -> None:
    client = FakeResponsesClient()
    result = run_narrative_shift_poc(
        output_dir=tmp_path,
        overwrite=False,
        environment={"DEEPSEEK_API_KEY": "test-only"},
        load_dotenv=False,
        client=client,
    )

    report_path = tmp_path / REPORT_FILENAME
    metadata_path = tmp_path / METADATA_FILENAME
    assert result["report_path"] == str(report_path)
    assert report_path.read_text(encoding="utf-8") == (
        "# Public Narrative Shift POC\n\nlimited shift"
    )
    metadata = read_json(metadata_path)
    assert metadata["api"] == "DeepSeek Responses API"
    assert metadata["web_search_enabled"] is True
    assert metadata["case_cutoff"] == "2026-05-29"
    assert metadata["model"] == DEFAULT_RESPONSES_MODEL
    assert metadata["usage"]["total_tokens"] == 33
    assert client.calls[0]["model"] == DEFAULT_RESPONSES_MODEL
    assert client.calls[0]["tools"] == [{"type": "web_search"}]
    assert client.calls[0]["tool_choice"] == {"type": "web_search"}
    assert "previous_response_id" not in client.calls[0]


def test_existing_output_requires_overwrite(tmp_path) -> None:
    client = FakeResponsesClient()
    run_narrative_shift_poc(
        output_dir=tmp_path,
        environment={"DEEPSEEK_API_KEY": "test-only"},
        load_dotenv=False,
        client=client,
    )
    with pytest.raises(OutputExistsError, match="--overwrite"):
        run_narrative_shift_poc(
            output_dir=tmp_path,
            environment={"DEEPSEEK_API_KEY": "test-only"},
            load_dotenv=False,
            client=client,
        )
    run_narrative_shift_poc(
        output_dir=tmp_path,
        overwrite=True,
        environment={"DEEPSEEK_API_KEY": "test-only"},
        load_dotenv=False,
        client=client,
    )
    assert (tmp_path / REPORT_FILENAME).exists()


def test_empty_and_failed_responses_are_errors() -> None:
    with pytest.raises(DeepSeekResponsesError, match="output_text"):
        create_web_search_response(
            instructions="x",
            input_text="y",
            client=FakeResponsesClient(_fake_response(output_text="   ")),
            load_dotenv=False,
            environment={"DEEPSEEK_API_KEY": "test-only"},
        )
    with pytest.raises(DeepSeekResponsesError, match="incomplete"):
        create_web_search_response(
            instructions="x",
            input_text="y",
            client=FakeResponsesClient(_fake_response(status="incomplete")),
            load_dotenv=False,
            environment={"DEEPSEEK_API_KEY": "test-only"},
        )
    with pytest.raises(DeepSeekResponsesError, match="failed"):
        create_web_search_response(
            instructions="x",
            input_text="y",
            client=FakeResponsesClient(_fake_response(status="failed")),
            load_dotenv=False,
            environment={"DEEPSEEK_API_KEY": "test-only"},
        )


def test_existing_deepseek_chat_completions_path_is_unchanged(tmp_path) -> None:
    captured: dict[str, object] = {}

    def transport(**kwargs: object) -> str:
        captured.update(kwargs)
        raise AssertionError("inactive path must not call the transport")

    result = explain_risk_with_deepseek(
        [],
        pd.DataFrame(),
        "2025-05-01",
        cache_dir=tmp_path,
        load_dotenv=False,
        environment={"DEEPSEEK_API_KEY": "test-key"},
        transport=transport,
    )

    assert DEFAULT_DEEPSEEK_MODEL == "deepseek-chat"
    assert result["status"] == "inactive"
    assert result["provider"] == "deepseek"
    assert result["model"] == "deepseek-chat"
    assert captured == {}
