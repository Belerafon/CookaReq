"""View layer for the agent chat panel widgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import wx

from ....i18n import _
from ..layout import AgentChatLayout, AgentChatLayoutBuilder
from ..token_usage import TokenCountResult


class WaitStateCallbacks(Protocol):
    """Helpers invoked when wait state toggles."""

    def on_refresh_layout(self) -> None:
        """Recalculate the layout of the bottom panel."""

    def on_focus_input(self) -> None:
        """Give the keyboard focus back to the input control."""


@dataclass(slots=True)
class AgentChatViewState:
    """Expose widgets created for the agent chat panel."""

    layout: AgentChatLayout


class AgentChatView:
    """Encapsulates widget construction and high-level updates."""

    def __init__(
        self,
        panel: wx.Panel,
        *,
        layout_builder: AgentChatLayoutBuilder,
        status_help_text: str,
    ) -> None:
        self._panel = panel
        self._layout_builder = layout_builder
        self._status_help_text = status_help_text
        self._state: AgentChatViewState | None = None

    # ------------------------------------------------------------------
    @property
    def state(self) -> AgentChatViewState:
        """Return the current view state."""

        if self._state is None:
            raise RuntimeError("AgentChatView is not initialized")
        return self._state

    # ------------------------------------------------------------------
    def build(self) -> AgentChatViewState:
        """Construct widgets and store the resulting handles."""

        layout = self._layout_builder.build(status_help_text=self._status_help_text)
        self._state = AgentChatViewState(layout=layout)
        return self._state

    # ------------------------------------------------------------------
    def set_wait_state(
        self,
        active: bool,
        *,
        tokens: TokenCountResult | None = None,
        callbacks: WaitStateCallbacks,
    ) -> None:
        """Reflect busy state in the view."""

        state = self.state
        send_btn = state.layout.send_button
        input_ctrl = state.layout.input_control
        stop_btn = state.layout.stop_button
        activity = state.layout.activity_indicator
        status_label = state.layout.status_label

        send_btn.Enable(not active)
        input_ctrl.Enable(not active)
        if stop_btn is not None:
            stop_btn.Enable(active)

        if active:
            activity.Show()
            activity.Start()
            callbacks.on_refresh_layout()
        else:
            activity.Stop()
            activity.Hide()
            callbacks.on_refresh_layout()
            status_label.SetLabel(_("Ready"))
            callbacks.on_focus_input()

    # ------------------------------------------------------------------
    def update_status_label(self, label: str) -> None:
        """Update the text shown in the status area."""

        self.state.layout.status_label.SetLabel(label)
