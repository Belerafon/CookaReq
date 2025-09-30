"""Shared exception types for LLM/MCP validation pipelines."""

from __future__ import annotations

__all__ = ["ToolValidationError"]


class ToolValidationError(ValueError):
    """Raised when the agent cannot interpret an LLM tool invocation."""

    pass
