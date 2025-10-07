"""Layout helpers for :class:`AgentChatPanel`."""

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent
from typing import TYPE_CHECKING, Callable, Sequence

import wx
import wx.dataview as dv
from wx.lib.scrolledpanel import ScrolledPanel

from ...i18n import _
from ..helpers import create_copy_button, dip, inherit_background
from ..splitter_utils import refresh_splitter_highlight, style_splitter
from ..widgets import SectionContainer
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
    attachment_button: wx.Button
    attachment_summary: wx.StaticText
    input_control: wx.TextCtrl
    primary_action_button: wx.Button
    primary_action_idle_label: str
    primary_action_idle_uses_bitmap: bool
    primary_action_idle_bitmap: wx.Bitmap | None
    primary_action_idle_disabled_bitmap: wx.Bitmap | None
    primary_action_stop_label: str
    primary_action_stop_uses_bitmap: bool
    primary_action_stop_bitmap: wx.Bitmap | None
    primary_action_stop_disabled_bitmap: wx.Bitmap | None
    batch_controls: BatchControls
    activity_indicator: wx.ActivityIndicator
    status_label: wx.StaticText
    project_settings_button: wx.Button
    confirm_choice: wx.Choice
    confirm_entries: tuple[tuple[RequirementConfirmPreference, str], ...]
    confirm_choice_index: dict[RequirementConfirmPreference, int]


PRIMARY_ACTION_IDLE_LABEL = "⬆"
PRIMARY_ACTION_ICON_EDGE = 14


