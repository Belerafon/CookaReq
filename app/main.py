"""Application entry point for CookaReq."""

from pathlib import Path

import wx

from . import i18n
from .config import ConfigManager
from .confirm import (
    set_confirm,
    set_requirement_update_confirm,
    wx_confirm,
    wx_confirm_requirement_update,
)
from .log import configure_logging
from .ui.main_frame import MainFrame
from .ui.requirement_model import RequirementModel

APP_NAME = "CookaReq"
LOCALE_DIR = Path(__file__).resolve().parent / "locale"


def init_locale(language: str | None = None) -> wx.Locale:
    """Initialize wx locale and load translations."""
    wx.Locale.AddCatalogLookupPathPrefix(str(LOCALE_DIR))
    if language and hasattr(wx.Locale, "FindLanguageInfo"):
        info = wx.Locale.FindLanguageInfo(language)
        locale = wx.Locale(info.Language) if info else wx.Locale(wx.LANGUAGE_DEFAULT)
    else:
        locale = wx.Locale(wx.LANGUAGE_DEFAULT)
    locale.AddCatalog(APP_NAME)
    languages: list[str] = []
    if language:
        languages.append(language)
    if not languages and hasattr(locale, "GetName"):
        name = locale.GetName()
        if name:
            languages.append(name)
    i18n.install(APP_NAME, LOCALE_DIR, languages)
    return locale


def main() -> None:
    """Run wx application with the main frame."""
    configure_logging()
    app = wx.App()
    set_confirm(wx_confirm)
    set_requirement_update_confirm(wx_confirm_requirement_update)
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
