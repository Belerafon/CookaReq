"""Tests for llm client."""

import asyncio
import json
import logging
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
import httpx

from app.llm.client import LLMClient, NO_API_KEY
from app.llm.types import LLMResponse, LLMToolCall
from app.llm.harmony import convert_tools_for_harmony
from app.llm.validation import ToolValidationError
from app.llm.spec import SYSTEM_PROMPT, TOOLS
from app.log import logger
from app.mcp.server import JsonlHandler
from app.settings import LLMSettings
from app.util.cancellation import CancellationEvent, OperationCancelledError
from tests.llm_utils import make_openai_mock, settings_with_llm

pytestmark = pytest.mark.integration
def test_missing_api_key_ignores_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    captured: dict[str, str | None] = {}

    class FakeOpenAI:
        def __init__(
            self,
            *,
            base_url,
            api_key,
            timeout,
            max_retries,
        ):  # pragma: no cover - simple capture
            captured["api_key"] = api_key
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: SimpleNamespace()),
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    settings = LLMSettings(base_url="https://example", model="foo", api_key=None)
    LLMClient(settings)
    assert captured["api_key"] == NO_API_KEY


def test_check_llm(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    monkeypatch.setattr(
        "openai.OpenAI",
        make_openai_mock({"ping": ("noop", {})}),
    )
    client = LLMClient(settings.llm)
    log_file = tmp_path / "llm.jsonl"
    handler = JsonlHandler(str(log_file))
    logger.addHandler(handler)
    prev_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        result = client.check_llm()
    finally:
        logger.setLevel(prev_level)
        logger.removeHandler(handler)
    assert result == {"ok": True}
    entries = [json.loads(line) for line in log_file.read_text().splitlines()]
    req = next(e for e in entries if e.get("event") == "LLM_REQUEST")
    res = next(e for e in entries if e.get("event") == "LLM_RESPONSE")
    assert req["payload"] == {
        "model": settings.llm.model,
        "messages": [{"role": "user", "content": "ping"}],
    }
    assert res["payload"]["ok"] is True
    assert "timestamp" in req and "size_bytes" in req
    assert "duration_ms" in res


def test_check_llm_omits_token_limits(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple container
            def create(*, model, messages, **kwargs):  # noqa: ANN001
                captured.update(kwargs)
                return SimpleNamespace()

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    client.check_llm()
    for forbidden in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
        assert forbidden not in captured









def test_chat_custom_temperature_applied(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    settings.llm.use_custom_temperature = True
    settings.llm.temperature = 0.37
    captured_temperatures: list[float | None] = []
    captured_kwargs: list[dict[str, object]] = []

    class FakeOpenAI:
        def __init__(self, *a, **k) -> None:  # pragma: no cover - simple capture
            def create(
                *,
                model,
                messages,
                tools=None,
                temperature=None,
                **kwargs,
            ):  # noqa: ANN001
                captured_temperatures.append(temperature)
                captured_kwargs.append(dict(kwargs))
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content="ok",
                                tool_calls=None,
                            )
                        )
                    ]
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )
            self.responses = SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    output=[
                        SimpleNamespace(
                            type="message",
                            content=[
                                SimpleNamespace(type="output_text", text="noop")
                            ],
                        )
                    ]
                )
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)

    assert client.check_llm() == {"ok": True}
    response = client.parse_command("ping")
    assert response.content == "ok"

    assert len(captured_temperatures) == 2
    for value in captured_temperatures:
        assert value == pytest.approx(settings.llm.temperature)
    for payload in captured_kwargs:
        assert "temperature" not in payload


def test_check_llm_harmony_reports_missing_responses(
    tmp_path: Path, monkeypatch
) -> None:
    settings = settings_with_llm(tmp_path, message_format="harmony")

    class FakeOpenAI:
        def __init__(self, *a, **k) -> None:  # pragma: no cover - simple stub
            def create(**kwargs):  # noqa: ANN001
                request = httpx.Request("POST", "https://example.test/v1/responses")
                response = httpx.Response(404, request=request)
                raise httpx.HTTPStatusError(
                    "Not Found", request=request, response=response
                )

            self.responses = SimpleNamespace(create=create)
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: SimpleNamespace())
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    result = client.check_llm()
    assert result["ok"] is False
    error = result["error"]
    assert error["type"] == "HTTPStatusError"
    assert "Responses API" in error["hint"]
    assert settings.llm.base_url in error["hint"]





