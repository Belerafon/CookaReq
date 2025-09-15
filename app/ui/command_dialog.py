"""Dialog for executing LocalAgent commands with persistent history."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import wx

from ..agent import LocalAgent
from ..i18n import _
from .helpers import format_error_message


@dataclass
class ChatEntry:
    """Stored conversation entry."""

    command: str
    response: str
    tokens: int


def _default_history_path() -> Path:
    """Return default path for chat history."""

    return Path.home() / ".cookareq" / "agent_chats.json"


def _token_count(text: str) -> int:
    """Naive token count based on whitespace splitting."""

    return len(text.split())


class CommandDialog(wx.Dialog):
    """Interface to run agent commands and manage chat history."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        agent: LocalAgent,
        history_path: Path | None = None,
    ) -> None:
        """Initialize dialog for interacting with ``agent``."""
        super().__init__(parent, title=_("Agent Command"))
        self._agent = agent
        self._history_path = history_path or _default_history_path()
        self.history: list[ChatEntry] = []
        self._is_running = False
        self._load_history()

        self.input = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.output = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
        )
        self.history_list = wx.ListBox(self)
        self.history_list.Bind(wx.EVT_LISTBOX, self._on_select_history)

        self._run_btn = wx.Button(self, label=_("Run"))
        self._run_btn.Bind(wx.EVT_BUTTON, self._on_run)
        clear_btn = wx.Button(self, label=_("Clear"))
        clear_btn.Bind(wx.EVT_BUTTON, self._on_clear)
        self.input.Bind(wx.EVT_TEXT_ENTER, self._on_run)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_sizer.Add(self._run_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(clear_btn, 0)

        right = wx.BoxSizer(wx.VERTICAL)
        right.Add(self.input, 0, wx.ALL | wx.EXPAND, 5)
        right.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 5)
        right.Add(self.output, 1, wx.ALL | wx.EXPAND, 5)

        main = wx.BoxSizer(wx.HORIZONTAL)
        main.Add(self.history_list, 0, wx.ALL | wx.EXPAND, 5)
        main.Add(right, 1, wx.EXPAND)
        self.SetSizerAndFit(main)
        self.SetSize((600, 400))
        self._refresh_history_list()

    def _on_run(self, _event: wx.Event) -> None:
        if self._is_running:
            return

        text = self.input.GetValue().strip()
        if not text:
            return

        command = text
        self._set_wait_state(True)

        app = wx.GetApp()
        is_main_loop_running = bool(
            app and getattr(app, "IsMainLoopRunning", lambda: False)()
        )
        finished = threading.Event()
        result_holder: dict[str, Any] = {}

        def worker() -> None:
            try:
                result = self._agent.run_command(command)
            except Exception as exc:  # pragma: no cover - defensive
                result = {
                    "ok": False,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }

            if is_main_loop_running:
                wx.CallAfter(self._finalize_run, command, result)
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
            self._finalize_run(command, result)

    def _on_clear(self, _event: wx.Event) -> None:
        self.input.SetValue("")
        self.output.SetValue("")
        self.history_list.SetSelection(wx.NOT_FOUND)

    def _on_select_history(self, event: wx.CommandEvent) -> None:
        idx = event.GetInt()
        if idx < 0 or idx >= len(self.history):
            return
        entry = self.history[idx]
        self.input.SetValue(entry.command)
        self.output.SetValue(entry.response)
        self.output.ShowPosition(self.output.GetLastPosition())

    # ------------------------------------------------------------------
    def _set_wait_state(self, active: bool) -> None:
        self._is_running = active
        self._run_btn.Enable(not active)
        if active:
            self.output.SetValue("...")
            self.output.ShowPosition(self.output.GetLastPosition())
        else:
            self.input.SetFocus()

    def _finalize_run(self, command: str, result: Any) -> None:
        display = self._format_result(result)
        try:
            self.output.SetValue(display)
            self.output.ShowPosition(self.output.GetLastPosition())
            self._append_history(command, display)
        finally:
            self._set_wait_state(False)

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
    def _append_history(self, command: str, response: str) -> None:
        tokens = _token_count(command) + _token_count(response)
        entry = ChatEntry(command=command, response=response, tokens=tokens)
        self.history.append(entry)
        self._save_history()
        self._refresh_history_list()
        self.history_list.SetSelection(len(self.history) - 1)

    def _refresh_history_list(self) -> None:
        self.history_list.Clear()
        for entry in self.history:
            label = f"{entry.command[:20]} ({entry.tokens})"
            self.history_list.Append(label)

    def _load_history(self) -> None:
        try:
            data = json.loads(self._history_path.read_text(encoding="utf-8"))
            self.history = [ChatEntry(**item) for item in data]
        except FileNotFoundError:
            self.history = []
        except Exception:
            self.history = []

    def _save_history(self) -> None:
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        with self._history_path.open("w", encoding="utf-8") as fh:
            json.dump(
                [asdict(h) for h in self.history],
                fh,
                ensure_ascii=False,
                indent=2,
            )