@dataclass(slots=True)
class _PrimaryActionVisual:
    """Describe how the primary action button looks in idle state."""

    label: str
    uses_bitmap: bool
    bitmap: wx.Bitmap | None
    disabled_bitmap: wx.Bitmap | None
    min_size: wx.Size | None


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
        bottom_panel = SectionContainer(vertical_splitter)
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
        panel._observe_history_columns(history_list)

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

        bottom_inner = wx.Panel(bottom_panel)
        inherit_background(bottom_inner, bottom_panel)
        bottom_padding = dip(panel, 6)
        bottom_sizer = wx.BoxSizer(wx.VERTICAL)
        bottom_sizer.AddSpacer(spacing)

        input_label = wx.StaticText(bottom_inner, label=_("Ask the agent"))
        input_ctrl = wx.TextCtrl(
            bottom_inner, style=wx.TE_PROCESS_ENTER | wx.TE_MULTILINE
        )
        if hasattr(input_ctrl, "SetHint"):
            input_ctrl.SetHint(_("Describe what you need the agent to do"))
        input_ctrl.Bind(wx.EVT_TEXT_ENTER, panel._on_send)

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        run_batch_btn = wx.Button(bottom_inner, label=_("Run batch"))
        stop_batch_btn = wx.Button(bottom_inner, label=_("Stop batch"))
        stop_batch_btn.Enable(False)
        icon_buttons_to_match: list[wx.Button] = []
        attachment_btn, attachment_uses_icon = self._create_attachment_button(
            bottom_inner
        )
        if attachment_uses_icon:
            icon_buttons_to_match.append(attachment_btn)
        attachment_btn.Bind(wx.EVT_BUTTON, panel._on_select_attachment)
        attachment_btn.SetToolTip(_("Attach file…"))
        attachment_summary = wx.StaticText(
            bottom_inner,
            label=_("No file attached"),
            style=wx.ST_ELLIPSIZE_MIDDLE,
        )
        settings_btn, settings_uses_icon = self._create_instructions_button(
            bottom_inner
        )
        if settings_uses_icon:
            icon_buttons_to_match.append(settings_btn)
        settings_btn.Bind(wx.EVT_BUTTON, panel._on_project_settings)
        settings_btn.SetToolTip(_("Agent instructions"))
        clear_btn, clear_uses_icon = self._create_clear_button(bottom_inner)
        if clear_uses_icon:
            icon_buttons_to_match.append(clear_btn)
        clear_btn.Bind(wx.EVT_BUTTON, panel._on_clear_input)
        clear_btn.SetToolTip(_("Clear input"))
        (
            primary_btn,
            primary_idle_visual,
            primary_stop_visual,
        ) = self._create_primary_action_button(bottom_inner)
        primary_btn.Bind(wx.EVT_BUTTON, panel._on_primary_action)
        primary_btn.SetToolTip(_("Send"))
        self._ensure_primary_button_capacity(
            primary_btn, primary_idle_visual, primary_stop_visual
        )

        icon_cluster = wx.BoxSizer(wx.HORIZONTAL)
        icon_cluster.Add(attachment_btn, 0, wx.ALIGN_TOP | wx.RIGHT, spacing)
        icon_cluster.Add(
            attachment_summary,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            spacing,
        )
        icon_cluster.Add(clear_btn, 0, wx.ALIGN_TOP | wx.RIGHT, spacing)
        icon_cluster.Add(settings_btn, 0, wx.ALIGN_TOP | wx.RIGHT, spacing)
        icon_cluster.Add(primary_btn, 0, wx.ALIGN_TOP)

        button_row.Add(run_batch_btn, 0, wx.ALIGN_TOP | wx.RIGHT, spacing)
        button_row.Add(stop_batch_btn, 0, wx.ALIGN_TOP | wx.RIGHT, spacing)
        button_row.Add(icon_cluster, 0, wx.ALIGN_TOP)

        batch_panel = wx.Panel(bottom_inner)
        inherit_background(batch_panel, bottom_inner)
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

        activity_indicator = wx.ActivityIndicator(bottom_inner)
        activity_indicator.Hide()
        status_label = wx.StaticText(bottom_inner, label=_("Ready"))
        status_row = wx.BoxSizer(wx.HORIZONTAL)
        status_row.Add(
            activity_indicator, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, spacing
        )
        status_row.Add(status_label, 0, wx.ALIGN_CENTER_VERTICAL)
        activity_indicator.SetToolTip(status_help_text)
        status_label.SetToolTip(status_help_text)

        confirm_entries: tuple[tuple[RequirementConfirmPreference, str], ...] = (
            (RequirementConfirmPreference.PROMPT, _("Ask every time")),
            (
                RequirementConfirmPreference.CHAT_ONLY,
                _("Skip for this chat"),
            ),
            (RequirementConfirmPreference.NEVER, _("Never ask")),
        )
        confirm_choice = wx.Choice(
            bottom_inner,
            choices=[label for _pref, label in confirm_entries],
        )
        confirm_choice.Bind(wx.EVT_CHOICE, panel._on_confirm_choice)
        confirm_choice_index = {
            pref: idx for idx, (pref, _label) in enumerate(confirm_entries)
        }
        confirm_label = wx.StaticText(
            bottom_inner, label=_("Requirement confirmations")
        )
        confirm_row = wx.BoxSizer(wx.HORIZONTAL)
        confirm_row.Add(
            confirm_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, dip(panel, 4)
        )
        confirm_row.Add(confirm_choice, 0, wx.ALIGN_CENTER_VERTICAL)

        controls_row = wx.BoxSizer(wx.HORIZONTAL)
        controls_row.Add(
            status_row,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            spacing,
        )
        controls_row.AddStretchSpacer()
        controls_row.Add(confirm_row, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, spacing)
        controls_row.Add(button_row, 0, wx.ALIGN_TOP)
        if icon_buttons_to_match:
            self._harmonize_icon_button_sizes(primary_btn, icon_buttons_to_match)

        bottom_sizer.Add(input_label, 0)
        bottom_sizer.AddSpacer(spacing)
        bottom_sizer.Add(input_ctrl, 1, wx.EXPAND)
        bottom_sizer.AddSpacer(spacing)
        bottom_sizer.Add(batch_panel, 0, wx.EXPAND)
        bottom_sizer.AddSpacer(spacing)
        bottom_sizer.Add(controls_row, 0, wx.EXPAND)
        bottom_sizer.AddSpacer(spacing)
        bottom_inner.SetSizer(bottom_sizer)

        container_sizer = wx.BoxSizer(wx.VERTICAL)
        container_sizer.Add(bottom_inner, 1, wx.EXPAND | wx.ALL, bottom_padding)
        bottom_panel.SetSizer(container_sizer)

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
            attachment_button=attachment_btn,
            attachment_summary=attachment_summary,
            input_control=input_ctrl,
            primary_action_button=primary_btn,
            primary_action_idle_label=primary_idle_visual.label,
            primary_action_idle_uses_bitmap=primary_idle_visual.uses_bitmap,
            primary_action_idle_bitmap=primary_idle_visual.bitmap,
            primary_action_idle_disabled_bitmap=primary_idle_visual.disabled_bitmap,
            primary_action_stop_label=primary_stop_visual.label,
            primary_action_stop_uses_bitmap=primary_stop_visual.uses_bitmap,
            primary_action_stop_bitmap=primary_stop_visual.bitmap,
            primary_action_stop_disabled_bitmap=primary_stop_visual.disabled_bitmap,
            batch_controls=batch_controls,
            activity_indicator=activity_indicator,
            status_label=status_label,
            project_settings_button=settings_btn,
            confirm_choice=confirm_choice,
            confirm_entries=confirm_entries,
            confirm_choice_index=confirm_choice_index,
        )

    # ------------------------------------------------------------------
    def _ensure_primary_button_capacity(
        self,
        button: wx.Button,
        idle_visual: _PrimaryActionVisual,
        stop_visual: _PrimaryActionVisual,
    ) -> None:
        """Keep the primary button size stable across idle and running states."""

        idle_size = self._measure_primary_action_visual(button, idle_visual)
        stop_size = self._measure_primary_action_visual(button, stop_visual)

        width = max(idle_size.width, stop_size.width)
        height = max(idle_size.height, stop_size.height)
        for visual in (idle_visual, stop_visual):
            if visual.min_size is not None:
                width = max(width, visual.min_size.GetWidth())
                height = max(height, visual.min_size.GetHeight())
        edge = max(width, height)
        button.SetMinSize(wx.Size(edge, edge))

        self._apply_primary_action_visual(button, idle_visual)

    # ------------------------------------------------------------------
    def _measure_primary_action_visual(
        self, button: wx.Button, visual: _PrimaryActionVisual
    ) -> wx.Size:
        """Return the best size for the provided primary action visual."""

        self._apply_primary_action_visual(button, visual)
        button.InvalidateBestSize()
        size = button.GetBestSize()
        if not size.IsFullySpecified():
            return wx.Size(max(size.width, 0), max(size.height, 0))
        return size

    # ------------------------------------------------------------------
    def _apply_primary_action_visual(
        self, button: wx.Button, visual: _PrimaryActionVisual
    ) -> None:
        """Apply the provided visual state to the primary action button."""

        if visual.uses_bitmap and visual.bitmap is not None:
            self._apply_button_bitmaps(
                button, visual.bitmap, visual.disabled_bitmap
            )
        else:
            self._clear_button_bitmaps(button)
        label = visual.label if visual.label else ""
        if button.GetLabel() != label:
            button.SetLabel(label)

    # ------------------------------------------------------------------
    def _create_primary_action_button(
        self, parent: wx.Window
    ) -> tuple[wx.Button, _PrimaryActionVisual, _PrimaryActionVisual]:
        """Construct the send/stop button together with its visuals."""

        idle_visual = self._build_primary_action_idle_visual(parent)
        stop_visual = self._build_primary_action_stop_visual(parent)
        button = wx.Button(parent, label="", style=wx.BU_AUTODRAW | wx.BU_EXACTFIT)
        inherit_background(button, parent)
        self._apply_primary_action_visual(button, idle_visual)
        return button, idle_visual, stop_visual

    # ------------------------------------------------------------------
    def _build_primary_action_idle_visual(
        self, parent: wx.Window
    ) -> _PrimaryActionVisual:
        """Return the idle visual description for the primary action button."""

        return self._build_primary_action_visual(
            parent,
            svg_builder=self._build_primary_action_arrow_svg,
            fallback_label=PRIMARY_ACTION_IDLE_LABEL,
        )

    # ------------------------------------------------------------------
    def _build_primary_action_stop_visual(
        self, parent: wx.Window
    ) -> _PrimaryActionVisual:
        """Return the running visual description for the primary action button."""

        return self._build_primary_action_visual(
            parent,
            svg_builder=self._build_primary_action_stop_svg,
            fallback_label=_("Stop"),
        )

    # ------------------------------------------------------------------
    def _build_primary_action_visual(
        self,
        parent: wx.Window,
        *,
        svg_builder: Callable[[wx.Colour], str],
        fallback_label: str,
    ) -> _PrimaryActionVisual:
        """Return a visual description for the primary action button."""

        icon_edge = dip(self._panel, PRIMARY_ACTION_ICON_EDGE)
        icon_size = wx.Size(icon_edge, icon_edge)
        bitmaps = self._render_primary_action_bitmaps(parent, icon_size, svg_builder)
        if bitmaps is None:
            return _PrimaryActionVisual(
                label=fallback_label,
                uses_bitmap=False,
                bitmap=None,
                disabled_bitmap=None,
                min_size=None,
            )
        normal_bitmap, disabled_bitmap = bitmaps
        return _PrimaryActionVisual(
            label="",
            uses_bitmap=True,
            bitmap=normal_bitmap,
            disabled_bitmap=disabled_bitmap,
            min_size=icon_size,
        )

    # ------------------------------------------------------------------
    def _render_primary_action_bitmaps(
        self,
        parent: wx.Window,
        icon_size: wx.Size,
        svg_builder: Callable[[wx.Colour], str],
    ) -> tuple[wx.Bitmap, wx.Bitmap] | None:
        """Render the idle-state bitmaps for the primary action button."""

        colours = self._resolve_primary_action_colours(parent)
        if colours is None:
            return None
        accent_colour, disabled_colour = colours
        normal_markup = svg_builder(accent_colour)
        normal = self._render_svg_bitmap(normal_markup, icon_size)
        if normal is None or not normal.IsOk():
            return None
        disabled_markup = svg_builder(disabled_colour)
        disabled = self._render_svg_bitmap(disabled_markup, icon_size)
        if disabled is None or not disabled.IsOk():
            return None
        return normal, disabled

    # ------------------------------------------------------------------
    def _resolve_primary_action_colours(
        self, parent: wx.Window
    ) -> tuple[wx.Colour, wx.Colour] | None:
        """Pick colours for the active and disabled arrow."""

        accent = parent.GetForegroundColour()
        if not isinstance(accent, wx.Colour) or not accent.IsOk():
            accent = wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNTEXT)
        if not accent.IsOk():
            return None

        background = parent.GetBackgroundColour()
        if not isinstance(background, wx.Colour) or not background.IsOk():
            background = wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE)
        if not background.IsOk():
            background = wx.Colour(240, 240, 240)

        disabled = self._mix_colour(accent, background, 0.35)
        return accent, disabled

    # ------------------------------------------------------------------
    def _mix_colour(
        self, first: wx.Colour, second: wx.Colour, first_weight: float
    ) -> wx.Colour:
        """Blend two colours using the provided weight for the first colour."""

        ratio = max(0.0, min(1.0, first_weight))
        other = 1.0 - ratio

        def _clamp(value: float) -> int:
            return max(0, min(int(round(value)), 255))

        first_alpha = self._colour_alpha(first)
        second_alpha = self._colour_alpha(second)
        return wx.Colour(
            _clamp(first.Red() * ratio + second.Red() * other),
            _clamp(first.Green() * ratio + second.Green() * other),
            _clamp(first.Blue() * ratio + second.Blue() * other),
            _clamp(first_alpha * ratio + second_alpha * other),
        )

    # ------------------------------------------------------------------
    def _colour_alpha(self, colour: wx.Colour) -> int:
        """Return the alpha component of a colour, defaulting to fully opaque."""

        alpha_getter = getattr(colour, "Alpha", None)
        if callable(alpha_getter):
            return int(alpha_getter())
        if hasattr(colour, "GetAlpha") and callable(colour.GetAlpha):
            return int(colour.GetAlpha())
        return 255

    # ------------------------------------------------------------------
    def _apply_button_bitmaps(
        self, button: wx.Button, bitmap: wx.Bitmap, disabled_bitmap: wx.Bitmap | None
    ) -> None:
        """Attach the provided bitmaps to a button."""

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
    def _clear_button_bitmaps(self, button: wx.Button) -> None:
        """Remove any bitmaps associated with a button."""

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
    def _harmonize_icon_button_sizes(
        self, primary_button: wx.Button, buttons: Sequence[wx.Button]
    ) -> None:
        """Align auxiliary icon buttons with the primary button footprint."""

        if not buttons:
            return

        reference = primary_button.GetMinSize()
        if reference == wx.DefaultSize or not reference.IsFullySpecified():
            primary_button.InvalidateBestSize()
            reference = primary_button.GetBestSize()

        width = max(reference.GetWidth(), 0)
        height = max(reference.GetHeight(), 0)
        if width <= 0 or height <= 0:
            return

        size = wx.Size(width, height)
        for button in buttons:
            button.SetMinSize(size)
            button.InvalidateBestSize()

    # ------------------------------------------------------------------
    def _create_attachment_button(
        self, parent: wx.Window
    ) -> tuple[wx.Button, bool]:
        """Create an icon-first button used to pick an attachment."""

        panel = self._panel
        icon_edge = dip(panel, PRIMARY_ACTION_ICON_EDGE)
        icon_size = wx.Size(icon_edge, icon_edge)
        inherit_background(parent, panel)

        bitmaps = self._load_attachment_button_bitmaps(parent, icon_size)
        button = wx.Button(parent, label="", style=wx.BU_AUTODRAW | wx.BU_EXACTFIT)
        inherit_background(button, parent)
        if bitmaps is None:
            button.SetLabel(_("Attach file…"))
            return button, False

        normal_bitmap, disabled_bitmap = bitmaps
        self._apply_button_bitmaps(button, normal_bitmap, disabled_bitmap)
        button.SetMinSize(icon_size)
        return button, True

    # ------------------------------------------------------------------
    def _create_instructions_button(
        self, parent: wx.Window
    ) -> tuple[wx.Button, bool]:
        """Create a compact icon button that opens agent instructions."""

        panel = self._panel
        icon_edge = dip(panel, PRIMARY_ACTION_ICON_EDGE)
        icon_size = wx.Size(icon_edge, icon_edge)
        inherit_background(parent, panel)

        bitmaps = self._load_instructions_button_bitmaps(parent, icon_size)
        button = wx.Button(parent, label="", style=wx.BU_AUTODRAW | wx.BU_EXACTFIT)
        inherit_background(button, parent)
        if bitmaps is None:
            button.SetLabel(_("Agent instructions"))
            return button, False

        normal_bitmap, disabled_bitmap = bitmaps
        self._apply_button_bitmaps(button, normal_bitmap, disabled_bitmap)
        button.SetMinSize(icon_size)
        return button, True

    # ------------------------------------------------------------------
    def _create_clear_button(
        self, parent: wx.Window
    ) -> tuple[wx.Button, bool]:
        """Create a compact button for clearing the chat input."""

        panel = self._panel
        icon_edge = dip(panel, PRIMARY_ACTION_ICON_EDGE)
        icon_size = wx.Size(icon_edge, icon_edge)
        inherit_background(parent, panel)

        bitmaps = self._load_clear_button_bitmaps(parent, icon_size)
        button = wx.Button(parent, label="", style=wx.BU_AUTODRAW | wx.BU_EXACTFIT)
        inherit_background(button, parent)
        if bitmaps is None:
            button.SetLabel(_("Clear input"))
            return button, False

        normal_bitmap, disabled_bitmap = bitmaps
        self._apply_button_bitmaps(button, normal_bitmap, disabled_bitmap)
        button.SetMinSize(icon_size)
        return button, True

    # ------------------------------------------------------------------
    def _load_clear_button_bitmaps(
        self, parent: wx.Window, icon_size: wx.Size
    ) -> tuple[wx.Bitmap, wx.Bitmap] | None:
        """Return bitmaps for the clear-input button or ``None`` if unavailable."""

        colour = self._resolve_control_icon_colour(parent)

        stroke = self._colour_to_hex(colour)
        opacity = max(0.0, min(self._colour_alpha(colour) / 255.0, 1.0))
        svg_markup = _CLEAR_INPUT_ICON_SVG_TEMPLATE.format(
            stroke=stroke,
            stroke_opacity=f"{opacity:.3f}",
        )

        bitmap = self._render_svg_bitmap(svg_markup, icon_size)
        if bitmap is None:
            return None

        disabled_image = bitmap.ConvertToImage().ConvertToDisabled()
        disabled_bitmap = wx.Bitmap(disabled_image)
        return bitmap, disabled_bitmap

    # ------------------------------------------------------------------
    def _load_attachment_button_bitmaps(
        self, parent: wx.Window, icon_size: wx.Size
    ) -> tuple[wx.Bitmap, wx.Bitmap] | None:
        """Return bitmaps for the attachment button or ``None`` if unavailable."""

        colour = self._resolve_control_icon_colour(parent)
        stroke = self._colour_to_hex(colour)
        opacity = max(0.0, min(self._colour_alpha(colour) / 255.0, 1.0))
        svg_markup = _ATTACHMENT_ICON_SVG_TEMPLATE.format(
            stroke=stroke,
            stroke_opacity=f"{opacity:.3f}",
        )

        bitmap = self._render_svg_bitmap(svg_markup, icon_size)
        if bitmap is None:
            return None

        disabled_image = bitmap.ConvertToImage().ConvertToDisabled()
        disabled_bitmap = wx.Bitmap(disabled_image)
        return bitmap, disabled_bitmap

    # ------------------------------------------------------------------
    def _load_instructions_button_bitmaps(
        self, parent: wx.Window, icon_size: wx.Size
    ) -> tuple[wx.Bitmap, wx.Bitmap] | None:
        """Return bitmaps for the agent instructions button."""

        highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
        if not isinstance(highlight, wx.Colour) or not highlight.IsOk():
            highlight = wx.Colour(33, 114, 229)
        fill = self._colour_to_hex(highlight)
        opacity = max(0.0, min(self._colour_alpha(highlight) / 255.0, 1.0))
        svg_markup = _INSTRUCTIONS_ICON_SVG_TEMPLATE.format(
            stroke=fill,
            stroke_opacity=f"{opacity:.3f}",
            fill=fill,
            fill_opacity=f"{opacity:.3f}",
        )

        bitmap = self._render_svg_bitmap(svg_markup, icon_size)
        if bitmap is None:
            return None

        disabled_image = bitmap.ConvertToImage().ConvertToDisabled()
        disabled_bitmap = wx.Bitmap(disabled_image)
        return bitmap, disabled_bitmap

    # ------------------------------------------------------------------
    def _resolve_control_icon_colour(self, parent: wx.Window) -> wx.Colour:
        """Return a foreground colour suitable for monochrome control icons."""

        colour = parent.GetForegroundColour()
        if not isinstance(colour, wx.Colour) or not colour.IsOk():
            colour = wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNTEXT)
        if not colour.IsOk():
            colour = wx.Colour(86, 99, 122)
        return colour

    # ------------------------------------------------------------------
    def _render_svg_bitmap(self, svg_markup: str, icon_size: wx.Size) -> wx.Bitmap | None:
        """Render SVG markup into a bitmap using available wx backends."""

        bitmap = self._render_svg_with_bitmap_bundle(svg_markup, icon_size)
        if bitmap is None:
            bitmap = self._render_svg_with_wxsvg(svg_markup, icon_size)
        return bitmap

    # ------------------------------------------------------------------
    def _render_svg_with_bitmap_bundle(
        self, svg_markup: str, icon_size: wx.Size
    ) -> wx.Bitmap | None:
        """Render SVG markup through :mod:`wx.BitmapBundle` if supported."""

        if not hasattr(wx, "BitmapBundle"):
            return None
        from_svg = getattr(wx.BitmapBundle, "FromSVG", None)
        if from_svg is None:
            return None

        try:
            bundle = from_svg(svg_markup.encode("utf-8"), icon_size)
        except (TypeError, ValueError, RuntimeError):
            return None
        if not bundle or not bundle.IsOk():
            return None

        bitmap = bundle.GetBitmap(icon_size)
        if not bitmap or not bitmap.IsOk():
            return None
        return bitmap

    # ------------------------------------------------------------------
    def _render_svg_with_wxsvg(
        self, svg_markup: str, icon_size: wx.Size
    ) -> wx.Bitmap | None:
        """Render SVG markup via :mod:`wx.svg` as a compatibility fallback."""

        try:
            import wx.svg as wxsvg
        except Exception:  # pragma: no cover - defensive against missing module
            return None

        create_from_string = getattr(wxsvg.SVGimage, "CreateFromString", None)
        if create_from_string is None:
            return None

        image = create_from_string(svg_markup)
        if image is None or not image.IsOk():
            return None

        width = max(icon_size.GetWidth(), 1)
        height = max(icon_size.GetHeight(), 1)
        bitmap = image.Render(width, height)
        if not bitmap or not bitmap.IsOk():
            return None
        return bitmap

    # ------------------------------------------------------------------
    def _build_primary_action_arrow_svg(self, colour: wx.Colour) -> str:
        """Return SVG markup for the idle-state upward arrow."""

        fill = self._colour_to_hex(colour)
        opacity = max(0.0, min(self._colour_alpha(colour) / 255.0, 1.0))
        return _PRIMARY_ACTION_ARROW_ICON_SVG_TEMPLATE.format(
            fill=fill,
            fill_opacity=f"{opacity:.3f}",
        )

    # ------------------------------------------------------------------
    def _build_primary_action_stop_svg(self, colour: wx.Colour) -> str:
        """Return SVG markup for the running-state stop icon."""

        fill = self._colour_to_hex(colour)
        opacity = max(0.0, min(self._colour_alpha(colour) / 255.0, 1.0))
        return _PRIMARY_ACTION_STOP_ICON_SVG_TEMPLATE.format(
            fill=fill,
            fill_opacity=f"{opacity:.3f}",
        )

    # ------------------------------------------------------------------
    def _colour_to_hex(self, colour: wx.Colour) -> str:
        """Convert a colour to a ``#RRGGBB`` hex string."""

        return "#{:02X}{:02X}{:02X}".format(
            max(0, min(int(colour.Red()), 255)),
            max(0, min(int(colour.Green()), 255)),
            max(0, min(int(colour.Blue()), 255)),
        )


