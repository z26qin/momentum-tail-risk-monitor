"""Tests for the isolated narrative-shift POC (mocked API only)."""

from __future__ import annotations

import importlib.util
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from src.evidence.deepseek_explainer import (
    DEFAULT_DEEPSEEK_MODEL,
    explain_risk_with_deepseek,
)
from src.evidence.deepseek_responses import (
    DEFAULT_RESPONSES_MODEL,
    AuthenticationFailureError,
    EmptyOutputError,
    FailedResponseError,
    IncompleteResponseError,
    InvalidRequestError,
    MissingAPIKeyError,
    RateLimitFailureError,
    UnsupportedSDKError,
    create_web_search_response,
    require_responses_create,
)
from src.evidence.gdelt_evidence import retrieve_gdelt_evidence
from src.evidence.narrative_shift_poc import (
    DEFAULT_CASE,
    FROZEN_CASE_CUTOFF,
    METADATA_FILENAME,
    REPORT_FILENAME,
    SYSTEM_INSTRUCTIONS,
    USER_PROMPT_TEMPLATE,
    OutputExistsError,
    dry_run_summary,
    format_dry_run,
    prompt_values,
    render_user_prompt,
    run_narrative_shift_poc,
    unresolved_placeholders,
)
from src.utils.io import REPO_ROOT, read_json


