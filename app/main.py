"""Application entry point for CookaReq."""

import atexit
import os
from pathlib import Path

import wx

from . import i18n
from .config import ConfigManager
from .confirm import set_confirm, wx_confirm
from .log import configure_logging
from .ui.main_frame import MainFrame
from .ui.requirement_model import RequirementModel

APP_NAME = "CookaReq"
LOCALE_DIR = os.path.join(os.path.dirname(__file__), "locale")
MISSING_PATH = Path(LOCALE_DIR) / "missing.po"
atexit.register(i18n.flush_missing, MISSING_PATH)


def init_locale(language: str | None = None) -> wx.Locale:
    """Initialize wx locale and load translations."""
    wx.Locale.AddCatalogLookupPathPrefix(LOCALE_DIR)
    if language and hasattr(wx.Locale, "FindLanguageInfo"):
        info = wx.Locale.FindLanguageInfo(language)
        locale = wx.Locale(info.Language) if info else wx.Locale(wx.LANGUAGE_DEFAULT)
    else:
        locale = wx.Locale(wx.LANGUAGE_DEFAULT)
    locale.AddCatalog(APP_NAME)
    code = language
    if not code and hasattr(locale, "GetName"):
        name = locale.GetName()
        if name:
            code = name.split("_")[0]
    codes = [code] if code else []
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
