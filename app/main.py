"""Application entry point for CookaReq."""

import logging
import os
import gettext
import wx

from .ui.main_frame import MainFrame


APP_NAME = "CookaReq"
LOCALE_DIR = os.path.join(os.path.dirname(__file__), "locale")


def init_locale() -> wx.Locale:
    """Initialize wx and gettext locales."""
    wx.Locale.AddCatalogLookupPathPrefix(LOCALE_DIR)
    locale = wx.Locale(wx.LANGUAGE_DEFAULT)
    locale.AddCatalog(APP_NAME)
    gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
    gettext.textdomain(APP_NAME)
    gettext.install(APP_NAME, LOCALE_DIR)
    return locale


def main() -> None:
    """Run wx application with the main frame."""
    logging.basicConfig(level=logging.INFO)
    app = wx.App()
    app.locale = init_locale()
    frame = MainFrame(parent=None)
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":  # pragma: no cover
    main()
