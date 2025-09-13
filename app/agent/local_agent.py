"""Local agent that combines LLM parsing with MCP tool execution."""

from __future__ import annotations

from typing import Any, Callable

from ..llm.client import LLMClient
from ..mcp.client import MCPClient
from ..mcp.utils import ErrorCode, mcp_error
from ..settings import AppSettings
from ..telemetry import log_event
from ..confirm import confirm as default_confirm


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

    # ------------------------------------------------------------------
    def check_tools(self) -> dict[str, Any]:
        """Delegate to :class:`MCPClient.check_tools`."""

        return self._mcp.check_tools()

    # ------------------------------------------------------------------
    def run_command(self, text: str) -> dict[str, Any]:
        """Use the LLM to parse *text* and execute the resulting tool call."""

        try:
            name, arguments = self._llm.parse_command(text)
        except Exception as exc:
            err = mcp_error(ErrorCode.VALIDATION_ERROR, str(exc))["error"]
            log_event("ERROR", {"error": err})
            return {"error": err}
        return self._mcp.call_tool(name, arguments)
