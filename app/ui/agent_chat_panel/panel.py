"""Panel providing conversational interface to the local agent."""
from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Deque
from contextlib import suppress
from pathlib import Path
from typing import Any

from dataclasses import dataclass

from concurrent.futures import ThreadPoolExecutor

import wx

from ...agent.run_contract import (
    AgentEvent,
    AgentEventLog,
    AgentRunPayload,
    AgentTimelineEntry,
    LlmStep,
    LlmTrace,
    ToolResultSnapshot,
    ToolError,
)

from ...confirm import confirm
from ...i18n import _
from ...llm.spec import SYSTEM_PROMPT
from ...llm.tokenizer import TokenCountResult, combine_token_counts, count_text_tokens
from ...mcp.paths import normalize_documents_path, resolve_documents_root
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
from .attachment_utils import looks_like_plain_text
from .batch_runner import BatchTarget
from .batch_ui import AgentBatchSection
from .components.view import AgentChatView, WaitStateCallbacks
from .confirm_preferences import (
    ConfirmPreferencesMixin,
    RequirementConfirmPreference,
)
from .coordinator import AgentChatCoordinator
from .controller import AgentRunCallbacks, AgentRunController, RemovedConversationEntry
from .execution import (
    AgentCommandExecutor,
    ThreadedAgentCommandExecutor,
    _AgentRunHandle,
)
from .history import AgentChatHistory
from .history_view import HistoryView
from .history_utils import (
    ensure_canonical_agent_payload,
    agent_payload_from_mapping,
    history_json_safe,
    stringify_payload,
    tool_messages_from_snapshots,
    tool_snapshot_dicts,
    tool_snapshots_from,
)
from .log_export import (
    compose_transcript_log_text,
    compose_transcript_text,
    write_event_log_debug,
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
from .layout_builder import AgentChatPanelLayoutBuilder
from .session import AgentChatSession
from .session_controller import SessionConfig, SessionController
from .history_sync import HistorySynchronizer
from .settings_dialog import AgentProjectSettingsDialog
from .time_formatting import format_last_activity
from .token_usage import (
    ContextTokenBreakdown,
    TOKEN_UNAVAILABLE_LABEL,
    format_token_quantity,
)
from .view_model import (
    ConversationTimeline,
    ConversationTimelineCache,
    _build_llm_trace_from_diagnostic,
    _build_timestamp,
)
from .segment_view import SegmentListView


logger = logging.getLogger("cookareq.ui.agent_chat_panel")


try:  # pragma: no cover - import only used for typing
    from ..agent import LocalAgent  # noqa: TCH004
except Exception:  # pragma: no cover - fallback when wx stubs are used
    LocalAgent = object  # type: ignore[assignment]

STATUS_HELP_TEXT = _(
    "The waiting status shows three elements:\n"
    "• The timer reports how long the agent has been running in mm:ss "
    "and updates every second.\n"
    "• The status text describes whether the agent is still working or has "
    "finished.\n"
    "• The spinning indicator on the left stays active while the agent is "
    "still working."
)


MAX_ATTACHMENT_BYTES = 1024 * 1024


_REQUIREMENT_EDITING_TOOLS: frozenset[str] = frozenset(
    {
        "create_requirement",
        "update_requirement_field",
        "set_requirement_labels",
        "set_requirement_attachments",
        "set_requirement_links",
        "delete_requirement",
        "link_requirements",
    }
)


class AttachmentValidationError(Exception):
    """Raised when a selected attachment fails validation."""


@dataclass(slots=True)
class _PendingAttachment:
    """Container storing in-memory copy of a pending attachment."""

    filename: str
    content: str
    size_bytes: int
    message_content: str
    token_info: TokenCountResult
    preview_lines: tuple[str, ...]

    def to_context_message(self) -> dict[str, Any]:
        return {
            "role": "user",
            "content": self.message_content,
            "metadata": {
                "attachment": {
                    "filename": self.filename,
                    "size_bytes": self.size_bytes,
                    "token_info": self.token_info.to_dict(),
                    "preview_lines": list(self.preview_lines),
                }
            },
        }


@dataclass(slots=True)
class _QueuedPrompt:
    """Message queued while the agent finishes the current turn."""

    conversation_id: str
    prompt: str
    prompt_at: str
    queued_at: str


class _PanelWaitCallbacks(WaitStateCallbacks):
    """Bridge view wait state callbacks back to the panel."""

    def __init__(self, panel: AgentChatPanel) -> None:
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
        documents_subdirectory: str | None = "share",
        command_executor: AgentCommandExecutor | None = None,
        token_model_resolver: Callable[[], str | None] | None = None,
        context_provider: Callable[
            [], Mapping[str, Any] | Sequence[Mapping[str, Any]] | None
        ] | None = None,
        context_window_resolver: Callable[[], int | None] | None = None,
        confirm_preference: RequirementConfirmPreference | str | None = None,
        persist_confirm_preference: Callable[[str], None] | None = None,
        batch_target_provider: Callable[[], Sequence[BatchTarget]] | None = None,
        batch_context_provider: Callable[
            [int], Sequence[Mapping[str, Any]] | Mapping[str, Any] | None
        ] | None = None,
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
        self._session = AgentChatSession(
            history=history,
            timer_owner=self,
            monotonic=lambda: time.monotonic(),
        )
        self._settings_path = settings_path_for_documents(None)
        self._documents_root_listener: Callable[[Path | None], None] | None = None
        self._requirements_directory: Path | None = None
        self._documents_root: Path | None = None
        self._default_documents_subdirectory = normalize_documents_path(
            documents_subdirectory
        )
        self._project_documents_subdirectory = ""
        self._project_settings = AgentProjectSettings()
        self._load_project_settings()
        self._token_model_resolver = (
            token_model_resolver if token_model_resolver is not None else lambda: None
        )
        self._context_window_resolver = (
            context_window_resolver
            if context_window_resolver is not None
            else (lambda: None)
        )
        self._executor_pool: ThreadPoolExecutor | None = None
        self._last_batch_conversation_id: str | None = None
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
        self._primary_action_btn: wx.Button | None = None
        self._bottom_panel: wx.Panel | None = None
        self._bottom_controls_panel: wx.Panel | None = None
        self._copy_conversation_btn: wx.Window | None = None
        self._history_view: HistoryView | None = None
        self._transcript_view: SegmentListView | None = None
        self._attachment_button: wx.Button | None = None
        self._attachment_summary: wx.StaticText | None = None
        self._clear_input_button: wx.Button | None = None
        self._run_batch_button: wx.Button | None = None
        self._stop_batch_button: wx.Button | None = None
        self._bottom_controls_wrap: wx.WrapSizer | None = None
        self._confirm_label: wx.StaticText | None = None
        self._timeline_cache = ConversationTimelineCache()
        self._pending_transcript_refresh: dict[str | None, set[str] | None] = {}
        self._transcript_refresh_scheduled = False
        self._latest_timeline: ConversationTimeline | None = None
        self._last_rendered_conversation_id: str | None = None
        self._history_last_sash = 0
        self._history_column_widths: tuple[int, ...] = ()
        self._history_column_refresh_scheduled = False
        self._vertical_sash_goal: int | None = None
        self._vertical_last_sash = 0
        self._controller: AgentRunController | None = None
        self._coordinator: AgentChatCoordinator | None = None
        self._context_provider = context_provider
        self._batch_target_provider = batch_target_provider
        self._batch_context_provider = batch_context_provider
        self._batch_attachment: _PendingAttachment | None = None
        self._batch_section: AgentBatchSection | None = None
        self._batch_conversation_ids: set[str] = set()
        self._persist_confirm_preference_callback = persist_confirm_preference
        self._layout_manager = AgentChatPanelLayoutBuilder(self)
        self._session_controller = SessionController(
            config=SessionConfig(
                token_model_resolver=self._token_model_resolver,
                context_window_resolver=self._context_window_resolver,
            )
        )
        self._session_controller.set_token_counter(
            lambda text, model=None: count_text_tokens(text, model=model)
        )
        self._history_sync = HistorySynchronizer(
            session=self._session,
            timeline_cache=self._timeline_cache,
            scheduler=wx.CallAfter,
        )
        persistent_preference = self._normalize_confirm_preference(confirm_preference)
        if persistent_preference is RequirementConfirmPreference.CHAT_ONLY:
            persistent_preference = RequirementConfirmPreference.PROMPT
        self._persistent_confirm_preference = persistent_preference
        self._pending_attachment: _PendingAttachment | None = None
        self._prompt_queue: Deque[_QueuedPrompt] = deque()
        self._queued_prompt_panel: wx.Panel | None = None
        self._queued_prompt_label: wx.StaticText | None = None
        self._queued_prompt_cancel: wx.Button | None = None
        self._tool_first_seen: dict[str, str] = {}
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
        self._pending_session_running: bool | None = None
        self._system_token_cache: dict[
            tuple[str | None, tuple[str, ...]], TokenCountResult
        ] = {}
        self._session.events.elapsed.connect(self._on_session_elapsed)
        self._bottom_layout_refresh_scheduled = False
        self._bottom_controls_last_size: wx.Size | None = None
        self._session.events.running_changed.connect(self._on_session_running_changed)
        self._session.events.tokens_changed.connect(self._on_session_tokens_changed)
        self._session.events.history_changed.connect(self._on_session_history_changed)
        self._initialize_history_state()
        self._build_ui()
        self._refresh_history_list()
        self._history_column_widths = tuple(
            getattr(self._layout_manager, "history_column_widths", lambda: ())()
        )
        self._initialize_controller()
        self._render_transcript()

    # ------------------------------------------------------------------
    def Destroy(self) -> bool:  # pragma: no cover - exercised via GUI tests
        """Stop background activity before delegating to the base destroyer."""
        self._history_sync.stop()
        self._session.shutdown()
        self._cleanup_executor()
        return super().Destroy()

    # ------------------------------------------------------------------
    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            self._layout_manager.cleanup()
            self._cleanup_executor()
        event.Skip()

    # ------------------------------------------------------------------
    def _cleanup_executor(self) -> None:
        coordinator = getattr(self, "_coordinator", None)
        if coordinator is not None:
            stop = getattr(coordinator, "stop", None)
            if callable(stop):
                stop()
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
        changed = self._history_sync.set_history_path(
            path, persist_existing=bool(self.conversations)
        )
        if not changed:
            return
        self._initialize_history_state()
        self._refresh_history_list()
        self._render_transcript()

    def set_history_directory(self, directory: Path | str | None) -> None:
        """Persist chat history inside *directory* when provided."""
        self._requirements_directory = (
            None if directory is None else _normalize_history_path(directory)
        )
        self.set_history_path(history_path_for_documents(directory))
        self.set_project_settings_path(settings_path_for_documents(directory))
        self._update_documents_root()
        self._update_project_settings_ui()

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
    def documents_root(self) -> Path | None:
        """Return the resolved documentation root directory if configured."""
        return self._documents_root

    @property
    def documents_subdirectory(self) -> str:
        """Return the configured documentation subdirectory relative to requirements."""
        project = getattr(self, "_project_documents_subdirectory", "")
        if project:
            return project
        return getattr(self, "_default_documents_subdirectory", "")

    def set_documents_subdirectory(self, value: str | None) -> None:
        """Update documentation subdirectory and notify listeners if it changes."""
        normalized = normalize_documents_path(value)
        previous_effective = self.documents_subdirectory
        if normalized == getattr(self, "_default_documents_subdirectory", ""):
            return
        self._default_documents_subdirectory = normalized
        if previous_effective != self.documents_subdirectory:
            self._update_documents_root()
        self._update_project_settings_ui()

    def _set_project_documents_subdirectory(
        self, value: str | None, *, update_ui: bool = True
    ) -> None:
        normalized = normalize_documents_path(value)
        if normalized == getattr(self, "_project_documents_subdirectory", ""):
            return
        self._project_documents_subdirectory = normalized
        self._update_documents_root()
        if update_ui:
            self._update_project_settings_ui()

    def set_documents_root_listener(
        self, callback: Callable[[Path | None], None] | None
    ) -> None:
        """Register *callback* to receive documentation root updates."""
        self._documents_root_listener = callback
        self._notify_documents_root_listener()

    @property
    def conversations(self) -> list[ChatConversation]:
        """Expose current conversations managed by the history component."""
        return self._session.history.conversations

    def _mark_conversation_dirty(self, conversation: ChatConversation | None) -> None:
        """Tell the history manager that *conversation* changed."""
        self._session.history.mark_conversation_dirty(conversation)

    def _register_conversation(self, conversation: ChatConversation) -> None:
        """Append *conversation* to the list and flag it for persistence."""
        self.conversations.append(conversation)
        self._mark_conversation_dirty(conversation)

    @property
    def active_conversation_id(self) -> str | None:
        """Return identifier of the active conversation."""
        return self._session.history.active_id

    @property
    def is_running(self) -> bool:
        """Expose whether the session currently waits for the agent."""
        return self._session.is_running

    @property
    def tokens(self) -> TokenCountResult:
        """Expose the latest token accounting snapshot."""
        return self._session.tokens

    @property
    def coordinator(self) -> AgentChatCoordinator | None:
        """Return the coordinator driving backend interactions."""
        return self._coordinator

    def _set_active_conversation_id(self, conversation_id: str | None) -> None:
        """Update active conversation via the history component."""
        self._session.history.set_active_id(conversation_id)

    # ------------------------------------------------------------------
    def _initialize_history_state(self) -> None:
        """Load history immediately and ensure a fresh draft conversation."""
        self._history_sync.initialize()
        self._timeline_cache = self._history_sync.timeline_cache
        self._pending_transcript_refresh.clear()
        self._latest_timeline = None
        self._notify_history_changed()
        self._schedule_lazy_history_cleanup()

    def _schedule_lazy_history_cleanup(self) -> None:
        self._history_sync.schedule_lazy_history_cleanup()

    def _save_history_to_store(self) -> None:
        self._session.save_history()

    # ------------------------------------------------------------------
    def _token_model(self) -> str | None:
        """Return configured model name for token accounting."""
        return self._session_controller.token_model()

    def _normalize_confirm_preference(
        self, value: RequirementConfirmPreference | str | None
    ) -> RequirementConfirmPreference:
        return self._session_controller.normalize_confirm_preference(value)

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    def focus_input(self) -> None:
        """Give keyboard focus to the input control."""
        self.input.SetFocus()

    # ------------------------------------------------------------------
    def _on_active_conversation_changed(
        self,
        previous_id: str | None,
        new_id: str | None,
    ) -> None:
        super()._on_active_conversation_changed(previous_id, new_id)
        if previous_id != new_id:
            self._last_rendered_conversation_id = None

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """Construct controls and layout."""
        state = self._layout_manager.build()
        self._layout = state.layout
        self.SetSizer(state.layout_root)
        self.Layout()

    def _apply_pending_session_running_state(self) -> None:
        """Replay pending session running state once the layout is ready."""
        pending = self._pending_session_running
        self._pending_session_running = None
        if pending is not None:
            self._on_session_running_changed(pending)
            return
        if self._session.is_running:
            self._on_session_running_changed(True)

    def _initialize_controller(self) -> None:
        def add_pending(
            conv: ChatConversation,
            prompt_text: str,
            prompt_at,
            context_messages,
        ) -> ChatEntry:
            return self._add_pending_entry(
                conv,
                prompt_text,
                prompt_at=prompt_at,
                context_messages=context_messages,
            )

        callbacks = AgentRunCallbacks(
            ensure_active_conversation=self._ensure_active_conversation,
            get_conversation_by_id=self._get_conversation_by_id,
            conversation_messages=self._conversation_messages,
            conversation_messages_for=self._conversation_messages_for,
            prepare_context_messages=self._prepare_context_messages,
            add_pending_entry=add_pending,
            remove_entry=self._remove_conversation_entry,
            restore_entry=self._restore_conversation_entry,
            is_running=lambda: self._session.is_running,
            persist_history=self._save_history_to_store,
            refresh_history=self._notify_history_changed,
            render_transcript=self._render_transcript,
            set_wait_state=self._set_wait_state,
            confirm_override_kwargs=self._confirm_override_kwargs,
            finalize_prompt=self._finalize_prompt,
            handle_streamed_tool_results=self._handle_streamed_tool_results,
            handle_llm_step=self._handle_llm_step,
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
        active_id = self.active_conversation_id
        last_batch_id = self._last_batch_conversation_id
        if last_batch_id is not None and not any(
            conversation.conversation_id == last_batch_id
            for conversation in self.conversations
        ):
            last_batch_id = None
            self._last_batch_conversation_id = None

        conversation = ChatConversation.new()
        self._register_conversation(conversation)

        should_activate = (
            active_id is None
            or not self._batch_conversation_ids
            or active_id in self._batch_conversation_ids
        )

        if should_activate:
            self._set_active_conversation_id(conversation.conversation_id)

        self._batch_conversation_ids.add(conversation.conversation_id)

        self._last_batch_conversation_id = conversation.conversation_id
        self._notify_history_changed()
        return conversation

    def _reset_batch_conversation_tracking(self) -> None:
        self._last_batch_conversation_id = None
        self._batch_conversation_ids.clear()

    def _prepare_batch_attachment(self) -> None:
        """Snapshot the current attachment for reuse across a batch run."""

        self._batch_attachment = self._pending_attachment

    def _clear_batch_attachment(self) -> None:
        """Release any batch-scoped attachment once processing finishes."""

        batch_attachment = self._batch_attachment
        self._batch_attachment = None
        if batch_attachment is not None and self._pending_attachment is batch_attachment:
            self._clear_pending_attachment()

    def _prepare_batch_conversation(
        self, conversation: ChatConversation, target: BatchTarget
    ) -> None:
        rid = target.rid.strip() if target.rid else ""
        if not rid:
            rid = str(target.requirement_id)
        base_title = _("Batch • {rid}").format(rid=rid)
        conversation.title = base_title
        self._mark_conversation_dirty(conversation)
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
        prepared = self._prepare_context_messages(
            raw,
            consume_pending=False,
            attachment_override=self._batch_attachment,
        )
        return prepared if prepared else None

    def _count_conversation_errors(self, conversation: ChatConversation) -> int:
        """Return number of error entries recorded in ``conversation``."""

        try:
            conversation.ensure_entries_loaded()
        except Exception:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to load entries for conversation %s",
                conversation.conversation_id,
            )
            return 0

        return sum(1 for entry in conversation.entries if self._entry_has_error(entry))

    @staticmethod
    def _entry_has_error(entry: ChatEntry) -> bool:
        raw_result = entry.raw_result
        if isinstance(raw_result, Mapping):
            if raw_result.get("ok") is False:
                return True
            status_value = raw_result.get("status")
            if isinstance(status_value, str) and status_value.strip().lower() == "failed":
                return True
            if raw_result.get("error"):
                return True

        diagnostic = entry.diagnostic
        if isinstance(diagnostic, Mapping) and diagnostic.get("error"):
            return True

        return False

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
            prepared_context=True,
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

    def _on_input_key_down(self, event: wx.KeyEvent) -> None:
        """Submit the prompt when Ctrl+Enter (or Cmd+Enter) is pressed."""
        key_code = event.GetKeyCode()
        if key_code not in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            event.Skip()
            return

        if event.ControlDown() or event.CmdDown():
            self._on_send(event)
            return

        event.Skip()

    def _on_send(self, _event: wx.Event) -> None:
        """Send prompt to agent."""
        text = self.input.GetValue().strip()
        if not text:
            return
        prompt_at = utc_now_iso()
        conversation = self._ensure_active_conversation()
        self.input.SetValue("")
        if self._session.is_running:
            self._queue_prompt(conversation, text, prompt_at=prompt_at)
            return
        self._submit_prompt(text, prompt_at=prompt_at)

    def _on_primary_action(self, event: wx.Event) -> None:
        """Dispatch the main action button based on session state."""
        if self._session.is_running:
            self._on_stop(event)
            return
        self._on_send(event)

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
        self._clear_pending_attachment()

    def _on_select_attachment(self, _event: wx.Event) -> None:
        """Select a text attachment and keep its copy in memory."""
        if self._session.is_running:
            return
        with wx.FileDialog(
            self,
            message=_("Select file to attach"),
            wildcard=_("All files|*.*|Text files (*.txt)|*.txt"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            selected = Path(dialog.GetPath())
        try:
            attachment = self._load_attachment(selected)
        except AttachmentValidationError as exc:
            wx.MessageBox(
                str(exc),
                _("Attachment error"),
                style=wx.OK | wx.ICON_ERROR,
                parent=self,
            )
            return
        except Exception as exc:
            wx.MessageBox(
                _("Failed to attach file {path}: {error}").format(
                    path=str(selected), error=str(exc)
                ),
                _("Attachment error"),
                style=wx.OK | wx.ICON_ERROR,
                parent=self,
            )
            return

        self._pending_attachment = attachment
        self._update_attachment_summary()

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
        for conversation in conversations:
            self._timeline_cache.forget(conversation.conversation_id)
        remaining = [
            conv
            for conv in self.conversations
            if conv.conversation_id not in ids_to_remove
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

    def cancel_agent_run(self) -> _AgentRunHandle | None:
        """Abort the current agent run and reconcile the transcript."""
        coordinator = self._coordinator
        if coordinator is None:
            return None
        handle = coordinator.cancel_active_run()
        if handle is None:
            return None
        self._set_wait_state(False)
        self._finalize_cancelled_run(handle)
        return handle

    def _on_stop(self, _event: wx.Event) -> None:
        """Cancel the in-flight agent request, if any."""
        if self._batch_section is not None:
            self._batch_section.request_skip_current()
        handle = self.cancel_agent_run()
        if handle is None:
            return
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

    def _on_bottom_controls_size(self, event: wx.SizeEvent) -> None:
        """Schedule a relayout when the controls container changes size."""
        event.Skip()
        size = event.GetSize()
        previous = self._bottom_controls_last_size
        if previous is not None and previous == size:
            return
        self._bottom_controls_last_size = size
        if self._bottom_layout_refresh_scheduled:
            return
        self._bottom_layout_refresh_scheduled = True
        wx.CallAfter(self._flush_bottom_controls_layout)

    def _flush_bottom_controls_layout(self) -> None:
        """Finalize pending relayout triggered by a size change."""
        self._bottom_layout_refresh_scheduled = False
        if self._bottom_panel is None or not self._bottom_panel:
            return
        self._refresh_bottom_panel_layout()

    # ------------------------------------------------------------------
    def _clear_pending_attachment(self) -> None:
        """Remove the currently selected attachment."""
        if self._pending_attachment is None:
            return
        self._pending_attachment = None
        self._update_attachment_summary()

    @staticmethod
    def _build_attachment_message_content(filename: str, content: str) -> str:
        header = f"[Attachment: {filename}]"
        if content:
            return f"{header}\n{content}"
        return header

    @staticmethod
    def _build_attachment_preview(
        content: str, *, max_lines: int = 3, max_length: int = 400
    ) -> tuple[str, ...]:
        """Return a trimmed preview for attachment metadata."""
        if not content:
            return ()
        lines = content.splitlines()
        limited_lines = lines[:max_lines]
        preview_text = "\n".join(limited_lines)[:max_length]
        return tuple(preview_text.splitlines())

    def _load_attachment(self, path: Path) -> _PendingAttachment:
        resolved = path.expanduser()
        text, size_bytes = self._read_attachment_text(resolved)
        message_content = self._build_attachment_message_content(resolved.name, text)
        token_info = count_text_tokens(message_content, model=self._token_model())
        preview_lines = self._build_attachment_preview(text)
        return _PendingAttachment(
            filename=resolved.name,
            content=text,
            size_bytes=size_bytes,
            message_content=message_content,
            token_info=token_info,
            preview_lines=preview_lines,
        )

    def _read_attachment_text(self, resolved: Path) -> tuple[str, int]:
        limit = MAX_ATTACHMENT_BYTES

        try:
            stat_size = resolved.stat().st_size
        except OSError:
            stat_size = None

        if stat_size is not None and stat_size > limit:
            raise AttachmentValidationError(
                _(
                    "The selected file {path} exceeds the maximum attachment "
                    "size of 1 MB."
                ).format(path=str(resolved))
            )

        try:
            raw_bytes = resolved.read_bytes()
        except OSError:
            raise

        actual_size = len(raw_bytes)
        if actual_size > limit:
            raise AttachmentValidationError(
                _(
                    "The selected file {path} exceeds the maximum attachment "
                    "size of 1 MB."
                ).format(path=str(resolved))
            )

        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AttachmentValidationError(
                _(
                    "Unable to read {path} as UTF-8 text. Only UTF-8 encoded "
                    "text files are supported."
                ).format(path=str(resolved))
            ) from exc

        if not looks_like_plain_text(text):
            raise AttachmentValidationError(
                _(
                    "The selected file {path} does not appear to be plain text. "
                    "Please choose a UTF-8 text document."
                ).format(path=str(resolved))
            )

        size_bytes = stat_size if stat_size is not None else actual_size
        return text, size_bytes

    def _update_attachment_summary(self) -> None:
        """Refresh the UI label describing the pending attachment."""
        label = self._attachment_summary
        if label is None:
            return
        attachment = self._pending_attachment
        if attachment is None:
            label.SetLabel(_("No file attached"))
            self._set_tooltip(label, None)
        else:
            compact, tooltip = self._build_attachment_summary_texts(attachment)
            label.SetLabel(compact)
            self._set_tooltip(label, tooltip)
        label.InvalidateBestSize()
        self._refresh_bottom_panel_layout()

    def _build_attachment_summary_texts(
        self, attachment: _PendingAttachment
    ) -> tuple[str, str]:
        """Return compact label and tooltip for an attachment summary."""
        short_name = self._shorten_filename(attachment.filename)
        size_compact, size_full = self._format_attachment_size(attachment.size_bytes)
        tokens_compact = self._format_compact_token_quantity(attachment.token_info)
        tokens_full = format_token_quantity(attachment.token_info)
        usage_full = self._format_context_percentage(
            attachment.token_info, self._context_token_limit()
        )
        usage_compact = self._strip_approximate_prefix(usage_full)
        compact_label = _("{name} • {size}/{tokens}/{usage}").format(
            name=short_name,
            size=size_compact,
            tokens=tokens_compact,
            usage=usage_compact,
        )
        tooltip = _(
            "Attachment: {name}\n"
            "Size: {size}\n"
            "Tokens: {tokens}\n"
            "Context window: {usage}"
        ).format(
            name=attachment.filename,
            size=size_full,
            tokens=tokens_full,
            usage=usage_full,
        )
        return compact_label, tooltip

    @staticmethod
    def _strip_approximate_prefix(value: str) -> str:
        """Remove leading approximation markers used in compact stats."""
        if value.startswith("~"):
            return value[1:]
        if value.startswith("≈"):
            return value[1:]
        return value

    def _format_compact_token_quantity(
        self, tokens: TokenCountResult
    ) -> str:
        """Return condensed token counter label for inline attachment stats."""
        if tokens.tokens is None:
            return TOKEN_UNAVAILABLE_LABEL
        quantity = tokens.tokens / 1000 if tokens.tokens else 0.0
        if quantity >= 100:
            formatted = f"{quantity:.0f}"
        elif quantity >= 10:
            formatted = f"{quantity:.1f}"
        else:
            formatted = f"{quantity:.2f}"
        unit = _("kTok")
        return f"{formatted}{unit}"

    def _format_attachment_size(self, size_bytes: int) -> tuple[str, str]:
        """Return compact and full textual representations of attachment size."""
        kb_value = size_bytes / 1024 if size_bytes > 0 else 0.0
        if kb_value >= 100:
            formatted = f"{kb_value:.0f}"
        elif kb_value >= 10:
            formatted = f"{kb_value:.1f}"
        else:
            formatted = f"{kb_value:.2f}"
        compact = _("{size}KB").format(size=formatted)
        detailed = _("{size} KB").format(size=formatted)
        return compact, detailed

    @staticmethod
    def _set_tooltip(control: wx.Window, tip: str | None) -> None:
        """Attach or clear a tooltip on ``control``."""
        if not tip:
            unset = getattr(control, "UnsetToolTip", None)
            if callable(unset):
                unset()
            else:  # pragma: no cover - compatibility path
                control.SetToolTip(None)
            return
        control.SetToolTip(tip)

    @staticmethod
    def _shorten_filename(name: str, limit: int = 48) -> str:
        if len(name) <= limit:
            return name
        if limit <= 3:
            return name[:limit]
        head = max(1, (limit - 1) // 2)
        tail = max(1, limit - head - 1)
        return f"{name[:head]}…{name[-tail:]}"

    def _queue_prompt(
        self,
        conversation: ChatConversation,
        prompt: str,
        *,
        prompt_at: str,
    ) -> None:
        """Store ``prompt`` so it runs after the active agent turn finishes."""
        queued_entry = _QueuedPrompt(
            conversation_id=conversation.conversation_id,
            prompt=prompt,
            prompt_at=prompt_at,
            queued_at=utc_now_iso(),
        )
        self._prompt_queue.append(queued_entry)
        self._update_queued_prompt_banner()
        self._refresh_bottom_panel_layout()
        self._view.update_status_label(
            _("Message queued — it will run after the current response."),
        )

    def _format_queued_preview(self, prompt: str, limit: int = 120) -> str:
        """Return compact single-line preview for a queued prompt."""
        if not prompt:
            return _("(empty message)")
        normalised = normalize_for_display(prompt)
        collapsed = " ".join(normalised.split())
        if len(collapsed) <= limit:
            return collapsed
        return f"{collapsed[: limit - 1]}…"

    def _queued_conversation_label(self, conversation_id: str) -> str:
        """Return human-friendly label for queued prompt destination."""
        conversation = self._get_conversation_by_id(conversation_id)
        if conversation is None:
            return _("Archived chat")
        self._session.history.ensure_conversation_entries(conversation)
        title, _last_activity = self._format_conversation_row(conversation)
        return title

    def _update_queued_prompt_banner(self) -> None:
        """Refresh the queued prompt summary shown above controls."""
        panel = self._queued_prompt_panel
        label = self._queued_prompt_label
        cancel = self._queued_prompt_cancel
        if panel is None or label is None:
            return

        # Drop entries for conversations that no longer exist.
        while self._prompt_queue:
            candidate = self._prompt_queue[0]
            if self._get_conversation_by_id(candidate.conversation_id) is None:
                self._prompt_queue.popleft()
            else:
                break

        if not self._prompt_queue:
            label.SetLabel("")
            self._set_tooltip(label, None)
            if cancel is not None:
                cancel.Enable(False)
            if panel.IsShown():
                panel.Hide()
                self._refresh_bottom_panel_layout()
            return

        entry = self._prompt_queue[0]
        conversation_name = self._queued_conversation_label(entry.conversation_id)
        preview = self._format_queued_preview(entry.prompt)
        remaining = len(self._prompt_queue) - 1
        if remaining > 0:
            label_text = _("Next for {chat}: {prompt} (+{count} more)").format(
                chat=conversation_name,
                prompt=preview,
                count=remaining,
            )
        else:
            label_text = _("Next for {chat}: {prompt}").format(
                chat=conversation_name,
                prompt=preview,
            )
        label.SetLabel(label_text)
        tooltip = _(
            "Queued at {time} for chat {chat}:\n{prompt}",
        ).format(time=entry.queued_at, chat=conversation_name, prompt=entry.prompt)
        self._set_tooltip(label, tooltip)
        if cancel is not None:
            cancel.Enable(True)
        if not panel.IsShown():
            panel.Show()
            self._refresh_bottom_panel_layout()
        else:
            panel.GetParent().Layout()

    def _schedule_prompt_queue_flush(self) -> None:
        """Process the next queued message when the agent becomes idle."""
        if not self._prompt_queue:
            return
        wx.CallAfter(self._process_next_queued_prompt)

    def _process_next_queued_prompt(self) -> None:
        """Submit the next queued prompt if the agent is idle."""
        if self._session.is_running:
            return
        while self._prompt_queue:
            entry = self._prompt_queue.popleft()
            conversation = self._get_conversation_by_id(entry.conversation_id)
            if conversation is None:
                continue
            coordinator = self._coordinator
            if coordinator is None:
                self._prompt_queue.appendleft(entry)
                break
            self._set_active_conversation_id(conversation.conversation_id)
            self._view.update_status_label(
                _("Sending queued message for {chat}…").format(
                    chat=self._queued_conversation_label(conversation.conversation_id),
                )
            )
            coordinator.submit_prompt(entry.prompt, prompt_at=entry.prompt_at)
            break
        self._update_queued_prompt_banner()
        self._refresh_bottom_panel_layout()

    def _on_cancel_queued_prompt(self, _event: wx.Event | None = None) -> None:
        """Remove the oldest queued prompt before it reaches the agent."""
        if not self._prompt_queue:
            return
        self._prompt_queue.popleft()
        self._view.update_status_label(_("Queued message removed."))
        self._update_queued_prompt_banner()
        self._refresh_bottom_panel_layout()

    # ------------------------------------------------------------------
    def _set_wait_state(
        self,
        active: bool,
        tokens: TokenCountResult | None = None,
    ) -> None:
        """Enable or disable busy indicators."""
        effective_tokens = tokens
        if active:
            breakdown = self._compute_context_token_breakdown()
            effective_tokens = breakdown.total
        if active:
            self._session.begin_run(tokens=effective_tokens)
            return
        self._session.finalize_run(tokens=effective_tokens)

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
            self._pending_session_running = running
            return
        self._pending_session_running = None
        tokens = self._session.tokens
        self._view.set_wait_state(
            running,
            tokens=tokens,
            context_limit=self._context_token_limit(),
            callbacks=self._wait_callbacks,
        )
        self._update_project_settings_ui()
        self._update_history_controls()
        if self._attachment_button is not None:
            self._attachment_button.Enable(not running)
        if running:
            self._update_status(0.0)
        if self._batch_section is not None:
            self._batch_section.update_ui()
        # Regenerate buttons live inside transcript cards; force a refresh so
        # their enabled state follows the latest running flag.
        self._request_transcript_refresh(
            conversation=self._get_active_conversation_loaded(),
            force=True,
            immediate=True,
        )
        self._update_regenerate_buttons(enabled=not running)

    def _update_regenerate_buttons(self, *, enabled: bool) -> None:
        """Toggle regenerate buttons regardless of cached card state."""

        transcript = getattr(self, "transcript_panel", None)
        if transcript is None:
            return
        target_labels = {"Regenerate", _("Regenerate")}

        def walker(window: wx.Window) -> None:
            for child in window.GetChildren():
                if isinstance(child, wx.Button) and child.GetLabel() in target_labels:
                    child.Enable(enabled)
                walker(child)

        walker(transcript)

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
        """Show compact progress timer while awaiting a response."""
        if self._layout is None:
            return
        self._view.update_wait_status(
            elapsed,
            self._session.tokens,
            self._context_token_limit(),
        )

    def _context_token_limit(self) -> int | None:
        """Return resolved context window size when available."""
        return self._session_controller.context_token_limit()

    def _active_context_messages(self) -> tuple[Mapping[str, Any], ...]:
        """Return contextual messages relevant to the current prompt."""
        handle = self._active_handle()
        if handle is not None and handle.context_messages:
            return handle.context_messages

        conversation = self._get_active_conversation_loaded()
        if conversation and conversation.entries:
            for entry in reversed(conversation.entries):
                if entry.context_messages:
                    return entry.context_messages
        return ()

    def _compute_token_breakdown(
        self,
        conversation: ChatConversation | None,
        *,
        context_messages: tuple[Mapping[str, Any], ...] | None = None,
        pending_entry: ChatEntry | None = None,
        prompt_tokens: TokenCountResult | None = None,
    ) -> ContextTokenBreakdown:
        """Return token accounting snapshot for *conversation*.

        This helper centralises the interaction with ``SessionController`` so
        that token usage is computed consistently between the transcript header
        and other UI surfaces (for example the batch queue table).
        """

        return self._session_controller.compute_context_token_breakdown(
            conversation,
            handle_context_messages=context_messages,
            pending_entry=pending_entry,
            active_handle_prompt_tokens=prompt_tokens,
            custom_system_prompt=self._custom_system_prompt(),
        )

    def _compute_context_token_breakdown(self) -> ContextTokenBreakdown:
        """Calculate token usage for the system prompt and conversation."""
        conversation = self._get_active_conversation_loaded()
        handle = self._active_handle()
        pending_entry = handle.pending_entry if handle is not None else None
        prompt_tokens = handle.prompt_tokens if handle is not None else None
        return self._compute_token_breakdown(
            conversation,
            context_messages=self._active_context_messages(),
            pending_entry=pending_entry,
            prompt_tokens=prompt_tokens,
        )

    def _format_context_percentage(
        self, tokens: TokenCountResult, limit: int | None
    ) -> str:
        """Return percentage representation of context usage."""
        if limit is None:
            return self._session_controller.format_context_percentage(tokens)
        return self._session_controller.format_context_percentage(tokens)

    def _format_tokens_for_status(
        self, tokens: TokenCountResult, *, limit: int | None = None
    ) -> str:
        if limit is None:
            return self._session_controller.format_tokens_for_status(tokens)
        return self._session_controller.format_tokens_for_status(tokens)

    def _update_conversation_header(self) -> None:
        """Refresh the transcript header with token statistics."""
        label = getattr(self, "_conversation_label", None)
        if label is None:
            return

        breakdown = self._compute_context_token_breakdown()
        total_tokens = breakdown.total
        context_limit = self._context_token_limit()
        tokens_text = self._format_tokens_for_status(total_tokens, limit=context_limit)
        percent_text = self._format_context_percentage(total_tokens, context_limit)

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
        elapsed = 0.0
        final_tokens: TokenCountResult | None = None
        tool_results: list[Any] | None = None
        tool_messages: tuple[dict[str, Any], ...] | None = None
        should_render = False
        success = True
        error_text: str | None = None
        total_tool_calls = 0
        requirement_edit_count = 0
        error_count: int | None = None
        token_count_value: int | None = None
        token_count_approximate = False
        conversation: ChatConversation | None = None
        conversation_token_breakdown: ContextTokenBreakdown | None = None
        try:
            (
                conversation_text,
                display_text,
                payload,
                tool_results,
                reasoning_segments,
            ) = self._process_result(result)
            latest_response = normalize_for_display(
                handle.latest_llm_response or ""
            )
            if latest_response:
                if latest_response not in conversation_text:
                    conversation_text = (
                        f"{latest_response}\n\n{conversation_text}"
                        if conversation_text
                        else latest_response
                    )
                if display_text:
                    if latest_response not in display_text:
                        display_text = f"{latest_response}\n\n{display_text}"
                else:
                    display_text = latest_response
            if not reasoning_segments and handle.latest_reasoning_segments:
                reasoning_segments = handle.latest_reasoning_segments

            streamed_snapshots = tuple(handle.tool_snapshots.values())
            final_snapshots: tuple[ToolResultSnapshot, ...]
            if tool_results:
                final_snapshots = tool_results
            elif streamed_snapshots:
                final_snapshots = streamed_snapshots
            else:
                final_snapshots = ()

            combined_snapshots: dict[str, ToolResultSnapshot] = {}

            def _merge_snapshots(
                source: Sequence[ToolResultSnapshot], prefix: str
            ) -> None:
                for index, snapshot in enumerate(source):
                    key = snapshot.call_id.strip() if snapshot.call_id else ""
                    if not key:
                        key = f"{prefix}:{index}"
                    existing = combined_snapshots.get(key)
                    if existing is None:
                        combined_snapshots[key] = snapshot
                        continue
                    merged_payload = snapshot.to_dict()
                    existing_payload = existing.to_dict()
                    for field in (
                        "started_at",
                        "completed_at",
                        "last_observed_at",
                        "status",
                    ):
                        if not merged_payload.get(field):
                            if existing_payload.get(field):
                                merged_payload[field] = existing_payload[field]
                    for field in ("tool_arguments", "result", "error"):
                        if merged_payload.get(field) in (None, {}, ""):
                            if existing_payload.get(field) not in (None, {}, ""):
                                merged_payload[field] = existing_payload[field]
                    try:
                        combined_snapshots[key] = ToolResultSnapshot.from_dict(
                            merged_payload
                        )
                    except Exception:
                        combined_snapshots[key] = snapshot

            _merge_snapshots(streamed_snapshots, "stream")
            _merge_snapshots(final_snapshots, "final")
            merged_snapshots = tuple(combined_snapshots.values())
            total_tool_calls = len(merged_snapshots)
            requirement_edit_count = sum(
                1
                for snapshot in merged_snapshots
                if snapshot.tool_name in _REQUIREMENT_EDITING_TOOLS
            )

            tool_payloads = tool_snapshot_dicts(merged_snapshots)
            tool_messages = self._build_tool_messages(merged_snapshots)

            if payload is not None:
                payload = ensure_canonical_agent_payload(
                    payload,
                    tool_snapshots=merged_snapshots,
                    llm_trace_preview=handle.llm_trace_preview,
                )
                raw_result = payload.to_dict()
                if tool_payloads:
                    raw_result["tool_results"] = tool_payloads
                else:
                    raw_result.pop("tool_results", None)
            else:
                raw_result = history_json_safe(result)
                if isinstance(raw_result, dict):
                    if tool_payloads:
                        raw_result["tool_results"] = tool_payloads
                    else:
                        raw_result.pop("tool_results", None)
            assistant_text = latest_response or conversation_text
            response_tokens = count_text_tokens(
                assistant_text,
                model=self._token_model(),
            )
            # The response token count is an estimate during streaming; treat it
            # as approximate and avoid double-counting the prompt/context when
            # reporting status for the latest turn.  If counting fails, surface
            # an "unavailable" snapshot so the status label uses "n/a".
            if response_tokens.tokens is None:
                final_tokens = TokenCountResult.unavailable(
                    model=response_tokens.model,
                    reason=response_tokens.reason,
                )
            else:
                final_tokens = TokenCountResult.approximate_result(
                    response_tokens.tokens,
                    model=response_tokens.model,
                    reason=response_tokens.reason,
                )
            token_count_value = final_tokens.tokens
            token_count_approximate = final_tokens.approximate
            response_at = utc_now_iso()
            prompt_at = getattr(handle, "prompt_at", None) or response_at
            conversation = self._get_conversation_by_id(handle.conversation_id)
            pending_entry = handle.pending_entry
            if conversation is not None and pending_entry is not None:
                self._complete_pending_entry(
                    conversation,
                    pending_entry,
                    prompt=prompt,
                    response=assistant_text,
                    display_response=display_text,
                    raw_result=raw_result,
                    token_info=final_tokens,
                    prompt_at=prompt_at,
                    response_at=response_at,
                    context_messages=handle.context_messages
                    or getattr(pending_entry, "context_messages", None),
                    history_snapshot=handle.history_snapshot,
                    reasoning_segments=reasoning_segments,
                    tool_messages=tool_messages,
                )
            else:
                self._append_history(
                    prompt,
                    assistant_text,
                    display_text,
                    raw_result,
                    final_tokens,
                    prompt_at=prompt_at,
                    response_at=response_at,
                    context_messages=handle.context_messages,
                    history_snapshot=handle.history_snapshot,
                    reasoning_segments=reasoning_segments,
                    tool_messages=tool_messages,
                )
            handle.pending_entry = None
            handle.tool_snapshots.clear()
            handle.tool_order.clear()
            handle.latest_llm_response = None
            handle.latest_reasoning_segments = None
            should_render = True
            if conversation is not None:
                error_count = self._count_conversation_errors(conversation)
                conversation_token_breakdown = self._compute_token_breakdown(
                    conversation,
                    context_messages=handle.context_messages or (),
                    prompt_tokens=handle.prompt_tokens,
                )
                conversation_total = conversation_token_breakdown.total
                if conversation_total.tokens is not None:
                    token_count_value = conversation_total.tokens
                    token_count_approximate = conversation_total.approximate
        finally:
            tokens_for_status = (
                conversation_token_breakdown.total
                if conversation_token_breakdown is not None
                else final_tokens
            )
            self._set_wait_state(False, tokens_for_status)
            elapsed = self._session.elapsed
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
                tool_call_count=total_tool_calls,
                requirement_edit_count=requirement_edit_count,
                error_count=error_count,
                token_count=token_count_value,
                tokens_approximate=token_count_approximate,
            )

        if should_render:
            self._render_transcript()
        self._schedule_prompt_queue_flush()

    def _process_result(
        self, result: Any
    ) -> tuple[
        str,
        str,
        AgentRunPayload | None,
        tuple[ToolResultSnapshot, ...],
        tuple[dict[str, str], ...],
    ]:
        """Normalise agent result for storage and display."""
        payload = agent_payload_from_mapping(result)
        if payload is None:
            text = stringify_payload(result)
            normalised = normalize_for_display(text)
            display_text = normalised
            tool_results: tuple[ToolResultSnapshot, ...] = ()
            if isinstance(result, Mapping):
                tool_results = tuple(tool_snapshots_from(result.get("tool_results")))
                error_payload = result.get("error")
                if error_payload:
                    display_text = normalize_for_display(
                        format_error_message(error_payload, fallback=normalised)
                    )
                if display_text == normalised:
                    result_payload = result.get("result")
                    if result_payload is not None:
                        display_text = normalize_for_display(
                            stringify_payload(result_payload)
                        )
            return normalised, display_text, None, tool_results, ()

        reasoning_segments: tuple[dict[str, str], ...] = tuple(
            {
                "type": normalize_for_display(str(segment.get("type", ""))),
                "text": normalize_for_display(str(segment.get("text", ""))),
            }
            for segment in payload.reasoning
            if isinstance(segment, Mapping) and str(segment.get("text", "")).strip()
        )

        tool_results = tuple(payload.tool_results)

        base_text = normalize_for_display(payload.result_text)
        conversation_parts: list[str] = []

        if payload.ok:
            display_text = base_text
            if display_text:
                conversation_parts.append(display_text)
        else:
            error_payload: Mapping[str, Any] | None = None
            if payload.error is not None:
                error_payload = payload.error.to_dict()
            else:
                diagnostic_payload = payload.diagnostic or {}
                if isinstance(diagnostic_payload, Mapping):
                    candidate = diagnostic_payload.get("error")
                    if isinstance(candidate, Mapping):
                        error_payload = candidate
            error_text = format_error_message(
                error_payload, fallback=base_text or _("Unknown error")
            )
            if error_text:
                conversation_parts.append(error_text)
            if base_text and base_text not in conversation_parts:
                conversation_parts.append(base_text)
            display_text = normalize_for_display(error_text or base_text or _("Agent run failed"))

        conversation_text = "\n\n".join(
            normalize_for_display(part)
            for part in conversation_parts
            if part.strip()
        )

        return (
            conversation_text,
            normalize_for_display(display_text),
            payload,
            tool_results,
            reasoning_segments,
        )

    @staticmethod
    def _normalise_reasoning_segments(
        raw_segments: Any
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
                leading_value = item.get("leading_whitespace")
                trailing_value = item.get("trailing_whitespace")
            else:
                type_value = getattr(item, "type", None)
                text_value = getattr(item, "text", None)
                leading_value = getattr(item, "leading_whitespace", "")
                trailing_value = getattr(item, "trailing_whitespace", "")
            if text_value is None:
                continue
            text_candidate = str(text_value)
            if not text_candidate:
                continue
            text = text_candidate.strip()
            if not text:
                continue
            type_str = str(type_value) if type_value is not None else ""
            segment: dict[str, str] = {"type": type_str, "text": text}
            leading = str(leading_value or "")
            trailing = str(trailing_value or "")
            if leading:
                segment["leading_whitespace"] = leading
            if trailing:
                segment["trailing_whitespace"] = trailing
            segments.append(segment)
        return tuple(segments)

    # ------------------------------------------------------------------
    def _conversation_messages(self) -> tuple[dict[str, str], ...]:
        conversation = self._get_active_conversation_loaded()
        if conversation is None:
            return ()
        return self._conversation_messages_for(conversation)

    def _conversation_messages_for(
        self, conversation: ChatConversation
    ) -> tuple[dict[str, Any], ...]:
        self._session.history.ensure_conversation_entries(conversation)
        messages: list[dict[str, Any]] = []
        custom_prompt = self._custom_system_prompt()
        if custom_prompt:
            messages.append({"role": "system", "content": custom_prompt})
        for entry in conversation.entries:
            if getattr(entry, "regenerated", False):
                continue
            if entry.prompt:
                messages.append({"role": "user", "content": entry.prompt})
            entry_messages = self._entry_conversation_messages(entry)
            if entry_messages:
                messages.extend(entry_messages)
        return tuple(messages)

    def _prepare_context_messages(
        self,
        raw: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
        *,
        consume_pending: bool = True,
        attachment_override: _PendingAttachment | None = None,
    ) -> tuple[dict[str, Any], ...]:
        prepared: list[dict[str, Any]] = []
        if raw:
            if isinstance(raw, Mapping):
                prepared.append(dict(raw))
            else:
                for entry in raw:
                    if isinstance(entry, Mapping):
                        prepared.append(dict(entry))

        attachment_present = any(
            isinstance(message.get("metadata"), Mapping)
            and isinstance(message["metadata"].get("attachment"), Mapping)
            for message in prepared
        )

        if attachment_present:
            if consume_pending and attachment_override is None and self._pending_attachment is not None:
                self._pending_attachment = None
                self._update_attachment_summary()
            return tuple(prepared)

        attachment = (
            attachment_override
            if attachment_override is not None
            else self._pending_attachment
        )
        if attachment is not None:
            prepared.append(attachment.to_context_message())
            if consume_pending and attachment_override is None:
                self._pending_attachment = None
                self._update_attachment_summary()
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

    @staticmethod
    def _clone_tool_messages(
        tool_messages: Sequence[Mapping[str, Any]] | None,
    ) -> tuple[dict[str, Any], ...] | None:
        if not tool_messages:
            return None
        cloned: list[dict[str, Any]] = []
        for message in tool_messages:
            if not isinstance(message, Mapping):
                continue
            cloned_message: dict[str, Any] = {}
            role_value = message.get("role")
            role = str(role_value).strip() if role_value is not None else "tool"
            cloned_message["role"] = role or "tool"
            content_value = message.get("content")
            cloned_message["content"] = (
                str(content_value) if content_value is not None else ""
            )
            call_value = message.get("tool_call_id")
            if isinstance(call_value, str) and call_value.strip():
                cloned_message["tool_call_id"] = call_value.strip()
            name_value = message.get("name")
            if isinstance(name_value, str) and name_value.strip():
                cloned_message["name"] = name_value.strip()
            cloned.append(cloned_message)
        if not cloned:
            return None
        return tuple(cloned)

    @staticmethod
    def _entry_conversation_messages(entry: ChatEntry) -> tuple[dict[str, Any], ...]:
        """Return assistant/tool message sequence reconstructed from ``entry``."""
        payload = agent_payload_from_mapping(
            entry.raw_result if isinstance(entry.raw_result, Mapping) else None
        )

        if payload is None or not payload.timeline:
            return ()

        tool_messages = tool_messages_from_snapshots(payload.tool_results)
        final_response_text = entry.response or payload.result_text

        return AgentChatPanel._entry_messages_from_timeline(
            payload.timeline,
            payload.llm_trace.steps,
            tool_messages,
            final_response_text,
            entry,
        )

    @staticmethod
    def _entry_messages_from_timeline(
        timeline: Sequence[AgentTimelineEntry],
        steps: Sequence[LlmStep],
        tool_messages: tuple[dict[str, Any], ...] | None,
        final_response_text: str | None,
        entry: ChatEntry,
    ) -> tuple[dict[str, Any], ...]:
        ordered_messages: list[dict[str, Any]] = []
        tool_messages_by_call: dict[str, list[dict[str, Any]]] = {}
        orphan_tool_messages: list[dict[str, Any]] = []

        if tool_messages:
            for message in tool_messages:
                call_identifier = message.get("tool_call_id")
                cloned_message = dict(message)
                if isinstance(call_identifier, str) and call_identifier:
                    tool_messages_by_call.setdefault(call_identifier, []).append(
                        cloned_message
                    )
                else:
                    orphan_tool_messages.append(cloned_message)

        steps_by_index: dict[int, LlmStep] = {step.index: step for step in steps}

        ordered_timeline = sorted(timeline, key=lambda entry: entry.sequence)
        used_tools: set[str] = set()
        existing_assistant_texts: set[str] = set()

        for entry_index, timeline_entry in enumerate(ordered_timeline):
            if timeline_entry.kind == "llm_step":
                step_payload = steps_by_index.get(timeline_entry.step_index or 0)
                assistant_message = AgentChatPanel._assistant_message_from_step(
                    step_payload
                )
                if assistant_message is None:
                    continue
                ordered_messages.append(assistant_message)
                content_value = assistant_message.get("content")
                if isinstance(content_value, str):
                    existing_assistant_texts.add(content_value)
            elif timeline_entry.kind == "tool_call":
                call_id = timeline_entry.call_id or ""
                if call_id in used_tools:
                    continue
                used_tools.add(call_id)
                queued_messages = tool_messages_by_call.pop(call_id, [])
                ordered_messages.extend(dict(message) for message in queued_messages)
            elif timeline_entry.kind == "agent_finished" and final_response_text:
                if final_response_text not in existing_assistant_texts:
                    final_message: dict[str, Any] = {
                        "role": "assistant",
                        "content": final_response_text,
                    }
                    reasoning_segments = AgentChatPanel._normalise_reasoning_segments(
                        getattr(entry, "reasoning", None)
                    )
                    if reasoning_segments:
                        final_message["reasoning"] = [
                            dict(segment) for segment in reasoning_segments
                        ]
                    ordered_messages.append(final_message)
                    existing_assistant_texts.add(final_response_text)

        for remaining in tool_messages_by_call.values():
            ordered_messages.extend(dict(message) for message in remaining)
        ordered_messages.extend(dict(message) for message in orphan_tool_messages)

        if (
            not ordered_messages
            and final_response_text
            and final_response_text not in existing_assistant_texts
        ):
            ordered_messages.append(
                {"role": "assistant", "content": final_response_text}
            )

        return tuple(ordered_messages)

    @staticmethod
    def _format_tool_message(message: Mapping[str, Any]) -> dict[str, Any] | None:
        if not isinstance(message, Mapping):
            return None
        role_value = message.get("role")
        role = str(role_value).strip() if role_value is not None else "tool"
        content_value = message.get("content")
        if content_value is None:
            content = ""
        else:
            content = str(content_value)
        formatted: dict[str, Any] = {"role": role or "tool", "content": content}
        call_value = message.get("tool_call_id")
        if isinstance(call_value, str) and call_value.strip():
            formatted["tool_call_id"] = call_value.strip()
        name_value = message.get("name")
        if isinstance(name_value, str) and name_value.strip():
            formatted["name"] = name_value.strip()
        return formatted

    @staticmethod
    def _assistant_message_from_step(
        step: Mapping[str, Any] | LlmStep | None,
    ) -> dict[str, Any] | None:
        if isinstance(step, LlmStep):
            response = step.response
        elif isinstance(step, Mapping):
            response = step.get("response")
        else:
            return None
        if not isinstance(response, Mapping):
            return None
        content_value = response.get("content")
        content = str(content_value) if content_value is not None else ""
        message: dict[str, Any] = {"role": "assistant", "content": content}
        reasoning_segments = AgentChatPanel._normalise_reasoning_segments(
            response.get("reasoning")
        )
        if reasoning_segments:
            message["reasoning"] = [dict(segment) for segment in reasoning_segments]
        tool_calls = AgentChatPanel._normalise_step_tool_calls(
            response.get("tool_calls")
        )
        if tool_calls:
            message["tool_calls"] = tool_calls
        return message

    @staticmethod
    def _normalise_step_tool_calls(raw_calls: Any) -> list[dict[str, Any]]:
        if not raw_calls:
            return []
        if isinstance(raw_calls, Mapping):
            candidates: Sequence[Any] = [raw_calls]
        elif isinstance(raw_calls, Sequence) and not isinstance(
            raw_calls, (str, bytes, bytearray)
        ):
            candidates = raw_calls
        else:
            candidates = [raw_calls]

        tool_calls: list[dict[str, Any]] = []
        for index, entry in enumerate(candidates):
            if not isinstance(entry, Mapping):
                continue
            call_identifier = (
                entry.get("id")
                or entry.get("tool_call_id")
                or entry.get("call_id")
                or f"tool_call_{index}"
            )
            function_payload = entry.get("function")
            name = None
            arguments: Any | None = None
            if isinstance(function_payload, Mapping):
                name = function_payload.get("name")
                arguments = function_payload.get("arguments")
            if name is None:
                name = entry.get("name")
            if arguments is None:
                arguments = entry.get("arguments")
            if name is None:
                continue
            arguments_text = AgentChatPanel._serialise_tool_call_arguments(arguments)
            tool_calls.append(
                {
                    "id": str(call_identifier),
                    "type": "function",
                    "function": {"name": str(name), "arguments": arguments_text},
                }
            )
        return tool_calls

    @staticmethod
    def _serialise_tool_call_arguments(arguments: Any) -> str:
        if isinstance(arguments, str):
            text = arguments.strip()
            return text or "{}"
        if isinstance(arguments, Mapping):
            return json.dumps(arguments, ensure_ascii=False, default=str)
        if arguments is None:
            return "{}"
        try:
            text = json.dumps(arguments, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return "{}"
        return text.strip() or "{}"

    def _build_tool_messages(
        self, tool_results: Sequence[ToolResultSnapshot] | None
    ) -> tuple[dict[str, Any], ...] | None:
        messages = tool_messages_from_snapshots(tool_results)
        return messages or None

    @staticmethod
    def _append_event_log(
        entry: ChatEntry,
        *,
        kind: str,
        payload: Any | None = None,
        occurred_at: str | None = None,
        source: str | None = None,
    ) -> None:
        """Persist a low-level diagnostic event on ``entry`` preserving order."""

        if not isinstance(entry, ChatEntry):
            return

        diagnostic = entry.diagnostic if isinstance(entry.diagnostic, dict) else {}
        if diagnostic is None:
            diagnostic = {}

        log = diagnostic.get("event_log")
        if not isinstance(log, list):
            log = []

        timestamp = (occurred_at or "").strip() or utc_now_iso()
        record: dict[str, Any] = {
            "kind": kind,
            "occurred_at": timestamp,
            "sequence": len(log),
        }
        if source:
            record["source"] = source
        if payload is not None:
            record["payload"] = history_json_safe(payload)

        log.append(record)
        diagnostic["event_log"] = log
        entry.diagnostic = diagnostic

    @staticmethod
    def _collect_entry_event_log(entry: ChatEntry) -> list[dict[str, Any]]:
        """Return the best-effort ordered ``event_log`` for ``entry``."""

        def _candidates() -> Iterable[Sequence[Any] | None]:
            diagnostic = entry.diagnostic if isinstance(entry.diagnostic, Mapping) else None
            if diagnostic:
                yield diagnostic.get("event_log")
            raw_result = entry.raw_result if isinstance(entry.raw_result, Mapping) else None
            if raw_result:
                yield raw_result.get("event_log")
                diagnostic_payload = raw_result.get("diagnostic")
                if isinstance(diagnostic_payload, Mapping):
                    yield diagnostic_payload.get("event_log")
                payload = agent_payload_from_mapping(raw_result)
                if payload is not None and payload.events.events:
                    yield [event.to_dict() for event in payload.events.events]

        for candidate in _candidates():
            if not isinstance(candidate, Sequence):
                continue
            events: list[dict[str, Any]] = []
            for record in candidate:
                if not isinstance(record, Mapping):
                    continue
                events.append({str(key): value for key, value in record.items()})
            if events:
                return events
        return []

    def _export_entry_event_log_debug(
        self,
        conversation: ChatConversation,
        entry: ChatEntry,
        *,
        stage: str,
    ) -> None:
        """Export the ordered event log for ``entry`` when configured."""

        directory = os.environ.get("COOKAREQ_AGENT_EVENT_LOG_DIR")
        if not directory:
            return

        log_events = self._collect_entry_event_log(entry)
        if not log_events:
            return

        try:
            entry_index = conversation.entries.index(entry)
        except ValueError:
            entry_index = None

        timestamp = entry.response_at or entry.prompt_at or utc_now_iso()
        conversation_id = conversation.conversation_id or conversation.title or "conversation"

        with suppress(Exception):
            write_event_log_debug(
                log_events,
                directory=directory,
                conversation_id=str(conversation_id),
                entry_index=entry_index,
                stage=stage,
                timestamp=timestamp,
            )

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
            display_response=_("Working"),
            raw_result=None,
            token_info=TokenCountResult.exact(0),
            prompt_at=prompt_at,
            response_at=None,
            context_messages=self._clone_context_messages(context_messages),
        )
        self._append_event_log(
            entry,
            kind="prompt",
            payload={
                "prompt": prompt_text,
                "context_messages": self._clone_context_messages(context_messages),
            },
            occurred_at=prompt_at,
            source="user",
        )
        conversation.append_entry(entry)
        self._mark_conversation_dirty(conversation)
        entry_id = self._entry_identifier(conversation, entry)
        self._request_transcript_refresh(
            conversation=conversation,
            entry_ids=[entry_id] if entry_id else None,
            force=entry_id is None,
            immediate=True,
        )
        return entry

    def _append_history(
        self,
        prompt: str,
        response: str,
        display_response: str,
        raw_result: Any | None,
        token_info: TokenCountResult | None,
        prompt_at: str | None = None,
        *,
        response_at: str | None = None,
        context_messages: tuple[dict[str, Any], ...] | None = None,
        history_snapshot: tuple[dict[str, Any], ...] | None = None,
        reasoning_segments: tuple[dict[str, str], ...] | None = None,
        tool_messages: tuple[dict[str, Any], ...] | None = None,
    ) -> None:
        conversation = self._ensure_active_conversation()
        self._session.history.ensure_conversation_entries(conversation)
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
        tool_message_clone = self._clone_tool_messages(tool_messages)
        reasoning_clone = self._normalise_reasoning_segments(reasoning_segments)
        if not reasoning_clone:
            reasoning_clone = None
        tool_snapshots = tool_snapshots_from(raw_result)
        entry = ChatEntry(
            prompt=prompt_text,
            response=response_text,
            tokens=tokens,
            display_response=display_text,
            raw_result=raw_result,
            token_info=token_info,
            prompt_at=prompt_at,
            response_at=response_at,
            context_messages=context_clone,
            tool_messages=tool_message_clone,
            reasoning=reasoning_clone,
            diagnostic=self._build_entry_diagnostic(
                prompt=prompt_text,
                prompt_at=prompt_at,
                response_at=response_at,
                display_response=display_text,
                stored_response=response_text,
                raw_result=raw_result,
                tool_results=tool_snapshots,
                history_snapshot=history_snapshot,
                context_snapshot=context_clone,
                custom_system_prompt=self._custom_system_prompt(),
            ),
        )
        self._append_event_log(
            entry,
            kind="final_response",
            payload={
                "prompt": prompt_text,
                "response": response_text,
                "display_response": display_text,
                "raw_result": raw_result,
                "tool_messages": tool_message_clone,
                "context_messages": context_clone,
                "reasoning": reasoning_clone,
            },
            occurred_at=response_at,
            source="finalise",
        )
        conversation.append_entry(entry)
        self._mark_conversation_dirty(conversation)
        entry_id = self._entry_identifier(conversation, entry)
        entry_ids: list[str] | None
        force_refresh = entry_id is None
        if entry_id is None:
            entry_ids = None
        else:
            entry_ids = [entry_id]
            prior_index = len(conversation.entries) - 2
            if prior_index >= 0:
                prior_entry = conversation.entries[prior_index]
                prior_id = self._entry_identifier(conversation, prior_entry)
                if prior_id and prior_id not in entry_ids:
                    entry_ids.append(prior_id)
        if force_refresh:
            timeline_cache = getattr(self, "_timeline_cache", None)
            if timeline_cache is not None:
                timeline_cache.invalidate_conversation(conversation.conversation_id)
        self._latest_timeline = None
        self._save_history_to_store()
        self._notify_history_changed()
        self._request_transcript_refresh(
            conversation=conversation,
            entry_ids=entry_ids,
            force=force_refresh,
            immediate=True,
        )

    def _complete_pending_entry(
        self,
        conversation: ChatConversation,
        entry: ChatEntry,
        *,
        prompt: str,
        response: str,
        display_response: str,
        raw_result: Any | None,
        token_info: TokenCountResult | None,
        prompt_at: str,
        response_at: str,
        context_messages: tuple[dict[str, Any], ...] | None,
        history_snapshot: tuple[dict[str, Any], ...] | None = None,
        reasoning_segments: tuple[dict[str, str], ...] | None = None,
        tool_messages: tuple[dict[str, Any], ...] | None = None,
    ) -> None:
        self._session.history.ensure_conversation_entries(conversation)
        prompt_text = normalize_for_display(prompt)
        response_text = normalize_for_display(response)
        display_text = normalize_for_display(display_response or response)
        entry.prompt = prompt_text
        entry.response = response_text
        entry.display_response = display_text
        entry.raw_result = raw_result
        tokens_info = (
            token_info if token_info is not None else TokenCountResult.exact(0)
        )
        entry.token_info = tokens_info
        entry.tokens = tokens_info.tokens or 0
        entry.prompt_at = prompt_at
        entry.response_at = response_at
        context_clone = self._clone_context_messages(context_messages)
        entry.context_messages = context_clone
        entry.tool_messages = self._clone_tool_messages(tool_messages)
        reasoning_clone = self._normalise_reasoning_segments(reasoning_segments)
        entry.reasoning = reasoning_clone or None
        tool_snapshots = tool_snapshots_from(raw_result)
        existing_diagnostic = (
            entry.diagnostic if isinstance(entry.diagnostic, Mapping) else None
        )
        entry.diagnostic = self._build_entry_diagnostic(
            prompt=prompt_text,
            prompt_at=prompt_at,
            response_at=response_at,
            display_response=display_text,
            stored_response=response_text,
            raw_result=raw_result,
            tool_results=tool_snapshots,
            history_snapshot=history_snapshot,
            context_snapshot=context_clone,
            custom_system_prompt=self._custom_system_prompt(),
            previous_diagnostic=existing_diagnostic,
        )
        self._append_event_log(
            entry,
            kind="final_response",
            payload={
                "prompt": prompt_text,
                "response": response_text,
                "display_response": display_text,
                "raw_result": raw_result,
                "tool_messages": entry.tool_messages,
                "context_messages": context_clone,
                "reasoning": entry.reasoning,
            },
            occurred_at=response_at,
            source="finalise",
        )
        self._export_entry_event_log_debug(
            conversation,
            entry,
            stage="finalise",
        )
        conversation.updated_at = response_at
        conversation.ensure_title()
        conversation.recalculate_preview()
        self._mark_conversation_dirty(conversation)
        self._save_history_to_store()
        self._notify_history_changed()
        entry_id = self._entry_identifier(conversation, entry)
        self._request_transcript_refresh(
            conversation=conversation,
            entry_ids=[entry_id] if entry_id else None,
            force=entry_id is None,
            immediate=True,
        )

    def _pop_conversation_entry(
        self,
        conversation: ChatConversation,
        entry: ChatEntry,
    ) -> RemovedConversationEntry | None:
        self._session.history.ensure_conversation_entries(conversation)
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
        conversation.recalculate_preview()
        self._mark_conversation_dirty(conversation)
        return RemovedConversationEntry(
            index=index,
            entry=removed,
            previous_updated_at=previous_updated,
        )

    def _remove_conversation_entry(
        self, conversation: ChatConversation, entry: ChatEntry
    ) -> RemovedConversationEntry | None:
        removal = self._pop_conversation_entry(conversation, entry)
        if removal is None:
            return None
        self._save_history_to_store()
        self._notify_history_changed()
        self._timeline_cache.invalidate_conversation(conversation.conversation_id)
        self._request_transcript_refresh(
            conversation=conversation, force=True, immediate=True
        )
        return removal

    def _restore_conversation_entry(
        self, conversation: ChatConversation, removal: RemovedConversationEntry
    ) -> None:
        self._session.history.ensure_conversation_entries(conversation)
        conversation.entries.insert(removal.index, removal.entry)
        conversation.updated_at = removal.previous_updated_at
        conversation.ensure_title()
        conversation.recalculate_preview()
        self._mark_conversation_dirty(conversation)
        self._save_history_to_store()
        self._notify_history_changed()
        self._timeline_cache.invalidate_conversation(conversation.conversation_id)
        self._request_transcript_refresh(
            conversation=conversation, force=True, immediate=True
        )

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
        handle.tool_snapshots.clear()
        handle.tool_order.clear()
        self._save_history_to_store()
        self._notify_history_changed()

    def _finalize_cancelled_run(self, handle: _AgentRunHandle) -> None:
        """Preserve transcript state after cancelling an agent run."""
        entry = handle.pending_entry
        if entry is None:
            self._request_transcript_refresh(force=True, immediate=True)
            self._schedule_prompt_queue_flush()
            return
        conversation = self._get_conversation_by_id(handle.conversation_id)
        if conversation is None:
            handle.pending_entry = None
            handle.tool_snapshots.clear()
            handle.tool_order.clear()
            handle.llm_trace_preview.clear()
            self._request_transcript_refresh(force=True, immediate=True)
            batch_section = self._batch_section
            if batch_section is not None:
                batch_section.notify_cancellation(
                    conversation_id=handle.conversation_id
                )
            self._schedule_prompt_queue_flush()
            return

        cancellation_message = _("Generation cancelled")
        response_at = utc_now_iso()
        prompt_at = getattr(handle, "prompt_at", None) or response_at
        token_info = combine_token_counts([handle.prompt_tokens])
        tool_snapshots = tuple(handle.tool_snapshots.values())
        tool_payloads = tool_snapshot_dicts(tool_snapshots)
        tool_messages = self._build_tool_messages(tool_snapshots)
        response_text = handle.latest_llm_response or ""
        reasoning_segments: tuple[dict[str, str], ...] | None = (
            handle.latest_reasoning_segments
            if handle.latest_reasoning_segments
            else None
        )
        if not response_text:
            last_step_payload: Mapping[str, Any] | None = None
            if handle.llm_trace_preview:
                candidate = handle.llm_trace_preview[-1]
                if isinstance(candidate, Mapping):
                    last_step_payload = candidate
            if isinstance(last_step_payload, Mapping):
                response_payload = last_step_payload.get("response")
                if isinstance(response_payload, Mapping):
                    content_value = response_payload.get("content")
                    if isinstance(content_value, str):
                        response_text = content_value
                    if reasoning_segments is None:
                        reasoning_segments = self._normalise_reasoning_segments(
                            response_payload.get("reasoning")
                        ) or None
        combined_display = cancellation_message
        if response_text:
            combined_display = f"{response_text}\n\n{cancellation_message}"

        events = AgentEventLog(
            events=[
                AgentEvent(
                    kind="agent_finished",
                    occurred_at=utc_now_iso(),
                    payload={
                        "ok": False,
                        "status": "failed",
                        "result": response_text or cancellation_message,
                        "error": {
                            "type": "OperationCancelledError",
                            "message": cancellation_message,
                            "details": {"reason": "user_cancelled"},
                        },
                    },
                )
            ]
        )

        prompt_timestamp = _build_timestamp(prompt_at, source="prompt_at")
        response_timestamp = _build_timestamp(response_at, source="response_at")
        llm_steps = [
            dict(step)
            for step in handle.llm_trace_preview
            if isinstance(step, Mapping)
        ]
        diagnostic_sections: dict[str, Any] = {}
        if llm_steps:
            diagnostic_sections["llm_steps"] = llm_steps
        diagnostic_sections["event_log"] = [
            event.to_dict() for event in events.events
        ]
        llm_trace = _build_llm_trace_from_diagnostic(
            diagnostic_sections,
            prompt_timestamp=prompt_timestamp,
            response_timestamp=response_timestamp,
        )
        if llm_trace is None:
            llm_trace = LlmTrace()

        payload = AgentRunPayload(
            ok=False,
            status="failed",
            result_text=response_text,
            events=events,
            reasoning=list(reasoning_segments or ()),
            tool_results=[snapshot for snapshot in tool_snapshots],
            llm_trace=llm_trace,
            error=ToolError(
                message=cancellation_message,
                code="OperationCancelledError",
                details={"reason": "user_cancelled"},
            ),
            tool_schemas=None,
            diagnostic=diagnostic_sections,
        )
        raw_result = payload.to_dict()
        if tool_payloads:
            raw_result["tool_results"] = tool_payloads

        self._complete_pending_entry(
            conversation,
            entry,
            prompt=handle.prompt,
            response=response_text,
            display_response=combined_display,
            raw_result=raw_result,
            token_info=token_info,
            prompt_at=prompt_at,
            response_at=response_at,
            context_messages=handle.context_messages,
            history_snapshot=handle.history_snapshot,
            reasoning_segments=reasoning_segments,
            tool_messages=tool_messages,
        )
        handle.pending_entry = None
        handle.tool_snapshots.clear()
        handle.tool_order.clear()
        handle.llm_trace_preview.clear()
        handle.latest_llm_response = None
        handle.latest_reasoning_segments = None
        batch_section = self._batch_section
        if batch_section is not None:
            batch_section.notify_cancellation(
                conversation_id=handle.conversation_id
            )
        self._schedule_prompt_queue_flush()

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

    def _current_history_column_widths(
        self, history_list: wx.Window | None = None
    ) -> tuple[int, ...]:
        observer = getattr(self, "_layout_manager", None)
        getter = getattr(observer, "_current_history_column_widths", None)
        if callable(getter):
            try:
                return tuple(getter(history_list))
            except Exception:
                return ()
        return ()

    def _refresh_history_columns(self) -> None:
        self._history_column_refresh_scheduled = False
        refresher = getattr(self._layout_manager, "refresh_history_columns", None)
        if callable(refresher):
            refresher()
            return
        history_list = getattr(self, "history_list", None)
        if history_list is not None:
            history_list.Refresh()
            history_list.Update()

    def _on_history_list_idle(self, event: wx.IdleEvent) -> None:
        event.Skip()
        widths = self._current_history_column_widths()
        if not widths:
            return
        if widths == tuple(self._history_column_widths or ()):  # type: ignore[arg-type]
            return
        self._history_column_widths = tuple(widths)
        if self._history_column_refresh_scheduled:
            return
        self._history_column_refresh_scheduled = True
        wx.CallAfter(self._refresh_history_columns)

    def _prepare_history_interaction(self) -> bool:
        """Flush pending transcript updates before history interactions."""
        if self._pending_transcript_refresh:
            self._flush_pending_transcript_refresh()
        return False

    def _request_transcript_refresh(
        self,
        *,
        conversation: ChatConversation | None = None,
        entry_ids: Iterable[str] | None = None,
        force: bool = False,
        immediate: bool = False,
    ) -> None:
        if conversation is None:
            conversation = self._get_active_conversation_loaded()
        conversation_id = (
            conversation.conversation_id if conversation is not None else None
        )

        if conversation_id is None:
            self._pending_transcript_refresh[None] = None
        else:
            if force:
                self._pending_transcript_refresh[conversation_id] = None
            else:
                entry_set = {entry_id for entry_id in (entry_ids or ()) if entry_id}
                if not entry_set:
                    return
                self._timeline_cache.invalidate_entries(conversation_id, entry_set)
                existing = self._pending_transcript_refresh.get(conversation_id)
                if (
                    existing is None
                    and conversation_id in self._pending_transcript_refresh
                ):
                    # full refresh already queued
                    pass
                else:
                    bucket = self._pending_transcript_refresh.setdefault(
                        conversation_id, set()
                    )
                    if bucket is not None:
                        bucket.update(entry_set)

        if immediate:
            self._flush_pending_transcript_refresh(immediate=True)
        elif not self._transcript_refresh_scheduled:
            self._transcript_refresh_scheduled = True
            wx.CallAfter(self._flush_pending_transcript_refresh)

    def _flush_pending_transcript_refresh(self, *, immediate: bool = False) -> None:
        pending = self._pending_transcript_refresh
        if not pending:
            self._transcript_refresh_scheduled = False
            return
        self._pending_transcript_refresh = {}
        self._transcript_refresh_scheduled = False

        view = self._transcript_view
        if view is None:
            return

        active_conversation = self._get_active_conversation_loaded()
        active_id = active_conversation.conversation_id if active_conversation else None

        for conversation_id, entry_ids in pending.items():
            force_request = entry_ids is None
            if conversation_id is None:
                render_kwargs = {
                    "conversation": None,
                    "timeline": None,
                    "updated_entries": None,
                    "force": True,
                }
                if immediate:
                    view.render_now(**render_kwargs)
                else:
                    view.schedule_render(**render_kwargs)
                self._latest_timeline = None
                self._last_rendered_conversation_id = None
                self._update_transcript_selection_probe(
                    compose_transcript_text(None)
                )
                continue

            conversation = (
                active_conversation
                if conversation_id == active_id
                else self._get_conversation_by_id(conversation_id)
            )
            if conversation is None:
                self._timeline_cache.forget(conversation_id)
                continue

            timeline = self._timeline_cache.timeline_for(conversation)
            if conversation_id != active_id:
                continue

            if not force_request and not entry_ids:
                continue

            if force_request:
                updated_entries: Iterable[str] | None = [
                    entry.entry_id for entry in timeline.entries
                ]
            else:
                updated_entries = sorted(entry_ids)

            should_force = force_request and (
                conversation_id != self._last_rendered_conversation_id
            )
            render_kwargs = {
                "conversation": conversation,
                "timeline": timeline,
                "updated_entries": updated_entries,
                "force": should_force,
            }
            if immediate:
                view.render_now(**render_kwargs)
            else:
                view.schedule_render(**render_kwargs)
            self._latest_timeline = timeline
            self._last_rendered_conversation_id = conversation_id
            self._update_transcript_selection_probe(
                compose_transcript_text(conversation, timeline=timeline)
            )

    def _render_transcript(self) -> None:
        active_conversation = self._get_active_conversation_loaded()
        force_refresh = (
            active_conversation is None
            or active_conversation.conversation_id
            != self._last_rendered_conversation_id
        )
        self._request_transcript_refresh(
            conversation=active_conversation,
            force=force_refresh,
            immediate=True,
        )

    def _update_transcript_selection_probe(self, text: str | None = None) -> None:
        probe = getattr(self, "_transcript_selection_probe", None)
        if not isinstance(probe, wx.TextCtrl):
            return
        if text is None:
            text = self._compose_transcript_text()
        normalised = normalize_for_display(text or "")
        if probe.GetValue() != normalised:
            probe.ChangeValue(normalised)

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

    @staticmethod
    def _sanitize_llm_step_sequence(
        steps: Sequence[Any] | None,
    ) -> list[dict[str, Any]]:
        if not steps or isinstance(steps, (str, bytes, bytearray)):
            return []
        sanitized: list[dict[str, Any]] = []
        for entry in steps:
            safe_entry = history_json_safe(entry)
            if isinstance(safe_entry, Mapping):
                sanitized.append(dict(safe_entry))
        return sanitized

    @classmethod
    def _sanitize_planned_tool_calls(
        cls, trace: LlmTrace | Sequence[Any] | None
    ) -> list[Any] | None:
        planned: list[Any] = []
        if isinstance(trace, LlmTrace):
            for step in trace.steps:
                tool_calls = step.response.get("tool_calls") if isinstance(step.response, Mapping) else None
                if not tool_calls:
                    continue
                safe_calls = history_json_safe(tool_calls)
                if safe_calls is None:
                    continue
                if isinstance(safe_calls, list):
                    planned = safe_calls
                else:
                    planned = [safe_calls]
            return planned or None

        if isinstance(trace, Sequence) and not isinstance(
            trace, (str, bytes, bytearray)
        ):
            for entry in trace:
                if isinstance(entry, Mapping):
                    planned.append(history_json_safe(entry))
        return planned or None

    @classmethod
    def _merge_llm_step_sequences(
        cls,
        primary: list[dict[str, Any]],
        fallback: Sequence[Mapping[str, Any]] | None,
    ) -> None:
        if not fallback:
            return
        fallback_steps = cls._sanitize_llm_step_sequence(fallback)
        if not fallback_steps:
            return

        def _step_key(step: Mapping[str, Any]) -> str:
            raw = step.get("step")
            return str(raw) if raw is not None else "0"

        fallback_lookup: dict[str, Mapping[str, Any]] = {
            _step_key(step): step for step in fallback_steps
        }
        seen: set[str] = set()
        for step in primary:
            key = _step_key(step)
            seen.add(key)
            response = step.get("response")
            if not isinstance(response, Mapping) or response.get("tool_calls"):
                continue
            fallback_step = fallback_lookup.get(key)
            if not isinstance(fallback_step, Mapping):
                continue
            fallback_response = fallback_step.get("response")
            if not isinstance(fallback_response, Mapping):
                continue
            tool_calls = fallback_response.get("tool_calls")
            if not tool_calls:
                continue
            safe_calls = history_json_safe(tool_calls)
            if safe_calls:
                merged_response = dict(response)
                merged_response["tool_calls"] = safe_calls
                step["response"] = merged_response

        for key, fallback_step in fallback_lookup.items():
            if key in seen:
                continue
            safe_step = history_json_safe(fallback_step)
            if isinstance(safe_step, Mapping):
                primary.append(dict(safe_step))

        primary.sort(key=lambda step: step.get("step") or 0)

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
        previous_diagnostic: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        prompt_text = normalize_for_display(prompt)
        display_text = normalize_for_display(display_response)
        stored_text = normalize_for_display(stored_response)
        history_messages = cls._sanitize_log_messages(history_snapshot)
        context_messages = cls._sanitize_log_messages(context_snapshot)

        raw_result_safe = (
            history_json_safe(raw_result) if raw_result is not None else None
        )
        raw_result_mapping = (
            raw_result_safe if isinstance(raw_result_safe, Mapping) else None
        )

        payload = agent_payload_from_mapping(raw_result_mapping)

        tool_snapshots: list[ToolResultSnapshot] = []
        if tool_results:
            tool_snapshots.extend(tool_snapshots_from(tool_results))
        elif payload is not None:
            tool_snapshots.extend(payload.tool_results)
        else:
            tool_snapshots.extend(tool_snapshots_from(raw_result_mapping))

        if not tool_snapshots and isinstance(raw_result_mapping, Mapping):
            try:
                snapshot = ToolResultSnapshot.from_dict(raw_result_mapping)
            except Exception:
                snapshot = None
            if snapshot is not None:
                tool_snapshots.append(snapshot)
        tool_payloads = tool_snapshot_dicts(tool_snapshots)

        previous_steps = cls._sanitize_llm_step_sequence(
            previous_diagnostic.get("llm_steps")
            if isinstance(previous_diagnostic, Mapping)
            else None
        )

        llm_request_sequence: list[dict[str, Any]] = []
        llm_request_messages: list[dict[str, Any]] = []
        planned_tool_calls: list[Any] | None = None
        llm_final_message: str | None = None
        error_payload: Any | None = None
        diagnostic_sections: Any | None = None
        reasoning_payload: list[dict[str, Any]] | None = None
        llm_trace_payload: dict[str, Any] | None = None

        diagnostic_from_payload: Mapping[str, Any] | None = None

        if payload is not None:
            llm_trace_payload = payload.llm_trace.to_dict()
            diagnostic_from_payload = (
                payload.diagnostic if isinstance(payload.diagnostic, Mapping) else None
            )
            raw_sequence = [
                {"step": step.index, "messages": step.request}
                for step in payload.llm_trace.steps
            ]
            llm_request_sequence = cls._sanitize_llm_requests(raw_sequence)
            if not llm_request_sequence and diagnostic_from_payload is not None:
                llm_request_sequence = cls._sanitize_llm_requests(
                    diagnostic_from_payload.get("llm_requests")
                )
            if llm_request_sequence:
                llm_request_messages = llm_request_sequence[-1]["messages"]
            planned_tool_calls = cls._sanitize_planned_tool_calls(payload.llm_trace)
            final_text = normalize_for_display(payload.result_text or "").strip()
            if not final_text:
                steps = payload.llm_trace.steps
                if steps:
                    last_response = steps[-1].response
                    if isinstance(last_response, Mapping):
                        content_value = last_response.get("content")
                        if isinstance(content_value, str):
                            final_text = normalize_for_display(content_value).strip()
            llm_final_message = final_text or None
            if diagnostic_from_payload:
                error_payload = history_json_safe(diagnostic_from_payload.get("error"))
                diagnostic_sections = history_json_safe(diagnostic_from_payload)
            elif payload.error is not None:
                error_payload = history_json_safe(payload.error.to_dict())
            reasoning_payload = [
                dict(segment)
                for segment in cls._normalise_reasoning_segments(payload.reasoning)
            ] or None
            current_steps = cls._sanitize_llm_step_sequence(
                [
                    {
                        "step": step.index,
                        "occurred_at": step.occurred_at,
                        "request": step.request,
                        "response": step.response,
                    }
                    for step in payload.llm_trace.steps
                ]
            )
            if not current_steps and diagnostic_from_payload is not None:
                current_steps = cls._sanitize_llm_step_sequence(
                    diagnostic_from_payload.get("llm_steps")
                )
        else:
            current_steps = []
            if isinstance(raw_result_mapping, Mapping):
                diagnostic_raw = raw_result_mapping.get("diagnostic")
                if isinstance(diagnostic_raw, Mapping):
                    error_payload = history_json_safe(diagnostic_raw.get("error"))
                    diagnostic_sections = history_json_safe(diagnostic_raw)
                    llm_request_sequence = cls._sanitize_llm_requests(
                        diagnostic_raw.get("llm_requests")
                    )
                    if llm_request_sequence:
                        llm_request_messages = llm_request_sequence[-1]["messages"]
                    current_steps = cls._sanitize_llm_step_sequence(
                        diagnostic_raw.get("llm_steps")
                    )
                elif "error" in raw_result_mapping:
                    error_payload = history_json_safe(raw_result_mapping.get("error"))

        if not current_steps:
            current_steps = previous_steps

        if not llm_request_sequence:
            llm_request_messages = [
                {"role": "system", "content": normalize_for_display(SYSTEM_PROMPT)},
                *history_messages,
                *context_messages,
                {"role": "user", "content": prompt_text},
            ]
            llm_request_sequence = [
                {"step": 1, "messages": list(llm_request_messages)}
            ]

        if not tool_payloads and isinstance(raw_result_mapping, Mapping):
            tool_name_value = raw_result_mapping.get("tool_name")
            if tool_name_value:
                call_id_value = raw_result_mapping.get("tool_call_id") or raw_result_mapping.get(
                    "call_id"
                )
                tool_payloads = [
                    {
                        "tool_name": tool_name_value,
                        "tool_call_id": call_id_value,
                        "call_id": call_id_value,
                        "tool_arguments": raw_result_mapping.get("tool_arguments")
                        or raw_result_mapping.get("arguments")
                        or {},
                        "ok": raw_result_mapping.get("ok"),
                        "error": raw_result_mapping.get("error"),
                    }
                ]

        if llm_final_message is None and isinstance(error_payload, Mapping):
            details = error_payload.get("details")
            if isinstance(details, Mapping):
                message_value = details.get("llm_message")
                if isinstance(message_value, str) and message_value.strip():
                    llm_final_message = normalize_for_display(message_value).strip()
                if planned_tool_calls is None:
                    planned_tool_calls = cls._sanitize_planned_tool_calls(
                        details.get("llm_tool_calls")
                    )

        diagnostic_payload = {
            "prompt_text": prompt_text,
            "prompt_at": prompt_at,
            "response_at": response_at,
            "history_messages": history_messages,
            "context_messages": context_messages,
            "llm_request_messages": llm_request_messages,
            "llm_request_messages_sequence": llm_request_sequence,
            "llm_requests": llm_request_sequence,
            "llm_trace": llm_trace_payload,
            "llm_steps": current_steps,
            "llm_final_message": llm_final_message,
            "llm_tool_calls": planned_tool_calls,
            "tool_exchanges": tool_payloads,
            "tool_results": tool_payloads,
            "agent_response_text": display_text,
            "agent_stored_response": stored_text
            if stored_text != display_text
            else None,
            "raw_result": raw_result_safe,
            "error_payload": error_payload,
            "custom_system_prompt": normalize_for_display(custom_system_prompt)
            if custom_system_prompt
            else None,
            "reasoning": reasoning_payload,
            "diagnostic": diagnostic_sections,
        }

        if isinstance(previous_diagnostic, Mapping):
            existing_log = previous_diagnostic.get("event_log")
            if isinstance(existing_log, list):
                sanitized_log = [
                    history_json_safe(record)
                    for record in existing_log
                    if isinstance(record, Mapping)
                ]
                if sanitized_log:
                    diagnostic_payload["event_log"] = sanitized_log

        return history_json_safe(diagnostic_payload)

    def _handle_streamed_tool_results(
        self,
        handle: _AgentRunHandle,
        tool_results: Sequence[ToolResultSnapshot] | None,
    ) -> None:
        """Update transcript with in-flight tool results for *handle*."""
        if handle.is_cancelled:
            return
        if handle is not self._active_handle():
            return
        entry = handle.pending_entry
        if entry is None:
            return
        conversation = self._get_conversation_by_id(handle.conversation_id)
        entry_id = self._entry_identifier(conversation, entry)
        if not tool_results:
            entry.tool_results = None
            self._request_transcript_refresh(
                conversation=conversation,
                entry_ids=[entry_id] if entry_id else None,
                force=entry_id is None,
            )
            return

        snapshots = tool_snapshots_from(tool_results)
        if not snapshots:
            entry.tool_results = None
            return

        for snapshot in snapshots:
            timestamp = (
                snapshot.last_observed_at
                or snapshot.completed_at
                or snapshot.started_at
                or utc_now_iso()
            )
            existing = handle.tool_snapshots.get(snapshot.call_id or "")
            existing_started = getattr(existing, "started_at", None)
            call_key = snapshot.call_id or ""
            first_seen = self._tool_first_seen.get(call_key)
            if first_seen is None:
                self._tool_first_seen[call_key] = timestamp
                first_seen = timestamp
            if snapshot.started_at is None:
                snapshot.started_at = existing_started or first_seen
            elif existing_started:
                snapshot.started_at = min(snapshot.started_at, existing_started)
            else:
                snapshot.started_at = min(snapshot.started_at, first_seen)
            if snapshot.last_observed_at is None:
                snapshot.last_observed_at = timestamp
            if snapshot.status in {"succeeded", "failed"} and snapshot.completed_at is None:
                snapshot.completed_at = snapshot.last_observed_at or timestamp

        cloned_results = tool_snapshot_dicts(snapshots)
        for snapshot in snapshots:
            self._append_event_log(
                entry,
                kind="tool_result",
                payload=snapshot.to_dict(),
                occurred_at=snapshot.last_observed_at or snapshot.started_at,
                source="tool_stream",
            )
        entry.tool_results = cloned_results if cloned_results else None
        self._request_transcript_refresh(
            conversation=conversation,
            entry_ids=[entry_id] if entry_id else None,
            force=entry_id is None,
        )

    def _handle_llm_step(
        self,
        handle: _AgentRunHandle,
        payload: Mapping[str, Any] | None,
    ) -> None:
        """Update pending entry with the latest LLM step details."""
        if handle.is_cancelled:
            return
        if handle is not self._active_handle():
            return
        entry = handle.pending_entry
        if entry is None:
            return
        if not isinstance(payload, Mapping):
            return
        occurred_at = None
        occurred_value = payload.get("occurred_at") or payload.get("timestamp")
        if isinstance(occurred_value, str) and occurred_value.strip():
            occurred_at = occurred_value
        self._append_event_log(
            entry,
            kind="llm_step",
            payload=payload,
            occurred_at=occurred_at,
            source="llm_stream",
        )
        response_payload = payload.get("response")
        updated = False
        updated |= self._update_entry_llm_steps(entry, payload)
        request_messages = payload.get("request_messages")
        if entry.context_messages is None and isinstance(request_messages, Sequence):
            entry.context_messages = self._clone_context_messages(request_messages)
            updated = True
        if isinstance(response_payload, Mapping):
            content_value = response_payload.get("content")
            if isinstance(content_value, str):
                text = normalize_for_display(content_value)
                if text and text != entry.display_response:
                    entry.response = text
                    entry.display_response = text
                    handle.latest_llm_response = text
                    updated = True
            reasoning_payload = response_payload.get("reasoning")
            reasoning_segments = self._normalise_reasoning_segments(reasoning_payload)
            if reasoning_segments:
                entry.reasoning = reasoning_segments
                handle.latest_reasoning_segments = reasoning_segments
                updated = True
        if updated:
            conversation = self._get_conversation_by_id(handle.conversation_id)
            entry_id = self._entry_identifier(conversation, entry)
            self._request_transcript_refresh(
                conversation=conversation,
                entry_ids=[entry_id] if entry_id else None,
                force=entry_id is None,
            )

    def _update_entry_llm_steps(
        self, entry: ChatEntry, payload: Mapping[str, Any]
    ) -> bool:
        safe_payload = history_json_safe(payload)
        if not isinstance(safe_payload, Mapping):
            return False
        record = dict(safe_payload)

        diagnostic = entry.diagnostic
        if not isinstance(diagnostic, dict):
            diagnostic = {}
            entry.diagnostic = diagnostic

        steps = diagnostic.get("llm_steps")
        if isinstance(steps, list):
            step_key = record.get("step")
            key_text = str(step_key) if step_key is not None else None
            for index, existing in enumerate(steps):
                if not isinstance(existing, Mapping):
                    continue
                existing_key = existing.get("step")
                if key_text is not None and str(existing_key) == key_text:
                    if dict(existing) == record:
                        return False
                    steps[index] = record
                    return True
            steps.append(record)
            return True

        diagnostic["llm_steps"] = [record]
        return True

    def _compose_transcript_text(self) -> str:
        conversation = self._get_active_conversation_loaded()
        if conversation is None:
            return compose_transcript_text(None)
        if self._transcript_refresh_scheduled:
            self._flush_pending_transcript_refresh(immediate=True)
        timeline = self._latest_timeline
        if timeline is None or timeline.conversation_id != conversation.conversation_id:
            timeline = self._timeline_cache.timeline_for(conversation)
        return compose_transcript_text(conversation, timeline=timeline)


    def _compose_transcript_log_text(self) -> str:
        conversation = self._get_active_conversation_loaded()
        if conversation is None:
            return compose_transcript_log_text(None)
        if self._transcript_refresh_scheduled:
            self._flush_pending_transcript_refresh(immediate=True)
        timeline = self._latest_timeline
        if timeline is None or timeline.conversation_id != conversation.conversation_id:
            timeline = self._timeline_cache.timeline_for(conversation)
        return compose_transcript_log_text(conversation, timeline=timeline)


    def _entry_identifier(
        self, conversation: ChatConversation | None, entry: ChatEntry | None
    ) -> str | None:
        if conversation is None or entry is None:
            return None
        self._session.history.ensure_conversation_entries(conversation)
        try:
            index = conversation.entries.index(entry)
        except ValueError:
            return None
        return f"{conversation.conversation_id}:{index}"

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
        self._set_project_documents_subdirectory(
            self._project_settings.documents_path, update_ui=False
        )
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
        tooltip_lines: list[str] = []
        if prompt:
            tooltip_lines.append(
                _(
                    "Custom instructions appended to the system prompt:\n"
                    "{instructions}"
                ).format(
                    instructions=normalize_for_display(prompt)
                )
            )
        else:
            tooltip_lines.append(
                _(
                    "Define project-specific instructions appended to the "
                    "system prompt."
                )
            )
        project_override = getattr(self, "_project_documents_subdirectory", "")
        default_documents = getattr(self, "_default_documents_subdirectory", "")
        subdirectory = self.documents_subdirectory
        if subdirectory:
            resolved = self.documents_root
            if project_override:
                tooltip_lines.append(
                    _("Project override: {path}").format(
                        path=normalize_for_display(project_override)
                    )
                )
            elif default_documents:
                tooltip_lines.append(
                    _("Default from MCP settings: {path}").format(
                        path=normalize_for_display(default_documents)
                    )
                )
            if resolved is not None:
                tooltip_lines.append(
                    _("Documentation folder: {path}").format(
                        path=normalize_for_display(str(resolved))
                    )
                )
            else:
                tooltip_lines.append(
                    _(
                        "Documentation folder pending: {path} "
                        "(open a requirements folder)"
                    ).format(path=normalize_for_display(subdirectory))
                )
        else:
            tooltip_lines.append(_("Documentation folder access disabled."))
        button.SetToolTip("\n\n".join(tooltip_lines))
        button.Enable(not self._session.is_running)

    def _apply_project_settings(
        self,
        settings: AgentProjectSettings,
        *,
        persist: bool = True,
    ) -> None:
        normalized = settings.normalized()
        if normalized == self._project_settings:
            self._set_project_documents_subdirectory(normalized.documents_path)
            self._update_project_settings_ui()
            return
        self._project_settings = normalized
        if persist:
            self._save_project_settings()
        self._set_project_documents_subdirectory(
            normalized.documents_path, update_ui=False
        )
        self._update_project_settings_ui()
        self._update_conversation_header()

    def _on_project_settings(self, _event: wx.Event) -> None:
        dialog = AgentProjectSettingsDialog(self, settings=self._project_settings)
        try:
            result = dialog.ShowModal()
            if result != wx.ID_OK:
                return
            prompt = dialog.get_custom_system_prompt()
            documents_path = dialog.get_documents_path()
            self._apply_project_settings(
                AgentProjectSettings(
                    custom_system_prompt=prompt,
                    documents_path=documents_path,
                )
            )
        finally:
            dialog.Destroy()

    def _notify_documents_root_listener(self) -> None:
        callback = getattr(self, "_documents_root_listener", None)
        if callback is None:
            return
        try:
            callback(self._documents_root)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Failed to notify documents root listener")

    def _resolve_documents_root(self) -> Path | None:
        base = getattr(self, "_requirements_directory", None)
        base_text = str(base) if base is not None else None
        resolved = resolve_documents_root(base_text, self.documents_subdirectory)
        return resolved

    def _update_documents_root(self) -> None:
        resolved = self._resolve_documents_root()
        current = getattr(self, "_documents_root", None)
        if current == resolved:
            return
        self._documents_root = resolved
        self._notify_documents_root_listener()
        self._update_project_settings_ui()

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

    def _get_active_conversation_loaded(self) -> ChatConversation | None:
        conversation = self._get_active_conversation()
        if conversation is None:
            return None
        self._session.history.ensure_conversation_entries(conversation)
        return conversation

    def _create_conversation(self, *, persist: bool) -> ChatConversation:
        conversation = ChatConversation.new()
        self._register_conversation(conversation)
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
        title = (conversation.title or "").strip()
        if not title:
            if conversation.entries_loaded and conversation.entries:
                title = conversation.derive_title().strip()
            elif conversation.preview:
                title = conversation.preview.strip()
        if not title:
            title = _("New chat")
        if len(title) > 60:
            title = title[:57] + "…"
        last_activity = format_last_activity(conversation.updated_at)
        title = normalize_for_display(title)
        return title, last_activity


    def _conversation_preview(self, conversation: ChatConversation) -> str:
        preview = conversation.preview
        if not preview and conversation.entries_loaded and conversation.entries:
            conversation.recalculate_preview()
            preview = conversation.preview
        if not preview:
            return ""
        return normalize_for_display(preview)

    def _on_history_row_activated(self, index: int) -> None:
        self._activate_conversation_by_index(
            index, persist=True, refresh_history=False, _source="history_row"
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
        self.history_list.Enable(has_conversations)
        if self._new_chat_btn is not None:
            self._new_chat_btn.Enable(True)

    def _on_new_chat(self, _event: wx.Event) -> None:
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
        return getattr(coordinator, "active_handle", None)

    @property
    def history(self) -> list[ChatEntry]:
        """Return entries for the active conversation or an empty list."""
        conversation = self._get_active_conversation_loaded()
        if conversation is None:
            return []
        return list(conversation.entries)

