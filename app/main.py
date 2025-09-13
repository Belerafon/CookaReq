"""Application entry point for CookaReq."""

import os
import wx

from .ui.main_frame import MainFrame
from .log import configure_logging
from .config import ConfigManager
from .ui.requirement_model import RequirementModel
from . import i18n
from .confirm import set_confirm, wx_confirm


APP_NAME = "CookaReq"
LOCALE_DIR = os.path.join(os.path.dirname(__file__), "locale")


def init_locale(language: str | None = None) -> wx.Locale:
    """Initialize wx locale and load translations."""
    wx.Locale.AddCatalogLookupPathPrefix(LOCALE_DIR)
    if language and hasattr(wx.Locale, "FindLanguageInfo"):
        info = wx.Locale.FindLanguageInfo(language)
        if info:
            locale = wx.Locale(info.Language)
        else:  # fallback to system default if code is unknown
            locale = wx.Locale(wx.LANGUAGE_DEFAULT)
    else:
        locale = wx.Locale(wx.LANGUAGE_DEFAULT)
    locale.AddCatalog(APP_NAME)
    codes = [language] if language else [locale.GetName().split("_")[0]]
    i18n.install(APP_NAME, LOCALE_DIR, codes)
    return locale


def main() -> None:
    """Run wx application with the main frame."""
    configure_logging()
    app = wx.App()
    set_confirm(wx_confirm)
    config = ConfigManager(APP_NAME)
    language = config.get_language()
    app.locale = init_locale(language)
    model = RequirementModel()
    try:
        frame = MainFrame(parent=None, config=config, model=model)
    except TypeError:  # compatibility with potential stubs
        frame = MainFrame(parent=None)
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":  # pragma: no cover
    main()
