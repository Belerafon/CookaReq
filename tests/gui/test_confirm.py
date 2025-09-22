"""Tests for confirm."""

import threading
import time

import pytest

from app import confirm as confirm_mod
from app.confirm import auto_confirm, set_confirm, wx_confirm

pytestmark = pytest.mark.gui


def test_confirm_without_callback_raises(monkeypatch):
    monkeypatch.setattr(confirm_mod, "_callback", None, raising=False)
    with pytest.raises(RuntimeError):
        confirm_mod.confirm("Are you sure?")


def test_set_confirm_and_auto_confirm_work():
    captured = {}

    def fake_callback(message: str) -> bool:
        captured["message"] = message
        return False

    set_confirm(fake_callback)
    assert confirm_mod.confirm("no") is False
    assert captured["message"] == "no"

    set_confirm(auto_confirm)
    assert confirm_mod.confirm("yes") is True


def test_wx_confirm(monkeypatch):
    import wx

    responses = iter([wx.ID_YES, wx.ID_NO, wx.ID_OK])
    destroyed: list[bool] = []

    class DummyDialog:
        def __init__(self, *_args, **_kwargs) -> None:
            self._destroyed = False

        def ShowModal(self) -> int:
            return next(responses)

        def Destroy(self) -> None:
            destroyed.append(True)

    monkeypatch.setattr(wx, "MessageDialog", lambda *a, **k: DummyDialog())
    monkeypatch.setattr(wx, "GetActiveWindow", lambda: None)
    monkeypatch.setattr(wx, "GetTopLevelWindows", lambda: [])

    assert wx_confirm("Proceed?") is True
    assert destroyed.pop(0) is True

    assert wx_confirm("Proceed?") is False
    assert destroyed.pop(0) is True

    assert wx_confirm("Proceed?") is True
    assert destroyed.pop(0) is True


def test_wx_confirm_from_worker_thread(monkeypatch, wx_app):
    import wx

    responses = iter([wx.ID_YES])
    destroyed: list[bool] = []
    modal_threads: list[bool] = []

    def fake_is_main_thread() -> bool:
        return threading.current_thread() is threading.main_thread()

    class DummyDialog:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def ShowModal(self) -> int:
            modal_threads.append(wx.IsMainThread())
            return next(responses)

        def Destroy(self) -> None:
            destroyed.append(True)

    monkeypatch.setattr(wx, "MessageDialog", lambda *a, **k: DummyDialog())
    monkeypatch.setattr(wx, "GetActiveWindow", lambda: None)
    monkeypatch.setattr(wx, "GetTopLevelWindows", lambda: [])
    monkeypatch.setattr(wx, "IsMainThread", fake_is_main_thread)

    results: list[bool] = []

    def worker() -> None:
        results.append(wx_confirm("Proceed?"))

    thread = threading.Thread(target=worker, name="confirm-worker")
    thread.start()

    deadline = time.time() + 2.0
    while time.time() < deadline and not results:
        wx_app.Yield()
        time.sleep(0.01)

    thread.join(timeout=0.5)
    assert not thread.is_alive(), "Worker thread did not finish"
    assert results == [True]
    assert destroyed == [True]
    assert modal_threads == [True]
