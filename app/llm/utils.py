"""Utility helpers shared by LLM modules."""

from __future__ import annotations

from typing import Any, Mapping

__all__ = ["extract_mapping"]


def extract_mapping(obj: Any) -> Mapping[str, Any] | None:
    """Return a mapping representation of *obj* when possible."""

    if isinstance(obj, Mapping):
        return obj
    for attr in ("model_dump", "dict"):
        method = getattr(obj, attr, None)
        if callable(method):
            try:
                data = method()
            except Exception:  # pragma: no cover - defensive
                continue
            if isinstance(data, Mapping):
                return data
    data = getattr(obj, "_data", None)
    if isinstance(data, Mapping):
        return data
    namespace = getattr(obj, "__dict__", None)
    if isinstance(namespace, Mapping):
        return namespace
    return None
