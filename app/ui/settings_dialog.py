"""Dialog for application settings."""

from gettext import gettext as _
from importlib import resources

import wx


def available_translations() -> list[tuple[str, str]]:
    """Return list of (language_code, display_name) for available translations."""
    langs: list[tuple[str, str]] = []
    locale_root = resources.files("app") / "locale"
    for entry in locale_root.iterdir():
        if entry.is_dir():
            code = entry.name
            info = wx.Locale.FindLanguageInfo(code)
            name = info.Description if info else code
            langs.append((code, name))
    return langs


class SettingsDialog(wx.Dialog):
    """Simple dialog with application preferences."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        open_last: bool,
        remember_sort: bool,
        language: str,
    ) -> None:
        super().__init__(parent, title=_("Settings"))
        self._open_last = wx.CheckBox(self, label=_("Open last folder on startup"))
        self._open_last.SetValue(open_last)
        self._remember_sort = wx.CheckBox(self, label=_("Remember sort order"))
        self._remember_sort.SetValue(remember_sort)

        self._languages = available_translations()
        choices = [name for _, name in self._languages]
        self._language_choice = wx.Choice(self, choices=choices)
        try:
            idx = [code for code, _ in self._languages].index(language)
        except ValueError:
            idx = 0
        self._language_choice.SetSelection(idx)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._open_last, 0, wx.ALL, 5)
        sizer.Add(self._remember_sort, 0, wx.ALL, 5)
        lang_sizer = wx.BoxSizer(wx.HORIZONTAL)
        lang_sizer.Add(wx.StaticText(self, label=_("Language")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        lang_sizer.Add(self._language_choice, 1, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(lang_sizer, 0, wx.ALL | wx.EXPAND, 5)
        btn_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        if btn_sizer:
            sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        self.SetSizerAndFit(sizer)

    def get_values(self) -> tuple[bool, bool, str]:
        """Return (open_last_folder, remember_sort, language_code)."""
        lang_code = self._languages[self._language_choice.GetSelection()][0]
        return self._open_last.GetValue(), self._remember_sort.GetValue(), lang_code
