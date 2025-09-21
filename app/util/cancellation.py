"""Thread-safe cancellation primitives built on :class:`threading.Event`."""

from __future__ import annotations

import threading

__all__ = ["CancellationEvent", "OperationCancelledError", "raise_if_cancelled"]


class OperationCancelledError(RuntimeError):
    """Raised when an in-flight operation is aborted via cancellation."""


class CancellationEvent:
    """Lightweight wrapper around :class:`threading.Event` for cancellations."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        """Return ``True`` when cancellation has been requested."""

        return self._event.is_set()

    def is_set(self) -> bool:
        """Expose :meth:`threading.Event.is_set`."""

        return self._event.is_set()

    def set(self) -> None:
        """Signal cancellation."""

        self._event.set()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until cancellation occurs or *timeout* elapses."""

        return self._event.wait(timeout)

    def clear(self) -> None:
        """Reset the event; used in tests to simulate reuse."""

        self._event.clear()

    def raise_if_cancelled(self) -> None:
        """Raise :class:`OperationCancelledError` if cancellation occurred."""

        if self._event.is_set():
            raise OperationCancelledError()


def raise_if_cancelled(cancellation: CancellationEvent | None) -> None:
    """Convenience helper raising when *cancellation* has been signalled."""

    if cancellation is not None:
        cancellation.raise_if_cancelled()
