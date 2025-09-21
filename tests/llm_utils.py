"""Utilities for LLM-related tests."""

import json
import os
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest

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

    ``responses`` — словарь ``{prompt: sequence}``, где элементами
    последовательности могут быть кортежи ``(tool, args)``, строки (как
    свободный ответ ассистента), словари ``{"message": "..."}`` или
    исключения. При вызове ``chat.completions.create`` будет найден последний
    пользовательский промпт и взят следующий ответ из очереди. Если ответы
    закончились, используется последнее значение. Исключения пробрасываются
    напрямую. Формат результата соответствует минимальному подмножеству
    OpenAI, используемому в ``LLMClient``. Такой мок можно переиспользовать в
    других тестах:

    >>> mapping = {"list": [("list_requirements", {"per_page": 1}), {"message": "готово"}]}
    >>> monkeypatch.setattr("openai.OpenAI", make_openai_mock(mapping))

    Это позволит детерминированно эмулировать ответ LLM без сетевых
    запросов. Для простых ping-запросов достаточно указать ключ ``"ping"``
    c произвольным значением, например ``("noop", {})``. Если подходящего
    ключа нет, мок возвращает валидный по MCP контракту вызов
    ``list_requirements`` с пустыми аргументами.
    """

    prepared: dict[str, list[object]] = {}
    for key, value in responses.items():
        if isinstance(value, list):
            prepared[key] = list(value)
        else:
            prepared[key] = [value]

    class _Completions:
        def create(self, *, model, messages, tools=None, **kwargs):
            user_msg = next(
                (
                    msg["content"]
                    for msg in reversed(messages)
                    if msg.get("role") == "user"
                ),
                messages[-1]["content"],
            )
            queue = prepared.get(user_msg)
            if queue is None:
                queue = prepared.setdefault(user_msg, [("list_requirements", {})])
            if len(queue) > 1:
                result = queue.pop(0)
            else:
                result = queue[0]
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


def settings_with_llm(tmp_path: Path, *, api_key: str = "dummy") -> AppSettings:
    """Persist LLM settings with *api_key* to a file and load them."""
    data = {
        "llm": {
            "base_url": "https://openrouter.ai/api/v1",
            "model": "qwen/qwen3-4b:free",
            "api_key": api_key,
            "max_retries": 3,
            "timeout_minutes": 60,
            "stream": False,
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
            "base_url": "https://openrouter.ai/api/v1",
            "model": "qwen/qwen3-4b:free",
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
