"""Data structures used by the chat UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
from uuid import uuid4

from ..llm.tokenizer import TokenCountResult, combine_token_counts
from ..util.time import utc_now_iso


@dataclass
class ChatEntry:
    """Stored request/response pair with supplementary metadata."""

    prompt: str
    response: str
    tokens: int
    display_response: str | None = None
    raw_result: Any | None = None
    tool_results: list[Any] | None = None
    token_info: TokenCountResult | None = None
    prompt_at: str | None = None
    response_at: str | None = None
    context_messages: tuple[dict[str, Any], ...] | None = None
    reasoning: tuple[dict[str, Any], ...] | None = None
    diagnostic: dict[str, Any] | None = None
    regenerated: bool = False
    layout_hints: dict[str, int] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:  # pragma: no cover - trivial
        if self.display_response is None:
            self.display_response = self.response
        if self.token_info is None:
            self.token_info = TokenCountResult.approximate(
                self.tokens,
                reason="legacy_tokens",
            )
        hints = self.layout_hints
        if not isinstance(hints, dict):
            self.layout_hints = {}
        else:
            sanitized: dict[str, int] = {}
            for key, value in hints.items():
                try:
                    width = int(value)
                except (TypeError, ValueError):
                    continue
                if width <= 0:
                    continue
                sanitized[str(key)] = width
            self.layout_hints = sanitized
        if self.context_messages is not None and not isinstance(
            self.context_messages, tuple
        ):
            normalized: list[dict[str, Any]] = []
            for message in self.context_messages:
                if isinstance(message, Mapping):
                    normalized.append(dict(message))
            self.context_messages = tuple(normalized) if normalized else None
        reasoning_raw = self.reasoning
        if reasoning_raw:
            if isinstance(reasoning_raw, Sequence) and not isinstance(
                reasoning_raw, (str, bytes, bytearray)
            ):
                iterable: Sequence[Any] = reasoning_raw
            else:
                iterable = (reasoning_raw,)
            normalised_segments: list[dict[str, Any]] = []
            for item in iterable:
                if isinstance(item, Mapping):
                    type_value = item.get("type")
                    text_value = item.get("text")
                else:
                    type_value = getattr(item, "type", None)
                    text_value = getattr(item, "text", None)
                if text_value is None:
                    continue
                text_str = str(text_value).strip()
                if not text_str:
                    continue
                type_str = str(type_value) if type_value is not None else ""
                normalised_segments.append({"type": type_str, "text": text_str})
            self.reasoning = tuple(normalised_segments) if normalised_segments else None
        else:
            self.reasoning = None

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
        token_info_raw = payload.get("token_info")
        token_info: TokenCountResult | None = None
        if isinstance(token_info_raw, Mapping):
            try:
                token_info = TokenCountResult.from_dict(token_info_raw)
            except Exception:  # pragma: no cover - defensive
                token_info = None
        if token_info is None and tokens:
            token_info = TokenCountResult.approximate(
                tokens,
                reason="legacy_tokens",
            )
        prompt_at_raw = payload.get("prompt_at")
        prompt_at = str(prompt_at_raw) if isinstance(prompt_at_raw, str) else None
        response_at_raw = payload.get("response_at")
        response_at = str(response_at_raw) if isinstance(response_at_raw, str) else None

        context_raw = payload.get("context_messages")
        context_messages: tuple[dict[str, Any], ...] | None = None
        if isinstance(context_raw, Sequence) and not isinstance(
            context_raw, (str, bytes, bytearray)
        ):
            prepared: list[dict[str, Any]] = []
            for item in context_raw:
                if isinstance(item, Mapping):
                    prepared.append(dict(item))
            if prepared:
                context_messages = tuple(prepared)

        reasoning_raw = payload.get("reasoning")
        reasoning: tuple[dict[str, Any], ...] | None = None
        if isinstance(reasoning_raw, Sequence) and not isinstance(
            reasoning_raw, (str, bytes, bytearray)
        ):
            prepared_reasoning: list[dict[str, Any]] = []
            for item in reasoning_raw:
                if not isinstance(item, Mapping):
                    continue
                text_value = item.get("text")
                if text_value is None:
                    continue
                text_str = str(text_value).strip()
                if not text_str:
                    continue
                type_value = item.get("type")
                type_str = str(type_value) if type_value is not None else ""
                prepared_reasoning.append({"type": type_str, "text": text_str})
            if prepared_reasoning:
                reasoning = tuple(prepared_reasoning)

        diagnostic_raw = payload.get("diagnostic")
        diagnostic: dict[str, Any] | None = None
        if isinstance(diagnostic_raw, Mapping):
            diagnostic = dict(diagnostic_raw)

        regenerated_raw = payload.get("regenerated")
        regenerated = bool(regenerated_raw) if isinstance(regenerated_raw, bool) else False

        return cls(
            prompt=prompt,
            response=response,
            tokens=tokens,
            display_response=display_response,
            raw_result=raw_result,
            tool_results=tool_results,
            token_info=token_info,
            prompt_at=prompt_at,
            response_at=response_at,
            context_messages=context_messages,
            reasoning=reasoning,
            diagnostic=diagnostic,
            regenerated=regenerated,
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
            "token_info": self.token_info.to_dict()
            if self.token_info is not None
            else None,
            "prompt_at": self.prompt_at,
            "response_at": self.response_at,
            "context_messages": [dict(message) for message in self.context_messages]
            if self.context_messages is not None
            else None,
            "reasoning": [dict(segment) for segment in self.reasoning]
            if self.reasoning is not None
            else None,
            "diagnostic": dict(self.diagnostic) if self.diagnostic is not None else None,
            "regenerated": self.regenerated,
        }


@dataclass
class ChatConversation:
    """Conversation consisting of ordered :class:`ChatEntry` items."""

    conversation_id: str
    title: str | None
    created_at: str
    updated_at: str
    entries: list[ChatEntry] = field(default_factory=list)

    @classmethod
    def new(cls) -> "ChatConversation":
        """Return empty conversation with generated identifiers."""

        now = utc_now_iso()
        return cls(
            conversation_id=str(uuid4()),
            title=None,
            created_at=now,
            updated_at=now,
            entries=[],
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ChatConversation":
        """Create :class:`ChatConversation` from stored mapping."""

        conversation_id_raw = payload.get("id") or payload.get("conversation_id")
        conversation_id = conversation_id_raw if isinstance(conversation_id_raw, str) else str(uuid4())

        title_raw = payload.get("title")
        title = str(title_raw) if isinstance(title_raw, str) else None
        if title == "":
            title = None

        created_at_raw = payload.get("created_at")
        created_at = created_at_raw if isinstance(created_at_raw, str) else utc_now_iso()

        updated_at_raw = payload.get("updated_at")
        updated_at = updated_at_raw if isinstance(updated_at_raw, str) else created_at

        entries_raw = payload.get("entries")
        entries: list[ChatEntry] = []
        if isinstance(entries_raw, Sequence):
            for item in entries_raw:
                if isinstance(item, Mapping):
                    try:
                        entries.append(ChatEntry.from_dict(item))
                    except Exception:  # pragma: no cover - defensive
                        continue

        conversation = cls(
            conversation_id=conversation_id,
            title=title,
            created_at=created_at,
            updated_at=updated_at,
            entries=entries,
        )
        conversation.ensure_title()
        return conversation

    def ensure_title(self) -> None:
        """Populate title from first prompt when unset."""

        if self.title:
            return
        derived = self.derive_title()
        if derived:
            self.title = derived

    def derive_title(self) -> str:
        """Generate human-friendly title from entries."""

        for entry in self.entries:
            candidate = entry.prompt.strip()
            if candidate:
                first_line = candidate.splitlines()[0]
                return first_line[:80]
        return ""

    def append_entry(self, entry: ChatEntry) -> None:
        """Add ``entry`` to the conversation and refresh metadata."""

        self.entries.append(entry)
        candidate = entry.response_at or entry.prompt_at
        if candidate:
            self.updated_at = candidate
        else:
            self.updated_at = utc_now_iso()
        if not self.title:
            self.ensure_title()

    def total_token_info(self) -> TokenCountResult:
        """Return aggregated token statistics for the conversation."""

        results: list[TokenCountResult] = []
        for item in self.entries:
            if item.token_info is not None:
                results.append(item.token_info)
            else:
                results.append(
                    TokenCountResult.approximate(
                        item.tokens,
                        reason="legacy_tokens",
                    )
                )
        return combine_token_counts(results)

    def total_tokens(self) -> int:
        """Return total token count across all entries."""

        return self.total_token_info().tokens or 0

    def to_dict(self) -> dict[str, Any]:
        """Return representation suitable for JSON storage."""

        return {
            "id": self.conversation_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "entries": [entry.to_dict() for entry in self.entries],
        }
