"""Dialog for managing label colors."""

from gettext import gettext as _

import wx

from app.core.labels import Label, PRESET_SETS, PRESET_SET_TITLES


class LabelsDialog(wx.Dialog):
    """Dialog allowing to view labels and adjust their colors."""

    def __init__(self, parent: wx.Window, labels: list[Label]):
        super().__init__(parent, title=_("Labels"))
        # copy labels to avoid modifying caller until OK
        self._labels: list[Label] = [Label(l.name, l.color) for l in labels]

        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.list.InsertColumn(0, _("Name"))

        # image list to display colored rectangles instead of hex codes
        self._img_list = wx.ImageList(16, 16)
        self._color_icons: dict[str, int] = {}
        self.list.AssignImageList(self._img_list, wx.IMAGE_LIST_SMALL)

        self._populate()

        self.color_picker = wx.ColourPickerCtrl(self)
        self.color_picker.Disable()

        self.add_presets = wx.Button(self, label=_("Add presets"))
        self.add_presets.Bind(wx.EVT_BUTTON, self._on_show_presets_menu)

        self.delete_btn = wx.Button(self, label=_("Delete"))
        self.delete_btn.Bind(wx.EVT_BUTTON, self._on_delete_selected)

        self.clear_btn = wx.Button(self, label=_("Clear all"))
        self.clear_btn.Bind(wx.EVT_BUTTON, self._on_clear_all)

        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_select)
        self.color_picker.Bind(wx.EVT_COLOURPICKER_CHANGED, self._on_color_changed)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self.color_picker, 0, wx.ALL | wx.ALIGN_RIGHT, 5)
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row.Add(self.add_presets, 0, wx.ALL, 5)
        btn_row.Add(self.delete_btn, 0, wx.ALL, 5)
        btn_row.Add(self.clear_btn, 0, wx.ALL, 5)
        sizer.Add(btn_row, 0, wx.ALIGN_RIGHT)
        btn_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        if btn_sizer:
            sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        self.SetSizerAndFit(sizer)

    def _get_icon_index(self, colour: str) -> int:
        """Return image index for ``colour``, creating bitmap if needed."""
        if colour not in self._color_icons:
            bmp = wx.Bitmap(16, 16)
            dc = wx.MemoryDC(bmp)
            wx_colour = wx.Colour(colour)
            dc.SetBrush(wx.Brush(wx_colour))
            dc.SetPen(wx.Pen(wx_colour))
            dc.DrawRectangle(0, 0, 16, 16)
            dc.SelectObject(wx.NullBitmap)
            self._color_icons[colour] = self._img_list.Add(bmp)
        return self._color_icons[colour]

    def _populate(self) -> None:
        self.list.DeleteAllItems()
        for lbl in self._labels:
            idx = self.list.InsertItem(self.list.GetItemCount(), lbl.name)
            img_idx = self._get_icon_index(lbl.color)
            self.list.SetItemColumnImage(idx, 0, img_idx)

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
        img_idx = self._get_icon_index(colour)
        self.list.SetItemColumnImage(idx, 0, img_idx)

    def _get_selected_indices(self) -> list[int]:
        indices: list[int] = []
        idx = self.list.GetFirstSelected()
        while idx != -1:
            indices.append(idx)
            idx = self.list.GetNextSelected(idx)
        return indices

    def _on_add_preset_set(self, key: str) -> None:  # pragma: no cover - GUI event
        existing = {lbl.name for lbl in self._labels}
        added = False
        for preset in PRESET_SETS.get(key, []):
            if preset.name not in existing:
                self._labels.append(Label(preset.name, preset.color))
                added = True
        if added:
            self._populate()

    def _on_show_presets_menu(self, event: wx.Event) -> None:  # pragma: no cover - GUI event
        menu = wx.Menu()
        for key, title in PRESET_SET_TITLES.items():
            item = menu.Append(wx.ID_ANY, _(title))
            menu.Bind(wx.EVT_MENU, lambda evt, k=key: self._on_add_preset_set(k), item)
        self.PopupMenu(menu)
        menu.Destroy()

    def _on_delete_selected(self, _event: wx.Event) -> None:  # pragma: no cover - GUI event
        indices = self._get_selected_indices()
        if not indices:
            return
        for i in sorted(indices, reverse=True):
            del self._labels[i]
        self._populate()
        self.color_picker.Disable()

    def _on_clear_all(self, _event: wx.Event) -> None:  # pragma: no cover - GUI event
        res = wx.MessageBox(
            _("Remove all labels?"),
            _("Confirm"),
            style=wx.YES_NO | wx.ICON_WARNING,
        )
        if res == wx.YES:
            self._labels.clear()
            self._populate()
            self.color_picker.Disable()

    def get_labels(self) -> list[Label]:
        """Return updated labels."""
        return list(self._labels)
