"""Local agent that combines LLM parsing with MCP tool execution.

The agent exposes a deterministic contract: tool executions are captured as
:class:`ToolResultSnapshot` objects while LLM interactions are recorded in an
:class:`LlmTrace`.  The previous heuristic-based payload merging has been
removed in favour of the structured :class:`AgentRunPayload` defined in
``app/agent/run_contract.py``.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence, Protocol, runtime_checkable

from collections.abc import Awaitable

from ..confirm import (
    ConfirmDecision,
    RequirementUpdatePrompt,
    confirm as default_confirm,
    confirm_requirement_update as default_update_confirm,
)
from ..llm.client import LLMClient
from ..llm.context import extract_selected_rids_from_text
from ..llm.reasoning import normalise_reasoning_segments
from ..llm.types import LLMReasoningSegment, LLMResponse, LLMToolCall
from ..llm.validation import ToolValidationError
from ..mcp.client import MCPClient
from ..mcp.utils import exception_to_mcp_error
from ..settings import AppSettings
from ..telemetry import log_debug_payload, log_event
from ..util.cancellation import (
    CancellationEvent,
    OperationCancelledError,
    raise_if_cancelled,
)
from ..util.time import utc_now_iso
from .run_contract import (
    AgentRunPayload,
    LlmTrace,
    ToolError,
    ToolResultSnapshot,
)


@runtime_checkable
class SupportsAgentLLM(Protocol):
    """Interface expected from LLM clients used by :class:`LocalAgent`."""

    async def check_llm_async(self) -> Mapping[str, Any]:
        """Verify that the LLM backend is reachable."""

    async def respond_async(
        self,
        conversation: Sequence[Mapping[str, Any]] | None,
        *,
        cancellation: CancellationEvent | None = None,
    ) -> LLMResponse:
        """Return an assistant reply for *conversation*."""


@runtime_checkable
class SupportsAgentMCP(Protocol):
    """Interface expected from MCP clients used by :class:`LocalAgent`."""

    async def check_tools_async(self) -> Mapping[str, Any]:
        """Verify that MCP tools are reachable."""

    async def ensure_ready_async(self) -> None:
        """Raise an exception when the MCP server is not ready."""

    async def call_tool_async(
        self, name: str, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Invoke MCP tool *name* with *arguments*."""

    async def get_tool_schemas_async(self) -> Mapping[str, Any]:
        """Return MCP-advertised tool schemas."""


