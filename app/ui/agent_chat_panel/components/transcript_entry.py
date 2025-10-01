"""Widgets for rendering a single conversation entry timeline."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
import json
from typing import Any

import wx

from ....i18n import _
from ...widgets.chat_message import MessageBubble
from ...text import normalize_for_display
from ..history_utils import history_json_safe
from ..tool_summaries import ToolCallSummary
from ..view_model import (
    ChatEventKind,
    ContextEvent,
    EntryTimeline,
    LlmRequestEvent,
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
    name: str | None = None,
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
    pane.SetName(name or label)
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

        if timeline.prompt is not None:
            bubble = self._create_prompt_bubble(
                timeline.prompt, context_event=timeline.context
            )
            sizer.Add(bubble, 0, wx.EXPAND | wx.ALL, self._padding)
            self._user_bubble = bubble

        agent_sections_present = bool(
            timeline.response
            or timeline.reasoning
            or timeline.raw_payload
            or timeline.llm_request
            or timeline.tool_calls
        )
        if agent_sections_present or timeline.can_regenerate:
            bubble, button = self._create_response_section(
                timeline.response,
                timeline,
                timeline.reasoning,
                timeline.llm_request,
                timeline.raw_payload,
                timeline.tool_calls,
                on_regenerate,
                regenerate_enabled,
            )
            sizer.Add(bubble, 0, wx.EXPAND | wx.ALL, self._padding)
            self._agent_bubble = bubble
            if button is not None:
                sizer.Add(
                    button,
                    0,
                    wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                    self._padding,
                )
                self._regenerate_button = button

        for system_event in timeline.system_messages:
            pane = self._create_system_section(system_event)
            if pane is not None:
                sizer.Add(pane, 0, wx.EXPAND | wx.ALL, self._padding)
                self._register_collapsible(
                    f"system:{system_event.event_id}", pane
                )

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
    def _create_collapsible_footer(
        self,
        bubble: wx.Window,
        *,
        key: str,
        name: str,
        label: str,
        text: str,
        minimum_height: int,
    ) -> wx.CollapsiblePane | None:
        pane = _build_collapsible_section(
            bubble,
            label=label,
            content=text,
            minimum_height=minimum_height,
            collapsed=self._collapsed_state.get(key, True),
            name=name,
        )
        if pane is not None:
            self._register_collapsible(key, pane)
        return pane

    # ------------------------------------------------------------------
    def _create_prompt_bubble(
        self, event: PromptEvent, *, context_event: ContextEvent | None
    ) -> MessageBubble:
        def footer_factory(bubble: wx.Window) -> wx.Sizer | None:
            if context_event is None:
                return None
            text = _format_context_messages(context_event.messages)
            pane = self._create_collapsible_footer(
                bubble,
                key="context",
                name="context",
                label=_("Context"),
                text=text,
                minimum_height=140,
            )
            if pane is None:
                return None
            sizer = wx.BoxSizer(wx.VERTICAL)
            sizer.Add(pane, 0, wx.EXPAND | wx.TOP, bubble.FromDIP(4))
            return sizer

        return MessageBubble(
            self,
            role_label=_("You"),
            timestamp=event.formatted_timestamp,
            text=event.text,
            align="right",
            allow_selection=True,
            width_hint=self._resolve_hint("user"),
            on_width_change=lambda width: self._emit_layout_hint("user", width),
            footer_factory=footer_factory,
        )

    def _build_tool_sections(
        self, bubble: wx.Window, tool_events: Sequence[ToolCallEvent]
    ) -> wx.Sizer | None:
        if not tool_events:
            return None
        container = wx.BoxSizer(wx.VERTICAL)
        added = False
        for event in tool_events:
            pane = self._create_tool_collapsible(bubble, event)
            if pane is not None:
                container.Add(pane, 0, wx.EXPAND | wx.TOP, bubble.FromDIP(4))
                added = True
        return container if added else None

    # ------------------------------------------------------------------
    def _create_tool_collapsible(
        self, bubble: wx.Window, event: ToolCallEvent
    ) -> wx.CollapsiblePane | None:
        summary = event.summary
        tool_name = summary.tool_name or _("Tool")
        label = _("Tool call {index}: {tool} — {status}").format(
            index=summary.index,
            tool=tool_name,
            status=summary.status or _("returned data"),
        )
        pane = wx.CollapsiblePane(
            bubble,
            label=label,
            style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE,
        )
        pane.SetName(
            f"tool:{summary.tool_name.strip().lower() if summary.tool_name else ''}:{summary.index}"
        )
        pane_background = bubble.GetBackgroundColour()
        if not pane_background.IsOk():
            pane_background = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        pane.SetBackgroundColour(pane_background)
        pane_foreground = bubble.GetForegroundColour()
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

        self._register_collapsible(f"tool:{event.event_id}", pane)

        inner_sizer = wx.BoxSizer(wx.VERTICAL)
        summary_text = self._format_tool_summary_text(event)
        summary_ctrl = wx.TextCtrl(
            inner,
            value=summary_text,
            style=(
                wx.TE_MULTILINE
                | wx.TE_READONLY
                | wx.TE_BESTWRAP
                | wx.BORDER_NONE
            ),
        )
        summary_ctrl.SetBackgroundColour(pane_background)
        summary_ctrl.SetForegroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
        )
        summary_ctrl.SetMinSize((-1, bubble.FromDIP(100)))
        inner_sizer.Add(summary_ctrl, 0, wx.EXPAND | wx.TOP, bubble.FromDIP(4))

        nested_sections: list[tuple[str, str, str, str, int]] = []
        request_text = _format_raw_payload(event.llm_request)
        if request_text:
            nested_sections.append(
                (
                    f"tool-request:{event.event_id}",
                    f"raw:tool-request:{summary.tool_name or ''}:{summary.index}",
                    _("LLM request"),
                    request_text,
                    150,
                )
            )
        raw_text = _format_raw_payload(event.raw_payload)
        if raw_text:
            nested_sections.append(
                (
                    f"tool:{event.event_id}",
                    f"raw:tool:{summary.tool_name or ''}:{summary.index}",
                    _("Raw data"),
                    raw_text,
                    150,
                )
            )

        for key, name, label_text, value, minimum_height in nested_sections:
            pane_key = key
            nested = _build_collapsible_section(
                inner,
                label=label_text,
                content=value,
                minimum_height=minimum_height,
                collapsed=self._collapsed_state.get(pane_key, True),
                name=name,
            )
            if nested is not None:
                self._register_collapsible(pane_key, nested)
                inner_sizer.Add(nested, 0, wx.EXPAND | wx.TOP, bubble.FromDIP(4))

        inner.SetSizer(inner_sizer)
        return pane

    # ------------------------------------------------------------------
    def _format_tool_summary_text(self, event: ToolCallEvent) -> str:
        summary = event.summary
        lines: list[str] = []
        lines.append(
            _("Tool: {name}").format(
                name=summary.tool_name or _("Unnamed tool")
            )
        )
        if summary.status:
            lines.append(_("Status: {status}").format(status=summary.status))
        for bullet in summary.bullet_lines:
            if bullet:
                lines.append("• " + bullet)
        if event.call_identifier:
            lines.append(
                _("Call identifier: {identifier}").format(
                    identifier=event.call_identifier
                )
            )
        if event.timestamp:
            lines.append(_("Recorded at: {timestamp}").format(timestamp=event.timestamp))
        return "\n".join(lines)


    # ------------------------------------------------------------------
    def _create_response_section(
        self,
        event: ResponseEvent | None,
        timeline: EntryTimeline,
        reasoning_event: ReasoningEvent | None,
        llm_request_event: LlmRequestEvent | None,
        raw_event: RawPayloadEvent | None,
        tool_events: Sequence[ToolCallEvent],
        on_regenerate: Callable[[], None] | None,
        regenerate_enabled: bool,
    ) -> tuple[MessageBubble, wx.Button | None]:
        text = ""
        timestamp = ""
        if event is not None:
            text = event.display_text or event.text or ""
            timestamp = event.formatted_timestamp
        elif timeline.prompt is not None:
            timestamp = timeline.prompt.formatted_timestamp

        sections: list[tuple[str, str, str, str, int]] = []
        if reasoning_event is not None:
            reasoning_text = _format_reasoning_segments(reasoning_event.segments)
            if reasoning_text:
                sections.append(
                    (
                        "reasoning",
                        "reasoning",
                        _("Model reasoning"),
                        reasoning_text,
                        160,
                    )
                )
        if llm_request_event is not None:
            request_payload: dict[str, Any] = {
                "messages": llm_request_event.messages,
            }
            if llm_request_event.sequence is not None:
                request_payload["sequence"] = llm_request_event.sequence
            request_text = _format_raw_payload(request_payload)
            if request_text:
                sections.append(
                    (
                        "llm-request",
                        "raw:llm-request",
                        _("LLM request"),
                        request_text,
                        160,
                    )
                )
        if raw_event is not None:
            raw_text = _format_raw_payload(raw_event.payload)
            if raw_text:
                sections.append(
                    (
                        "raw",
                        "raw:agent",
                        _("Raw data"),
                        raw_text,
                        160,
                    )
                )

        def footer_factory(bubble: wx.Window) -> wx.Sizer | None:
            sizer = wx.BoxSizer(wx.VERTICAL)
            added = False
            for key, name, label, value, minimum_height in sections:
                pane = self._create_collapsible_footer(
                    bubble,
                    key=key,
                    name=name,
                    label=label,
                    text=value,
                    minimum_height=minimum_height,
                )
                if pane is not None:
                    sizer.Add(pane, 0, wx.EXPAND | wx.TOP, bubble.FromDIP(4))
                    added = True
            tool_sizer = self._build_tool_sections(bubble, tool_events)
            if tool_sizer is not None:
                sizer.Add(tool_sizer, 0, wx.EXPAND | wx.TOP, bubble.FromDIP(4))
                added = True
            return sizer if added else None

        bubble = MessageBubble(
            self,
            role_label=_("Agent"),
            timestamp=timestamp,
            text=text,
            align="left",
            allow_selection=True,
            render_markdown=True,
            width_hint=self._resolve_hint("agent"),
            on_width_change=lambda width: self._emit_layout_hint("agent", width),
            footer_factory=footer_factory,
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
