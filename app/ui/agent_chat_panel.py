"""Panel providing conversational interface to the local agent."""

from __future__ import annotations

import datetime
import json
import logging
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from concurrent.futures import Future

import wx
import wx.dataview as dv
from wx.lib.scrolledpanel import ScrolledPanel

from ..i18n import _
from ..util.json import make_json_safe
from ..util.cancellation import CancellationTokenSource, OperationCancelledError
from .chat_entry import ChatConversation, ChatEntry
from .helpers import dip, format_error_message, inherit_background
from .splitter_utils import refresh_splitter_highlight, style_splitter
from .widgets.chat_message import TranscriptMessagePanel


logger = logging.getLogger(__name__)


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


def _history_json_safe(value: Any) -> Any:
    """Convert values for history storage using permissive coercions."""

    return make_json_safe(
        value,
        stringify_keys=True,
        sort_sets=False,
        coerce_sequences=True,
        default=str,
    )


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


class AgentCommandExecutor(Protocol):
    """Simple protocol for running agent commands asynchronously."""

    def submit(self, func: Callable[[], Any]) -> Future[Any]:  # pragma: no cover - protocol
        """Schedule ``func`` for execution and return a future with its result."""


class ThreadedAgentCommandExecutor:
    """Background executor creating a dedicated thread per submission."""

    def submit(self, func: Callable[[], Any]) -> Future[Any]:
        future: Future[Any] = Future()

        def runner() -> None:
            if not future.set_running_or_notify_cancel():
                return
            try:
                result = func()
            except BaseException as exc:  # pragma: no cover - defensive
                future.set_exception(exc)
            else:
                future.set_result(result)

        thread = threading.Thread(target=runner, daemon=True, name="AgentChatCommand")
        thread.start()
        return future


@dataclass(slots=True)
class _AgentRunHandle:
    """Track metadata for an in-flight agent invocation."""

    run_id: int
    prompt: str
    cancellation: CancellationTokenSource
    future: Future[Any] | None = None

    @property
    def is_cancelled(self) -> bool:
        return self.cancellation.cancelled

    def cancel(self) -> None:
        self.cancellation.cancel()
        future = self.future
        if future is not None:
            future.cancel()


