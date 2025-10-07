"""Dialog for editing project-scoped agent instructions."""

from __future__ import annotations

import wx

from ...i18n import _
from ..helpers import dip, inherit_background
from .project_settings import AgentProjectSettings


class AgentProjectSettingsDialog(wx.Dialog):
    """Modal dialog exposing project-specific agent options."""

    def __init__(self, parent: wx.Window, *, settings: AgentProjectSettings) -> None:
        super().__init__(parent, title=_("Agent instructions"))

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

        documents_label = wx.StaticText(
            self,
            label=_("User documentation folder"),
        )
        documents_hint = wx.StaticText(
            self,
            label=_(
                "Optional path where the agent can read and write project "
                "documentation. Relative values are resolved from the active "
                "requirements folder."
            ),
        )
        documents_hint.Wrap(dip(self, 360))

        self._documents_path = wx.TextCtrl(
            self,
            value=settings.documents_path,
            style=wx.TE_PROCESS_ENTER,
        )
        self._documents_path.SetMinSize(wx.Size(dip(self, 360), -1))
        browse_label = _("Browse…")
        self._documents_browse = wx.Button(self, label=browse_label)
        self._documents_browse.Bind(wx.EVT_BUTTON, self._on_browse_documents_path)

        documents_path_sizer = wx.BoxSizer(wx.HORIZONTAL)
        documents_path_sizer.Add(
            self._documents_path,
            1,
            wx.RIGHT | wx.EXPAND,
            spacing,
        )
        documents_path_sizer.Add(self._documents_browse, 0)

        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        ok_button = self.FindWindowById(wx.ID_OK)
        if isinstance(ok_button, wx.Button):
            ok_button.SetDefault()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(message, 0, wx.ALL | wx.EXPAND, spacing)
        sizer.Add(self._prompt, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, spacing)
        sizer.Add(documents_label, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, spacing)
        sizer.Add(documents_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, spacing)
        sizer.Add(documents_path_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, spacing)
        if buttons is not None:
            sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, spacing)

        self.SetSizerAndFit(sizer)
        self._prompt.SetFocus()

    def get_custom_system_prompt(self) -> str:
        """Return the configured custom system prompt."""

        return self._prompt.GetValue().strip()

    def get_documents_path(self) -> str:
        """Return the configured user documentation path."""

        return self._documents_path.GetValue().strip()

    def _on_browse_documents_path(self, _event: wx.Event) -> None:
        """Ask the user to select a documentation directory."""

        current = self.get_documents_path()
        start_path = current or ""
        style = getattr(wx, "DD_DEFAULT_STYLE", 0) | getattr(wx, "DD_NEW_DIR_BUTTON", 0)
        dialog = wx.DirDialog(
            self,
            _("Select documentation folder"),
            start_path,
            style=style,
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self._documents_path.SetValue(dialog.GetPath())
        finally:
            dialog.Destroy()


__all__ = ["AgentProjectSettingsDialog"]

