"""Dialogs for managing requirement documents."""

from __future__ import annotations

from dataclasses import dataclass
import re

import wx

from ..i18n import _


PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass
class DocumentProperties:
    """Properties describing a requirements document."""

    prefix: str
    title: str
    digits: int


class DocumentPropertiesDialog(wx.Dialog):
    """Prompt user for document properties."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        mode: str,
        prefix: str = "",
        title: str = "",
        digits: int = 3,
        parent_prefix: str | None = None,
    ) -> None:
        if mode not in {"create", "rename"}:
            raise ValueError(f"unsupported mode: {mode}")
        heading = _("New document") if mode == "create" else _("Rename document")
        super().__init__(parent, title=heading)
        self._mode = mode
        self._result: DocumentProperties | None = None
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(0, 2, 5, 5)
        grid.AddGrowableCol(1, 1)

        prefix_label = wx.StaticText(self, label=_("Prefix"))
        grid.Add(prefix_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.prefix_ctrl = wx.TextCtrl(self, value=prefix)
        if mode == "rename":
            self.prefix_ctrl.Enable(False)
        grid.Add(self.prefix_ctrl, 1, wx.EXPAND)

        title_label = wx.StaticText(self, label=_("Title"))
        grid.Add(title_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.title_ctrl = wx.TextCtrl(self, value=title)
        grid.Add(self.title_ctrl, 1, wx.EXPAND)

        digits_label = wx.StaticText(self, label=_("Digits"))
        grid.Add(digits_label, 0, wx.ALIGN_CENTER_VERTICAL)
        max_digits = digits if digits > 0 else 1
        max_digits = max(9, max_digits)
        self.digits_ctrl = wx.SpinCtrl(
            self, min=1, max=max_digits, initial=max(digits, 1)
        )
        grid.Add(self.digits_ctrl, 1, wx.EXPAND)

        parent_label = wx.StaticText(self, label=_("Parent"))
        grid.Add(parent_label, 0, wx.ALIGN_CENTER_VERTICAL)
        parent_value = parent_prefix or _("(top-level)")
        grid.Add(wx.StaticText(self, label=parent_value), 0, wx.ALIGN_CENTER_VERTICAL)

        main_sizer.Add(grid, 0, wx.ALL | wx.EXPAND, 10)

        btn_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        if btn_sizer:
            main_sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        self.SetSizer(main_sizer)
        self.SetMinSize((320, 200))
        if mode == "create":
            self.prefix_ctrl.SetFocus()
        else:
            self.title_ctrl.SetFocus()
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

    def _on_ok(self, event: wx.CommandEvent) -> None:
        prefix = self.prefix_ctrl.GetValue().strip()
        title = self.title_ctrl.GetValue().strip()
        digits = int(self.digits_ctrl.GetValue())
        if self._mode == "create":
            if not prefix:
                wx.MessageBox(_("Document prefix is required."), _("Error"), wx.ICON_ERROR)
                self.prefix_ctrl.SetFocus()
                return
            if not PREFIX_RE.match(prefix):
                wx.MessageBox(
                    _("Prefix must start with a capital letter and contain only letters, digits or underscores."),
                    _("Error"),
                    wx.ICON_ERROR,
                )
                self.prefix_ctrl.SetFocus()
                return
        if digits <= 0:
            wx.MessageBox(_("Digits must be positive."), _("Error"), wx.ICON_ERROR)
            self.digits_ctrl.SetFocus()
            return
        if not title:
            title = prefix
        self._result = DocumentProperties(prefix=prefix, title=title, digits=digits)
        self.EndModal(wx.ID_OK)

    def get_properties(self) -> DocumentProperties | None:
        """Return document properties when dialog was accepted."""

        return self._result
