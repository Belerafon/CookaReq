"""Dialog for executing LocalAgent commands with persistent history."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from ..i18n import _

import wx

from ..agent import LocalAgent


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
        super().__init__(parent, title=_("Agent Command"))
        self._agent = agent
        self._history_path = history_path or _default_history_path()
        self.history: list[ChatEntry] = []
        self._load_history()

        self.input = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.output = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL
        )
        self.history_list = wx.ListBox(self)
        self.history_list.Bind(wx.EVT_LISTBOX, self._on_select_history)

        run_btn = wx.Button(self, label=_("Run"))
        run_btn.Bind(wx.EVT_BUTTON, self._on_run)
        clear_btn = wx.Button(self, label=_("Clear"))
        clear_btn.Bind(wx.EVT_BUTTON, self._on_clear)
        self.input.Bind(wx.EVT_TEXT_ENTER, self._on_run)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_sizer.Add(run_btn, 0, wx.RIGHT, 5)
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

    def _on_run(self, event: wx.Event) -> None:
        text = self.input.GetValue().strip()
        if not text:
            return
        result = self._agent.run_command(text)
        if "error" in result:
            err = result["error"]
            code = err.get("code", "")
            msg = err.get("message", "")
            display = f"{code}: {msg}".strip(": ")
        else:
            display = json.dumps(result, ensure_ascii=False, indent=2)
        self.output.SetValue(display)
        self.output.ShowPosition(self.output.GetLastPosition())
        self._append_history(text, display)

    def _on_clear(self, event: wx.Event) -> None:
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
            json.dump([asdict(h) for h in self.history], fh, ensure_ascii=False, indent=2)
