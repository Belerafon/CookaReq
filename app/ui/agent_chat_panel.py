"""Panel providing conversational interface to the local agent."""

from __future__ import annotations

import datetime
import json
import logging
import textwrap
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from concurrent.futures import Future, ThreadPoolExecutor

import wx
import wx.dataview as dv
from wx.lib.scrolledpanel import ScrolledPanel

from ..confirm import confirm
from ..i18n import _
from ..llm.spec import SYSTEM_PROMPT, TOOLS
from ..llm.tokenizer import TokenCountResult, combine_token_counts, count_text_tokens
from ..util.json import make_json_safe
from ..util.cancellation import CancellationEvent, OperationCancelledError
from ..util.time import utc_now_iso
from .chat_entry import ChatConversation, ChatEntry
from .helpers import dip, format_error_message, inherit_background
from .text import normalize_for_display
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


def _normalize_history_path(path: Path | str) -> Path:
    """Expand user references and coerce *path* into :class:`Path`."""

    return Path(path).expanduser()


def history_path_for_documents(base_directory: Path | str | None) -> Path:
    """Return history file path colocated with a requirements directory."""

    if base_directory is None:
        return _default_history_path()
    base_path = _normalize_history_path(base_directory)
    return base_path / ".cookareq" / "agent_chats.json"
TOKEN_UNAVAILABLE_LABEL = "n/a"


STATUS_HELP_TEXT = _(
    "The waiting status shows four elements:\n"
    "• The timer reports how long the agent has been running in mm:ss and updates every second.\n"
    "• The centered bullet (•) separates the timer from the token counter.\n"
    "• The token counter reports the prompt size in thousands of tokens (k tokens); a leading ~"
    " marks an approximate value when the tokenizer cannot provide an exact figure.\n"
    "• The spinning indicator on the left stays active while the agent is still working."
)


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
class AgentCommandExecutor(Protocol):
    """Simple protocol for running agent commands asynchronously."""

    def submit(self, func: Callable[[], Any]) -> Future[Any]:  # pragma: no cover - protocol
        """Schedule ``func`` for execution and return a future with its result."""


class ThreadedAgentCommandExecutor:
    """Agent executor backed by a shared :class:`ThreadPoolExecutor`."""

    def __init__(self, pool: ThreadPoolExecutor | None = None) -> None:
        if pool is None:
            pool = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="AgentChatCommand",
            )
        self._pool = pool

    @property
    def pool(self) -> ThreadPoolExecutor:
        """Expose the underlying thread pool."""

        return self._pool

    def submit(self, func: Callable[[], Any]) -> Future[Any]:
        return self._pool.submit(func)