def test_harmony_custom_temperature_applied(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path, message_format="harmony")
    settings.llm.use_custom_temperature = True
    settings.llm.temperature = 1.5
    captured_temperatures: list[float | None] = []
    captured_kwargs: list[dict[str, object]] = []

    class FakeOpenAI:
        def __init__(self, *a, **k) -> None:  # pragma: no cover - simple capture
            def create(
                *,
                model,
                input,
                tools,
                reasoning,
                temperature=None,
                **kwargs,
            ):  # noqa: ANN001
                captured_temperatures.append(temperature)
                captured_kwargs.append(dict(kwargs))
                return SimpleNamespace(
                    output=[
                        SimpleNamespace(
                            type="message",
                            content=[
                                SimpleNamespace(type="output_text", text="done")
                            ],
                        )
                    ]
                )

            self.responses = SimpleNamespace(create=create)
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: SimpleNamespace())
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)

    assert client.check_llm() == {"ok": True}
    response = client.parse_command("ping")
    assert response.content == "done"

    assert len(captured_temperatures) == 2
    for value in captured_temperatures:
        assert value == pytest.approx(settings.llm.temperature)
    for payload in captured_kwargs:
        assert "temperature" not in payload


def test_parse_command_includes_history(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple container
            def create(*, model, messages, tools=None, **kwargs):  # noqa: ANN001
                captured["messages"] = messages
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        function=SimpleNamespace(
                                            name="list_requirements",
                                            arguments="{}",
                                        )
                                    )
                                ]
                            )
                        )
                    ]
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "system", "content": "drop me"},
    ]
    response = client.parse_command("follow up", history=history)
    assert isinstance(response, LLMResponse)
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert isinstance(call, LLMToolCall)
    assert call.name == "list_requirements"
    assert call.arguments == {}
    messages = captured["messages"]
    system_message = messages[0]
    assert system_message["role"] == "system"
    assert system_message["content"].startswith(SYSTEM_PROMPT)
    assert "drop me" in system_message["content"]
    assert messages[-1] == {"role": "user", "content": "follow up"}
    assert messages[1:-1] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]


def test_parse_command_preserves_assistant_reasoning(
    tmp_path: Path, monkeypatch
) -> None:
    settings = settings_with_llm(tmp_path)
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple capture
            def create(*, model, messages, tools=None, **kwargs):  # noqa: ANN001
                captured["messages"] = messages
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content="ok",
                                tool_calls=None,
                            )
                        )
                    ]
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    history = [
        {
            "role": "assistant",
            "content": "previous reply",
            "reasoning": [{"type": "analysis", "text": "thinking"}],
        }
    ]

    client.parse_command("follow up", history=history)

    messages = captured["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"].startswith(SYSTEM_PROMPT)
    assistant_message = messages[1]
    assert assistant_message["role"] == "assistant"
    assert assistant_message["content"].strip() == "previous reply"
    assert assistant_message["reasoning"] == [
        {"type": "analysis", "text": "thinking"}
    ]
    assert messages[-1] == {"role": "user", "content": "follow up"}


def test_qwen_message_format_wraps_segments(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path, message_format="qwen")
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple capture
            def create(*, model, messages, **kwargs):  # noqa: ANN001
                captured["messages"] = messages
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content="ok",
                                tool_calls=None,
                            )
                        )
                    ]
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    response = client.parse_command("hello")
    assert response.content == "ok"
    assert response.reasoning == ()
    messages = captured["messages"]
    assert isinstance(messages, list)
    system_message = messages[0]
    assert system_message["role"] == "system"
    assert system_message["content"] == [
        {"type": "text", "text": SYSTEM_PROMPT}
    ]
    user_message = messages[-1]
    assert user_message["role"] == "user"
    assert user_message["content"] == [
        {"type": "text", "text": "hello"}
    ]


