"""Local agent that combines LLM parsing with MCP tool execution."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any, Awaitable, Callable, Mapping, Protocol, runtime_checkable

from ..confirm import (
    ConfirmDecision,
    RequirementUpdatePrompt,
    confirm as default_confirm,
    confirm_requirement_update as default_update_confirm,
)
from ..llm.client import LLMClient, LLMResponse, LLMToolCall
from ..llm.validation import ToolValidationError
from ..mcp.client import MCPClient
from ..mcp.utils import exception_to_mcp_error
from ..settings import AppSettings
from ..telemetry import log_event
from ..util.cancellation import (
    CancellationEvent,
    OperationCancelledError,
    raise_if_cancelled,
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


class LocalAgent:
    """High-level agent aggregating LLM and MCP clients."""

    _MAX_THOUGHT_STEPS = 8
    _MESSAGE_PREVIEW_LIMIT = 400

    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        llm: SupportsAgentLLM | None = None,
        mcp: SupportsAgentMCP | None = None,
        confirm: Callable[[str], bool] | None = None,
        confirm_requirement_update: Callable[[RequirementUpdatePrompt], ConfirmDecision]
        | None = None,
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
        if llm is None or mcp is None:
            raise TypeError("settings or clients must be provided")
        if not isinstance(llm, SupportsAgentLLM):
            raise TypeError(
                "LLM client must implement async methods check_llm_async() and "
                "respond_async()."
            )
        if not isinstance(mcp, SupportsAgentMCP):
            raise TypeError(
                "MCP client must implement async methods check_tools_async(), "
                "ensure_ready_async(), and call_tool_async()."
            )
        self._llm: SupportsAgentLLM = llm
        self._mcp: SupportsAgentMCP = mcp

    # ------------------------------------------------------------------
    @classmethod
    def _preview(cls, text: str, limit: int | None = None) -> str:
        """Return a trimmed preview of *text* for logging."""

        limit = limit or cls._MESSAGE_PREVIEW_LIMIT
        snippet = text.strip()
        if len(snippet) > limit:
            return snippet[: limit - 1] + "\u2026"
        return snippet

    @staticmethod
    def _summarize_tool_calls(tool_calls: Sequence[LLMToolCall]) -> list[dict[str, Any]]:
        """Return lightweight metadata about planned tool calls."""

        summary: list[dict[str, Any]] = []
        for call in tool_calls:
            args = call.arguments if isinstance(call.arguments, Mapping) else {}
            summary.append(
                {
                    "id": call.id,
                    "name": call.name,
                    "argument_keys": sorted(args.keys()) if isinstance(args, Mapping) else [],
                }
            )
        return summary

    def _log_step(self, step: int, response: LLMResponse) -> None:
        """Record intermediate agent step for diagnostics."""

        log_event(
            "AGENT_STEP",
            {
                "step": step,
                "message_preview": self._preview(response.content),
                "tool_calls": self._summarize_tool_calls(response.tool_calls),
            },
        )

    @staticmethod
    def _summarize_result(result: Mapping[str, Any]) -> dict[str, Any]:
        """Return compact metadata about final agent outcome."""

        payload: dict[str, Any] = {}
        ok_value = result.get("ok")
        if isinstance(ok_value, bool):
            payload["ok"] = ok_value
        if "error" in result and result["error"]:
            payload["error"] = result["error"]
        if "result" in result and result["result"]:
            payload["result_type"] = type(result["result"]).__name__
        if "tool_results" in result:
            try:
                payload["tool_results"] = len(result["tool_results"])
            except TypeError:
                payload["tool_results"] = result["tool_results"]
        return payload

    @staticmethod
    def _extract_mcp_error(exc: Exception) -> dict[str, Any]:
        """Return structured MCP error payload derived from *exc*."""

        payload = getattr(exc, "error_payload", None)
        if isinstance(payload, Mapping):
            return dict(payload)
        payload = getattr(exc, "error", None)
        if isinstance(payload, Mapping):
            return dict(payload)
        return exception_to_mcp_error(exc)["error"]

    @staticmethod
    def _raise_if_cancelled(cancellation: CancellationEvent | None) -> None:
        """Abort execution when *cancellation* has been triggered."""

        raise_if_cancelled(cancellation)

    @staticmethod
    def _run_sync(coro: Awaitable[Any]) -> Any:
        """Execute asynchronous helpers from synchronous entry points."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError(
            "Synchronous LocalAgent methods cannot run inside an active "
            "asyncio event loop; use the async variants instead."
        )

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

    def _prepare_conversation(
        self,
        text: str,
        history: Sequence[Mapping[str, Any]] | None,
        *,
        context: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    ) -> list[Mapping[str, Any]]:
        conversation: list[Mapping[str, Any]] = list(history or [])
        conversation.extend(self._normalise_context(context))
        conversation.append({"role": "user", "content": text})
        return conversation

    # ------------------------------------------------------------------
    def check_llm(self) -> dict[str, Any]:
        """Delegate to :class:`LLMClient.check_llm`."""

        return self._run_sync(self._llm.check_llm_async())

    async def check_llm_async(self) -> dict[str, Any]:
        """Asynchronous variant of :meth:`check_llm`."""

        return await self._llm.check_llm_async()

    # ------------------------------------------------------------------
    def check_tools(self) -> dict[str, Any]:
        """Delegate to :class:`MCPClient.check_tools`."""

        return self._run_sync(self._mcp.check_tools_async())

    async def check_tools_async(self) -> dict[str, Any]:
        """Asynchronous variant of :meth:`check_tools`."""

        return await self._mcp.check_tools_async()

    # ------------------------------------------------------------------
    def run_command(
        self,
        text: str,
        *,
        history: Sequence[Mapping[str, Any]] | None = None,
        context: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        cancellation: CancellationEvent | None = None,
        on_tool_result: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Drive an agent loop that may invoke MCP tools before replying."""

        conversation = self._prepare_conversation(text, history, context=context)
        log_event(
            "AGENT_START",
            {"history_count": len(history or []), "prompt": self._preview(text, 200)},
        )
        try:
            result = self._run_sync(
                self._run_loop_core(
                    conversation,
                    cancellation=cancellation,
                    on_tool_result=on_tool_result,
                )
            )
        except OperationCancelledError:
            log_event("AGENT_CANCELLED", {"reason": "user-request"})
            raise
        except Exception as exc:
            err = exception_to_mcp_error(exc)["error"]
            log_event("ERROR", {"error": err})
            return {"ok": False, "error": err}
        log_event("AGENT_RESULT", self._summarize_result(result))
        return result

    async def run_command_async(
        self,
        text: str,
        *,
        history: Sequence[Mapping[str, Any]] | None = None,
        context: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        cancellation: CancellationEvent | None = None,
        on_tool_result: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Asynchronous variant of :meth:`run_command`."""

        conversation = self._prepare_conversation(text, history, context=context)
        log_event(
            "AGENT_START",
            {"history_count": len(history or []), "prompt": self._preview(text, 200)},
        )
        try:
            result = await self._run_loop_core(
                conversation,
                cancellation=cancellation,
                on_tool_result=on_tool_result,
            )
        except OperationCancelledError:
            log_event("AGENT_CANCELLED", {"reason": "user-request"})
            raise
        except Exception as exc:
            err = exception_to_mcp_error(exc)["error"]
            log_event("ERROR", {"error": err})
            return {"ok": False, "error": err}
        log_event("AGENT_RESULT", self._summarize_result(result))
        return result

    # ------------------------------------------------------------------
    async def _run_loop_core(
        self,
        conversation: list[Mapping[str, Any]],
        *,
        cancellation: CancellationEvent | None = None,
        on_tool_result: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        accumulated_results: list[Mapping[str, Any]] = []
        for step in range(self._MAX_THOUGHT_STEPS):
            self._raise_if_cancelled(cancellation)
            response = await self._llm.respond_async(
                conversation,
                cancellation=cancellation,
            )
            conversation.append(self._assistant_message(response))
            self._log_step(step + 1, response)
            if not response.tool_calls:
                return self._success_result(response, accumulated_results)
            (
                tool_messages,
                early_result,
                batch_results,
            ) = await self._execute_tool_calls_core(
                response.tool_calls,
                cancellation=cancellation,
                on_tool_result=on_tool_result,
            )
            conversation.extend(tool_messages)
            accumulated_results.extend(batch_results)
            if early_result is not None:
                return early_result
            self._raise_if_cancelled(cancellation)
        log_event(
            "AGENT_ABORTED",
            {"reason": "max-steps", "max_steps": self._MAX_THOUGHT_STEPS},
        )
        raise ToolValidationError(
            "LLM did not finish interaction within allowed steps",
        )

    async def _execute_tool_calls_core(
        self,
        tool_calls: Sequence[LLMToolCall],
        *,
        cancellation: CancellationEvent | None = None,
        on_tool_result: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[Mapping[str, Any]]]:
        messages: list[dict[str, Any]] = []
        successful: list[Mapping[str, Any]] = []
        for call in tool_calls:
            self._raise_if_cancelled(cancellation)
            try:
                log_event(
                    "AGENT_TOOL_CALL",
                    {
                        "call_id": call.id,
                        "tool_name": call.name,
                        "arguments": call.arguments,
                    },
                )
                await self._mcp.ensure_ready_async()
                result = await self._mcp.call_tool_async(call.name, call.arguments)
            except Exception as exc:
                error = self._extract_mcp_error(exc)
                log_event("ERROR", {"error": error})
                log_event(
                    "AGENT_TOOL_RESULT",
                    {
                        "call_id": call.id,
                        "tool_name": call.name,
                        "ok": False,
                        "error": error,
                    },
                )
                payload = self._prepare_tool_payload(
                    call,
                    {"ok": False, "error": error},
                    include_arguments=True,
                )
                self._emit_tool_result(on_tool_result, payload)
                messages.append(self._tool_message(call, payload))
                return messages, payload, successful
            if not isinstance(result, Mapping):
                payload = self._prepare_tool_payload(
                    call,
                    {
                        "ok": False,
                        "error": {
                            "type": "ToolProtocolError",
                            "message": "Tool returned unexpected payload",
                        },
                    },
                    include_arguments=True,
                )
                self._emit_tool_result(on_tool_result, payload)
                messages.append(self._tool_message(call, payload))
                return messages, payload, successful
            result_dict = self._prepare_tool_payload(
                call,
                result,
                include_arguments=True,
            )
            log_payload: dict[str, Any] = {
                "call_id": call.id,
                "tool_name": call.name,
                "ok": bool(result_dict.get("ok", False)),
            }
            if not log_payload["ok"] and result_dict.get("error"):
                log_payload["error"] = result_dict["error"]
            log_event("AGENT_TOOL_RESULT", log_payload)
            self._emit_tool_result(on_tool_result, result_dict)
            messages.append(self._tool_message(call, result_dict))
            if not result_dict.get("ok", False):
                return messages, result_dict, successful
            successful.append(result_dict)
            self._raise_if_cancelled(cancellation)
        return messages, None, successful

    @staticmethod
    def _emit_tool_result(
        callback: Callable[[Mapping[str, Any]], None] | None,
        payload: Mapping[str, Any],
    ) -> None:
        """Deliver intermediate MCP *payload* to the provided *callback*."""

        if callback is None:
            return
        try:
            prepared = dict(payload) if isinstance(payload, Mapping) else {"value": payload}
            callback(prepared)
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                "AGENT_TOOL_STREAM_ERROR",
                {"error": {"type": type(exc).__name__, "message": str(exc)}},
            )

    @staticmethod
    def _success_result(
        response: LLMResponse, tool_results: Sequence[Mapping[str, Any]] | None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": True,
            "error": None,
            "result": response.content.strip(),
        }
        if tool_results:
            payload["tool_results"] = [dict(result) for result in tool_results]
        return payload

    def _normalise_tool_arguments(self, call: LLMToolCall) -> Any:
        """Return JSON-compatible representation of tool arguments."""

        try:
            return json.loads(self._format_tool_arguments(call.arguments))
        except (TypeError, ValueError, json.JSONDecodeError):
            if isinstance(call.arguments, Mapping):
                return dict(call.arguments)
            return call.arguments

    def _prepare_tool_payload(
        self,
        call: LLMToolCall,
        payload: Mapping[str, Any],
        *,
        include_arguments: bool = True,
    ) -> dict[str, Any]:
        """Attach identifying metadata for *call* to the tool *payload*."""

        prepared = dict(payload)
        prepared.setdefault("tool_name", call.name)
        prepared.setdefault("tool_call_id", call.id)
        prepared.setdefault("call_id", call.id)
        if include_arguments and "tool_arguments" not in prepared:
            prepared["tool_arguments"] = self._normalise_tool_arguments(call)
        return prepared

    def _assistant_message(self, response: LLMResponse) -> dict[str, Any]:
        message: dict[str, Any] = {
            "role": "assistant",
            "content": response.content,
        }
        if response.tool_calls:
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

    @staticmethod
    def _format_tool_arguments(arguments: Mapping[str, Any]) -> str:
        return json.dumps(arguments, ensure_ascii=False, default=str)

    @staticmethod
    def _serialise_tool_payload(payload: Mapping[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, default=str)
