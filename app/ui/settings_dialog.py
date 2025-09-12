"""Dialog for application settings."""

from gettext import gettext as _

import wx


class SettingsDialog(wx.Dialog):
    """Simple dialog with application preferences."""

    def __init__(self, parent: wx.Window, *, open_last: bool, remember_sort: bool):
        super().__init__(parent, title=_("Settings"))
        self._open_last = wx.CheckBox(self, label=_("Open last folder on startup"))
        self._open_last.SetValue(open_last)
        self._remember_sort = wx.CheckBox(self, label=_("Remember sort order"))
        self._remember_sort.SetValue(remember_sort)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._open_last, 0, wx.ALL, 5)
        sizer.Add(self._remember_sort, 0, wx.ALL, 5)
        btn_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        if btn_sizer:
            sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        self.SetSizerAndFit(sizer)

    def get_values(self) -> tuple[bool, bool]:
        """Return (open_last_folder, remember_sort)."""
        return self._open_last.GetValue(), self._remember_sort.GetValue()