def test_qwen_reasoning_tool_call_extraction(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path, message_format="qwen")

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple capture
            def create(*, model, messages, tools=None, **kwargs):  # noqa: ANN001
                reasoning = [
                    {"type": "reasoning", "text": "thinking"},
                    {
                        "type": "tool_call",
                        "id": "call-1",
                        "function": {
                            "name": "list_requirements",
                            "arguments": {"per_page": 5},
                        },
                    },
                ]
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content="",
                                tool_calls=None,
                                reasoning_content=reasoning,
                            )
                        )
                    ]
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    history = [{"role": "user", "content": "ping"}]
    response = client.respond(history)
    assert response.content == "thinking"
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.name == "list_requirements"
    assert call.arguments == {"per_page": 5}
    assert response.reasoning
    assert response.reasoning[0].text == "thinking"


def test_parse_command_captures_reasoning_segments(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple capture
            def create(*, model, messages, tools=None, **kwargs):  # noqa: ANN001
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=[
                                    {"type": "reasoning", "text": "step one"},
                                    {"type": "reasoning", "text": "step two"},
                                    {"type": "text", "text": "final answer"},
                                ],
                                tool_calls=None,
                            )
                        )
                    ]
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    response = client.parse_command("hello")
    assert response.content == "final answer"
    assert len(response.reasoning) == 1
    combined = response.reasoning[0].text
    assert "step one" in combined
    assert "step two" in combined


def test_parse_command_collects_reasoning_text_and_summary(
    tmp_path: Path, monkeypatch
) -> None:
    settings = settings_with_llm(tmp_path)

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple capture
            def create(*, model, messages, tools=None, **kwargs):  # noqa: ANN001
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content="final",
                                tool_calls=None,
                                reasoning="internal stream",
                                reasoning_details=[
                                    {
                                        "type": "reasoning.summary",
                                        "summary": "condensed",
                                    },
                                    {
                                        "type": "reasoning.encrypted",
                                        "data": "hidden",
                                    },
                                ],
                            )
                        )
                    ]
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    response = client.parse_command("hello")
    assert response.content == "final"
    assert [
        (segment.type, segment.text)
        for segment in response.reasoning
    ] == [
        ("reasoning", "internal stream"),
        ("reasoning.summary", "condensed"),
    ]


def test_parse_command_recovers_concatenated_tool_arguments(
    tmp_path: Path, monkeypatch
) -> None:
    settings = settings_with_llm(tmp_path)

    recovered_events: list[tuple[str, dict[str, object] | None]] = []
    recovered_debug: list[dict[str, object] | None] = []

    def fake_log_event(event: str, payload=None, **kwargs):  # noqa: ANN001
        if event == "LLM_TOOL_ARGUMENTS_RECOVERED":
            recovered_events.append((event, payload))

    def fake_log_debug(event: str, payload=None):  # noqa: ANN001
        if event == "LLM_TOOL_ARGUMENTS_RECOVERED":
            recovered_debug.append(payload)

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple container
            def create(*, model, messages, tools=None, **kwargs):  # noqa: ANN001
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        function=SimpleNamespace(
                                            name="update_requirement_field",
                                            arguments='{}{"rid": "SYS-1", "field": "status", "value": "approved"}',
                                        )
                                    )
                                ],
                                content=None,
                            )
                        )
                    ]
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("app.llm.response_parser.log_event", fake_log_event)
    monkeypatch.setattr(
        "app.llm.response_parser.log_debug_payload", fake_log_debug
    )
    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)

    response = client.parse_command("update status SYS-1")
    assert response.tool_calls, "expected recovered tool call"
    call = response.tool_calls[0]
    assert call.name == "update_requirement_field"
    assert call.arguments == {
        "rid": "SYS-1",
        "field": "status",
        "value": "approved",
    }

    assert recovered_events, "expected telemetry for recovered tool arguments"
    event_name, payload = recovered_events[0]
    assert event_name == "LLM_TOOL_ARGUMENTS_RECOVERED"
    assert payload is not None
    assert payload["call_id"] == "tool_call_0"
    assert payload["tool_name"] == "update_requirement_field"
    assert payload["classification"] == "concatenated_json"
    assert payload["fragments"] == 2
    assert payload["recovered_fragment_index"] == 1
    assert payload["empty_fragments"] == 1
    assert payload["preview"].startswith("{}{")
    assert payload["length"] == len(
        '{}{"rid": "SYS-1", "field": "status", "value": "approved"}'
    )
    assert payload["recovered_keys"] == ["field", "rid", "value"]
    assert recovered_debug, "expected debug payload for recovered arguments"
    debug_payload = recovered_debug[0]
    assert debug_payload is not None
    assert debug_payload["recovered_arguments"] == {
        "rid": "SYS-1",
        "field": "status",
        "value": "approved",
    }


