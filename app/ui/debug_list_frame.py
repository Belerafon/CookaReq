"""Auxiliary frame that renders a standalone debug requirement list."""

from __future__ import annotations

from collections.abc import Sequence

import wx

from ..core.model import Requirement
from ..i18n import _
from .list_panel import ListPanel
from .requirement_model import RequirementModel


class DebugListFrame(wx.Frame):
    """Top-level window hosting an isolated :class:`ListPanel`."""

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

        model = RequirementModel()
        self.list_panel = ListPanel(container, model=model)
        self.list_panel.set_columns(list(columns))
        self.list_panel.set_requirements(list(requirements), {})

        sizer.Add(self.list_panel, 1, wx.EXPAND)
        self.SetMinSize(self.FromDIP((600, 360)))
        container.Layout()
        self.Layout()
