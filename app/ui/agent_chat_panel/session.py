"""State management for the agent chat panel."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from contextlib import suppress
from typing import Any
import time

import wx

from .history import AgentChatHistory
from .token_usage import TokenCountResult


class SessionEvent:
    """Simple signal implementation for the session model."""

    __slots__ = ("_listeners",)

    def __init__(self) -> None:
        self._listeners: list[Callable[[Any], None]] = []

    def connect(self, callback: Callable[[Any], None]) -> None:
        self._listeners.append(callback)

    def disconnect(self, callback: Callable[[Any], None]) -> None:
        with suppress(ValueError):
            self._listeners.remove(callback)

    def emit(self, payload: Any) -> None:
        for listener in list(self._listeners):
            listener(payload)


@dataclass(slots=True)
class AgentChatSessionEvents:
    """Expose observable hooks for the session lifecycle."""

    running_changed: SessionEvent[bool]
    tokens_changed: SessionEvent[TokenCountResult]
    elapsed: SessionEvent[float]
    history_changed: SessionEvent[AgentChatHistory]


class AgentChatSession:
    """Encapsulate stateful aspects of the chat panel."""

    def __init__(
        self,
        *,
        history: AgentChatHistory,
        timer_owner: wx.EvtHandler,
    ) -> None:
        self._history = history
        self._timer = wx.Timer(timer_owner)
        self._timer_owner = timer_owner
        self._is_running = False
        self._start_time: float | None = None
        self._tokens = TokenCountResult.exact(0)
        self._elapsed = 0.0
        timer_owner.Bind(wx.EVT_TIMER, self._on_timer, self._timer)
        self.events = AgentChatSessionEvents(
            running_changed=SessionEvent(),
            tokens_changed=SessionEvent(),
            elapsed=SessionEvent(),
            history_changed=SessionEvent(),
        )

    # ------------------------------------------------------------------
    @property
    def history(self) -> AgentChatHistory:
        return self._history

    # ------------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        return self._is_running

    # ------------------------------------------------------------------
    @property
    def tokens(self) -> TokenCountResult:
        return self._tokens

    # ------------------------------------------------------------------
    def begin_run(self, *, tokens: TokenCountResult | None = None) -> None:
        """Mark the agent run as active."""
        self._is_running = True
        self._tokens = tokens if tokens is not None else TokenCountResult.exact(0)
        self._start_time = time.monotonic()
        self._elapsed = 0.0
        self.events.running_changed.emit(True)
        self.events.tokens_changed.emit(self._tokens)
        self.events.elapsed.emit(0.0)
        self._timer.Start(100)

    # ------------------------------------------------------------------
    def finalize_run(self, *, tokens: TokenCountResult | None = None) -> None:
        """Mark the agent run as completed."""
        if self._start_time is not None:
            try:
                self._elapsed = max(0.0, time.monotonic() - self._start_time)
            except Exception:  # pragma: no cover - defensive
                self._elapsed = 0.0
        if tokens is not None:
            self._tokens = tokens
        else:
            self._tokens = TokenCountResult.exact(0)
        self._is_running = False
        self._timer.Stop()
        self._start_time = None
        self.events.elapsed.emit(self._elapsed)
        self.events.running_changed.emit(False)
        self.events.tokens_changed.emit(self._tokens)

    # ------------------------------------------------------------------
    def update_tokens(self, tokens: TokenCountResult) -> None:
        """Persist the latest token usage."""
        self._tokens = tokens
        self.events.tokens_changed.emit(tokens)

    # ------------------------------------------------------------------
    @property
    def elapsed(self) -> float:
        """Return the latest elapsed value in seconds."""
        return self._elapsed

    # ------------------------------------------------------------------
    def notify_history_changed(self) -> None:
        """Emit a change event for the underlying history."""
        self.events.history_changed.emit(self._history)

    # ------------------------------------------------------------------
    def load_history(self) -> None:
        """Refresh the in-memory history from disk."""
        self._history.load()
        self.notify_history_changed()

    # ------------------------------------------------------------------
    def save_history(self) -> None:
        """Persist the in-memory history to disk."""
        self._history.save()

    # ------------------------------------------------------------------
    def set_history_path(
        self,
        path: Path | str | None,
        *,
        persist_existing: bool = False,
    ) -> bool:
        """Update the history storage location."""
        changed = self._history.set_path(path, persist_existing=persist_existing)
        if changed:
            self.notify_history_changed()
        return changed

    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        """Tear down resources owned by the session."""
        if self._timer.IsRunning():
            self._timer.Stop()
        self._timer_owner.Unbind(wx.EVT_TIMER, handler=self._on_timer, source=self._timer)

    # ------------------------------------------------------------------
    def _on_timer(self, _event: wx.TimerEvent) -> None:
        if not self._is_running or self._start_time is None:
            return
        elapsed = time.monotonic() - self._start_time
        self._elapsed = elapsed
        self.events.elapsed.emit(elapsed)


__all__ = ["AgentChatSession", "AgentChatSessionEvents", "SessionEvent"]
