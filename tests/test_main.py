import sys
import types
import importlib


def test_main_runs(monkeypatch):
    class DummyApp:
        def __init__(self):
            self.loop_ran = False
        def MainLoop(self):
            self.loop_ran = True

    dummy_app = DummyApp()
    wx_stub = types.SimpleNamespace(App=lambda: dummy_app)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)

    class DummyFrame:
        instances = []
        shown = False

        def __init__(self, parent):
            self.parent = parent
            DummyFrame.instances.append(self)
        def Show(self):
            DummyFrame.shown = True

    monkeypatch.setitem(sys.modules, "app.ui.main_frame", types.SimpleNamespace(MainFrame=DummyFrame))

    import app.main as main_module
    importlib.reload(main_module)

    main_module.main()

    assert dummy_app.loop_ran
    assert DummyFrame.shown
    assert DummyFrame.instances and DummyFrame.instances[0].parent is None
