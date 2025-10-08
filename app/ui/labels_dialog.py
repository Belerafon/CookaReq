"""Dialog for managing label colors."""

import wx

from ..config import ConfigManager
from ..confirm import confirm
from ..core.label_presets import PRESET_SET_TITLES, PRESET_SETS
from ..services.requirements import LabelDef, label_color
from ..i18n import _


class _LabelEditDialog(wx.Dialog):
    """Small dialog to edit label key and title."""

    def __init__(self, parent: wx.Window, key: str, title: str):
        super().__init__(parent, title=_("Edit label"))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label=_("Key")), 0, wx.ALL, 5)
        self.key_ctrl = wx.TextCtrl(self, value=key)
        sizer.Add(self.key_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(wx.StaticText(self, label=_("Title")), 0, wx.ALL, 5)
        self.title_ctrl = wx.TextCtrl(self, value=title)
        sizer.Add(self.title_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        btn_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        if btn_sizer:
            sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        self.SetSizerAndFit(sizer)

    def get_values(self) -> tuple[str, str]:
        return self.key_ctrl.GetValue().strip(), self.title_ctrl.GetValue().strip()


class LabelsDialog(wx.Dialog):
    """Dialog allowing to view labels and adjust their colors."""

    def __init__(self, parent: wx.Window | None, labels: list[LabelDef]):
        """Initialize labels dialog with editable label list."""
        style = wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        super().__init__(parent, title=_("Labels"), style=style)
        # copy labels to avoid modifying caller until OK
        self._labels: list[LabelDef] = [
            LabelDef(lbl.key, lbl.title, lbl.color) for lbl in labels
        ]
        cfg = getattr(parent, "config", None)
        if cfg is None:
            cfg = ConfigManager()
        self._config = cfg

        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.list.InsertColumn(0, _("Key"))
        self.list.InsertColumn(1, _("Title"))

        # image list to display colored rectangles instead of hex codes
        self._img_list = wx.ImageList(16, 16)
        self._color_icons: dict[str, int] = {}
        self.list.AssignImageList(self._img_list, wx.IMAGE_LIST_SMALL)

        self._populate()

        self.color_picker = wx.ColourPickerCtrl(self)
        self.color_picker.Disable()

        self.add_presets = wx.Button(self, label=_("Add presets"))
        self.add_presets.Bind(wx.EVT_BUTTON, self._on_show_presets_menu)

        self.edit_btn = wx.Button(self, label=_("Edit"))
        self.edit_btn.Bind(wx.EVT_BUTTON, self._on_edit_selected)

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
        btn_row.Add(self.edit_btn, 0, wx.ALL, 5)
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
        wx.CallAfter(self._resize_columns)

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
            idx = self.list.InsertItem(self.list.GetItemCount(), lbl.key)
            self.list.SetItem(idx, 1, lbl.title)
            img_idx = self._get_icon_index(label_color(lbl))
            self.list.SetItemColumnImage(idx, 0, img_idx)
        self._resize_columns()

    def _on_select(self, event: wx.ListEvent) -> None:  # pragma: no cover - GUI event
        idx = event.GetIndex()
        colour = wx.Colour(label_color(self._labels[idx]))
        self.color_picker.SetColour(colour)
        self.color_picker.Enable()

    def _on_color_changed(
        self,
        event: wx.ColourPickerEvent,
    ) -> None:  # pragma: no cover - GUI event
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
        existing = {lbl.key for lbl in self._labels}
        added = False
        for preset in PRESET_SETS.get(key, []):
            if preset.key not in existing:
                self._labels.append(LabelDef(preset.key, preset.title, preset.color))
                added = True
        if added:
            self._populate()

    def _on_show_presets_menu(
        self,
        _event: wx.Event,
    ) -> None:  # pragma: no cover - GUI event
        menu = wx.Menu()
        for key, title in PRESET_SET_TITLES.items():
            item = menu.Append(wx.ID_ANY, _(title))
            menu.Bind(wx.EVT_MENU, lambda _evt, k=key: self._on_add_preset_set(k), item)
        self.PopupMenu(menu)
        menu.Destroy()

    def _on_delete_selected(
        self,
        _event: wx.Event,
    ) -> None:  # pragma: no cover - GUI event
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

    def get_labels(self) -> list[LabelDef]:
        """Return updated labels."""
        return [LabelDef(lbl.key, lbl.title, lbl.color) for lbl in self._labels]

    # --- new methods -------------------------------------------------

    def _resize_columns(self) -> None:
        width = self.list.GetClientSize().width
        if width > 0:
            first = int(width * 0.4)
            self.list.SetColumnWidth(0, first)
            self.list.SetColumnWidth(1, width - first - 4)

    def _on_list_size(self, _event: wx.Event) -> None:  # pragma: no cover - GUI event
        self._resize_columns()

    def _on_edit_selected(
        self,
        _event: wx.Event,
    ) -> None:  # pragma: no cover - GUI event
        idx = self.list.GetFirstSelected()
        if idx == -1:
            return
        lbl = self._labels[idx]
        dlg = _LabelEditDialog(self, lbl.key, lbl.title)
        if dlg.ShowModal() == wx.ID_OK:
            new_key, new_title = dlg.get_values()
            if not new_key:
                dlg.Destroy()
                return
            existing = {
                label.key for i, label in enumerate(self._labels) if i != idx
            }
            if new_key in existing:
                wx.MessageBox(_("Label already exists"), _("Error"), style=wx.ICON_ERROR)
            else:
                lbl.key = new_key
                lbl.title = new_title or new_key
                self.list.SetItem(idx, 0, lbl.key)
                self.list.SetItem(idx, 1, lbl.title)
        dlg.Destroy()

    def _load_layout(self) -> None:
        w = self._config.read_int("labels_w", 300)
        h = self._config.read_int("labels_h", 200)
        w = max(200, min(w, 1000))
        h = max(150, min(h, 800))
        self.SetSize((w, h))
        x = self._config.read_int("labels_x", -1)
        y = self._config.read_int("labels_y", -1)
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
        self._config.write_int("labels_w", w)
        self._config.write_int("labels_h", h)
        self._config.write_int("labels_x", x)
        self._config.write_int("labels_y", y)
        self._config.flush()

    def Destroy(self) -> bool:  # pragma: no cover - GUI side effect
        """Save window geometry before closing dialog."""
        self._save_layout()
        return super().Destroy()
