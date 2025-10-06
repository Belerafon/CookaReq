"""Layout helpers for :class:`AgentChatPanel`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import wx
import wx.dataview as dv
from wx.lib.scrolledpanel import ScrolledPanel

from ...i18n import _
from ..helpers import create_copy_button, dip, inherit_background
from ..splitter_utils import refresh_splitter_highlight, style_splitter
from ..widgets.marquee_dataview import MarqueeDataViewListCtrl
from .batch_ui import BatchControls
from .confirm_preferences import RequirementConfirmPreference
from .history_view import HistoryView
from .segment_view import SegmentListView, SegmentViewCallbacks

if TYPE_CHECKING:  # pragma: no cover - type hints only
    from .panel import AgentChatPanel


@dataclass(slots=True)
class AgentChatLayout:
    """Container describing widgets constructed for the chat panel."""

    outer_sizer: wx.BoxSizer
    vertical_splitter: wx.SplitterWindow
    horizontal_splitter: wx.SplitterWindow
    history_panel: wx.Panel
    history_view: HistoryView
    history_list: MarqueeDataViewListCtrl
    new_chat_button: wx.Button
    conversation_label: wx.StaticText
    copy_conversation_button: wx.Window
    copy_log_button: wx.Window
    transcript_container: wx.Panel
    transcript_scroller: ScrolledPanel
    transcript_sizer: wx.BoxSizer
    transcript_view: SegmentListView
    bottom_panel: wx.Panel
    input_control: wx.TextCtrl
    stop_button: wx.Button
    send_button: wx.Button
    batch_controls: BatchControls
    activity_indicator: wx.ActivityIndicator
    status_label: wx.StaticText
    project_settings_button: wx.Button
    confirm_choice: wx.Choice
    confirm_entries: tuple[tuple[RequirementConfirmPreference, str], ...]
    confirm_choice_index: dict[RequirementConfirmPreference, int]


class AgentChatLayoutBuilder:
    """Build and configure widgets composing :class:`AgentChatPanel`."""

    def __init__(self, panel: AgentChatPanel) -> None:
        self._panel = panel

    def build(self, *, status_help_text: str) -> AgentChatLayout:
        panel = self._panel
        spacing = dip(panel, 5)

        outer = wx.BoxSizer(wx.VERTICAL)
        splitter_style = wx.SP_LIVE_UPDATE | wx.SP_3D

        vertical_splitter = wx.SplitterWindow(panel, style=splitter_style)
        style_splitter(vertical_splitter)
        vertical_splitter.SetMinimumPaneSize(dip(panel, 160))

        top_panel = wx.Panel(vertical_splitter)
        bottom_panel = wx.Panel(vertical_splitter)
        inherit_background(top_panel, panel)
        inherit_background(bottom_panel, panel)

        horizontal_splitter = wx.SplitterWindow(top_panel, style=splitter_style)
        style_splitter(horizontal_splitter)
        history_min_width = dip(panel, 260)
        horizontal_splitter.SetMinimumPaneSize(history_min_width)

        history_panel = wx.Panel(horizontal_splitter)
        inherit_background(history_panel, panel)
        history_sizer = wx.BoxSizer(wx.VERTICAL)
        history_header = wx.BoxSizer(wx.HORIZONTAL)
        history_label = wx.StaticText(history_panel, label=_("Chats"))
        new_chat_btn = wx.Button(history_panel, label=_("New chat"))
        new_chat_btn.Bind(wx.EVT_BUTTON, panel._on_new_chat)
        history_header.Add(history_label, 1, wx.ALIGN_CENTER_VERTICAL)
        history_header.Add(new_chat_btn, 0, wx.ALIGN_CENTER_VERTICAL)
        history_style = dv.DV_MULTIPLE | dv.DV_ROW_LINES | dv.DV_VERT_RULES
        history_list = MarqueeDataViewListCtrl(history_panel, style=history_style)
        history_list.SetMinSize(wx.Size(dip(panel, 260), -1))
        title_col = history_list.AppendTextColumn(
            _("Title"), mode=dv.DATAVIEW_CELL_INERT, width=dip(panel, 180)
        )
        title_col.SetMinWidth(dip(panel, 140))
        activity_col = history_list.AppendTextColumn(
            _("Last activity"), mode=dv.DATAVIEW_CELL_INERT, width=dip(panel, 140)
        )
        activity_col.SetMinWidth(dip(panel, 120))

        history_view = HistoryView(
            history_list,
            get_conversations=lambda: panel.conversations,
            format_row=panel._format_conversation_row,
            get_active_index=panel._active_index,
            activate_conversation=panel._on_history_row_activated,
            handle_delete_request=panel._delete_history_rows,
            is_running=lambda: panel.is_running,
            splitter=horizontal_splitter,
            prepare_interaction=panel._prepare_history_interaction,
        )
        panel._attach_history_header_events(history_list)

        history_sizer.Add(history_header, 0, wx.EXPAND)
        history_sizer.AddSpacer(spacing)
        history_sizer.Add(history_list, 1, wx.EXPAND)
        history_panel.SetSizer(history_sizer)

        transcript_container = wx.Panel(horizontal_splitter)
        transcript_sizer = wx.BoxSizer(wx.VERTICAL)
        transcript_header = wx.BoxSizer(wx.HORIZONTAL)
        conversation_label = wx.StaticText(
            transcript_container, label=_("Conversation")
        )
        transcript_header.Add(conversation_label, 0, wx.ALIGN_CENTER_VERTICAL)
        transcript_header.AddStretchSpacer()
        copy_conversation_btn = create_copy_button(
            transcript_container,
            tooltip=_("Copy conversation"),
            fallback_label=_("Copy conversation"),
            handler=panel._on_copy_conversation,
        )
        copy_conversation_btn.Enable(False)
        transcript_header.Add(copy_conversation_btn, 0, wx.ALIGN_CENTER_VERTICAL)
        transcript_header.AddSpacer(dip(panel, 4))
        copy_log_btn = create_copy_button(
            transcript_container,
            tooltip=_("Copy technical log"),
            fallback_label=_("Copy technical log"),
            handler=panel._on_copy_transcript_log,
        )
        copy_log_btn.Enable(False)
        transcript_header.Add(copy_log_btn, 0, wx.ALIGN_CENTER_VERTICAL)

        transcript_scroller = ScrolledPanel(
            transcript_container,
            style=wx.TAB_TRAVERSAL,
        )
        inherit_background(transcript_container, panel)
        inherit_background(transcript_scroller, transcript_container)
        transcript_scroller.SetupScrolling(scroll_x=False, scroll_y=True)
        transcript_box = wx.BoxSizer(wx.VERTICAL)
        transcript_scroller.SetSizer(transcript_box)

        transcript_view = SegmentListView(
            panel,
            transcript_scroller,
            transcript_box,
            callbacks=SegmentViewCallbacks(
                get_conversation=panel._get_active_conversation_loaded,
                is_running=lambda: panel.is_running,
                on_regenerate=panel._handle_regenerate_request,
                update_copy_buttons=panel._update_transcript_copy_buttons,
                update_header=panel._update_conversation_header,
            ),
        )

        transcript_sizer.Add(transcript_header, 0, wx.EXPAND)
        transcript_sizer.AddSpacer(spacing)
        transcript_sizer.Add(transcript_scroller, 1, wx.EXPAND)
        transcript_container.SetSizer(transcript_sizer)

        horizontal_splitter.SplitVertically(history_panel, transcript_container, history_min_width)
        horizontal_splitter.SetSashGravity(1.0)
        horizontal_splitter.Bind(wx.EVT_SIZE, panel._on_history_splitter_size)
        horizontal_splitter.Bind(
            wx.EVT_SPLITTER_SASH_POS_CHANGED, panel._on_history_sash_changed
        )

        top_sizer = wx.BoxSizer(wx.VERTICAL)
        top_sizer.Add(horizontal_splitter, 1, wx.EXPAND)
        top_panel.SetSizer(top_sizer)

        bottom_sizer = wx.BoxSizer(wx.VERTICAL)
        bottom_sizer.Add(wx.StaticLine(bottom_panel), 0, wx.EXPAND)
        bottom_sizer.AddSpacer(spacing)

        input_label = wx.StaticText(bottom_panel, label=_("Ask the agent"))
        input_ctrl = wx.TextCtrl(
            bottom_panel, style=wx.TE_PROCESS_ENTER | wx.TE_MULTILINE
        )
        if hasattr(input_ctrl, "SetHint"):
            input_ctrl.SetHint(_("Describe what you need the agent to do"))
        input_ctrl.Bind(wx.EVT_TEXT_ENTER, panel._on_send)

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        run_batch_btn = wx.Button(bottom_panel, label=_("Run batch"))
        stop_batch_btn = wx.Button(bottom_panel, label=_("Stop batch"))
        stop_batch_btn.Enable(False)
        clear_btn = wx.Button(bottom_panel, label=_("Clear input"))
        clear_btn.Bind(wx.EVT_BUTTON, panel._on_clear_input)
        stop_btn = wx.Button(bottom_panel, label=_("Stop"))
        stop_btn.Enable(False)
        stop_btn.Bind(wx.EVT_BUTTON, panel._on_stop)
        send_btn = wx.Button(bottom_panel, label=_("Send"))
        send_btn.Bind(wx.EVT_BUTTON, panel._on_send)
        button_row.Add(run_batch_btn, 0, wx.RIGHT, spacing)
        button_row.Add(stop_batch_btn, 0, wx.RIGHT, spacing)
        button_row.Add(clear_btn, 0, wx.RIGHT, spacing)
        button_row.Add(stop_btn, 0, wx.RIGHT, spacing)
        button_row.Add(send_btn, 0)

        batch_panel = wx.Panel(bottom_panel)
        inherit_background(batch_panel, bottom_panel)
        batch_box = wx.StaticBoxSizer(wx.VERTICAL, batch_panel, _("Batch queue"))
        batch_status_label = wx.StaticText(
            batch_panel, label=_("Select requirements and run a batch")
        )
        batch_progress = wx.Gauge(batch_panel, range=1, style=wx.GA_HORIZONTAL)
        batch_progress.SetValue(0)
        batch_progress.SetMinSize(wx.Size(-1, dip(panel, 12)))
        batch_list = dv.DataViewListCtrl(batch_panel, style=dv.DV_ROW_LINES | dv.DV_VERT_RULES)
        batch_list.SetMinSize(wx.Size(-1, dip(panel, 140)))
        batch_list.AppendTextColumn(_("RID"), mode=dv.DATAVIEW_CELL_INERT, width=dip(panel, 120))
        batch_list.AppendTextColumn(_("Title"), mode=dv.DATAVIEW_CELL_INERT, width=dip(panel, 200))
        batch_list.AppendTextColumn(_("Status"), mode=dv.DATAVIEW_CELL_INERT, width=dip(panel, 220))
        batch_box.Add(batch_status_label, 0, wx.BOTTOM, spacing)
        batch_box.Add(batch_progress, 0, wx.EXPAND | wx.BOTTOM, spacing)
        batch_box.Add(batch_list, 1, wx.EXPAND)
        batch_panel.SetSizer(batch_box)
        batch_panel.Hide()

        activity_indicator = wx.ActivityIndicator(bottom_panel)
        activity_indicator.Hide()
        status_label = wx.StaticText(bottom_panel, label=_("Ready"))
        status_row = wx.BoxSizer(wx.HORIZONTAL)
        status_row.Add(
            activity_indicator, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, spacing
        )
        status_row.Add(status_label, 0, wx.ALIGN_CENTER_VERTICAL)
        activity_indicator.SetToolTip(status_help_text)
        status_label.SetToolTip(status_help_text)

        settings_btn = wx.Button(bottom_panel, label=_("Agent instructions"))
        settings_btn.Bind(wx.EVT_BUTTON, panel._on_project_settings)

        confirm_entries: tuple[tuple[RequirementConfirmPreference, str], ...] = (
            (RequirementConfirmPreference.PROMPT, _("Ask every time")),
            (
                RequirementConfirmPreference.CHAT_ONLY,
                _("Skip for this chat"),
            ),
            (RequirementConfirmPreference.NEVER, _("Never ask")),
        )
        confirm_choice = wx.Choice(
            bottom_panel,
            choices=[label for _pref, label in confirm_entries],
        )
        confirm_choice.Bind(wx.EVT_CHOICE, panel._on_confirm_choice)
        confirm_choice_index = {
            pref: idx for idx, (pref, _label) in enumerate(confirm_entries)
        }
        confirm_label = wx.StaticText(
            bottom_panel, label=_("Requirement confirmations")
        )
        confirm_row = wx.BoxSizer(wx.HORIZONTAL)
        confirm_row.Add(
            confirm_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, dip(panel, 4)
        )
        confirm_row.Add(confirm_choice, 0, wx.ALIGN_CENTER_VERTICAL)

        controls_row = wx.BoxSizer(wx.HORIZONTAL)
        controls_row.Add(status_row, 0, wx.ALIGN_CENTER_VERTICAL)
        controls_row.AddStretchSpacer()
        controls_row.Add(settings_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, spacing)
        controls_row.Add(confirm_row, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, spacing)
        controls_row.Add(button_row, 0, wx.ALIGN_CENTER_VERTICAL)

        bottom_sizer.Add(input_label, 0)
        bottom_sizer.AddSpacer(spacing)
        bottom_sizer.Add(input_ctrl, 1, wx.EXPAND)
        bottom_sizer.AddSpacer(spacing)
        bottom_sizer.Add(batch_panel, 0, wx.EXPAND)
        bottom_sizer.AddSpacer(spacing)
        bottom_sizer.Add(controls_row, 0, wx.EXPAND)
        bottom_sizer.AddSpacer(spacing)
        bottom_panel.SetSizer(bottom_sizer)

        vertical_splitter.SplitHorizontally(top_panel, bottom_panel)
        vertical_splitter.SetSashGravity(1.0)
        vertical_splitter.Bind(
            wx.EVT_SPLITTER_SASH_POS_CHANGED, panel._on_vertical_sash_changed
        )

        outer.Add(vertical_splitter, 1, wx.EXPAND)
        panel.SetSizer(outer)
        refresh_splitter_highlight(horizontal_splitter)
        refresh_splitter_highlight(vertical_splitter)

        batch_controls = BatchControls(
            panel=batch_panel,
            run_button=run_batch_btn,
            stop_button=stop_batch_btn,
            status_label=batch_status_label,
            progress=batch_progress,
            list_ctrl=batch_list,
        )

        return AgentChatLayout(
            outer_sizer=outer,
            vertical_splitter=vertical_splitter,
            horizontal_splitter=horizontal_splitter,
            history_panel=history_panel,
            history_view=history_view,
            history_list=history_list,
            new_chat_button=new_chat_btn,
            conversation_label=conversation_label,
            copy_conversation_button=copy_conversation_btn,
            copy_log_button=copy_log_btn,
            transcript_container=transcript_container,
            transcript_scroller=transcript_scroller,
            transcript_sizer=transcript_box,
            transcript_view=transcript_view,
            bottom_panel=bottom_panel,
            input_control=input_ctrl,
            stop_button=stop_btn,
            send_button=send_btn,
            batch_controls=batch_controls,
            activity_indicator=activity_indicator,
            status_label=status_label,
            project_settings_button=settings_btn,
            confirm_choice=confirm_choice,
            confirm_entries=confirm_entries,
            confirm_choice_index=confirm_choice_index,
        )


__all__ = ["AgentChatLayout", "AgentChatLayoutBuilder"]

