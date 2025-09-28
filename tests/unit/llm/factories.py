"""Factories for stubbing LLM request/response components in tests."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from app.llm.request_builder import PreparedChatRequest
from app.llm.types import LLMResponse


@dataclass
class DummyChatRequest:
    """Pre-baked chat request returning a static response."""

    request_args: dict[str, Any]
    snapshot: tuple[Mapping[str, Any], ...]


class DummyRequestBuilder:
    """Minimal implementation of :class:`LLMRequestBuilder` for tests."""

    def __init__(self, settings: Any, message_format: str) -> None:
        self.settings = settings
        self.message_format = message_format

    def resolve_temperature(self) -> None:
        return None

    def build_chat_request(
        self,
        conversation: Sequence[Mapping[str, Any]] | None,
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        stream: bool = False,
        temperature: float | None = None,
    ) -> PreparedChatRequest:
        return PreparedChatRequest(
            messages=list(conversation or []),
            snapshot=tuple(conversation or ()),
            request_args={
                "model": getattr(self.settings, "model", "dummy"),
                "messages": list(conversation or []),
                "tools": tools,
                "stream": stream,
                "temperature": temperature,
            },
        )

    def build_harmony_prompt(self, conversation: Sequence[Mapping[str, Any]]):
        return SimpleNamespace(prompt="", snapshot=lambda: tuple(conversation or ()))


class DummyResponseParser:
    """Minimal implementation of :class:`LLMResponseParser` for tests."""

    def __init__(self, settings: Any, message_format: str) -> None:
        self.settings = settings
        self.message_format = message_format

    def consume_stream(self, stream, *, cancellation=None):  # noqa: ANN001
        return "", [], []

    def parse_chat_completion(self, completion):  # noqa: ANN001
        return "", [], []

    def parse_harmony_output(self, completion):  # noqa: ANN001
        return "", []

    def parse_tool_calls(self, tool_calls):  # noqa: ANN001
        return ()

    def finalize_reasoning_segments(self, segments):  # noqa: ANN001
        return ()


def dummy_llm_response(text: str = "", *, tool_calls: Sequence[Any] = ()) -> LLMResponse:
    """Return a synthetic :class:`LLMResponse` for unit tests."""

    return LLMResponse(content=text, tool_calls=tuple(tool_calls))
