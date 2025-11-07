"""Application entry point for CookaReq."""

from pathlib import Path

import wx

from app import i18n
from app.application import ApplicationContext
import sys

from app.log import configure_logging, install_exception_hooks, logger
from app.ui.main_frame import MainFrame

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


class CookaReqApp(wx.App):
    """Custom wx.App that logs unhandled GUI exceptions."""

    def OnExceptionInMainLoop(self) -> None:  # pragma: no cover - GUI path
        exc_info = sys.exc_info()
        try:
            logger.exception("Unhandled exception in GUI main loop", exc_info=exc_info)
        finally:
            # Delegate to default handler (will show native crash in debug builds)
            super().OnExceptionInMainLoop()


def main() -> None:
    """Run wx application with the main frame."""
    configure_logging()
    install_exception_hooks()
    context = ApplicationContext.for_gui(app_name=APP_NAME)
    config = context.config
    language = config.get_language()
    app = CookaReqApp()
    app.locale = init_locale(language)
    frame = MainFrame(
        parent=None,
        context=context,
        config=config,
        model=context.requirement_model,
    )
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":  # pragma: no cover
    main()
