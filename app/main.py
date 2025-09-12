"""Application entry point for CookaReq."""

import os
import gettext
import wx

from .ui.main_frame import MainFrame
from .log import configure_logging


APP_NAME = "CookaReq"
LOCALE_DIR = os.path.join(os.path.dirname(__file__), "locale")


def init_locale(language: str | None = None) -> wx.Locale:
    """Initialize wx and gettext locales."""
    wx.Locale.AddCatalogLookupPathPrefix(LOCALE_DIR)
    if language:
        info = wx.Locale.FindLanguageInfo(language)
        if info:
            locale = wx.Locale(info.Language)
        else:  # fallback to system default if code is unknown
            locale = wx.Locale(wx.LANGUAGE_DEFAULT)
    else:
        locale = wx.Locale(wx.LANGUAGE_DEFAULT)
    locale.AddCatalog(APP_NAME)
    gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
    gettext.textdomain(APP_NAME)
    codes = [language] if language else None
    gettext.translation(APP_NAME, LOCALE_DIR, languages=codes, fallback=True).install()
    return locale


def main() -> None:
    """Run wx application with the main frame."""
    configure_logging()
    app = wx.App()
    config = wx.Config(appName=APP_NAME)
    language = config.Read("language") or None
    app.locale = init_locale(language)
    frame = MainFrame(parent=None)
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":  # pragma: no cover
    main()
