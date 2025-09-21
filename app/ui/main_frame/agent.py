"""Agent chat helpers for the main frame."""

from __future__ import annotations

from typing import TYPE_CHECKING

import wx

from ...agent import LocalAgent
from ...settings import AppSettings

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from .frame import MainFrame


class MainFrameAgentMixin:
    """Provide agent chat integration and shortcuts."""

    def _create_agent(self: "MainFrame") -> LocalAgent:
        """Construct ``LocalAgent`` using current settings."""

        from . import confirm

        settings = AppSettings(llm=self.llm_settings, mcp=self.mcp_settings)
        return LocalAgent(settings=settings, confirm=confirm)

    def on_run_command(self: "MainFrame", _event: wx.Event) -> None:
        """Ensure agent chat panel is visible and focused."""

        if not self.agent_chat_menu_item:
            return
        if not self.agent_chat_menu_item.IsChecked():
            self.agent_chat_menu_item.Check(True)
            self.on_toggle_agent_chat(None)
        else:
            self._apply_agent_chat_visibility(persist=False)

    def on_toggle_agent_chat(self: "MainFrame", _event: wx.CommandEvent | None) -> None:
        """Toggle agent chat panel visibility."""

        if not self.agent_chat_menu_item:
            return
        self._apply_agent_chat_visibility(persist=True)
