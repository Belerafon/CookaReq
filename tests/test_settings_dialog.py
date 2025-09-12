import pytest


def test_available_translations_contains_locales():
    wx = pytest.importorskip("wx")
    from app.ui.settings_dialog import available_translations

    langs = available_translations()
    codes = {code for code, _ in langs}
    # english is default, russian is provided in repo
    assert {"en", "ru"}.issubset(codes)


def test_settings_dialog_returns_language():
    wx = pytest.importorskip("wx")
    _app = wx.App()
    from app.ui.settings_dialog import SettingsDialog

    dlg = SettingsDialog(None, open_last=True, remember_sort=False, language="ru")
    values = dlg.get_values()
    assert values == (True, False, "ru")
    dlg.Destroy()
