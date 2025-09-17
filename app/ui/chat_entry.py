"""Data structures used by the chat UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass
class ChatEntry:
    """Stored request/response pair with supplementary metadata."""

    prompt: str
    response: str
    tokens: int
    display_response: str | None = None
    raw_result: Any | None = None
    tool_results: list[Any] | None = None

    def __post_init__(self) -> None:  # pragma: no cover - trivial
        if self.display_response is None:
            self.display_response = self.response

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ChatEntry":
        """Create :class:`ChatEntry` instance from stored mapping."""

        prompt = str(payload.get("prompt", ""))
        response = str(payload.get("response", ""))
        tokens_raw = payload.get("tokens", 0)
        try:
            tokens = int(tokens_raw)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            tokens = 0
        display_response = payload.get("display_response")
        if display_response is not None:
            display_response = str(display_response)
        raw_result = payload.get("raw_result")
        tool_results_raw = payload.get("tool_results")
        if isinstance(tool_results_raw, Sequence) and not isinstance(
            tool_results_raw, (str, bytes, bytearray)
        ):
            tool_results = list(tool_results_raw)
        else:
            tool_results = None
        return cls(
            prompt=prompt,
            response=response,
            tokens=tokens,
            display_response=display_response,
            raw_result=raw_result,
            tool_results=tool_results,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return representation suitable for JSON storage."""

        return {
            "prompt": self.prompt,
            "response": self.response,
            "tokens": self.tokens,
            "display_response": self.display_response,
            "raw_result": self.raw_result,
            "tool_results": self.tool_results,
        }
