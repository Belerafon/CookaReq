import threading
import time

import pytest

from app.util.cancellation import (
    CancellationEvent,
    OperationCancelledError,
    raise_if_cancelled,
)


@pytest.fixture(name="cancel_event")
def _cancel_event() -> CancellationEvent:
    return CancellationEvent()


def test_cancellation_event_notifies_waiters(cancel_event: CancellationEvent) -> None:
    started = threading.Event()
    finished = threading.Event()

    def worker() -> None:
        started.set()
        cancel_event.wait()
        finished.set()

    thread = threading.Thread(target=worker)
    thread.start()

    assert started.wait(0.2)
    assert not finished.is_set()

    cancel_event.set()

    thread.join(timeout=0.5)
    assert not thread.is_alive()
    assert finished.is_set()


def test_wait_respects_timeout(cancel_event: CancellationEvent) -> None:
    start = time.perf_counter()
    assert not cancel_event.wait(0.05)
    elapsed = time.perf_counter() - start
    assert elapsed >= 0.05


def test_raise_if_cancelled(cancel_event: CancellationEvent) -> None:
    cancel_event.set()
    with pytest.raises(OperationCancelledError):
        cancel_event.raise_if_cancelled()
    with pytest.raises(OperationCancelledError):
        raise_if_cancelled(cancel_event)


def test_raise_if_cancelled_ignored_for_none() -> None:
    # ``raise_if_cancelled`` should tolerate ``None`` without raising.
    raise_if_cancelled(None)