def test_parse_command_reports_invalid_tool_arguments(
    tmp_path: Path, monkeypatch
) -> None:
    settings = settings_with_llm(tmp_path)

    events: list[tuple[str, dict[str, object] | None]] = []
    debug_payloads: list[dict[str, object] | None] = []

    def fake_log_event(event: str, payload=None, **kwargs):  # noqa: ANN001
        if event == "LLM_TOOL_ARGUMENTS_INVALID":
            events.append((event, payload))

    def fake_log_debug(event: str, payload=None):  # noqa: ANN001
        if event == "LLM_TOOL_ARGUMENTS_INVALID":
            debug_payloads.append(payload)

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple container
            def create(*, model, messages, tools=None, **kwargs):  # noqa: ANN001
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        function=SimpleNamespace(
                                            name="update_requirement_field",
                                            arguments='{"rid": "SYS-1", "field": "status", "value": "approved"',
                                        )
                                    )
                                ],
                                content=None,
                            )
                        )
                    ]
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("app.llm.response_parser.log_event", fake_log_event)
    monkeypatch.setattr(
        "app.llm.response_parser.log_debug_payload", fake_log_debug
    )
    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)

    with pytest.raises(ToolValidationError):
        client.parse_command("update status SYS-1")

    assert events, "expected telemetry for invalid tool arguments"
    event_name, payload = events[0]
    assert event_name == "LLM_TOOL_ARGUMENTS_INVALID"
    assert payload is not None
    assert payload["call_id"] == "tool_call_0"
    assert payload["tool_name"] == "update_requirement_field"
    assert payload["preview"].startswith('{"rid": "SYS-1"')
    assert payload["length"] == len(
        '{"rid": "SYS-1", "field": "status", "value": "approved"'
    )
    assert debug_payloads, "expected debug payload for invalid arguments"


def test_parse_command_omits_token_limits(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple container
            def create(*, model, messages, tools=None, **kwargs):  # noqa: ANN001
                captured.update(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        function=SimpleNamespace(
                                            name="list_requirements",
                                            arguments="{}",
                                        )
                                    )
                                ]
                            )
                        )
                    ]
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    response = client.parse_command("anything")
    assert isinstance(response, LLMResponse)
    assert len(response.tool_calls) == 1
    for forbidden in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
        assert forbidden not in captured


def test_parse_command_reports_missing_choices(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)

    class DummyCompletion:
        response = SimpleNamespace(status_code=200)

        @staticmethod
        def model_dump() -> dict[str, object]:
            return {"detail": "This endpoint does not implement chat completions"}

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple container
            def create(*, model, messages, tools=None, **kwargs):  # noqa: ANN001
                return DummyCompletion()

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    with pytest.raises(ToolValidationError) as exc:
        client.parse_command("anything")

    message = str(exc.value)
    assert "base URL" in message
    assert settings.llm.base_url in message
    assert "LM Studio" in message
    assert "keys: detail" in message
    assert "HTTP status 200" in message


def test_parse_command_without_tool_call(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple container
            def create(*, model, messages, tools=None, **kwargs):  # noqa: ANN001
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                tool_calls=None,
                                content="Hello",
                            ),
                        )
                    ]
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    response = client.parse_command("hi")
    assert isinstance(response, LLMResponse)
    assert response.tool_calls == ()
    assert response.content == "Hello"


