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
    def run_command(
        self,
        text: str,
        *,
        history: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Drive an agent loop that may invoke MCP tools before replying."""

        conversation: list[Mapping[str, Any]] = list(history or [])
        conversation.append({"role": "user", "content": text})
        try:
            return self._run_loop(conversation)
        except Exception as exc:
            err = exception_to_mcp_error(exc)["error"]
            log_event("ERROR", {"error": err})
            return {"ok": False, "error": err}

    async def run_command_async(
        self,
        text: str,
        *,
        history: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Asynchronous variant of :meth:`run_command`."""

        conversation: list[Mapping[str, Any]] = list(history or [])
        conversation.append({"role": "user", "content": text})
        try:
            return await self._run_loop_async(conversation)
        except Exception as exc:
            err = exception_to_mcp_error(exc)["error"]
            log_event("ERROR", {"error": err})
            return {"ok": False, "error": err}

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
            if not response.tool_calls:
                return self._success_result(response, accumulated_results)
            tool_messages, early_result, batch_results = self._execute_tool_calls(
                response.tool_calls
            )
            conversation.extend(tool_messages)
            accumulated_results.extend(batch_results)
            if early_result is not None:
                return early_result
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
            if not response.tool_calls:
                return self._success_result(response, accumulated_results)
            tool_messages, early_result, batch_results = (
                await self._execute_tool_calls_async(response.tool_calls)
            )
            conversation.extend(tool_messages)
            accumulated_results.extend(batch_results)
            if early_result is not None:
                return early_result
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
                result = self._mcp.call_tool(call.name, call.arguments)
            except Exception as exc:
                error = exception_to_mcp_error(exc)["error"]
                log_event("ERROR", {"error": error})
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
            messages.append(self._tool_message(call, result))
            if not result.get("ok", False):
                return messages, dict(result), successful
            successful.append(self._enrich_tool_result(call, result))
        return messages, None, successful

    async def _execute_tool_calls_async(
        self, tool_calls: Sequence[LLMToolCall]
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[Mapping[str, Any]]]:
        messages: list[dict[str, Any]] = []
        successful: list[Mapping[str, Any]] = []
        for call in tool_calls:
            try:
                result = await self._call_tool_async(call.name, call.arguments)
            except Exception as exc:
                error = exception_to_mcp_error(exc)["error"]
                log_event("ERROR", {"error": error})
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
            messages.append(self._tool_message(call, result))
            if not result.get("ok", False):
                return messages, dict(result), successful
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
