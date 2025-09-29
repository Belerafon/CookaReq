"""Panel providing conversational interface to the local agent."""

from __future__ import annotations

import json
import logging
import textwrap
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from concurrent.futures import ThreadPoolExecutor

import wx

from ...confirm import confirm
from ...i18n import _
from ...llm.spec import SYSTEM_PROMPT, TOOLS
from ...llm.tokenizer import TokenCountResult, combine_token_counts, count_text_tokens
from ...util.time import utc_now_iso
from ..chat_entry import (
    ChatConversation,
    ChatEntry,
    count_context_message_tokens,
)
from ..helpers import (
    format_error_message,
    inherit_background,
)
from ..text import normalize_for_display
from .batch_runner import BatchTarget
from .batch_ui import AgentBatchSection
from .components.view import AgentChatView, WaitStateCallbacks
from .confirm_preferences import (
    ConfirmPreferencesMixin,
    RequirementConfirmPreference,
)
from .coordinator import AgentChatCoordinator
from .controller import AgentRunCallbacks, AgentRunController
from .execution import AgentCommandExecutor, ThreadedAgentCommandExecutor, _AgentRunHandle
from .history import AgentChatHistory
from .history_view import HistoryView
from .history_utils import (
    clone_streamed_tool_results,
    history_json_safe,
    looks_like_tool_payload,
    stringify_payload,
)
from .paths import (
    _normalize_history_path,
    history_path_for_documents,
    settings_path_for_documents,
)
from .project_settings import (
    AgentProjectSettings,
    load_agent_project_settings,
    save_agent_project_settings,
)
from .layout import AgentChatLayoutBuilder
from .session import AgentChatSession
from .settings_dialog import AgentProjectSettingsDialog
from .time_formatting import format_last_activity
from .token_usage import (
    ContextTokenBreakdown,
    TOKEN_UNAVAILABLE_LABEL,
    format_token_quantity,
)
from .tool_summaries import (
    render_tool_summaries_plain,
    summarize_tool_results,
)
from .transcript_view import TranscriptView


logger = logging.getLogger("cookareq.ui.agent_chat_panel")


try:  # pragma: no cover - import only used for typing
    from ..agent import LocalAgent  # noqa: TCH004
except Exception:  # pragma: no cover - fallback when wx stubs are used
    LocalAgent = object  # type: ignore[assignment]

STATUS_HELP_TEXT = _(
    "The waiting status shows three elements:\n"
    "• The timer reports how long the agent has been running in mm:ss and updates every second.\n"
    "• The status text describes whether the agent is still working or has finished.\n"
    "• The spinning indicator on the left stays active while the agent is still working."
)


class _PanelWaitCallbacks(WaitStateCallbacks):
    """Bridge view wait state callbacks back to the panel."""

    def __init__(self, panel: "AgentChatPanel") -> None:
        self._panel = panel

    def on_refresh_layout(self) -> None:
        self._panel._refresh_bottom_panel_layout()

    def on_focus_input(self) -> None:
        self._panel.input.SetFocus()