def test_respond_includes_request_snapshot(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    monkeypatch.setattr("openai.OpenAI", make_openai_mock({"hello": "Done"}))
    client = LLMClient(settings.llm)

    conversation = [
        {"role": "system", "content": "extra system"},
        {"role": "user", "content": "hello"},
    ]

    response = client.respond(conversation)
    assert response.request_messages is not None
    assert response.request_messages[0]["role"] == "system"
    assert response.request_messages[-1]["role"] == "user"
    assert response.request_messages[-1]["content"] == "hello"


def test_parse_command_reports_tool_validation_details(
    tmp_path: Path, monkeypatch
) -> None:
    settings = settings_with_llm(tmp_path)

    monkeypatch.setattr(
        "openai.OpenAI",
        make_openai_mock(
            {
                "Write the text of the first requirement": [
                    (
                        "create_requirement",
                        {"prefix": "SYS", "data": {"title": "Req-1"}},
                    )
                ]
            }
        ),
    )

    client = LLMClient(settings.llm)

    response = client.parse_command("Write the text of the first requirement")

    assert isinstance(response, LLMResponse)
    assert response.tool_calls
    call = response.tool_calls[0]
    assert call.name == "create_requirement"
    assert call.arguments["data"]["title"] == "Req-1"


def test_parse_command_streaming_message(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    settings.llm.stream = True

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple container
            def create(*, model, messages, tools=None, **kwargs):  # noqa: ANN001
                return [
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(
                                    content=[{"type": "text", "text": "Hel"}],
                                    tool_calls=None,
                                )
                            )
                        ]
                    ),
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(
                                    content=[{"type": "text", "text": "lo!"}],
                                    tool_calls=None,
                                )
                            )
                        ]
                    ),
                ]

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    response = client.parse_command("say hi")
    assert isinstance(response, LLMResponse)
    assert response.tool_calls == ()
    assert response.content == "Hello!"


def test_streaming_cancellation_closes_stream(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    settings.llm.stream = True

    class FakeStream:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.closed = threading.Event()
            self.allow = threading.Event()

        def __iter__(self):
            return self

        def __next__(self):
            self.started.set()
            while not self.closed.is_set():
                if self.allow.wait(0.05):
                    self.allow.clear()
                    break
            if self.closed.is_set():
                raise httpx.ReadError("closed", request=None)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        index=0,
                        delta=SimpleNamespace(
                            content=[{"type": "text", "text": "chunk"}],
                            tool_calls=None,
                        ),
                    )
                ]
            )

        def close(self) -> None:
            self.closed.set()
            self.allow.set()

    class FakeOpenAI:
        def __init__(self, *args, **kwargs):  # pragma: no cover - simple container
            self.stream = FakeStream()

            def create(**_kwargs):  # noqa: ANN001
                return self.stream

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    fake_client = client._client  # type: ignore[attr-defined]
    stream: FakeStream = fake_client.stream  # type: ignore[assignment]
    cancel_event = CancellationEvent()
    result: dict[str, object] = {}

    def target() -> None:
        try:
            client.respond([], cancellation=cancel_event)
        except Exception as exc:  # pragma: no cover - thread propagation
            result["exc"] = exc

    worker = threading.Thread(target=target)
    worker.start()

    assert stream.started.wait(1.0)
    cancel_event.set()
    stream.allow.set()
    worker.join(timeout=1.0)
    assert not worker.is_alive()

    assert stream.closed.is_set()
    assert isinstance(result.get("exc"), OperationCancelledError)


