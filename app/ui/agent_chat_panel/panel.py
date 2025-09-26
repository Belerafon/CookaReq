"""Panel providing conversational interface to the local agent."""

from __future__ import annotations

import datetime
import json
import logging
import textwrap
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from concurrent.futures import Future, ThreadPoolExecutor

import wx
import wx.dataview as dv
from wx.lib.scrolledpanel import ScrolledPanel

from ...confirm import confirm
from ...i18n import _
from ...llm.spec import SYSTEM_PROMPT, TOOLS
from ...llm.tokenizer import TokenCountResult, combine_token_counts, count_text_tokens
from ...util.cancellation import CancellationEvent, OperationCancelledError
from ...util.time import utc_now_iso
from ..chat_entry import ChatConversation, ChatEntry
from ..helpers import (
    create_copy_button,
    dip,
    format_error_message,
    inherit_background,
)
from ..text import normalize_for_display
from ..splitter_utils import refresh_splitter_highlight, style_splitter
from ..widgets.chat_message import TranscriptMessagePanel
from .confirm_preferences import (
    ConfirmPreferencesMixin,
    RequirementConfirmPreference,
)
from .execution import (
    AgentCommandExecutor,
    ThreadedAgentCommandExecutor,
    _AgentRunHandle,
)
from .history_storage import HistoryPersistenceMixin
from .history_utils import (
    clone_streamed_tool_results,
    history_json_safe,
    looks_like_tool_payload,
    stringify_payload,
)
from .paths import (
    _default_history_path,
    _normalize_history_path,
    history_path_for_documents,
    settings_path_for_documents,
)
from .project_settings import (
    AgentProjectSettings,
    load_agent_project_settings,
    save_agent_project_settings,
)
from .settings_dialog import AgentProjectSettingsDialog
from .time_formatting import format_entry_timestamp, format_last_activity
from .token_usage import ContextTokenBreakdown
from .tool_summaries import (
    format_value_snippet,
    render_tool_summaries_plain,
    summarize_tool_results,
    shorten_text,
)


logger = logging.getLogger("cookareq.ui.agent_chat_panel")


try:  # pragma: no cover - import only used for typing
    from ..agent import LocalAgent  # noqa: TCH004
except Exception:  # pragma: no cover - fallback when wx stubs are used
    LocalAgent = object  # type: ignore[assignment]

TOKEN_UNAVAILABLE_LABEL = "n/a"


STATUS_HELP_TEXT = _(
    "The waiting status shows three elements:\n"
    "• The timer reports how long the agent has been running in mm:ss and updates every second.\n"
    "• The status text describes whether the agent is still working or has finished.\n"
    "• The spinning indicator on the left stays active while the agent is still working."
)


