"""Utilities for LLM-related tests."""

import json
from pathlib import Path
from types import SimpleNamespace

from app.settings import AppSettings, load_app_settings


def make_openai_mock(responses: dict[str, tuple[str, dict] | Exception]):
    """Return a ``FakeOpenAI`` class wired with *responses*.

    ``responses`` — словарь ``{prompt: (tool, args) | Exception}``.
    При вызове ``chat.completions.create`` будет найден последний
    пользовательский промпт и возвращён подготовленный ответ. Если вместо
    пары передано исключение, оно будет возбуждёно. Формат результата
    соответствует минимальному подмножеству OpenAI, используемому в
    ``LLMClient``. Такой мок можно переиспользовать в других тестах:

    >>> mapping = {"list": ("list_requirements", {"per_page": 1})}
    >>> monkeypatch.setattr("openai.OpenAI", make_openai_mock(mapping))

    Это позволит детерминированно эмулировать ответ LLM без сетевых
    запросов. Для простых ping-запросов достаточно указать ключ ``"ping"``
    c произвольным значением, например ``("noop", {})``.
    """

    class _Completions:
        def create(self, *, model, messages, tools=None, **kwargs):  # noqa: D401
            user_msg = messages[-1]["content"]
            result = responses.get(user_msg, ("noop", {}))
            if isinstance(result, Exception):
                raise result
            name, args = result
            if tools:
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        function=SimpleNamespace(
                                            name=name,
                                            arguments=json.dumps(args),
                                        )
                                    )
                                ]
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
            "max_output_tokens": 0,
            "timeout_minutes": 60,
            "stream": False,
        }
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
            "max_output_tokens": 0,
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
base_url = \"{settings['llm']['base_url']}\"
model = \"{settings['llm']['model']}\"
api_key = \"{settings['llm']['api_key']}\"
max_retries = {settings['llm']['max_retries']}
max_output_tokens = {settings['llm']['max_output_tokens']}
timeout_minutes = {settings['llm']['timeout_minutes']}
stream = {str(settings['llm']['stream']).lower()}

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
