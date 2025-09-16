"""Tests for llm client."""

import asyncio
import json
import logging
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.llm.client import NO_API_KEY, LLMClient
from app.llm.constants import DEFAULT_MAX_OUTPUT_TOKENS, MIN_MAX_OUTPUT_TOKENS
from app.llm.spec import SYSTEM_PROMPT
from app.log import logger
from app.mcp.server import JsonlHandler
from app.settings import LLMSettings
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
    assert req["payload"]["api_key"] == "[REDACTED]"
    assert res["payload"]["ok"] is True
    assert "timestamp" in req and "size_bytes" in req
    assert "duration_ms" in res


def test_check_llm_uses_configured_token_limit(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    settings.llm.max_output_tokens = MIN_MAX_OUTPUT_TOKENS + 512
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
    assert captured["max_output_tokens"] == MIN_MAX_OUTPUT_TOKENS + 512


def test_check_llm_uses_default_when_no_limit(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    settings.llm.max_output_tokens = 0
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
    assert captured["max_output_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS


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
    tool, args = client.parse_command("follow up", history=history)
    assert tool == "list_requirements"
    assert args == {}
    messages = captured["messages"]
    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert messages[-1] == {"role": "user", "content": "follow up"}
    assert messages[1:-1] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]


def test_parse_command_trims_history_by_tokens(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    captured: dict[str, object] = {}

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
    client = LLMClient(settings.llm)
    history = [
        {"role": "user", "content": "h1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "h2"},
        {"role": "assistant", "content": "a2"},
    ]
    tool, args = client.parse_command("latest", history=history)
    assert tool == "list_requirements"
    assert args == {}
    messages = captured["messages"]
    # With the patched token counter each message costs 1 token. Limit reserves
    # 2 tokens for system prompt and current user message, leaving room for two
    # entries from history.
    assert messages[1:-1] == [
        {"role": "user", "content": "h2"},
        {"role": "assistant", "content": "a2"},
    ]


def test_parse_command_uses_default_when_no_limit(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    settings.llm.max_output_tokens = None
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, *a, **k):  # pragma: no cover - simple container
            def create(*, model, messages, **kwargs):  # noqa: ANN001
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
    tool, args = client.parse_command("anything")
    assert tool == "list_requirements"
    assert args == {}
    assert captured["max_output_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS


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
    tool, args = asyncio.run(client.parse_command_async("anything", history=history))
    assert tool == "list_requirements"
    assert args == {"per_page": 2}
