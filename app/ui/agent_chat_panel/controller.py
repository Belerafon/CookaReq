"""Agent run controller decoupling execution logic from the wx panel."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable

import wx

from ...llm.tokenizer import TokenCountResult, count_text_tokens
from ...util.cancellation import CancellationEvent, OperationCancelledError
from ...util.time import utc_now_iso
from ..chat_entry import ChatConversation, ChatEntry
from .execution import AgentCommandExecutor, _AgentRunHandle
from .history_utils import clone_streamed_tool_results

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentRunCallbacks:
    """Callables used by :class:`AgentRunController` to update the UI."""

    ensure_active_conversation: Callable[[], ChatConversation]
    get_conversation_by_id: Callable[[str], ChatConversation | None]
    conversation_messages: Callable[[], tuple[dict[str, Any], ...]]
    prepare_context_messages: Callable[[
        Mapping[str, Any] | Sequence[Mapping[str, Any]] | None
    ], tuple[dict[str, Any], ...]]
    add_pending_entry: Callable[
        [ChatConversation, str, str, tuple[dict[str, Any], ...] | None], ChatEntry
    ]
    is_running: Callable[[], bool]
    persist_history: Callable[[], None]
    refresh_history: Callable[[], None]
    render_transcript: Callable[[], None]
    set_wait_state: Callable[[bool, TokenCountResult | None], None]
    confirm_override_kwargs: Callable[[], dict[str, Any]]
    finalize_prompt: Callable[[str, Any, _AgentRunHandle], None]
    handle_streamed_tool_results: Callable[[
        _AgentRunHandle, Sequence[Mapping[str, Any]] | None
    ], None]


class AgentRunController:
    """Coordinate asynchronous agent interactions for the chat panel."""

    def __init__(
        self,
        *,
        agent_supplier: Callable[..., Any],
        command_executor: AgentCommandExecutor,
        token_model_resolver: Callable[[], str | None],
        context_provider: Callable[
            [], Mapping[str, Any] | Sequence[Mapping[str, Any]] | None
        ] | None,
        callbacks: AgentRunCallbacks,
    ) -> None:
        self._agent_supplier = agent_supplier
        self._command_executor = command_executor
        self._token_model_resolver = token_model_resolver
        self._context_provider = context_provider
        self._callbacks = callbacks
        self._run_counter = 0
        self._active_handle: _AgentRunHandle | None = None

    # ------------------------------------------------------------------
    @property
    def active_handle(self) -> _AgentRunHandle | None:
        return self._active_handle

    # ------------------------------------------------------------------
    def submit_prompt(self, prompt: str, *, prompt_at: str | None = None) -> None:
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
        self._active_handle = handle

        conversation = self._callbacks.ensure_active_conversation()
        history_messages = self._callbacks.conversation_messages()
        context_messages: tuple[dict[str, Any], ...] | None = None
        if self._context_provider is not None:
            try:
                provided_context = self._context_provider()
            except Exception:  # pragma: no cover - defensive logging
                logger.exception("Failed to collect agent context")
                provided_context = None
            context_messages = self._callbacks.prepare_context_messages(provided_context)
            if not context_messages:
                context_messages = None
        handle.context_messages = context_messages
        if history_messages:
            handle.history_snapshot = tuple(dict(message) for message in history_messages)
        else:
            handle.history_snapshot = None

        pending_entry = self._callbacks.add_pending_entry(
            conversation,
            normalized_prompt,
            effective_prompt_at,
            context_messages,
        )
        handle.conversation_id = conversation.conversation_id
        handle.pending_entry = pending_entry
        self._callbacks.persist_history()
        self._callbacks.refresh_history()
        self._callbacks.render_transcript()
        self._callbacks.set_wait_state(True, prompt_tokens)

        def worker() -> Any:
            try:
                overrides = self._callbacks.confirm_override_kwargs()
                agent = self._agent_supplier(**overrides)

                def _merge_streamed_tool_result(payload: dict[str, Any]) -> None:
                    call_id = payload.get("call_id") or payload.get("tool_call_id")
                    if not call_id:
                        handle.streamed_tool_results.append(payload)
                        return
                    for index, existing in enumerate(handle.streamed_tool_results):
                        existing_id = existing.get("call_id") or existing.get("tool_call_id")
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
                    snapshot = clone_streamed_tool_results(handle.streamed_tool_results)
                    wx.CallAfter(
                        self._callbacks.handle_streamed_tool_results,
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
                logger.exception("Agent command failed", exc_info=exc)
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

    # ------------------------------------------------------------------
    def stop(self) -> _AgentRunHandle | None:
        handle = self._active_handle
        if handle is None:
            return None
        handle.cancel()
        self._active_handle = None
        return handle

    # ------------------------------------------------------------------
    def regenerate_entry(self, conversation_id: str, entry: ChatEntry) -> None:
        if self._callbacks.is_running():
            return
        conversation = self._callbacks.get_conversation_by_id(conversation_id)
        if conversation is None or not conversation.entries:
            return
        if entry is not conversation.entries[-1]:
            return
        prompt = entry.prompt
        if not prompt.strip():
            return
        previous_state = entry.regenerated
        entry.regenerated = True
        try:
            self._callbacks.persist_history()
            self._callbacks.refresh_history()
            self._callbacks.render_transcript()
            self.submit_prompt(prompt)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to regenerate agent response")
            entry.regenerated = previous_state
            self._callbacks.persist_history()
            self._callbacks.refresh_history()
            self._callbacks.render_transcript()

    # ------------------------------------------------------------------
    def _finalize_prompt(self, prompt: str, result: Any, handle: _AgentRunHandle) -> None:
        self._callbacks.finalize_prompt(prompt, result, handle)
        if self._active_handle is handle:
            self._active_handle = None

    # ------------------------------------------------------------------
    def reset_active_handle(self, handle: _AgentRunHandle) -> None:
        if self._active_handle is handle:
            self._active_handle = None

    # ------------------------------------------------------------------
    def _token_model(self) -> str | None:
        try:
            return self._token_model_resolver()
        except Exception:  # pragma: no cover - defensive
            return None


__all__ = ["AgentRunController", "AgentRunCallbacks"]