def _load_cli_module():
    path = REPO_ROOT / "scripts" / "run_narrative_shift_poc.py"
    spec = importlib.util.spec_from_file_location("narrative_shift_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_response(**overrides):
    payload = {
        "output_text": "# Public Narrative Shift POC\n\nlimited shift",
        "status": "completed",
        "model": DEFAULT_RESPONSES_MODEL,
        "usage": SimpleNamespace(
            input_tokens=11,
            output_tokens=22,
            total_tokens=33,
            output_tokens_details=SimpleNamespace(reasoning_tokens=4),
        ),
        "error": None,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


class FakeResponsesClient:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._response = response if response is not None else _fake_response()
        self._error = error
        self.responses = SimpleNamespace(create=self.create)

    def create(self, **kwargs: object):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


def test_prompt_variables_are_filled_and_cutoff_is_present() -> None:
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
    assert "{case_cutoff}" in USER_PROMPT_TEMPLATE
    assert unresolved_placeholders(USER_PROMPT_TEMPLATE)


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


def test_cli_dry_run_does_not_call_create(monkeypatch, capsys) -> None:
    cli = _load_cli_module()
    monkeypatch.setattr(
        "src.evidence.narrative_shift_poc.create_web_search_response",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("API called")),
    )
    exit_code = cli.main(["--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "deepseek-v4-flash" in captured.out
    assert "2026-05-29" in captured.out
    assert "AI infrastructure and semiconductor momentum" in captured.out
    assert "api_key_present:" in captured.out


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
    assert metadata["limitations"][0] == "Exploratory POC only"
    assert client.calls[0]["model"] == DEFAULT_RESPONSES_MODEL
    assert client.calls[0]["tools"] == [{"type": "web_search"}]
    assert client.calls[0]["tool_choice"] == {"type": "web_search"}
    assert "previous_response_id" not in client.calls[0]
    assert "conversation" not in client.calls[0]
    assert "search_context_size" not in str(client.calls[0])
    assert "user_location" not in str(client.calls[0])


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
    with pytest.raises(EmptyOutputError, match="output_text"):
        create_web_search_response(
            instructions="x",
            input_text="y",
            client=FakeResponsesClient(_fake_response(output_text="   ")),
            load_dotenv=False,
            environment={"DEEPSEEK_API_KEY": "test-only"},
        )
    with pytest.raises(IncompleteResponseError, match="incomplete"):
        create_web_search_response(
            instructions="x",
            input_text="y",
            client=FakeResponsesClient(_fake_response(status="incomplete")),
            load_dotenv=False,
            environment={"DEEPSEEK_API_KEY": "test-only"},
        )
    with pytest.raises(FailedResponseError, match="failed"):
        create_web_search_response(
            instructions="x",
            input_text="y",
            client=FakeResponsesClient(_fake_response(status="failed")),
            load_dotenv=False,
            environment={"DEEPSEEK_API_KEY": "test-only"},
        )


def test_auth_errors_are_not_retried(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.evidence.deepseek_responses._classify_sdk_error",
        lambda _exc: AuthenticationFailureError(
            "DeepSeek authentication failed."
        ),
    )
    client = FakeResponsesClient(error=RuntimeError("401"))
    with pytest.raises(AuthenticationFailureError, match="authentication"):
        create_web_search_response(
            instructions="x",
            input_text="y",
            client=client,
            load_dotenv=False,
            environment={"DEEPSEEK_API_KEY": "test-only"},
        )
    assert len(client.calls) == 1


def test_transient_errors_retry_twice(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        "src.evidence.deepseek_responses.time.sleep", sleeps.append
    )
    monkeypatch.setattr(
        "src.evidence.deepseek_responses._classify_sdk_error",
        lambda _exc: RateLimitFailureError("rate limit"),
    )
    client = FakeResponsesClient(error=RuntimeError("429"))
    with pytest.raises(RateLimitFailureError, match="rate limit"):
        create_web_search_response(
            instructions="x",
            input_text="y",
            client=client,
            load_dotenv=False,
            environment={"DEEPSEEK_API_KEY": "test-only"},
        )
    assert len(client.calls) == 3
    assert sleeps == [1.0, 2.0]


def test_invalid_request_is_not_retried(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.evidence.deepseek_responses._classify_sdk_error",
        lambda _exc: InvalidRequestError("bad request"),
    )
    client = FakeResponsesClient(error=RuntimeError("400"))
    with pytest.raises(InvalidRequestError, match="bad request"):
        create_web_search_response(
            instructions="x",
            input_text="y",
            client=client,
            load_dotenv=False,
            environment={"DEEPSEEK_API_KEY": "test-only"},
        )
    assert len(client.calls) == 1


def test_unsupported_sdk_without_responses_create() -> None:
    with pytest.raises(UnsupportedSDKError, match="responses.create"):
        require_responses_create(SimpleNamespace())


def _gdelt_evidence():
    rows = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2025-04-24T16:30:00Z"),
                "date": date(2025, 4, 24),
                "title": "Credit a short squeeze for the market bounce",
                "source": "news.example",
                "url": "https://example.com/short-squeeze",
                "gdelt_query": "crowding",
            }
        ]
    )
    triggers = [
        {
            "trigger": "short_loss_in_recovery",
            "observed_value": 0.27,
            "threshold": 0.26,
            "status": "triggered",
            "direction": "greater_than_or_equal",
        }
    ]
    return retrieve_gdelt_evidence(
        rows,
        as_of_date="2025-05-01",
        active_triggers=triggers,
        lookback_days=30,
        max_records=20,
        clamp_max_records=False,
    ), triggers


def test_existing_deepseek_chat_completions_path_is_unchanged(tmp_path) -> None:
    captured: dict[str, object] = {}

    def transport(**kwargs: object) -> str:
        captured.update(kwargs)
        return (
            '{"trigger_summary":"Short-leg losses are active.",'
            '"recent_narrative":"Coverage mentions a short squeeze [E1].",'
            '"momentum_mechanism":"Short covering may amplify the rebound.",'
            '"key_evidence_ids":["E1"],'
            '"limitations":"Title-only evidence is incomplete.",'
            '"pm_takeaway":"Review the short-leg contribution."}'
        )

    evidence, triggers = _gdelt_evidence()
    result = explain_risk_with_deepseek(
        triggers,
        evidence,
        "2025-05-01",
        cache_dir=tmp_path,
        load_dotenv=False,
        environment={"DEEPSEEK_API_KEY": "test-key"},
        transport=transport,
    )

    assert DEFAULT_DEEPSEEK_MODEL == "deepseek-chat"
    assert result["status"] == "ok"
    assert result["provider"] == "deepseek"
    assert result["model"] == "deepseek-chat"
    assert captured["model"] == "deepseek-chat"
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["temperature"] == 0.2
    assert "messages" in captured
    assert "tools" not in captured
