"""Local agent that combines LLM parsing with MCP tool execution."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Sequence
from typing import Any, Callable, Mapping

from ..confirm import confirm as default_confirm
from ..llm.client import LLMClient, LLMResponse, LLMToolCall
from ..llm.validation import ToolValidationError
from ..mcp.client import MCPClient
from ..mcp.utils import exception_to_mcp_error
from ..settings import AppSettings
from ..telemetry import log_event


class LocalAgent:
    """High-level agent aggregating LLM and MCP clients."""

    _MAX_THOUGHT_STEPS = 8
    _MESSAGE_PREVIEW_LIMIT = 400

    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        llm: LLMClient | None = None,
        mcp: MCPClient | None = None,
        confirm: Callable[[str], bool] | None = None,
    ) -> None:
        """Initialize agent with optional settings or prebuilt clients."""
        if settings is not None:
            if confirm is None:
                confirm = default_confirm
            if llm is None:
                llm = LLMClient(settings.llm)
            if mcp is None:
                mcp = MCPClient(settings.mcp, confirm=confirm)
        if llm is None or mcp is None:
            raise TypeError("settings or clients must be provided")
        self._llm = llm
        self._mcp = mcp

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

    # ------------------------------------------------------------------
    def check_llm(self) -> dict[str, Any]:
        """Delegate to :class:`LLMClient.check_llm`."""

        return self._llm.check_llm()

    async def check_llm_async(self) -> dict[str, Any]:
        """Asynchronous variant of :meth:`check_llm`."""

        method = getattr(self._llm, "check_llm_async", None)
        if method is not None:
            result = method()
            if inspect.isawaitable(result):
                return await result
            return result
        return await asyncio.to_thread(self._llm.check_llm)

    # ------------------------------------------------------------------
    def check_tools(self) -> dict[str, Any]:
        """Delegate to :class:`MCPClient.check_tools`."""

        return self._mcp.check_tools()

    async def check_tools_async(self) -> dict[str, Any]:
        """Asynchronous variant of :meth:`check_tools`."""

        method = getattr(self._mcp, "check_tools_async", None)
        if method is not None:
            result = method()
            if inspect.isawaitable(result):
                return await result
            return result
        return await asyncio.to_thread(self._mcp.check_tools)

    # ------------------------------------------------------------------
    def _ensure_mcp_ready(self) -> None:
        """Invoke MCP readiness probe when the client exposes it."""

        ensure_ready = getattr(self._mcp, "ensure_ready", None)
        if callable(ensure_ready):
            ensure_ready()

    async def _ensure_mcp_ready_async(self) -> None:
        """Asynchronous readiness probe wrapper."""

        ensure_ready_async = getattr(self._mcp, "ensure_ready_async", None)
        if ensure_ready_async is not None:
            result = ensure_ready_async()
            if inspect.isawaitable(result):
                await result
            return
        ensure_ready = getattr(self._mcp, "ensure_ready", None)
        if callable(ensure_ready):
            await asyncio.to_thread(ensure_ready)

    # ------------------------------------------------------------------
    def run_command(
        self,
        text: str,
        *,
        history: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Drive an agent loop that may invoke MCP tools before replying."""

        conversation: list[Mapping[str, Any]] = list(history or [])
        conversation.append({"role": "user", "content": text})
        log_event(
            "AGENT_START",
            {"history_count": len(history or []), "prompt": self._preview(text, 200)},
        )
        try:
            result = self._run_loop(conversation)
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
    ) -> dict[str, Any]:
        """Asynchronous variant of :meth:`run_command`."""

        conversation: list[Mapping[str, Any]] = list(history or [])
        conversation.append({"role": "user", "content": text})
        log_event(
            "AGENT_START",
            {"history_count": len(history or []), "prompt": self._preview(text, 200)},
        )
        try:
            result = await self._run_loop_async(conversation)
        except Exception as exc:
            err = exception_to_mcp_error(exc)["error"]
            log_event("ERROR", {"error": err})
            return {"ok": False, "error": err}
        log_event("AGENT_RESULT", self._summarize_result(result))
        return result

    async def _call_tool_async(
        self, name: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        method = getattr(self._mcp, "call_tool_async", None)
        if method is not None:
            result = method(name, arguments)
            if inspect.isawaitable(result):
                return await result
            return result
        return await asyncio.to_thread(self._mcp.call_tool, name, arguments)

    async def _respond_async(
        self, conversation: Sequence[Mapping[str, Any]]
    ) -> LLMResponse:
        method = getattr(self._llm, "respond_async", None)
        if method is not None:
            result = method(conversation)
            if inspect.isawaitable(result):
                return await result
            return result
        return await asyncio.to_thread(self._llm.respond, conversation)

    def _run_loop(
        self, conversation: list[Mapping[str, Any]]
    ) -> dict[str, Any]:
        accumulated_results: list[Mapping[str, Any]] = []
        for step in range(self._MAX_THOUGHT_STEPS):
            response = self._llm.respond(conversation)
            conversation.append(self._assistant_message(response))
            self._log_step(step + 1, response)
            if not response.tool_calls:
                return self._success_result(response, accumulated_results)
            tool_messages, early_result, batch_results = self._execute_tool_calls(
                response.tool_calls
            )
            conversation.extend(tool_messages)
            accumulated_results.extend(batch_results)
            if early_result is not None:
                return early_result
        log_event(
            "AGENT_ABORTED",
            {"reason": "max-steps", "max_steps": self._MAX_THOUGHT_STEPS},
        )
        raise ToolValidationError(
            "LLM did not finish interaction within allowed steps",
        )

    async def _run_loop_async(
        self, conversation: list[Mapping[str, Any]]
    ) -> dict[str, Any]:
        accumulated_results: list[Mapping[str, Any]] = []
        for step in range(self._MAX_THOUGHT_STEPS):
            response = await self._respond_async(conversation)
            conversation.append(self._assistant_message(response))
            self._log_step(step + 1, response)
            if not response.tool_calls:
                return self._success_result(response, accumulated_results)
            tool_messages, early_result, batch_results = (
                await self._execute_tool_calls_async(response.tool_calls)
            )
            conversation.extend(tool_messages)
            accumulated_results.extend(batch_results)
            if early_result is not None:
                return early_result
        log_event(
            "AGENT_ABORTED",
            {"reason": "max-steps", "max_steps": self._MAX_THOUGHT_STEPS},
        )
        raise ToolValidationError(
            "LLM did not finish interaction within allowed steps",
        )

    def _execute_tool_calls(
        self, tool_calls: Sequence[LLMToolCall]
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[Mapping[str, Any]]]:
        messages: list[dict[str, Any]] = []
        successful: list[Mapping[str, Any]] = []
        for call in tool_calls:
            try:
                log_event(
                    "AGENT_TOOL_CALL",
                    {
                        "call_id": call.id,
                        "tool_name": call.name,
                        "arguments": call.arguments,
                    },
                )
                self._ensure_mcp_ready()
                result = self._mcp.call_tool(call.name, call.arguments)
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
                payload = {"ok": False, "error": error}
                messages.append(self._tool_message(call, payload))
                return messages, payload, successful
            if not isinstance(result, Mapping):
                payload = {
                    "ok": False,
                    "error": {
                        "type": "ToolProtocolError",
                        "message": "Tool returned unexpected payload",
                    },
                }
                messages.append(self._tool_message(call, payload))
                return messages, payload, successful
            result_dict = dict(result)
            log_payload: dict[str, Any] = {
                "call_id": call.id,
                "tool_name": call.name,
                "ok": bool(result_dict.get("ok", False)),
            }
            if not log_payload["ok"] and result_dict.get("error"):
                log_payload["error"] = result_dict["error"]
            log_event("AGENT_TOOL_RESULT", log_payload)
            messages.append(self._tool_message(call, result))
            if not result_dict.get("ok", False):
                return messages, result_dict, successful
            successful.append(self._enrich_tool_result(call, result))
        return messages, None, successful

    async def _execute_tool_calls_async(
        self, tool_calls: Sequence[LLMToolCall]
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[Mapping[str, Any]]]:
        messages: list[dict[str, Any]] = []
        successful: list[Mapping[str, Any]] = []
        for call in tool_calls:
            try:
                log_event(
                    "AGENT_TOOL_CALL",
                    {
                        "call_id": call.id,
                        "tool_name": call.name,
                        "arguments": call.arguments,
                    },
                )
                await self._ensure_mcp_ready_async()
                result = await self._call_tool_async(call.name, call.arguments)
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
                payload = {"ok": False, "error": error}
                messages.append(self._tool_message(call, payload))
                return messages, payload, successful
            if not isinstance(result, Mapping):
                payload = {
                    "ok": False,
                    "error": {
                        "type": "ToolProtocolError",
                        "message": "Tool returned unexpected payload",
                    },
                }
                messages.append(self._tool_message(call, payload))
                return messages, payload, successful
            result_dict = dict(result)
            log_payload = {
                "call_id": call.id,
                "tool_name": call.name,
                "ok": bool(result_dict.get("ok", False)),
            }
            if not log_payload["ok"] and result_dict.get("error"):
                log_payload["error"] = result_dict["error"]
            log_event("AGENT_TOOL_RESULT", log_payload)
            messages.append(self._tool_message(call, result))
            if not result_dict.get("ok", False):
                return messages, result_dict, successful
            successful.append(self._enrich_tool_result(call, result))
        return messages, None, successful

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

    def _enrich_tool_result(
        self, call: LLMToolCall, result: Mapping[str, Any]
    ) -> dict[str, Any]:
        payload = dict(result)
        payload.setdefault("tool_name", call.name)
        if "tool_arguments" not in payload:
            try:
                payload["tool_arguments"] = json.loads(
                    self._format_tool_arguments(call.arguments)
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                payload["tool_arguments"] = dict(call.arguments)
        return payload

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
