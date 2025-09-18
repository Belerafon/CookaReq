import threading

from app.util.cancellation import (
    CancellationTokenSource,
    OperationCancelledError,
)


def test_cancellation_triggers_callbacks():
    source = CancellationTokenSource()
    called = threading.Event()

    def on_cancel() -> None:
        called.set()

    registration = source.token.register(on_cancel)
    assert not source.cancelled

    source.cancel()

    assert source.cancelled
    assert called.wait(0.1)

    # Disposing after cancellation should be a no-op
    registration.dispose()


def test_disposing_registration_prevents_callback():
    source = CancellationTokenSource()
    called = threading.Event()

    def on_cancel() -> None:
        called.set()

    registration = source.token.register(on_cancel)
    registration.dispose()

    source.cancel()

    assert not called.is_set()


def test_register_after_cancellation_invokes_immediately():
    source = CancellationTokenSource()
    source.cancel()

    called = threading.Event()

    source.token.register(lambda: called.set())

    assert called.wait(0.1)


def test_raise_if_cancelled():
    source = CancellationTokenSource()
    source.cancel()

    try:
        source.token.raise_if_cancelled()
    except OperationCancelledError:
        pass
    else:  # pragma: no cover - sanity guard
        raise AssertionError("Expected OperationCancelledError")
