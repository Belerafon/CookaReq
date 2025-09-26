"""Tests for main."""

import importlib
import sys
import types
from typing import ClassVar

import pytest

pytestmark = [pytest.mark.gui, pytest.mark.gui_smoke]


def test_main_runs(monkeypatch):
    class DummyApp:
        def __init__(self):
            self.loop_ran = False

        def MainLoop(self):
            self.loop_ran = True

    dummy_app = DummyApp()

    class DummyLocale:
        def __init__(self, lang):
            self.lang = lang

        def AddCatalog(self, name):
            pass

    class DummyConfig:
        def __init__(self, **kwargs):
            self.app_name = kwargs.get("appName")

        def Read(self, key):
            return ""

    def add_prefix(path):
        return None

    wx_stub = types.SimpleNamespace(
        App=lambda: dummy_app,
        Locale=DummyLocale,
        Config=DummyConfig,
        LANGUAGE_DEFAULT=0,
    )
    wx_stub.Locale.AddCatalogLookupPathPrefix = add_prefix
    monkeypatch.setitem(sys.modules, "wx", wx_stub)

    class DummyFrame:
        instances: ClassVar[list] = []
        shown = False

        def __init__(self, parent=None, **kwargs):
            self.parent = parent
            self.kwargs = kwargs
            DummyFrame.instances.append(self)

        def Show(self):
            DummyFrame.shown = True

    monkeypatch.setitem(
        sys.modules,
        "app.ui.main_frame",
        types.SimpleNamespace(MainFrame=DummyFrame),
    )

    import app.main as main_module

    importlib.reload(main_module)

    main_module.main()

    assert dummy_app.loop_ran
    assert DummyFrame.shown
    assert DummyFrame.instances and DummyFrame.instances[0].parent is None
    assert "config" in DummyFrame.instances[0].kwargs
    assert "model" in DummyFrame.instances[0].kwargs