_PRIMARY_ACTION_ARROW_ICON_SVG_TEMPLATE = dedent(
    """
    <svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M12 2 L20 11 H16.4 V21 H7.6 V11 H4 Z" fill="{fill}" fill-opacity="{fill_opacity}" />
    </svg>
    """
)

_PRIMARY_ACTION_STOP_ICON_SVG_TEMPLATE = dedent(
    """
    <svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <rect x="5" y="5" width="14" height="14" rx="3" fill="{fill}" fill-opacity="{fill_opacity}" />
      <rect x="6" y="6" width="12" height="12" rx="2.4" fill="none" stroke="{fill}" stroke-opacity="{fill_opacity}" stroke-width="1.4" />
    </svg>
    """
)

_ATTACHMENT_ICON_SVG_TEMPLATE = dedent(
    """
    <svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M9 6.5 C9 5.12 10.12 4 11.5 4 C12.88 4 14 5.12 14 6.5 V15.8 C14 17.57 12.57 19 10.8 19 C9.03 19 7.6 17.57 7.6 15.8 V8.2 C7.6 7.08 8.48 6.2 9.6 6.2 C10.72 6.2 11.6 7.08 11.6 8.2 V15.2 C11.6 15.75 12.05 16.2 12.6 16.2 C13.15 16.2 13.6 15.75 13.6 15.2 V9.3" fill="none" stroke="{stroke}" stroke-opacity="{stroke_opacity}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
    """
)

