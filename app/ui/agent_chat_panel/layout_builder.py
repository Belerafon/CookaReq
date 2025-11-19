"""UI composition helpers extracted from :mod:`panel`."""
from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

import wx

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .panel import AgentChatPanel


@dataclass(slots=True)
class PanelLayoutState:
    """Aggregate layout handles returned after building the UI."""

    layout: object
    layout_root: wx.Sizer


class AgentChatPanelLayoutBuilder:
    """Build widgets and keep splitter/column observers together."""

    def __init__(self, panel: AgentChatPanel) -> None:
        self._panel = panel
        self._history_list_window: wx.Window | None = None
        self._history_main_window: wx.Window | None = None
        self._history_column_widths: tuple[int, ...] | None = None
        self._history_column_refresh_scheduled = False

    # ------------------------------------------------------------------
    def build(self) -> PanelLayoutState:
        """Construct the UI tree for the owning panel."""
        panel = self._panel
        state = panel._view.build()
        layout = state.layout
        panel._layout = layout
        panel._vertical_splitter = layout.vertical_splitter
        panel._horizontal_splitter = layout.horizontal_splitter
        panel._history_panel = layout.history_panel
        panel.history_list = layout.history_list
        panel._history_view = layout.history_view
        panel._new_chat_btn = layout.new_chat_button
        panel._conversation_label = layout.conversation_label
        panel._copy_conversation_btn = layout.copy_conversation_button
        panel._copy_transcript_log_btn = layout.copy_log_button
        panel.transcript_panel = layout.transcript_scroller
        panel._transcript_sizer = layout.transcript_sizer
        panel._transcript_view = layout.transcript_view
        panel._transcript_selection_probe = wx.TextCtrl(
            panel,
            style=(
                wx.TE_MULTILINE
                | wx.TE_READONLY
                | wx.TE_WORDWRAP
                | wx.TE_NO_VSCROLL
                | wx.BORDER_NONE
            ),
        )
        panel._transcript_selection_probe.Hide()
        panel._bottom_panel = layout.bottom_panel
        panel._bottom_controls_panel = layout.bottom_inner_panel
        panel._attachment_button = layout.attachment_button
        panel._attachment_summary = layout.attachment_summary
        panel._clear_input_button = layout.clear_button
        panel._run_batch_button = layout.run_batch_button
        panel._stop_batch_button = layout.stop_batch_button
        panel._bottom_controls_wrap = layout.controls_wrap
        panel.input = layout.input_control
        panel._queued_prompt_panel = layout.queued_panel
        panel._queued_prompt_label = layout.queued_message
        panel._queued_prompt_cancel = layout.queued_cancel_button
        layout.queued_cancel_button.Bind(wx.EVT_BUTTON, panel._on_cancel_queued_prompt)
        panel._primary_action_btn = layout.primary_action_button
        panel._batch_controls = layout.batch_controls
        panel.activity = layout.activity_indicator
        panel.status_label = layout.status_label
        panel._project_settings_button = layout.project_settings_button
        panel._confirm_label = layout.confirm_label
        panel._confirm_choice = layout.confirm_choice
        panel._confirm_choice_entries = layout.confirm_entries
        panel._confirm_choice_index = layout.confirm_choice_index

        panel._update_confirm_choice_ui(panel._confirm_preference)
        panel._history_last_sash = panel._horizontal_splitter.GetSashPosition()
        panel._vertical_last_sash = panel._vertical_splitter.GetSashPosition()
        panel._update_conversation_header()
        panel._refresh_history_list()
        wx.CallAfter(panel._adjust_vertical_splitter)
        wx.CallAfter(panel._update_project_settings_ui)
        wx.CallAfter(panel._update_attachment_summary)
        wx.CallAfter(panel._update_queued_prompt_banner)
        panel._apply_pending_session_running_state()

        self._observe_history_columns(panel.history_list)
        return PanelLayoutState(layout=layout, layout_root=layout.outer_sizer)

    def start_history_observation(self, history_list: wx.Window) -> None:
        """Allow the orchestrator to restart observation after rebuild."""
        self._observe_history_columns(history_list)

    # ------------------------------------------------------------------
    def cleanup(self) -> None:
        """Detach observers when the panel is destroyed."""
        self._unbind_history_column_observers()

    # ------------------------------------------------------------------
    def history_column_widths(self) -> tuple[int, ...]:
        return self._history_column_widths or ()

    # ------------------------------------------------------------------
    def refresh_history_columns(self) -> None:
        """Force the dataview to repaint after column resize."""
        history_list = getattr(self._panel, "history_list", None)
        if history_list is None:
            return
        history_list.Refresh()
        history_list.Update()
        get_main = getattr(history_list, "GetMainWindow", None)
        if callable(get_main):
            main_window = get_main()
            if isinstance(main_window, wx.Window):
                main_window.Refresh()
                main_window.Update()

    # ------------------------------------------------------------------
    def _observe_history_columns(self, history_list: wx.Window) -> None:
        self._unbind_history_column_observers()
        self._history_list_window = history_list
        self._history_column_widths = self._current_history_column_widths(history_list)
        with suppress(Exception):
            history_list.Unbind(wx.EVT_IDLE, handler=self._on_history_list_idle)
        history_list.Bind(wx.EVT_IDLE, self._on_history_list_idle)
        self._bind_history_main_window(history_list)
        self._detect_history_column_change()

    def _bind_history_main_window(self, history_list: wx.Window) -> None:
        getter = getattr(history_list, "GetMainWindow", None)
        window = getter() if callable(getter) else None
        if not isinstance(window, wx.Window):
            self._history_main_window = None
            return
        with suppress(Exception):
            window.Unbind(wx.EVT_IDLE, handler=self._on_history_main_window_idle)
        window.Bind(wx.EVT_IDLE, self._on_history_main_window_idle)
        self._history_main_window = window

    def _unbind_history_column_observers(self) -> None:
        if self._history_list_window is not None:
            with suppress(Exception):
                self._history_list_window.Unbind(
                    wx.EVT_IDLE, handler=self._on_history_list_idle
                )
        if self._history_main_window is not None:
            with suppress(Exception):
                self._history_main_window.Unbind(
                    wx.EVT_IDLE, handler=self._on_history_main_window_idle
                )
        self._history_list_window = None
        self._history_main_window = None

    def _on_history_list_idle(self, event: wx.IdleEvent) -> None:
        event.Skip()
        self._detect_history_column_change()

    def _on_history_main_window_idle(self, event: wx.IdleEvent) -> None:
        event.Skip()
        self._detect_history_column_change()

    def _current_history_column_widths(
        self, history_list: wx.Window | None = None
    ) -> tuple[int, ...]:
        target = history_list
        if target is None:
            target = getattr(self, "history_list", None)
        if target is None:
            target = self._history_list_window
        if target is None:
            return ()
        count_getter = getattr(target, "GetColumnCount", None)
        column_getter = getattr(target, "GetColumn", None)
        if not callable(count_getter) or not callable(column_getter):
            return ()
        widths: list[int] = []
        count = count_getter()
        for index in range(count):
            column = column_getter(index)
            if column is None:
                continue
            with suppress(Exception):
                widths.append(int(column.GetWidth()))
        return tuple(widths)

    def _detect_history_column_change(self) -> None:
        widths = self._current_history_column_widths()
        if widths != self._history_column_widths:
            self._history_column_widths = widths
            if widths:
                self._schedule_history_column_refresh()

    def _schedule_history_column_refresh(self) -> None:
        if self._history_column_refresh_scheduled:
            return
        self._history_column_refresh_scheduled = True
        wx.CallAfter(self._refresh_history_columns)

    def _refresh_history_columns(self) -> None:
        self._history_column_refresh_scheduled = False
        self.refresh_history_columns()


__all__ = ["AgentChatPanelLayoutBuilder", "PanelLayoutState"]
