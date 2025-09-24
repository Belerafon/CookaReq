"""Execution helpers for the agent chat panel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from concurrent.futures import Future, ThreadPoolExecutor

from ...util.cancellation import CancellationEvent
from ...llm.tokenizer import TokenCountResult
from .history_utils import clone_streamed_tool_results


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
    pending_entry: Any | None = None
    context_messages: tuple[dict[str, Any], ...] | None = None
    history_snapshot: tuple[dict[str, Any], ...] | None = None
    streamed_tool_results: list[dict[str, Any]] = field(default_factory=list)
    notified_tool_results: int = 0

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self) -> None:
        self.cancel_event.set()
        future = self.future
        if future is not None:
            future.cancel()

    def prepare_tool_results_payload(
        self,
    ) -> tuple[dict[str, Any], ...] | None:
        """Return an immutable snapshot of collected tool payloads."""

        if not self.streamed_tool_results:
            return None
        return clone_streamed_tool_results(self.streamed_tool_results)


__all__ = [
    "AgentCommandExecutor",
    "ThreadedAgentCommandExecutor",
    "_AgentRunHandle",
]
