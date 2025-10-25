"""Utilities for LLM-related tests."""

import json
import os
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.llm.constants import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL
from app.settings import AppSettings, load_app_settings


def require_real_llm_tests_flag(*, env_var: str = "COOKAREQ_RUN_REAL_LLM_TESTS") -> None:
    """Ensure the opt-in flag for real LLM tests is present or skip.

    ``pytest.skip`` is raised when the environment variable designated by
    ``env_var`` is absent or false-y, guaranteeing consistent behaviour across
    tests and fixtures that depend on the real LLM backend.
    """

    if os.getenv(env_var):
        return
    pytest.skip(
        "Set COOKAREQ_RUN_REAL_LLM_TESTS=1 to run tests hitting real LLM",
    )


def make_openai_mock(responses: dict[str, object]):
    """Return a ``FakeOpenAI`` class wired with *responses*.

    ``responses`` is a mapping ``{prompt: sequence}`` where each sequence entry
    can be a ``(tool, args)`` tuple, a string (representing a free-form assistant
    reply), a dictionary ``{"message": "..."}``, or an exception. When
    ``chat.completions.create`` is called, the helper finds the latest user
    prompt and consumes the next entry from the queue. Once responses run out,
    the last value is reused. Exceptions are raised as-is. The returned payload
    mirrors the minimal subset of OpenAI fields consumed by ``LLMClient``. The
    mock can be reused across tests:

    >>> mapping = {"list": [("list_requirements", {"prefix": "SYS", "per_page": 1}), {"message": "done"}]}
    >>> monkeypatch.setattr("openai.OpenAI", make_openai_mock(mapping))

    This makes it possible to emulate deterministic LLM replies without
    network traffic. For simple ping requests provide the ``"ping"`` key with
    any value, for example ``("noop", {})``. When a prompt is missing, the mock
    returns a contract-compliant ``list_requirements`` call with empty
    arguments.
    """

    prepared: dict[str, list[object]] = {}
    for key, value in responses.items():
        if isinstance(value, list):
            prepared[key] = list(value)
        else:
            prepared[key] = [value]

    def _content_to_text(content):
        if isinstance(content, str):
            return content
        if isinstance(content, Mapping):
            text_value = content.get("text")
            if isinstance(text_value, str):
                return text_value
            return _content_to_text(content.get("content"))
        if isinstance(content, list):
            return "".join(_content_to_text(part) for part in content)
        return str(content)

    class _Completions:
        def create(self, *, model, messages, tools=None, **kwargs):
            user_msg = next(
                (
                    _content_to_text(msg.get("content"))
                    for msg in reversed(messages)
                    if msg.get("role") == "user"
                ),
                _content_to_text(messages[-1].get("content")),
            )
            queue = prepared.get(user_msg)
            if queue is None:
                queue = prepared.setdefault(
                    user_msg, [("list_requirements", {"prefix": "SYS"})]
                )
            result = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(result, Exception):
                raise result
            if isinstance(result, str):
                message_content = result
                name = None
                args = {}
            elif isinstance(result, Mapping) and "message" in result:
                message_content = str(result["message"])
                name = None
                args = {}
            else:
                name, args = result
                message_content = None
            if tools:
                if name:
                    return SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(
                                    tool_calls=[
                                        SimpleNamespace(
                                            function=SimpleNamespace(
                                                name=name,
                                                arguments=json.dumps(args),
                                            ),
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    )
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                tool_calls=None,
                                content=message_content,
                            )
                        )
                    ]
                )
            return SimpleNamespace()

    class _Chat:
        def __init__(self) -> None:
            self.completions = _Completions()

    class FakeOpenAI:
        def __init__(self, *a, **k) -> None:  # pragma: no cover - simple container
            self.chat = _Chat()

    return FakeOpenAI


def settings_with_llm(
    tmp_path: Path,
    *,
    api_key: str = "dummy",
    message_format: str = "openai-chat",
    stream: bool = False,
) -> AppSettings:
    """Persist LLM settings with *api_key* to a file and load them."""
    data = {
        "llm": {
            "base_url": DEFAULT_LLM_BASE_URL,
            "model": DEFAULT_LLM_MODEL,
            "api_key": api_key,
            "max_retries": 3,
            "timeout_minutes": 60,
            "stream": stream,
            "message_format": message_format,
        },
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data))
    return load_app_settings(path)


def settings_with_mcp(
    host: str,
    port: int,
    base_path: str,
    token: str,
    *,
    tmp_path: Path,
    require_token: bool = False,
    fmt: str = "json",
    api_key: str = "dummy",
) -> AppSettings:
    """Return settings for LLM and MCP, persisted to a file.

    ``fmt`` controls the file format (``"json"`` or ``"toml"``).
    """

    settings = {
        "llm": {
            "base_url": DEFAULT_LLM_BASE_URL,
            "model": DEFAULT_LLM_MODEL,
            "api_key": api_key,
            "max_retries": 3,
            "timeout_minutes": 60,
            "stream": False,
        },
        "mcp": {
            "host": host,
            "port": port,
            "base_path": base_path,
            "require_token": require_token,
            "token": token,
        },
    }
    path = tmp_path / ("settings.toml" if fmt == "toml" else "settings.json")
    if fmt == "toml":
        toml = f"""
[llm]
base_url = \"{settings["llm"]["base_url"]}\"
model = \"{settings["llm"]["model"]}\"
api_key = \"{settings["llm"]["api_key"]}\"
max_retries = {settings["llm"]["max_retries"]}
timeout_minutes = {settings["llm"]["timeout_minutes"]}
stream = {str(settings["llm"]["stream"]).lower()}

[mcp]
host = \"{host}\"
port = {port}
base_path = \"{base_path}\"
require_token = {str(require_token).lower()}
token = \"{token}\"
"""
        path.write_text(toml)
    else:
        path.write_text(json.dumps(settings))
    return load_app_settings(path)