def test_streaming_truncation_returns_partial_message(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    settings.llm.stream = True

    class FakeStream:
        # This fake stream emits a single partial chunk and then simulates a dropped
        # connection.  The scenario documents why the client must surface the text
        # that already arrived: downstream agents rely on the partial statement to
        # decide whether a retry is necessary, and regressions in this behaviour
        # manifest exactly as the "empty message" errors observed in the field.
        def __init__(self) -> None:
            self.closed = False
            self.iteration = 0

        def __iter__(self):
            return self

        def __next__(self):
            if self.iteration == 0:
                self.iteration += 1
                return {
                    "choices": [
                        {
                            "delta": {
                                "content": [
                                    {"type": "text", "text": "partial"},
                                ]
                            },
                        }
                    ]
                }
            raise httpx.ReadError("connection dropped", request=None)

        def close(self) -> None:
            self.closed = True

    class FakeOpenAI:
        def __init__(self, *args, **kwargs):  # pragma: no cover - simple container
            self.stream = FakeStream()

            def create(**_kwargs):  # noqa: ANN001
                return self.stream

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    fake_client = client._client  # type: ignore[attr-defined]
    stream: FakeStream = fake_client.stream  # type: ignore[assignment]

    response = client.respond([])

    assert response.content == "partial"
    assert response.tool_calls == ()
    assert stream.closed is True


def test_parse_command_trims_history_by_tokens(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    captured: dict[str, object] = {}
    logged_events: list[tuple[str, dict[str, object]]] = []

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple container
            def create(*, model, messages, **kwargs):  # noqa: ANN001
                captured["messages"] = messages
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        function=SimpleNamespace(
                                            name="list_requirements",
                                            arguments="{}",
                                        )
                                    )
                                ]
                            )
                        )
                    ]
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    monkeypatch.setattr(
        "app.llm.request_builder.LLMRequestBuilder._resolved_max_context_tokens",
        lambda self: 4,
    )
    monkeypatch.setattr(
        "app.llm.request_builder.LLMRequestBuilder._count_tokens",
        lambda self, text: 1 if text else 0,
    )
    
    def fake_log_event(
        event: str,
        payload: dict[str, object] | None = None,
        *,
        start_time: float | None = None,
    ) -> None:
        logged_events.append((event, dict(payload or {})))

    monkeypatch.setattr("app.llm.request_builder.log_event", fake_log_event)
    client = LLMClient(settings.llm)
    history = [
        {"role": "user", "content": "h1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "h2"},
        {"role": "assistant", "content": "a2"},
    ]
    response = client.parse_command("latest", history=history)
    assert isinstance(response, LLMResponse)
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.name == "list_requirements"
    assert call.arguments == {}
    messages = captured["messages"]
    # With the patched token counter each message costs 1 token. Limit reserves
    # 2 tokens for system prompt and current user message, leaving room for two
    # entries from history.
    assert messages[1:-1] == [
        {"role": "user", "content": "h2"},
        {"role": "assistant", "content": "a2"},
    ]

    trim_payloads = [payload for event, payload in logged_events if event == "LLM_CONTEXT_TRIMMED"]
    assert len(trim_payloads) == 1
    payload = trim_payloads[0]
    assert payload == {
        "dropped_messages": 2,
        "dropped_tokens": 2,
        "history_messages_before": 5,
        "history_messages_after": 3,
        "history_tokens_before": 5,
        "history_tokens_after": 3,
        "max_context_tokens": 4,
        "system_prompt_tokens": 1,
        "history_token_budget": 3,
    }


def test_respond_preserves_context_for_update(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple container
            def create(*, model, messages, tools=None, **kwargs):  # noqa: ANN001
                captured["messages"] = messages
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        function=SimpleNamespace(
                                            name="update_requirement_field",
                                            arguments=json.dumps(
                                                {
                                                    "rid": "SYS-1",
                                                    "field": "statement",
                                                    "value": "Updated",
                                                }
                                            ),
                                        ),
                                        id="call-0",
                                    )
                                ]
                            )
                        )
                    ]
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    conversation = [
        {
            "role": "system",
            "content": (
                "[Workspace context]\n"
                "Active requirements list: SYS — System Requirements\n"
                "Selected requirement RIDs: SYS-1"
            ),
        },
        {
            "role": "user",
            "content": "add more information to this requirement text",
        },
    ]

    response = client.respond(conversation)
    assert isinstance(response, LLMResponse)
    assert response.tool_calls
    tool_call = response.tool_calls[0]
    assert tool_call.name == "update_requirement_field"
    assert tool_call.arguments == {
        "rid": "SYS-1",
        "field": "statement",
        "value": "Updated",
    }

    messages = captured["messages"]
    system_messages = [msg for msg in messages if msg.get("role") == "system"]
    assert len(system_messages) == 1
    system_content = system_messages[0].get("content", "")
    assert "Analyse the user's intent" in system_content
    assert "Selected requirement RIDs:" in system_content
    assert "SYS-1" in system_content
    assert "GUI selection #" not in system_content
    assert "(id=" not in system_content