_CLEAR_INPUT_ICON_SVG_TEMPLATE = dedent(
    """
    <svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M8.8 6.5 L9.3 5.2 C9.5 4.7 9.9 4.4 10.4 4.4 H13.6 C14.1 4.4 14.5 4.7 14.7 5.2 L15.2 6.5" fill="none" stroke="{stroke}" stroke-opacity="{stroke_opacity}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
      <path d="M6 6.5 H18" stroke="{stroke}" stroke-opacity="{stroke_opacity}" stroke-width="1.6" stroke-linecap="round" />
      <rect x="7.5" y="8.2" width="9" height="10.8" rx="2.2" fill="none" stroke="{stroke}" stroke-opacity="{stroke_opacity}" stroke-width="1.6" stroke-linejoin="round" />
      <path d="M10.2 10.5 V16.7" stroke="{stroke}" stroke-opacity="{stroke_opacity}" stroke-width="1.6" stroke-linecap="round" />
      <path d="M13.8 10.5 V16.7" stroke="{stroke}" stroke-opacity="{stroke_opacity}" stroke-width="1.6" stroke-linecap="round" />
    </svg>
    """
)

_INSTRUCTIONS_ICON_SVG_TEMPLATE = dedent(
    """
    <svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <rect x="3.4" y="3.4" width="17.2" height="17.2" rx="3.6" fill="none" stroke="{stroke}" stroke-opacity="{stroke_opacity}" stroke-width="1.6" />
      <rect x="10.4" y="8.7" width="3.2" height="9.1" rx="1.4" fill="{fill}" fill-opacity="{fill_opacity}" />
      <circle cx="12" cy="6.8" r="1.6" fill="{fill}" fill-opacity="{fill_opacity}" />
    </svg>
    """
)


__all__ = ["AgentChatLayout", "AgentChatLayoutBuilder"]