class AgentChatPanel(ConfirmPreferencesMixin, HistoryPersistenceMixin, wx.Panel):
    """Interactive chat panel driving the :class:`LocalAgent`."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        agent_supplier: Callable[..., LocalAgent],
        history_path: Path | str | None = None,
        command_executor: AgentCommandExecutor | None = None,
        token_model_resolver: Callable[[], str | None] | None = None,
        context_provider: Callable[
            [], Mapping[str, Any] | Sequence[Mapping[str, Any]] | None
        ] | None = None,
        context_window_resolver: Callable[[], int | None] | None = None,
        confirm_preference: RequirementConfirmPreference | str | None = None,
        persist_confirm_preference: Callable[[str], None] | None = None,
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
        self._settings_path = settings_path_for_documents(None)
        self._project_settings = load_agent_project_settings(self._settings_path)
        self._token_model_resolver = (
            token_model_resolver if token_model_resolver is not None else lambda: None
        )
        self._context_window_resolver = (
            context_window_resolver
            if context_window_resolver is not None
            else (lambda: None)
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
        self._conversation_label: wx.StaticText | None = None
        self._stop_btn: wx.Button | None = None
        self._bottom_panel: wx.Panel | None = None
        self._copy_conversation_btn: wx.Window | None = None
        self._suppress_history_selection = False
        self._history_last_sash = 0
        self._history_sash_goal: int | None = None
        self._history_sash_dirty = False
        self._history_sash_internal_adjust = 0
        self._vertical_sash_goal: int | None = None
        self._vertical_last_sash = 0
        self._run_counter = 0
        self._active_run_handle: _AgentRunHandle | None = None
        self._context_provider = context_provider
        self._persist_confirm_preference_callback = persist_confirm_preference
        persistent_preference = self._normalize_confirm_preference(confirm_preference)
        if persistent_preference is RequirementConfirmPreference.CHAT_ONLY:
            persistent_preference = RequirementConfirmPreference.PROMPT
        self._persistent_confirm_preference = persistent_preference
        self._confirm_preference = persistent_preference
        self._auto_confirm_overrides: dict[str, Any] | None = None
        self._confirm_choice: wx.Choice | None = None
        self._confirm_choice_index: dict[
            RequirementConfirmPreference, int
        ] = {}
        self._confirm_choice_entries: tuple[
            tuple[RequirementConfirmPreference, str], ...
        ] = ()
        self._suppress_confirm_choice_events = False
        self._project_settings_button: wx.Button | None = None
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
        self.set_project_settings_path(settings_path_for_documents(directory))

    @property
    def history_path(self) -> Path:
        """Return the path of the current chat history file."""

        return self._history_path

    def set_project_settings_path(self, path: Path | str | None) -> None:
        """Switch storage for project agent settings to *path*."""

        new_path = (
            settings_path_for_documents(None)
            if path is None
            else _normalize_history_path(path)
        )
        if new_path == self._settings_path:
            return
        self._save_project_settings()
        self._settings_path = new_path
        self._load_project_settings()

    @property
    def project_settings_path(self) -> Path:
        """Return the current path with project-scoped agent settings."""

        return self._settings_path

    @property
    def project_settings(self) -> AgentProjectSettings:
        """Return the active project settings."""

        return self._project_settings

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
        self._conversation_label = wx.StaticText(
            transcript_panel, label=_("Conversation")
        )
        transcript_header.Add(self._conversation_label, 0, wx.ALIGN_CENTER_VERTICAL)
        transcript_header.AddStretchSpacer()
        self._copy_conversation_btn = create_copy_button(
            transcript_panel,
            tooltip=_("Copy conversation"),
            fallback_label=_("Copy conversation"),
            handler=self._on_copy_conversation,
        )
        self._copy_conversation_btn.Enable(False)
        transcript_header.Add(self._copy_conversation_btn, 0, wx.ALIGN_CENTER_VERTICAL)
        transcript_header.AddSpacer(dip(self, 4))
        self._copy_transcript_log_btn = create_copy_button(
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

        self._update_conversation_header()

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

        settings_btn = wx.Button(bottom_panel, label=_("Agent instructions"))
        settings_btn.Bind(wx.EVT_BUTTON, self._on_project_settings)
        self._project_settings_button = settings_btn

        confirm_entries: tuple[
            tuple[RequirementConfirmPreference, str], ...
        ] = (
            (RequirementConfirmPreference.PROMPT, _("Ask every time")),
            (
                RequirementConfirmPreference.CHAT_ONLY,
                _("Skip for this chat"),
            ),
            (RequirementConfirmPreference.NEVER, _("Never ask")),
        )
        self._confirm_choice_entries = confirm_entries
        confirm_choice = wx.Choice(
            bottom_panel,
            choices=[label for _pref, label in confirm_entries],
        )
        self._confirm_choice = confirm_choice
        self._confirm_choice_index = {
            pref: idx for idx, (pref, _label) in enumerate(confirm_entries)
        }
        confirm_choice.Bind(wx.EVT_CHOICE, self._on_confirm_choice)
        confirm_label = wx.StaticText(
            bottom_panel, label=_("Requirement confirmations")
        )
        confirm_box = wx.BoxSizer(wx.HORIZONTAL)
        confirm_box.Add(
            confirm_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, dip(self, 4)
        )
        confirm_box.Add(confirm_choice, 0, wx.ALIGN_CENTER_VERTICAL)

        controls_sizer = wx.BoxSizer(wx.HORIZONTAL)
        controls_sizer.Add(status_sizer, 0, wx.ALIGN_CENTER_VERTICAL)
        controls_sizer.AddStretchSpacer()
        controls_sizer.Add(settings_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, spacing)
        controls_sizer.Add(confirm_box, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, spacing)
        controls_sizer.Add(button_sizer, 0, wx.ALIGN_CENTER_VERTICAL)

        self._update_confirm_choice_ui(self._confirm_preference)

        bottom_sizer.Add(input_label, 0)
        bottom_sizer.AddSpacer(spacing)
        bottom_sizer.Add(self.input, 1, wx.EXPAND)
        bottom_sizer.AddSpacer(spacing)
        bottom_sizer.Add(controls_sizer, 0, wx.EXPAND)
        bottom_sizer.AddSpacer(spacing)
        bottom_panel.SetSizer(bottom_sizer)

        self._vertical_splitter.SplitHorizontally(top_panel, bottom_panel)
        self._vertical_splitter.SetSashGravity(1.0)
        self._vertical_splitter.Bind(
            wx.EVT_SPLITTER_SASH_POS_CHANGED, self._on_vertical_sash_changed
        )
        self._vertical_last_sash = self._vertical_splitter.GetSashPosition()

        outer.Add(self._vertical_splitter, 1, wx.EXPAND)

        self.SetSizer(outer)
        refresh_splitter_highlight(self._horizontal_splitter)
        refresh_splitter_highlight(self._vertical_splitter)
        self._refresh_history_list()
        wx.CallAfter(self._adjust_vertical_splitter)
        wx.CallAfter(self._update_project_settings_ui)

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

    @property
    def vertical_sash(self) -> int:
        """Return the current top pane height for the vertical splitter."""

        splitter = getattr(self, "_vertical_splitter", None)
        if splitter and splitter.IsSplit():
            pos = splitter.GetSashPosition()
            if pos > 0:
                self._vertical_last_sash = pos
        return max(self._vertical_last_sash, 0)

    def apply_vertical_sash(self, value: int | None) -> None:
        """Apply previously stored vertical sash height if available."""

        if value is None:
            return
        target = max(int(value), 0)
        self._vertical_sash_goal = target
        self._vertical_last_sash = max(target, 0)
        self._apply_vertical_sash_if_ready()

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
        success = abs(actual - target) <= 1
        return success

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
        if history_messages:
            handle.history_snapshot = tuple(dict(message) for message in history_messages)
        else:
            handle.history_snapshot = None
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
                overrides = self._confirm_override_kwargs()
                agent = self._agent_supplier(**overrides)

                def _extract_tool_call_id(
                    payload: Mapping[str, Any]
                ) -> str | None:
                    for key in ("call_id", "tool_call_id"):
                        value = payload.get(key)
                        if isinstance(value, str) and value:
                            return value
                    return None

                def _merge_streamed_tool_result(
                    payload: dict[str, Any]
                ) -> None:
                    call_id = _extract_tool_call_id(payload)
                    if not call_id:
                        handle.streamed_tool_results.append(payload)
                        return
                    for index, existing in enumerate(handle.streamed_tool_results):
                        existing_id = _extract_tool_call_id(existing)
                        if existing_id == call_id:
                            merged = dict(existing)
                            merged.update(payload)
                            handle.streamed_tool_results[index] = merged
                            return
                    handle.streamed_tool_results.append(payload)

                def on_tool_result(payload: Mapping[str, Any]) -> None:
                    if handle.is_cancelled:
                        return
                    if not isinstance(payload, Mapping):
                        return
                    try:
                        prepared = dict(payload)
                    except Exception:  # pragma: no cover - defensive
                        return
                    _merge_streamed_tool_result(prepared)
                    snapshot = clone_streamed_tool_results(
                        handle.streamed_tool_results
                    )
                    wx.CallAfter(
                        self._handle_streamed_tool_results,
                        handle,
                        snapshot,
                    )

                return agent.run_command(
                    normalized_prompt,
                    history=history_messages,
                    context=context_messages,
                    cancellation=handle.cancel_event,
                    on_tool_result=on_tool_result,
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
        previous_id = self._active_conversation_id
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
        self._on_active_conversation_changed(previous_id, self._active_conversation_id)
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
        self._finalize_cancelled_run(handle)
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
        self._update_project_settings_ui()
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
        self._update_conversation_header()

    def _adjust_vertical_splitter(self) -> None:
        """Size the vertical splitter so the bottom pane hugs the controls."""

        if self._vertical_sash_goal is not None:
            self._apply_vertical_sash_if_ready()
            return
        if self._bottom_panel is None:
            return
        total_height = self._vertical_splitter.GetClientSize().GetHeight()
        if total_height <= 0:
            return
        bottom_height = self._bottom_panel.GetBestSize().GetHeight()
        min_top = self._vertical_splitter.GetMinimumPaneSize()
        sash_position = max(min_top, total_height - bottom_height)
        self._vertical_splitter.SetSashPosition(sash_position, True)
        self._vertical_last_sash = self._vertical_splitter.GetSashPosition()

    def _apply_vertical_sash_if_ready(self) -> None:
        """Attempt to apply stored vertical sash once metrics are available."""

        target = self._vertical_sash_goal
        if target is None:
            return
        splitter = getattr(self, "_vertical_splitter", None)
        if splitter is None or not splitter.IsSplit():
            return
        size = splitter.GetClientSize()
        total = size.GetHeight()
        if total <= 0:
            wx.CallAfter(self._apply_vertical_sash_if_ready)
            return
        minimum = splitter.GetMinimumPaneSize()
        max_top = max(minimum, total - minimum)
        desired = max(minimum, min(target, max_top))
        splitter.SetSashPosition(desired)
        actual = splitter.GetSashPosition()
        self._vertical_last_sash = max(actual, 0)

    def _on_vertical_sash_changed(self, event: wx.SplitterEvent) -> None:
        """Track user-driven adjustments of the vertical splitter."""

        splitter = getattr(self, "_vertical_splitter", None)
        if splitter is None or event.GetEventObject() is not splitter:
            event.Skip()
            return
        pos = splitter.GetSashPosition()
        self._vertical_last_sash = max(pos, 0)
        self._vertical_sash_goal = self._vertical_last_sash
        event.Skip()

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

    def _update_status(self, elapsed: float) -> None:
        """Show formatted timer and prompt size."""

        minutes, seconds = divmod(int(elapsed), 60)
        label = _("Waiting for agent… {time}").format(
            time=f"{minutes:02d}:{seconds:02d}",
        )
        self.status_label.SetLabel(label)

    def _context_token_limit(self) -> int | None:
        """Return resolved context window size when available."""

        resolver = getattr(self, "_context_window_resolver", None)
        if resolver is None:
            return None
        try:
            value = resolver()
        except Exception:  # pragma: no cover - defensive
            return None
        if value is None:
            return None
        try:
            numeric = int(value)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return None
        return numeric if numeric > 0 else None

    @staticmethod
    def _count_context_message_tokens(
        message: Mapping[str, Any],
        model: str | None,
    ) -> TokenCountResult:
        """Return token usage for *message* passed as contextual metadata."""

        if not isinstance(message, Mapping):
            return TokenCountResult.exact(0, model=model)

        parts: list[TokenCountResult] = []
        role = message.get("role")
        if role:
            parts.append(count_text_tokens(str(role), model=model))
        name = message.get("name")
        if name:
            parts.append(count_text_tokens(str(name), model=model))

        content = message.get("content")
        if content not in (None, ""):
            if isinstance(content, str):
                content_text = content
            else:
                try:
                    content_text = json.dumps(content, ensure_ascii=False)
                except Exception:  # pragma: no cover - defensive
                    content_text = str(content)
            parts.append(count_text_tokens(content_text, model=model))

        tool_calls = message.get("tool_calls")
        if tool_calls:
            try:
                serialized = json.dumps(tool_calls, ensure_ascii=False)
            except Exception:  # pragma: no cover - defensive
                serialized = str(tool_calls)
            parts.append(count_text_tokens(serialized, model=model))

        if not parts:
            return TokenCountResult.exact(0, model=model)
        return combine_token_counts(parts)

    def _active_context_messages(self) -> tuple[Mapping[str, Any], ...]:
        """Return contextual messages relevant to the current prompt."""

        handle = getattr(self, "_active_run_handle", None)
        if handle is not None and handle.context_messages:
            return handle.context_messages

        conversation = self._get_active_conversation()
        if conversation and conversation.entries:
            for entry in reversed(conversation.entries):
                if entry.context_messages:
                    return entry.context_messages
        return ()

    def _compute_context_token_breakdown(self) -> ContextTokenBreakdown:
        """Calculate token usage for the system prompt and conversation."""

        model = self._token_model()
        system_parts = [SYSTEM_PROMPT]
        custom_prompt = self._custom_system_prompt()
        if custom_prompt:
            system_parts.append(custom_prompt)
        system_tokens = combine_token_counts(
            [count_text_tokens(part, model=model) for part in system_parts if part]
        )

        history_counts: list[TokenCountResult] = []
        conversation = self._get_active_conversation()
        pending_entry = None
        if self._active_run_handle is not None:
            pending_entry = getattr(self._active_run_handle, "pending_entry", None)
        if conversation is not None:
            for entry in conversation.entries:
                if pending_entry is not None and entry is pending_entry:
                    continue
                if entry.prompt:
                    history_counts.append(
                        count_text_tokens(entry.prompt, model=model)
                    )
                if entry.response:
                    history_counts.append(
                        count_text_tokens(entry.response, model=model)
                    )
        history_tokens = combine_token_counts(history_counts)

        context_counts = [
            self._count_context_message_tokens(message, model)
            for message in self._active_context_messages()
        ]
        context_tokens = combine_token_counts(context_counts)

        if self._active_run_handle is not None:
            prompt_tokens = self._active_run_handle.prompt_tokens
        else:
            prompt_tokens = TokenCountResult.exact(0, model=model)

        return ContextTokenBreakdown(
            system=system_tokens,
            history=history_tokens,
            context=context_tokens,
            prompt=prompt_tokens,
        )

    def _format_context_percentage(
        self, tokens: TokenCountResult, limit: int | None
    ) -> str:
        """Return percentage representation of context usage."""

        if limit is None or limit <= 0:
            return TOKEN_UNAVAILABLE_LABEL
        if tokens.tokens is None:
            return TOKEN_UNAVAILABLE_LABEL
        percentage = (tokens.tokens / limit) * 100
        if percentage >= 10:
            formatted = f"{percentage:.0f}%"
        elif percentage >= 1:
            formatted = f"{percentage:.1f}%"
        else:
            formatted = f"{percentage:.2f}%"
        if tokens.approximate:
            return f"~{formatted}"
        return formatted

    def _update_conversation_header(self) -> None:
        """Refresh the transcript header with token statistics."""

        label = getattr(self, "_conversation_label", None)
        if label is None:
            return

        breakdown = self._compute_context_token_breakdown()
        total_tokens = breakdown.total
        tokens_text = self._format_tokens_for_status(total_tokens)
        percent_text = self._format_context_percentage(
            total_tokens, self._context_token_limit()
        )

        limit = self._context_token_limit()
        if limit is not None:
            limit_tokens = TokenCountResult.exact(
                limit,
                model=total_tokens.model,
            )
            limit_text = self._format_tokens_for_status(limit_tokens)
            tokens_text = _("{used} / {limit}").format(
                used=tokens_text,
                limit=limit_text,
            )

        stats_text = _("Tokens: {tokens} • Context window: {usage}").format(
            tokens=tokens_text,
            usage=percent_text,
        )
        combined_label = _("{base} — {details}").format(
            base=_("Conversation"),
            details=stats_text,
        )
        label.SetLabel(combined_label)
        parent = label.GetParent()
        if parent is not None:
            parent.Layout()

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
        tool_results: list[Any] | None = None
        should_render = False
        try:
            (
                conversation_text,
                display_text,
                raw_result,
                tool_results,
                reasoning_segments,
            ) = self._process_result(result)
            if not tool_results and handle.streamed_tool_results:
                tool_results = list(
                    clone_streamed_tool_results(handle.streamed_tool_results)
                )
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
                    history_snapshot=handle.history_snapshot,
                    reasoning_segments=reasoning_segments,
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
                    history_snapshot=handle.history_snapshot,
                    reasoning_segments=reasoning_segments,
                )
            handle.pending_entry = None
            handle.streamed_tool_results.clear()
            should_render = True
        finally:
            self._set_wait_state(False, final_tokens)
            if elapsed:
                minutes, seconds = divmod(int(elapsed), 60)
                time_text = f"{minutes:02d}:{seconds:02d}"
                token_label = self._format_tokens_for_status(self._current_tokens)
                if token_label:
                    label = _("Received response in {time} • {tokens}").format(
                        time=time_text,
                        tokens=token_label,
                    )
                else:
                    label = _("Received response in {time}").format(time=time_text)
                self.status_label.SetLabel(label)

        if should_render:
            self._render_transcript()

    def _process_result(
        self, result: Any
    ) -> tuple[
        str,
        str,
        Any | None,
        list[Any] | None,
        tuple[dict[str, str], ...],
    ]:
        """Normalise agent result for storage and display."""

        display_text = ""
        conversation_parts: list[str] = []
        raw_payload: Any | None = None
        tool_results: list[Any] | None = None
        reasoning_segments: tuple[dict[str, str], ...] = ()

        if isinstance(result, Mapping):
            raw_payload = history_json_safe(result)
            if not result.get("ok", False):
                display_text = format_error_message(result.get("error"))
                conversation_parts.append(display_text)
            else:
                payload = result.get("result")
                display_text = stringify_payload(payload)
                if display_text:
                    conversation_parts.append(display_text)

            extras = result.get("tool_results")
            if extras:
                safe_extras = history_json_safe(extras)
                if isinstance(safe_extras, list):
                    tool_results = safe_extras
                else:
                    tool_results = [safe_extras]
                extras_text = stringify_payload(safe_extras)
                if extras_text:
                    conversation_parts.append(extras_text)
            reasoning_segments = self._normalise_reasoning_segments(
                result.get("reasoning")
            )
        else:
            display_text = str(result)
            conversation_parts.append(display_text)

        conversation_text = "\n\n".join(part for part in conversation_parts if part)
        conversation_text = normalize_for_display(conversation_text)
        if display_text:
            display_text = normalize_for_display(display_text)
        else:
            display_text = conversation_text

        return (
            conversation_text,
            display_text,
            raw_payload,
            tool_results,
            reasoning_segments,
        )

    def _normalise_reasoning_segments(
        self, raw_segments: Any
    ) -> tuple[dict[str, str], ...]:
        if not raw_segments:
            return ()
        if isinstance(raw_segments, Mapping):
            candidates: Sequence[Any] = [raw_segments]
        elif isinstance(raw_segments, Sequence) and not isinstance(
            raw_segments, (str, bytes, bytearray)
        ):
            candidates = raw_segments
        else:
            candidates = [raw_segments]
        segments: list[dict[str, str]] = []
        for item in candidates:
            if isinstance(item, Mapping):
                type_value = item.get("type")
                text_value = item.get("text")
            else:
                type_value = getattr(item, "type", None)
                text_value = getattr(item, "text", None)
            if text_value is None:
                continue
            text = str(text_value).strip()
            if not text:
                continue
            type_str = str(type_value) if type_value is not None else ""
            segments.append({"type": type_str, "text": text})
        return tuple(segments)

    # ------------------------------------------------------------------
    def _conversation_messages(self) -> list[dict[str, str]]:
        conversation = self._get_active_conversation()
        if conversation is None:
            return []
        messages: list[dict[str, str]] = []
        custom_prompt = self._custom_system_prompt()
        if custom_prompt:
            messages.append({"role": "system", "content": custom_prompt})
        for entry in conversation.entries:
            if getattr(entry, "regenerated", False):
                continue
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
        history_snapshot: tuple[dict[str, Any], ...] | None = None,
        reasoning_segments: tuple[dict[str, str], ...] | None = None,
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
        context_clone = self._clone_context_messages(context_messages)
        reasoning_clone = self._normalise_reasoning_segments(reasoning_segments)
        if not reasoning_clone:
            reasoning_clone = None
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
            context_messages=context_clone,
            reasoning=reasoning_clone,
            diagnostic=self._build_entry_diagnostic(
                prompt=prompt_text,
                prompt_at=prompt_at,
                response_at=response_at,
                display_response=display_text,
                stored_response=response_text,
                raw_result=raw_result,
                tool_results=tool_results,
                history_snapshot=history_snapshot,
                context_snapshot=context_clone,
                custom_system_prompt=self._custom_system_prompt(),
            ),
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
        history_snapshot: tuple[dict[str, Any], ...] | None = None,
        reasoning_segments: tuple[dict[str, str], ...] | None = None,
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
        context_clone = self._clone_context_messages(context_messages)
        entry.context_messages = context_clone
        reasoning_clone = self._normalise_reasoning_segments(reasoning_segments)
        entry.reasoning = reasoning_clone or None
        entry.diagnostic = self._build_entry_diagnostic(
            prompt=prompt_text,
            prompt_at=prompt_at,
            response_at=response_at,
            display_response=display_text,
            stored_response=response_text,
            raw_result=raw_result,
            tool_results=tool_results,
            history_snapshot=history_snapshot,
            context_snapshot=context_clone,
            custom_system_prompt=self._custom_system_prompt(),
        )
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
        handle.streamed_tool_results.clear()
        self._save_history()
        self._refresh_history_list()
        self._render_transcript()

    def _finalize_cancelled_run(self, handle: _AgentRunHandle) -> None:
        """Preserve transcript state after cancelling an agent run."""

        entry = handle.pending_entry
        if entry is None:
            self._render_transcript()
            return
        conversation = self._get_conversation_by_id(handle.conversation_id)
        if conversation is None:
            handle.pending_entry = None
            handle.streamed_tool_results.clear()
            self._render_transcript()
            return

        cancellation_message = _("Generation cancelled")
        response_at = utc_now_iso()
        prompt_at = getattr(handle, "prompt_at", None) or response_at
        token_info = combine_token_counts([handle.prompt_tokens])
        tool_results_payload = handle.prepare_tool_results_payload()
        tool_results = list(tool_results_payload) if tool_results_payload else None
        raw_result = {
            "ok": False,
            "error": {
                "type": "OperationCancelledError",
                "message": cancellation_message,
                "details": {"reason": "user_cancelled"},
            },
        }

        self._complete_pending_entry(
            conversation,
            entry,
            prompt=handle.prompt,
            response="",
            display_response=cancellation_message,
            raw_result=raw_result,
            tool_results=tool_results,
            token_info=token_info,
            prompt_at=prompt_at,
            response_at=response_at,
            context_messages=handle.context_messages,
            history_snapshot=handle.history_snapshot,
        )
        handle.pending_entry = None
        handle.streamed_tool_results.clear()
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
                    tool_summaries = summarize_tool_results(entry.tool_results)
                    response_text = entry.display_response or entry.response
                    valid_hint_keys = {"user", "agent"}
                    for summary in tool_summaries:
                        valid_hint_keys.add(
                            TranscriptMessagePanel.tool_layout_hint_key(summary)
                        )
                    hints = entry.layout_hints if isinstance(entry.layout_hints, dict) else {}
                    entry.layout_hints = {
                        key: value for key, value in hints.items() if key in valid_hint_keys
                    }
                    panel = TranscriptMessagePanel(
                        self.transcript_panel,
                        prompt=entry.prompt,
                        response=response_text,
                        prompt_timestamp=format_entry_timestamp(entry.prompt_at),
                        response_timestamp=format_entry_timestamp(entry.response_at),
                        on_regenerate=on_regenerate,
                        regenerate_enabled=not self._is_running,
                        tool_summaries=tool_summaries,
                        context_messages=entry.context_messages,
                        reasoning_segments=entry.reasoning,
                        regenerated=getattr(entry, "regenerated", False),
                        layout_hints=entry.layout_hints,
                        on_layout_hint=lambda key, width, entry=entry: entry.layout_hints.__setitem__(
                            key, int(width)
                        ),
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
        self._update_conversation_header()

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
        previous_state = entry.regenerated
        entry.regenerated = True
        self._save_history()
        self._refresh_history_list()
        self._render_transcript()
        try:
            self._submit_prompt(prompt)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to regenerate agent response")
            entry.regenerated = previous_state
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

    @staticmethod
    def _sanitize_log_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
        safe_mapping_raw = history_json_safe(value)
        mapping: dict[str, Any] = {}
        if isinstance(safe_mapping_raw, Mapping):
            for key, val in safe_mapping_raw.items():
                key_str = str(key)
                if isinstance(val, str):
                    mapping[key_str] = normalize_for_display(val)
                else:
                    mapping[key_str] = val
        if "role" not in mapping and "role" in value:
            mapping["role"] = normalize_for_display(str(value["role"]))
        if "content" not in mapping:
            if "content" in value:
                content_value = value["content"]
                if content_value is None:
                    mapping["content"] = ""
                elif isinstance(content_value, str):
                    mapping["content"] = normalize_for_display(content_value)
                else:
                    mapping["content"] = history_json_safe(content_value)
            else:
                mapping["content"] = ""
        return mapping

    @classmethod
    def _sanitize_log_messages(
        cls, messages: Sequence[Mapping[str, Any]] | None
    ) -> list[dict[str, Any]]:
        sanitized: list[dict[str, Any]] = []
        if not messages:
            return sanitized
        for message in messages:
            if isinstance(message, Mapping):
                sanitized.append(cls._sanitize_log_mapping(message))
        return sanitized

    @classmethod
    def _sanitize_llm_requests(
        cls, requests: Sequence[Any] | None
    ) -> list[dict[str, Any]]:
        sanitized: list[dict[str, Any]] = []
        if not requests:
            return sanitized
        for index, entry in enumerate(requests, start=1):
            if not isinstance(entry, Mapping):
                continue
            messages_raw = entry.get("messages")
            messages = cls._sanitize_log_messages(
                messages_raw if isinstance(messages_raw, Sequence) else None
            )
            step_raw = entry.get("step")
            try:
                step_value = int(step_raw) if step_raw is not None else index
            except (TypeError, ValueError):
                step_value = index
            sanitized.append({"step": step_value, "messages": messages})
        return sanitized

    @classmethod
    def _build_entry_diagnostic(
        cls,
        *,
        prompt: str,
        prompt_at: str | None,
        response_at: str | None,
        display_response: str,
        stored_response: str,
        raw_result: Any | None,
        tool_results: Sequence[Any] | None,
        history_snapshot: Sequence[Mapping[str, Any]] | None,
        context_snapshot: Sequence[Mapping[str, Any]] | None,
        custom_system_prompt: str | None = None,
    ) -> dict[str, Any]:
        prompt_text = normalize_for_display(prompt)
        display_text = normalize_for_display(display_response)
        stored_text = normalize_for_display(stored_response)
        history_messages = cls._sanitize_log_messages(history_snapshot)
        context_messages = cls._sanitize_log_messages(context_snapshot)

        raw_result_safe = history_json_safe(raw_result) if raw_result is not None else None
        raw_result_mapping = (
            raw_result_safe if isinstance(raw_result_safe, Mapping) else None
        )

        if isinstance(raw_result_mapping, Mapping):
            diagnostic_raw = raw_result_mapping.get("diagnostic")
        else:
            diagnostic_raw = None

        llm_request_sequence: list[dict[str, Any]] = []
        if isinstance(diagnostic_raw, Mapping):
            requests_raw = diagnostic_raw.get("llm_requests")
            if isinstance(requests_raw, Sequence):
                llm_request_sequence = cls._sanitize_llm_requests(requests_raw)

        if llm_request_sequence:
            llm_request_messages = llm_request_sequence[-1]["messages"]
        else:
            llm_request_messages = [
                {"role": "system", "content": normalize_for_display(SYSTEM_PROMPT)},
                *history_messages,
                *context_messages,
                {"role": "user", "content": prompt_text},
            ]
            llm_request_sequence = [
                {"step": 1, "messages": list(llm_request_messages)}
            ]

        llm_message: str | None = None
        error_payload: Any | None = None
        planned_tool_calls: list[Any] | None = None
        if raw_result_mapping:
            result_value = raw_result_mapping.get("result")
            if isinstance(result_value, str):
                llm_message = normalize_for_display(result_value)
            error_value = raw_result_mapping.get("error")
            if error_value:
                error_payload = history_json_safe(error_value)
                if isinstance(error_payload, Mapping):
                    details_payload = error_payload.get("details")
                    if isinstance(details_payload, Mapping):
                        raw_llm_message = details_payload.get("llm_message")
                        if (
                            llm_message in (None, "")
                            and isinstance(raw_llm_message, str)
                            and raw_llm_message.strip()
                        ):
                            llm_message = normalize_for_display(raw_llm_message)
                        raw_tool_calls = details_payload.get("llm_tool_calls")
                        if raw_tool_calls:
                            safe_calls = history_json_safe(raw_tool_calls)
                            if isinstance(safe_calls, list):
                                planned_tool_calls = safe_calls or None
                            elif safe_calls is not None:
                                planned_tool_calls = [safe_calls]

        tool_payloads: list[Any] = []
        if tool_results:
            for payload in tool_results:
                tool_payloads.append(history_json_safe(payload))
        elif raw_result_mapping and looks_like_tool_payload(raw_result_mapping):
            tool_payloads.append(raw_result_mapping)

        diagnostic_payload = {
            "prompt_text": prompt_text,
            "prompt_at": prompt_at,
            "response_at": response_at,
            "llm_request_messages": llm_request_messages,
            "history_messages": history_messages,
            "context_messages": context_messages,
            "llm_final_message": llm_message,
            "llm_tool_calls": planned_tool_calls,
            "tool_exchanges": tool_payloads,
            "agent_response_text": display_text,
            "agent_stored_response": stored_text
            if stored_text != display_text
            else None,
            "raw_result": raw_result_safe,
            "error_payload": error_payload,
            "llm_request_messages_sequence": llm_request_sequence,
            "llm_requests": llm_request_sequence,
            "custom_system_prompt": normalize_for_display(custom_system_prompt)
            if custom_system_prompt
            else None,
        }

        return history_json_safe(diagnostic_payload)

    def _handle_streamed_tool_results(
        self,
        handle: _AgentRunHandle,
        tool_results: Sequence[Mapping[str, Any]] | None,
    ) -> None:
        """Update transcript with in-flight tool results for *handle*."""

        if handle.is_cancelled:
            return
        if handle is not self._active_run_handle:
            return
        entry = handle.pending_entry
        if entry is None:
            return
        if not tool_results:
            entry.tool_results = None
            self._render_transcript()
            return

        cloned_results = list(clone_streamed_tool_results(tool_results))
        entry.tool_results = cloned_results
        self._render_transcript()

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
            tool_summary_plain = render_tool_summaries_plain(
                summarize_tool_results(entry.tool_results)
            )
            if tool_summary_plain:
                base_response = (response_source or "").strip()
                if base_response:
                    response_source = f"{base_response}\n\n{tool_summary_plain}"
                else:
                    response_source = tool_summary_plain
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

        def _normalise_json_value(value: Any) -> Any:
            if isinstance(value, str):
                stripped = value.strip()
                if stripped.startswith("{") or stripped.startswith("["):
                    try:
                        decoded = json.loads(stripped)
                    except (TypeError, ValueError):
                        return value
                    return _normalise_json_value(decoded)
                return value
            if isinstance(value, Mapping):
                return {
                    str(key): _normalise_json_value(val)
                    for key, val in value.items()
                }
            if isinstance(value, Sequence) and not isinstance(
                value, (str, bytes, bytearray)
            ):
                return [_normalise_json_value(item) for item in value]
            return value

        def format_json_block(value: Any) -> str:
            if value is None:
                return _("(none)")
            normalised = _normalise_json_value(value)
            if isinstance(normalised, str):
                text = normalised
            else:
                try:
                    text = json.dumps(
                        normalised,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                except (TypeError, ValueError):
                    text = str(normalised)
            return normalize_for_display(text)

        def indent_block(value: str, *, prefix: str = "    ") -> str:
            return textwrap.indent(value, prefix)

        def describe_message_origin(role: str | None) -> str:
            normalized = (role or "").strip().lower()
            if normalized == "system":
                return _("Agent system prompt")
            if normalized == "developer":
                return _("Agent developer message")
            if normalized == "user":
                return _("User message (forwarded to LLM)")
            if normalized == "assistant":
                return _("LLM response (replayed as context)")
            if normalized == "tool":
                return _("Tool result (forwarded to LLM)")
            if normalized == "function":
                return _("Function result (forwarded to LLM)")
            return _("Recorded message role: {role}").format(
                role=normalize_for_display(role or _("unknown"))
            )

        def format_llm_request_sequence(
            request_sequence: Sequence[Mapping[str, Any]] | None,
        ) -> list[str]:
            if not request_sequence:
                return [_("Agent → LLM request: (no request payload recorded)")]

            formatted: list[str] = []
            for request in request_sequence:
                if not isinstance(request, Mapping):
                    continue
                step = request.get("step")
                try:
                    step_value = int(step) if step is not None else None
                except (TypeError, ValueError):
                    step_value = None
                if step_value is None:
                    formatted.append(_("Agent → LLM request:"))
                else:
                    formatted.append(
                        _("Agent → LLM request (step {index}):").format(
                            index=step_value
                        )
                    )

                messages = request.get("messages")
                if not isinstance(messages, Sequence) or not messages:
                    formatted.append(indent_block(_("No messages captured.")))
                    continue

                for idx, message in enumerate(messages, start=1):
                    if not isinstance(message, Mapping):
                        continue
                    role_value = message.get("role") if "role" in message else None
                    origin_label = describe_message_origin(
                        str(role_value) if role_value is not None else None
                    )
                    formatted.append(
                        indent_block(
                            _("Message {index} ({origin}):").format(
                                index=idx,
                                origin=origin_label,
                            )
                        )
                    )
                    formatted.append(
                        indent_block(
                            format_json_block(message),
                            prefix="        ",
                        )
                    )
            return formatted

        def format_planned_tool_calls(
            planned_calls: Sequence[Any] | None,
        ) -> list[str]:
            if not planned_calls:
                return []

            formatted: list[str] = []
            formatted.append(_("LLM → Agent planned tool calls:"))
            for index, call in enumerate(planned_calls, start=1):
                formatted.append(
                    indent_block(
                        _("Call {index}:").format(index=index)
                    )
                )
                formatted.append(
                    indent_block(
                        format_json_block(call),
                        prefix="        ",
                    )
                )
            return formatted

        def format_tool_exchange(index: int, payload: Any) -> list[str]:
            lines: list[str] = []
            if not isinstance(payload, Mapping):
                lines.append(
                    _("Agent → MCP call {index}: {summary}").format(
                        index=index,
                        summary=normalize_for_display(str(payload)),
                    )
                )
                lines.append(
                    _("MCP → Agent response {index}: (unavailable)").format(
                        index=index
                    )
                )
                return lines

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
                _("Agent → MCP call {index}: {name}").format(
                    index=index,
                    name=name,
                )
            )
            call_id = payload.get("call_id") or payload.get("tool_call_id")
            if call_id:
                lines.append(
                    indent_block(
                        _("MCP call ID: {value}").format(
                            value=normalize_for_display(str(call_id))
                        )
                    )
                )
            arguments = payload.get("tool_arguments")
            if arguments is not None:
                lines.append(indent_block(_("Arguments:")))
                lines.append(
                    indent_block(
                        format_json_block(arguments),
                        prefix="        ",
                    )
                )
            lines.append(
                _("MCP → Agent response {index}: {status}").format(
                    index=index,
                    status=status,
                )
            )
            result_payload = payload.get("result")
            if result_payload is not None:
                lines.append(indent_block(_("Result payload:")))
                lines.append(
                    indent_block(
                        format_json_block(result_payload),
                        prefix="        ",
                    )
                )
            error_payload = payload.get("error")
            if error_payload is not None:
                lines.append(indent_block(_("Error payload:")))
                lines.append(
                    indent_block(
                        format_json_block(error_payload),
                        prefix="        ",
                    )
                )
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
                lines.append(indent_block(_("Additional fields:")))
                lines.append(
                    indent_block(
                        format_json_block(extras),
                        prefix="        ",
                    )
                )
            return lines

        def ensure_diagnostic(
            entry: ChatEntry, history_messages: Sequence[Mapping[str, Any]]
        ) -> Mapping[str, Any]:
            diagnostic = entry.diagnostic
            if isinstance(diagnostic, Mapping):
                return diagnostic
            diagnostic = self._build_entry_diagnostic(
                prompt=entry.prompt,
                prompt_at=entry.prompt_at,
                response_at=entry.response_at,
                display_response=entry.display_response or entry.response,
                stored_response=entry.response,
                raw_result=entry.raw_result,
                tool_results=entry.tool_results,
                history_snapshot=history_messages,
                context_snapshot=entry.context_messages,
            )
            if isinstance(diagnostic, Mapping):
                entry.diagnostic = diagnostic
                return diagnostic
            return {}

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
            safe_value = history_json_safe(prepared)
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
            history_messages = gather_history_messages(index - 1)
            diagnostic = ensure_diagnostic(entry, history_messages)
            request_sequence = diagnostic.get("llm_request_messages_sequence")
            lines.extend(
                format_llm_request_sequence(
                    request_sequence
                    if isinstance(request_sequence, Sequence)
                    else None
                )
            )
            if TOOLS:
                lines.append(
                    _(
                        "Tool specifications are sent as a separate payload and therefore do not appear inside the compiled request messages."
                    )
                )
            lines.append(
                _("Response timestamp: {timestamp}").format(
                    timestamp=format_timestamp(entry.response_at)
                )
            )

            llm_message_text = diagnostic.get("llm_final_message")
            lines.append(_("LLM → Agent message:"))
            if llm_message_text:
                lines.append(indent_block(normalize_for_display(str(llm_message_text))))
            else:
                lines.append(indent_block(_("(none)")))

            planned_calls = diagnostic.get("llm_tool_calls")
            if isinstance(planned_calls, Sequence):
                lines.extend(format_planned_tool_calls(planned_calls))
            elif planned_calls:
                lines.extend(format_planned_tool_calls([planned_calls]))

            tool_payloads = diagnostic.get("tool_exchanges") or []
            if tool_payloads:
                for tool_index, payload in enumerate(tool_payloads, start=1):
                    lines.extend(format_tool_exchange(tool_index, payload))
            else:
                lines.append(_("Agent → MCP calls: (none)"))
                lines.append(_("MCP → Agent responses: (none)"))

            agent_text = diagnostic.get("agent_response_text")
            if not agent_text:
                agent_text = entry.display_response or entry.response
            agent_text = normalize_for_display(agent_text or "")
            lines.append(_("Agent → User response:"))
            if agent_text:
                lines.append(indent_block(agent_text))
            else:
                lines.append(indent_block(_("(empty)")))
            stored_response = diagnostic.get("agent_stored_response")
            if not stored_response:
                stored_response = entry.response
            stored_response = normalize_for_display(stored_response or "")
            if stored_response and stored_response != agent_text:
                lines.append(_("Agent stored response payload:"))
                lines.append(indent_block(stored_response))
            lines.append(_("Tokens: {count}").format(count=entry.tokens))

            error_payload = diagnostic.get("error_payload")
            raw_result_payload = diagnostic.get("raw_result")
            if raw_result_payload is None and entry.raw_result is not None:
                raw_result_payload = entry.raw_result
            if raw_result_payload is not None:
                if error_payload:
                    lines.append(_("Agent reported error payload:"))
                    lines.append(indent_block(format_json_block(error_payload)))
                lines.append(_("Agent raw result payload:"))
                lines.append(indent_block(format_json_block(raw_result_payload)))
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

    def _load_project_settings(self) -> None:
        self._project_settings = load_agent_project_settings(self._settings_path)
        self._update_project_settings_ui()

    def _save_project_settings(self) -> None:
        try:
            save_agent_project_settings(self._settings_path, self._project_settings)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to persist agent project settings to %s", self._settings_path
            )

    def _custom_system_prompt(self) -> str:
        settings = getattr(self, "_project_settings", None)
        if isinstance(settings, AgentProjectSettings):
            return settings.custom_system_prompt.strip()
        return ""

    def _update_project_settings_ui(self) -> None:
        button = getattr(self, "_project_settings_button", None)
        if button is None:
            return
        prompt = self._custom_system_prompt()
        if prompt:
            tooltip = _(
                "Custom instructions appended to the system prompt:\n{instructions}"
            ).format(instructions=normalize_for_display(prompt))
        else:
            tooltip = _(
                "Define project-specific instructions appended to the system prompt."
            )
        button.SetToolTip(tooltip)
        button.Enable(not self._is_running)

    def _apply_project_settings(
        self,
        settings: AgentProjectSettings,
        *,
        persist: bool = True,
    ) -> None:
        normalized = settings.normalized()
        if normalized == self._project_settings:
            self._update_project_settings_ui()
            return
        self._project_settings = normalized
        if persist:
            self._save_project_settings()
        self._update_project_settings_ui()
        self._update_conversation_header()

    def _on_project_settings(self, _event: wx.Event) -> None:
        dialog = AgentProjectSettingsDialog(self, settings=self._project_settings)
        try:
            result = dialog.ShowModal()
            if result != wx.ID_OK:
                return
            prompt = dialog.get_custom_system_prompt()
            self._apply_project_settings(
                AgentProjectSettings(custom_system_prompt=prompt)
            )
        finally:
            dialog.Destroy()

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
        previous_id = self._active_conversation_id
        conversation = ChatConversation.new()
        self.conversations.append(conversation)
        self._active_conversation_id = conversation.conversation_id
        self._on_active_conversation_changed(previous_id, self._active_conversation_id)
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

    def _format_conversation_row(
        self, conversation: ChatConversation
    ) -> tuple[str, str]:
        title = (conversation.title or conversation.derive_title()).strip()
        if not title:
            title = _("New chat")
        if len(title) > 60:
            title = title[:57] + "…"
        last_activity = format_last_activity(conversation.updated_at)
        title = normalize_for_display(title)
        return title, last_activity


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
        previous_id = self._active_conversation_id
        self._active_conversation_id = conversation.conversation_id
        self._on_active_conversation_changed(previous_id, self._active_conversation_id)
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

