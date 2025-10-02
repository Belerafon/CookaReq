"""Helpers for reasoning-aware LLM responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .utils import extract_mapping

__all__ = [
    "REASONING_TYPE_ALIASES",
    "REASONING_KEYWORDS",
    "ReasoningFragment",
    "is_reasoning_type",
    "extract_reasoning_entries",
    "collect_reasoning_fragments",
    "normalise_reasoning_segments",
]


@dataclass(frozen=True, slots=True)
class ReasoningFragment:
    """Piece of reasoning text with edge whitespace preserved."""

    type: str
    text: str
    leading_whitespace: str
    trailing_whitespace: str

REASONING_TYPE_ALIASES = frozenset(
    {
        "analysis",
        "chain_of_thought",
        "internal_thought",
        "reason",
        "reasoning",
        "reflection",
        "thought",
        "thinking",
    }
)

REASONING_KEYWORDS = ("reason", "think", "analysis", "reflect")


def is_reasoning_type(value: Any) -> bool:
    """Return ``True`` when *value* denotes a reasoning segment."""

    if not isinstance(value, str):
        return False
    lowered = value.strip().lower()
    if not lowered:
        return False
    if lowered in REASONING_TYPE_ALIASES:
        return True
    return any(keyword in lowered for keyword in REASONING_KEYWORDS)


def extract_reasoning_entries(payload: Any) -> list[Mapping[str, Any]]:
    """Return flattened reasoning segments from *payload*."""

    if not payload:
        return []
    if isinstance(payload, (str, bytes, bytearray)):
        return []
    items = [payload] if isinstance(payload, Mapping) else list(payload)
    segments: list[Mapping[str, Any]] = []
    for item in items:
        mapping = extract_mapping(item)
        if not mapping:
            continue
        segments.append(mapping)
        nested = mapping.get("reasoning_content") or mapping.get("items")
        if nested:
            segments.extend(extract_reasoning_entries(nested))
    return segments


def collect_reasoning_fragments(payload: Any) -> list[ReasoningFragment]:
    """Return reasoning fragments with preserved edge whitespace."""

    fragments: list[ReasoningFragment] = []
    if not payload:
        return fragments

    def add_fragment(raw_type: Any, text: Any) -> None:
        if not text:
            return
        fragment_text = str(text)
        if not fragment_text:
            return
        stripped_text = fragment_text.strip()
        if not stripped_text:
            return
        fragment_type = str(raw_type or "reasoning")
        leading_length = len(fragment_text) - len(fragment_text.lstrip())
        trailing_length = len(fragment_text) - len(fragment_text.rstrip())
        leading = fragment_text[:leading_length]
        trailing = fragment_text[len(fragment_text) - trailing_length :]
        fragments.append(
            ReasoningFragment(
                type=fragment_type,
                text=stripped_text,
                leading_whitespace=leading,
                trailing_whitespace=trailing,
            )
        )

    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8", "ignore")
        except Exception:  # pragma: no cover - defensive
            return fragments

    mapping_candidate = extract_mapping(payload)
    if mapping_candidate and not isinstance(payload, Mapping):
        payload = mapping_candidate

    if isinstance(payload, str):
        add_fragment("reasoning", payload)
        return fragments

    if isinstance(payload, Mapping):
        item_type = payload.get("type")
        text_value = payload.get("text")
        if text_value is None:
            text_value = payload.get("summary")
        if text_value is None and isinstance(payload.get("content"), str):
            text_value = payload.get("content")
        add_fragment(item_type or "reasoning", text_value)
        for key in (
            "reasoning_content",
            "reasoning",
            "items",
            "entries",
            "details",
            "reasoning_details",
        ):
            nested = payload.get(key)
            if nested:
                fragments.extend(collect_reasoning_fragments(nested))
        content_value = payload.get("content")
        if content_value is not None and (
            not isinstance(item_type, str) or is_reasoning_type(item_type)
        ):
            fragments.extend(collect_reasoning_fragments(content_value))
        return fragments

    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        for item in payload:
            fragments.extend(collect_reasoning_fragments(item))
    return fragments


def normalise_reasoning_segments(payload: Any) -> list[dict[str, Any]]:
    """Return sanitized reasoning segments suitable for JSON payloads."""

    normalized: list[dict[str, Any]] = []
    if not payload:
        return normalized

    for fragment in collect_reasoning_fragments(payload):
        text_str = fragment.text
        if not text_str:
            continue
        type_candidate = fragment.type if fragment.type is not None else ""
        type_str = str(type_candidate).strip()
        if not type_str:
            type_str = "reasoning"
        entry: dict[str, Any] = {"type": type_str, "text": text_str}
        if fragment.leading_whitespace:
            entry["leading_whitespace"] = fragment.leading_whitespace
        if fragment.trailing_whitespace:
            entry["trailing_whitespace"] = fragment.trailing_whitespace
        normalized.append(entry)
    return normalized
