"""View layer for the agent chat panel widgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import wx

from ....i18n import _
from ..layout import AgentChatLayout, AgentChatLayoutBuilder
from ..token_usage import (
    TOKEN_UNAVAILABLE_LABEL,
    TokenCountResult,
    summarize_token_usage,
)


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
        context_limit: int | None = None,
        callbacks: WaitStateCallbacks,
    ) -> None:
        """Reflect busy state in the view."""

        state = self.state
        send_btn = state.layout.send_button
        input_ctrl = state.layout.input_control
        stop_btn = state.layout.stop_button
        activity = state.layout.activity_indicator

        send_btn.Enable(not active)
        input_ctrl.Enable(not active)
        if stop_btn is not None:
            stop_btn.Enable(active)

        if active:
            activity.Show()
            activity.Start()
            self.update_status_label(
                self._build_running_status(tokens, context_limit)
            )
            callbacks.on_refresh_layout()
        else:
            activity.Stop()
            activity.Hide()
            self.update_status_label(
                self._build_ready_status(tokens, context_limit)
            )
            callbacks.on_refresh_layout()
            callbacks.on_focus_input()

    # ------------------------------------------------------------------
    def update_status_label(self, label: str) -> None:
        """Update the text shown in the status area."""

        self.state.layout.status_label.SetLabel(label)

    # ------------------------------------------------------------------
    def update_wait_status(
        self,
        elapsed: float,
        tokens: TokenCountResult | None,
        context_limit: int | None,
    ) -> None:
        """Show running timer alongside prompt token summary."""

        minutes, seconds = divmod(int(elapsed), 60)
        base = _("Waiting for agent… {time}").format(
            time=f"{minutes:02d}:{seconds:02d}",
        )
        if tokens is None:
            self.update_status_label(base)
            return
        details = summarize_token_usage(tokens, context_limit)
        if details == TOKEN_UNAVAILABLE_LABEL and context_limit is None:
            self.update_status_label(base)
            return
        combined = _("{base} — {details}").format(base=base, details=details)
        self.update_status_label(combined)

    # ------------------------------------------------------------------
    def _build_ready_status(
        self,
        tokens: TokenCountResult | None,
        context_limit: int | None,
    ) -> str:
        """Return label for the ready state."""

        base = _("Ready")
        if tokens is None:
            return base
        details = summarize_token_usage(tokens, context_limit)
        if details == TOKEN_UNAVAILABLE_LABEL and context_limit is None:
            return base
        return _("{base} — {details}").format(base=base, details=details)

    # ------------------------------------------------------------------
    def _build_running_status(
        self,
        tokens: TokenCountResult | None,
        context_limit: int | None,
    ) -> str:
        """Return label for the initial running state."""

        if tokens is None:
            return _("Waiting for agent… {time}").format(time="00:00")
        details = summarize_token_usage(tokens, context_limit)
        if details == TOKEN_UNAVAILABLE_LABEL and context_limit is None:
            return _("Waiting for agent… {time}").format(time="00:00")
        base = _("Waiting for agent… {time}").format(time="00:00")
        return _("{base} — {details}").format(base=base, details=details)
