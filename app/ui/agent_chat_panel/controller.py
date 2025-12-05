"""Agent run controller decoupling execution logic from the wx panel."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import wx

from ...llm.reasoning import normalise_reasoning_segments
from ...llm.tokenizer import TokenCountResult, count_text_tokens
from ...util.cancellation import CancellationEvent, OperationCancelledError
from ...util.time import utc_now_iso
from ...agent.run_contract import ToolResultSnapshot
from .execution import AgentCommandExecutor, _AgentRunHandle
from .history_utils import history_json_safe

if TYPE_CHECKING:
    from ..chat_entry import ChatConversation, ChatEntry

logger = logging.getLogger(__name__)


def _call_supports_keyword(func: Any, name: str) -> bool:
    """Return True when *func* accepts the keyword argument ``name``."""
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):  # pragma: no cover - fallback for builtins
        return True
    parameters = signature.parameters
    if name in parameters:
        return True
    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


@dataclass(slots=True)
class RemovedConversationEntry:
    """Container describing an entry removed from a conversation."""

    index: int
    entry: ChatEntry
    previous_updated_at: str


@dataclass(slots=True)
class AgentRunCallbacks:
    """Callables used by :class:`AgentRunController` to update the UI."""

    ensure_active_conversation: Callable[[], ChatConversation]
    get_conversation_by_id: Callable[[str], ChatConversation | None]
    conversation_messages: Callable[[], tuple[dict[str, Any], ...]]
    conversation_messages_for: Callable[[ChatConversation], tuple[dict[str, Any], ...]]
    prepare_context_messages: Callable[[
        Mapping[str, Any] | Sequence[Mapping[str, Any]] | None
    ], tuple[dict[str, Any], ...]]
    add_pending_entry: Callable[
        [ChatConversation, str, str, tuple[dict[str, Any], ...] | None], ChatEntry
    ]
    remove_entry: Callable[[ChatConversation, ChatEntry], RemovedConversationEntry | None]
    restore_entry: Callable[[ChatConversation, RemovedConversationEntry], None]
    is_running: Callable[[], bool]
    persist_history: Callable[[], None]
    refresh_history: Callable[[], None]
    render_transcript: Callable[[], None]
    set_wait_state: Callable[[bool, TokenCountResult | None], None]
    confirm_override_kwargs: Callable[[], dict[str, Any]]
    finalize_prompt: Callable[[str, Any, _AgentRunHandle], None]
    handle_streamed_tool_results: Callable[[
        _AgentRunHandle, Sequence[ToolResultSnapshot] | None
    ], None]
    handle_llm_step: Callable[[
        _AgentRunHandle, Mapping[str, Any] | None
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
        history_payload = tuple(dict(message) for message in history_messages)
        self._start_prompt(
            conversation=conversation,
            normalized_prompt=normalized_prompt,
            prompt_at=effective_prompt_at,
            history_messages=history_payload,
            context_messages=context_messages,
        )

    # ------------------------------------------------------------------
    def submit_prompt_with_context(
        self,
        prompt: str,
        *,
        conversation_id: str,
        context_messages: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
        prompt_at: str | None = None,
        prepared_context: bool = False,
    ) -> None:
        normalized_prompt = prompt.strip()
        if not normalized_prompt:
            return

        conversation = self._callbacks.get_conversation_by_id(conversation_id)
        if conversation is None:
            conversation = self._callbacks.ensure_active_conversation()
            if conversation.conversation_id != conversation_id:  # pragma: no cover - defensive
                logger.warning(
                    "Conversation %s not found for custom context run; using active conversation %s",
                    conversation_id,
                    conversation.conversation_id,
                )
        history_messages = self._callbacks.conversation_messages_for(conversation)
        context_payload: tuple[dict[str, Any], ...] | None
        if prepared_context:
            context_payload = (
                tuple(dict(message) for message in context_messages)
                if context_messages
                else None
            )
        else:
            prepared_context_messages = self._callbacks.prepare_context_messages(
                context_messages
            )
            context_payload = prepared_context_messages or None
        history_payload = tuple(dict(message) for message in history_messages)
        effective_prompt_at = prompt_at or utc_now_iso()
        self._start_prompt(
            conversation=conversation,
            normalized_prompt=normalized_prompt,
            prompt_at=effective_prompt_at,
            history_messages=history_payload,
            context_messages=context_payload,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _prepare_llm_step_payload(
        handle: _AgentRunHandle,
        payload: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        safe_payload_raw = history_json_safe(payload)
        if not isinstance(safe_payload_raw, Mapping):
            return None
        record = dict(safe_payload_raw)
        response_payload = payload.get("response")
        if isinstance(response_payload, Mapping):
            content_value = response_payload.get("content")
            if isinstance(content_value, str):
                handle.latest_llm_response = content_value
            reasoning_payload = response_payload.get("reasoning")
            reasoning_segments = normalise_reasoning_segments(reasoning_payload)
            if reasoning_segments:
                handle.latest_reasoning_segments = tuple(
                    dict(segment) for segment in reasoning_segments
                )
        step_key = record.get("step")
        identifier = str(step_key) if step_key is not None else None
        if identifier is not None:
            for index, existing in enumerate(handle.llm_trace_preview):
                existing_step = existing.get("step")
                if isinstance(existing_step, (int, float, str)) and str(existing_step) == identifier:
                    handle.llm_trace_preview[index] = record
                    break
            else:
                handle.llm_trace_preview.append(record)
        else:
            handle.llm_trace_preview.append(record)
        return record

    # ------------------------------------------------------------------
    def _start_prompt(
        self,
        *,
        conversation: ChatConversation,
        normalized_prompt: str,
        prompt_at: str,
        history_messages: tuple[dict[str, Any], ...],
        context_messages: tuple[dict[str, Any], ...] | None,
    ) -> None:
        self._run_counter += 1
        cancel_event = CancellationEvent()
        prompt_tokens = count_text_tokens(normalized_prompt, model=self._token_model())
        handle = _AgentRunHandle(
            run_id=self._run_counter,
            prompt=normalized_prompt,
            prompt_tokens=prompt_tokens,
            cancel_event=cancel_event,
            prompt_at=prompt_at,
        )
        self._active_handle = handle

        history_payload = tuple(dict(message) for message in history_messages)
        context_payload = None
        if context_messages:
            context_payload = tuple(dict(message) for message in context_messages)
        handle.context_messages = context_payload
        handle.history_snapshot = history_payload if history_payload else None

        pending_entry = self._callbacks.add_pending_entry(
            conversation,
            normalized_prompt,
            prompt_at,
            context_payload,
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

                def on_tool_result(payload: Mapping[str, Any]) -> None:
                    if handle.is_cancelled:
                        return
                    if not isinstance(payload, Mapping):
                        return
                    timestamp = utc_now_iso()
                    safe_payload = dict(payload)
                    event = str(safe_payload.get("event") or "").lower()
                    call_id = (
                        safe_payload.get("call_id")
                        or safe_payload.get("tool_call_id")
                        or safe_payload.get("id")
                    )
                    if call_id:
                        safe_payload.setdefault("call_id", call_id)
                        safe_payload.setdefault("tool_call_id", call_id)

                    input_payload = safe_payload.get("input")
                    output_payload = safe_payload.get("output")
                    if isinstance(input_payload, Mapping):
                        safe_payload.setdefault("tool_arguments", dict(input_payload))
                    if isinstance(output_payload, Mapping):
                        if not safe_payload.get("tool_arguments"):
                            arguments_value = output_payload.get("input")
                            if isinstance(arguments_value, Mapping):
                                safe_payload["tool_arguments"] = dict(arguments_value)
                        if not safe_payload.get("tool_name"):
                            tool_name_value = output_payload.get("tool_name") or output_payload.get("name")
                            if tool_name_value:
                                safe_payload["tool_name"] = tool_name_value
                        if output_payload.get("tool_call_id") and not safe_payload.get(
                            "call_id"
                        ):
                            safe_payload["call_id"] = output_payload.get("tool_call_id")
                            safe_payload["tool_call_id"] = output_payload.get("tool_call_id")
                        if "ok" in output_payload:
                            safe_payload.setdefault("ok", output_payload.get("ok"))
                        if "result" in output_payload and not safe_payload.get("result"):
                            safe_payload["result"] = output_payload.get("result")
                        if "error" in output_payload and not safe_payload.get("error"):
                            safe_payload["error"] = output_payload.get("error")

                    if not safe_payload.get("tool_name"):
                        inferred_name = safe_payload.get("name")
                        if inferred_name is None and isinstance(input_payload, Mapping):
                            inferred_name = input_payload.get("tool_name") or input_payload.get("name")
                        safe_payload["tool_name"] = inferred_name or str(call_id or "tool")

                    safe_payload.setdefault("last_observed_at", timestamp)
                    if event in {"tool_started", "tool_running", "started"}:
                        safe_payload.setdefault("started_at", timestamp)
                        safe_payload.setdefault("status", "running")
                    if event in {"tool_finished", "tool_completed", "completed", "failed"}:
                        safe_payload.setdefault("completed_at", timestamp)
                        if "status" not in safe_payload:
                            safe_payload["status"] = "failed" if safe_payload.get("error") else "succeeded"

                    safe_payload = history_json_safe(safe_payload)
                    if not isinstance(safe_payload, Mapping):
                        return
                    ordered = handle.record_tool_snapshot(safe_payload)
                    wx.CallAfter(
                        self._callbacks.handle_streamed_tool_results,
                        handle,
                        ordered,
                    )

                def on_llm_step(payload: Mapping[str, Any]) -> None:
                    if handle.is_cancelled:
                        return
                    if not isinstance(payload, Mapping):
                        return
                    safe_payload = self._prepare_llm_step_payload(handle, payload)
                    if safe_payload is None:
                        return
                    wx.CallAfter(
                        self._callbacks.handle_llm_step,
                        handle,
                        safe_payload,
                    )

                history_arg: tuple[dict[str, Any], ...] | None
                history_arg = history_payload or None

                run_command = agent.run_command
                kwargs = {
                    "history": history_arg,
                    "context": context_payload,
                    "cancellation": handle.cancel_event,
                    "on_tool_result": on_tool_result,
                }
                if _call_supports_keyword(run_command, "on_llm_step"):
                    kwargs["on_llm_step"] = on_llm_step
                return run_command(normalized_prompt, **kwargs)
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
        removal = self._callbacks.remove_entry(conversation, entry)
        if removal is None:
            return
        try:
            self.submit_prompt(prompt)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to regenerate agent response")
            self._callbacks.restore_entry(conversation, removal)

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


__all__ = [
    "AgentRunController",
    "AgentRunCallbacks",
    "RemovedConversationEntry",
]