class _AgentMCPAdapter(SupportsAgentMCP):
    """Bridge MCP clients that partially implement the async interface."""

    __slots__ = ("_client",)

    _MISSING = object()

    def __init__(self, client: Any) -> None:
        self._client = client

    async def check_tools_async(self) -> Mapping[str, Any]:
        result = await self._call("check_tools_async", fallback="check_tools")
        if isinstance(result, Mapping):
            return result
        raise TypeError(
            "MCP client must return a mapping from check_tools_async/check_tools",
        )

    async def ensure_ready_async(self) -> None:
        await self._call("ensure_ready_async", fallback="ensure_ready", default=None)

    async def call_tool_async(
        self, name: str, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        result = await self._call(
            "call_tool_async",
            fallback="call_tool",
            args=(name, arguments),
        )
        if isinstance(result, Mapping):
            return result
        raise TypeError(
            "MCP client must return a mapping from call_tool_async/call_tool",
        )

    async def get_tool_schemas_async(self) -> Mapping[str, Any]:
        result = await self._call(
            "get_tool_schemas_async",
            fallback="get_tool_schemas",
            default={},
        )
        if isinstance(result, Mapping):
            return result
        return {}

    async def _call(
        self,
        async_name: str,
        *,
        fallback: str | None = None,
        args: tuple[Any, ...] = (),
        default: Any = _MISSING,
    ) -> Any:
        method = getattr(self._client, async_name, None)
        if callable(method):
            return await self._maybe_await(method(*args))
        if fallback:
            fallback_method = getattr(self._client, fallback, None)
            if callable(fallback_method):
                return await self._maybe_await(fallback_method(*args))
        if default is self._MISSING:
            raise TypeError(
                f"MCP client must implement {async_name}() or {fallback}()",
            )
        return default

    async def _maybe_await(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value


@dataclass(slots=True)
class _ToolExecutionOutcome:
    """Outcome of a single MCP call."""

    message: Mapping[str, Any]
    error_payload: Mapping[str, Any] | None


@dataclass(slots=True)
class _ToolExecutionBatchResult:
    """Aggregated outcome of executing a batch of MCP tool calls."""

    messages: list[Mapping[str, Any]]
    successful_results: list[Mapping[str, Any]]
    error_payload: Mapping[str, Any] | None


@dataclass(slots=True)
class _AgentIterationResult:
    """Container describing the outcome of one loop iteration."""

    response: LLMResponse
    tool_error: Mapping[str, Any] | None
    tool_messages: Sequence[Mapping[str, Any]]
    final_payload: AgentRunPayload | None


class _AgentRunRecorder:
    """Collects deterministic artefacts for an agent run."""

    def __init__(self, *, tool_schemas: Mapping[str, Any] | None = None) -> None:
        self._snapshots: dict[str, ToolResultSnapshot] = {}
        self._order: list[str] = []
        self._llm_trace = LlmTrace()
        self._reasoning: list[dict[str, Any]] = []
        self._result_text = ""
        self._ok = False
        self._status: str = "failed"
        self._diagnostic: dict[str, Any] = {}
        self._tool_schemas = dict(tool_schemas) if tool_schemas else {}
        self._error: ToolError | None = None
        self._last_tool: ToolResultSnapshot | None = None
        self._agent_stop_reason: Mapping[str, Any] | None = None
        self._llm_steps: list[dict[str, Any]] = []
        self._llm_requests: list[dict[str, Any]] = []
        self._exclude_from_results: set[str] = set()

    # ------------------------------------------------------------------
    def record_llm_step(
        self,
        *,
        index: int,
        request_messages: Sequence[Mapping[str, Any]],
        response: Mapping[str, Any],
    ) -> None:
        request_snapshot = [dict(message) for message in request_messages]
        response_snapshot = dict(response)
        self._llm_trace.append(
            index=index, request=request_snapshot, response=response_snapshot
        )
        self._llm_steps.append(
            {
                "step": index,
                "request_messages": request_snapshot,
                "response": response_snapshot,
            }
        )
        self._llm_requests.append({"step": index, "messages": request_snapshot})

    def extend_reasoning(
        self, segments: Sequence[LLMReasoningSegment] | None
    ) -> None:
        normalised = normalise_reasoning_segments(segments)
        if not normalised:
            return

        for segment in normalised:
            stored: dict[str, Any] = {
                "type": segment.get("type", ""),
                "text": segment.get("text", ""),
            }
            leading = segment.get("leading_whitespace")
            if isinstance(leading, str) and leading:
                stored["leading_whitespace"] = leading
            trailing = segment.get("trailing_whitespace")
            if isinstance(trailing, str) and trailing:
                stored["trailing_whitespace"] = trailing
            self._reasoning.append(stored)

    # ------------------------------------------------------------------
    def begin_tool(
        self, call: LLMToolCall, *, arguments: Any | None
    ) -> ToolResultSnapshot:
        snapshot = ToolResultSnapshot(
            call_id=call.id,
            tool_name=call.name,
            status="running",
            arguments=arguments,
            schema=self._tool_schemas.get(call.name),
        )
        snapshot.mark_event("started")
        self._snapshots[call.id] = snapshot
        self._order.append(call.id)
        self._exclude_from_results.discard(call.id)
        return snapshot

    def mark_tool_succeeded(
        self, call: LLMToolCall, payload: Mapping[str, Any]
    ) -> ToolResultSnapshot:
        snapshot = self._snapshots[call.id]
        snapshot.status = "succeeded"
        snapshot.result = payload.get("result")
        snapshot.error = None
        snapshot.mark_event("completed")
        metrics = payload.get("metrics")
        if isinstance(metrics, Mapping):
            duration = metrics.get("duration_seconds")
            if isinstance(duration, (int, float)):
                snapshot.metrics.duration_seconds = float(duration)
            cost_payload = metrics.get("cost")
            if isinstance(cost_payload, Mapping):
                snapshot.metrics.cost = dict(cost_payload)
        self._last_tool = snapshot
        self._exclude_from_results.discard(call.id)
        return snapshot

    def mark_tool_failed(
        self,
        call: LLMToolCall,
        error_payload: Mapping[str, Any],
        *,
        include_in_results: bool = True,
    ) -> ToolResultSnapshot:
        snapshot = self._snapshots[call.id]
        snapshot.status = "failed"
        snapshot.result = None
        snapshot.error = self._tool_error(error_payload)
        snapshot.mark_event("failed")
        self._last_tool = snapshot
        if include_in_results:
            self._exclude_from_results.discard(call.id)
        else:
            self._exclude_from_results.add(call.id)
        return snapshot

    def _tool_error(self, payload: Mapping[str, Any]) -> ToolError:
        message_value = payload.get("message") or payload.get("code") or "Tool failed"
        message = str(message_value)
        code = payload.get("code")
        if code is None and "type" in payload:
            code = payload["type"]
        details = payload.get("details")
        if isinstance(details, Mapping):
            detail_value: Mapping[str, Any] | None = dict(details)
        else:
            detail_value = None
        return ToolError(message=message, code=code, details=detail_value)

    # ------------------------------------------------------------------
    def finalise_success(self, *, result_text: str) -> None:
        self._ok = True
        self._status = "succeeded"
        self._result_text = result_text.strip()
        self._error = None
        self._agent_stop_reason = None

    def finalise_failure(
        self,
        *,
        message: str = "",
        error_payload: Mapping[str, Any] | None = None,
        stop_reason: Mapping[str, Any] | None = None,
    ) -> None:
        self._ok = False
        self._status = "failed"
        self._result_text = message.strip()
        if error_payload:
            self._error = self._tool_error(error_payload)
            self._diagnostic["error"] = dict(error_payload)
        else:
            self._error = None
        if stop_reason:
            reason = dict(stop_reason)
            self._diagnostic["stop_reason"] = reason
            self._agent_stop_reason = reason
        if "llm_steps" not in self._diagnostic and self._llm_trace.steps:
            self._diagnostic["llm_steps"] = [
                step.to_dict() for step in self._llm_trace.steps
            ]

    def attach_diagnostic(self, key: str, value: Any) -> None:
        self._diagnostic[key] = value

    # ------------------------------------------------------------------
    def iter_tool_snapshots(
        self, *, include_excluded: bool = False
    ) -> list[ToolResultSnapshot]:
        snapshots: list[ToolResultSnapshot] = []
        for call_id in self._order:
            if not include_excluded and call_id in self._exclude_from_results:
                continue
            snapshots.append(self._snapshots[call_id])
        return snapshots

    # ------------------------------------------------------------------
    def to_payload(self) -> AgentRunPayload:
        snapshots = self.iter_tool_snapshots()
        if self._ok:
            filtered_snapshots = [
                snapshot for snapshot in snapshots if snapshot.status == "succeeded"
            ]
        else:
            filtered_snapshots = snapshots
        diagnostic: dict[str, Any] = {}
        if self._diagnostic:
            diagnostic.update(self._diagnostic)
        if self._llm_steps:
            diagnostic["llm_steps"] = [
                {
                    "step": entry["step"],
                    "request_messages": [dict(message) for message in entry["request_messages"]],
                    "response": dict(entry["response"]),
                }
                for entry in self._llm_steps
            ]
        if self._llm_requests:
            diagnostic["llm_requests"] = [
                {
                    "step": entry["step"],
                    "messages": [dict(message) for message in entry["messages"]],
                }
                for entry in self._llm_requests
            ]
        if snapshots:
            diagnostic.setdefault(
                "tool_results",
                [snapshot.to_dict() for snapshot in snapshots],
            )
        diagnostic_value: Mapping[str, Any] | None
        if diagnostic:
            diagnostic_value = diagnostic
        else:
            diagnostic_value = None
        return AgentRunPayload(
            ok=self._ok,
            status="succeeded" if self._status == "succeeded" else "failed",
            result_text=self._result_text,
            reasoning=list(self._reasoning),
            tool_results=filtered_snapshots,
            llm_trace=self._llm_trace,
            error=self._error,
            diagnostic=diagnostic_value,
            tool_schemas=dict(self._tool_schemas) if self._tool_schemas else None,
            last_tool=self._last_tool,
            agent_stop_reason=(
                dict(self._agent_stop_reason)
                if isinstance(self._agent_stop_reason, Mapping)
                else None
            ),
        )


class LocalAgent:
    """High-level agent aggregating LLM and MCP clients."""

    DEFAULT_MAX_THOUGHT_STEPS: int | None = None
    DEFAULT_MAX_CONSECUTIVE_TOOL_ERRORS: int | None = 5
    _MESSAGE_PREVIEW_LIMIT = 400
    _REQUIREMENT_SUMMARY_FIELDS: tuple[str, str] = ("title", "statement")

    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        llm: SupportsAgentLLM | None = None,
        mcp: SupportsAgentMCP | None = None,
        confirm: Callable[[str], bool] | None = None,
        confirm_requirement_update: Callable[[RequirementUpdatePrompt], ConfirmDecision]
        | None = None,
        max_thought_steps: int | None = None,
        max_consecutive_tool_errors: int | None = None,
    ) -> None:
        """Initialize agent with optional settings or prebuilt clients."""
        if settings is not None:
            if confirm is None:
                confirm = default_confirm
            if confirm_requirement_update is None:
                confirm_requirement_update = default_update_confirm
            if llm is None:
                llm = LLMClient(settings.llm)
            if mcp is None:
                mcp = MCPClient(
                    settings.mcp,
                    confirm=confirm,
                    confirm_requirement_update=confirm_requirement_update,
                )
            if max_thought_steps is None:
                max_thought_steps = settings.agent.max_thought_steps
            if max_consecutive_tool_errors is None:
                max_consecutive_tool_errors = (
                    settings.agent.max_consecutive_tool_errors
                )
        if llm is None or mcp is None:
            raise TypeError("settings or clients must be provided")
        if not isinstance(llm, SupportsAgentLLM):
            raise TypeError(
                "LLM client must implement async methods check_llm_async() and "
                "respond_async()."
            )
        if not isinstance(mcp, SupportsAgentMCP):
            if not self._supports_partial_async_mcp(mcp):
                raise TypeError(
                    "MCP client must implement async methods check_tools_async(), "
                    "ensure_ready_async(), call_tool_async() and get_tool_schemas_async()."
                )
            mcp = _AgentMCPAdapter(mcp)
        self._llm: SupportsAgentLLM = llm
        self._mcp: SupportsAgentMCP = mcp
        self._max_thought_steps: int | None = self._normalise_max_thought_steps(
            max_thought_steps
        )
        self._max_consecutive_tool_errors: int | None = (
            self._normalise_max_consecutive_tool_errors(max_consecutive_tool_errors)
        )

    # ------------------------------------------------------------------
    def check_llm(self) -> Mapping[str, Any]:
        """Synchronously verify the LLM backend."""
        return self._run_sync(self.check_llm_async())

    async def check_llm_async(self) -> Mapping[str, Any]:
        return await self._llm.check_llm_async()

    def check_tools(self) -> Mapping[str, Any]:
        """Synchronously verify MCP tool availability."""
        return self._run_sync(self.check_tools_async())

    async def check_tools_async(self) -> Mapping[str, Any]:
        return await self._mcp.check_tools_async()

    # ------------------------------------------------------------------
    @staticmethod
    def _supports_partial_async_mcp(candidate: Any) -> bool:
        required_methods = ("check_tools_async", "ensure_ready_async", "call_tool_async")
        return all(callable(getattr(candidate, name, None)) for name in required_methods)

    # ------------------------------------------------------------------
    @classmethod
    def _preview(cls, text: str, limit: int | None = None) -> str:
        """Return a trimmed preview of *text* for logging."""
        limit = limit or cls._MESSAGE_PREVIEW_LIMIT
        snippet = text.strip()
        if len(snippet) > limit:
            return snippet[: limit - 1] + "\u2026"
        return snippet

    # ------------------------------------------------------------------
    def run_command(
        self,
        text: str,
        *,
        history: Sequence[Mapping[str, Any]] | None = None,
        context: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        cancellation: CancellationEvent | None = None,
        on_tool_result: Callable[[Mapping[str, Any]], None] | None = None,
        on_llm_step: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> Mapping[str, Any]:
        """Drive an agent loop that may invoke MCP tools before replying."""
        return self._run_sync(
            self.run_command_async(
                text,
                history=history,
                context=context,
                cancellation=cancellation,
                on_tool_result=on_tool_result,
                on_llm_step=on_llm_step,
            )
        )

    async def run_command_async(
        self,
        text: str,
        *,
        history: Sequence[Mapping[str, Any]] | None = None,
        context: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        cancellation: CancellationEvent | None = None,
        on_tool_result: Callable[[Mapping[str, Any]], None] | None = None,
        on_llm_step: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> Mapping[str, Any]:
        """Asynchronous variant of :meth:`run_command`."""
        context_messages = await self._prepare_context_messages_async(context)
        conversation = self._prepare_conversation(
            text,
            history,
            context=context_messages,
        )
        log_event(
            "AGENT_START",
            {"history_count": len(history or []), "prompt": self._preview(text, 200)},
        )

        tool_schemas = await self._load_tool_schemas_async()
        recorder = _AgentRunRecorder(tool_schemas=tool_schemas)

        try:
            payload = await self._run_loop_core(
                conversation,
                recorder=recorder,
                cancellation=cancellation,
                on_tool_result=on_tool_result,
                on_llm_step=on_llm_step,
            )
        except OperationCancelledError:
            log_event("AGENT_CANCELLED", {"reason": "user-request"})
            raise
        except Exception as exc:
            err = exception_to_mcp_error(exc)["error"]
            log_event("ERROR", {"error": err})
            recorder.finalise_failure(message=str(exc), error_payload=err)
            payload = recorder.to_payload()

        log_event("AGENT_RESULT", self._summarise_payload(payload))
        result_payload = payload.to_dict()
        if not payload.ok:
            result_payload.pop("tool_results", None)
        return result_payload

    # ------------------------------------------------------------------
    async def _run_loop_core(
        self,
        conversation: list[Mapping[str, Any]],
        *,
        recorder: _AgentRunRecorder,
        cancellation: CancellationEvent | None = None,
        on_tool_result: Callable[[Mapping[str, Any]], None] | None = None,
        on_llm_step: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> AgentRunPayload:
        runner = AgentLoopRunner(
            agent=self,
            recorder=recorder,
            conversation=conversation,
            cancellation=cancellation,
            on_tool_result=on_tool_result,
            on_llm_step=on_llm_step,
        )
        return await runner.run()

    # ------------------------------------------------------------------
    async def _load_tool_schemas_async(self) -> Mapping[str, Any]:
        try:
            schemas = await self._mcp.get_tool_schemas_async()
        except Exception as exc:  # pragma: no cover - defensive logging
            error_payload = exception_to_mcp_error(exc)["error"]
            log_event("MCP_SCHEMA_ERROR", {"error": error_payload})
            return {}
        return schemas

    # ------------------------------------------------------------------
    def _prepare_conversation(
        self,
        text: str,
        history: Sequence[Mapping[str, Any]] | None,
        *,
        context: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[Mapping[str, Any]]:
        conversation: list[Mapping[str, Any]] = list(history or [])
        if context:
            conversation.extend(context)
        conversation.append({"role": "user", "content": text})
        return conversation

    def _prepare_context_messages(
        self, context: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None
    ) -> list[Mapping[str, Any]]:
        return self._run_sync(self._prepare_context_messages_async(context))

    async def _prepare_context_messages_async(
        self, context: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None
    ) -> list[Mapping[str, Any]]:
        messages = self._normalise_context(context)
        if not messages:
            return []
        await self._enrich_workspace_context_async(messages)
        return messages

    async def _enrich_workspace_context_async(
        self, messages: Sequence[Mapping[str, Any]]
    ) -> None:
        for message in messages:
            role = message.get("role") if isinstance(message, Mapping) else None
            if role != "system":
                continue
            content = message.get("content")
            if not isinstance(content, str):
                continue
            stripped = content.lstrip()
            if not stripped.startswith("[Workspace context]"):
                continue
            selected_rids = self._extract_selected_rids_from_context(content)
            if not selected_rids:
                continue
            existing_lines = content.splitlines()
            already_present = {
                line.split(" — ", 1)[0].strip()
                for line in existing_lines
                if " — " in line
            }
            to_fetch: list[str] = []
            seen: set[str] = set()
            for rid in selected_rids:
                if rid in already_present or rid in seen:
                    continue
                to_fetch.append(rid)
                seen.add(rid)
            if not to_fetch:
                continue
            summaries = await self._fetch_requirement_summaries_async(to_fetch)
            if not summaries:
                continue
            additions: list[str] = []
            for rid in to_fetch:
                summary = summaries.get(rid)
                if not summary:
                    continue
                additions.append(f"{rid} — {summary}")
            if additions:
                message["content"] = "\n".join([*existing_lines, *additions])

    @staticmethod
    def _extract_selected_rids_from_context(content: str) -> list[str]:
        return extract_selected_rids_from_text(content)

    async def _fetch_requirement_summaries_async(
        self, rids: Sequence[str]
    ) -> dict[str, str]:
        unique: list[str] = []
        seen: set[str] = set()
        for rid in rids:
            if rid in seen:
                continue
            unique.append(rid)
            seen.add(rid)
        if not unique:
            return {}
        try:
            response = await self._mcp.call_tool_async(
                "get_requirement",
                {"rid": unique, "fields": list(self._REQUIREMENT_SUMMARY_FIELDS)},
            )
        except Exception:
            return {}
        if not isinstance(response, Mapping):
            return {}
        if response.get("ok") is not True:
            return {}
        result = response.get("result")
        if not isinstance(result, Mapping):
            return {}
        items = result.get("items")
        if not isinstance(items, Sequence):
            return {}
        summaries: dict[str, str] = {}
        for item in items:
            if not isinstance(item, Mapping):
                continue
            rid_value = str(item.get("rid") or "").strip()
            if not rid_value:
                continue
            statement = str(item.get("statement") or "").strip()
            summary = statement or str(item.get("title") or "").strip()
            if not summary:
                continue
            summaries[rid_value] = summary
        return summaries

    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_context(
        context: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if not context:
            return []
        if isinstance(context, Mapping):
            role = context.get("role")
            if role is None:
                return []
            return [
                {
                    "role": str(role),
                    "content": ""
                    if context.get("content") is None
                    else str(context.get("content")),
                }
            ]
        normalised: list[dict[str, Any]] = []
        for message in context:
            if not isinstance(message, Mapping):
                continue
            role = message.get("role")
            if role is None:
                continue
            entry: dict[str, Any] = {
                "role": str(role),
                "content": ""
                if message.get("content") is None
                else str(message.get("content")),
            }
            if "tool_calls" in message and isinstance(
                message.get("tool_calls"), Sequence
            ):
                entry["tool_calls"] = message.get("tool_calls")
            normalised.append(entry)
        return normalised

    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_max_thought_steps(value: int | None) -> int | None:
        if value is None:
            return LocalAgent.DEFAULT_MAX_THOUGHT_STEPS
        if isinstance(value, bool):  # pragma: no cover - defensive guard
            raise TypeError("max_thought_steps must be an integer or None")
        try:
            numeric = int(value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise TypeError("max_thought_steps must be an integer or None") from exc
        if numeric <= 0:
            return LocalAgent.DEFAULT_MAX_THOUGHT_STEPS
        return numeric

    @property
    def max_thought_steps(self) -> int | None:
        return self._max_thought_steps

    @staticmethod
    def _normalise_max_consecutive_tool_errors(value: int | None) -> int | None:
        if value is None:
            return LocalAgent.DEFAULT_MAX_CONSECUTIVE_TOOL_ERRORS
        if isinstance(value, bool):  # pragma: no cover - defensive guard
            raise TypeError(
                "max_consecutive_tool_errors must be an integer or None"
            )
        try:
            numeric = int(value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise TypeError(
                "max_consecutive_tool_errors must be an integer or None"
            ) from exc
        if numeric <= 0:
            return None
        return numeric

    @property
    def max_consecutive_tool_errors(self) -> int | None:
        return self._max_consecutive_tool_errors

    # ------------------------------------------------------------------
    @staticmethod
    def _run_sync(coro: Awaitable[Any]) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError(
            "Synchronous LocalAgent methods cannot run inside an active "
            "asyncio event loop; use the async variants instead."
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _raise_if_cancelled(cancellation: CancellationEvent | None) -> None:
        if cancellation is None:
            return
        raise_if_cancelled(cancellation)

    # ------------------------------------------------------------------
    def _normalise_tool_arguments(self, call: LLMToolCall) -> Any:
        try:
            return json.loads(self._format_tool_arguments(call.arguments))
        except (TypeError, ValueError, json.JSONDecodeError):
            if isinstance(call.arguments, Mapping):
                return dict(call.arguments)
            return call.arguments

    @staticmethod
    def _format_tool_arguments(arguments: Mapping[str, Any]) -> str:
        return json.dumps(arguments, ensure_ascii=False, default=str)

    @staticmethod
    def _serialise_tool_payload(payload: Mapping[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, default=str)

    @staticmethod
    def _extract_mcp_error(exc: Exception) -> Mapping[str, Any]:
        payload = getattr(exc, "error_payload", None)
        if isinstance(payload, Mapping):
            return dict(payload)
        payload = getattr(exc, "error", None)
        if isinstance(payload, Mapping):
            return dict(payload)
        return exception_to_mcp_error(exc)["error"]

    def _assistant_message(
        self,
        response: LLMResponse,
        *,
        tool_call_payloads: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        message: dict[str, Any] = {
            "role": "assistant",
            "content": response.content,
        }
        reasoning_segments = normalise_reasoning_segments(response.reasoning)
        if reasoning_segments:
            message["reasoning"] = reasoning_segments
        if tool_call_payloads is not None:
            fragments: list[dict[str, Any]] = []
            for entry in tool_call_payloads:
                if not isinstance(entry, Mapping):
                    continue
                fragment = dict(entry)
                function = fragment.get("function")
                if isinstance(function, Mapping):
                    function_payload = dict(function)
                else:
                    function_payload = {}
                if "arguments" in function_payload:
                    arguments_value = function_payload["arguments"]
                    if isinstance(arguments_value, Mapping):
                        function_payload["arguments"] = dict(arguments_value)
                fragment.setdefault("type", "function")
                fragment["function"] = function_payload
                if fragment.get("id") is None:
                    fragment["id"] = ""
                fragments.append(fragment)
            if fragments:
                message["tool_calls"] = fragments
        elif response.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": self._format_tool_arguments(call.arguments),
                    },
                }
                for call in response.tool_calls
            ]
        return message

    def _tool_message(self, call: LLMToolCall, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": call.id,
            "name": call.name,
            "content": self._serialise_tool_payload(payload),
        }

    def _conversation_tool_payload(
        self,
        call: LLMToolCall,
        payload: Mapping[str, Any],
        *,
        include_arguments: bool = True,
    ) -> dict[str, Any]:
        prepared = dict(payload)
        prepared.setdefault("tool_name", call.name)
        prepared.setdefault("tool_call_id", call.id)
        prepared.setdefault("call_id", call.id)
        if include_arguments and "tool_arguments" not in prepared:
            prepared["tool_arguments"] = self._normalise_tool_arguments(call)
        return prepared

    def _summarise_payload(self, payload: AgentRunPayload) -> Mapping[str, Any]:
        summary: dict[str, Any] = {
            "ok": payload.ok,
            "status": payload.status,
            "result_preview": self._preview(payload.result_text or "")
            if payload.result_text
            else "",
            "tool_results": len(payload.tool_results),
        }
        return summary

    def _log_step(self, index: int, response: LLMResponse) -> None:
        """Emit detailed logging payload for an LLM step."""
        request_messages = [
            dict(message) for message in (response.request_messages or []) if isinstance(message, Mapping)
        ]
        reasoning_segments = normalise_reasoning_segments(response.reasoning)
        detail = {
            "step": index,
            "request_messages": request_messages,
            "response": {
                "content": response.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "name": call.name,
                        "arguments": self._normalise_tool_arguments(call),
                    }
                    for call in response.tool_calls
                ],
                "reasoning": [
                    {
                        "type": segment.get("type", ""),
                        "text": segment.get("text", ""),
                    }
                    for segment in reasoning_segments
                ],
            },
        }
        log_debug_payload("AGENT_STEP_DETAIL", detail)

    def _emit_tool_snapshot(
        self,
        callback: Callable[[Mapping[str, Any]], None] | None,
        snapshot: ToolResultSnapshot,
    ) -> None:
        if callback is None:
            return
        try:
            callback(snapshot.to_dict())
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                "AGENT_TOOL_STREAM_ERROR",
                {"error": {"type": type(exc).__name__, "message": str(exc)}},
            )

    # ------------------------------------------------------------------
    def _conversation_payload_from_error(
        self,
        call: LLMToolCall,
        error_payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self._conversation_tool_payload(
            call,
            {"ok": False, "error": dict(error_payload)},
            include_arguments=True,
        )

    async def _execute_tool_calls_core(
        self, tool_calls: Sequence[LLMToolCall]
    ) -> _ToolExecutionBatchResult:
        messages: list[Mapping[str, Any]] = []
        successful_results: list[Mapping[str, Any]] = []
        error_payload: Mapping[str, Any] | None = None
        for call in tool_calls:
            arguments = self._normalise_tool_arguments(call)
            log_event(
                "AGENT_TOOL_CALL",
                {"call_id": call.id, "tool_name": call.name, "arguments": call.arguments},
            )
            log_debug_payload(
                "AGENT_TOOL_CALL_DETAIL",
                {"call_id": call.id, "tool_name": call.name, "arguments": arguments},
            )
            try:
                await self._mcp.ensure_ready_async()
                result = await self._mcp.call_tool_async(call.name, call.arguments)
            except Exception as exc:
                error_payload = self._extract_mcp_error(exc)
                log_event("ERROR", {"error": error_payload})
                detail = self._conversation_payload_from_error(call, error_payload)
                messages.append(self._tool_message(call, detail))
                break
            log_debug_payload(
                "AGENT_TOOL_RESULT_DETAIL",
                {
                    "call_id": call.id,
                    "tool_name": call.name,
                    "ok": True,
                    "result": dict(result),
                },
            )
            if result.get("ok") is True:
                successful_results.append(dict(result))
                detail = self._conversation_tool_payload(call, result)
                messages.append(self._tool_message(call, detail))
                continue
            error_payload_candidate = result.get("error")
            if not isinstance(error_payload_candidate, Mapping):
                error_payload_candidate = {
                    "code": "UNKNOWN",
                    "message": "Tool returned failure without error payload",
                }
            error_payload = error_payload_candidate
            log_event("ERROR", {"error": error_payload})
            log_debug_payload(
                "AGENT_TOOL_RESULT_DETAIL",
                {
                    "call_id": call.id,
                    "tool_name": call.name,
                    "ok": False,
                    "result": {
                        "ok": False,
                        "error": dict(error_payload),
                    },
                },
            )
            detail = self._conversation_payload_from_error(call, error_payload)
            messages.append(self._tool_message(call, detail))
            break
        return _ToolExecutionBatchResult(
            messages=messages,
            successful_results=successful_results,
            error_payload=error_payload,
        )


@dataclass(slots=True)
class _ValidationToolCallPayload:
    call: LLMToolCall
    assistant_fragment: dict[str, Any]
    arguments_for_payload: Any | None


class AgentLoopRunner:
    """Stateful helper executing :class:`LocalAgent` iterations."""

    def __init__(
        self,
        *,
        agent: LocalAgent,
        recorder: _AgentRunRecorder,
        conversation: list[Mapping[str, Any]],
        cancellation: CancellationEvent | None,
        on_tool_result: Callable[[Mapping[str, Any]], None] | None,
        on_llm_step: Callable[[Mapping[str, Any]], None] | None,
    ) -> None:
        self._agent = agent
        self._recorder = recorder
        self._conversation = conversation
        self._cancellation = cancellation
        self._on_tool_result = on_tool_result
        self._on_llm_step = on_llm_step
        self._step = 0
        self._consecutive_tool_errors = 0
        self._last_response: LLMResponse | None = None

    async def run(self) -> AgentRunPayload:
        while not self._reached_step_limit():
            self._agent._raise_if_cancelled(self._cancellation)
            iteration = await self._step_once()
            if iteration.final_payload is not None:
                return iteration.final_payload
            if iteration.tool_error is None:
                self._consecutive_tool_errors = 0
                self._agent._raise_if_cancelled(self._cancellation)
                continue
            self._consecutive_tool_errors += 1
            if self._should_abort_due_to_tool_errors():
                return self._abort_due_to_tool_errors(iteration.tool_error)
            self._agent._raise_if_cancelled(self._cancellation)
        return self._abort_due_to_step_limit()

    async def _step_once(self) -> _AgentIterationResult:
        try:
            response = await self._agent._llm.respond_async(
                self._conversation,
                cancellation=self._cancellation,
            )
        except ToolValidationError as exc:
            return await self._handle_validation_error(exc)

        return await self._handle_response(response)

    async def _handle_response(
        self, response: LLMResponse
    ) -> _AgentIterationResult:
        self._register_response(response)
        self._conversation.append(self._agent._assistant_message(response))
        self._advance_step(response)
        if not response.tool_calls:
            self._recorder.finalise_success(result_text=response.content)
            return _AgentIterationResult(
                response=response,
                tool_error=None,
                tool_messages=(),
                final_payload=self._recorder.to_payload(),
            )

        messages: list[Mapping[str, Any]] = []
        first_error: Mapping[str, Any] | None = None
        for call in response.tool_calls:
            self._agent._raise_if_cancelled(self._cancellation)
            outcome = await self._run_single_tool_call(call)
            messages.append(outcome.message)
            if outcome.error_payload is not None:
                first_error = outcome.error_payload
                break
            self._agent._raise_if_cancelled(self._cancellation)
        self._conversation.extend(messages)
        return _AgentIterationResult(
            response=response,
            tool_error=first_error,
            tool_messages=tuple(messages),
            final_payload=None,
        )

    async def _run_single_tool_call(
        self, call: LLMToolCall
    ) -> _ToolExecutionOutcome:
        arguments = self._agent._normalise_tool_arguments(call)
        snapshot = self._recorder.begin_tool(call, arguments=arguments)
        self._agent._emit_tool_snapshot(self._on_tool_result, snapshot)
        log_event(
            "AGENT_TOOL_CALL",
            {
                "call_id": call.id,
                "tool_name": call.name,
                "arguments": call.arguments,
            },
        )
        log_debug_payload(
            "AGENT_TOOL_CALL_DETAIL",
            {
                "call_id": call.id,
                "tool_name": call.name,
                "arguments": arguments,
            },
        )
        try:
            ready_result = self._agent._mcp.ensure_ready_async()
            if inspect.isawaitable(ready_result):
                await ready_result
        except Exception as exc:
            error_payload = self._agent._extract_mcp_error(exc)
            snapshot = self._recorder.mark_tool_failed(
                call,
                error_payload,
                include_in_results=False,
            )
            self._agent._emit_tool_snapshot(self._on_tool_result, snapshot)
            log_event("ERROR", {"error": error_payload})
            prepared = self._agent._conversation_payload_from_error(call, error_payload)
            message = self._agent._tool_message(call, prepared)
            return _ToolExecutionOutcome(message=message, error_payload=prepared["error"])
        try:
            call_result = self._agent._mcp.call_tool_async(call.name, call.arguments)
            result = (
                await call_result
                if inspect.isawaitable(call_result)
                else call_result
            )
        except Exception as exc:
            error_payload = self._agent._extract_mcp_error(exc)
            snapshot = self._recorder.mark_tool_failed(call, error_payload)
            self._agent._emit_tool_snapshot(self._on_tool_result, snapshot)
            log_event("ERROR", {"error": error_payload})
            prepared = self._agent._conversation_payload_from_error(call, error_payload)
            message = self._agent._tool_message(call, prepared)
            return _ToolExecutionOutcome(message=message, error_payload=prepared["error"])

        prepared_payload = self._agent._conversation_tool_payload(call, result)
        if result.get("ok") is True:
            snapshot = self._recorder.mark_tool_succeeded(call, result)
            self._agent._emit_tool_snapshot(self._on_tool_result, snapshot)
            message = self._agent._tool_message(call, prepared_payload)
            return _ToolExecutionOutcome(message=message, error_payload=None)

        error_payload = result.get("error")
        if not isinstance(error_payload, Mapping):
            error_payload = {
                "code": "UNKNOWN",
                "message": "Tool returned failure without error payload",
            }
        snapshot = self._recorder.mark_tool_failed(call, error_payload)
        self._agent._emit_tool_snapshot(self._on_tool_result, snapshot)
        prepared = self._agent._conversation_payload_from_error(call, error_payload)
        message = self._agent._tool_message(call, prepared)
        return _ToolExecutionOutcome(message=message, error_payload=error_payload)

    def _register_response(
        self,
        response: LLMResponse,
        *,
        tool_call_payloads: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self._last_response = response
        request_messages: Sequence[Mapping[str, Any]]
        if response.request_messages:
            request_messages = [dict(m) for m in response.request_messages if isinstance(m, Mapping)]
        else:
            request_messages = list(self._conversation)
        tool_call_details: list[dict[str, Any]] = []
        if tool_call_payloads is not None:
            for entry in tool_call_payloads:
                if not isinstance(entry, Mapping):
                    continue
                fragment = dict(entry)
                call_id = str(fragment.get("id") or "")
                function = fragment.get("function") if isinstance(fragment.get("function"), Mapping) else {}
                name = ""
                arguments_value: Any = {}
                if isinstance(function, Mapping):
                    name = str(function.get("name") or "")
                    if "arguments" in function:
                        arguments_value = function["arguments"]
                if not name and fragment.get("name"):
                    name = str(fragment.get("name"))
                if isinstance(arguments_value, Mapping):
                    arguments_value = dict(arguments_value)
                tool_call_details.append(
                    {
                        "id": call_id,
                        "name": name,
                        "arguments": arguments_value,
                    }
                )
        else:
            tool_call_details = [
                {
                    "id": call.id,
                    "name": call.name,
                    "arguments": self._agent._normalise_tool_arguments(call),
                }
                for call in response.tool_calls
            ]
        self._recorder.record_llm_step(
            index=self._step + 1,
            request_messages=request_messages,
            response={
                "content": response.content,
                "tool_calls": tool_call_details,
                "reasoning": [
                    {"type": segment.type, "text": segment.text}
                    for segment in response.reasoning
                ],
            },
        )
        self._recorder.extend_reasoning(response.reasoning)

    def _advance_step(self, response: LLMResponse) -> None:
        self._step += 1
        if self._on_llm_step is None:
            return
        detail_payload = {
            "step": self._step,
            "message_preview": LocalAgent._preview(response.content),
            "tool_calls": [
                {
                    "id": call.id,
                    "name": call.name,
                    "argument_keys": sorted(call.arguments.keys()),
                }
                for call in response.tool_calls
            ],
        }
        reasoning_segments = normalise_reasoning_segments(response.reasoning)
        if reasoning_segments:
            detail_payload["reasoning"] = [
                {
                    "type": segment["type"],
                    "preview": LocalAgent._preview(segment["text"], limit=200),
                }
                for segment in reasoning_segments
            ]
        try:
            self._on_llm_step(detail_payload)
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                "AGENT_STEP_STREAM_ERROR",
                {"error": {"type": type(exc).__name__, "message": str(exc)}},
            )

    def _reached_step_limit(self) -> bool:
        limit = self._agent._max_thought_steps
        return limit is not None and self._step >= limit

    def _should_abort_due_to_tool_errors(self) -> bool:
        limit = self._agent._max_consecutive_tool_errors
        return limit is not None and self._consecutive_tool_errors >= limit

    def _abort_due_to_tool_errors(
        self, error_payload: Mapping[str, Any]
    ) -> AgentRunPayload:
        stop_reason: dict[str, Any] = {
            "type": "consecutive_tool_errors",
            "count": self._consecutive_tool_errors,
        }
        limit = self._agent._max_consecutive_tool_errors
        if limit is not None:
            stop_reason["max_consecutive_tool_errors"] = limit
        self._recorder.finalise_failure(
            message="",
            error_payload=error_payload,
            stop_reason=stop_reason,
        )
        return self._recorder.to_payload()

    def _abort_due_to_step_limit(self) -> AgentRunPayload:
        limit = self._agent._max_thought_steps
        last_response = self._last_response
        last_call_arguments: Any | None = None
        last_call_name: str | None = None
        llm_tool_calls: list[dict[str, Any]] = []
        if last_response is not None and last_response.tool_calls:
            for call in last_response.tool_calls:
                arguments = self._agent._normalise_tool_arguments(call)
                llm_tool_calls.append(
                    {
                        "id": call.id,
                        "name": call.name,
                        "arguments": arguments,
                    }
                )
            final_call = last_response.tool_calls[-1]
            last_call_name = final_call.name
            last_call_arguments = self._agent._normalise_tool_arguments(final_call)
        elif self._recorder._last_tool is not None:
            snapshot = self._recorder._last_tool
            last_call_name = snapshot.tool_name
            last_call_arguments = snapshot.arguments
        if isinstance(last_call_arguments, Mapping):
            arguments_preview = self._agent._format_tool_arguments(last_call_arguments)
        else:
            arguments_preview = str(last_call_arguments or "{}")
        if last_call_name:
            message = (
                "LLM did not finish interaction within allowed steps "
                f"({limit}); last tool call {last_call_name} with arguments "
                f"{arguments_preview}"
            )
        else:
            message = (
                "LLM did not finish interaction within allowed steps "
                f"({limit})"
            )
        tool_results_payload = [
            snapshot.to_dict()
            for snapshot in self._recorder.iter_tool_snapshots()
        ]
        details: dict[str, Any] = {"type": "ToolValidationError"}
        if last_response is not None and last_response.content:
            details["llm_message"] = last_response.content
        if llm_tool_calls:
            details["llm_tool_calls"] = llm_tool_calls
        if tool_results_payload:
            details["tool_results"] = tool_results_payload
        error_payload = {
            "code": "VALIDATION_ERROR",
            "message": message,
            "details": details,
        }
        self._recorder.finalise_failure(message=message, error_payload=error_payload)
        return self._recorder.to_payload()

    async def _handle_validation_error(
        self, exc: ToolValidationError
    ) -> _AgentIterationResult:
        message_text = getattr(exc, "llm_message", "") or ""
        raw_calls = getattr(exc, "llm_tool_calls", None)
        raw_request_messages = getattr(exc, "llm_request_messages", None)
        raw_reasoning = getattr(exc, "llm_reasoning", None)
        prepared_calls = self._prepare_invalid_tool_calls(raw_calls)
        if not prepared_calls:
            prepared_calls.append(self._build_validation_error_placeholder_call())
        request_snapshot: list[dict[str, Any]] = []
        if isinstance(raw_request_messages, Sequence) and not isinstance(
            raw_request_messages, (str, bytes, bytearray)
        ):
            for message in raw_request_messages:
                if isinstance(message, Mapping):
                    request_snapshot.append(dict(message))
        if not request_snapshot:
            request_snapshot = list(self._conversation)

        reasoning_segments = normalise_reasoning_segments(raw_reasoning)
        reasoning_tuple = tuple(
            LLMReasoningSegment(type=segment["type"], text=segment["text"])
            for segment in reasoning_segments
        )

        def _preview_messages(messages: Sequence[Mapping[str, Any]]) -> list[Any]:
            previews: list[Any] = []
            for message in messages:
                if not isinstance(message, Mapping):
                    previews.append(message)
                    continue
                cloned = dict(message)
                content = cloned.get("content")
                if isinstance(content, str):
                    cloned["content"] = LocalAgent._preview(content)
                previews.append(cloned)
            return previews

        log_debug_payload(
            "AGENT_VALIDATION_ERROR",
            {
                "message": str(exc) or type(exc).__name__,
                "llm_message": message_text,
                "tool_calls": [dict(prepared.assistant_fragment) for prepared in prepared_calls],
                "request_messages": _preview_messages(request_snapshot),
                "reasoning": [
                    {
                        "type": segment["type"],
                        "text": LocalAgent._preview(segment["text"], limit=200),
                    }
                    for segment in reasoning_segments
                ],
            },
        )

        synthetic_response = LLMResponse(
            content=message_text,
            tool_calls=tuple(prepared.call for prepared in prepared_calls),
            request_messages=tuple(request_snapshot),
            reasoning=reasoning_tuple,
        )

        tool_call_fragments = [
            dict(prepared.assistant_fragment) for prepared in prepared_calls
        ]

        self._register_response(
            synthetic_response, tool_call_payloads=tool_call_fragments
        )

        tool_messages: list[Mapping[str, Any]] = []
        first_error_payload: Mapping[str, Any] | None = None
        error_payload = exception_to_mcp_error(exc)["error"]
        for prepared in prepared_calls:
            snapshot = self._recorder.begin_tool(
                prepared.call,
                arguments=prepared.arguments_for_payload,
            )
            self._agent._emit_tool_snapshot(self._on_tool_result, snapshot)
            snapshot = self._recorder.mark_tool_failed(
                prepared.call,
                error_payload,
            )
            self._agent._emit_tool_snapshot(self._on_tool_result, snapshot)
            message = self._agent._tool_message(
                prepared.call,
                self._agent._conversation_tool_payload(
                    prepared.call,
                    {"ok": False, "error": dict(error_payload)},
                    include_arguments=True,
                ),
            )
            tool_messages.append(message)
            if first_error_payload is None:
                first_error_payload = error_payload
        if first_error_payload is None:
            first_error_payload = error_payload

        assistant_message = self._agent._assistant_message(
            synthetic_response,
            tool_call_payloads=tool_call_fragments,
        )
        self._conversation.append(assistant_message)
        if tool_messages:
            self._conversation.extend(tool_messages)
        self._advance_step(synthetic_response)
        return _AgentIterationResult(
            response=synthetic_response,
            tool_error=first_error_payload,
            tool_messages=tuple(tool_messages),
            final_payload=None,
        )

    def _build_validation_error_placeholder_call(self) -> _ValidationToolCallPayload:
        call_id = f"validation_error_step_{self._step + 1}" if self._step >= 0 else "validation_error"
        call = LLMToolCall(id=call_id, name="__tool_validation_error__", arguments={})
        assistant_fragment = {
            "id": call.id,
            "type": "function",
            "function": {"name": call.name, "arguments": "{}"},
        }
        return _ValidationToolCallPayload(
            call=call,
            assistant_fragment=assistant_fragment,
            arguments_for_payload=None,
        )

    def _prepare_invalid_tool_calls(
        self, raw_calls: Sequence[Any] | None
    ) -> list[_ValidationToolCallPayload]:
        if not isinstance(raw_calls, Sequence) or isinstance(
            raw_calls, (str, bytes, bytearray)
        ):
            return []
        prepared: list[_ValidationToolCallPayload] = []
        for index, entry in enumerate(raw_calls):
            if not isinstance(entry, Mapping):
                continue
            function = entry.get("function")
            if not isinstance(function, Mapping):
                continue
            name = function.get("name")
            if not name:
                continue
            arguments_text, arguments_for_payload = self._normalise_tool_arguments_from_error(
                function.get("arguments")
            )
            call_id = entry.get("id") or entry.get("tool_call_id") or f"tool_call_{index}"
            call_id_str = str(call_id)
            assistant_fragment = {
                "id": call_id_str,
                "type": "function",
                "function": {
                    "name": str(name),
                    "arguments": arguments_text,
                },
            }
            if isinstance(arguments_for_payload, Mapping):
                call_arguments: Mapping[str, Any] = dict(arguments_for_payload)
            else:
                call_arguments = {}
            prepared.append(
                _ValidationToolCallPayload(
                    call=LLMToolCall(
                        id=call_id_str,
                        name=str(name),
                        arguments=call_arguments,
                    ),
                    assistant_fragment=assistant_fragment,
                    arguments_for_payload=(
                        dict(arguments_for_payload)
                        if isinstance(arguments_for_payload, Mapping)
                        else arguments_for_payload
                    ),
                )
            )
        return prepared

    def _normalise_tool_arguments_from_error(self, raw: Any) -> tuple[str, Any | None]:
        if isinstance(raw, str):
            text = raw.strip() or "{}"
            parsed = self._safe_json_loads(text)
            if isinstance(parsed, Mapping):
                return text, dict(parsed)
            return text, parsed
        if isinstance(raw, Mapping):
            prepared = dict(raw)
            return self._format_tool_arguments(prepared), prepared
        if raw is None:
            return "{}", None
        try:
            text = json.dumps(raw, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return "{}", None
        parsed = self._safe_json_loads(text)
        if isinstance(parsed, Mapping):
            return text, dict(parsed)
        return text, parsed

    @staticmethod
    def _safe_json_loads(text: str) -> Any:
        try:
            return json.loads(text)
        except Exception:
            return text
