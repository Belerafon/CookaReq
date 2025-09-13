import importlib
from pathlib import Path

import pytest


def test_switch_to_russian_updates_ui(monkeypatch):
    wx = pytest.importorskip("wx")
    from compile_translations import compile_all
    compile_all(Path("app/locale"))
    app = wx.App()
    import app.ui.main_frame as main_frame
    importlib.reload(main_frame)

    frame = main_frame.MainFrame(None)
    assert frame.GetMenuBar().GetMenu(0).GetTitle() == "&File"

    import app.main as main_mod

    def fake_init_locale(language):
        import gettext
        from app.main import APP_NAME, LOCALE_DIR
        gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
        gettext.textdomain(APP_NAME)
        gettext.translation(APP_NAME, LOCALE_DIR, languages=[language], fallback=True).install()
        return None

    monkeypatch.setattr(main_mod, "init_locale", fake_init_locale)

    class DummySettingsDialog:
        def __init__(self, *args, **kwargs):
            pass
        def ShowModal(self):
            return wx.ID_OK
        def get_values(self):
            return (
                frame.auto_open_last,
                frame.remember_sort,
                "ru",
                frame.mcp_host,
                frame.mcp_port,
                frame.mcp_base_path,
                frame.mcp_require_token,
                frame.mcp_token,
            )
        def Destroy(self):
            pass

    monkeypatch.setattr(main_frame, "SettingsDialog", DummySettingsDialog)

    frame.on_open_settings(None)
    assert frame.GetMenuBar().GetMenu(0).GetTitle() == "&Файл"

    frame.Destroy()
    app.Destroy()
