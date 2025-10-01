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
    ChatEvent,
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
        self._agent_panel: wx.Window | None = None

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
        self._agent_panel = None
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
            or timeline.intermediate_responses
            or timeline.reasoning
            or timeline.raw_payload
            or timeline.llm_request
            or timeline.tool_calls
        )
        if agent_sections_present or timeline.can_regenerate:
            panel, button = self._create_agent_panel(
                timeline,
                on_regenerate=on_regenerate,
                regenerate_enabled=regenerate_enabled,
            )
            if panel is not None:
                sizer.Add(panel, 0, wx.EXPAND | wx.ALL, self._padding)
                self._agent_panel = panel
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
    def _create_prompt_bubble(
        self, event: PromptEvent, *, context_event: ContextEvent | None
    ) -> MessageBubble:
        def footer_factory(bubble: wx.Window) -> wx.Sizer | None:
            if context_event is None:
                return None
            text = _format_context_messages(context_event.messages)
            pane = _build_collapsible_section(
                bubble,
                label=_("Context"),
                content=text,
                minimum_height=140,
                collapsed=self._collapsed_state.get("context", True),
                name="context",
            )
            if pane is not None:
                self._register_collapsible("context", pane)
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

    def _create_tool_collapsible(
        self, parent: wx.Window, event: ToolCallEvent
    ) -> wx.CollapsiblePane | None:
        summary = event.summary
        tool_name = summary.tool_name or _("Tool")
        label = _("Tool call {index}: {tool} — {status}").format(
            index=summary.index,
            tool=tool_name,
            status=summary.status or _("returned data"),
        )
        pane = wx.CollapsiblePane(
            parent,
            label=label,
            style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE,
        )
        pane.SetName(
            f"tool:{summary.tool_name.strip().lower() if summary.tool_name else ''}:{summary.index}"
        )
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
        summary_ctrl.SetMinSize((-1, parent.FromDIP(100)))
        inner_sizer.Add(summary_ctrl, 0, wx.EXPAND | wx.TOP, parent.FromDIP(4))

        nested_sections: list[tuple[str, str, str, str, int]] = []
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
                inner_sizer.Add(nested, 0, wx.EXPAND | wx.TOP, parent.FromDIP(4))

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
        lines.extend(self._render_tool_exchange(event))
        if event.call_identifier:
            lines.append(
                _("Call identifier: {identifier}").format(
                    identifier=event.call_identifier
                )
            )
        return "\n".join(lines)

    def _render_tool_exchange(self, event: ToolCallEvent) -> list[str]:
        payload = event.llm_request
        if not payload:
            return []

        lines: list[str] = []
        request_payload: Any = payload
        response_payload: Any | None = None
        step_label: str | None = None

        if isinstance(payload, Mapping):
            response_payload = payload.get("response")
            tool_call_payload = payload.get("tool_call")
            if tool_call_payload is not None:
                request_payload = tool_call_payload
            step_value = payload.get("step")
            if isinstance(step_value, (int, str)):
                step_text = str(step_value).strip()
                if step_text:
                    step_label = step_text

        request_text = _format_raw_payload(request_payload)
        if request_text:
            lines.append(_("LLM request:"))
            if step_label is not None:
                lines.append(
                    _("  • Step {step}").format(step=normalize_for_display(step_label))
                )
            lines.extend(self._indent_for_summary(request_text))

        response_text = _format_raw_payload(response_payload)
        if response_text:
            lines.append(_("LLM response:"))
            lines.extend(self._indent_for_summary(response_text))

        return lines

    @staticmethod
    def _indent_for_summary(text: str) -> list[str]:
        lines = text.splitlines()
        if not lines:
            return ["    "]
        return ["    " + segment if segment else "    " for segment in lines]


    # ------------------------------------------------------------------
    def _create_agent_panel(
        self,
        timeline: EntryTimeline,
        *,
        on_regenerate: Callable[[], None] | None,
        regenerate_enabled: bool,
    ) -> tuple[wx.Window | None, wx.Button | None]:
        relevant_kinds = {
            ChatEventKind.REASONING,
            ChatEventKind.LLM_REQUEST,
            ChatEventKind.RESPONSE,
            ChatEventKind.TOOL_CALL,
            ChatEventKind.RAW_PAYLOAD,
        }
        events = [
            event
            for event in timeline.events
            if event.kind in relevant_kinds and event.entry_id == timeline.entry_id
        ]
        if not events and not timeline.can_regenerate:
            return None, None

        container = wx.Panel(self)
        container.SetBackgroundColour(self.GetBackgroundColour())
        container.SetForegroundColour(self.GetForegroundColour())
        container.SetDoubleBuffered(True)
        container.SetName("agent-entry")
        container_sizer = wx.BoxSizer(wx.VERTICAL)
        container.SetSizer(container_sizer)

        rendered: list[wx.Window] = []
        final_bubble: MessageBubble | None = None

        for event in events:
            if isinstance(event, ResponseEvent):
                bubble = self._create_agent_message_bubble(container, event)
                if bubble is None:
                    continue
                rendered.append(bubble)
                if event.is_final:
                    final_bubble = bubble
                continue

            section = self._create_agent_section(container, event)
            if section is None:
                continue
            rendered.append(section)

        if final_bubble is None and timeline.response is not None:
            bubble = self._create_agent_message_bubble(container, timeline.response)
            if bubble is not None:
                rendered.append(bubble)
                final_bubble = bubble

        if final_bubble is not None:
            self._agent_bubble = final_bubble

        for index, widget in enumerate(rendered):
            container_sizer.Add(
                widget,
                0,
                wx.EXPAND | (wx.TOP if index else 0),
                container.FromDIP(4) if index else 0,
            )

        regenerate_button: wx.Button | None = None
        if timeline.can_regenerate and on_regenerate is not None:
            regenerate_button = wx.Button(
                self,
                label=_("Regenerate"),
                style=wx.BU_EXACTFIT,
            )
            regenerate_button.SetToolTip(_("Restart response generation"))
            regenerate_button.Bind(wx.EVT_BUTTON, self._on_regenerate_clicked)
            regenerate_button.Enable(regenerate_enabled)
            self._regenerate_handler = on_regenerate
        else:
            self._regenerate_handler = on_regenerate

        if not rendered:
            container.Destroy()
            return None, regenerate_button

        return container, regenerate_button

    # ------------------------------------------------------------------
    def _create_agent_message_bubble(
        self, parent: wx.Window, event: ResponseEvent
    ) -> MessageBubble | None:
        text = event.display_text or event.text or ""
        if not text and not event.is_final:
            return None

        timestamp_label = event.formatted_timestamp
        if not timestamp_label:
            if event.step_index is not None and not event.is_final:
                timestamp_label = _("Step {index}").format(index=event.step_index)
            elif event.timestamp:
                timestamp_label = normalize_for_display(event.timestamp)

        bubble = MessageBubble(
            parent,
            role_label=_("Agent"),
            timestamp=timestamp_label,
            text=text,
            align="left",
            allow_selection=True,
            render_markdown=True,
            width_hint=self._resolve_hint("agent"),
            on_width_change=lambda width: self._emit_layout_hint("agent", width),
        )
        return bubble

    # ------------------------------------------------------------------
    def _create_agent_section(
        self, parent: wx.Window, event: ChatEvent
    ) -> wx.Window | None:
        if isinstance(event, ReasoningEvent):
            text = _format_reasoning_segments(event.segments)
            if not text:
                return None
            key = f"reasoning:{event.event_id}"
            pane = _build_collapsible_section(
                parent,
                label=_("Model reasoning"),
                content=text,
                minimum_height=160,
                collapsed=self._collapsed_state.get(key, True),
                name="reasoning",
            )
            if pane is not None:
                self._register_collapsible(key, pane)
            return pane

        if isinstance(event, LlmRequestEvent):
            payload: dict[str, Any] = {"messages": event.messages}
            if event.sequence is not None:
                payload["sequence"] = event.sequence
            text = _format_raw_payload(payload)
            if not text:
                return None
            key = f"llm-request:{event.event_id}"
            pane = _build_collapsible_section(
                parent,
                label=_("LLM request"),
                content=text,
                minimum_height=160,
                collapsed=self._collapsed_state.get(key, True),
                name="raw:llm-request",
            )
            if pane is not None:
                self._register_collapsible(key, pane)
            return pane

        if isinstance(event, ToolCallEvent):
            pane = self._create_tool_collapsible(parent, event)
            if pane is not None:
                self._register_collapsible(f"tool:{event.event_id}", pane)
            return pane

        if isinstance(event, RawPayloadEvent):
            text = _format_raw_payload(event.payload)
            if not text:
                return None
            key = f"raw:{event.event_id}"
            pane = _build_collapsible_section(
                parent,
                label=_("Raw data"),
                content=text,
                minimum_height=160,
                collapsed=self._collapsed_state.get(key, True),
                name="raw:agent",
            )
            if pane is not None:
                self._register_collapsible(key, pane)
            return pane

        return None

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
