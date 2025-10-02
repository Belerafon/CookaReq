"""Segment-based widgets for the agent chat transcript."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
import json
from typing import Any, Literal

import wx

from ....i18n import _
from ...text import normalize_for_display
from ...widgets.chat_message import MessageBubble, tool_bubble_palette
from ..history_utils import format_value_snippet, history_json_safe
from ..view_model import (
    AgentResponse,
    AgentSegment,
    LlmRequestSnapshot,
    PromptMessage,
    PromptSegment,
    TranscriptSegment,
    SystemMessage,
    TimestampInfo,
    ToolCallDetails,
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

    merged: list[tuple[str, str]] = []
    for segment in segments:
        if isinstance(segment, Mapping):
            type_value = segment.get("type")
            text_value = segment.get("text")
            leading_value = segment.get("leading_whitespace")
            trailing_value = segment.get("trailing_whitespace")
        else:
            type_value = getattr(segment, "type", None)
            text_value = getattr(segment, "text", None)
            leading_value = getattr(segment, "leading_whitespace", "")
            trailing_value = getattr(segment, "trailing_whitespace", "")
        if text_value is None:
            continue
        text = str(text_value)
        if not text.strip():
            continue
        leading = str(leading_value or "")
        trailing = str(trailing_value or "")
        raw_text = f"{leading}{text}{trailing}"
        if not raw_text.strip():
            continue
        type_label = str(type_value).strip() if type_value is not None else ""
        if merged and merged[-1][0] == type_label:
            merged[-1] = (type_label, _merge_reasoning_text(merged[-1][1], raw_text))
        else:
            merged.append((type_label, raw_text))

    blocks: list[str] = []
    for index, (type_label, text) in enumerate(merged, start=1):
        heading = type_label or _("Thought {index}").format(index=index)
        blocks.append(f"{heading}\n{text}")
    return "\n\n".join(blocks)


def _merge_reasoning_text(existing: str, addition: str) -> str:
    if not existing:
        return addition
    if not addition:
        return existing
    if existing.endswith(("\n", "\r")) or addition.startswith("\n"):
        return existing + addition
    if existing.endswith(" ") or addition.startswith(" "):
        return existing + addition
    return f"{existing}{addition}"


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


def _summarize_request_arguments(arguments: Any) -> list[str]:
    if isinstance(arguments, Mapping):
        lines: list[str] = []
        for key, value in arguments.items():
            key_text = normalize_for_display(str(key).strip())
            value_text = format_value_snippet(value)
            if key_text and value_text:
                lines.append(f"{key_text}: {value_text}")
            elif key_text:
                lines.append(key_text)
            elif value_text:
                lines.append(value_text)
        return lines
    if arguments is not None:
        value_text = format_value_snippet(arguments)
        if value_text:
            return [value_text]
    return []


def _summarize_tool_payload(payload: Any) -> list[str]:
    if isinstance(payload, Mapping):
        description = payload.get("description")
        if isinstance(description, str):
            text = normalize_for_display(description).strip()
            if text:
                return [text]
        arguments = payload.get("arguments")
        return _summarize_request_arguments(arguments)
    return _summarize_request_arguments(payload)


def _summarize_llm_request(snapshot: LlmRequestSnapshot | None) -> list[str]:
    if snapshot is None or not snapshot.messages:
        return []
    messages: list[str] = []
    for message in snapshot.messages:
        if not isinstance(message, Mapping):
            continue
        role = normalize_for_display(str(message.get("role", "")).strip())
        content = message.get("content")
        if isinstance(content, str):
            body = normalize_for_display(content)
        elif isinstance(content, Sequence):
            parts: list[str] = []
            for fragment in content:
                if isinstance(fragment, Mapping):
                    parts.append(normalize_for_display(str(fragment.get("text", ""))))
                else:
                    parts.append(normalize_for_display(str(fragment)))
            body = "\n".join(part for part in parts if part)
        else:
            body = normalize_for_display(str(content))
        if role and body:
            messages.append(f"{role}: {body}")
        elif body:
            messages.append(body)
    return [message for message in messages if message]


def _summarize_system_message(system_message: SystemMessage) -> str:
    message = normalize_for_display(system_message.message or "").strip()
    details = normalize_for_display(str(system_message.details or "")).strip()
    if message and details:
        return f"{message}\n{details}"
    return message or details


class MessageSegmentPanel(wx.Panel):
    """Render a single user or agent message segment."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        entry_id: str,
        segment_kind: Literal["user", "agent"],
        on_layout_hint: Callable[[str, int], None] | None,
    ) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(parent.GetBackgroundColour())
        self.SetForegroundColour(parent.GetForegroundColour())
        self.SetDoubleBuffered(True)
        self.SetSizer(wx.BoxSizer(wx.VERTICAL))
        self._entry_id = entry_id
        self._segment_kind = segment_kind
        self._on_layout_hint = on_layout_hint
        self._layout_hints: dict[str, int] = {}
        self._collapsible: dict[str, wx.CollapsiblePane] = {}
        self._collapsed_state: dict[str, bool] = {}
        self._regenerate_button: wx.Button | None = None
        self._regenerate_handler: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    def update(
        self,
        payload: PromptSegment | AgentSegment,
        *,
        regenerate_enabled: bool,
        on_regenerate: Callable[[], None] | None,
    ) -> None:
        self._capture_collapsed_state()
        self._collapsible.clear()
        sizer = self.GetSizer()
        sizer.Clear(delete_windows=True)
        self._regenerate_button = None
        self._regenerate_handler = on_regenerate

        if self._segment_kind == "user":
            assert isinstance(payload, PromptSegment)
            self._layout_hints = dict(payload.layout_hints)
            self._build_user_segment(payload)
        else:
            assert isinstance(payload, AgentSegment)
            self._layout_hints = dict(payload.layout_hints)
            self._build_agent_segment(
                payload,
                regenerate_enabled=regenerate_enabled,
                on_regenerate=on_regenerate,
            )
        self.Layout()

    # ------------------------------------------------------------------
    def enable_regenerate(self, enabled: bool) -> None:
        if self._regenerate_button is not None:
            self._regenerate_button.Enable(enabled)

    # ------------------------------------------------------------------
    def _build_user_segment(self, payload: PromptSegment) -> None:
        prompt = payload.prompt
        if prompt is None and not payload.context_messages:
            return
        if prompt is None:
            prompt = PromptMessage(
                text="",
                timestamp=TimestampInfo(raw="", occurred_at=None, formatted="", missing=True),
            )

        bubble = MessageBubble(
            self,
            role_label=_("You"),
            timestamp=self._format_timestamp(prompt.timestamp),
            text=prompt.text,
            align="right",
            allow_selection=True,
            width_hint=self._resolve_hint("user"),
            on_width_change=lambda width: self._emit_layout_hint("user", width),
        )
        self.GetSizer().Add(bubble, 0, wx.EXPAND)

        if payload.context_messages:
            pane = _build_collapsible_section(
                self,
                label=_("Context"),
                content=_format_context_messages(payload.context_messages),
                minimum_height=140,
                collapsed=self._collapsed_state.get("context", True),
                name=f"context:{self._entry_id}",
            )
            if pane is not None:
                self._register_collapsible("context", pane)
                self.GetSizer().Add(pane, 0, wx.EXPAND | wx.TOP, self.FromDIP(4))

    # ------------------------------------------------------------------
    def _build_agent_segment(
        self,
        payload: AgentSegment,
        *,
        regenerate_enabled: bool,
        on_regenerate: Callable[[], None] | None,
    ) -> None:
        turn = payload.turn
        container = wx.Panel(self)
        container.SetBackgroundColour(self.GetBackgroundColour())
        container.SetForegroundColour(self.GetForegroundColour())
        container.SetDoubleBuffered(True)
        container.SetSizer(wx.BoxSizer(wx.VERTICAL))

        rendered: list[wx.Window] = []
        timestamp_info = turn.timestamp if turn is not None else None
        if turn is not None:
            for response in turn.streamed_responses:
                bubble = self._create_agent_message_bubble(
                    container, response, timestamp_info
                )
                if bubble is not None:
                    rendered.append(bubble)
            if turn.final_response is not None:
                bubble = self._create_agent_message_bubble(
                    container, turn.final_response, timestamp_info
                )
                if bubble is not None:
                    rendered.append(bubble)

        if turn is not None:
            reasoning_section = self._create_reasoning_section(
                container, payload, turn.reasoning
            )
            if reasoning_section is not None:
                rendered.append(reasoning_section)

            llm_section = self._create_llm_request_section(
                container, payload, turn.llm_request
            )
            if llm_section is not None:
                rendered.append(llm_section)

            raw_section = self._create_raw_payload_section(
                container, payload, turn.raw_payload
            )
            if raw_section is not None:
                rendered.append(raw_section)

        for index, widget in enumerate(rendered):
            container.GetSizer().Add(
                widget,
                0,
                wx.EXPAND | (wx.TOP if index else 0),
                container.FromDIP(4) if index else 0,
            )

        if rendered:
            self.GetSizer().Add(container, 0, wx.EXPAND)
        else:
            container.Destroy()

        if payload.can_regenerate and on_regenerate is not None:
            button = wx.Button(
                self,
                label=_("Regenerate"),
                style=wx.BU_EXACTFIT,
            )
            button.SetToolTip(_("Restart response generation"))
            button.Bind(wx.EVT_BUTTON, self._on_regenerate_clicked)
            button.Enable(regenerate_enabled)
            self.GetSizer().Add(
                button,
                0,
                wx.ALIGN_RIGHT | wx.TOP,
                self.FromDIP(4),
            )
            self._regenerate_button = button

    # ------------------------------------------------------------------
    def _create_agent_message_bubble(
        self,
        parent: wx.Window,
        response: AgentResponse,
        turn_timestamp: TimestampInfo | None,
    ) -> MessageBubble | None:
        text = response.display_text or response.text or ""
        if not text and not response.is_final:
            return None

        labels: list[str] = []
        if response.step_index is not None and not response.is_final:
            labels.append(_("Step {index}").format(index=response.step_index))

        own_timestamp = self._format_timestamp(response.timestamp)
        if own_timestamp:
            labels.append(own_timestamp)
        else:
            fallback = self._format_timestamp(turn_timestamp)
            if fallback:
                labels.append(fallback)
            elif turn_timestamp is not None and turn_timestamp.missing:
                labels.append(_("Timestamp unavailable"))

        timestamp_label = " • ".join(label for label in labels if label)

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
    def _create_reasoning_section(
        self,
        parent: wx.Window,
        payload: AgentSegment,
        reasoning: Sequence[Mapping[str, Any]] | None,
    ) -> wx.CollapsiblePane | None:
        text = _format_reasoning_segments(reasoning)
        if not text:
            return None
        key = f"reasoning:{self._entry_id}"
        pane = _build_collapsible_section(
            parent,
            label=_("Model reasoning"),
            content=text,
            minimum_height=160,
            collapsed=self._collapsed_state.get(key, True),
            name=key,
        )
        if pane is not None:
            self._register_collapsible(key, pane)
        return pane

    # ------------------------------------------------------------------
    def _create_llm_request_section(
        self,
        parent: wx.Window,
        payload: AgentSegment,
        snapshot: LlmRequestSnapshot | None,
    ) -> wx.CollapsiblePane | None:
        summary_lines = _summarize_llm_request(snapshot)
        if not summary_lines:
            return None
        text = "\n\n".join(summary_lines)
        key = f"llm:{self._entry_id}"
        pane = _build_collapsible_section(
            parent,
            label=_("Request sent to the LLM"),
            content=text,
            minimum_height=160,
            collapsed=self._collapsed_state.get(key, True),
            name=key,
        )
        if pane is not None:
            self._register_collapsible(key, pane)
        return pane

    # ------------------------------------------------------------------
    def _create_raw_payload_section(
        self,
        parent: wx.Window,
        payload: AgentSegment,
        raw_payload: Any,
    ) -> wx.CollapsiblePane | None:
        text = _format_raw_payload(raw_payload)
        if not text:
            return None
        key = f"raw:{self._entry_id}"
        pane = _build_collapsible_section(
            parent,
            label=_("Raw response payload"),
            content=text,
            minimum_height=160,
            collapsed=self._collapsed_state.get(key, True),
            name=key,
        )
        if pane is not None:
            self._register_collapsible(key, pane)
        return pane

    # ------------------------------------------------------------------
    def _capture_collapsed_state(self) -> None:
        for key, pane in list(self._collapsible.items()):
            if isinstance(pane, wx.CollapsiblePane):
                self._collapsed_state[key] = pane.IsCollapsed()

    # ------------------------------------------------------------------
    def _register_collapsible(self, key: str, pane: wx.CollapsiblePane) -> None:
        if key:
            self._collapsible[key] = pane

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
    @staticmethod
    def _format_timestamp(timestamp: TimestampInfo | None) -> str:
        if timestamp is None:
            return ""
        if timestamp.formatted:
            return timestamp.formatted
        if timestamp.raw:
            return normalize_for_display(timestamp.raw)
        if timestamp.missing:
            return _("Timestamp unavailable")
        return ""

    # ------------------------------------------------------------------
    def _on_regenerate_clicked(self, _event: wx.CommandEvent) -> None:
        handler = self._regenerate_handler
        if handler is None:
            return
        try:
            handler()
        except Exception:
            pass


