"""Tests for language switch."""

import importlib

import pytest

from app.config import ConfigManager
from app.settings import MCPSettings

pytestmark = pytest.mark.gui


def test_switch_to_russian_updates_ui(monkeypatch, wx_app, tmp_path, gui_context):
    wx = pytest.importorskip("wx")
    import app.ui.main_frame as main_frame

    importlib.reload(main_frame)
    config = ConfigManager(path=tmp_path / "language.ini")
    config.set_mcp_settings(MCPSettings(auto_start=False))

    frame = main_frame.MainFrame(None, context=gui_context, config=config)
    assert frame.GetMenuBar().GetMenu(0).GetTitle() == "&File"

    import app.main as main_mod
    from app import i18n

    def fake_init_locale(language):
        i18n.install(main_mod.APP_NAME, main_mod.LOCALE_DIR, [language])

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
                frame.llm_settings.base_url,
                frame.llm_settings.model,
                getattr(
                    frame.llm_settings.message_format,
                    "value",
                    frame.llm_settings.message_format,
                ),
                frame.llm_settings.api_key or "",
                frame.llm_settings.max_retries,
                frame.llm_settings.max_context_tokens,
                frame.llm_settings.timeout_minutes,
                frame.llm_settings.use_custom_temperature,
                frame.llm_settings.temperature,
                frame.llm_settings.stream,
                frame.mcp_settings.auto_start,
                frame.mcp_settings.host,
                frame.mcp_settings.port,
                frame.mcp_settings.base_path,
                frame.mcp_settings.log_dir or "",
                frame.mcp_settings.require_token,
                frame.mcp_settings.token,
            )

        def Destroy(self):
            pass

    monkeypatch.setattr(main_frame, "SettingsDialog", DummySettingsDialog)

    frame.on_open_settings(None)
    expected_title = i18n.gettext("&File")
    assert frame.GetMenuBar().GetMenu(0).GetTitle() == expected_title

    frame.Destroy()
    # restore default language for subsequent tests
    i18n.install(main_mod.APP_NAME, main_mod.LOCALE_DIR, ["en"])
