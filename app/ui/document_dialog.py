"""Dialogs for managing requirement documents."""
from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
import re

import wx

from ..i18n import _
from .helpers import make_help_button


PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass
class DocumentProperties:
    """Properties describing a requirements document."""

    prefix: str
    title: str
    parent: str | None = None


FIELD_HELP = {
    "prefix": _(
        "Short uppercase prefix placed at the beginning of every requirement identifier (for example SYS1)."
        " It is also used for the document directory name. Identifiers are numbered sequentially without leading zeros"
        " (SYS1, SYS2, …). The prefix must start with a capital letter and may contain only ASCII letters, digits or"
        " underscores."
    ),
    "title": _(
        "Human-friendly document name shown in the navigation tree, window titles and exports."
        " When left empty the title defaults to the prefix."
    ),
    "parent": _(
        "Parent document that determines where this entry sits in the hierarchy. The top level is shown as '(top-level)'."
        " Select a parent to place the document under it or choose '(top-level)' to keep it at the root."
    ),
}


class DocumentPropertiesDialog(wx.Dialog):
    """Prompt user for document properties."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        mode: str,
        prefix: str = "",
        title: str = "",
        parent_prefix: str | None = None,
        parent_choices: Sequence[tuple[str | None, str]] | None = None,
    ) -> None:
        """Prepare dialog controls depending on ``mode`` and defaults."""
        if mode not in {"create", "rename"}:
            raise ValueError(f"unsupported mode: {mode}")
        heading = _("New document") if mode == "create" else _("Edit document")
        super().__init__(parent, title=heading)
        self._mode = mode
        self._result: DocumentProperties | None = None
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(0, 3, 5, 5)
        grid.AddGrowableCol(1, 1)

        prefix_label = wx.StaticText(self, label=_("Prefix"))
        grid.Add(prefix_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.prefix_ctrl = wx.TextCtrl(self, value=prefix)
        if mode == "rename":
            self.prefix_ctrl.Enable(False)
        grid.Add(self.prefix_ctrl, 1, wx.EXPAND)
        grid.Add(
            make_help_button(self, FIELD_HELP["prefix"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )

        title_label = wx.StaticText(self, label=_("Title"))
        grid.Add(title_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.title_ctrl = wx.TextCtrl(self, value=title)
        grid.Add(self.title_ctrl, 1, wx.EXPAND)
        grid.Add(
            make_help_button(self, FIELD_HELP["title"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )

        parent_label = wx.StaticText(self, label=_("Parent"))
        grid.Add(parent_label, 0, wx.ALIGN_CENTER_VERTICAL)
        choices: list[tuple[str | None, str]]
        choices = list(parent_choices) if parent_choices else [(None, _("(top-level)"))]
        self._parent_values = [value for value, _ in choices]
        parent_labels = [label for _, label in choices]
        self.parent_ctrl = wx.Choice(self, choices=parent_labels)
        default_selection = 0
        if parent_prefix is not None:
            with suppress(ValueError):
                default_selection = self._parent_values.index(parent_prefix)
        self.parent_ctrl.SetSelection(default_selection)
        grid.Add(self.parent_ctrl, 0, wx.ALIGN_CENTER_VERTICAL | wx.EXPAND)
        grid.Add(
            make_help_button(self, FIELD_HELP["parent"], dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            5,
        )

        main_sizer.Add(grid, 0, wx.ALL | wx.EXPAND, 10)

        btn_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        if btn_sizer:
            main_sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        self.SetSizer(main_sizer)
        self.SetMinSize((320, 180))
        if mode == "create":
            self.prefix_ctrl.SetFocus()
        else:
            self.title_ctrl.SetFocus()
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

    def _on_ok(self, event: wx.CommandEvent) -> None:
        prefix = self.prefix_ctrl.GetValue().strip()
        title = self.title_ctrl.GetValue().strip()
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
        if not title:
            title = prefix
        parent_value = None
        if hasattr(self, "parent_ctrl"):
            selection = self.parent_ctrl.GetSelection()
            if 0 <= selection < len(self._parent_values):
                parent_value = self._parent_values[selection]
        self._result = DocumentProperties(prefix=prefix, title=title, parent=parent_value)
        self.EndModal(wx.ID_OK)

    def get_properties(self) -> DocumentProperties | None:
        """Return document properties when dialog was accepted."""
        return self._result
