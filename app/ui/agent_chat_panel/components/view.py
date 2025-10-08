"""Helpers for constructing and updating the agent chat panel view."""

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
        """Capture collaborators used to build and refresh the view."""
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
        primary_btn = state.layout.primary_action_button
        idle_label_text = state.layout.primary_action_idle_label
        idle_uses_bitmap = state.layout.primary_action_idle_uses_bitmap
        idle_bitmap = state.layout.primary_action_idle_bitmap
        idle_disabled_bitmap = state.layout.primary_action_idle_disabled_bitmap
        stop_label_text = state.layout.primary_action_stop_label
        stop_uses_bitmap = state.layout.primary_action_stop_uses_bitmap
        stop_bitmap = state.layout.primary_action_stop_bitmap
        stop_disabled_bitmap = state.layout.primary_action_stop_disabled_bitmap
        input_ctrl = state.layout.input_control
        activity = state.layout.activity_indicator

        input_ctrl.Enable(not active)
        primary_btn.Enable(True)
        send_tooltip = _("Send")
        stop_tooltip = _("Stop")
        if active:
            self._apply_primary_action_visual(
                primary_btn,
                label=stop_label_text,
                uses_bitmap=stop_uses_bitmap,
                bitmap=stop_bitmap,
                disabled_bitmap=stop_disabled_bitmap,
            )
            tooltip = stop_tooltip
        else:
            self._apply_primary_action_visual(
                primary_btn,
                label=idle_label_text,
                uses_bitmap=idle_uses_bitmap,
                bitmap=idle_bitmap,
                disabled_bitmap=idle_disabled_bitmap,
            )
            tooltip = send_tooltip
        primary_btn.SetToolTip(tooltip)

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
    def _set_primary_action_bitmaps(
        self,
        button: wx.Button,
        bitmap: wx.Bitmap,
        disabled_bitmap: wx.Bitmap | None,
    ) -> None:
        """Attach the idle-state bitmaps to the primary action button."""
        if not bitmap or not bitmap.IsOk():
            return

        for attr in (
            "SetBitmap",
            "SetBitmapCurrent",
            "SetBitmapFocus",
            "SetBitmapPressed",
            "SetBitmapHover",
        ):
            setter = getattr(button, attr, None)
            if callable(setter):
                setter(bitmap)

        if disabled_bitmap and disabled_bitmap.IsOk():
            setter = getattr(button, "SetBitmapDisabled", None)
            if callable(setter):
                setter(disabled_bitmap)

        margins = getattr(button, "SetBitmapMargins", None)
        if callable(margins):
            margins(0, 0)

    # ------------------------------------------------------------------
    def _clear_primary_action_bitmaps(self, button: wx.Button) -> None:
        """Remove bitmaps from the primary action button."""
        null_bitmap = wx.NullBitmap
        for attr in (
            "SetBitmap",
            "SetBitmapCurrent",
            "SetBitmapFocus",
            "SetBitmapPressed",
            "SetBitmapHover",
            "SetBitmapDisabled",
        ):
            setter = getattr(button, attr, None)
            if callable(setter):
                setter(null_bitmap)

    # ------------------------------------------------------------------
    def _apply_primary_action_visual(
        self,
        button: wx.Button,
        *,
        label: str,
        uses_bitmap: bool,
        bitmap: wx.Bitmap | None,
        disabled_bitmap: wx.Bitmap | None,
    ) -> None:
        """Apply the requested primary action presentation."""
        if uses_bitmap and bitmap is not None:
            self._set_primary_action_bitmaps(button, bitmap, disabled_bitmap)
        else:
            self._clear_primary_action_bitmaps(button)

        value = label if label else ""
        if button.GetLabel() != value:
            button.SetLabel(value)
            button.InvalidateBestSize()

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
