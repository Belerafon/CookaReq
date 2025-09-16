"""Dialog for selecting labels with color icons."""

import wx
from contextlib import suppress

from ..core.document_store import LabelDef, label_color
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
    ):
        """Initialize dialog listing ``labels`` with ``selected`` prechecked.

        When ``allow_freeform`` is ``True`` an additional text field accepts
        comma-separated custom label names.
        """
        style = wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        super().__init__(parent, title=_("Labels"), style=style)
        self._labels = [LabelDef(lbl.key, lbl.title, lbl.color) for lbl in labels]
        self._allow_freeform = allow_freeform

        self.list = _CheckListCtrl(self)
        self.list.InsertColumn(0, _("Key"))
        self.list.InsertColumn(1, _("Title"))

        self._img_list = wx.ImageList(16, 16)
        self._color_icons: dict[str, int] = {}
        self.list.AssignImageList(self._img_list, wx.IMAGE_LIST_SMALL)

        for lbl in self._labels:
            idx = self.list.InsertItem(self.list.GetItemCount(), lbl.key)
            self.list.SetItem(idx, 1, lbl.title)
            img_idx = self._get_icon_index(label_color(lbl))
            self.list.SetItemColumnImage(idx, 0, img_idx)
            if lbl.key in selected:
                self.list.CheckItem(idx)

        self.list.Bind(wx.EVT_SIZE, self._on_list_size)

        sizer = wx.BoxSizer(wx.VERTICAL)
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
        names = [self._labels[i].key for i in self.list.GetCheckedItems()]
        if self.freeform_ctrl:
            extra = [
                t.strip() for t in self.freeform_ctrl.GetValue().split(",") if t.strip()
            ]
            for name in extra:
                if name not in names:
                    names.append(name)
        return names
