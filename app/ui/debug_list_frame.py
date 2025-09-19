"""Auxiliary frame that renders a standalone debug requirement list."""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum

import wx

from ..core.model import Requirement
from ..i18n import _
from . import locale
from .list_panel import ListPanel
from .requirement_model import RequirementModel


class DebugListFrame(wx.Frame):
    """Top-level window with :class:`ListPanel` and raw :class:`wx.ListCtrl`."""

    def __init__(
        self,
        parent: wx.Window | None,
        *,
        columns: Sequence[str],
        requirements: Sequence[Requirement],
    ) -> None:
        """Create a debug frame populated with ``requirements``."""

        super().__init__(parent=parent, title=_("Debug Requirements List"))
        container = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        container.SetSizer(sizer)

        dataset = list(requirements)
        column_fields = list(columns)

        model = RequirementModel()
        self.list_panel = ListPanel(container, model=model)
        self.list_panel.set_columns(column_fields)
        self.list_panel.set_requirements(dataset, {})

        caption = wx.StaticText(
            container,
            label=_("Plain wx.ListCtrl (no custom panel)"),
        )
        caption_font = caption.GetFont()
        if caption_font and hasattr(caption_font, "MakeBold"):
            try:
                caption.SetFont(caption_font.MakeBold())
            except Exception:  # pragma: no cover - backend quirk
                pass

        self.native_list = wx.ListCtrl(container, style=wx.LC_REPORT)
        self._populate_native_list(self.native_list, column_fields, dataset)

        padding = self.FromDIP(8)
        sizer.Add(self.list_panel, 1, wx.EXPAND | wx.ALL, padding)
        sizer.Add(wx.StaticLine(container), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, padding)
        sizer.Add(caption, 0, wx.LEFT | wx.RIGHT | wx.TOP, padding)
        sizer.Add(self.native_list, 1, wx.EXPAND | wx.ALL, padding)

        self.SetMinSize(self.FromDIP((600, 360)))
        container.Layout()
        self.Layout()

    def _populate_native_list(
        self,
        ctrl: wx.ListCtrl,
        columns: Sequence[str],
        requirements: Sequence[Requirement],
    ) -> None:
        """Populate ``ctrl`` with ``requirements`` mirroring ``ListPanel`` display."""

        ctrl.ClearAll()
        ctrl.InsertColumn(0, _("Title"))
        for field in columns:
            ctrl.InsertColumn(ctrl.GetColumnCount(), locale.field_label(field))

        for index, req in enumerate(requirements):
            title = getattr(req, "title", "")
            ctrl.InsertItem(index, str(title))
            for offset, field in enumerate(columns, start=1):
                value = getattr(req, field, "")
                if isinstance(value, Enum):
                    value = locale.code_to_label(field, value.value)
                elif isinstance(value, list):
                    value = ", ".join(str(item) for item in value)
                ctrl.SetItem(index, offset, str(value))

        autosize = getattr(wx, "LIST_AUTOSIZE", None)
        if autosize is not None:
            for col in range(ctrl.GetColumnCount()):
                try:
                    ctrl.SetColumnWidth(col, autosize)
                except Exception:  # pragma: no cover - backend quirk
                    fallback = getattr(wx, "LIST_AUTOSIZE_USEHEADER", None)
                    if fallback is None:
                        continue
                    try:
                        ctrl.SetColumnWidth(col, fallback)
                    except Exception:
                        continue
