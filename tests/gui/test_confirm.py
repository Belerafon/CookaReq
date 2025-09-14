"""Tests for confirm."""

import pytest

from app import confirm as confirm_mod
from app.confirm import set_confirm, auto_confirm, wx_confirm

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

    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.YES)
    assert wx_confirm("Proceed?") is True

    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.NO)
    assert wx_confirm("Proceed?") is False
