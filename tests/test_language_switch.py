"""Tests for language switch."""

import importlib

import pytest


def test_switch_to_russian_updates_ui(monkeypatch, wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.main_frame as main_frame
    importlib.reload(main_frame)

    frame = main_frame.MainFrame(None)
    assert frame.GetMenuBar().GetMenu(0).GetTitle() == "&File"

    import app.main as main_mod
    from app import i18n

    def fake_init_locale(language):
        i18n.install(main_mod.APP_NAME, main_mod.LOCALE_DIR, [language])
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
                frame.llm_settings.api_base,
                frame.llm_settings.model,
                frame.llm_settings.api_key,
                frame.llm_settings.timeout,
                frame.mcp_settings.host,
                frame.mcp_settings.port,
                frame.mcp_settings.base_path,
                frame.mcp_settings.require_token,
                frame.mcp_settings.token,
            )
        def Destroy(self):
            pass

    monkeypatch.setattr(main_frame, "SettingsDialog", DummySettingsDialog)

    frame.on_open_settings(None)
    assert frame.GetMenuBar().GetMenu(0).GetTitle() == "&Файл"

    frame.Destroy()
    from app import i18n
    # restore default language for subsequent tests
    i18n.install(main_mod.APP_NAME, main_mod.LOCALE_DIR, ["en"])
