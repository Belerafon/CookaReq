"""Batch execution helper for the agent chat panel."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any
from collections.abc import Callable, Mapping, Sequence

from ...util.time import utc_now_iso

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BatchTarget:
    """Descriptor of a requirement selected for batch processing."""

    requirement_id: int
    rid: str
    title: str


class BatchItemStatus(Enum):
    """Lifecycle states for entries in the batch queue."""

    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass(slots=True)
class BatchItem:
    """Runtime metadata for an entry within the batch queue."""

    target: BatchTarget
    conversation_id: str | None = None
    status: BatchItemStatus = BatchItemStatus.PENDING
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    tool_call_count: int = 0
    requirement_edit_count: int = 0
    error_count: int = 0
    token_count: int | None = None
    tokens_approximate: bool = False


class CancelMode(Enum):
    """Describe follow-up action after cancelling the active item."""

    NONE = auto()
    SKIP_CURRENT = auto()
    STOP_ALL = auto()


_METRIC_UNSET = object()


class AgentBatchRunner:
    """Manage sequential execution of prompts for selected requirements."""

    def __init__(
        self,
        *,
        submit_prompt: Callable[
            [
                str,
                str,
                Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
                str | None,
            ],
            None,
        ],
        create_conversation: Callable[[], Any],
        ensure_conversation_id: Callable[[Any], str],
        on_state_changed: Callable[[], None],
        context_factory: Callable[[BatchTarget], Sequence[Mapping[str, Any]] | Mapping[str, Any] | None],
        prepare_conversation: Callable[[Any, BatchTarget], None] | None = None,
    ) -> None:
        self._submit_prompt = submit_prompt
        self._create_conversation = create_conversation
        self._ensure_conversation_id = ensure_conversation_id
        self._on_state_changed = on_state_changed
        self._context_factory = context_factory
        self._prepare_conversation = prepare_conversation
        self._items: list[BatchItem] = []
        self._prompt: str | None = None
        self._active_index: int | None = None
        self._cancel_mode = CancelMode.NONE
        self._running = False

    # ------------------------------------------------------------------
    @property
    def items(self) -> tuple[BatchItem, ...]:
        """Return immutable snapshot of queued items."""
        return tuple(self._items)

    # ------------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    @property
    def active_item(self) -> BatchItem | None:
        if self._active_index is None:
            return None
        try:
            return self._items[self._active_index]
        except IndexError:  # pragma: no cover - defensive
            return None

    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Clear the queue without notifying the controller."""
        self._items.clear()
        self._prompt = None
        self._active_index = None
        self._cancel_mode = CancelMode.NONE
        self._running = False
        self._on_state_changed()

    # ------------------------------------------------------------------
    def start(self, prompt: str, targets: Sequence[BatchTarget]) -> bool:
        """Initialise queue with *targets* and launch the first run."""
        normalized = prompt.strip()
        if not normalized:
            return False
        if self._running:
            return False

        self._items = [BatchItem(target=target) for target in targets]
        self._prompt = normalized
        self._active_index = None
        self._cancel_mode = CancelMode.NONE
        self._running = bool(self._items)
        self._on_state_changed()
        if not self._items:
            return False
        self._advance()
        return True

    # ------------------------------------------------------------------
    def cancel_all(self) -> None:
        """Request cancellation of the active item and mark queue as cancelled."""
        if not self._items:
            return

        self._cancel_mode = CancelMode.STOP_ALL
        for item in self._items:
            if item.status is BatchItemStatus.PENDING:
                item.status = BatchItemStatus.CANCELLED
                item.finished_at = utc_now_iso()
        self._on_state_changed()

    # ------------------------------------------------------------------
    def request_skip_current(self) -> None:
        """Request cancellation of current item while keeping queue running."""
        if not self._running:
            return
        self._cancel_mode = CancelMode.SKIP_CURRENT

    # ------------------------------------------------------------------
    def handle_completion(
        self,
        *,
        conversation_id: str | None,
        success: bool,
        error: str | None,
        tool_call_count: int | None = None,
        requirement_edit_count: int | None = None,
        error_count: int | None = None,
        token_count: object = _METRIC_UNSET,
        tokens_approximate: bool | None = None,
    ) -> None:
        """Update queue state after controller finalises the prompt."""
        if not conversation_id:
            return
        item = self._item_by_conversation(conversation_id)
        if item is None:
            return
        item.finished_at = utc_now_iso()
        if success:
            item.status = BatchItemStatus.COMPLETED
            item.error = None
        else:
            item.status = BatchItemStatus.FAILED
            item.error = error
        if tool_call_count is not None:
            item.tool_call_count = tool_call_count
        if requirement_edit_count is not None:
            item.requirement_edit_count = requirement_edit_count
        if error_count is not None:
            item.error_count = error_count
        if token_count is not _METRIC_UNSET:
            if token_count is None or isinstance(token_count, int):
                item.token_count = token_count
        if tokens_approximate is not None:
            item.tokens_approximate = tokens_approximate
        self._active_index = None
        self._on_state_changed()
        self._advance()

    # ------------------------------------------------------------------
    def handle_cancellation(self, *, conversation_id: str | None) -> None:
        """React to cancelled prompt and continue if needed."""
        if not conversation_id:
            return
        item = self._item_by_conversation(conversation_id)
        if item is None:
            return
        item.finished_at = utc_now_iso()
        item.status = BatchItemStatus.CANCELLED
        self._active_index = None
        mode = self._cancel_mode
        self._cancel_mode = CancelMode.NONE
        self._on_state_changed()
        if mode is CancelMode.STOP_ALL:
            self._running = False
            self._on_state_changed()
            return
        self._advance()

    # ------------------------------------------------------------------
    def progress_counts(self) -> tuple[int, int]:
        """Return tuple ``(completed, total)`` ignoring skipped entries."""
        total = len(self._items)
        completed = sum(
            1
            for item in self._items
            if item.status in {BatchItemStatus.COMPLETED, BatchItemStatus.FAILED, BatchItemStatus.CANCELLED}
        )
        return completed, total

    # ------------------------------------------------------------------
    def _item_by_conversation(self, conversation_id: str) -> BatchItem | None:
        for index, item in enumerate(self._items):
            if item.conversation_id == conversation_id:
                self._active_index = index
                return item
        return None

    # ------------------------------------------------------------------
    def _advance(self) -> None:
        if not self._running:
            return
        for index, item in enumerate(self._items):
            if item.status is BatchItemStatus.PENDING:
                self._start_item(index)
                return
        self._running = False
        self._active_index = None
        self._on_state_changed()

    # ------------------------------------------------------------------
    def _start_item(self, index: int) -> None:
        prompt = self._prompt
        if not prompt:
            return
        try:
            conversation = self._create_conversation()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to create conversation for batch item")
            item = self._items[index]
            item.status = BatchItemStatus.FAILED
            item.error = "failed to create conversation"
            item.finished_at = utc_now_iso()
            self._on_state_changed()
            self._advance()
            return

        item = self._items[index]
        item.started_at = utc_now_iso()
        try:
            item.conversation_id = self._ensure_conversation_id(conversation)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Conversation missing identifier in batch runner")
            item.status = BatchItemStatus.FAILED
            item.error = "conversation missing identifier"
            item.finished_at = utc_now_iso()
            self._on_state_changed()
            self._advance()
            return

        if self._prepare_conversation is not None:
            try:
                self._prepare_conversation(conversation, item.target)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to prepare batch conversation %s", item.target.rid)

        item.status = BatchItemStatus.RUNNING
        item.error = None
        self._active_index = index
        self._on_state_changed()

        context: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None
        try:
            context = self._context_factory(item.target)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Failed to prepare batch context for %s", item.target.rid)
            item.status = BatchItemStatus.FAILED
            item.error = str(exc)
            item.finished_at = utc_now_iso()
            self._on_state_changed()
            self._advance()
            return

        prompt_at = item.started_at or utc_now_iso()
        try:
            self._submit_prompt(
                prompt,
                item.conversation_id,
                context,
                prompt_at,
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to submit batch prompt")
            item.status = BatchItemStatus.FAILED
            item.error = "failed to submit prompt"
            item.finished_at = utc_now_iso()
            self._on_state_changed()
            self._advance()


__all__ = [
    "AgentBatchRunner",
    "BatchItem",
    "BatchItemStatus",
    "BatchTarget",
]
