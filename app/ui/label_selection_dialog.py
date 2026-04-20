"""Dialog for selecting labels with color icons."""

import wx
from contextlib import suppress

from ..config import ConfigManager
from ..services.requirements import LabelDef, label_color
from ..i18n import _


class _CheckListCtrl(wx.ListCtrl):
    """ListCtrl with simple checkbox helpers."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        with suppress(Exception):
            self.EnableCheckBoxes(True)

    def GetCheckedItems(self) -> list[int]:
        return [i for i in range(self.GetItemCount()) if self.IsItemChecked(i)]


class LabelSelectionDialog(wx.Dialog):
    """Dialog allowing to choose labels while displaying their colors."""

    def __init__(
        self,
        parent: wx.Window | None,
        labels: list[LabelDef],
        selected: list[str],
        *,
        allow_freeform: bool = False,
        inherited_labels: list[LabelDef] | None = None,
    ):
        """Initialize dialog listing ``labels`` with ``selected`` prechecked.

        When ``allow_freeform`` is ``True`` an additional text field accepts
        comma-separated custom label names.
        """
        style = wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        super().__init__(parent, title=_("Labels"), style=style)
        self._local_labels = [LabelDef(lbl.key, lbl.title, lbl.color) for lbl in labels]
        inherited = inherited_labels if inherited_labels is not None else labels
        self._inherited_labels = [LabelDef(lbl.key, lbl.title, lbl.color) for lbl in inherited]
        self._labels: list[LabelDef] = []
        self._allow_freeform = allow_freeform
        self._selected_keys: set[str] = {key for key in selected if isinstance(key, str)}
        self._config = self._resolve_config(parent)
        self._include_inherited_key = "labels_include_inherited"
        self._has_inherited_toggle = inherited_labels is not None
        self._include_inherited = self._read_include_inherited_default()

        self.list = _CheckListCtrl(self)
        self.list.InsertColumn(0, _("Key"))
        self.list.InsertColumn(1, _("Title"))

        self._img_list = wx.ImageList(16, 16)
        self._color_icons: dict[str, int] = {}
        self.list.AssignImageList(self._img_list, wx.IMAGE_LIST_SMALL)

        self.list.Bind(wx.EVT_SIZE, self._on_list_size)

        sizer = wx.BoxSizer(wx.VERTICAL)
        if self._has_inherited_toggle:
            self.inherited_toggle = wx.CheckBox(
                self,
                label=_("Use higher-level labels"),
            )
            self.inherited_toggle.SetValue(self._include_inherited)
            self.inherited_toggle.Bind(wx.EVT_CHECKBOX, self._on_toggle_inherited)
            sizer.Add(self.inherited_toggle, 0, wx.ALL, 5)
        else:
            self.inherited_toggle = None
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)
        if self._allow_freeform:
            lbl = wx.StaticText(self, label=_("Custom labels (comma-separated)"))
            sizer.Add(lbl, 0, wx.LEFT | wx.RIGHT, 5)
            self.freeform_ctrl = wx.TextCtrl(self)
            sizer.Add(self.freeform_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        else:
            self.freeform_ctrl = None
        btn_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        if btn_sizer:
            sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        self.SetSizer(sizer)
        sizer.Fit(self)
        self.SetMinSize(self.GetSize())
        self._populate_labels()
        wx.CallAfter(self._resize_columns)

    def _resolve_config(self, parent: wx.Window | None) -> ConfigManager:
        cfg = getattr(parent, "config", None)
        if cfg is None and parent is not None:
            top = wx.GetTopLevelParent(parent)
            cfg = getattr(top, "config", None) if top is not None else None
        if cfg is None:
            cfg = ConfigManager()
        return cfg

    def _read_include_inherited_default(self) -> bool:
        try:
            value = self._config.get_value(self._include_inherited_key, False)
        except Exception:
            return False
        return bool(value)

    def _write_include_inherited_default(self, value: bool) -> None:
        try:
            self._config.set_value(self._include_inherited_key, bool(value))
            self._config.flush()
        except Exception:
            return

    def _sync_checked_selection(self) -> None:
        for idx in self.list.GetCheckedItems():
            if 0 <= idx < len(self._labels):
                self._selected_keys.add(self._labels[idx].key)

    def _active_labels(self) -> list[LabelDef]:
        source = self._inherited_labels if self._include_inherited else self._local_labels
        return [LabelDef(lbl.key, lbl.title, lbl.color) for lbl in source]

    def _populate_labels(self) -> None:
        self._labels = self._active_labels()
        self.list.DeleteAllItems()
        for lbl in self._labels:
            idx = self.list.InsertItem(self.list.GetItemCount(), lbl.key)
            self.list.SetItem(idx, 1, lbl.title)
            img_idx = self._get_icon_index(label_color(lbl))
            self.list.SetItemColumnImage(idx, 0, img_idx)
            if lbl.key in self._selected_keys:
                self.list.CheckItem(idx)
        self._resize_columns()

    def _on_toggle_inherited(self, event: wx.CommandEvent) -> None:  # pragma: no cover - GUI event
        self._sync_checked_selection()
        self._include_inherited = bool(event.IsChecked())
        self._write_include_inherited_default(self._include_inherited)
        self._populate_labels()

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

    def _resize_columns(self) -> None:
        width = self.list.GetClientSize().width
        if width > 0:
            first = int(width * 0.4)
            self.list.SetColumnWidth(0, first)
            self.list.SetColumnWidth(1, width - first - 4)

    def _on_list_size(self, _event: wx.Event) -> None:  # pragma: no cover - GUI event
        self._resize_columns()

    def get_selected(self) -> list[str]:
        """Return names of checked and custom labels."""
        self._sync_checked_selection()
        names = [
            lbl.key
            for lbl in self._active_labels()
            if lbl.key in self._selected_keys
        ]
        if self.freeform_ctrl:
            extra = [
                t.strip() for t in self.freeform_ctrl.GetValue().split(",") if t.strip()
            ]
            for name in extra:
                if name not in names:
                    names.append(name)
        return names
