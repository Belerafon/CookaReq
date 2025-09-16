"""Local agent that combines LLM parsing with MCP tool execution."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable, Mapping

from ..confirm import confirm as default_confirm
from ..llm.client import LLMClient
from ..llm.validation import validate_tool_call
from ..mcp.client import MCPClient
from ..mcp.utils import exception_to_mcp_error
from ..settings import AppSettings
from ..telemetry import log_event


class LocalAgent:
    """High-level agent aggregating LLM and MCP clients."""

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
    def run_command(self, text: str) -> dict[str, Any]:
        """Use the LLM to parse *text* and execute the resulting tool call.

        Returns a dictionary following the same ``{"ok": bool, "error": ...}``
        contract as :meth:`MCPClient.call_tool`.
        """

        try:
            name, arguments = self._llm.parse_command(text)
            arguments = validate_tool_call(name, arguments)
        except Exception as exc:
            err = exception_to_mcp_error(exc)["error"]
            log_event("ERROR", {"error": err})
            return {"ok": False, "error": err}
        return self._mcp.call_tool(name, arguments)

    async def run_command_async(self, text: str) -> dict[str, Any]:
        """Asynchronous variant of :meth:`run_command`."""

        try:
            name, arguments = await self._parse_command_async(text)
            arguments = validate_tool_call(name, arguments)
        except Exception as exc:
            err = exception_to_mcp_error(exc)["error"]
            log_event("ERROR", {"error": err})
            return {"ok": False, "error": err}
        return await self._call_tool_async(name, arguments)

    # ------------------------------------------------------------------
    async def _parse_command_async(self, text: str) -> tuple[str, Mapping[str, Any]]:
        method = getattr(self._llm, "parse_command_async", None)
        if method is not None:
            result = method(text)
            if inspect.isawaitable(result):
                return await result
            return result
        return await asyncio.to_thread(self._llm.parse_command, text)

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
