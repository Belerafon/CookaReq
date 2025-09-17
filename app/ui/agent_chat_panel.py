"""Panel providing conversational interface to the local agent."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

import wx
from wx.lib.scrolledpanel import ScrolledPanel

from ..i18n import _
from .chat_entry import ChatEntry
from .helpers import dip, format_error_message, inherit_background
from .splitter_utils import refresh_splitter_highlight, style_splitter
from .widgets.chat_message import TranscriptMessagePanel


try:  # pragma: no cover - import only used for typing
    from ..agent import LocalAgent  # noqa: TCH004
except Exception:  # pragma: no cover - fallback when wx stubs are used
    LocalAgent = object  # type: ignore[assignment]
def _default_history_path() -> Path:
    """Return default location for persisted chat history."""

    return Path.home() / ".cookareq" / "agent_chats.json"


def _token_count(text: str) -> int:
    """Very naive token count using whitespace separation."""

    return len(text.split())


def _make_json_safe(value: Any) -> Any:
    """Convert value into structure that :func:`json.dumps` can handle."""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): _make_json_safe(val) for key, val in value.items()}
    if isinstance(value, set):  # pragma: no cover - uncommon
        return [_make_json_safe(item) for item in value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_make_json_safe(item) for item in value]
    return str(value)


def _stringify_payload(payload: Any) -> str:
    """Return textual representation suitable for transcript storage."""

    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return str(payload)


class _TranscriptAccessor:
    """Compatibility wrapper exposing legacy ``GetValue`` API for tests."""

    def __init__(self, owner: "AgentChatPanel" | None = None) -> None:
        self._owner = owner

    def bind(self, owner: "AgentChatPanel") -> None:
        self._owner = owner

    def GetValue(self) -> str:  # pragma: no cover - exercised via GUI tests
        if self._owner is None:
            return ""
        return self._owner._compose_transcript_text()


class AgentChatPanel(wx.Panel):
    """Interactive chat panel driving the :class:`LocalAgent`."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        agent_supplier: Callable[[], LocalAgent],
        history_path: Path | None = None,
    ) -> None:
        """Create panel bound to ``agent_supplier``."""

        super().__init__(parent)
        inherit_background(self, parent)
        self._agent_supplier = agent_supplier
        self._history_path = history_path or _default_history_path()
        self.history: list[ChatEntry] = []
        self._is_running = False
        self._timer = wx.Timer(self)
        self._timer.Bind(wx.EVT_TIMER, self._on_timer)
        self._start_time: float | None = None
        self._current_tokens: int = 0
        self._clear_history_btn: wx.Button | None = None
        self._bottom_panel: wx.Panel | None = None
        self.transcript = _TranscriptAccessor()
        self._load_history()

        self._build_ui()
        self.transcript.bind(self)
        self._render_transcript()

    # ------------------------------------------------------------------
    def focus_input(self) -> None:
        """Give keyboard focus to the input control."""

        self.input.SetFocus()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """Construct controls and layout."""

        outer = wx.BoxSizer(wx.VERTICAL)
        spacing = dip(self, 5)

        splitter_style = wx.SP_LIVE_UPDATE | wx.SP_3D
        self._vertical_splitter = wx.SplitterWindow(self, style=splitter_style)
        style_splitter(self._vertical_splitter)
        self._vertical_splitter.SetMinimumPaneSize(dip(self, 160))

        top_panel = wx.Panel(self._vertical_splitter)
        bottom_panel = wx.Panel(self._vertical_splitter)
        self._bottom_panel = bottom_panel
        for panel in (top_panel, bottom_panel):
            inherit_background(panel, self)

        self._horizontal_splitter = wx.SplitterWindow(top_panel, style=splitter_style)
        style_splitter(self._horizontal_splitter)
        self._horizontal_splitter.SetMinimumPaneSize(dip(self, 160))

        history_panel = wx.Panel(self._horizontal_splitter)
        history_sizer = wx.BoxSizer(wx.VERTICAL)
        history_label = wx.StaticText(history_panel, label=_("Chat History"))
        self.history_list = wx.ListBox(history_panel, style=wx.LB_SINGLE)
        self.history_list.SetMinSize(wx.Size(dip(self, 220), -1))
        self.history_list.Bind(wx.EVT_LISTBOX, self._on_select_history)
        inherit_background(history_panel, self)
        history_sizer.Add(history_label, 0)
        history_sizer.AddSpacer(spacing)
        history_sizer.Add(self.history_list, 1, wx.EXPAND)
        history_panel.SetSizer(history_sizer)

        transcript_panel = wx.Panel(self._horizontal_splitter)
        transcript_sizer = wx.BoxSizer(wx.VERTICAL)
        transcript_label = wx.StaticText(transcript_panel, label=_("Conversation"))
        self.transcript_panel = ScrolledPanel(
            transcript_panel,
            style=wx.TAB_TRAVERSAL,
        )
        inherit_background(transcript_panel, self)
        inherit_background(self.transcript_panel, transcript_panel)
        self.transcript_panel.SetupScrolling(scroll_x=False, scroll_y=True)
        self._transcript_sizer = wx.BoxSizer(wx.VERTICAL)
        self.transcript_panel.SetSizer(self._transcript_sizer)
        transcript_sizer.Add(transcript_label, 0)
        transcript_sizer.AddSpacer(spacing)
        transcript_sizer.Add(self.transcript_panel, 1, wx.EXPAND)
        transcript_panel.SetSizer(transcript_sizer)

        self._horizontal_splitter.SplitVertically(history_panel, transcript_panel, dip(self, 260))
        self._horizontal_splitter.SetSashGravity(1.0)

        top_sizer = wx.BoxSizer(wx.VERTICAL)
        top_sizer.Add(self._horizontal_splitter, 1, wx.EXPAND)
        top_panel.SetSizer(top_sizer)

        bottom_sizer = wx.BoxSizer(wx.VERTICAL)
        bottom_sizer.Add(wx.StaticLine(bottom_panel), 0, wx.EXPAND)
        bottom_sizer.AddSpacer(spacing)

        input_label = wx.StaticText(bottom_panel, label=_("Ask the agent"))
        self.input = wx.TextCtrl(bottom_panel, style=wx.TE_PROCESS_ENTER | wx.TE_MULTILINE)
        if hasattr(self.input, "SetHint"):
            self.input.SetHint(_("Describe what you need the agent to do"))
        self.input.Bind(wx.EVT_TEXT_ENTER, self._on_send)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self._send_btn = wx.Button(bottom_panel, label=_("Send"))
        self._send_btn.Bind(wx.EVT_BUTTON, self._on_send)
        self._clear_history_btn = wx.Button(bottom_panel, label=_("Clear history"))
        self._clear_history_btn.Bind(wx.EVT_BUTTON, self._on_clear_history)
        clear_btn = wx.Button(bottom_panel, label=_("Clear input"))
        clear_btn.Bind(wx.EVT_BUTTON, self._on_clear_input)
        buttons.AddStretchSpacer()
        buttons.Add(self._clear_history_btn, 0, wx.RIGHT, spacing)
        buttons.Add(clear_btn, 0, wx.RIGHT, spacing)
        buttons.Add(self._send_btn, 0)

        status_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.activity = wx.ActivityIndicator(bottom_panel)
        self.activity.Hide()
        self.status_label = wx.StaticText(bottom_panel, label=_("Ready"))
        status_sizer.Add(self.activity, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, spacing)
        status_sizer.Add(self.status_label, 0, wx.ALIGN_CENTER_VERTICAL)

        bottom_sizer.Add(input_label, 0)
        bottom_sizer.AddSpacer(spacing)
        bottom_sizer.Add(self.input, 1, wx.EXPAND)
        bottom_sizer.AddSpacer(spacing)
        bottom_sizer.Add(buttons, 0, wx.EXPAND)
        bottom_sizer.AddSpacer(spacing)
        bottom_sizer.Add(status_sizer, 0, wx.EXPAND)
        bottom_panel.SetSizer(bottom_sizer)

        self._vertical_splitter.SplitHorizontally(top_panel, bottom_panel)
        self._vertical_splitter.SetSashGravity(1.0)

        outer.Add(self._vertical_splitter, 1, wx.EXPAND)

        self.SetSizer(outer)
        refresh_splitter_highlight(self._horizontal_splitter)
        refresh_splitter_highlight(self._vertical_splitter)
        self._refresh_history_list()
        wx.CallAfter(self._adjust_vertical_splitter)

    # ------------------------------------------------------------------
    def _on_send(self, _event: wx.Event) -> None:
        """Send prompt to agent."""

        if self._is_running:
            return

        text = self.input.GetValue().strip()
        if not text:
            return

        prompt = text
        tokens = _token_count(prompt)
        history_messages = self._conversation_messages()
        self._set_wait_state(True, tokens)

        app = wx.GetApp()
        is_main_loop_running = bool(
            app and getattr(app, "IsMainLoopRunning", lambda: False)()
        )
        finished = threading.Event()
        result_holder: dict[str, Any] = {}

        def worker() -> None:
            try:
                agent = self._agent_supplier()
                result = agent.run_command(prompt, history=history_messages)
            except Exception as exc:  # pragma: no cover - defensive
                result = {
                    "ok": False,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }

            if is_main_loop_running:
                wx.CallAfter(self._finalize_prompt, prompt, result)
            else:
                result_holder["value"] = result
                finished.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        if not is_main_loop_running:
            finished.wait()
            result = result_holder.get(
                "value",
                {"ok": False, "error": _("Unknown error")},
            )
            self._finalize_prompt(prompt, result)

    def _on_clear_input(self, _event: wx.Event) -> None:
        """Clear input field and reset selection."""

        self.input.SetValue("")
        self.history_list.SetSelection(wx.NOT_FOUND)
        self.input.SetFocus()

    def _on_clear_history(self, _event: wx.Event) -> None:
        """Remove all stored conversation entries."""

        if self._is_running or not self.history:
            return
        self.history.clear()
        self._save_history()
        self._refresh_history_list()
        self.history_list.SetSelection(wx.NOT_FOUND)
        self._render_transcript()
        self.input.SetFocus()

    def _on_select_history(self, event: wx.CommandEvent) -> None:
        """Load prompt from history selection."""

        idx = event.GetInt()
        if 0 <= idx < len(self.history):
            entry = self.history[idx]
            self.input.SetValue(entry.prompt)
            self.input.SetInsertionPointEnd()
            self._ensure_history_visible(idx)

    # ------------------------------------------------------------------
    def _set_wait_state(self, active: bool, tokens: int = 0) -> None:
        """Enable or disable busy indicators."""

        self._is_running = active
        self._send_btn.Enable(not active)
        self.input.Enable(not active)
        self.history_list.Enable(not active)
        if self._clear_history_btn is not None:
            self._clear_history_btn.Enable(not active)
        if active:
            self._current_tokens = tokens
            self._start_time = time.monotonic()
            self.activity.Show()
            self.activity.Start()
            self._update_status(0.0)
            self._timer.Start(100)
        else:
            self._timer.Stop()
            self.activity.Stop()
            self.activity.Hide()
            self.status_label.SetLabel(_("Ready"))
            self._start_time = None
            self.input.SetFocus()

    def _adjust_vertical_splitter(self) -> None:
        """Size the vertical splitter so the bottom pane hugs the controls."""

        if self._bottom_panel is None:
            return
        total_height = self._vertical_splitter.GetClientSize().GetHeight()
        if total_height <= 0:
            return
        bottom_height = self._bottom_panel.GetBestSize().GetHeight()
        min_top = self._vertical_splitter.GetMinimumPaneSize()
        sash_position = max(min_top, total_height - bottom_height)
        self._vertical_splitter.SetSashPosition(sash_position, True)

    def _on_timer(self, _event: wx.TimerEvent) -> None:
        """Refresh elapsed time display while waiting for response."""

        if not self._is_running or self._start_time is None:
            return
        elapsed = time.monotonic() - self._start_time
        self._update_status(elapsed)

    def _update_status(self, elapsed: float) -> None:
        """Show formatted timer and prompt size."""

        minutes, seconds = divmod(int(elapsed), 60)
        label = _("Waiting for agent… {time} • {tokens:.2f} ktok").format(
            time=f"{minutes:02d}:{seconds:02d}",
            tokens=self._current_tokens / 1000 if self._current_tokens else 0.0,
        )
        self.status_label.SetLabel(label)

    def _finalize_prompt(self, prompt: str, result: Any) -> None:
        """Render agent response and update history."""

        try:
            conversation_text, display_text, raw_result, tool_results = self._process_result(result)
            self._append_history(
                prompt,
                conversation_text,
                display_text,
                raw_result,
                tool_results,
            )
            self._render_transcript()
        finally:
            elapsed = (
                time.monotonic() - self._start_time
                if self._start_time is not None
                else 0.0
            )
            self._set_wait_state(False)
            if elapsed:
                minutes, seconds = divmod(int(elapsed), 60)
                label = _("Received response in {time} • {tokens:.2f} ktok").format(
                    time=f"{minutes:02d}:{seconds:02d}",
                    tokens=self._current_tokens / 1000 if self._current_tokens else 0.0,
                )
                self.status_label.SetLabel(label)

    def _process_result(
        self, result: Any
    ) -> tuple[str, str, Any | None, list[Any] | None]:
        """Normalise agent result for storage and display."""

        display_text = ""
        conversation_parts: list[str] = []
        raw_payload: Any | None = None
        tool_results: list[Any] | None = None

        if isinstance(result, Mapping):
            raw_payload = _make_json_safe(result)
            if not result.get("ok", False):
                display_text = format_error_message(result.get("error"))
                conversation_parts.append(display_text)
            else:
                payload = result.get("result")
                display_text = _stringify_payload(payload)
                if display_text:
                    conversation_parts.append(display_text)

            extras = result.get("tool_results")
            if extras:
                safe_extras = _make_json_safe(extras)
                if isinstance(safe_extras, list):
                    tool_results = safe_extras
                else:
                    tool_results = [safe_extras]
                extras_text = _stringify_payload(safe_extras)
                if extras_text:
                    conversation_parts.append(extras_text)
        else:
            display_text = str(result)
            conversation_parts.append(display_text)

        conversation_text = "\n\n".join(part for part in conversation_parts if part)
        if not display_text:
            display_text = conversation_text

        return conversation_text, display_text, raw_payload, tool_results

    # ------------------------------------------------------------------
    def _conversation_messages(self) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for entry in self.history:
            if entry.prompt:
                messages.append({"role": "user", "content": entry.prompt})
            if entry.response:
                messages.append({"role": "assistant", "content": entry.response})
        return messages

    def _append_history(
        self,
        prompt: str,
        response: str,
        display_response: str,
        raw_result: Any | None,
        tool_results: list[Any] | None,
    ) -> None:
        tokens = _token_count(prompt) + _token_count(response)
        entry = ChatEntry(
            prompt=prompt,
            response=response,
            tokens=tokens,
            display_response=display_response,
            raw_result=raw_result,
            tool_results=tool_results,
        )
        self.history.append(entry)
        self._save_history()
        self._refresh_history_list()
        self.history_list.SetSelection(len(self.history) - 1)
        self._ensure_history_visible(len(self.history) - 1)

    def _refresh_history_list(self) -> None:
        self.history_list.Freeze()
        try:
            self.history_list.Clear()
            for entry in self.history:
                label = f"{entry.prompt[:30]} · {entry.tokens / 1000:.2f} ktok"
                self.history_list.Append(label)
        finally:
            self.history_list.Thaw()

    def _render_transcript(self) -> None:
        last_panel: wx.Window | None = None
        self.transcript_panel.Freeze()
        try:
            self._transcript_sizer.Clear(delete_windows=True)
            if not self.history:
                placeholder = wx.StaticText(
                    self.transcript_panel,
                    label=_("Start chatting with the agent to see responses here."),
                )
                self._transcript_sizer.Add(
                    placeholder,
                    0,
                    wx.ALL,
                    dip(self, 8),
                )
            else:
                for idx, entry in enumerate(self.history, start=1):
                    panel = TranscriptMessagePanel(
                        self.transcript_panel,
                        index=idx,
                        prompt=entry.prompt,
                        response=entry.display_response or entry.response,
                        tool_results=entry.tool_results,
                    )
                    panel.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self._on_transcript_pane_toggled)
                    self._transcript_sizer.Add(panel, 0, wx.EXPAND)
                    last_panel = panel
        finally:
            self.transcript_panel.Layout()
            self.transcript_panel.FitInside()
            self.transcript_panel.SetupScrolling(scroll_x=False, scroll_y=True)
            self.transcript_panel.Thaw()
            if last_panel is not None:
                self.transcript_panel.ScrollChildIntoView(last_panel)

    def _ensure_history_visible(self, index: int) -> None:
        if 0 <= index < self.history_list.GetCount():
            self.history_list.SetFirstItem(index)

    def _compose_transcript_text(self) -> str:
        if not self.history:
            return _("Start chatting with the agent to see responses here.")

        blocks: list[str] = []
        for idx, entry in enumerate(self.history, start=1):
            block = (
                f"{idx}. "
                + _("You:")
                + f"\n{entry.prompt}\n\n"
                + _("Agent:")
                + f"\n{entry.response}"
            )
            blocks.append(block)
        return "\n\n".join(blocks)

    def _on_transcript_pane_toggled(self, event: wx.CollapsiblePaneEvent) -> None:
        """Recalculate layout when tool details are expanded or collapsed."""

        event.Skip()
        window = event.GetEventObject()
        self.transcript_panel.Layout()
        self.transcript_panel.FitInside()
        self.transcript_panel.SetupScrolling(scroll_x=False, scroll_y=True)
        if isinstance(window, wx.Window):
            self.transcript_panel.ScrollChildIntoView(window)

    def _load_history(self) -> None:
        try:
            raw = json.loads(self._history_path.read_text(encoding="utf-8"))
            entries: list[ChatEntry] = []
            for item in raw:
                if isinstance(item, Mapping):
                    try:
                        entries.append(ChatEntry.from_dict(item))
                    except Exception:  # pragma: no cover - defensive
                        continue
            self.history = entries
        except FileNotFoundError:
            self.history = []
        except Exception:
            self.history = []

    def _save_history(self) -> None:
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        with self._history_path.open("w", encoding="utf-8") as fh:
            json.dump(
                [entry.to_dict() for entry in self.history],
                fh,
                ensure_ascii=False,
                indent=2,
            )

