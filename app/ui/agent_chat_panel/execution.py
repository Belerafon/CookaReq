"""Execution helpers for the agent chat panel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol
from collections.abc import Callable

from concurrent.futures import Future, ThreadPoolExecutor

from ...agent.run_contract import ToolResultSnapshot
from ...util.cancellation import CancellationEvent
from ...llm.tokenizer import TokenCountResult


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
    tool_snapshots: dict[str, ToolResultSnapshot] = field(default_factory=dict)
    tool_order: list[str] = field(default_factory=list)
    latest_llm_response: str | None = None
    latest_reasoning_segments: tuple[dict[str, str], ...] | None = None
    llm_trace_preview: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self) -> None:
        self.cancel_event.set()
        future = self.future
        if future is not None:
            future.cancel()

    def record_tool_snapshot(
        self, payload: Mapping[str, Any]
    ) -> tuple[ToolResultSnapshot, ...]:
        """Store *payload* as the latest snapshot for its call identifier."""
        try:
            snapshot = ToolResultSnapshot.from_dict(payload)
        except Exception:
            return tuple(self.tool_snapshots[identifier] for identifier in self.tool_order)

        call_id = snapshot.call_id.strip()
        if not call_id:
            call_id = f"{self.run_id}:tool:{len(self.tool_order) + 1}"
            snapshot.call_id = call_id

        self.tool_snapshots[call_id] = snapshot
        if call_id not in self.tool_order:
            self.tool_order.append(call_id)
        return tuple(self.tool_snapshots[identifier] for identifier in self.tool_order)


__all__ = [
    "AgentCommandExecutor",
    "ThreadedAgentCommandExecutor",
    "_AgentRunHandle",
]
