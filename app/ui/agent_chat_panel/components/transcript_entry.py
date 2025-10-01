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
from ..history_utils import format_value_snippet, history_json_safe
from ..tool_summaries import ToolCallSummary, extract_error_message
from ..view_model import (
    AgentResponse,
    AgentTurn,
    LlmRequestSnapshot,
    PromptMessage,
    TimestampInfo,
    ToolCallDetails,
    SystemMessage,
    TranscriptEntry,
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


def _normalise_text_lines(text: str | None) -> list[str]:
    if not text:
        return []
    result: list[str] = []
    for fragment in text.splitlines():
        normalised = normalize_for_display(fragment).strip()
        if normalised:
            result.append(normalised)
    return result


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


def _coerce_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _extract_tool_arguments(event: ToolCallDetails) -> Mapping[str, Any] | None:
    request_payload = _coerce_mapping(event.llm_request)
    if request_payload:
        call_payload = _coerce_mapping(request_payload.get("tool_call"))
        if call_payload:
            for key in ("arguments", "tool_arguments", "args"):
                candidate = _coerce_mapping(call_payload.get(key))
                if candidate:
                    return candidate
        for key in ("arguments", "tool_arguments", "args"):
            candidate = _coerce_mapping(request_payload.get(key))
            if candidate:
                return candidate

    payload_mapping = _coerce_mapping(event.raw_payload)
    if payload_mapping:
        for key in ("tool_arguments", "arguments", "args"):
            candidate = _coerce_mapping(payload_mapping.get(key))
            if candidate:
                return candidate
    return None


def _summarize_tool_arguments(event: ToolCallDetails) -> list[str]:
    arguments = _extract_tool_arguments(event)
    if not arguments:
        return []
    lines: list[str] = []
    for index, (key, value) in enumerate(arguments.items(), start=1):
        key_text = normalize_for_display(str(key).strip())
        if not key_text:
            key_text = f"arg{index}"
        value_text = format_value_snippet(value)
        if value_text:
            lines.append(f"{key_text}: {value_text}")
        else:
            lines.append(key_text)
        if len(lines) >= 6:
            lines.append("…")
            break
    return lines


def _extract_tool_result(event: ToolCallDetails) -> Any:
    payload_mapping = _coerce_mapping(event.raw_payload)
    if not payload_mapping:
        return None
    for key in ("result", "response", "data"):
        if key in payload_mapping:
            return payload_mapping.get(key)
    return None


def _summarize_tool_result(event: ToolCallDetails) -> list[str]:
    result_payload = _extract_tool_result(event)
    if result_payload is None:
        return []
    if isinstance(result_payload, Mapping):
        lines: list[str] = []
        for index, (key, value) in enumerate(result_payload.items(), start=1):
            key_text = normalize_for_display(str(key).strip())
            if not key_text:
                key_text = f"field{index}"
            value_text = format_value_snippet(value)
            if value_text:
                lines.append(f"{key_text}: {value_text}")
            else:
                lines.append(key_text)
            if len(lines) >= 6:
                lines.append("…")
                break
        return lines
    if isinstance(result_payload, Sequence) and not isinstance(
        result_payload, (str, bytes, bytearray)
    ):
        items: list[str] = []
        for index, item in enumerate(result_payload, start=1):
            items.append(format_value_snippet(item))
            if index >= 5:
                if len(result_payload) > index:
                    items.append("…")
                break
        return items
    snippet = format_value_snippet(result_payload)
    return [snippet] if snippet else []


def _extract_tool_error(event: ToolCallDetails) -> str | None:
    payload_mapping = _coerce_mapping(event.raw_payload)
    if not payload_mapping:
        return None
    error_payload = payload_mapping.get("error")
    message = extract_error_message(error_payload)
    if message:
        if isinstance(error_payload, Mapping):
            code_value = error_payload.get("code")
            if isinstance(code_value, str) and code_value.strip():
                code_text = normalize_for_display(code_value.strip())
                if code_text and code_text not in message:
                    message = _("[{code}] {message}").format(
                        code=code_text, message=message
                    )
        return message
    if payload_mapping.get("ok") is False:
        return _("Tool call failed")
    return None


def _summarize_tool_call_request(payload: Any) -> list[str]:
    if isinstance(payload, Mapping):
        call_payload = payload.get("tool_call")
        if isinstance(call_payload, Mapping):
            return _summarize_tool_call_request(call_payload)
        lines: list[str] = []
        name_value = payload.get("name") or payload.get("tool_name")
        if isinstance(name_value, str) and name_value.strip():
            lines.append(normalize_for_display(name_value.strip()))
        argument_payload = (
            payload.get("arguments")
            or payload.get("tool_arguments")
            or payload.get("args")
        )
        lines.extend(_summarize_request_arguments(argument_payload))
        if lines:
            return lines
    fallback = _format_raw_payload(payload)
    return _normalise_text_lines(fallback)


def _summarize_reasoning(reasoning: Any) -> list[str]:
    if not isinstance(reasoning, Sequence) or isinstance(
        reasoning, (str, bytes, bytearray)
    ):
        return []
    lines: list[str] = []
    for segment in reasoning:
        if isinstance(segment, Mapping):
            text_value = segment.get("text")
            type_value = segment.get("type")
            text_lines = _normalise_text_lines(str(text_value)) if text_value else []
            if not text_lines:
                continue
            if isinstance(type_value, str) and type_value.strip():
                heading = normalize_for_display(type_value.strip())
                for index, line in enumerate(text_lines):
                    if index == 0:
                        lines.append(f"{heading}: {line}")
                    else:
                        lines.append(line)
            else:
                lines.extend(text_lines)
        elif isinstance(segment, str):
            lines.extend(_normalise_text_lines(segment))
    return lines


def _summarize_llm_response(payload: Any) -> list[str]:
    if isinstance(payload, Mapping):
        lines: list[str] = []
        content_lines: list[str] = []
        content_value = payload.get("content")
        if isinstance(content_value, str):
            content_lines.extend(_normalise_text_lines(content_value))
        elif isinstance(content_value, Sequence) and not isinstance(
            content_value, (str, bytes, bytearray)
        ):
            for fragment in content_value:
                if isinstance(fragment, Mapping):
                    text_value = fragment.get("text")
                    content_lines.extend(_normalise_text_lines(str(text_value)))
                elif isinstance(fragment, str):
                    content_lines.extend(_normalise_text_lines(fragment))
                elif fragment is not None:
                    content_lines.append(format_value_snippet(fragment))
        elif content_value is not None:
            content_lines.append(format_value_snippet(content_value))
        lines.extend(content_lines)
        lines.extend(_summarize_reasoning(payload.get("reasoning")))
        if not lines:
            tool_calls = payload.get("tool_calls")
            if isinstance(tool_calls, Sequence) and not isinstance(
                tool_calls, (str, bytes, bytearray)
            ):
                for call in tool_calls:
                    lines.extend(_summarize_tool_call_request(call))
        if lines:
            unique: list[str] = []
            seen: set[str] = set()
            for line in lines:
                normalised = normalize_for_display(str(line)).strip()
                if not normalised or normalised in seen:
                    continue
                seen.add(normalised)
                unique.append(normalised)
            if unique:
                return unique
    fallback = _format_raw_payload(payload)
    return _normalise_text_lines(fallback)


class TranscriptEntryPanel(wx.Panel):
    """Render a single timeline entry using message and diagnostic widgets."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        timeline: TranscriptEntry,
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
            on_layout_hint=on_layout_hint,
            on_regenerate=on_regenerate,
            regenerate_enabled=regenerate_enabled,
        )

    # ------------------------------------------------------------------
    def rebuild(
        self,
        timeline: TranscriptEntry,
        *,
        layout_hints: Mapping[str, int],
        on_layout_hint: Callable[[str, int], None] | None,
        on_regenerate: Callable[[], None] | None,
        regenerate_enabled: bool,
    ) -> None:
        self._capture_collapsed_state()
        self._layout_hints = dict(layout_hints)
        self._on_layout_hint = on_layout_hint
        self._regenerate_handler = on_regenerate

        sizer = self.GetSizer()
        sizer.Clear(delete_windows=True)
        self._collapsible.clear()
        self._regenerated_notice = None
        self._user_bubble = None
        self._agent_bubble = None
        self._agent_panel = None
        self._regenerate_button = None

        agent_turn = timeline.agent_turn

        if (
            agent_turn is not None
            and agent_turn.final_response is not None
            and agent_turn.final_response.regenerated
        ):
            notice = wx.StaticText(self, label=_("Response was regenerated"))
            sizer.Add(notice, 0, wx.ALL, self._padding)
            self._regenerated_notice = notice

        if timeline.prompt is not None:
            bubble = self._create_prompt_bubble(
                timeline.prompt, context_messages=timeline.context_messages
            )
            sizer.Add(bubble, 0, wx.EXPAND | wx.ALL, self._padding)
            self._user_bubble = bubble

        agent_sections_present = bool(
            agent_turn
            and (
                agent_turn.final_response
                or agent_turn.streamed_responses
                or agent_turn.reasoning
                or (agent_turn.llm_request and agent_turn.llm_request.messages)
                or agent_turn.tool_calls
                or agent_turn.raw_payload is not None
            )
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

        for index, system_event in enumerate(timeline.system_messages):
            pane = self._create_system_section(system_event)
            if pane is not None:
                sizer.Add(pane, 0, wx.EXPAND | wx.ALL, self._padding)
                self._register_collapsible(
                    f"system:{timeline.entry_id}:{index}", pane
                )

        self._collapsed_state = {
            key: self._collapsed_state.get(key, True)
            for key in self._collapsible
        }
        self.Layout()

    # ------------------------------------------------------------------
    def update(
        self,
        timeline: TranscriptEntry,
        *,
        layout_hints: Mapping[str, int],
        on_layout_hint: Callable[[str, int], None] | None,
        on_regenerate: Callable[[], None] | None,
        regenerate_enabled: bool,
    ) -> None:
        self.rebuild(
            timeline,
            layout_hints=layout_hints,
            on_layout_hint=on_layout_hint,
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
    def _format_timestamp(self, timestamp: TimestampInfo | None) -> str:
        if timestamp is None:
            return ""
        if timestamp.formatted:
            return timestamp.formatted
        if timestamp.missing:
            return _("Timestamp unavailable")
        return ""

    # ------------------------------------------------------------------
    def _create_prompt_bubble(
        self,
        prompt: PromptMessage,
        *,
        context_messages: Sequence[Mapping[str, Any]] | None,
    ) -> MessageBubble:
        def footer_factory(bubble: wx.Window) -> wx.Sizer | None:
            if not context_messages:
                return None
            text = _format_context_messages(context_messages)
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
            timestamp=self._format_timestamp(prompt.timestamp),
            text=prompt.text,
            align="right",
            allow_selection=True,
            width_hint=self._resolve_hint("user"),
            on_width_change=lambda width: self._emit_layout_hint("user", width),
            footer_factory=footer_factory,
        )

    def _create_tool_collapsible(
        self,
        parent: wx.Window,
        entry_id: str,
        details: ToolCallDetails,
    ) -> wx.CollapsiblePane | None:
        summary = details.summary
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
        pane.SetName(f"tool:{entry_id}:{summary.index}")
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
        summary_text = self._format_tool_summary_text(details)
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
        raw_text = _format_raw_payload(details.raw_payload)
        if raw_text:
            nested_sections.append(
                (
                    f"tool:{entry_id}:{summary.index}:raw",
                    f"raw:tool:{summary.tool_name or ''}:{summary.index}",
                    _("Raw data"),
                    raw_text,
                    150,
                )
            )

        llm_payload = details.llm_request
        request_payload: Any = llm_payload
        response_payload: Any | None = None
        if isinstance(llm_payload, Mapping):
            response_payload = llm_payload.get("response")
            request_payload = llm_payload.get("tool_call") or llm_payload
        request_raw = _format_raw_payload(request_payload)
        if request_raw:
            nested_sections.append(
                (
                    f"tool:{entry_id}:{summary.index}:llm-request",
                    f"raw:tool:{summary.tool_name or ''}:{summary.index}:llm-request",
                    _("Raw LLM request"),
                    request_raw,
                    150,
                )
            )
        response_raw = _format_raw_payload(response_payload)
        if response_raw:
            nested_sections.append(
                (
                    f"tool:{entry_id}:{summary.index}:llm-response",
                    f"raw:tool:{summary.tool_name or ''}:{summary.index}:llm-response",
                    _("Raw LLM response"),
                    response_raw,
                    150,
                )
            )

        for key, name, label_text, value, minimum_height in nested_sections:
            nested = _build_collapsible_section(
                inner,
                label=label_text,
                content=value,
                minimum_height=minimum_height,
                collapsed=self._collapsed_state.get(key, True),
                name=name,
            )
            if nested is not None:
                self._register_collapsible(key, nested)
                inner_sizer.Add(nested, 0, wx.EXPAND | wx.TOP, parent.FromDIP(4))

        inner.SetSizer(inner_sizer)
        return pane

    # ------------------------------------------------------------------
    def _format_tool_summary_text(self, details: ToolCallDetails) -> str:
        summary = details.summary
        lines: list[str] = []
        lines.append(
            _("Tool: {name}").format(
                name=summary.tool_name or _("Unnamed tool")
            )
        )
        status_label = summary.status or _("returned data")
        lines.append(_("Status: {status}").format(status=status_label))

        argument_lines = _summarize_tool_arguments(details)
        if argument_lines:
            lines.append(_("Arguments:"))
            lines.extend("• " + line for line in argument_lines)

        error_text = _extract_tool_error(details)
        result_lines = [] if error_text else _summarize_tool_result(details)
        if error_text:
            lines.append(_("Error: {message}").format(message=error_text))
        elif result_lines:
            lines.append(_("Result:"))
            lines.extend("• " + line for line in result_lines)

        lines.extend(self._render_tool_exchange(details))
        if details.call_identifier:
            lines.append(
                _("Call identifier: {identifier}").format(
                    identifier=details.call_identifier
                )
            )
        return "\n".join(lines)

    def _render_tool_exchange(self, details: ToolCallDetails) -> list[str]:
        payload = details.llm_request

        lines: list[str] = []
        response_payload: Any | None = None
        step_label: str | None = None

        request_source: Any = payload
        if isinstance(payload, Mapping):
            response_payload = payload.get("response")
            step_value = payload.get("step")
            if isinstance(step_value, (int, float)):
                step_label = str(int(step_value))
            elif isinstance(step_value, str) and step_value.strip():
                step_label = step_value.strip()
        else:
            request_source = None

        request_lines = _summarize_tool_call_request(request_source)
        if not request_lines:
            argument_lines = _summarize_tool_arguments(details)
            if argument_lines:
                request_lines = argument_lines
        if request_lines:
            if step_label is not None:
                lines.append(
                    _("LLM request (step {step}):").format(
                        step=normalize_for_display(step_label)
                    )
                )
            else:
                lines.append(_("LLM request:"))
            if step_label is not None:
                lines.extend(
                    self._indent_for_summary(
                        _("Step {step}").format(
                            step=normalize_for_display(step_label)
                        )
                    )
                )
            lines.extend(
                self._indent_for_summary("\n".join(request_lines))
            )
        else:
            lines.append(_("LLM request: (not recorded)"))

        response_lines = _summarize_llm_response(response_payload)
        if response_lines:
            lines.append(_("LLM response:"))
            lines.extend(self._indent_for_summary("\n".join(response_lines)))

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
        timeline: TranscriptEntry,
        *,
        on_regenerate: Callable[[], None] | None,
        regenerate_enabled: bool,
    ) -> tuple[wx.Window | None, wx.Button | None]:
        turn = timeline.agent_turn
        tool_calls = list(turn.tool_calls) if turn is not None else []
        timestamp_info = turn.timestamp if turn is not None else None

        has_content = bool(
            turn
            and (
                turn.final_response
                or turn.streamed_responses
                or turn.reasoning
                or (turn.llm_request and turn.llm_request.messages)
                or turn.raw_payload is not None
            )
        )
        if not has_content and not tool_calls and not timeline.can_regenerate:
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
                    final_bubble = bubble

        if final_bubble is None and tool_calls:
            placeholder = self._create_tool_summary_bubble(
                container,
                timeline.entry_id,
                tool_calls,
                timestamp_info,
            )
            if placeholder is not None:
                rendered.append(placeholder)
                final_bubble = placeholder

        if final_bubble is not None:
            self._agent_bubble = final_bubble

        if tool_calls:
            if final_bubble is not None:
                self._attach_tool_call_footer(
                    timeline.entry_id, final_bubble, tool_calls
                )
            else:
                for details in tool_calls:
                    pane = self._create_tool_collapsible(
                        container, timeline.entry_id, details
                    )
                    if pane is None:
                        continue
                    key = f"tool:{timeline.entry_id}:{details.summary.index}"
                    self._register_collapsible(key, pane)
                    rendered.append(pane)

        if turn is not None:
            reasoning_section = self._create_reasoning_section(
                container, timeline.entry_id, turn.reasoning
            )
            if reasoning_section is not None:
                rendered.append(reasoning_section)

            llm_section = self._create_llm_request_section(
                container, timeline.entry_id, turn.llm_request
            )
            if llm_section is not None:
                rendered.append(llm_section)

            raw_section = self._create_raw_payload_section(
                container, timeline.entry_id, turn.raw_payload
            )
            if raw_section is not None:
                rendered.append(raw_section)

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
    def _attach_tool_call_footer(
        self,
        entry_id: str,
        bubble: MessageBubble,
        details_list: Sequence[ToolCallDetails],
    ) -> None:
        if not details_list:
            bubble.set_footer(None)
            return

        def factory(parent: wx.Window) -> wx.Sizer | None:
            sizer = wx.BoxSizer(wx.VERTICAL)
            padding = parent.FromDIP(4)
            added = False
            for details in details_list:
                pane = self._create_tool_collapsible(
                    parent, entry_id, details
                )
                if pane is None:
                    continue
                key = f"tool:{entry_id}:{details.summary.index}"
                self._register_collapsible(key, pane)
                border = padding if added else 0
                flag = wx.EXPAND | (wx.TOP if added else 0)
                sizer.Add(pane, 0, flag, border)
                added = True
            if not added:
                sizer.Clear(delete_windows=True)
                return None
            return sizer

        bubble.set_footer(factory)

    # ------------------------------------------------------------------
    def _create_reasoning_section(
        self,
        parent: wx.Window,
        entry_id: str,
        segments: Sequence[Mapping[str, Any]] | None,
    ) -> wx.CollapsiblePane | None:
        text = _format_reasoning_segments(segments)
        if not text:
            return None
        key = f"reasoning:{entry_id}"
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

    def _create_llm_request_section(
        self,
        parent: wx.Window,
        entry_id: str,
        snapshot: LlmRequestSnapshot | None,
    ) -> wx.CollapsiblePane | None:
        if snapshot is None or not snapshot.messages:
            return None
        payload: dict[str, Any] = {"messages": snapshot.messages}
        if snapshot.sequence is not None:
            payload["sequence"] = snapshot.sequence
        text = _format_raw_payload(payload)
        if not text:
            return None
        key = f"llm-request:{entry_id}"
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

    def _create_raw_payload_section(
        self,
        parent: wx.Window,
        entry_id: str,
        payload: Any,
    ) -> wx.CollapsiblePane | None:
        text = _format_raw_payload(payload)
        if not text:
            return None
        key = f"raw:{entry_id}"
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

    # ------------------------------------------------------------------
    def _create_system_section(
        self, entry: SystemMessage
    ) -> wx.CollapsiblePane | None:
        message = normalize_for_display(getattr(entry, "message", "") or "")
        details_payload = getattr(entry, "details", None)
        details = (
            _format_raw_payload(details_payload)
            if details_payload is not None
            else ""
        )
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
    def _create_tool_summary_bubble(
        self,
        parent: wx.Window,
        entry_id: str,
        tool_calls: Sequence[ToolCallDetails],
        turn_timestamp: TimestampInfo | None,
    ) -> MessageBubble | None:
        summary_lines: list[str] = []
        for details in tool_calls:
            summary = details.summary
            tool_name = summary.tool_name or _("Unnamed tool")
            status_label = summary.status or _("returned data")
            summary_lines.append(
                _("Ran {tool} — {status}").format(
                    tool=normalize_for_display(tool_name),
                    status=normalize_for_display(status_label),
                )
            )
        if not summary_lines:
            return None
        summary_lines.append(_("Details are available below."))
        text = "\n".join(summary_lines)
        timestamp_label = self._format_timestamp(turn_timestamp)
        if not timestamp_label and turn_timestamp is not None and turn_timestamp.missing:
            timestamp_label = _("Timestamp unavailable")
        bubble = MessageBubble(
            parent,
            role_label=_("Agent"),
            timestamp=timestamp_label,
            text=text,
            align="left",
            allow_selection=True,
            width_hint=self._resolve_hint("agent"),
            on_width_change=lambda width: self._emit_layout_hint("agent", width),
        )
        return bubble

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