class ToolCallPanel(wx.Panel):
    """Render a single tool call entry."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        entry_id: str,
        on_layout_hint: Callable[[str, int], None] | None,
    ) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(parent.GetBackgroundColour())
        self.SetForegroundColour(parent.GetForegroundColour())
        self.SetDoubleBuffered(True)
        self.SetSizer(wx.BoxSizer(wx.VERTICAL))
        self._entry_id = entry_id
        self._on_layout_hint = on_layout_hint
        self._layout_hints: dict[str, int] = {}
        self._collapsible: dict[str, wx.CollapsiblePane] = {}
        self._collapsed_state: dict[str, bool] = {}

    # ------------------------------------------------------------------
    def update(self, details: ToolCallDetails) -> None:
        self._capture_collapsed_state()
        self._collapsible.clear()
        sizer = self.GetSizer()
        sizer.Clear(delete_windows=True)

        summary = details.summary
        header = self._create_summary_bubble(details)
        if header is not None:
            sizer.Add(header, 0, wx.EXPAND)

        sections = self._build_sections(details)
        for index, pane in enumerate(sections):
            sizer.Add(
                pane,
                0,
                wx.EXPAND | wx.TOP,
                self.FromDIP(4) if index or header is not None else 0,
            )

        self.Layout()

    # ------------------------------------------------------------------
    def _create_summary_bubble(self, details: ToolCallDetails) -> MessageBubble | None:
        summary = details.summary
        tool_name = summary.tool_name or _("Tool")
        status = summary.status or _("returned data")
        lines: list[str] = [
            _("Ran {tool} — {status}").format(
                tool=normalize_for_display(tool_name),
                status=normalize_for_display(status),
            )
        ]

        arguments = _summarize_tool_payload(details.raw_payload)
        lines.extend(arguments)

        text = "\n".join(line for line in lines if line)
        if not text:
            return None

        bubble = MessageBubble(
            self,
            role_label=_("Tool"),
            timestamp=None,
            text=text,
            align="left",
            allow_selection=True,
            palette=tool_bubble_palette(self.GetBackgroundColour(), tool_name),
            width_hint=self._resolve_hint("tool"),
            on_width_change=lambda width: self._emit_layout_hint("tool", width),
        )
        return bubble

    # ------------------------------------------------------------------
    def _build_sections(self, details: ToolCallDetails) -> list[wx.CollapsiblePane]:
        sections: list[wx.CollapsiblePane] = []
        summary = details.summary
        entry_key = f"tool:{self._entry_id}:{summary.index}" if summary.index else self._entry_id

        summary_text = self._format_tool_summary_text(details)
        if summary_text:
            pane = _build_collapsible_section(
                self,
                label=_("Summary"),
                content=summary_text,
                minimum_height=120,
                collapsed=self._collapsed_state.get(f"summary:{entry_key}", True),
                name=f"tool:summary:{entry_key}",
            )
            if pane is not None:
                self._register_collapsible(f"summary:{entry_key}", pane)
                sections.append(pane)

        raw_text = _format_raw_payload(details.raw_payload)
        if raw_text:
            pane = _build_collapsible_section(
                self,
                label=_("Raw data"),
                content=raw_text,
                minimum_height=160,
                collapsed=self._collapsed_state.get(f"raw:{entry_key}", True),
                name=f"tool:raw:{entry_key}",
            )
            if pane is not None:
                self._register_collapsible(f"raw:{entry_key}", pane)
                sections.append(pane)

        llm_payload = details.llm_request
        if isinstance(llm_payload, Mapping):
            request_payload = llm_payload.get("tool_call") or llm_payload
            response_payload = llm_payload.get("response")
        else:
            request_payload = llm_payload
            response_payload = None

        request_text = _format_raw_payload(request_payload)
        if request_text:
            pane = _build_collapsible_section(
                self,
                label=_("LLM request"),
                content=request_text,
                minimum_height=160,
                collapsed=self._collapsed_state.get(f"llm-request:{entry_key}", True),
                name=f"tool:llm-request:{entry_key}",
            )
            if pane is not None:
                self._register_collapsible(f"llm-request:{entry_key}", pane)
                sections.append(pane)

        response_text = _format_raw_payload(response_payload)
        if response_text:
            pane = _build_collapsible_section(
                self,
                label=_("LLM response"),
                content=response_text,
                minimum_height=160,
                collapsed=self._collapsed_state.get(f"llm-response:{entry_key}", True),
                name=f"tool:llm-response:{entry_key}",
            )
            if pane is not None:
                self._register_collapsible(f"llm-response:{entry_key}", pane)
                sections.append(pane)

        return sections

    # ------------------------------------------------------------------
    def _format_tool_summary_text(self, details: ToolCallDetails) -> str:
        summary = details.summary
        summary_lines: list[str] = []
        tool_name = summary.tool_name or _("Tool")
        summary_lines.append(_("Tool name: {tool}").format(tool=tool_name))
        if summary.status:
            summary_lines.append(
                _("Status: {status}").format(
                    status=normalize_for_display(summary.status)
                )
            )
        if summary.duration:
            summary_lines.append(
                _("Duration: {seconds:.2f} s").format(seconds=summary.duration)
            )
        if summary.cost is not None:
            summary_lines.append(_("Cost: {cost}").format(cost=summary.cost))
        if summary.error_message:
            summary_lines.append(
                _("Error: {message}").format(
                    message=normalize_for_display(summary.error_message)
                )
            )
        additional = _summarize_request_arguments(summary.arguments)
        summary_lines.extend(additional)
        return "\n".join(line for line in summary_lines if line)

    # ------------------------------------------------------------------
    def _capture_collapsed_state(self) -> None:
        for key, pane in list(self._collapsible.items()):
            if isinstance(pane, wx.CollapsiblePane):
                self._collapsed_state[key] = pane.IsCollapsed()

    # ------------------------------------------------------------------
    def _register_collapsible(self, key: str, pane: wx.CollapsiblePane) -> None:
        if key:
            self._collapsible[key] = pane

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


class TurnCard(wx.Panel):
    """Container combining message and diagnostic segments for an entry."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        entry_id: str,
        entry_index: int,
        on_layout_hint: Callable[[str, int], None] | None,
    ) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(parent.GetBackgroundColour())
        self.SetForegroundColour(parent.GetForegroundColour())
        self.SetDoubleBuffered(True)
        self.SetSizer(wx.BoxSizer(wx.VERTICAL))
        self._entry_id = entry_id
        self._entry_index = entry_index
        self._on_layout_hint = on_layout_hint
        self._user_panel = MessageSegmentPanel(
            self,
            entry_id=entry_id,
            segment_kind="user",
            on_layout_hint=on_layout_hint,
        )
        self._agent_panel = MessageSegmentPanel(
            self,
            entry_id=entry_id,
            segment_kind="agent",
            on_layout_hint=on_layout_hint,
        )
        self._tool_panels: dict[str, ToolCallPanel] = {}
        self._system_sections: dict[str, wx.CollapsiblePane] = {}
        self._collapsed_state: dict[str, bool] = {}
        self._regenerated_notice: wx.StaticText | None = None

    # ------------------------------------------------------------------
    def update(
        self,
        *,
        segments: Sequence[TranscriptSegment],
        on_regenerate: Callable[[], None] | None,
        regenerate_enabled: bool,
    ) -> None:
        self._capture_system_state()
        previous_notice = self._regenerated_notice
        sizer = self.GetSizer()
        sizer.Clear(delete_windows=False)
        self._regenerated_notice = None
        if previous_notice is not None:
            try:
                previous_notice.Destroy()
            except RuntimeError:
                pass

        prompt_segment = next(
            (segment for segment in segments if segment.kind == "user"),
            None,
        )
        agent_segment = next(
            (segment for segment in segments if segment.kind == "agent"),
            None,
        )
        tool_segments = [
            segment for segment in segments if segment.kind == "tool"
        ]
        system_segments = [
            segment for segment in segments if segment.kind == "system"
        ]

        if prompt_segment is not None:
            self._user_panel.update(
                prompt_segment.payload,
                regenerate_enabled=regenerate_enabled,
                on_regenerate=None,
            )
            self._user_panel.Show()
            sizer.Add(self._user_panel, 0, wx.EXPAND | wx.ALL, self.FromDIP(4))
        else:
            self._user_panel.Hide()

        if (
            agent_segment is not None
            and isinstance(agent_segment.payload, AgentSegment)
            and agent_segment.payload.turn is not None
            and agent_segment.payload.turn.final_response is not None
            and agent_segment.payload.turn.final_response.regenerated
        ):
            notice = wx.StaticText(self, label=_("Response was regenerated"))
            sizer.Add(notice, 0, wx.ALL, self.FromDIP(4))
            self._regenerated_notice = notice

        if agent_segment is not None:
            self._agent_panel.update(
                agent_segment.payload,
                regenerate_enabled=regenerate_enabled,
                on_regenerate=on_regenerate,
            )
            self._agent_panel.enable_regenerate(regenerate_enabled)
            self._agent_panel.Show()
            sizer.Add(self._agent_panel, 0, wx.EXPAND | wx.ALL, self.FromDIP(4))
        else:
            self._agent_panel.Hide()

        seen_tool_ids: set[str] = set()
        for tool_segment in tool_segments:
            details: ToolCallDetails = tool_segment.payload
            summary = details.summary
            identifier = (
                f"{tool_segment.entry_id}:{summary.index}"
                if summary.index is not None
                else f"{tool_segment.entry_id}:{id(details)}"
            )
            panel = self._tool_panels.get(identifier)
            if panel is None or not panel.IsShownOnScreen():
                panel = ToolCallPanel(
                    self,
                    entry_id=tool_segment.entry_id,
                    on_layout_hint=self._on_layout_hint,
                )
                self._tool_panels[identifier] = panel
            panel.update(details)
            panel.Show()
            sizer.Add(panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, self.FromDIP(4))
            seen_tool_ids.add(identifier)

        for stale_id in list(self._tool_panels.keys()):
            if stale_id in seen_tool_ids:
                continue
            panel = self._tool_panels.pop(stale_id)
            if panel.GetContainingSizer() is sizer:
                sizer.Detach(panel)
            panel.Destroy()

        for index, system_segment in enumerate(system_segments, start=1):
            text = _summarize_system_message(system_segment.payload)
            if not text:
                continue
            key = f"system:{self._entry_id}:{index}"
            pane = _build_collapsible_section(
                self,
                label=_("System message"),
                content=text,
                minimum_height=140,
                collapsed=self._collapsed_state.get(key, True),
                name=key,
            )
            if pane is None:
                continue
            self._system_sections[key] = pane
            sizer.Add(pane, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, self.FromDIP(4))

        self.Layout()

    # ------------------------------------------------------------------
    def _capture_system_state(self) -> None:
        for key, pane in list(self._system_sections.items()):
            if isinstance(pane, wx.CollapsiblePane):
                self._collapsed_state[key] = pane.IsCollapsed()
                try:
                    pane.Destroy()
                except RuntimeError:
                    pass
        self._system_sections.clear()


__all__ = ["MessageSegmentPanel", "ToolCallPanel", "TurnCard"]
