"""Dialog for editing project-scoped agent settings."""

from __future__ import annotations

import wx

from ...i18n import _
from ..helpers import dip, inherit_background
from .project_settings import AgentProjectSettings


class AgentProjectSettingsDialog(wx.Dialog):
    """Modal dialog exposing project-specific agent options."""

    def __init__(self, parent: wx.Window, *, settings: AgentProjectSettings) -> None:
        super().__init__(parent, title=_("Agent settings"))

        inherit_background(self, parent)
        spacing = dip(self, 6)

        message = wx.StaticText(
            self,
            label=_(
                "Custom instructions are appended to the agent's system prompt for "
                "this project. Use them to encode domain conventions, coding "
                "standards or policies the assistant must follow."
            ),
        )
        message.Wrap(dip(self, 360))

        text_style = wx.TE_MULTILINE
        if hasattr(wx, "TE_RICH2"):
            text_style |= wx.TE_RICH2
        self._prompt = wx.TextCtrl(
            self,
            value=settings.custom_system_prompt,
            style=text_style,
        )
        self._prompt.SetMinSize(wx.Size(dip(self, 360), dip(self, 160)))

        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        ok_button = self.FindWindowById(wx.ID_OK)
        if isinstance(ok_button, wx.Button):
            ok_button.SetDefault()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(message, 0, wx.ALL | wx.EXPAND, spacing)
        sizer.Add(self._prompt, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, spacing)
        if buttons is not None:
            sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, spacing)

        self.SetSizerAndFit(sizer)
        self._prompt.SetFocus()

    def get_custom_system_prompt(self) -> str:
        """Return the configured custom system prompt."""

        return self._prompt.GetValue().strip()


__all__ = ["AgentProjectSettingsDialog"]

