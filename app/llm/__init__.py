"""LLM integration utilities."""

from typing import TYPE_CHECKING, Any

__all__ = ["LLMClient"]

if TYPE_CHECKING:  # pragma: no cover - typing helper
    from .client import LLMClient


def __getattr__(name: str) -> Any:
    """Lazily expose heavy modules to avoid import cycles."""
    if name == "LLMClient":
        from .client import LLMClient

        return LLMClient
    raise AttributeError(f"module 'app.llm' has no attribute {name!r}")
