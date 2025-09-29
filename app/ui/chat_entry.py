"""Data structures used by the chat UI."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Mapping, Sequence
from uuid import uuid4

from ..llm.tokenizer import (
    TokenCountResult,
    combine_token_counts,
    count_text_tokens,
)
from ..util.time import utc_now_iso


_DEFAULT_TOKEN_MODEL = "cl100k_base"
_DEFAULT_MODEL_KEY = "__default__"


def _normalise_model_key(model: str | None) -> str:
    text = (model or "").strip()
    return text if text else _DEFAULT_MODEL_KEY


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_context_messages(
    messages: Sequence[Mapping[str, Any]] | None,
) -> str:
    if not messages:
        return "empty"
    serialised: list[str] = []
    for message in messages:
        try:
            serialised.append(
                json.dumps(message, ensure_ascii=False, sort_keys=True)
            )
        except TypeError:
            fallback = {str(key): str(value) for key, value in message.items()}
            serialised.append(
                json.dumps(fallback, ensure_ascii=False, sort_keys=True)
            )
    blob = "\u241e".join(serialised)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EntryTokenCacheRecord:
    """Persisted token statistics for a chat entry component."""

    digest: str
    tokens: TokenCountResult

    def to_dict(self) -> dict[str, Any]:
        return {"digest": self.digest, "tokens": self.tokens.to_dict()}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EntryTokenCacheRecord:
        digest = payload.get("digest")
        if not isinstance(digest, str) or not digest:
            raise ValueError("missing digest in cached token payload")
        tokens_payload = payload.get("tokens")
        if not isinstance(tokens_payload, Mapping):
            raise ValueError("missing token info in cached token payload")
        tokens = TokenCountResult.from_dict(tokens_payload)
        return cls(digest=digest, tokens=tokens)


def _deserialize_token_cache(
    payload: Any,
) -> dict[str, dict[str, EntryTokenCacheRecord]]:
    """Return sanitised cache mapping from serialized representation."""

    if not isinstance(payload, Mapping):
        return {}
    cache: dict[str, dict[str, EntryTokenCacheRecord]] = {}
    for model_key, parts in payload.items():
        if not isinstance(model_key, str) or not isinstance(parts, Mapping):
            continue
        model_cache: dict[str, EntryTokenCacheRecord] = {}
        for part_name in ("prompt", "response", "context"):
            raw_part = parts.get(part_name)
            if not isinstance(raw_part, Mapping):
                continue
            try:
                record = EntryTokenCacheRecord.from_dict(raw_part)
            except Exception:
                continue
            model_cache[part_name] = record
        if model_cache:
            cache[model_key] = model_cache
    return cache


def count_context_message_tokens(
    message: Mapping[str, Any],
    model: str | None,
) -> TokenCountResult:
    """Return token usage for a single contextual message."""

    if not isinstance(message, Mapping):
        return TokenCountResult.exact(0, model=model)

    parts: list[TokenCountResult] = []
    role = message.get("role")
    if role:
        parts.append(count_text_tokens(str(role), model=model))
    name = message.get("name")
    if name:
        parts.append(count_text_tokens(str(name), model=model))

    content = message.get("content")
    if content not in (None, ""):
        if isinstance(content, str):
            content_text = content
        else:
            try:
                content_text = json.dumps(content, ensure_ascii=False)
            except Exception:
                content_text = str(content)
        parts.append(count_text_tokens(content_text, model=model))

    tool_calls = message.get("tool_calls")
    if tool_calls:
        try:
            serialized = json.dumps(tool_calls, ensure_ascii=False)
        except Exception:
            serialized = str(tool_calls)
        parts.append(count_text_tokens(serialized, model=model))

    if not parts:
        return TokenCountResult.exact(0, model=model)
    return combine_token_counts(parts)


def _recalculate_pair_token_info(prompt: str, response: str) -> TokenCountResult:
    """Return combined token statistics for *prompt* and *response*."""

    prompt_tokens = count_text_tokens(prompt, model=_DEFAULT_TOKEN_MODEL)
    response_tokens = count_text_tokens(response, model=_DEFAULT_TOKEN_MODEL)
    combined = combine_token_counts((prompt_tokens, response_tokens))
    model = combined.model or _DEFAULT_TOKEN_MODEL
    tokens = combined.tokens
    if tokens is None:
        return TokenCountResult.unavailable(model=model, reason=combined.reason)
    if combined.approximate:
        return TokenCountResult.approximate_result(
            tokens,
            model=model,
            reason=combined.reason,
        )
    return TokenCountResult.exact(tokens, model=model, reason=combined.reason)


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
    token_cache: dict[str, dict[str, EntryTokenCacheRecord]] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:  # pragma: no cover - trivial
        if self.display_response is None:
            self.display_response = self.response
        self.ensure_token_info()
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
        self._sanitize_token_cache()

    def _sanitize_token_cache(self) -> None:
        raw_cache = self.token_cache
        if isinstance(raw_cache, Mapping):
            sanitized = _deserialize_token_cache(raw_cache)
        else:
            sanitized = {}
        self.token_cache = sanitized

    def _cache_lookup(
        self,
        part: str,
        *,
        model: str | None,
        digest: str,
    ) -> TokenCountResult | None:
        model_key = _normalise_model_key(model)
        cache = self.token_cache.get(model_key)
        if not cache:
            return None
        record = cache.get(part)
        if record is None:
            return None
        if record.digest != digest:
            return None
        return record.tokens

    def _cache_store(
        self,
        part: str,
        *,
        model: str | None,
        digest: str,
        tokens: TokenCountResult,
    ) -> None:
        model_key = _normalise_model_key(model)
        cache = self.token_cache.setdefault(model_key, {})
        cache[part] = EntryTokenCacheRecord(digest=digest, tokens=tokens)

    def ensure_token_info(self, *, force: bool = False) -> TokenCountResult | None:
        """Ensure ``token_info`` reflects the current prompt/response text."""

        if force or self.token_info is None:
            self.token_info = _recalculate_pair_token_info(self.prompt, self.response)
        info = self.token_info
        if info is None:
            self.tokens = 0
            return None
        self.tokens = info.tokens or 0
        return info

    def ensure_prompt_token_usage(self, model: str | None) -> TokenCountResult:
        """Return token count for the prompt, caching the result."""

        text = self.prompt or ""
        digest = _hash_text(text)
        cached = self._cache_lookup("prompt", model=model, digest=digest)
        if cached is not None:
            return cached
        result = count_text_tokens(text, model=model)
        self._cache_store("prompt", model=model, digest=digest, tokens=result)
        return result

    def ensure_response_token_usage(self, model: str | None) -> TokenCountResult:
        """Return token count for the response, caching the result."""

        text = self.response or ""
        digest = _hash_text(text)
        cached = self._cache_lookup("response", model=model, digest=digest)
        if cached is not None:
            return cached
        result = count_text_tokens(text, model=model)
        self._cache_store("response", model=model, digest=digest, tokens=result)
        return result

    def ensure_context_token_usage(
        self,
        model: str | None,
        *,
        messages: tuple[dict[str, Any], ...] | None = None,
    ) -> TokenCountResult:
        """Return token count for contextual messages, caching the result."""

        if messages is None:
            messages = self.context_messages
        if not messages:
            return TokenCountResult.exact(0, model=model)
        digest = _hash_context_messages(messages)
        cached = self._cache_lookup("context", model=model, digest=digest)
        if cached is not None:
            return cached
        parts = [
            count_context_message_tokens(message, model)
            for message in messages
        ]
        combined = combine_token_counts(parts)
        if messages == self.context_messages:
            self._cache_store("context", model=model, digest=digest, tokens=combined)
        return combined

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ChatEntry:
        """Create :class:`ChatEntry` instance from stored mapping."""

        prompt = str(payload.get("prompt", ""))
        response = str(payload.get("response", ""))
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
        if not isinstance(token_info_raw, Mapping):
            raise ValueError("token_info field missing from chat entry payload")
        try:
            token_info = TokenCountResult.from_dict(token_info_raw)
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError("invalid token_info payload") from exc
        tokens = token_info.tokens or 0
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

        token_cache_raw = payload.get("token_cache")
        token_cache = _deserialize_token_cache(token_cache_raw)

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
            token_cache=token_cache,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return representation suitable for JSON storage."""

        payload = {
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
        cache_payload: dict[str, dict[str, Any]] = {}
        for model_key, parts in self.token_cache.items():
            if not isinstance(model_key, str) or not parts:
                continue
            part_payload: dict[str, Any] = {}
            for part_name, record in parts.items():
                if part_name not in {"prompt", "response", "context"}:
                    continue
                if not isinstance(record, EntryTokenCacheRecord):
                    continue
                part_payload[part_name] = record.to_dict()
            if part_payload:
                cache_payload[model_key] = part_payload
        payload["token_cache"] = cache_payload
        return payload


@dataclass
class ChatConversation:
    """Conversation consisting of ordered :class:`ChatEntry` items."""

    conversation_id: str
    title: str | None
    created_at: str
    updated_at: str
    entries: list[ChatEntry] = field(default_factory=list)

    @classmethod
    def new(cls) -> ChatConversation:
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
    def from_dict(cls, payload: Mapping[str, Any]) -> ChatConversation:
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
            info = item.ensure_token_info()
            if info is not None:
                results.append(info)
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
