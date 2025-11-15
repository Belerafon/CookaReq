"""Shared configuration for transcript sanitisation."""

from __future__ import annotations

from ..util.json import JsonSanitizerLimits

HISTORY_JSON_LIMITS = JsonSanitizerLimits(
    max_depth=8,
    max_items=256,
    max_string_length=8000,
)

__all__ = ["HISTORY_JSON_LIMITS"]
