"""Shared dataclasses for LLM client interactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

__all__ = [
    "LLMToolCall",
    "LLMReasoningSegment",
    "LLMResponse",
    "HistoryTrimResult",
]


@dataclass(frozen=True, slots=True)
class LLMToolCall:
    """Structured representation of an MCP tool invocation."""

    id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class LLMReasoningSegment:
    """Captured reasoning segment produced by the LLM."""

    type: str
    text: str
    leading_whitespace: str = ""
    trailing_whitespace: str = ""

    @property
    def text_with_whitespace(self) -> str:
        """Return ``text`` including preserved edge whitespace."""

        return f"{self.leading_whitespace}{self.text}{self.trailing_whitespace}"

    def preview(self, limit: int = 160) -> str:
        """Return a truncated representation retaining edge whitespace."""

        if limit <= 0:
            return ""
        return self.text_with_whitespace[:limit]


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Assistant message possibly containing tool calls."""

    content: str
    tool_calls: tuple[LLMToolCall, ...] = ()
    request_messages: tuple[Mapping[str, Any], ...] | None = None
    reasoning: tuple[LLMReasoningSegment, ...] = ()


@dataclass(frozen=True, slots=True)
class HistoryTrimResult:
    """Container describing the outcome of history trimming."""

    kept_messages: list[dict[str, Any]]
    dropped_messages: int
    dropped_tokens: int
    total_messages: int
    total_tokens: int
    kept_tokens: int
