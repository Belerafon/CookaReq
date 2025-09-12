"""Dialog for managing label colors."""

from gettext import gettext as _

import wx

from app.core.labels import Label


class LabelsDialog(wx.Dialog):
    """Dialog allowing to view labels and adjust their colors."""

    def __init__(self, parent: wx.Window, labels: list[Label]):
        super().__init__(parent, title=_("Labels"))
        # copy labels to avoid modifying caller until OK
        self._labels: list[Label] = [Label(l.name, l.color) for l in labels]

        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.list.InsertColumn(0, _("Name"))
        self.list.InsertColumn(1, _("Color"))

        self._populate()

        self.color_picker = wx.ColourPickerCtrl(self)
        self.color_picker.Disable()

        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_select)
        self.color_picker.Bind(wx.EVT_COLOURPICKER_CHANGED, self._on_color_changed)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self.color_picker, 0, wx.ALL | wx.ALIGN_RIGHT, 5)
        btn_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        if btn_sizer:
            sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        self.SetSizerAndFit(sizer)

    def _populate(self) -> None:
        self.list.DeleteAllItems()
        for lbl in self._labels:
            idx = self.list.InsertItem(self.list.GetItemCount(), lbl.name)
            self.list.SetItem(idx, 1, lbl.color)

    def _on_select(self, event: wx.ListEvent) -> None:  # pragma: no cover - GUI event
        idx = event.GetIndex()
        colour = wx.Colour(self._labels[idx].color)
        self.color_picker.SetColour(colour)
        self.color_picker.Enable()

    def _on_color_changed(self, event: wx.ColourPickerEvent) -> None:  # pragma: no cover - GUI event
        idx = self.list.GetFirstSelected()
        if idx == -1:
            return
        colour = event.GetColour().GetAsString(wx.C2S_HTML_SYNTAX)
        self._labels[idx].color = colour
        self.list.SetItem(idx, 1, colour)

    def get_labels(self) -> list[Label]:
        """Return updated labels."""
        return list(self._labels)
