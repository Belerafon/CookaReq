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

    dlg = SettingsDialog(
        None,
        open_last=True,
        remember_sort=False,
        language="ru",
        host="127.0.0.1",
        port=8000,
        base_path="/tmp",
    )
    values = dlg.get_values()
    assert values == (True, False, "ru", "127.0.0.1", 8000, "/tmp")
    dlg.Destroy()
