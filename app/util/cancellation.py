"""Thread-safe cancellation primitives used across CookaReq."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable, Optional

__all__ = [
    "CancellationRegistration",
    "CancellationToken",
    "CancellationTokenSource",
    "OperationCancelledError",
]

_logger = logging.getLogger(__name__)


class OperationCancelledError(RuntimeError):
    """Raised when an in-flight operation is aborted via cancellation."""


@dataclass(slots=True)
class CancellationRegistration:
    """Handle allowing subscribers to detach cancellation callbacks."""

    _source: "CancellationTokenSource"
    _key: Optional[int]
    _disposed: bool = False

    def dispose(self) -> None:
        """Remove the associated callback from the cancellation source."""

        if self._disposed:
            return
        self._disposed = True
        if self._key is not None:
            self._source._unregister(self._key)


class CancellationToken:
    """Read-only view over a :class:`CancellationTokenSource`."""

    __slots__ = ("_source",)

    def __init__(self, source: "CancellationTokenSource") -> None:
        self._source = source

    @property
    def cancelled(self) -> bool:
        """Return ``True`` when cancellation has been requested."""

        return self._source._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the token is cancelled or *timeout* elapses."""

        return self._source._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        """Raise :class:`OperationCancelledError` if cancellation occurred."""

        if self.cancelled:
            raise OperationCancelledError()

    def register(self, callback: Callable[[], None]) -> CancellationRegistration:
        """Attach *callback* to be invoked when the token is cancelled."""

        return self._source._register(callback)


class CancellationTokenSource:
    """Mutable cancellation controller that owns a token."""

    __slots__ = ("_event", "_lock", "_callbacks", "_next_key", "_token")

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._next_key = 0
        self._token = CancellationToken(self)

    @property
    def token(self) -> CancellationToken:
        """Expose the read-only cancellation token."""

        return self._token

    @property
    def cancelled(self) -> bool:
        """Return ``True`` when :meth:`cancel` has been called."""

        return self._event.is_set()

    def cancel(self) -> None:
        """Signal cancellation and invoke registered callbacks once."""

        callbacks: list[Callable[[], None]]
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            callbacks = list(self._callbacks.values())
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:  # pragma: no cover - defensive
                _logger.exception("Cancellation callback failed")

    def _register(self, callback: Callable[[], None]) -> CancellationRegistration:
        if not callable(callback):
            raise TypeError("callback must be callable")
        with self._lock:
            if self._event.is_set():
                registration = CancellationRegistration(self, None, True)
            else:
                key = self._next_key
                self._next_key += 1
                self._callbacks[key] = callback
                return CancellationRegistration(self, key)
        try:
            callback()
        except Exception:  # pragma: no cover - defensive
            _logger.exception("Cancellation callback failed")
        return registration

    def _unregister(self, key: int) -> None:
        with self._lock:
            self._callbacks.pop(key, None)
