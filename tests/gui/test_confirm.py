"""Tests for confirm."""

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
