"""Dialog for editing project-scoped agent instructions."""

from __future__ import annotations

from pathlib import Path

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

        documents_hint = wx.StaticText(
            self,
            label=_(
                "Documentation folder (optional). Relative paths resolve against the "
                "current requirements directory when one is open."
            ),
        )
        documents_hint.Wrap(dip(self, 360))
        self._documents_path = wx.TextCtrl(
            self,
            value=settings.documents_path,
        )
        browse_label = _("Browse…")
        self._browse_documents = wx.Button(self, label=browse_label)
        self._browse_documents.Bind(wx.EVT_BUTTON, self._on_browse_documents_path)

        documents_row = wx.BoxSizer(wx.HORIZONTAL)
        documents_row.Add(self._documents_path, 1, wx.ALIGN_CENTER_VERTICAL)
        documents_row.AddSpacer(spacing)
        documents_row.Add(self._browse_documents, 0, wx.ALIGN_CENTER_VERTICAL)

        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        ok_button = self.FindWindowById(wx.ID_OK)
        if isinstance(ok_button, wx.Button):
            ok_button.SetDefault()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(message, 0, wx.ALL | wx.EXPAND, spacing)
        sizer.Add(self._prompt, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, spacing)
        sizer.Add(documents_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, spacing)
        sizer.Add(documents_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, spacing)
        if buttons is not None:
            sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, spacing)

        self.SetSizerAndFit(sizer)
        self._prompt.SetFocus()

    def get_custom_system_prompt(self) -> str:
        """Return the configured custom system prompt."""
        return self._prompt.GetValue().strip()

    def get_documents_path(self) -> str:
        """Return the configured documentation directory path."""
        return self._documents_path.GetValue().strip()

    def _on_browse_documents_path(self, _event: wx.Event) -> None:
        dialog = wx.DirDialog(self, _("Select documentation folder"))
        try:
            current = self._documents_path.GetValue().strip()
            if current:
                candidate = Path(current).expanduser()
                if candidate.exists():
                    dialog.SetPath(str(candidate))
        except Exception:
            pass

        if dialog.ShowModal() == wx.ID_OK:
            self._documents_path.SetValue(dialog.GetPath())
        dialog.Destroy()


__all__ = ["AgentProjectSettingsDialog"]

