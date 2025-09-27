"""Notification helpers for MCP tool results."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any
from collections.abc import Callable, Mapping, Sequence

logger = logging.getLogger("cookareq.mcp.events")


@dataclass(frozen=True)
class ToolResultEvent:
    """Payload describing successful MCP tool results."""

    base_path: Path | None
    payloads: tuple[Mapping[str, Any], ...]


_Listener = Callable[[ToolResultEvent], None]


class _ToolResultBus:
    """Thread-safe registry for MCP tool result listeners."""

    def __init__(self) -> None:
        self._listeners: set[_Listener] = set()
        self._lock = RLock()

    def add_listener(self, listener: _Listener) -> Callable[[], None]:
        """Register *listener* and return a callable removing it."""

        with self._lock:
            self._listeners.add(listener)

        def _remove() -> None:
            self.remove_listener(listener)

        return _remove

    def remove_listener(self, listener: _Listener) -> None:
        """Unregister *listener* ignoring unknown references."""

        with self._lock:
            self._listeners.discard(listener)

    def emit(self, event: ToolResultEvent) -> None:
        """Send *event* to all registered listeners."""

        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:  # pragma: no cover - defensive logging
                logger.exception("Tool result listener raised an exception")


_bus = _ToolResultBus()


def add_tool_result_listener(listener: _Listener) -> Callable[[], None]:
    """Register *listener* to receive :class:`ToolResultEvent` objects."""

    return _bus.add_listener(listener)


def remove_tool_result_listener(listener: _Listener) -> None:
    """Unregister *listener* from receiving tool result events."""

    _bus.remove_listener(listener)


def notify_tool_success(
    tool_name: str,
    *,
    base_path: str | Path | None,
    arguments: Mapping[str, Any] | None,
    result: Mapping[str, Any] | None,
) -> None:
    """Broadcast a successful tool invocation to registered listeners."""

    if not tool_name:
        return

    payload: dict[str, Any] = {
        "ok": True,
        "tool_name": tool_name,
    }
    if arguments is not None:
        try:
            payload["tool_arguments"] = dict(arguments)
        except Exception:  # pragma: no cover - defensive logging
            payload["tool_arguments"] = arguments
    if result is not None:
        try:
            payload["result"] = dict(result)
        except Exception:  # pragma: no cover - defensive logging
            payload["result"] = result
    event = ToolResultEvent(
        base_path=_normalise_base_path(base_path),
        payloads=(payload,),
    )
    _bus.emit(event)


def notify_tool_success_many(
    *,
    base_path: str | Path | None,
    payloads: Sequence[Mapping[str, Any]],
) -> None:
    """Broadcast pre-built payloads to registered listeners."""

    if not payloads:
        return
    event = ToolResultEvent(
        base_path=_normalise_base_path(base_path),
        payloads=tuple(payloads),
    )
    _bus.emit(event)


def _normalise_base_path(base_path: str | Path | None) -> Path | None:
    if base_path is None:
        return None
    try:
        text = str(base_path).strip()
        if not text:
            return None
        path = Path(text)
    except TypeError:
        return None
    try:
        return path.resolve()
    except OSError:
        return path
