"""Local agent that combines LLM parsing with MCP tool execution."""

from __future__ import annotations

from typing import Any

import wx

from app.llm.client import LLMClient
from app.mcp.client import MCPClient
from app.mcp.utils import ErrorCode, mcp_error
from app.telemetry import log_event


class LocalAgent:
    """High-level agent aggregating LLM and MCP clients."""

    def __init__(
        self,
        cfg: wx.Config | None = None,
        *,
        llm: LLMClient | None = None,
        mcp: MCPClient | None = None,
    ) -> None:
        if llm is None:
            if cfg is None:
                raise TypeError("cfg or llm must be provided")
            llm = LLMClient(cfg)
        if mcp is None:
            if cfg is None:
                raise TypeError("cfg or mcp must be provided")
            mcp = MCPClient(cfg)
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
        return self._mcp._call_tool(name, arguments)
