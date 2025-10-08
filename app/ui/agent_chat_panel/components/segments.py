"""Widgets and helpers for rendering transcript segments inside the chat panel."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import suppress
import json
from typing import Any, Literal

from dataclasses import dataclass, field

import wx

from ....i18n import _
from ...text import normalize_for_display
from ...widgets.chat_message import MessageBubble, tool_bubble_palette
from ..history_utils import format_value_snippet, history_json_safe
from ..tool_summaries import ToolCallSummary, prettify_key
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


class _LabeledCollapsiblePane(wx.CollapsiblePane):
    """Collapsible pane that preserves the assigned label for testing hooks."""

    def __init__(self, parent: wx.Window, *, label: str, style: int) -> None:
        super().__init__(parent, label=label, style=style)
        self._stored_label = label

    def SetLabel(self, label: str) -> None:  # noqa: N802 - wx naming convention
        self._stored_label = label
        super().SetLabel(label)

    def GetLabel(self) -> str:  # noqa: N802 - wx naming convention
        return self._stored_label

    def Collapse(self, collapse: bool) -> None:  # noqa: N802 - wx naming convention
        super().Collapse(collapse)
        if collapse:
            return
        callback = getattr(self, "_cookareq_on_expand", None)
        if callable(callback):
            with suppress(Exception):
                callback()


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

    pane = _LabeledCollapsiblePane(
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


@dataclass(slots=True)
class _DeferredPayloadState:
    pane: wx.CollapsiblePane
    text_ctrl: wx.TextCtrl
    raw_payload: Any
    cached_text: str | None = None
    loading: bool = False
    handler: Callable[[wx.CollapsiblePaneEvent], None] | None = None
    mirrors: list[wx.TextCtrl] = field(default_factory=list)


def _build_deferred_payload_section(
    parent: wx.Window,
    *,
    label: str,
    minimum_height: int,
    collapsed: bool,
    name: str | None,
    raw_payload: Any,
    callback: Callable[[wx.CollapsiblePane, wx.TextCtrl, Any], None],
) -> wx.CollapsiblePane:
    pane = _LabeledCollapsiblePane(
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
        value="",
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

    callback(pane, text_ctrl, raw_payload)
    return pane


def _extract_bullet_label(text: str) -> str:
    label, separator, _ = text.partition(":")
    if not separator:
        return ""
    return normalize_for_display(label).strip().casefold()


def _format_argument_line(key: Any, value: Any) -> str:
    value_text = format_value_snippet(value)
    if not value_text:
        return ""
    if isinstance(key, str):
        normalized_key = normalize_for_display(key.strip())
        if not normalized_key:
            return value_text
        lowered = normalized_key.casefold()
        if lowered == "rid":
            return _("Requirement: {rid}").format(rid=value_text)
        if lowered == "directory":
            return ""
    label = prettify_key(key)
    if not label:
        return value_text
    return _("{label}: {value}").format(label=label, value=value_text)


def _summarize_request_arguments(
    arguments: Any, *, skip_labels: Collection[str] = ()
) -> list[str]:
    skip = {label.casefold() for label in skip_labels if label}
    if isinstance(arguments, Mapping):
        lines: list[str] = []
        for key, value in arguments.items():
            line = _format_argument_line(key, value)
            if not line:
                continue
            label_key = _extract_bullet_label(line)
            if label_key:
                if label_key in skip:
                    continue
                skip.add(label_key)
            if len(lines) >= 5:
                break
            lines.append(line)
        return lines
    if arguments is not None:
        line = _("Arguments: {value}").format(
            value=format_value_snippet(arguments)
        )
        label_key = _extract_bullet_label(line)
        if not label_key or label_key not in skip:
            return [line]
    return []


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
        """Initialise panel bookkeeping for a chat segment."""
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
        self._alias_collapsibles: list[wx.CollapsiblePane] = []
        self._regenerate_button: wx.Button | None = None
        self._regenerate_handler: Callable[[], None] | None = None
        self._deferred_payloads: dict[str, _DeferredPayloadState] = {}

    # ------------------------------------------------------------------
    def update(
        self,
        payload: PromptSegment | AgentSegment,
        *,
        regenerate_enabled: bool,
        on_regenerate: Callable[[], None] | None,
    ) -> None:
        """Populate the panel with widgets for the supplied ``payload``."""
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
            for event in turn.events:
                if event.kind == "response" and event.response is not None:
                    bubble = self._create_agent_message_bubble(
                        container, event.response, timestamp_info
                    )
                    if bubble is not None:
                        rendered.append(bubble)
                elif event.kind == "tool" and event.tool_call is not None:
                    bubble, raw_section = self._render_tool_event(
                        container, event.tool_call, event.order_index
                    )
                    if bubble is not None:
                        rendered.append(bubble)
                    if raw_section is not None:
                        rendered.append(raw_section)

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
    def _render_tool_event(
        self,
        parent: wx.Window,
        details: ToolCallDetails,
        order_index: int,
    ) -> tuple[MessageBubble | None, wx.CollapsiblePane | None]:
        bubble = self._create_tool_summary_bubble(parent, details)
        raw_section = self._create_tool_raw_section(parent, details, order_index)
        return bubble, raw_section

    # ------------------------------------------------------------------
    def _create_tool_summary_bubble(
        self, parent: wx.Window, details: ToolCallDetails
    ) -> MessageBubble | None:
        summary = details.summary
        tool_name = summary.tool_name or "Tool"
        status = summary.status or "returned data"
        heading = f"Tool call {normalize_for_display(tool_name)} — {normalize_for_display(status)}"

        bullet_lines = self._collect_tool_bullet_lines(summary)
        text_lines = [heading]
        text_lines.extend(f"• {line}" for line in bullet_lines if line)
        text = "\n".join(text_lines)
        if not text.strip():
            return None

        timestamp_label = self._format_timestamp(details.timestamp) or None
        bubble = MessageBubble(
            parent,
            role_label="Tool",
            timestamp=timestamp_label,
            text=text,
            align="left",
            allow_selection=True,
            palette=tool_bubble_palette(self.GetBackgroundColour(), tool_name),
            width_hint=self._resolve_hint("tool"),
            on_width_change=lambda width: self._emit_layout_hint("tool", width),
        )
        return bubble

    # ------------------------------------------------------------------
    def _collect_tool_bullet_lines(self, summary: ToolCallSummary) -> list[str]:
        bullet_lines: list[str] = []
        seen_lines: set[str] = set()
        seen_labels: set[str] = set()

        def add_bullet_line(text: str | None) -> None:
            if not text:
                return
            normalized = normalize_for_display(text).strip()
            if not normalized:
                return
            key = normalized.casefold()
            if key in seen_lines:
                return
            seen_lines.add(key)
            label_key = _extract_bullet_label(normalized)
            if label_key:
                seen_labels.add(label_key)
            bullet_lines.append(normalized)

        if summary.cost:
            add_bullet_line(
                f"Cost: {normalize_for_display(summary.cost)}"
            )
        if summary.error_message:
            add_bullet_line(
                f"Error: {normalize_for_display(summary.error_message)}"
            )

        for bullet in summary.bullet_lines:
            add_bullet_line(bullet)

        for argument in _summarize_request_arguments(
            summary.arguments, skip_labels=seen_labels
        ):
            add_bullet_line(argument)

        return bullet_lines

    # ------------------------------------------------------------------
    def _create_tool_raw_section(
        self,
        parent: wx.Window,
        details: ToolCallDetails,
        order_index: int,
    ) -> wx.CollapsiblePane | None:
        if details.raw_data is None:
            return None

        identifier = self._make_tool_identifier(details, order_index)
        state_key = f"tool:raw:{identifier}"
        pane = _build_deferred_payload_section(
            parent,
            label=_("Raw data"),
            minimum_height=160,
            collapsed=self._collapsed_state.get(state_key, True),
            name=state_key,
            raw_payload=details.raw_data,
            callback=lambda created_pane, text_ctrl, payload: self._register_deferred_payload(
                state_key, created_pane, text_ctrl, payload
            ),
        )
        self._register_collapsible(state_key, pane)
        handler = self._make_deferred_loader(state_key)
        pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, handler)
        state = self._deferred_payloads.get(state_key)
        if state is not None:
            state.handler = handler
        wx.CallAfter(lambda: self._ensure_deferred_payload_loaded(state_key))
        return pane

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
        if raw_payload is None:
            return None
        key = f"raw:{self._entry_id}"
        pane = _build_deferred_payload_section(
            parent,
            label=_("Raw response payload"),
            minimum_height=160,
            collapsed=self._collapsed_state.get(key, True),
            name=key,
            raw_payload=raw_payload,
            callback=lambda created_pane, text_ctrl, payload: self._register_deferred_payload(
                key, created_pane, text_ctrl, payload
            ),
        )
        self._register_collapsible(key, pane)
        handler = self._make_deferred_loader(key)
        pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, handler)
        state = self._deferred_payloads.get(key)
        if state is not None:
            state.handler = handler
        alias_name = "raw:agent"
        if not any(alias.GetName() == alias_name for alias in self._alias_collapsibles):
            alias = _build_deferred_payload_section(
                parent,
                label=_("Raw response payload"),
                minimum_height=160,
                collapsed=True,
                name=alias_name,
                raw_payload=raw_payload,
                callback=lambda alias_pane, alias_ctrl, _payload: self._attach_deferred_mirror(
                    key, alias_pane, alias_ctrl
                ),
            )
            alias.Hide()
            self._alias_collapsibles.append(alias)
        return pane

    # ------------------------------------------------------------------
    def _capture_collapsed_state(self) -> None:
        for alias in self._alias_collapsibles:
            with suppress(RuntimeError):
                alias.Destroy()
            with suppress(AttributeError):
                delattr(alias, "_cookareq_on_expand")
        self._alias_collapsibles.clear()
        for key, state in list(self._deferred_payloads.items()):
            pane = state.pane
            if isinstance(pane, wx.CollapsiblePane):
                with suppress(RuntimeError):
                    self._collapsed_state[key] = pane.IsCollapsed()
                handler = state.handler
                if handler is not None:
                    with suppress(RuntimeError):
                        pane.Unbind(wx.EVT_COLLAPSIBLEPANE_CHANGED, handler=handler)
                with suppress(AttributeError):
                    delattr(pane, "_cookareq_on_expand")
            state.mirrors.clear()
        self._deferred_payloads.clear()
        for key, pane in list(self._collapsible.items()):
            if isinstance(pane, wx.CollapsiblePane):
                with suppress(RuntimeError):
                    self._collapsed_state[key] = pane.IsCollapsed()

    # ------------------------------------------------------------------
    def _register_collapsible(self, key: str, pane: wx.CollapsiblePane) -> None:
        if key:
            self._collapsible[key] = pane

    # ------------------------------------------------------------------
    def _register_deferred_payload(
        self,
        key: str,
        pane: wx.CollapsiblePane,
        text_ctrl: wx.TextCtrl,
        raw_payload: Any,
    ) -> None:
        def loader() -> None:
            self._ensure_deferred_payload_loaded(key)

        pane._cookareq_on_expand = loader  # type: ignore[attr-defined]
        self._deferred_payloads[key] = _DeferredPayloadState(
            pane=pane,
            text_ctrl=text_ctrl,
            raw_payload=raw_payload,
        )

    # ------------------------------------------------------------------
    def _attach_deferred_mirror(
        self,
        key: str,
        _pane: wx.CollapsiblePane,
        text_ctrl: wx.TextCtrl,
    ) -> None:
        state = self._deferred_payloads.get(key)
        if state is None:
            return
        state.mirrors.append(text_ctrl)

    # ------------------------------------------------------------------
    def _apply_deferred_text(
        self, state: _DeferredPayloadState, text: str
    ) -> None:
        with suppress(RuntimeError):
            state.text_ctrl.ChangeValue(text)
        for mirror in list(state.mirrors):
            with suppress(RuntimeError):
                mirror.ChangeValue(text)

    # ------------------------------------------------------------------
    def _ensure_deferred_payload_loaded(self, key: str) -> None:
        state = self._deferred_payloads.get(key)
        if state is None:
            return
        if state.cached_text is not None:
            self._apply_deferred_text(state, state.cached_text)
            handler = state.handler
            if handler is not None:
                with suppress(RuntimeError):
                    state.pane.Unbind(wx.EVT_COLLAPSIBLEPANE_CHANGED, handler=handler)
                state.handler = None
            return
        if state.loading:
            return

        state.loading = True
        placeholder = _("Загрузка…")
        self._apply_deferred_text(state, placeholder)

        raw_payload = state.raw_payload

        def finish() -> None:
            try:
                safe_payload = history_json_safe(raw_payload)
                try:
                    text = json.dumps(safe_payload, ensure_ascii=False, indent=2)
                except (TypeError, ValueError):
                    text = normalize_for_display(str(safe_payload))
            except Exception:
                text = normalize_for_display(str(raw_payload))

            state.cached_text = text
            state.loading = False
            self._apply_deferred_text(state, text)
            with suppress(RuntimeError):
                state.text_ctrl.ShowPosition(0)

            handler_ref = state.handler
            if handler_ref is not None:
                with suppress(RuntimeError):
                    state.pane.Unbind(
                        wx.EVT_COLLAPSIBLEPANE_CHANGED, handler=handler_ref
                    )
                state.handler = None

        wx.CallAfter(finish)

    def _make_deferred_loader(
        self, key: str
    ) -> Callable[[wx.CollapsiblePaneEvent], None]:
        def handler(event: wx.CollapsiblePaneEvent) -> None:
            if event.GetCollapsed():
                event.Skip()
                return
            self._ensure_deferred_payload_loaded(key)
            event.Skip()

        return handler

    # ------------------------------------------------------------------
    def _make_tool_identifier(
        self, details: ToolCallDetails, order_index: int
    ) -> str:
        summary_index = details.summary.index
        if summary_index:
            return f"tool:{self._entry_id}:{summary_index}"
        return f"tool:{self._entry_id}:{order_index}"

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
        with suppress(Exception):
            self._on_layout_hint(key, width)

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
        with suppress(Exception):
            handler()
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
        """Prepare sub-panels used to render a conversation entry."""
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
        """Render transcript ``segments`` and capture regenerated state."""
        self._capture_system_state()
        previous_notice = self._regenerated_notice
        sizer = self.GetSizer()
        sizer.Clear(delete_windows=False)
        self._regenerated_notice = None
        if previous_notice is not None:
            with suppress(RuntimeError):
                previous_notice.Destroy()

        prompt_segment = next(
            (segment for segment in segments if segment.kind == "user"),
            None,
        )
        agent_segment = next(
            (segment for segment in segments if segment.kind == "agent"),
            None,
        )
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
                with suppress(RuntimeError):
                    pane.Destroy()
        self._system_sections.clear()

    # ------------------------------------------------------------------
__all__ = ["MessageSegmentPanel", "TurnCard"]
