"""Data structures used by the chat UI."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar, cast
from collections.abc import Iterable, Mapping, Sequence
from uuid import uuid4

from ..agent.run_contract import (
    AgentRunPayload,
    ToolResultSnapshot,
    sort_tool_result_snapshots,
)
from ..agent.timeline_utils import assess_timeline_integrity
from ..llm.tokenizer import (
    TokenCountResult,
    combine_token_counts,
    count_text_tokens,
)
from ..util.json import make_json_safe
from ..util.time import utc_now_iso
from .agent_chat_panel.history_utils import (
    agent_payload_from_mapping,
    tool_messages_from_snapshots,
)
from .history_config import HISTORY_JSON_LIMITS

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


def _normalise_tool_results_payload(value: Any) -> list[dict[str, Any]]:
    """Convert *value* into deterministic tool snapshot payloads."""
    if value is None:
        return []
    if isinstance(value, Mapping):
        candidates: Sequence[Any] = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        candidates = value
    else:
        return []
    snapshots: list[ToolResultSnapshot] = []
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        try:
            snapshot = ToolResultSnapshot.from_dict(item)
        except Exception:
            continue
        snapshots.append(snapshot)
    if not snapshots:
        return []
    ordered_snapshots = sort_tool_result_snapshots(snapshots)
    return [snapshot.to_dict() for snapshot in ordered_snapshots]


def _parse_agent_run_payload(raw_result: Any) -> AgentRunPayload | None:
    if not isinstance(raw_result, Mapping):
        return None
    return agent_payload_from_mapping(raw_result)


def _strip_diagnostic_event_log(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    cleaned = {k: v for k, v in value.items() if k != "event_log"}
    return cleaned or None


def _normalise_timeline_status(value: Any) -> str:
    if isinstance(value, str):
        normalised = value.strip().lower()
        if normalised in {"valid", "damaged", "missing"}:
            return normalised
    return "unknown"


def _normalise_timeline_checksum(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _derive_tool_messages(raw_result: Any) -> tuple[dict[str, Any], ...]:
    payload = _parse_agent_run_payload(raw_result)
    if payload is not None:
        messages = tool_messages_from_snapshots(payload.tool_results)
        if messages:
            return messages

    if isinstance(raw_result, Mapping):
        tool_results = raw_result.get("tool_results")
        normalised_results = _normalise_tool_results_payload(tool_results)
        messages = tool_messages_from_snapshots(normalised_results)
        if messages:
            return messages

    return ()


@dataclass(frozen=True)
class EntryTokenCacheRecord:
    """Persisted token statistics for a chat entry component."""

    digest: str
    tokens: TokenCountResult

    def to_dict(self) -> dict[str, Any]:
        """Convert cache record to serialisable mapping."""
        return {"digest": self.digest, "tokens": self.tokens.to_dict()}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EntryTokenCacheRecord:
        """Create cache record from mapping raising for malformed payloads."""
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


_CACHE_INVALIDATING_FIELDS = {
    "prompt",
    "response",
    "display_response",
    "raw_result",
    "context_messages",
    "tool_messages",
    "reasoning",
    "diagnostic",
}


_CACHE_SENTINEL: object = object()
T = TypeVar("T")


def _history_json_safe(value: Any) -> Any:
    return make_json_safe(
        value,
        stringify_keys=True,
        sort_sets=False,
        coerce_sequences=True,
        default=str,
        limits=HISTORY_JSON_LIMITS,
    )


def _sanitize_for_history(
    sequence: Sequence[Mapping[str, Any]] | None,
) -> tuple[dict[str, Any], ...]:
    if not sequence:
        return ()
    sanitized: list[dict[str, Any]] = []
    for item in sequence:
        safe_item = _history_json_safe(item)
        if isinstance(safe_item, Mapping):
            sanitized.append(dict(safe_item))
    return tuple(sanitized)


@dataclass
class ChatEntry:
    """Stored request/response pair with supplementary metadata."""

    prompt: str
    response: str
    tokens: int
    display_response: str | None = None
    raw_result: Any | None = None
    token_info: TokenCountResult | None = None
    prompt_at: str | None = None
    response_at: str | None = None
    context_messages: tuple[dict[str, Any], ...] | None = None
    tool_messages: tuple[dict[str, Any], ...] | None = None
    reasoning: tuple[dict[str, Any], ...] | None = None
    diagnostic: dict[str, Any] | None = None
    regenerated: bool = False
    timeline_status: str = "unknown"
    timeline_checksum: str | None = None
    layout_hints: dict[str, int] = field(default_factory=dict, repr=False, compare=False)
    token_cache: dict[str, dict[str, EntryTokenCacheRecord]] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    def __setattr__(self, key: str, value: Any) -> None:  # pragma: no cover - hot path
        object.__setattr__(self, key, value)
        if key in _CACHE_INVALIDATING_FIELDS:
            self._reset_view_cache()

    def __post_init__(self) -> None:
        """Normalise derived fields and cached token metadata."""

        if self.display_response is None:
            self.display_response = self.response
        self.timeline_status = _normalise_timeline_status(self.timeline_status)
        self.timeline_checksum = _normalise_timeline_checksum(self.timeline_checksum)
        self.ensure_token_info()
        payload = _parse_agent_run_payload(self.raw_result)
        self._update_timeline_metadata(payload)
        if payload is not None:
            if payload.timeline_checksum is None:
                payload.timeline_checksum = self.timeline_checksum
            self.raw_result = payload.to_history_dict()
            if not self.reasoning and payload.reasoning:
                self.reasoning = tuple(dict(segment) for segment in payload.reasoning)
            diagnostic = _strip_diagnostic_event_log(self.diagnostic)
            self.diagnostic = diagnostic
        if isinstance(self.raw_result, Mapping):
            updated = dict(self.raw_result)
            diagnostic_raw = updated.get("diagnostic")
            cleaned_diagnostic = _strip_diagnostic_event_log(diagnostic_raw)
            if cleaned_diagnostic is None:
                updated.pop("diagnostic", None)
            else:
                updated["diagnostic"] = cleaned_diagnostic
            tool_results_raw = updated.get("tool_results")
            normalised_results = _normalise_tool_results_payload(tool_results_raw)
            if normalised_results:
                updated["tool_results"] = normalised_results
            else:
                updated.pop("tool_results", None)
            self.raw_result = updated
        tool_messages = self.tool_messages
        if tool_messages:
            if isinstance(tool_messages, Sequence) and not isinstance(
                tool_messages, (str, bytes, bytearray)
            ):
                iterable: Sequence[Any] = tool_messages
            else:
                iterable = (tool_messages,)
            normalised_messages: list[dict[str, Any]] = []
            for message in iterable:
                if not isinstance(message, Mapping):
                    continue
                role_value = message.get("role")
                role = str(role_value).strip() if role_value is not None else "tool"
                if not role:
                    role = "tool"
                content_value = message.get("content")
                content = str(content_value) if content_value is not None else ""
                tool_message: dict[str, Any] = {"role": role, "content": content}
                call_value = message.get("tool_call_id")
                if isinstance(call_value, str) and call_value.strip():
                    tool_message["tool_call_id"] = call_value.strip()
                name_value = message.get("name")
                if isinstance(name_value, str) and name_value.strip():
                    tool_message["name"] = name_value.strip()
                normalised_messages.append(tool_message)
            self.tool_messages = tuple(normalised_messages) if normalised_messages else None
        else:
            self.tool_messages = None
        if self.tool_messages is None:
            derived_tool_messages = _derive_tool_messages(self.raw_result)
            self.tool_messages = derived_tool_messages or None
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
                    leading_value = item.get("leading_whitespace")
                    trailing_value = item.get("trailing_whitespace")
                else:
                    type_value = getattr(item, "type", None)
                    text_value = getattr(item, "text", None)
                    leading_value = getattr(item, "leading_whitespace", "")
                    trailing_value = getattr(item, "trailing_whitespace", "")
                if text_value is None:
                    continue
                text_str = str(text_value).strip()
                if not text_str:
                    continue
                type_str = str(type_value) if type_value is not None else ""
                segment: dict[str, str] = {"type": type_str, "text": text_str}
                if leading_value is not None:
                    leading_str = str(leading_value)
                    if leading_str:
                        segment["leading_whitespace"] = leading_str
                if trailing_value is not None:
                    trailing_str = str(trailing_value)
                    if trailing_str:
                        segment["trailing_whitespace"] = trailing_str
                normalised_segments.append(segment)
            self.reasoning = tuple(normalised_segments) if normalised_segments else None
        else:
            self.reasoning = None

    def _update_timeline_metadata(self, payload: AgentRunPayload | None) -> None:
        prior_status = _normalise_timeline_status(self.timeline_status)
        prior_checksum = _normalise_timeline_checksum(self.timeline_checksum)

        if payload is None:
            self.timeline_status = (
                prior_status if prior_status in {"missing", "damaged"} else "missing"
            )
            self.timeline_checksum = prior_checksum
            self._sanitize_token_cache()
            self._reset_view_cache()
            return

        declared_checksum = payload.timeline_checksum or prior_checksum
        integrity = assess_timeline_integrity(
            payload.timeline, declared_checksum=declared_checksum
        )
        status = integrity.status
        if prior_status in {"missing", "damaged"} and status == "valid":
            status = prior_status
        checksum = integrity.checksum or declared_checksum

        self.timeline_status = status
        self.timeline_checksum = checksum
        self._sanitize_token_cache()
        self._reset_view_cache()

    def refresh_timeline_metadata(self) -> None:
        """Recompute timeline status/checksum based on current raw payload."""
        self.timeline_status = "unknown"
        self.timeline_checksum = None
        payload = _parse_agent_run_payload(self.raw_result)
        self._update_timeline_metadata(payload)

    def _reset_view_cache(self) -> None:
        cache = getattr(self, "_view_cache", None)
        if isinstance(cache, dict):
            cache.clear()
        else:
            object.__setattr__(self, "_view_cache", {})

    def _ensure_view_cache(self) -> dict[str, Any]:
        cache = getattr(self, "_view_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            object.__setattr__(self, "_view_cache", cache)
        return cache

    def cache_view_value(self, key: str, factory: Callable[[], T]) -> T:
        cache = self._ensure_view_cache()
        value = cache.get(key, _CACHE_SENTINEL)
        if value is _CACHE_SENTINEL:
            value = factory()
            cache[key] = value
        return cast(T, value)

    def history_safe_raw_result(self) -> Any:
        if self.raw_result is None:
            return None

        return self.cache_view_value(
            "history_raw_result",
            lambda: _history_json_safe(self.raw_result),
        )

    def sanitized_context_messages(self) -> tuple[dict[str, Any], ...]:
        return self.cache_view_value(
            "context_messages",
            lambda: _sanitize_for_history(self.context_messages),
        )

    def sanitized_reasoning_segments(self) -> tuple[dict[str, Any], ...]:
        return self.cache_view_value(
            "reasoning_segments",
            lambda: _sanitize_for_history(self.reasoning),
        )

    @property
    def tool_results(self) -> list[dict[str, Any]] | None:
        """Return deterministic tool snapshots associated with this entry."""
        raw_result = self.raw_result
        if not isinstance(raw_result, Mapping):
            return None
        payload = raw_result.get("tool_results")
        normalised = _normalise_tool_results_payload(payload)
        if not normalised:
            if "tool_results" in raw_result:
                updated = dict(raw_result)
                updated.pop("tool_results", None)
                self.raw_result = updated
            return None
        if payload != normalised:
            updated = dict(raw_result)
            updated["tool_results"] = normalised
            self.raw_result = updated
        return normalised

    @tool_results.setter
    def tool_results(self, value: Sequence[Any] | None) -> None:
        if value is None:
            if isinstance(self.raw_result, Mapping):
                updated = dict(self.raw_result)
                updated.pop("tool_results", None)
                self.raw_result = updated
            return
        normalised = _normalise_tool_results_payload(value)
        if not normalised:
            if isinstance(self.raw_result, Mapping):
                updated = dict(self.raw_result)
                updated.pop("tool_results", None)
                self.raw_result = updated
            else:
                self.raw_result = None
            return
        base = dict(self.raw_result) if isinstance(self.raw_result, Mapping) else {}
        base["tool_results"] = normalised
        self.raw_result = base

    def ensure_tool_messages(self) -> tuple[dict[str, Any], ...] | None:
        """Return or derive tool messages associated with this entry."""

        if self.tool_messages is None:
            derived = _derive_tool_messages(self.raw_result)
            if derived:
                self.tool_messages = derived
        return self.tool_messages

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
        raw_result_payload = payload.get("raw_result")
        raw_result = (
            dict(raw_result_payload)
            if isinstance(raw_result_payload, Mapping)
            else raw_result_payload
        )
        parsed_payload = _parse_agent_run_payload(raw_result)
        if parsed_payload is not None:
            raw_result = parsed_payload.to_history_dict()
        tool_results_raw = payload.get("tool_results")
        if tool_results_raw is not None:
            normalised_results = _normalise_tool_results_payload(tool_results_raw)
            base = dict(raw_result) if isinstance(raw_result, Mapping) else {}
            if normalised_results:
                base["tool_results"] = normalised_results
            else:
                base.pop("tool_results", None)
            raw_result = base
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

        timeline_status = _normalise_timeline_status(payload.get("timeline_status"))
        timeline_checksum = _normalise_timeline_checksum(payload.get("timeline_checksum"))

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

        tool_messages: tuple[dict[str, Any], ...] | None = None

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
                segment: dict[str, str] = {"type": type_str, "text": text_str}
                leading_value = item.get("leading_whitespace")
                if leading_value is not None:
                    leading_str = str(leading_value)
                    if leading_str:
                        segment["leading_whitespace"] = leading_str
                trailing_value = item.get("trailing_whitespace")
                if trailing_value is not None:
                    trailing_str = str(trailing_value)
                    if trailing_str:
                        segment["trailing_whitespace"] = trailing_str
                prepared_reasoning.append(segment)
            if prepared_reasoning:
                reasoning = tuple(prepared_reasoning)
        elif parsed_payload is not None and parsed_payload.reasoning:
            reasoning = tuple(dict(segment) for segment in parsed_payload.reasoning)

        diagnostic_raw = payload.get("diagnostic")
        diagnostic: dict[str, Any] | None = None
        if isinstance(diagnostic_raw, Mapping):
            diagnostic = dict(diagnostic_raw)
        if parsed_payload is not None:
            diagnostic = _strip_diagnostic_event_log(diagnostic)

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
            token_info=token_info,
            prompt_at=prompt_at,
            response_at=response_at,
            context_messages=context_messages,
            tool_messages=tool_messages,
            reasoning=reasoning,
            diagnostic=diagnostic,
            regenerated=regenerated,
            timeline_status=timeline_status,
            timeline_checksum=timeline_checksum,
            token_cache=token_cache,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return representation suitable for JSON storage."""
        diagnostic = _strip_diagnostic_event_log(self.diagnostic)

        payload = {
            "prompt": self.prompt,
            "response": self.response,
            "tokens": self.tokens,
            "display_response": self.display_response,
            "raw_result": self.raw_result,
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
            "diagnostic": dict(diagnostic) if diagnostic is not None else None,
            "regenerated": self.regenerated,
            "timeline_status": self.timeline_status,
            "timeline_checksum": self.timeline_checksum,
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
    preview: str | None = None
    _entries: list[ChatEntry] = field(default_factory=list, repr=False, compare=False)
    _entries_loaded: bool = field(default=True, repr=False, compare=False)
    _entries_loader: Callable[[], Sequence[ChatEntry]] | None = field(
        default=None, repr=False, compare=False
    )

    @classmethod
    def new(cls) -> ChatConversation:
        """Return empty conversation with generated identifiers."""
        now = utc_now_iso()
        return cls(
            conversation_id=str(uuid4()),
            title=None,
            created_at=now,
            updated_at=now,
            preview=None,
            _entries=[],
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ChatConversation:
        """Create :class:`ChatConversation` from stored mapping."""
        conversation_id_raw = payload.get("id") or payload.get("conversation_id")
        conversation_id = (
            conversation_id_raw if isinstance(conversation_id_raw, str) else str(uuid4())
        )

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
            preview=payload.get("preview"),
            _entries=entries,
        )
        conversation.ensure_title()
        if conversation.preview is None:
            conversation.preview = conversation._derive_preview(entries)
        return conversation

    @property
    def entries(self) -> list[ChatEntry]:
        """Return in-memory chat entries, loading them if necessary."""
        return self._entries

    @entries.setter
    def entries(self, value: Iterable[ChatEntry]) -> None:
        self.replace_entries(value)

    @property
    def entries_loaded(self) -> bool:
        """Return ``True`` when entries have been materialised."""
        return self._entries_loaded

    def mark_entries_unloaded(
        self, loader: Callable[[], Sequence[ChatEntry]] | None = None
    ) -> None:
        """Drop cached entries and optionally provide deferred loader."""
        self._entries = []
        self._entries_loaded = False
        self._entries_loader = loader

    def ensure_entries_loaded(self) -> None:
        """Load entries using deferred loader when they are not available."""
        if self._entries_loaded:
            return
        loader = self._entries_loader
        if loader is None:
            entries: Sequence[ChatEntry] = []
        else:
            entries = loader()
        self._entries = list(entries)
        self._entries_loaded = True
        self.preview = self._derive_preview(self._entries)
        self._entries_loader = None

    def replace_entries(self, entries: Iterable[ChatEntry]) -> None:
        """Replace stored entries and refresh preview metadata."""
        self._entries = list(entries)
        self._entries_loaded = True
        self.preview = self._derive_preview(self._entries)
        self._entries_loader = None

    @classmethod
    def _derive_preview(cls, entries: Sequence[ChatEntry]) -> str | None:
        if not entries:
            return None
        for entry in reversed(entries):
            preview = cls._entry_preview(entry)
            if preview:
                return preview
        return None

    @staticmethod
    def _entry_preview(entry: ChatEntry) -> str | None:
        text = entry.prompt.strip()
        if not text:
            candidate = entry.display_response or entry.response
            text = candidate.strip() if isinstance(candidate, str) else ""
        if not text:
            return None
        normalised = " ".join(text.split())
        if len(normalised) > 80:
            normalised = normalised[:77] + "…"
        return normalised

    def ensure_title(self) -> None:
        """Populate title from first prompt when unset."""
        if self.title:
            return
        derived = self.derive_title()
        if derived:
            self.title = derived

    def derive_title(self) -> str:
        """Generate human-friendly title from entries."""
        self.ensure_entries_loaded()
        for entry in self._entries:
            candidate = entry.prompt.strip()
            if candidate:
                first_line = candidate.splitlines()[0]
                return first_line[:80]
        return ""

    def append_entry(self, entry: ChatEntry) -> None:
        """Add ``entry`` to the conversation and refresh metadata."""
        if not self._entries_loaded:
            self._entries = []
            self._entries_loaded = True
        self._entries.append(entry)
        candidate = entry.response_at or entry.prompt_at
        if candidate:
            self.updated_at = candidate
        else:
            self.updated_at = utc_now_iso()
        if not self.title:
            self.ensure_title()
        preview = self._entry_preview(entry)
        if preview:
            self.preview = preview

    def recalculate_preview(self) -> None:
        """Recompute preview text from the currently loaded entries."""
        self.ensure_entries_loaded()
        self.preview = self._derive_preview(self._entries)

    def total_token_info(self) -> TokenCountResult:
        """Return aggregated token statistics for the conversation."""
        self.ensure_entries_loaded()
        results: list[TokenCountResult] = []
        for item in self._entries:
            info = item.ensure_token_info()
            if info is not None:
                results.append(info)
        return combine_token_counts(results)

    def total_tokens(self) -> int:
        """Return total token count across all entries."""
        return self.total_token_info().tokens or 0

    def to_dict(self) -> dict[str, Any]:
        """Return representation suitable for JSON storage."""
        self.ensure_entries_loaded()
        return {
            "id": self.conversation_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "preview": self.preview,
            "entries": [entry.to_dict() for entry in self._entries],
        }
