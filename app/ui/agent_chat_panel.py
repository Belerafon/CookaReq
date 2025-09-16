"""Panel providing conversational interface to the local agent."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import wx

from ..i18n import _
from .helpers import format_error_message


try:  # pragma: no cover - import only used for typing
    from ..agent import LocalAgent  # noqa: TCH004
except Exception:  # pragma: no cover - fallback when wx stubs are used
    LocalAgent = object  # type: ignore[assignment]


@dataclass
class ChatEntry:
    """Stored request/response pair."""

    prompt: str
    response: str
    tokens: int


def _default_history_path() -> Path:
    """Return default location for persisted chat history."""

    return Path.home() / ".cookareq" / "agent_chats.json"


def _token_count(text: str) -> int:
    """Very naive token count using whitespace separation."""

    return len(text.split())


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
        self._agent_supplier = agent_supplier
        self._history_path = history_path or _default_history_path()
        self.history: list[ChatEntry] = []
        self._is_running = False
        self._timer = wx.Timer(self)
        self._timer.Bind(wx.EVT_TIMER, self._on_timer)
        self._start_time: float | None = None
        self._current_tokens: int = 0
        self._clear_history_btn: wx.Button | None = None
        self._load_history()

        self._build_ui()
        self._render_transcript()

    # ------------------------------------------------------------------
    def focus_input(self) -> None:
        """Give keyboard focus to the input control."""

        self.input.SetFocus()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """Construct controls and layout."""

        outer = wx.BoxSizer(wx.VERTICAL)

        content = wx.BoxSizer(wx.HORIZONTAL)

        history_sizer = wx.BoxSizer(wx.VERTICAL)
        history_label = wx.StaticText(self, label=_("Chat History"))
        self.history_list = wx.ListBox(self, style=wx.LB_SINGLE)
        self.history_list.Bind(wx.EVT_LISTBOX, self._on_select_history)
        history_sizer.Add(history_label, 0, wx.ALL, 5)
        history_sizer.Add(self.history_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        transcript_sizer = wx.BoxSizer(wx.VERTICAL)
        transcript_label = wx.StaticText(self, label=_("Conversation"))
        self.transcript = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
        )
        self.transcript.SetBackgroundColour(self.GetBackgroundColour())
        self.transcript.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT))
        transcript_sizer.Add(transcript_label, 0, wx.ALL, 5)
        transcript_sizer.Add(self.transcript, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        content.Add(history_sizer, 0, wx.EXPAND)
        content.Add(transcript_sizer, 1, wx.EXPAND)

        input_label = wx.StaticText(self, label=_("Ask the agent"))
        self.input = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER | wx.TE_MULTILINE)
        if hasattr(self.input, "SetHint"):
            self.input.SetHint(_("Describe what you need the agent to do"))
        self.input.Bind(wx.EVT_TEXT_ENTER, self._on_send)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self._send_btn = wx.Button(self, label=_("Send"))
        self._send_btn.Bind(wx.EVT_BUTTON, self._on_send)
        self._clear_history_btn = wx.Button(self, label=_("Clear history"))
        self._clear_history_btn.Bind(wx.EVT_BUTTON, self._on_clear_history)
        clear_btn = wx.Button(self, label=_("Clear input"))
        clear_btn.Bind(wx.EVT_BUTTON, self._on_clear_input)
        buttons.AddStretchSpacer()
        buttons.Add(self._clear_history_btn, 0, wx.RIGHT, 5)
        buttons.Add(clear_btn, 0, wx.RIGHT, 5)
        buttons.Add(self._send_btn, 0)

        status_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.activity = wx.ActivityIndicator(self)
        self.activity.Hide()
        self.status_label = wx.StaticText(self, label=_("Ready"))
        status_sizer.Add(self.activity, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        status_sizer.Add(self.status_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        outer.Add(content, 1, wx.EXPAND)
        outer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        outer.Add(input_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        outer.Add(self.input, 0, wx.EXPAND | wx.ALL, 5)
        outer.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        outer.Add(status_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.SetSizer(outer)
        self._refresh_history_list()

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
            response = self._format_result(result)
            self._append_history(prompt, response)
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

    def _format_result(self, result: Any) -> str:
        if isinstance(result, dict):
            if not result.get("ok", False):
                return format_error_message(result.get("error"))
            payload = result.get("result")
        else:
            return str(result)

        try:
            return json.dumps(payload, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(payload)

    # ------------------------------------------------------------------
    def _conversation_messages(self) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for entry in self.history:
            if entry.prompt:
                messages.append({"role": "user", "content": entry.prompt})
            if entry.response:
                messages.append({"role": "assistant", "content": entry.response})
        return messages

    def _append_history(self, prompt: str, response: str) -> None:
        tokens = _token_count(prompt) + _token_count(response)
        entry = ChatEntry(prompt=prompt, response=response, tokens=tokens)
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
        if not self.history:
            self.transcript.SetValue(_("Start chatting with the agent to see responses here."))
            return

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
        self.transcript.SetValue("\n\n".join(blocks))
        self.transcript.ShowPosition(self.transcript.GetLastPosition())

    def _ensure_history_visible(self, index: int) -> None:
        if 0 <= index < self.history_list.GetCount():
            self.history_list.SetFirstItem(index)

    def _load_history(self) -> None:
        try:
            raw = json.loads(self._history_path.read_text(encoding="utf-8"))
            self.history = [ChatEntry(**item) for item in raw]
        except FileNotFoundError:
            self.history = []
        except Exception:
            self.history = []

    def _save_history(self) -> None:
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        with self._history_path.open("w", encoding="utf-8") as fh:
            json.dump([asdict(entry) for entry in self.history], fh, ensure_ascii=False, indent=2)