class AgentChatPanel(wx.Panel):
    """Interactive chat panel driving the :class:`LocalAgent`."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        agent_supplier: Callable[[], LocalAgent],
        history_path: Path | None = None,
        command_executor: AgentCommandExecutor | None = None,
    ) -> None:
        """Create panel bound to ``agent_supplier``."""

        super().__init__(parent)
        inherit_background(self, parent)
        self._agent_supplier = agent_supplier
        self._history_path = history_path or _default_history_path()
        self._command_executor = command_executor or ThreadedAgentCommandExecutor()
        self.conversations: list[ChatConversation] = []
        self._active_conversation_id: str | None = None
        self._is_running = False
        self._timer = wx.Timer(self)
        self._timer.Bind(wx.EVT_TIMER, self._on_timer)
        self._start_time: float | None = None
        self._current_tokens: int = 0
        self._new_chat_btn: wx.Button | None = None
        self._clear_history_btn: wx.Button | None = None
        self._stop_btn: wx.Button | None = None
        self._bottom_panel: wx.Panel | None = None
        self.transcript = _TranscriptAccessor()
        self._suppress_history_selection = False
        self._history_last_sash = 0
        self._run_counter = 0
        self._active_run_handle: _AgentRunHandle | None = None
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
        history_min_width = dip(self, 260)
        self._horizontal_splitter.SetMinimumPaneSize(history_min_width)

        history_panel = wx.Panel(self._horizontal_splitter)
        self._history_panel = history_panel
        history_sizer = wx.BoxSizer(wx.VERTICAL)
        history_header = wx.BoxSizer(wx.HORIZONTAL)
        history_label = wx.StaticText(history_panel, label=_("Chats"))
        self._new_chat_btn = wx.Button(history_panel, label=_("New chat"))
        self._new_chat_btn.Bind(wx.EVT_BUTTON, self._on_new_chat)
        history_header.Add(history_label, 1, wx.ALIGN_CENTER_VERTICAL)
        history_header.Add(self._new_chat_btn, 0, wx.ALIGN_CENTER_VERTICAL)
        style = dv.DV_SINGLE | dv.DV_ROW_LINES | dv.DV_VERT_RULES
        self.history_list = dv.DataViewListCtrl(history_panel, style=style)
        self.history_list.SetMinSize(wx.Size(dip(self, 260), -1))
        title_col = self.history_list.AppendTextColumn(
            _("Title"),
            mode=dv.DATAVIEW_CELL_INERT,
            width=dip(self, 180),
        )
        title_col.SetMinWidth(dip(self, 140))
        activity_col = self.history_list.AppendTextColumn(
            _("Last activity"),
            mode=dv.DATAVIEW_CELL_INERT,
            width=dip(self, 140),
        )
        activity_col.SetMinWidth(dip(self, 120))
        summary_col = self.history_list.AppendTextColumn(
            _("Summary"),
            mode=dv.DATAVIEW_CELL_INERT,
            width=dip(self, 260),
        )
        summary_col.SetMinWidth(dip(self, 220))
        self.history_list.Bind(dv.EVT_DATAVIEW_SELECTION_CHANGED, self._on_select_history)
        inherit_background(history_panel, self)
        history_sizer.Add(history_header, 0, wx.EXPAND)
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

        self._horizontal_splitter.SplitVertically(
            history_panel, transcript_panel, history_min_width
        )
        self._horizontal_splitter.SetSashGravity(1.0)
        self._history_last_sash = self._horizontal_splitter.GetSashPosition()

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

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._clear_history_btn = wx.Button(bottom_panel, label=_("Delete chat"))
        self._clear_history_btn.Bind(wx.EVT_BUTTON, self._on_clear_history)
        clear_btn = wx.Button(bottom_panel, label=_("Clear input"))
        clear_btn.Bind(wx.EVT_BUTTON, self._on_clear_input)
        self._stop_btn = wx.Button(bottom_panel, label=_("Stop"))
        self._stop_btn.Bind(wx.EVT_BUTTON, self._on_stop)
        self._stop_btn.Enable(False)
        self._send_btn = wx.Button(bottom_panel, label=_("Send"))
        self._send_btn.Bind(wx.EVT_BUTTON, self._on_send)
        button_sizer.Add(self._clear_history_btn, 0, wx.RIGHT, spacing)
        button_sizer.Add(clear_btn, 0, wx.RIGHT, spacing)
        button_sizer.Add(self._stop_btn, 0, wx.RIGHT, spacing)
        button_sizer.Add(self._send_btn, 0)

        status_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.activity = wx.ActivityIndicator(bottom_panel)
        self.activity.Hide()
        self.status_label = wx.StaticText(bottom_panel, label=_("Ready"))
        status_sizer.Add(self.activity, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, spacing)
        status_sizer.Add(self.status_label, 0, wx.ALIGN_CENTER_VERTICAL)

        controls_sizer = wx.BoxSizer(wx.HORIZONTAL)
        controls_sizer.Add(status_sizer, 0, wx.ALIGN_CENTER_VERTICAL)
        controls_sizer.AddStretchSpacer()
        controls_sizer.Add(button_sizer, 0, wx.ALIGN_CENTER_VERTICAL)

        bottom_sizer.Add(input_label, 0)
        bottom_sizer.AddSpacer(spacing)
        bottom_sizer.Add(self.input, 1, wx.EXPAND)
        bottom_sizer.AddSpacer(spacing)
        bottom_sizer.Add(controls_sizer, 0, wx.EXPAND)
        bottom_sizer.AddSpacer(spacing)
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
    @property
    def history_sash(self) -> int:
        """Return the current width of the history pane."""

        splitter = getattr(self, "_horizontal_splitter", None)
        if splitter and splitter.IsSplit():
            pos = splitter.GetSashPosition()
            if pos > 0:
                self._history_last_sash = pos
        return max(self._history_last_sash, 0)

    def default_history_sash(self) -> int:
        """Return reasonable default sash width for the history pane."""

        splitter = getattr(self, "_horizontal_splitter", None)
        if splitter and splitter.IsSplit():
            pos = splitter.GetSashPosition()
            if pos > 0:
                return pos
            return splitter.GetMinimumPaneSize()
        return max(self._history_last_sash, 0)

    def apply_history_sash(self, value: int) -> None:
        """Apply a stored history sash if the splitter is available."""

        splitter = getattr(self, "_horizontal_splitter", None)
        if splitter and splitter.IsSplit():
            minimum = splitter.GetMinimumPaneSize()
            target = max(value, minimum)
            splitter.SetSashPosition(target)
            self._history_last_sash = target
        else:
            self._history_last_sash = max(value, 0)

    def _on_send(self, _event: wx.Event) -> None:
        """Send prompt to agent."""

        if self._is_running:
            return

        text = self.input.GetValue().strip()
        if not text:
            return

        prompt = text
        self.input.SetValue("")
        self._run_counter += 1
        cancellation = CancellationTokenSource()
        handle = _AgentRunHandle(
            run_id=self._run_counter,
            prompt=prompt,
            cancellation=cancellation,
        )
        self._active_run_handle = handle
        self._ensure_active_conversation()
        tokens = _token_count(prompt)
        history_messages = self._conversation_messages()
        self._set_wait_state(True, tokens)

        def worker() -> Any:
            try:
                agent = self._agent_supplier()
                return agent.run_command(
                    prompt,
                    history=history_messages,
                    cancellation=handle.cancellation.token,
                )
            except OperationCancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                return {
                    "ok": False,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }

        future = self._command_executor.submit(worker)
        handle.future = future

        def on_complete(task: Future[Any]) -> None:
            if handle.is_cancelled:
                return
            try:
                result = task.result()
            except OperationCancelledError:
                return
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Agent command failed", exc_info=exc)
                result = {
                    "ok": False,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            wx.CallAfter(self._finalize_prompt, prompt, result, handle)

        future.add_done_callback(on_complete)

    def _on_clear_input(self, _event: wx.Event) -> None:
        """Clear input field and reset selection."""

        self.input.SetValue("")
        self.input.SetFocus()

    def _on_clear_history(self, _event: wx.Event) -> None:
        """Delete the currently selected conversation."""

        if self._is_running:
            return
        active_index = self._active_index()
        conversation = self._get_active_conversation()
        if conversation is None:
            return
        try:
            self.conversations.remove(conversation)
        except ValueError:  # pragma: no cover - defensive
            pass
        if self.conversations:
            if active_index is None:
                self._active_conversation_id = self.conversations[-1].conversation_id
            else:
                next_index = min(active_index, len(self.conversations) - 1)
                self._active_conversation_id = self.conversations[next_index].conversation_id
        else:
            self._active_conversation_id = None
        self._save_history()
        self._refresh_history_list()
        self._render_transcript()
        self.input.SetValue("")
        self.input.SetFocus()

    def _on_select_history(self, event: dv.DataViewEvent) -> None:
        """Load prompt from history selection."""

        if self._suppress_history_selection:
            event.Skip()
            return

        index = self._extract_history_index(event)
        if index is not None:
            self._activate_conversation_by_index(index)
        event.Skip()

    def _on_stop(self, _event: wx.Event) -> None:
        """Cancel the in-flight agent request, if any."""

        handle = self._active_run_handle
        if handle is None:
            return
        handle.cancel()
        self._active_run_handle = None
        self._set_wait_state(False)
        self.status_label.SetLabel(_("Generation cancelled"))
        self.input.SetValue(handle.prompt)
        self.input.SetInsertionPointEnd()
        self.input.SetFocus()

    # ------------------------------------------------------------------
    def _set_wait_state(self, active: bool, tokens: int = 0) -> None:
        """Enable or disable busy indicators."""

        self._is_running = active
        self._send_btn.Enable(not active)
        self.input.Enable(not active)
        if self._stop_btn is not None:
            self._stop_btn.Enable(active)
        self._update_history_controls()
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

    def _finalize_prompt(
        self,
        prompt: str,
        result: Any,
        handle: _AgentRunHandle,
    ) -> None:
        """Render agent response and update history."""

        if handle.is_cancelled:
            return
        if self._active_run_handle is handle:
            self._active_run_handle = None
        elapsed = (
            time.monotonic() - self._start_time
            if self._start_time is not None
            else 0.0
        )
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
            raw_payload = _history_json_safe(result)
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
                safe_extras = _history_json_safe(extras)
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
        conversation = self._get_active_conversation()
        if conversation is None:
            return []
        messages: list[dict[str, str]] = []
        for entry in conversation.entries:
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
        conversation = self._ensure_active_conversation()
        tokens = _token_count(prompt) + _token_count(response)
        entry = ChatEntry(
            prompt=prompt,
            response=response,
            tokens=tokens,
            display_response=display_response,
            raw_result=raw_result,
            tool_results=tool_results,
        )
        conversation.append_entry(entry)
        self._save_history()
        self._refresh_history_list()

    def _refresh_history_list(self) -> None:
        self.history_list.Freeze()
        self._suppress_history_selection = True
        try:
            self.history_list.DeleteAllItems()
            active_index = self._active_index()
            for conversation in self.conversations:
                row = self._format_conversation_row(conversation)
                self.history_list.AppendItem(list(row))
            if active_index is not None and 0 <= active_index < self.history_list.GetItemCount():
                self.history_list.SelectRow(active_index)
                self._ensure_history_visible(active_index)
            else:
                self.history_list.UnselectAll()
        finally:
            self._suppress_history_selection = False
            self.history_list.Thaw()
        self._update_history_controls()

    def _render_transcript(self) -> None:
        last_panel: wx.Window | None = None
        self.transcript_panel.Freeze()
        try:
            self._transcript_sizer.Clear(delete_windows=True)
            conversation = self._get_active_conversation()
            if conversation is None:
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
            elif not conversation.entries:
                placeholder = wx.StaticText(
                    self.transcript_panel,
                    label=_("This chat does not have any messages yet. Send one to get started."),
                )
                self._transcript_sizer.Add(
                    placeholder,
                    0,
                    wx.ALL,
                    dip(self, 8),
                )
            else:
                for idx, entry in enumerate(conversation.entries, start=1):
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
        if not (0 <= index < self.history_list.GetItemCount()):
            return
        item = self.history_list.RowToItem(index)
        if item.IsOk():
            self.history_list.EnsureVisible(item)

    def _compose_transcript_text(self) -> str:
        conversation = self._get_active_conversation()
        if conversation is None:
            return _("Start chatting with the agent to see responses here.")
        if not conversation.entries:
            return _("This chat does not have any messages yet. Send one to get started.")

        blocks: list[str] = []
        for idx, entry in enumerate(conversation.entries, start=1):
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
        self.conversations = []
        self._active_conversation_id = None
        try:
            raw = json.loads(self._history_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except Exception:
            return

        if not isinstance(raw, Mapping):
            return

        conversations_raw = raw.get("conversations")
        if not isinstance(conversations_raw, Sequence):
            return

        conversations: list[ChatConversation] = []
        for item in conversations_raw:
            if isinstance(item, Mapping):
                try:
                    conversations.append(ChatConversation.from_dict(item))
                except Exception:  # pragma: no cover - defensive
                    continue
        if not conversations:
            return

        self.conversations = conversations
        active_id = raw.get("active_id")
        if isinstance(active_id, str) and any(
            conv.conversation_id == active_id for conv in self.conversations
        ):
            self._active_conversation_id = active_id
        else:
            self._active_conversation_id = self.conversations[-1].conversation_id

    def _save_history(self) -> None:
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 2,
            "active_id": self._active_conversation_id,
            "conversations": [conv.to_dict() for conv in self.conversations],
        }
        with self._history_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

    def _active_index(self) -> int | None:
        if self._active_conversation_id is None:
            return None
        for idx, conversation in enumerate(self.conversations):
            if conversation.conversation_id == self._active_conversation_id:
                return idx
        return None

    def _get_active_conversation(self) -> ChatConversation | None:
        index = self._active_index()
        if index is None:
            return None
        try:
            return self.conversations[index]
        except IndexError:  # pragma: no cover - defensive
            return None

    def _create_conversation(self, *, persist: bool) -> ChatConversation:
        conversation = ChatConversation.new()
        self.conversations.append(conversation)
        self._active_conversation_id = conversation.conversation_id
        self._refresh_history_list()
        self._render_transcript()
        if persist:
            self._save_history()
        return conversation

    def _ensure_active_conversation(self) -> ChatConversation:
        conversation = self._get_active_conversation()
        if conversation is not None:
            return conversation
        return self._create_conversation(persist=False)

    def _format_conversation_row(self, conversation: ChatConversation) -> tuple[str, str, str]:
        title = (conversation.title or conversation.derive_title()).strip()
        if not title:
            title = _("New chat")
        if len(title) > 60:
            title = title[:57] + "…"
        last_activity = self._format_last_activity(conversation.updated_at)
        summary = self._format_conversation_summary(conversation)
        return title, last_activity, summary

    def _format_last_activity(self, timestamp: str | None) -> str:
        if not timestamp:
            return _("No activity yet")
        try:
            moment = datetime.datetime.fromisoformat(timestamp)
        except ValueError:
            return timestamp
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=datetime.timezone.utc)
        local_moment = moment.astimezone()
        now = datetime.datetime.now(local_moment.tzinfo)
        today = now.date()
        date_value = local_moment.date()
        if date_value == today:
            return _("Today {time}").format(time=local_moment.strftime("%H:%M"))
        if date_value == today - datetime.timedelta(days=1):
            return _("Yesterday {time}").format(time=local_moment.strftime("%H:%M"))
        if date_value.year == today.year:
            return local_moment.strftime("%d %b %H:%M")
        return local_moment.strftime("%Y-%m-%d %H:%M")

    def _format_conversation_summary(self, conversation: ChatConversation) -> str:
        if not conversation.entries:
            return _("No messages yet")
        count = len(conversation.entries)
        parts = [_("Messages: {count}").format(count=count)]
        tokens = conversation.total_tokens()
        parts.append(
            _("Tokens: {tokens:.2f}k").format(
                tokens=tokens / 1000 if tokens else 0.0
            )
        )
        preview = self._conversation_preview(conversation)
        if preview:
            parts.append(preview)
        return " • ".join(parts)

    def _conversation_preview(self, conversation: ChatConversation) -> str:
        if not conversation.entries:
            return ""
        last_entry = conversation.entries[-1]
        text = last_entry.prompt.strip()
        if not text:
            candidate = last_entry.display_response or last_entry.response
            text = candidate.strip() if isinstance(candidate, str) else ""
        if not text:
            return ""
        normalized = " ".join(text.split())
        if len(normalized) > 80:
            normalized = normalized[:77] + "…"
        return normalized

    def _extract_history_index(self, event: dv.DataViewEvent | None) -> int | None:
        item = None
        if event is not None:
            item = event.GetItem()
        if item is None or not item.IsOk():
            item = self.history_list.GetSelection()
        if item is None or not item.IsOk():
            return None
        row = self.history_list.ItemToRow(item)
        if 0 <= row < len(self.conversations):
            return row
        return None

    def _activate_conversation_by_index(self, index: int, *, persist: bool = True) -> None:
        if not (0 <= index < len(self.conversations)):
            return
        conversation = self.conversations[index]
        self._active_conversation_id = conversation.conversation_id
        if persist:
            self._save_history()
        self._refresh_history_list()
        self._ensure_history_visible(index)
        self._render_transcript()
        self.input.SetFocus()

    def _update_history_controls(self) -> None:
        has_conversations = bool(self.conversations)
        self.history_list.Enable(has_conversations and not self._is_running)
        if self._clear_history_btn is not None:
            self._clear_history_btn.Enable(has_conversations and not self._is_running)
        if self._new_chat_btn is not None:
            self._new_chat_btn.Enable(not self._is_running)

    def _on_new_chat(self, _event: wx.Event) -> None:
        if self._is_running:
            return
        self._create_conversation(persist=True)
        self.input.SetValue("")
        self.input.SetFocus()

    @property
    def history(self) -> list[ChatEntry]:
        conversation = self._get_active_conversation()
        if conversation is None:
            return []
        return list(conversation.entries)