class AgentChatPanel(ConfirmPreferencesMixin, wx.Panel):
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
        batch_target_provider: Callable[[], Sequence[BatchTarget]] | None = None,
        batch_context_provider: Callable[[int], Sequence[Mapping[str, Any]] | Mapping[str, Any] | None] | None = None,
    ) -> None:
        """Create panel bound to ``agent_supplier``."""

        super().__init__(parent)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        inherit_background(self, parent)
        self._agent_supplier = agent_supplier
        history = AgentChatHistory(
            history_path=history_path,
            on_active_changed=self._on_active_conversation_changed,
        )
        self._session = AgentChatSession(history=history, timer_owner=self)
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
        self._new_chat_btn: wx.Button | None = None
        self._conversation_label: wx.StaticText | None = None
        self._stop_btn: wx.Button | None = None
        self._bottom_panel: wx.Panel | None = None
        self._copy_conversation_btn: wx.Window | None = None
        self._history_view: HistoryView | None = None
        self._transcript_view: TranscriptView | None = None
        self._history_last_sash = 0
        self._vertical_sash_goal: int | None = None
        self._vertical_last_sash = 0
        self._controller: AgentRunController | None = None
        self._coordinator: AgentChatCoordinator | None = None
        self._context_provider = context_provider
        self._batch_target_provider = batch_target_provider
        self._batch_context_provider = batch_context_provider
        self._batch_section: AgentBatchSection | None = None
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
        self._view = AgentChatView(
            self,
            layout_builder=AgentChatLayoutBuilder(self),
            status_help_text=STATUS_HELP_TEXT,
        )
        self._wait_callbacks = _PanelWaitCallbacks(self)
        self._layout = None
        self._system_token_cache: dict[tuple[str | None, tuple[str, ...]], TokenCountResult] = {}
        self._session.events.elapsed.connect(self._on_session_elapsed)
        self._session.events.running_changed.connect(self._on_session_running_changed)
        self._session.events.tokens_changed.connect(self._on_session_tokens_changed)
        self._session.events.history_changed.connect(self._on_session_history_changed)
        self._session.load_history()
        self._build_ui()
        self._initialize_controller()
        self._render_transcript()

    # ------------------------------------------------------------------
    def Destroy(self) -> bool:  # pragma: no cover - exercised via GUI tests
        self._session.shutdown()
        self._cleanup_executor()
        return super().Destroy()

    # ------------------------------------------------------------------
    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            self._cleanup_executor()
        event.Skip()

    # ------------------------------------------------------------------
    def _cleanup_executor(self) -> None:
        coordinator = getattr(self, "_coordinator", None)
        if coordinator is not None:
            coordinator.stop()
        else:
            controller = getattr(self, "_controller", None)
            if controller is not None:
                controller.stop()
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

        changed = self._session.set_history_path(
            path, persist_existing=bool(self.conversations)
        )
        if not changed:
            return
        self._load_history_from_store()
        self._refresh_history_list()
        self._render_transcript()

    def set_history_directory(self, directory: Path | str | None) -> None:
        """Persist chat history inside *directory* when provided."""

        self.set_history_path(history_path_for_documents(directory))
        self.set_project_settings_path(settings_path_for_documents(directory))

    @property
    def history_path(self) -> Path:
        """Return the path of the current chat history file."""

        return self._session.history.path

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

    @property
    def conversations(self) -> list[ChatConversation]:
        """Expose current conversations managed by the history component."""

        return self._session.history.conversations

    @property
    def active_conversation_id(self) -> str | None:
        """Return identifier of the active conversation."""

        return self._session.history.active_id

    @property
    def is_running(self) -> bool:
        """Expose whether the session currently waits for the agent."""

        return self._session.is_running

    @property
    def coordinator(self) -> AgentChatCoordinator | None:
        """Return the coordinator driving backend interactions."""

        return self._coordinator

    def _set_active_conversation_id(self, conversation_id: str | None) -> None:
        """Update active conversation via the history component."""

        self._session.history.set_active_id(conversation_id)

    # ------------------------------------------------------------------
    def _load_history_from_store(self) -> None:
        self._session.load_history()

    def _save_history_to_store(self) -> None:
        self._session.save_history()

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

        state = self._view.build()
        layout = state.layout
        self._layout = layout
        self._vertical_splitter = layout.vertical_splitter
        self._horizontal_splitter = layout.horizontal_splitter
        self._history_panel = layout.history_panel
        self.history_list = layout.history_list
        self._history_view = layout.history_view
        self._new_chat_btn = layout.new_chat_button
        self._conversation_label = layout.conversation_label
        self._copy_conversation_btn = layout.copy_conversation_button
        self._copy_transcript_log_btn = layout.copy_log_button
        self.transcript_panel = layout.transcript_scroller
        self._transcript_sizer = layout.transcript_sizer
        self._transcript_view = layout.transcript_view
        self._bottom_panel = layout.bottom_panel
        self.input = layout.input_control
        self._stop_btn = layout.stop_button
        self._send_btn = layout.send_button
        self._batch_controls = layout.batch_controls
        self.activity = layout.activity_indicator
        self.status_label = layout.status_label
        self._project_settings_button = layout.project_settings_button
        self._confirm_choice = layout.confirm_choice
        self._confirm_choice_entries = layout.confirm_entries
        self._confirm_choice_index = layout.confirm_choice_index

        self._update_confirm_choice_ui(self._confirm_preference)
        self._history_last_sash = self._horizontal_splitter.GetSashPosition()
        self._vertical_last_sash = self._vertical_splitter.GetSashPosition()
        self._update_conversation_header()
        self._refresh_history_list()
        wx.CallAfter(self._adjust_vertical_splitter)
        wx.CallAfter(self._update_project_settings_ui)

    def _initialize_controller(self) -> None:
        callbacks = AgentRunCallbacks(
            ensure_active_conversation=self._ensure_active_conversation,
            get_conversation_by_id=self._get_conversation_by_id,
            conversation_messages=self._conversation_messages,
            conversation_messages_for=self._conversation_messages_for,
            prepare_context_messages=self._prepare_context_messages,
            add_pending_entry=lambda conv, prompt, prompt_at, context: self._add_pending_entry(
                conv,
                prompt,
                prompt_at=prompt_at,
                context_messages=context,
            ),
            is_running=lambda: self._session.is_running,
            persist_history=self._save_history_to_store,
            refresh_history=self._notify_history_changed,
            render_transcript=self._render_transcript,
            set_wait_state=self._set_wait_state,
            confirm_override_kwargs=self._confirm_override_kwargs,
            finalize_prompt=self._finalize_prompt,
            handle_streamed_tool_results=self._handle_streamed_tool_results,
        )
        self._controller = AgentRunController(
            agent_supplier=self._agent_supplier,
            command_executor=self._command_executor,
            token_model_resolver=self._token_model,
            context_provider=self._context_provider,
            callbacks=callbacks,
        )
        self._coordinator = AgentChatCoordinator(
            session=self._session,
            run_controller=self._controller,
            command_executor=self._command_executor,
        )
        if self._layout is not None:
            self._batch_section = AgentBatchSection(
                panel=self,
                controls=self._batch_controls,
                target_provider=self._batch_target_provider,
            )
        else:
            self._batch_section = None

    def _create_batch_conversation(self) -> ChatConversation:
        return self._create_conversation(persist=False)

    def _prepare_batch_conversation(
        self, conversation: ChatConversation, target: BatchTarget
    ) -> None:
        rid = target.rid.strip() if target.rid else ""
        if not rid:
            rid = str(target.requirement_id)
        base_title = _("Batch • {rid}").format(rid=rid)
        conversation.title = base_title
        self._notify_history_changed()

    def _build_batch_context(
        self, target: BatchTarget
    ) -> tuple[dict[str, Any], ...] | None:
        provider = self._batch_context_provider
        if provider is None:
            return None
        try:
            raw = provider(target.requirement_id)
        except Exception:
            logger.exception("Failed to prepare batch context for %s", target.rid)
            raise
        prepared = self._prepare_context_messages(raw)
        return prepared if prepared else None

    def _submit_batch_prompt(
        self,
        prompt: str,
        conversation_id: str,
        context: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
        prompt_at: str | None,
    ) -> None:
        coordinator = self._coordinator
        if coordinator is None:
            return
        coordinator.submit_prompt_with_context(
            prompt,
            conversation_id=conversation_id,
            context_messages=context,
            prompt_at=prompt_at,
        )

    @property
    def history_sash(self) -> int:
        """Return the current width of the history pane."""

        if self._history_view is None:
            return max(self._history_last_sash, 0)
        value = self._history_view.history_sash()
        self._history_last_sash = value
        return value

    def default_history_sash(self) -> int:
        """Return reasonable default sash width for the history pane."""

        if self._history_view is None:
            return max(self._history_last_sash, 0)
        return self._history_view.default_history_sash()

    def apply_history_sash(self, value: int) -> None:
        """Apply a stored history sash if the splitter is available."""

        if self._history_view is None:
            return
        self._history_view.apply_history_sash(value)

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

        if self._history_view is not None:
            self._history_view.on_splitter_size(event)
        else:
            event.Skip()

    def _on_history_sash_changed(self, event: wx.SplitterEvent) -> None:
        """Store user-driven sash updates as the new desired position."""

        if self._history_view is not None:
            self._history_view.on_sash_changed(event)
            self._history_last_sash = self._history_view.history_sash()
        else:
            event.Skip()

    def _on_send(self, _event: wx.Event) -> None:
        """Send prompt to agent."""

        if self._session.is_running:
            return

        text = self.input.GetValue().strip()
        if not text:
            return

        self.input.SetValue("")
        self._submit_prompt(text)

    def _submit_prompt(self, prompt: str, *, prompt_at: str | None = None) -> None:
        """Submit ``prompt`` to the agent pipeline."""

        coordinator = self._coordinator
        if coordinator is None:
            return
        coordinator.submit_prompt(prompt, prompt_at=prompt_at)

    def _on_clear_input(self, _event: wx.Event) -> None:
        """Clear input field and reset selection."""

        self.input.SetValue("")
        self.input.SetFocus()

    def _on_clear_history(self, _event: wx.Event | None = None) -> None:
        """Delete selected conversations from history."""

        self._delete_selected_conversations(require_confirmation=True, rows=None)

    def _delete_history_rows(self, rows: Sequence[int]) -> None:
        self._delete_selected_conversations(require_confirmation=True, rows=rows)

    def _delete_selected_conversations(
        self, *, require_confirmation: bool, rows: Sequence[int] | None
    ) -> None:
        if self._session.is_running:
            return
        if rows is None:
            if self._history_view is None:
                return
            rows = self._history_view.selected_rows()
        rows = sorted({row for row in rows if 0 <= row < len(self.conversations)})
        if not rows:
            return
        conversations = [self.conversations[row] for row in rows]
        if require_confirmation:
            message = self._format_delete_confirmation_message(conversations)
            if not confirm(message):
                return
        self._remove_conversations(conversations)

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
            self.active_conversation_id is not None
            and self.active_conversation_id in ids_to_remove
        )
        view = self._transcript_view
        if view is not None:
            view.forget_conversations(ids_to_remove)
        remaining = [
            conv for conv in self.conversations if conv.conversation_id not in ids_to_remove
        ]
        self._session.history.set_conversations(remaining)
        if self.conversations:
            if self.active_conversation_id not in {
                conv.conversation_id for conv in self.conversations
            }:
                fallback_index = min(indices_to_remove[0], len(self.conversations) - 1)
                self._set_active_conversation_id(
                    self.conversations[fallback_index].conversation_id
                )
        else:
            self._set_active_conversation_id(None)
        self._save_history_to_store()
        self._notify_history_changed()
        if removed_active:
            self.input.SetValue("")
        self.input.SetFocus()

    def _on_stop(self, _event: wx.Event) -> None:
        """Cancel the in-flight agent request, if any."""

        coordinator = self._coordinator
        if coordinator is None:
            return
        if self._batch_section is not None:
            self._batch_section.request_skip_current()
        handle = coordinator.cancel_active_run()
        if handle is None:
            return
        self._finalize_cancelled_run(handle)
        self._set_wait_state(False)
        self._view.update_status_label(_("Generation cancelled"))
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

        if active:
            self._session.begin_run(tokens=tokens)
            return
        self._session.finalize_run(tokens=tokens)

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

    def _on_session_elapsed(self, elapsed: float) -> None:
        """Refresh elapsed time display while waiting for response."""

        if not self._session.is_running:
            return
        self._update_status(elapsed)

    def _on_session_running_changed(self, running: bool) -> None:
        """Synchronize UI with the session running state."""

        if self._layout is None:
            return
        tokens = self._session.tokens
        self._view.set_wait_state(
            running,
            tokens=tokens,
            context_limit=self._context_token_limit(),
            callbacks=self._wait_callbacks,
        )
        self._update_project_settings_ui()
        self._update_history_controls()
        if running:
            self._update_status(0.0)
        if self._batch_section is not None:
            self._batch_section.update_ui()

    def _on_session_tokens_changed(self, _tokens: TokenCountResult) -> None:
        """Update UI whenever the session token accounting changes."""

        if self._layout is None:
            return
        self._update_conversation_header()

    def _on_session_history_changed(self, _history: AgentChatHistory) -> None:
        """React to history changes propagated by the session model."""

        if self._layout is None:
            return
        self._refresh_history_list()
        self._render_transcript()

    def _update_status(self, elapsed: float) -> None:
        """Show formatted timer and prompt size."""

        if self._layout is None:
            return
        self._view.update_wait_status(
            elapsed,
            self._session.tokens,
            self._context_token_limit(),
        )

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

    def _active_context_messages(self) -> tuple[Mapping[str, Any], ...]:
        """Return contextual messages relevant to the current prompt."""

        handle = self._active_handle()
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
        system_key = (model, tuple(part for part in system_parts if part))
        system_tokens = self._system_token_cache.get(system_key)
        if system_tokens is None:
            if system_key[1]:
                system_tokens = combine_token_counts(
                    [count_text_tokens(part, model=model) for part in system_key[1]]
                )
            else:
                system_tokens = TokenCountResult.exact(0, model=model)
            self._system_token_cache[system_key] = system_tokens

        history_counts: list[TokenCountResult] = []
        conversation = self._get_active_conversation()
        pending_entry = None
        handle = self._active_handle()
        if handle is not None:
            pending_entry = handle.pending_entry
        if conversation is not None:
            for entry in conversation.entries:
                if pending_entry is not None and entry is pending_entry:
                    continue
                if entry.prompt:
                    history_counts.append(entry.ensure_prompt_token_usage(model))
                if entry.response:
                    history_counts.append(entry.ensure_response_token_usage(model))
        if history_counts:
            history_tokens = combine_token_counts(history_counts)
        else:
            history_tokens = TokenCountResult.exact(0, model=model)

        context_messages = self._active_context_messages()
        if context_messages:
            cached_entry: ChatEntry | None = None
            if conversation is not None:
                for entry in reversed(conversation.entries):
                    if entry.context_messages == context_messages:
                        cached_entry = entry
                        break
            if cached_entry is not None:
                context_tokens = cached_entry.ensure_context_token_usage(
                    model,
                    messages=context_messages,
                )
            else:
                context_tokens = combine_token_counts(
                    count_context_message_tokens(message, model)
                    for message in context_messages
                )
        else:
            context_tokens = TokenCountResult.exact(0, model=model)

        if handle is not None:
            prompt_tokens = handle.prompt_tokens
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
        tokens_text = format_token_quantity(total_tokens)
        percent_text = self._format_context_percentage(
            total_tokens, self._context_token_limit()
        )

        limit = self._context_token_limit()
        if limit is not None:
            limit_tokens = TokenCountResult.exact(
                limit,
                model=total_tokens.model,
            )
            limit_text = format_token_quantity(limit_tokens)
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
        coordinator = self._coordinator
        if coordinator is not None:
            coordinator.reset_active_handle(handle)
        elapsed = self._session.elapsed
        final_tokens: TokenCountResult | None = None
        tool_results: list[Any] | None = None
        should_render = False
        success = True
        error_text: str | None = None
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
                token_label = format_token_quantity(self._session.tokens)
                if token_label:
                    label = _("Received response in {time} • {tokens}").format(
                        time=time_text,
                        tokens=token_label,
                    )
                else:
                    label = _("Received response in {time}").format(time=time_text)
                self._view.update_status_label(label)

        if isinstance(result, Mapping) and not result.get("ok", False):
            success = False
            error_text = display_text
        batch_section = self._batch_section
        if batch_section is not None:
            batch_section.notify_completion(
                conversation_id=handle.conversation_id,
                success=success,
                error=error_text,
            )

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
    def _conversation_messages(self) -> tuple[dict[str, str], ...]:
        conversation = self._get_active_conversation()
        if conversation is None:
            return ()
        return self._conversation_messages_for(conversation)

    def _conversation_messages_for(
        self, conversation: ChatConversation
    ) -> tuple[dict[str, str], ...]:
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
        return tuple(messages)

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
        self._save_history_to_store()
        self._notify_history_changed()

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
        self._save_history_to_store()
        self._notify_history_changed()

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
        self._save_history_to_store()
        self._notify_history_changed()

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
            batch_section = self._batch_section
            if batch_section is not None:
                batch_section.notify_cancellation(
                    conversation_id=handle.conversation_id
                )
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
        batch_section = self._batch_section
        if batch_section is not None:
            batch_section.notify_cancellation(
                conversation_id=handle.conversation_id
            )

    def _notify_history_changed(self) -> None:
        """Propagate history updates through the session events."""

        self._session.notify_history_changed()

    def _refresh_history_list(self) -> None:
        if self._history_view is None:
            return
        self._history_view.refresh()
        self._update_history_controls()
        view = self._transcript_view
        if view is not None:
            view.sync_known_conversations(
                [conversation.conversation_id for conversation in self.conversations]
            )

    def _render_transcript(self) -> None:
        if self._transcript_view is None:
            return
        self._transcript_view.render()

    def _on_regenerate_entry(
        self,
        conversation_id: str,
        entry: ChatEntry,
    ) -> None:
        if self._session.is_running:
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
        self._save_history_to_store()
        self._notify_history_changed()
        try:
            self._submit_prompt(prompt)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to regenerate agent response")
            entry.regenerated = previous_state
            self._save_history_to_store()
            self._notify_history_changed()

    def _ensure_history_visible(self, index: int) -> None:
        if self._history_view is None:
            return
        self._history_view.ensure_visible(index)

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
        if handle is not self._active_handle():
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
                if stripped.startswith(("{", "[")):
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
        button.Enable(not self._session.is_running)

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
        active_id = self.active_conversation_id
        if active_id is None:
            return None
        for idx, conversation in enumerate(self.conversations):
            if conversation.conversation_id == active_id:
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
        self._set_active_conversation_id(conversation.conversation_id)
        self._notify_history_changed()
        if persist:
            self._save_history_to_store()
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

    def _on_history_row_activated(self, index: int) -> None:
        self._activate_conversation_by_index(
            index, persist=True, refresh_history=False, source="history_row"
        )

    def _activate_conversation_by_index(
        self,
        index: int,
        *,
        persist: bool = True,
        refresh_history: bool = True,
        _source: str = "unknown",
    ) -> None:
        if not (0 <= index < len(self.conversations)):
            return
        conversation = self.conversations[index]
        self._set_active_conversation_id(conversation.conversation_id)
        if persist:
            self._session.history.persist_active_selection()
        if refresh_history:
            self._refresh_history_list()
        else:
            self._update_history_controls()
        self._ensure_history_visible(index)
        self._render_transcript()

        input_ctrl = getattr(self, "input", None)
        if input_ctrl is None:
            return
        try:
            if not input_ctrl or input_ctrl.IsBeingDeleted():
                return
        except RuntimeError:
            return
        input_ctrl.SetFocus()

    def _update_history_controls(self) -> None:
        has_conversations = bool(self.conversations)
        self.history_list.Enable(has_conversations and not self._session.is_running)
        if self._new_chat_btn is not None:
            self._new_chat_btn.Enable(not self._session.is_running)

    def _on_new_chat(self, _event: wx.Event) -> None:
        if self._session.is_running:
            return
        self._create_conversation(persist=True)
        self.input.SetValue("")
        self.input.SetFocus()

    def _handle_regenerate_request(
        self, conversation_id: str, entry: ChatEntry
    ) -> None:
        coordinator = self._coordinator
        if coordinator is None:
            return
        coordinator.regenerate_entry(conversation_id, entry)

    def _active_handle(self) -> _AgentRunHandle | None:
        coordinator = self._coordinator
        if coordinator is None:
            return None
        return coordinator.active_handle

    @property
    def history(self) -> list[ChatEntry]:
        conversation = self._get_active_conversation()
        if conversation is None:
            return []
        return list(conversation.entries)

