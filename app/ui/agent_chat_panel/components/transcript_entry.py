"""Widgets for rendering a single conversation entry timeline."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
import json
from typing import Any

import wx

from ....i18n import _
from ...widgets.chat_message import MessageBubble, tool_bubble_palette
from ...text import normalize_for_display
from ..history_utils import history_json_safe
from ..tool_summaries import ToolCallSummary, render_tool_summary_markdown
from ..view_model import (
    ChatEventKind,
    ContextEvent,
    EntryTimeline,
    PromptEvent,
    RawPayloadEvent,
    ReasoningEvent,
    ResponseEvent,
    SystemMessageEvent,
    ToolCallEvent,
)


def _format_context_messages(
    messages: Sequence[Mapping[str, Any]] | None,
) -> str:
    if not messages:
        return ""

    blocks: list[str] = []
    for message in messages:
        if isinstance(message, Mapping):
            role_value = message.get("role")
            content_value = message.get("content")
        else:
            role_value = getattr(message, "role", None)
            content_value = getattr(message, "content", None)

        fragments: list[str] = []
        if isinstance(content_value, Sequence) and not isinstance(
            content_value, (str, bytes, bytearray)
        ):
            for fragment in content_value:
                if isinstance(fragment, Mapping):
                    fragment_text = normalize_for_display(
                        fragment.get("text", "")
                    )
                    if fragment_text:
                        fragments.append(fragment_text)
                    continue
                if isinstance(fragment, str):
                    fragments.append(fragment)
                else:
                    fragments.append(str(fragment))
        elif content_value is not None:
            fragments.append(str(content_value))

        text = "\n".join(part for part in fragments if part)
        role = str(role_value).strip() if role_value is not None else ""
        if not text and not role:
            continue

        parts: list[str] = []
        if role:
            parts.append(f"{role}:")
        if text:
            parts.append(text)
        blocks.append("\n".join(parts).strip())

    return "\n\n".join(block for block in blocks if block)


def _format_reasoning_segments(
    segments: Sequence[Mapping[str, Any]] | None,
) -> str:
    if not segments:
        return ""

    blocks: list[str] = []
    for index, segment in enumerate(segments, start=1):
        if isinstance(segment, Mapping):
            type_value = segment.get("type")
            text_value = segment.get("text")
        else:
            type_value = getattr(segment, "type", None)
            text_value = getattr(segment, "text", None)
        if text_value is None:
            continue
        text = str(text_value).strip()
        if not text:
            continue
        type_label = str(type_value).strip() if type_value is not None else ""
        heading = type_label or _("Thought {index}").format(index=index)
        blocks.append(f"{heading}\n{text}")
    return "\n\n".join(blocks)


def _format_raw_payload(raw_payload: Any) -> str:
    if raw_payload is None:
        return ""
    safe_payload = history_json_safe(raw_payload)
    try:
        return json.dumps(safe_payload, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return normalize_for_display(str(safe_payload))


def _build_collapsible_section(
    parent: wx.Window,
    *,
    label: str,
    content: str,
    minimum_height: int,
    collapsed: bool = True,
) -> wx.CollapsiblePane | None:
    display_text = normalize_for_display(content).strip()
    if not display_text:
        return None

    pane = wx.CollapsiblePane(
        parent,
        label=label,
        style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE,
    )
    with suppress(Exception):
        pane.SetLabel(label)
    pane.SetName(label)
    if collapsed:
        pane.Collapse(True)

    pane_background = parent.GetBackgroundColour()
    if not pane_background.IsOk():
        pane_background = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
    pane.SetBackgroundColour(pane_background)
    pane_foreground = parent.GetForegroundColour()
    if pane_foreground.IsOk():
        pane.SetForegroundColour(pane_foreground)
        with suppress(Exception):
            toggle = pane.GetButton()
            if toggle is not None:
                toggle.SetForegroundColour(pane_foreground)
                toggle.SetBackgroundColour(pane_background)
    inner = pane.GetPane()
    inner.SetBackgroundColour(pane_background)
    if pane_foreground.IsOk():
        inner.SetForegroundColour(pane_foreground)

    content_sizer = wx.BoxSizer(wx.VERTICAL)
    text_ctrl = wx.TextCtrl(
        inner,
        value=display_text,
        style=(
            wx.TE_MULTILINE
            | wx.TE_READONLY
            | wx.TE_BESTWRAP
            | wx.BORDER_NONE
        ),
    )
    text_ctrl.SetBackgroundColour(pane_background)
    text_ctrl.SetForegroundColour(
        wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
    )
    text_ctrl.SetMinSize((-1, parent.FromDIP(minimum_height)))
    content_sizer.Add(text_ctrl, 1, wx.EXPAND | wx.TOP, parent.FromDIP(4))
    inner.SetSizer(content_sizer)
    return pane


class TranscriptEntryPanel(wx.Panel):
    """Render a single timeline entry using message and diagnostic widgets."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        timeline: EntryTimeline,
        layout_hints: Mapping[str, int] | None,
        on_layout_hint: Callable[[str, int], None] | None,
        on_regenerate: Callable[[], None] | None,
        regenerate_enabled: bool,
    ) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(parent.GetBackgroundColour())
        self.SetDoubleBuffered(True)

        self._padding = self.FromDIP(4)
        self._on_layout_hint = on_layout_hint
        self._layout_hints: dict[str, int] = dict(layout_hints or {})
        self._collapsed_state: dict[str, bool] = {}
        self._collapsible: dict[str, wx.CollapsiblePane] = {}
        self._regenerate_handler = on_regenerate
        self._regenerate_button: wx.Button | None = None
        self._regenerated_notice: wx.StaticText | None = None
        self._user_bubble: MessageBubble | None = None
        self._agent_bubble: MessageBubble | None = None

        self.SetSizer(wx.BoxSizer(wx.VERTICAL))
        self.rebuild(
            timeline,
            layout_hints=layout_hints or {},
            on_regenerate=on_regenerate,
            regenerate_enabled=regenerate_enabled,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def tool_layout_hint_key(summary: ToolCallSummary) -> str:
        return f"tool:{summary.tool_name.strip().lower()}:{summary.index}"

    # ------------------------------------------------------------------
    def rebuild(
        self,
        timeline: EntryTimeline,
        *,
        layout_hints: Mapping[str, int],
        on_regenerate: Callable[[], None] | None,
        regenerate_enabled: bool,
    ) -> None:
        self._capture_collapsed_state()
        self._layout_hints = dict(layout_hints)
        self._regenerate_handler = on_regenerate

        sizer = self.GetSizer()
        sizer.Clear(delete_windows=True)
        self._collapsible.clear()
        self._regenerated_notice = None
        self._user_bubble = None
        self._agent_bubble = None
        self._regenerate_button = None

        if (
            timeline.response is not None
            and getattr(timeline.response, "regenerated", False)
        ):
            notice = wx.StaticText(self, label=_("Response was regenerated"))
            sizer.Add(notice, 0, wx.ALL, self._padding)
            self._regenerated_notice = notice

        for event in timeline.events:
            if event.kind is ChatEventKind.CONTEXT and isinstance(event, ContextEvent):
                pane = self._create_context_section(event)
                if pane is not None:
                    sizer.Add(pane, 0, wx.EXPAND | wx.ALL, self._padding)
                    self._register_collapsible("context", pane)
                continue

            if event.kind is ChatEventKind.PROMPT and isinstance(event, PromptEvent):
                bubble = self._create_prompt_bubble(event)
                sizer.Add(bubble, 0, wx.EXPAND | wx.ALL, self._padding)
                self._user_bubble = bubble
                continue

            if event.kind is ChatEventKind.REASONING and isinstance(
                event, ReasoningEvent
            ):
                pane = self._create_reasoning_section(event)
                if pane is not None:
                    sizer.Add(pane, 0, wx.EXPAND | wx.ALL, self._padding)
                    self._register_collapsible("reasoning", pane)
                continue

            if event.kind is ChatEventKind.TOOL_CALL and isinstance(
                event, ToolCallEvent
            ):
                bubble, raw_key, raw_pane = self._create_tool_call_section(event)
                sizer.Add(bubble, 0, wx.EXPAND | wx.ALL, self._padding)
                if raw_pane is not None:
                    sizer.Add(raw_pane, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, self._padding)
                    self._register_collapsible(raw_key, raw_pane)
                continue

            if event.kind is ChatEventKind.RESPONSE and isinstance(
                event, ResponseEvent
            ):
                bubble, button = self._create_response_section(
                    event,
                    timeline,
                    on_regenerate,
                    regenerate_enabled,
                )
                sizer.Add(bubble, 0, wx.EXPAND | wx.ALL, self._padding)
                self._agent_bubble = bubble
                if button is not None:
                    sizer.Add(button, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, self._padding)
                    self._regenerate_button = button
                continue

            if event.kind is ChatEventKind.RAW_PAYLOAD and isinstance(
                event, RawPayloadEvent
            ):
                pane = self._create_raw_section(event)
                if pane is not None:
                    sizer.Add(pane, 0, wx.EXPAND | wx.ALL, self._padding)
                    self._register_collapsible("raw", pane)
                continue

            if event.kind is ChatEventKind.SYSTEM_MESSAGE and isinstance(
                event, SystemMessageEvent
            ):
                pane = self._create_system_section(event)
                if pane is not None:
                    sizer.Add(pane, 0, wx.EXPAND | wx.ALL, self._padding)
                    self._register_collapsible(f"system:{event.event_id}", pane)
                continue

        self._collapsed_state = {
            key: self._collapsed_state.get(key, True)
            for key in self._collapsible
        }
        self.Layout()

    # ------------------------------------------------------------------
    def update(
        self,
        timeline: EntryTimeline,
        *,
        layout_hints: Mapping[str, int],
        on_regenerate: Callable[[], None] | None,
        regenerate_enabled: bool,
    ) -> None:
        self.rebuild(
            timeline,
            layout_hints=layout_hints,
            on_regenerate=on_regenerate,
            regenerate_enabled=regenerate_enabled,
        )

    # ------------------------------------------------------------------
    def _capture_collapsed_state(self) -> None:
        for key, pane in list(self._collapsible.items()):
            if not isinstance(pane, wx.CollapsiblePane):
                continue
            try:
                self._collapsed_state[key] = pane.IsCollapsed()
            except RuntimeError:
                continue

    # ------------------------------------------------------------------
    def _register_collapsible(self, key: str, pane: wx.CollapsiblePane) -> None:
        self._collapsible[key] = pane
        collapsed = self._collapsed_state.get(key, True)
        try:
            pane.Collapse(collapsed)
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    def _create_prompt_bubble(self, event: PromptEvent) -> MessageBubble:
        return MessageBubble(
            self,
            role_label=_("You"),
            timestamp=event.formatted_timestamp,
            text=event.text,
            align="right",
            allow_selection=True,
            width_hint=self._resolve_hint("user"),
            on_width_change=lambda width: self._emit_layout_hint("user", width),
        )

    # ------------------------------------------------------------------
    def _create_context_section(
        self, event: ContextEvent
    ) -> wx.CollapsiblePane | None:
        text = _format_context_messages(event.messages)
        return _build_collapsible_section(
            self,
            label=_("Context"),
            content=text,
            minimum_height=140,
        )

    # ------------------------------------------------------------------
    def _create_reasoning_section(
        self, event: ReasoningEvent
    ) -> wx.CollapsiblePane | None:
        text = _format_reasoning_segments(event.segments)
        return _build_collapsible_section(
            self,
            label=_("Model reasoning"),
            content=text,
            minimum_height=160,
        )

    # ------------------------------------------------------------------
    def _create_tool_call_section(
        self, event: ToolCallEvent
    ) -> tuple[MessageBubble, str, wx.CollapsiblePane | None]:
        summary = event.summary
        markdown = render_tool_summary_markdown(summary).strip()
        if not markdown:
            markdown = _("(tool call summary unavailable)")
        timestamp = (
            summary.completed_at
            or summary.last_observed_at
            or summary.started_at
            or event.timestamp
            or ""
        )
        hint_key = self.tool_layout_hint_key(summary)
        bubble = MessageBubble(
            self,
            role_label=summary.tool_name or _("Tool"),
            timestamp=timestamp,
            text=markdown,
            align="left",
            allow_selection=True,
            render_markdown=True,
            palette=tool_bubble_palette(self.GetBackgroundColour(), summary.tool_name),
            width_hint=self._resolve_hint(hint_key),
            on_width_change=lambda width, key=hint_key: self._emit_layout_hint(key, width),
        )
        raw_text = _format_raw_payload(event.raw_payload)
        pane: wx.CollapsiblePane | None = None
        if raw_text:
            pane = _build_collapsible_section(
                self,
                label=_("Raw data"),
                content=raw_text,
                minimum_height=140,
            )
            if pane is not None:
                pane.SetName(f"raw:tool:{summary.tool_name or ''}:{summary.index}")
        return bubble, f"tool:{event.event_id}", pane

    # ------------------------------------------------------------------
    def _create_response_section(
        self,
        event: ResponseEvent,
        timeline: EntryTimeline,
        on_regenerate: Callable[[], None] | None,
        regenerate_enabled: bool,
    ) -> tuple[MessageBubble, wx.Button | None]:
        text = event.display_text or event.text or ""
        bubble = MessageBubble(
            self,
            role_label=_("Agent"),
            timestamp=event.formatted_timestamp,
            text=text,
            align="left",
            allow_selection=True,
            render_markdown=True,
            width_hint=self._resolve_hint("agent"),
            on_width_change=lambda width: self._emit_layout_hint("agent", width),
        )
        button: wx.Button | None = None
        if timeline.can_regenerate and on_regenerate is not None:
            button = wx.Button(self, label=_("Regenerate"), style=wx.BU_EXACTFIT)
            button.SetToolTip(_("Restart response generation"))
            button.Bind(wx.EVT_BUTTON, self._on_regenerate_clicked)
            button.Enable(regenerate_enabled)
            self._regenerate_handler = on_regenerate
        else:
            self._regenerate_handler = on_regenerate
        return bubble, button

    # ------------------------------------------------------------------
    def _create_raw_section(
        self, event: RawPayloadEvent
    ) -> wx.CollapsiblePane | None:
        text = _format_raw_payload(event.payload)
        pane = _build_collapsible_section(
            self,
            label=_("Raw data"),
            content=text,
            minimum_height=160,
        )
        if pane is not None:
            pane.SetName("raw:agent")
        return pane

    # ------------------------------------------------------------------
    def _create_system_section(
        self, event: SystemMessageEvent
    ) -> wx.CollapsiblePane | None:
        message = normalize_for_display(event.message or "")
        details = _format_raw_payload(event.details) if event.details is not None else ""
        combined = message
        if details:
            combined = f"{message}\n\n{details}" if message else details
        return _build_collapsible_section(
            self,
            label=_("System message"),
            content=combined,
            minimum_height=140,
        )

    # ------------------------------------------------------------------
    def _resolve_hint(self, key: str) -> int | None:
        value = self._layout_hints.get(key)
        if value is None:
            return None
        try:
            width = int(value)
        except (TypeError, ValueError):
            return None
        return width if width > 0 else None

    # ------------------------------------------------------------------
    def _emit_layout_hint(self, key: str, width: int) -> None:
        self._layout_hints[key] = width
        if self._on_layout_hint is None:
            return
        try:
            self._on_layout_hint(key, width)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _on_regenerate_clicked(self, _event: wx.CommandEvent) -> None:
        handler = self._regenerate_handler
        if handler is None:
            return
        try:
            handler()
        except Exception:
            pass


__all__ = ["TranscriptEntryPanel"]