def test_respond_preserves_context_for_delete(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple container
            def create(*, model, messages, tools=None, **kwargs):  # noqa: ANN001
                captured["messages"] = messages
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        function=SimpleNamespace(
                                            name="delete_requirement",
                                            arguments=json.dumps({"rid": "SYS-2"}),
                                        ),
                                        id="call-0",
                                    ),
                                    SimpleNamespace(
                                        function=SimpleNamespace(
                                            name="delete_requirement",
                                            arguments=json.dumps({"rid": "SYS-3"}),
                                        ),
                                        id="call-1",
                                    ),
                                ]
                            )
                        )
                    ]
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    conversation = [
        {
            "role": "system",
            "content": (
                "[Workspace context]\n"
                "Active requirements list: SYS — System Requirements\n"
                "Selected requirement RIDs: SYS-2, SYS-3"
            ),
        },
        {"role": "user", "content": "delete these requirements"},
    ]

    response = client.respond(conversation)
    assert isinstance(response, LLMResponse)
    assert len(response.tool_calls) == 2
    assert {call.name for call in response.tool_calls} == {"delete_requirement"}
    ids = {call.arguments["rid"] for call in response.tool_calls}
    assert ids == {"SYS-2", "SYS-3"}

    messages = captured["messages"]
    system_messages = [msg for msg in messages if msg.get("role") == "system"]
    assert len(system_messages) == 1
    system_content = system_messages[0].get("content", "")
    assert "Analyse the user's intent" in system_content
    assert "Selected requirement RIDs:" in system_content
    assert "SYS-2" in system_content
    assert "SYS-3" in system_content
    assert "GUI selection #" not in system_content
    assert "prefix=" not in system_content
