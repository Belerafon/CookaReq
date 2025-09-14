"""Dialog for selecting labels with color icons."""
import wx
from wx.lib.mixins.listctrl import CheckListCtrlMixin

from ..core.labels import Label
from ..i18n import _


class _CheckListCtrl(wx.ListCtrl, CheckListCtrlMixin):
    """ListCtrl with checkboxes."""

    def __init__(self, parent: wx.Window):
        wx.ListCtrl.__init__(self, parent, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        CheckListCtrlMixin.__init__(self)


class LabelSelectionDialog(wx.Dialog):
    """Dialog allowing to choose labels while displaying their colors."""

    def __init__(self, parent: wx.Window | None, labels: list[Label], selected: list[str]):
        """Initialize dialog listing ``labels`` with ``selected`` prechecked."""
        style = wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        super().__init__(parent, title=_("Labels"), style=style)
        self._labels = list(labels)

        self.list = _CheckListCtrl(self)
        self.list.InsertColumn(0, _("Name"))

        self._img_list = wx.ImageList(16, 16)
        self._color_icons: dict[str, int] = {}
        self.list.AssignImageList(self._img_list, wx.IMAGE_LIST_SMALL)

        for lbl in self._labels:
            idx = self.list.InsertItem(self.list.GetItemCount(), lbl.name)
            img_idx = self._get_icon_index(lbl.color)
            self.list.SetItemColumnImage(idx, 0, img_idx)
            if lbl.name in selected:
                self.list.CheckItem(idx)

        self.list.Bind(wx.EVT_SIZE, self._on_list_size)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)
        btn_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        if btn_sizer:
            sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        self.SetSizer(sizer)
        sizer.Fit(self)
        self.SetMinSize(self.GetSize())
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

    def _resize_column(self) -> None:
        width = self.list.GetClientSize().width
        if width > 0:
            self.list.SetColumnWidth(0, width - 4)

    def _on_list_size(self, _event: wx.Event) -> None:  # pragma: no cover - GUI event
        self._resize_column()

    def get_selected(self) -> list[str]:
        """Return names of checked labels."""
        return [self._labels[i].name for i in self.list.GetCheckedItems()]
