"""State helpers for streamed tool result payloads."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


def _ensure_mapping(payload: Mapping[str, Any] | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        return dict(payload)
    return dict(payload)


def _normalise_timestamp(candidate: Any) -> str | None:
    if not isinstance(candidate, str):
        return None
    text = candidate.strip()
    return text or None


def _pick_timestamp(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        text = _normalise_timestamp(value)
        if text:
            return text
    return None


def _extract_call_identifier(payload: Mapping[str, Any]) -> str | None:
    for key in ("call_id", "tool_call_id"):
        value = payload.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
        elif value is not None:
            return str(value)
    return None


def _normalise_status_update_payload(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    status_value = payload.get("status") or payload.get("agent_status")
    if not isinstance(status_value, str):
        return None

    status_text = status_value.strip()
    if not status_text:
        return None

    prefix, separator, remainder = status_text.partition(":")
    status_label = prefix.strip() if separator else status_text
    message: str | None = remainder.strip() if separator else None

    if not message:
        fallback = payload.get("status_message") or payload.get("message")
        if isinstance(fallback, str):
            candidate = fallback.strip()
            if candidate:
                message = candidate

    if not message and status_label.lower() == "running":
        message = "Applying updates"

    timestamp: str | None = None
    for key in (
        "observed_at",
        "last_observed_at",
        "completed_at",
        "started_at",
        "first_observed_at",
    ):
        candidate = payload.get(key)
        if isinstance(candidate, str):
            text = candidate.strip()
            if text:
                timestamp = text
                break

    update: dict[str, Any] = {"raw": status_text, "status": status_label}
    if message:
        update["message"] = message
    if timestamp:
        update["at"] = timestamp
    return update


def _coerce_status_updates_list(candidate: Any) -> list[dict[str, Any]]:
    if isinstance(candidate, Mapping):
        return [dict(candidate)]
    if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes, bytearray)):
        updates: list[dict[str, Any]] = []
        for entry in candidate:
            if isinstance(entry, Mapping):
                updates.append(dict(entry))
        return updates
    return []


def _merge_status_update_lists(
    existing: Any,
    incoming: Any,
    fallback: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()

    def add(entry: Mapping[str, Any] | None) -> None:
        if not isinstance(entry, Mapping):
            return
        fingerprint = (
            entry.get("raw"),
            entry.get("at"),
            entry.get("status"),
        )
        if fingerprint in seen:
            return
        seen.add(fingerprint)
        merged.append(dict(entry))

    for item in _coerce_status_updates_list(existing):
        add(item)
    for item in _coerce_status_updates_list(incoming):
        add(item)
    add(fallback)
    return merged


def _should_mark_completed(payload: Mapping[str, Any]) -> bool:
    status_value = payload.get("agent_status") or payload.get("status")
    if isinstance(status_value, str) and status_value.strip().lower() in {
        "completed",
        "failed",
        "succeeded",
    }:
        return True
    ok_value = payload.get("ok")
    if isinstance(ok_value, bool):
        return True
    return False


@dataclass(slots=True)
class StreamedToolResultState:
    """Mutable state for a single streamed tool result."""

    call_id: str | None
    data: dict[str, Any] = field(default_factory=dict)
    first_observed_at: str | None = None
    last_observed_at: str | None = None
    completed_at: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "StreamedToolResultState":
        candidate = _ensure_mapping(payload)
        state = cls(call_id=_extract_call_identifier(candidate), data=candidate)
        fallback = _normalise_status_update_payload(candidate)
        incoming_updates = candidate.get("status_updates")
        updates = _merge_status_update_lists([], incoming_updates, fallback)
        if updates:
            state.data["status_updates"] = updates
        else:
            state.data.pop("status_updates", None)
        state._ingest_timestamps(candidate)
        state._finalise_timestamps()
        return state

    @classmethod
    def from_serialized(cls, payload: Mapping[str, Any]) -> "StreamedToolResultState":
        candidate = _ensure_mapping(payload)
        state = cls(call_id=_extract_call_identifier(candidate), data=candidate)
        updates = _coerce_status_updates_list(candidate.get("status_updates"))
        if updates:
            state.data["status_updates"] = updates
        else:
            state.data.pop("status_updates", None)
        state._ingest_timestamps(candidate, preserve_existing=True)
        state._finalise_timestamps()
        return state

    def merge_payload(self, payload: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping):
            return
        candidate = _ensure_mapping(payload)
        fallback = _normalise_status_update_payload(candidate)
        incoming_updates = candidate.get("status_updates")
        updates = _merge_status_update_lists(
            self.data.get("status_updates"), incoming_updates, fallback
        )
        candidate_without_status = dict(candidate)
        candidate_without_status.pop("status_updates", None)
        self.data.update(candidate_without_status)
        if updates:
            self.data["status_updates"] = updates
        else:
            self.data.pop("status_updates", None)
        self.call_id = _extract_call_identifier(self.data)
        self._ingest_timestamps(candidate)
        self._finalise_timestamps()

    def to_payload(self) -> dict[str, Any]:
        return dict(self.data)

    def _ingest_timestamps(
        self,
        payload: Mapping[str, Any],
        *,
        preserve_existing: bool = False,
    ) -> None:
        first_candidate = _pick_timestamp(
            payload, "first_observed_at", "started_at", "observed_at"
        )
        if first_candidate and (self.first_observed_at is None or not preserve_existing):
            if self.first_observed_at is None:
                self.first_observed_at = first_candidate
        elif self.first_observed_at is None:
            existing_first = _pick_timestamp(
                self.data, "first_observed_at", "started_at", "observed_at"
            )
            if existing_first:
                self.first_observed_at = existing_first

        last_candidate = _pick_timestamp(
            payload, "last_observed_at", "observed_at", "completed_at"
        )
        if last_candidate:
            self.last_observed_at = last_candidate
        elif self.last_observed_at is None:
            existing_last = _pick_timestamp(
                self.data, "last_observed_at", "observed_at", "completed_at"
            )
            if existing_last:
                self.last_observed_at = existing_last

        completed_candidate = _pick_timestamp(payload, "completed_at")
        if completed_candidate:
            self.completed_at = completed_candidate
        elif self.completed_at is None and _should_mark_completed(payload):
            completion_source = _pick_timestamp(
                payload, "completed_at", "last_observed_at", "observed_at"
            )
            if completion_source:
                self.completed_at = completion_source

        if self.first_observed_at and self.last_observed_at is None:
            self.last_observed_at = self.first_observed_at

    def _finalise_timestamps(self) -> None:
        if self.first_observed_at:
            self.data.setdefault("first_observed_at", self.first_observed_at)
            self.data.setdefault("started_at", self.first_observed_at)
        else:
            self.data.pop("first_observed_at", None)

        if self.last_observed_at:
            self.data["last_observed_at"] = self.last_observed_at
        else:
            self.data.pop("last_observed_at", None)

        if self.completed_at:
            self.data.setdefault("completed_at", self.completed_at)
        else:
            self.data.pop("completed_at", None)


__all__ = [
    "StreamedToolResultState",
]

