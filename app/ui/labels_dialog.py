"""Dialog for managing label colors."""

from ..i18n import _
from ..confirm import confirm

import wx

from ..core.labels import Label, PRESET_SETS, PRESET_SET_TITLES
from ..config import ConfigManager


class LabelsDialog(wx.Dialog):
    """Dialog allowing to view labels and adjust their colors."""

    def __init__(self, parent: wx.Window | None, labels: list[Label]):
        style = wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        super().__init__(parent, title=_("Labels"), style=style)
        # copy labels to avoid modifying caller until OK
        self._labels: list[Label] = [Label(lbl.name, lbl.color) for lbl in labels]
        cfg = getattr(parent, "config", None)
        if cfg is None:
            cfg = ConfigManager()
        self._config = cfg

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

        self.rename_btn = wx.Button(self, label=_("Rename"))
        self.rename_btn.Bind(wx.EVT_BUTTON, self._on_rename_selected)

        self.delete_btn = wx.Button(self, label=_("Delete"))
        self.delete_btn.Bind(wx.EVT_BUTTON, self._on_delete_selected)

        self.clear_btn = wx.Button(self, label=_("Clear all"))
        self.clear_btn.Bind(wx.EVT_BUTTON, self._on_clear_all)

        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_select)
        self.list.Bind(wx.EVT_SIZE, self._on_list_size)
        self.color_picker.Bind(wx.EVT_COLOURPICKER_CHANGED, self._on_color_changed)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self.color_picker, 0, wx.ALL | wx.ALIGN_RIGHT, 5)
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row.Add(self.add_presets, 0, wx.ALL, 5)
        btn_row.Add(self.rename_btn, 0, wx.ALL, 5)
        btn_row.Add(self.delete_btn, 0, wx.ALL, 5)
        btn_row.Add(self.clear_btn, 0, wx.ALL, 5)
        sizer.Add(btn_row, 0, wx.ALIGN_RIGHT)
        btn_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        if btn_sizer:
            sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        self.SetSizer(sizer)
        sizer.Fit(self)
        self.SetMinSize(self.GetSize())
        self._load_layout()
        wx.CallAfter(self._resize_column)

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
        self._resize_column()

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
        if confirm(_("Remove all labels?")):
            self._labels.clear()
            self._populate()
            self.color_picker.Disable()

    def get_labels(self) -> list[Label]:
        """Return updated labels."""
        return list(self._labels)

    # --- new methods -------------------------------------------------

    def _resize_column(self) -> None:
        width = self.list.GetClientSize().width
        if width > 0:
            self.list.SetColumnWidth(0, width - 4)

    def _on_list_size(self, _event: wx.Event) -> None:  # pragma: no cover - GUI event
        self._resize_column()

    def _on_rename_selected(self, _event: wx.Event) -> None:  # pragma: no cover - GUI event
        idx = self.list.GetFirstSelected()
        if idx == -1:
            return
        old_name = self._labels[idx].name
        dlg = wx.TextEntryDialog(self, _("New name"), _("Rename"), value=old_name)
        if dlg.ShowModal() == wx.ID_OK:
            new_name = dlg.GetValue().strip()
            if not new_name:
                dlg.Destroy()
                return
            existing = {lbl.name for i, lbl in enumerate(self._labels) if i != idx}
            if new_name in existing:
                wx.MessageBox(_("Label already exists"), _("Error"), style=wx.ICON_ERROR)
            else:
                self._labels[idx].name = new_name
                self.list.SetItem(idx, 0, new_name)
        dlg.Destroy()

    def _load_layout(self) -> None:
        w = self._config.ReadInt("labels_w", 300)
        h = self._config.ReadInt("labels_h", 200)
        w = max(200, min(w, 1000))
        h = max(150, min(h, 800))
        self.SetSize((w, h))
        x = self._config.ReadInt("labels_x", -1)
        y = self._config.ReadInt("labels_y", -1)
        if x != -1 and y != -1:
            self.SetPosition((x, y))
            rect = self.GetRect()
            visible = False
            for i in range(wx.Display.GetCount()):
                if wx.Display(i).GetGeometry().Intersects(rect):
                    visible = True
                    break
            if not visible:
                if self.GetParent():
                    self.CentreOnParent()
                else:
                    self.Centre()
        else:
            if self.GetParent():
                self.CentreOnParent()
            else:
                self.Centre()

    def _save_layout(self) -> None:
        w, h = self.GetSize()
        x, y = self.GetPosition()
        self._config.WriteInt("labels_w", w)
        self._config.WriteInt("labels_h", h)
        self._config.WriteInt("labels_x", x)
        self._config.WriteInt("labels_y", y)
        self._config.Flush()

    def Destroy(self) -> bool:  # pragma: no cover - GUI side effect
        """Save window geometry before closing dialog."""

        self._save_layout()
        return super().Destroy()
