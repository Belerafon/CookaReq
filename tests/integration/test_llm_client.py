"""Tests for llm client."""

import asyncio
import json
import logging
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
import httpx

from app.llm.client import LLMResponse, LLMToolCall, LLMClient, NO_API_KEY
from app.llm.validation import ToolValidationError
from app.llm.spec import SYSTEM_PROMPT
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
    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert messages[-1] == {"role": "user", "content": "follow up"}
    assert messages[1:-1] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "system", "content": "drop me"},
    ]


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
                                content="Привет",
                            ),
                        )
                    ]
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = LLMClient(settings.llm)
    response = client.parse_command("куку")
    assert isinstance(response, LLMResponse)
    assert response.tool_calls == ()
    assert response.content == "Привет"


def test_parse_command_reports_tool_validation_details(
    tmp_path: Path, monkeypatch
) -> None:
    settings = settings_with_llm(tmp_path)

    monkeypatch.setattr(
        "openai.OpenAI",
        make_openai_mock(
            {
                "Напиши текст первого требования": [
                    (
                        "create_requirement",
                        {"prefix": "SYS", "data": {"title": "Req-1"}},
                    )
                ]
            }
        ),
    )

    client = LLMClient(settings.llm)

    with pytest.raises(ToolValidationError) as excinfo:
        client.parse_command("Напиши текст первого требования")

    exc = excinfo.value
    assert hasattr(exc, "llm_tool_calls")
    assert exc.llm_tool_calls
    first_call = exc.llm_tool_calls[0]
    assert first_call["function"]["name"] == "create_requirement"
    arguments = json.loads(first_call["function"]["arguments"])
    assert arguments["data"]["title"] == "Req-1"


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
                                    content=[{"type": "text", "text": "Прив"}],
                                    tool_calls=None,
                                )
                            )
                        ]
                    ),
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(
                                    content=[{"type": "text", "text": "ет!"}],
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
    assert response.content == "Привет!"


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
    monkeypatch.setattr(LLMClient, "_resolved_max_context_tokens", lambda self: 4)
    monkeypatch.setattr(LLMClient, "_count_tokens", staticmethod(lambda text: 1 if text else 0))
    
    def fake_log_event(
        event: str,
        payload: dict[str, object] | None = None,
        *,
        start_time: float | None = None,
    ) -> None:
        logged_events.append((event, dict(payload or {})))

    monkeypatch.setattr("app.llm.client.log_event", fake_log_event)
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
                "Selected requirements (1):\n"
                "- GUI selection #1: requirement SYS-1 — Power control is currently highlighted in the graphical interface."
            ),
        },
        {
            "role": "user",
            "content": "впиши в текст этого требования дополнительную информацию",
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
    assert len(system_messages) >= 2
    assert any(
        "Selected requirements (1)" in msg.get("content", "")
        for msg in system_messages[1:]
    )
    assert any(
        "Selected requirement RID summary:" in msg.get("content", "")
        for msg in system_messages[1:]
    )
    assert all("(id=" not in msg.get("content", "") for msg in system_messages)


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
                "Selected requirements (2):\n"
                "- GUI selection #1: requirement SYS-2 — Secondary is currently highlighted in the graphical interface.\n"
                "- GUI selection #2: requirement SYS-3 — Legacy is currently highlighted in the graphical interface."
            ),
        },
        {"role": "user", "content": "удали эти требования"},
    ]

    response = client.respond(conversation)
    assert isinstance(response, LLMResponse)
    assert len(response.tool_calls) == 2
    assert {call.name for call in response.tool_calls} == {"delete_requirement"}
    ids = {call.arguments["rid"] for call in response.tool_calls}
    assert ids == {"SYS-2", "SYS-3"}

    messages = captured["messages"]
    system_messages = [msg for msg in messages if msg.get("role") == "system"]
    assert len(system_messages) >= 2
    assert any(
        "Selected requirements (2)" in msg.get("content", "")
        for msg in system_messages[1:]
    )
    assert any(
        "Selected requirement RID summary:" in msg.get("content", "")
        for msg in system_messages[1:]
    )
    assert all("prefix=" not in msg.get("content", "") for msg in system_messages)
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
                                content="Готово",
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
            "content": "",
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
    assert response.content == "Готово"
    messages = captured["messages"]
    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert messages[1:] == [
        {"role": "user", "content": "list"},
        {
            "role": "assistant",
            "content": "",
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