@dataclass(slots=True)
class _AgentRunHandle:
    """Track metadata for an in-flight agent invocation."""

    run_id: int
    prompt: str
    prompt_tokens: TokenCountResult
    cancel_event: CancellationEvent
    prompt_at: str
    future: Future[Any] | None = None
    conversation_id: str | None = None
    pending_entry: ChatEntry | None = None
    context_messages: tuple[dict[str, Any], ...] | None = None

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self) -> None:
        self.cancel_event.set()
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
        history_path: Path | str | None = None,
        command_executor: AgentCommandExecutor | None = None,
        token_model_resolver: Callable[[], str | None] | None = None,
        context_provider: Callable[
            [], Mapping[str, Any] | Sequence[Mapping[str, Any]] | None
        ] | None = None,
    ) -> None:
        """Create panel bound to ``agent_supplier``."""

        super().__init__(parent)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        inherit_background(self, parent)
        self._agent_supplier = agent_supplier
        if history_path is None:
            self._history_path = _default_history_path()
        else:
            self._history_path = _normalize_history_path(history_path)
        self._token_model_resolver = (
            token_model_resolver if token_model_resolver is not None else lambda: None
        )
        self._executor_pool: ThreadPoolExecutor | None = None
        if command_executor is None:
            pool = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="AgentChatCommand",
            )
            self._executor_pool = pool
            self._command_executor = ThreadedAgentCommandExecutor(pool)
        else:
            self._command_executor = command_executor
            pool = getattr(command_executor, "pool", None)
            if pool is not None:
                self._executor_pool = pool
        self.conversations: list[ChatConversation] = []
        self._active_conversation_id: str | None = None
        self._is_running = False
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_timer, self._timer)
        self._start_time: float | None = None
        self._current_tokens: TokenCountResult = TokenCountResult.exact(0)
        self._new_chat_btn: wx.Button | None = None
        self._stop_btn: wx.Button | None = None
        self._bottom_panel: wx.Panel | None = None
        self._copy_conversation_btn: wx.Window | None = None
        self._suppress_history_selection = False
        self._history_last_sash = 0
        self._history_sash_goal: int | None = None
        self._history_sash_dirty = False
        self._history_sash_internal_adjust = 0
        self._run_counter = 0
        self._active_run_handle: _AgentRunHandle | None = None
        self._context_provider = context_provider
        self._load_history()

        self._build_ui()
        self._render_transcript()

    # ------------------------------------------------------------------
    def Destroy(self) -> bool:  # pragma: no cover - exercised via GUI tests
        self._cleanup_executor()
        return super().Destroy()

    # ------------------------------------------------------------------
    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            self._cleanup_executor()
        event.Skip()

    # ------------------------------------------------------------------
    def _cleanup_executor(self) -> None:
        handle = getattr(self, "_active_run_handle", None)
        if handle is not None:
            handle.cancel()
            self._active_run_handle = None
        pool = self._executor_pool
        if pool is None:
            return
        self._executor_pool = None
        shutdown = getattr(pool, "shutdown", None)
        if callable(shutdown):
            try:
                shutdown(wait=False, cancel_futures=True)
            except TypeError:
                shutdown(wait=False)

    # ------------------------------------------------------------------
    def set_history_path(self, path: Path | str | None) -> None:
        """Switch to *path* reloading conversations from disk."""

        new_path = _default_history_path() if path is None else _normalize_history_path(path)
        if new_path == self._history_path:
            return
        if getattr(self, "conversations", []):
            self._save_history()
        self._history_path = new_path
        self._load_history()
        self._refresh_history_list()
        self._render_transcript()

    def set_history_directory(self, directory: Path | str | None) -> None:
        """Persist chat history inside *directory* when provided."""

        self.set_history_path(history_path_for_documents(directory))

    @property
    def history_path(self) -> Path:
        """Return the path of the current chat history file."""

        return self._history_path

    # ------------------------------------------------------------------
    def _token_model(self) -> str | None:
        """Return configured model name for token accounting."""

        resolver = getattr(self, "_token_model_resolver", None)
        if resolver is None:
            return None
        try:
            model = resolver()
        except Exception:  # pragma: no cover - defensive
            return None
        if not isinstance(model, str):
            return None
        text = model.strip()
        return text or None

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
        style = dv.DV_MULTIPLE | dv.DV_ROW_LINES | dv.DV_VERT_RULES
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
        self.history_list.Bind(
            dv.EVT_DATAVIEW_SELECTION_CHANGED, self._on_select_history
        )
        self.history_list.Bind(
            dv.EVT_DATAVIEW_ITEM_CONTEXT_MENU, self._on_history_item_context_menu
        )
        self.history_list.Bind(wx.EVT_CONTEXT_MENU, self._on_history_context_menu)
        inherit_background(history_panel, self)
        history_sizer.Add(history_header, 0, wx.EXPAND)
        history_sizer.AddSpacer(spacing)
        history_sizer.Add(self.history_list, 1, wx.EXPAND)
        history_panel.SetSizer(history_sizer)

        transcript_panel = wx.Panel(self._horizontal_splitter)
        transcript_sizer = wx.BoxSizer(wx.VERTICAL)
        transcript_header = wx.BoxSizer(wx.HORIZONTAL)
        transcript_label = wx.StaticText(transcript_panel, label=_("Conversation"))
        transcript_header.Add(transcript_label, 0, wx.ALIGN_CENTER_VERTICAL)
        transcript_header.AddStretchSpacer()
        self._copy_conversation_btn = self._create_copy_button(
            transcript_panel,
            tooltip=_("Copy conversation"),
            fallback_label=_("Copy conversation"),
            handler=self._on_copy_conversation,
        )
        self._copy_conversation_btn.Enable(False)
        transcript_header.Add(self._copy_conversation_btn, 0, wx.ALIGN_CENTER_VERTICAL)
        transcript_header.AddSpacer(dip(self, 4))
        self._copy_transcript_log_btn = self._create_copy_button(
            transcript_panel,
            tooltip=_("Copy technical log"),
            fallback_label=_("Copy technical log"),
            handler=self._on_copy_transcript_log,
        )
        self._copy_transcript_log_btn.Enable(False)
        transcript_header.Add(
            self._copy_transcript_log_btn, 0, wx.ALIGN_CENTER_VERTICAL
        )
        self.transcript_panel = ScrolledPanel(
            transcript_panel,
            style=wx.TAB_TRAVERSAL,
        )
        inherit_background(transcript_panel, self)
        inherit_background(self.transcript_panel, transcript_panel)
        self.transcript_panel.SetupScrolling(scroll_x=False, scroll_y=True)
        self._transcript_sizer = wx.BoxSizer(wx.VERTICAL)
        self.transcript_panel.SetSizer(self._transcript_sizer)
        transcript_sizer.Add(transcript_header, 0, wx.EXPAND)
        transcript_sizer.AddSpacer(spacing)
        transcript_sizer.Add(self.transcript_panel, 1, wx.EXPAND)
        transcript_panel.SetSizer(transcript_sizer)

        self._horizontal_splitter.SplitVertically(
            history_panel, transcript_panel, history_min_width
        )
        self._horizontal_splitter.SetSashGravity(1.0)
        self._horizontal_splitter.Bind(wx.EVT_SIZE, self._on_history_splitter_size)
        self._horizontal_splitter.Bind(
            wx.EVT_SPLITTER_SASH_POS_CHANGED, self._on_history_sash_changed
        )
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
        clear_btn = wx.Button(bottom_panel, label=_("Clear input"))
        clear_btn.Bind(wx.EVT_BUTTON, self._on_clear_input)
        self._stop_btn = wx.Button(bottom_panel, label=_("Stop"))
        self._stop_btn.Bind(wx.EVT_BUTTON, self._on_stop)
        self._stop_btn.Enable(False)
        self._send_btn = wx.Button(bottom_panel, label=_("Send"))
        self._send_btn.Bind(wx.EVT_BUTTON, self._on_send)
        button_sizer.Add(clear_btn, 0, wx.RIGHT, spacing)
        button_sizer.Add(self._stop_btn, 0, wx.RIGHT, spacing)
        button_sizer.Add(self._send_btn, 0)

        status_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.activity = wx.ActivityIndicator(bottom_panel)
        self.activity.Hide()
        self.status_label = wx.StaticText(bottom_panel, label=_("Ready"))
        status_sizer.Add(self.activity, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, spacing)
        status_sizer.Add(self.status_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.activity.SetToolTip(STATUS_HELP_TEXT)
        self.status_label.SetToolTip(STATUS_HELP_TEXT)

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
    def _create_copy_button(
        self,
        parent: wx.Window,
        *,
        tooltip: str,
        fallback_label: str,
        handler: Callable[[wx.CommandEvent], None],
    ) -> wx.Window:
        """Create a bitmap copy button with textual fallback."""

        size = wx.Size(dip(self, 16), dip(self, 16))
        bitmap = wx.ArtProvider.GetBitmap(wx.ART_COPY, wx.ART_BUTTON, size)
        if bitmap.IsOk():
            button = wx.BitmapButton(
                parent,
                bitmap=bitmap,
                style=wx.BU_EXACTFIT | wx.BORDER_NONE,
            )
        else:
            button = wx.Button(parent, label=fallback_label, style=wx.BU_EXACTFIT)
        inherit_background(button, parent)
        button.SetToolTip(tooltip)
        button.Bind(wx.EVT_BUTTON, handler)
        return button

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

        target = max(int(value), 0)
        self._history_sash_goal = target
        self._history_last_sash = max(target, 0)
        self._history_sash_dirty = True
        self._apply_history_sash_if_ready()

    def _on_history_splitter_size(self, event: wx.SizeEvent) -> None:
        """Attempt pending sash application when the splitter is resized."""

        event.Skip()
        target = self._history_sash_goal
        if target is None:
            return
        splitter = getattr(self, "_horizontal_splitter", None)
        if splitter is None or not splitter.IsSplit():
            return
        current = splitter.GetSashPosition()
        if not self._history_sash_dirty and abs(current - target) <= 1:
            return
        self._history_sash_dirty = True
        self._apply_history_sash_if_ready()

    def _on_history_sash_changed(self, event: wx.SplitterEvent) -> None:
        """Store user-driven sash updates as the new desired position."""

        splitter = getattr(self, "_horizontal_splitter", None)
        if splitter is None or event.GetEventObject() is not splitter:
            event.Skip()
            return
        if getattr(self, "_history_sash_internal_adjust", 0) > 0:
            event.Skip()
            return
        pos = splitter.GetSashPosition()
        self._history_last_sash = max(pos, 0)
        self._history_sash_goal = pos
        self._history_sash_dirty = False
        event.Skip()

    def _apply_history_sash_if_ready(self) -> None:
        """Try applying the stored history sash when splitter metrics are ready."""

        target = self._history_sash_goal
        if target is None:
            self._history_sash_dirty = False
            return
        splitter = getattr(self, "_horizontal_splitter", None)
        if splitter is None or not splitter.IsSplit():
            return
        size = splitter.GetClientSize()
        if size.width <= 0:
            return
        minimum = splitter.GetMinimumPaneSize()
        desired = max(target, minimum)
        if not self._attempt_set_history_sash(desired):
            self._history_sash_dirty = True
            return
        self._history_sash_dirty = False
        wx.CallAfter(self._verify_history_sash_after_apply)

    def _attempt_set_history_sash(self, target: int) -> bool:
        """Apply ``target`` if splitter dimensions are ready, return success flag."""

        splitter = getattr(self, "_horizontal_splitter", None)
        if splitter is None or not splitter.IsSplit():
            return False
        self._history_sash_internal_adjust += 1
        splitter.SetSashPosition(target)
        actual = splitter.GetSashPosition()
        wx.CallAfter(self._release_history_sash_adjust)
        self._history_last_sash = max(actual, 0)
        return abs(actual - target) <= 1

    def _release_history_sash_adjust(self) -> None:
        """Lower the internal adjustment guard after splitter callbacks run."""

        count = getattr(self, "_history_sash_internal_adjust", 0)
        if count > 0:
            self._history_sash_internal_adjust = count - 1

    def _verify_history_sash_after_apply(self) -> None:
        """Reapply the desired history sash if subsequent layout changed it."""

        target = self._history_sash_goal
        if target is None:
            return
        splitter = getattr(self, "_horizontal_splitter", None)
        if splitter is None or not splitter.IsSplit():
            return
        current = splitter.GetSashPosition()
        self._history_last_sash = max(current, 0)
        expected = max(target, splitter.GetMinimumPaneSize())
        if abs(current - expected) <= 1:
            return
        self._history_sash_dirty = True
        self._apply_history_sash_if_ready()

    def _on_send(self, _event: wx.Event) -> None:
        """Send prompt to agent."""

        if self._is_running:
            return

        text = self.input.GetValue().strip()
        if not text:
            return

        self.input.SetValue("")
        self._submit_prompt(text)

    def _submit_prompt(self, prompt: str, *, prompt_at: str | None = None) -> None:
        """Submit ``prompt`` to the agent pipeline."""

        if self._is_running:
            return

        normalized_prompt = prompt.strip()
        if not normalized_prompt:
            return

        effective_prompt_at = prompt_at or utc_now_iso()
        self._run_counter += 1
        cancel_event = CancellationEvent()
        prompt_tokens = count_text_tokens(normalized_prompt, model=self._token_model())
        handle = _AgentRunHandle(
            run_id=self._run_counter,
            prompt=normalized_prompt,
            prompt_tokens=prompt_tokens,
            cancel_event=cancel_event,
            prompt_at=effective_prompt_at,
        )
        self._active_run_handle = handle
        conversation = self._ensure_active_conversation()
        history_messages = self._conversation_messages()
        context_messages: tuple[dict[str, Any], ...] | None = None
        if self._context_provider is not None:
            try:
                provided_context = self._context_provider()
            except Exception:  # pragma: no cover - defensive logging
                logger.exception("Failed to collect agent context")
                provided_context = None
            context_messages = self._prepare_context_messages(provided_context)
            if not context_messages:
                context_messages = None
        handle.context_messages = context_messages
        pending_entry = self._add_pending_entry(
            conversation,
            normalized_prompt,
            prompt_at=effective_prompt_at,
            context_messages=context_messages,
        )
        handle.conversation_id = conversation.conversation_id
        handle.pending_entry = pending_entry
        self._save_history()
        self._refresh_history_list()
        self._render_transcript()
        self._set_wait_state(True, prompt_tokens)

        def worker() -> Any:
            try:
                agent = self._agent_supplier()
                return agent.run_command(
                    normalized_prompt,
                    history=history_messages,
                    context=context_messages,
                    cancellation=handle.cancel_event,
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
            wx.CallAfter(self._finalize_prompt, normalized_prompt, result, handle)

        future.add_done_callback(on_complete)

    def _on_clear_input(self, _event: wx.Event) -> None:
        """Clear input field and reset selection."""

        self.input.SetValue("")
        self.input.SetFocus()

    def _on_clear_history(self, _event: wx.Event | None = None) -> None:
        """Delete selected conversations from history."""

        self._delete_selected_conversations(require_confirmation=True)

    def _delete_selected_conversations(self, *, require_confirmation: bool) -> None:
        if self._is_running:
            return
        rows = self._selected_history_rows()
        if not rows:
            return
        conversations = [self.conversations[row] for row in rows]
        if require_confirmation:
            message = self._format_delete_confirmation_message(conversations)
            if not confirm(message):
                return
        self._remove_conversations(conversations)

    def _selected_history_rows(self) -> list[int]:
        selections = self.history_list.GetSelections()
        rows: list[int] = []
        for item in selections:
            if not item.IsOk():
                continue
            row = self.history_list.ItemToRow(item)
            if row != wx.NOT_FOUND:
                rows.append(row)
        if not rows:
            item = self.history_list.GetSelection()
            if item and item.IsOk():
                row = self.history_list.ItemToRow(item)
                if row != wx.NOT_FOUND:
                    rows.append(row)
        rows.sort()
        return rows

    def _format_delete_confirmation_message(
        self, conversations: Sequence[ChatConversation]
    ) -> str:
        if len(conversations) == 1:
            conversation = conversations[0]
            title = (conversation.title or conversation.derive_title()).strip()
            if not title:
                title = _("this chat")
            return _("Delete chat \"{title}\"?").format(
                title=normalize_for_display(title)
            )
        return _("Delete {count} selected chats?").format(count=len(conversations))

    def _remove_conversations(
        self, conversations: Sequence[ChatConversation]
    ) -> None:
        if not conversations:
            return
        ids_to_remove = {conv.conversation_id for conv in conversations}
        indices_to_remove = [
            idx
            for idx, conv in enumerate(self.conversations)
            if conv.conversation_id in ids_to_remove
        ]
        if not indices_to_remove:
            return
        removed_active = (
            self._active_conversation_id is not None
            and self._active_conversation_id in ids_to_remove
        )
        remaining = [
            conv for conv in self.conversations if conv.conversation_id not in ids_to_remove
        ]
        self.conversations = remaining
        if self.conversations:
            if self._active_conversation_id not in {
                conv.conversation_id for conv in self.conversations
            }:
                fallback_index = min(indices_to_remove[0], len(self.conversations) - 1)
                self._active_conversation_id = self.conversations[
                    fallback_index
                ].conversation_id
        else:
            self._active_conversation_id = None
        self._save_history()
        self._refresh_history_list()
        self._render_transcript()
        if removed_active:
            self.input.SetValue("")
        self.input.SetFocus()

    def _on_history_item_context_menu(self, event: dv.DataViewEvent) -> None:
        if event.GetEventObject() is not self.history_list:
            event.Skip()
            return
        item = event.GetItem()
        row = None
        if item and item.IsOk():
            row = self.history_list.ItemToRow(item)
        self._show_history_context_menu(row)

    def _on_history_context_menu(self, event: wx.ContextMenuEvent) -> None:
        if event.GetEventObject() is not self.history_list:
            event.Skip()
            return
        pos = event.GetPosition()
        row = None
        if pos != wx.DefaultPosition:
            client = self.history_list.ScreenToClient(pos)
            item, _column = self.history_list.HitTest(client)
            if item and item.IsOk():
                row = self.history_list.ItemToRow(item)
        self._show_history_context_menu(row)

    def _show_history_context_menu(self, row: int | None) -> None:
        if self._is_running:
            return
        if row is not None and not (0 <= row < self.history_list.GetItemCount()):
            row = None
        if row is not None:
            selected_rows = set(self._selected_history_rows())
            if row not in selected_rows:
                try:
                    item = self.history_list.RowToItem(row)
                except (AttributeError, RuntimeError):
                    item = None
                if item and item.IsOk():
                    self.history_list.UnselectAll()
                    self.history_list.Select(item)
        selected_rows = self._selected_history_rows()
        if not selected_rows:
            return
        menu = wx.Menu()
        label = _("Delete chat") if len(selected_rows) == 1 else _(
            "Delete selected chats"
        )
        delete_item = menu.Append(wx.ID_ANY, label)
        menu.Bind(wx.EVT_MENU, self._on_clear_history, delete_item)
        try:
            self.history_list.PopupMenu(menu)
        finally:
            menu.Destroy()

    def _on_select_history(self, event: dv.DataViewEvent) -> None:
        """Load prompt from history selection."""

        if self._suppress_history_selection:
            event.Skip()
            return

        index = self._extract_history_index(event)
        if index is not None:
            self._activate_conversation_by_index(
                index, persist=True, refresh_history=False
            )
        event.Skip()

    def _on_stop(self, _event: wx.Event) -> None:
        """Cancel the in-flight agent request, if any."""

        handle = self._active_run_handle
        if handle is None:
            return
        handle.cancel()
        self._discard_pending_entry(handle)
        self._active_run_handle = None
        self._set_wait_state(False)
        self.status_label.SetLabel(_("Generation cancelled"))
        self.input.SetValue(handle.prompt)
        self.input.SetInsertionPointEnd()
        self.input.SetFocus()

    # ------------------------------------------------------------------
    def _refresh_bottom_panel_layout(self) -> None:
        """Request layout update for controls hosted in the bottom panel."""

        panel = self._bottom_panel
        if panel is None:
            return
        panel.Layout()
        panel.SendSizeEvent()
        self.Layout()

    # ------------------------------------------------------------------
    def _set_wait_state(
        self,
        active: bool,
        tokens: TokenCountResult | None = None,
    ) -> None:
        """Enable or disable busy indicators."""

        self._is_running = active
        self._send_btn.Enable(not active)
        self.input.Enable(not active)
        if self._stop_btn is not None:
            self._stop_btn.Enable(active)
        self._update_history_controls()
        if active:
            self._current_tokens = (
                tokens if tokens is not None else TokenCountResult.exact(0)
            )
            self._start_time = time.monotonic()
            self.activity.Show()
            self.activity.Start()
            self._refresh_bottom_panel_layout()
            self._update_status(0.0)
            self._timer.Start(100)
        else:
            if tokens is not None:
                self._current_tokens = tokens
            else:
                self._current_tokens = TokenCountResult.exact(0)
            self._timer.Stop()
            self.activity.Stop()
            self.activity.Hide()
            self._refresh_bottom_panel_layout()
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

    def _format_tokens_for_status(self, tokens: TokenCountResult) -> str:
        """Return status label representation for ``tokens``."""

        if tokens.tokens is None:
            return TOKEN_UNAVAILABLE_LABEL
        quantity = tokens.tokens / 1000 if tokens.tokens else 0.0
        label = f"{quantity:.2f} k tokens"
        return f"~{label}" if tokens.approximate else label

    def _format_tokens_for_summary(self, tokens: TokenCountResult) -> str:
        """Return history summary representation for ``tokens``."""

        if tokens.tokens is None:
            return TOKEN_UNAVAILABLE_LABEL
        quantity = tokens.tokens / 1000 if tokens.tokens else 0.0
        label = f"{quantity:.2f}k"
        return f"~{label}" if tokens.approximate else label

    def _update_status(self, elapsed: float) -> None:
        """Show formatted timer and prompt size."""

        minutes, seconds = divmod(int(elapsed), 60)
        label = _("Waiting for agent… {time} • {tokens}").format(
            time=f"{minutes:02d}:{seconds:02d}",
            tokens=self._format_tokens_for_status(self._current_tokens),
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
        final_tokens: TokenCountResult | None = None
        try:
            conversation_text, display_text, raw_result, tool_results = self._process_result(result)
            response_tokens = count_text_tokens(
                conversation_text,
                model=self._token_model(),
            )
            final_tokens = combine_token_counts(
                [handle.prompt_tokens, response_tokens]
            )
            response_at = utc_now_iso()
            prompt_at = getattr(handle, "prompt_at", None) or response_at
            conversation = self._get_conversation_by_id(handle.conversation_id)
            pending_entry = handle.pending_entry
            if conversation is not None and pending_entry is not None:
                self._complete_pending_entry(
                    conversation,
                    pending_entry,
                    prompt=prompt,
                    response=conversation_text,
                    display_response=display_text,
                    raw_result=raw_result,
                    tool_results=tool_results,
                    token_info=final_tokens,
                    prompt_at=prompt_at,
                    response_at=response_at,
                    context_messages=handle.context_messages,
                )
            else:
                self._append_history(
                    prompt,
                    conversation_text,
                    display_text,
                    raw_result,
                    tool_results,
                    final_tokens,
                    prompt_at=prompt_at,
                    response_at=response_at,
                    context_messages=handle.context_messages,
                )
            handle.pending_entry = None
            self._render_transcript()
        finally:
            self._set_wait_state(False, final_tokens)
            if elapsed:
                minutes, seconds = divmod(int(elapsed), 60)
                if final_tokens is None:
                    tokens_label = self._format_tokens_for_status(TokenCountResult.exact(0))
                else:
                    tokens_label = self._format_tokens_for_status(final_tokens)
                label = _("Received response in {time} • {tokens}").format(
                    time=f"{minutes:02d}:{seconds:02d}",
                    tokens=tokens_label,
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
        conversation_text = normalize_for_display(conversation_text)
        if display_text:
            display_text = normalize_for_display(display_text)
        else:
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

    @staticmethod
    def _prepare_context_messages(
        raw: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    ) -> tuple[dict[str, Any], ...]:
        if not raw:
            return ()
        if isinstance(raw, Mapping):
            return (dict(raw),)
        prepared: list[dict[str, Any]] = []
        for entry in raw:
            if isinstance(entry, Mapping):
                prepared.append(dict(entry))
        return tuple(prepared)

    @staticmethod
    def _clone_context_messages(
        context: Sequence[Mapping[str, Any]] | None,
    ) -> tuple[dict[str, Any], ...] | None:
        if not context:
            return None
        cloned: list[dict[str, Any]] = []
        for message in context:
            if isinstance(message, Mapping):
                cloned.append(dict(message))
        if not cloned:
            return None
        return tuple(cloned)

    def _add_pending_entry(
        self,
        conversation: ChatConversation,
        prompt: str,
        *,
        prompt_at: str,
        context_messages: tuple[dict[str, Any], ...] | None,
    ) -> ChatEntry:
        prompt_text = normalize_for_display(prompt)
        entry = ChatEntry(
            prompt=prompt_text,
            response="",
            tokens=0,
            display_response=_("Waiting for agent response…"),
            raw_result=None,
            tool_results=None,
            token_info=TokenCountResult.exact(0),
            prompt_at=prompt_at,
            response_at=None,
            context_messages=self._clone_context_messages(context_messages),
        )
        conversation.append_entry(entry)
        return entry

    def _append_history(
        self,
        prompt: str,
        response: str,
        display_response: str,
        raw_result: Any | None,
        tool_results: list[Any] | None,
        token_info: TokenCountResult | None,
        *,
        prompt_at: str | None = None,
        response_at: str | None = None,
        context_messages: tuple[dict[str, Any], ...] | None = None,
    ) -> None:
        conversation = self._ensure_active_conversation()
        prompt_text = normalize_for_display(prompt)
        response_text = normalize_for_display(response)
        display_text = normalize_for_display(display_response)
        if token_info is None:
            token_info = combine_token_counts(
                [
                    count_text_tokens(prompt_text, model=self._token_model()),
                    count_text_tokens(response_text, model=self._token_model()),
                ]
            )
        tokens = token_info.tokens or 0
        entry = ChatEntry(
            prompt=prompt_text,
            response=response_text,
            tokens=tokens,
            display_response=display_text,
            raw_result=raw_result,
            tool_results=tool_results,
            token_info=token_info,
            prompt_at=prompt_at,
            response_at=response_at,
            context_messages=self._clone_context_messages(context_messages),
        )
        conversation.append_entry(entry)
        self._save_history()
        self._refresh_history_list()

    def _complete_pending_entry(
        self,
        conversation: ChatConversation,
        entry: ChatEntry,
        *,
        prompt: str,
        response: str,
        display_response: str,
        raw_result: Any | None,
        tool_results: list[Any] | None,
        token_info: TokenCountResult | None,
        prompt_at: str,
        response_at: str,
        context_messages: tuple[dict[str, Any], ...] | None,
    ) -> None:
        prompt_text = normalize_for_display(prompt)
        response_text = normalize_for_display(response)
        display_text = normalize_for_display(display_response or response)
        entry.prompt = prompt_text
        entry.response = response_text
        entry.display_response = display_text
        entry.raw_result = raw_result
        entry.tool_results = tool_results
        tokens_info = token_info if token_info is not None else TokenCountResult.exact(0)
        entry.token_info = tokens_info
        entry.tokens = tokens_info.tokens or 0
        entry.prompt_at = prompt_at
        entry.response_at = response_at
        entry.context_messages = self._clone_context_messages(context_messages)
        conversation.updated_at = response_at
        conversation.ensure_title()
        self._save_history()
        self._refresh_history_list()

    def _pop_conversation_entry(
        self,
        conversation: ChatConversation,
        entry: ChatEntry,
    ) -> tuple[int, ChatEntry, str] | None:
        try:
            index = conversation.entries.index(entry)
        except ValueError:
            return None
        previous_updated = conversation.updated_at
        removed = conversation.entries.pop(index)
        if conversation.entries:
            last = conversation.entries[-1]
            conversation.updated_at = (
                last.response_at or last.prompt_at or conversation.updated_at
            )
        else:
            conversation.updated_at = conversation.created_at
        return index, removed, previous_updated

    @staticmethod
    def _restore_conversation_entry(
        conversation: ChatConversation,
        index: int,
        entry: ChatEntry,
        previous_updated: str,
    ) -> None:
        conversation.entries.insert(index, entry)
        conversation.updated_at = previous_updated

    def _discard_pending_entry(self, handle: _AgentRunHandle) -> None:
        entry = handle.pending_entry
        if entry is None:
            return
        conversation = self._get_conversation_by_id(handle.conversation_id)
        if conversation is None:
            return
        removal = self._pop_conversation_entry(conversation, entry)
        if removal is None:
            return
        handle.pending_entry = None
        self._save_history()
        self._refresh_history_list()
        self._render_transcript()

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
        has_entries = False
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
                has_entries = True
                last_entry = conversation.entries[-1]
                for entry in conversation.entries:
                    can_regenerate = entry is last_entry and entry.response_at is not None
                    on_regenerate = (
                        (lambda e=entry, cid=conversation.conversation_id: self._on_regenerate_entry(cid, e))
                        if can_regenerate
                        else None
                    )
                    panel = TranscriptMessagePanel(
                        self.transcript_panel,
                        prompt=entry.prompt,
                        response=entry.display_response or entry.response,
                        prompt_timestamp=self._format_entry_timestamp(entry.prompt_at),
                        response_timestamp=self._format_entry_timestamp(entry.response_at),
                        on_regenerate=on_regenerate,
                        regenerate_enabled=not self._is_running,
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
                self._scroll_transcript_to_bottom(last_panel)
        self._update_transcript_copy_buttons(has_entries)

    def _on_regenerate_entry(
        self,
        conversation_id: str,
        entry: ChatEntry,
    ) -> None:
        if self._is_running:
            return
        conversation = self._get_conversation_by_id(conversation_id)
        if conversation is None or not conversation.entries:
            return
        if entry is not conversation.entries[-1]:
            return
        prompt = entry.prompt
        if not prompt.strip():
            return
        removal = self._pop_conversation_entry(conversation, entry)
        if removal is None:
            return
        index, removed_entry, previous_updated = removal
        try:
            self._submit_prompt(prompt)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to regenerate agent response")
            self._restore_conversation_entry(
                conversation,
                index,
                removed_entry,
                previous_updated,
            )
            self._save_history()
            self._refresh_history_list()
            self._render_transcript()

    @staticmethod
    def _is_window_alive(window: wx.Window | None) -> bool:
        if window is None:
            return False
        try:
            return bool(window) and not window.IsBeingDeleted()
        except RuntimeError:
            return False

    def _scroll_transcript_to_bottom(self, target: wx.Window | None) -> None:
        self._apply_transcript_scroll(target)
        wx.CallAfter(self._apply_transcript_scroll, target)

    def _apply_transcript_scroll(self, target: wx.Window | None) -> None:
        panel = getattr(self, "transcript_panel", None)
        if not self._is_window_alive(panel):
            return
        assert isinstance(panel, ScrolledPanel)
        window: wx.Window | None = target if self._is_window_alive(target) else None
        if window is not None and window.GetParent() is not panel:
            window = None
        if window is not None:
            try:
                panel.ScrollChildIntoView(window)
            except RuntimeError:
                window = None
        bottom_pos = max(0, panel.GetScrollRange(wx.VERTICAL))
        view_x, view_y = panel.GetViewStart()
        if bottom_pos != view_y:
            panel.Scroll(view_x, bottom_pos)

    def _ensure_history_visible(self, index: int) -> None:
        if not (0 <= index < self.history_list.GetItemCount()):
            return
        item = self.history_list.RowToItem(index)
        if item.IsOk():
            self.history_list.EnsureVisible(item)

    def get_transcript_text(self) -> str:
        """Return plain-text transcript of the active conversation.

        This method is intentionally public so tests and other automation can
        assert against the transcript without accessing wx-specific widgets or
        recreating helper wrappers.
        """

        return self._compose_transcript_text()

    def get_transcript_log_text(self) -> str:
        """Return detailed transcript log for diagnostic purposes."""

        return self._compose_transcript_log_text()

    def _compose_transcript_text(self) -> str:
        conversation = self._get_active_conversation()
        if conversation is None:
            return _("Start chatting with the agent to see responses here.")
        if not conversation.entries:
            return _("This chat does not have any messages yet. Send one to get started.")

        blocks: list[str] = []
        for idx, entry in enumerate(conversation.entries, start=1):
            prompt_text = normalize_for_display(entry.prompt)
            response_source = entry.display_response or entry.response
            response_text = normalize_for_display(response_source)
            block = (
                f"{idx}. "
                + _("You:")
                + f"\n{prompt_text}\n\n"
                + _("Agent:")
                + f"\n{response_text}"
            )
            blocks.append(block)
        return "\n\n".join(blocks)

    def _compose_transcript_log_text(self) -> str:
        conversation = self._get_active_conversation()
        if conversation is None:
            return _("Start chatting with the agent to see responses here.")
        if not conversation.entries:
            return _("This chat does not have any messages yet. Send one to get started.")

        def format_timestamp(value: str | None) -> str:
            if not value:
                return _("not recorded")
            return normalize_for_display(value)

        def format_json_block(value: Any) -> str:
            if value is None:
                return _("(none)")
            if isinstance(value, str):
                text = value
            else:
                try:
                    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
                except (TypeError, ValueError):
                    text = str(value)
            return normalize_for_display(text)

        def indent_block(value: str, *, prefix: str = "    ") -> str:
            return textwrap.indent(value, prefix)

        def format_tool_payload(index: int, payload: Any) -> list[str]:
            lines: list[str] = []
            if isinstance(payload, Mapping):
                raw_name = (
                    payload.get("tool_name")
                    or payload.get("name")
                    or payload.get("tool")
                )
                name = (
                    normalize_for_display(str(raw_name))
                    if raw_name
                    else _("Unnamed tool")
                )
                ok_value = payload.get("ok")
                if ok_value is True:
                    status = _("Success")
                elif ok_value is False:
                    status = _("Error")
                else:
                    status = _("Unknown")
                lines.append(
                    _("  [{index}] {name} — Status: {status}").format(
                        index=index,
                        name=name,
                        status=status,
                    )
                )
                call_id = payload.get("call_id") or payload.get("tool_call_id")
                if call_id:
                    lines.append(
                        _("    Call ID: {value}").format(
                            value=normalize_for_display(str(call_id))
                        )
                    )
                arguments = payload.get("tool_arguments")
                if arguments is not None:
                    lines.append(_("    Arguments:"))
                    lines.append(indent_block(format_json_block(arguments), prefix="      "))
                result_payload = payload.get("result")
                if result_payload is not None:
                    lines.append(_("    Result payload:"))
                    lines.append(indent_block(format_json_block(result_payload), prefix="      "))
                error_payload = payload.get("error")
                if error_payload and ok_value is not True:
                    lines.append(_("    Error details:"))
                    lines.append(indent_block(format_json_block(error_payload), prefix="      "))
                extras = {
                    key: value
                    for key, value in payload.items()
                    if key
                    not in {
                        "tool_name",
                        "name",
                        "tool",
                        "call_id",
                        "tool_call_id",
                        "ok",
                        "tool_arguments",
                        "result",
                        "error",
                    }
                }
                if extras:
                    lines.append(_("    Extra fields:"))
                    lines.append(indent_block(format_json_block(extras), prefix="      "))
            else:
                lines.append(
                    _("  [{index}] {summary}").format(
                        index=index,
                        summary=normalize_for_display(str(payload)),
                    )
                )
            return lines

        def format_message_list(
            messages: Sequence[Mapping[str, Any]] | None,
        ) -> str:
            if not messages:
                return format_json_block(None)
            prepared: list[dict[str, Any]] = []
            for message in messages:
                if isinstance(message, Mapping):
                    prepared.append(dict(message))
            if not prepared:
                return format_json_block(None)
            safe_value = _history_json_safe(prepared)
            return format_json_block(safe_value)

        def gather_history_messages(limit: int) -> list[dict[str, Any]]:
            history_messages: list[dict[str, Any]] = []
            for previous in conversation.entries[:limit]:
                if previous.prompt:
                    history_messages.append(
                        {
                            "role": "user",
                            "content": normalize_for_display(previous.prompt),
                        }
                    )
                if previous.response:
                    history_messages.append(
                        {
                            "role": "assistant",
                            "content": normalize_for_display(previous.response),
                        }
                    )
            return history_messages

        lines: list[str] = []
        lines.append(
            _("Conversation ID: {conversation_id}").format(
                conversation_id=normalize_for_display(conversation.conversation_id)
            )
        )
        lines.append(
            _("Created at: {timestamp}").format(
                timestamp=format_timestamp(conversation.created_at)
            )
        )
        lines.append(
            _("Updated at: {timestamp}").format(
                timestamp=format_timestamp(conversation.updated_at)
            )
        )
        lines.append(_("Entries: {count}").format(count=len(conversation.entries)))
        lines.append("")
        lines.append(_("LLM system prompt:"))
        lines.append(indent_block(normalize_for_display(SYSTEM_PROMPT)))
        lines.append(_("LLM tool specification:"))
        lines.append(indent_block(format_message_list(TOOLS)))
        lines.append("")

        for index, entry in enumerate(conversation.entries, start=1):
            lines.append(_("=== Interaction {index} ===").format(index=index))
            lines.append(
                _("Prompt timestamp: {timestamp}").format(
                    timestamp=format_timestamp(entry.prompt_at)
                )
            )
            prompt_text = normalize_for_display(entry.prompt)
            if prompt_text:
                lines.append(_("Prompt:"))
                lines.append(indent_block(prompt_text))
            else:
                lines.append(_("Prompt: (empty)"))
            context_snapshot = [
                dict(message) for message in (entry.context_messages or ())
            ]
            lines.append(_("Context messages:"))
            lines.append(indent_block(format_message_list(context_snapshot)))
            history_messages = gather_history_messages(index - 1)
            lines.append(_("History sent to LLM:"))
            lines.append(indent_block(format_message_list(history_messages)))
            llm_request_messages: list[dict[str, Any]] = [
                {"role": "system", "content": SYSTEM_PROMPT},
                *history_messages,
                *context_snapshot,
                {"role": "user", "content": prompt_text if prompt_text else ""},
            ]
            lines.append(_("LLM request messages:"))
            lines.append(indent_block(format_message_list(llm_request_messages)))
            lines.append(
                _("Response timestamp: {timestamp}").format(
                    timestamp=format_timestamp(entry.response_at)
                )
            )
            agent_text = normalize_for_display(entry.display_response or entry.response)
            if agent_text:
                lines.append(_("Agent response:"))
                lines.append(indent_block(agent_text))
            else:
                lines.append(_("Agent response:"))
                lines.append(indent_block(_("(empty)")))
            stored_response = normalize_for_display(entry.response)
            if stored_response and stored_response != agent_text:
                lines.append(_("Stored response payload:"))
                lines.append(indent_block(stored_response))
            lines.append(_("Tokens: {count}").format(count=entry.tokens))
            if entry.raw_result is not None:
                lines.append(_("Raw result payload:"))
                lines.append(indent_block(format_json_block(entry.raw_result)))
            tool_results = entry.tool_results or []
            if tool_results:
                lines.append(_("Tool calls:"))
                for tool_index, payload in enumerate(tool_results, start=1):
                    lines.extend(format_tool_payload(tool_index, payload))
            lines.append("")

        return "\n".join(line for line in lines if line is not None).strip()

    def _update_transcript_copy_buttons(self, enabled: bool) -> None:
        for button in (
            getattr(self, "_copy_conversation_btn", None),
            getattr(self, "_copy_transcript_log_btn", None),
        ):
            if button is not None:
                button.Enable(enabled)

    def _on_copy_conversation(self, _event: wx.CommandEvent) -> None:
        text = self._compose_transcript_text()
        if not text:
            return
        self._copy_text_to_clipboard(text)

    def _on_copy_transcript_log(self, _event: wx.CommandEvent) -> None:
        text = self._compose_transcript_log_text()
        if not text:
            return
        self._copy_text_to_clipboard(text)

    @staticmethod
    def _copy_text_to_clipboard(text: str) -> None:
        if not text:
            return
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(text))
            finally:
                wx.TheClipboard.Close()

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

    def _get_conversation_by_id(
        self, conversation_id: str | None
    ) -> ChatConversation | None:
        if conversation_id is None:
            return None
        for conversation in self.conversations:
            if conversation.conversation_id == conversation_id:
                return conversation
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
        title = normalize_for_display(title)
        summary = normalize_for_display(summary)
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

    def _format_entry_timestamp(self, timestamp: str | None) -> str:
        if not timestamp:
            return ""
        try:
            moment = datetime.datetime.fromisoformat(timestamp)
        except ValueError:
            return timestamp
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=datetime.timezone.utc)
        local_moment = moment.astimezone()
        return local_moment.strftime("%Y-%m-%d %H:%M")

    def _format_conversation_summary(self, conversation: ChatConversation) -> str:
        if not conversation.entries:
            return _("No messages yet")
        count = len(conversation.entries)
        parts = [_("Messages: {count}").format(count=count)]
        tokens = conversation.total_token_info()
        parts.append(
            _("Tokens: {tokens}").format(
                tokens=self._format_tokens_for_summary(tokens)
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
        return normalize_for_display(normalized)

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

    def _activate_conversation_by_index(
        self,
        index: int,
        *,
        persist: bool = True,
        refresh_history: bool = True,
    ) -> None:
        if not (0 <= index < len(self.conversations)):
            return
        conversation = self.conversations[index]
        self._active_conversation_id = conversation.conversation_id
        if persist:
            self._save_history()
        if refresh_history:
            self._refresh_history_list()
        else:
            self._update_history_controls()
        self._ensure_history_visible(index)
        self._render_transcript()
        self.input.SetFocus()

    def _update_history_controls(self) -> None:
        has_conversations = bool(self.conversations)
        self.history_list.Enable(has_conversations and not self._is_running)
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