def test_check_llm_async_uses_thread(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    captured: dict[str, object] = {}
    main_thread = threading.get_ident()

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple container
            def create(*, model, messages, **kwargs):  # noqa: ANN001
                captured.update(kwargs)
                captured["thread"] = threading.get_ident()
                return SimpleNamespace()

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    result = asyncio.run(client.check_llm_async())
    assert result == {"ok": True}
    assert captured["thread"] != main_thread


def test_parse_command_async(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    responses = {"anything": ("list_requirements", {"per_page": 2})}
    monkeypatch.setattr("openai.OpenAI", make_openai_mock(responses))
    client = LLMClient(settings.llm)
    history = [{"role": "user", "content": "earlier"}]
    response = asyncio.run(
        client.parse_command_async("anything", history=history)
    )
    assert isinstance(response, LLMResponse)
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.name == "list_requirements"
    assert call.arguments == {"per_page": 2}


def test_respond_accepts_tool_history(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple container
            def create(*, model, messages, tools=None, **kwargs):  # noqa: ANN001
                captured["messages"] = messages
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                tool_calls=None,
                                content="Done",
                            )
                        )
                    ]
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    conversation = [
        {"role": "user", "content": "list"},
        {
            "role": "assistant",
            "content": " ",
            "tool_calls": [
                {
                    "id": "call-0",
                    "type": "function",
                    "function": {
                        "name": "list_requirements",
                        "arguments": json.dumps({"per_page": 1}),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-0",
            "name": "list_requirements",
            "content": json.dumps({"ok": True, "result": []}),
        },
    ]
    response = client.respond(conversation)
    assert isinstance(response, LLMResponse)
    assert response.content == "Done"
    messages = captured["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"].startswith(SYSTEM_PROMPT)
    assert messages[1:] == [
        {"role": "user", "content": "list"},
        {
            "role": "assistant",
            "content": " ",
            "tool_calls": [
                {
                    "id": "call-0",
                    "type": "function",
                    "function": {
                        "name": "list_requirements",
                        "arguments": json.dumps({"per_page": 1}),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-0",
            "name": "list_requirements",
            "content": json.dumps({"ok": True, "result": []}),
        },
    ]


def test_harmony_prompt_includes_tools(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path, message_format="harmony")
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, *a, **k) -> None:  # pragma: no cover - simple capture
            def create(
                *, model, input, tools, reasoning, temperature=None, **kwargs
            ):  # noqa: ANN001
                captured["model"] = model
                captured["input"] = input
                captured["temperature"] = temperature
                captured["tools"] = tools
                captured["reasoning"] = reasoning
                captured["kwargs"] = kwargs
                return SimpleNamespace(
                    output=[
                        SimpleNamespace(
                            type="message",
                            content=[
                                SimpleNamespace(type="output_text", text="done")
                            ],
                        )
                    ]
                )

            self.responses = SimpleNamespace(create=create)
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: SimpleNamespace())
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    response = client.parse_command("ping")
    prompt = captured["input"]
    assert isinstance(prompt, str)
    assert prompt.strip().startswith("<|start|>system<|message|")
    assert "# Instructions" in prompt
    assert "namespace functions" in prompt
    assert prompt.strip().endswith("<|start|>assistant")
    assert captured["tools"] == convert_tools_for_harmony(TOOLS)
    assert captured["temperature"] is None
    assert "temperature" not in captured["kwargs"]
    assert response.content == "done"
    assert response.tool_calls == ()


def test_harmony_function_call_parsing(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path, message_format="harmony")

    class FakeOpenAI:
        def __init__(self, *a, **k) -> None:  # pragma: no cover - simple capture
            def create(**kwargs):  # noqa: ANN001
                return SimpleNamespace(
                    output=[
                        SimpleNamespace(
                            type="function_call",
                            name="list_requirements",
                            arguments="{\"page\": 1}",
                            id="call-1",
                        )
                    ]
                )

            self.responses = SimpleNamespace(create=create)
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: SimpleNamespace())
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    response = client.parse_command("list requirements")
    assert response.content == ""
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.name == "list_requirements"
    assert call.arguments == {"page": 1}


def test_harmony_streaming(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path, message_format="harmony")
    settings.llm.stream = True

    captured: dict[str, object] = {}

    class DummyStream:
        def __init__(self, events: list[object], final_response: object) -> None:
            self._events = iter(events)
            self._final_response = final_response
            self._closed = False

        def __iter__(self):
            return self

        def __next__(self):
            return next(self._events)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            self.close()

        def close(self) -> None:
            self._closed = True

        def until_done(self):  # pragma: no cover - compatibility with OpenAI stream
            try:
                while True:
                    next(self)
            except StopIteration:
                pass
            return self

        def get_final_response(self):
            self.until_done()
            return self._final_response

    class FakeOpenAI:
        def __init__(self, *a, **k) -> None:  # pragma: no cover - simple capture
            def stream(**kwargs):  # noqa: ANN001
                captured.update(kwargs)
                events: list[object] = [object(), object()]
                final = SimpleNamespace(
                    output=[
                        SimpleNamespace(
                            type="function_call",
                            name="list_requirements",
                            arguments="{\"page\": 2}",
                            id="call-42",
                        ),
                        SimpleNamespace(
                            type="message",
                            content=[
                                SimpleNamespace(type="output_text", text="done")
                            ],
                        ),
                    ]
                )
                return DummyStream(events, final)

            def create(**kwargs):  # noqa: ANN001
                raise AssertionError("Harmony streaming should not fall back to blocking create")

            self.responses = SimpleNamespace(stream=stream, create=create)
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: SimpleNamespace())
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    response = client.parse_command("streamed request")
    assert captured["model"] == settings.llm.model
    assert captured["input"]
    assert response.content == "done"
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.id == "call-42"
    assert call.name == "list_requirements"
    assert call.arguments == {"page": 2}

def test_respond_infers_selected_rids_for_get_requirement(
    tmp_path: Path, monkeypatch
) -> None:
    settings = settings_with_llm(tmp_path)

    class FakeOpenAI:
        def __init__(self, *args, **kwargs) -> None:  # noqa: D401 - simple stub
            def create(*, model, messages, tools=None, **_):  # noqa: ANN001
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content="",
                                tool_calls=[
                                    SimpleNamespace(
                                        id="call-0",
                                        function=SimpleNamespace(
                                            name="get_requirement",
                                            arguments="{}",
                                        ),
                                    )
                                ],
                            )
                        )
                    ]
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    conversation = [
        {
            "role": "system",
            "content": (
                "[Workspace context]\nSelected requirement RIDs: SYS7, SYS8"
            ),
        },
        {"role": "user", "content": "translate"},
    ]

    response = client.respond(conversation)

    assert response.tool_calls
    assert response.tool_calls[0].name == "get_requirement"
    assert response.tool_calls[0].arguments["rid"] == ["SYS7", "SYS8"]
