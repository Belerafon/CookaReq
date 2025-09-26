"""Validation helpers for LLM-produced MCP tool calls."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jsonschema import ValidationError
from jsonschema.validators import validator_for

from ..core.model import Priority, RequirementType, Status, Verification
from .spec import TOOLS

__all__ = ["KNOWN_TOOLS", "ToolValidationError", "validate_tool_call"]


class ToolValidationError(ValueError):
    """Raised when the LLM returns an invalid MCP tool invocation."""


def _build_validators() -> dict[str, Any]:
    """Compile JSON Schema validators for all declared tools."""

    validators: dict[str, Any] = {}
    for tool in TOOLS:
        function = tool.get("function", {})
        name = function.get("name")
        if not name:
            continue
        schema = function.get("parameters") or {"type": "object"}
        validator_cls = validator_for(schema)
        validator_cls.check_schema(schema)
        validators[name] = validator_cls(schema)
    return validators


_VALIDATORS = _build_validators()
KNOWN_TOOLS = frozenset(_VALIDATORS.keys())

_STATUS_VALUES = frozenset(status.value for status in Status)
_TYPE_VALUES = frozenset(req_type.value for req_type in RequirementType)
_PRIORITY_VALUES = frozenset(priority.value for priority in Priority)
_VERIFICATION_VALUES = frozenset(method.value for method in Verification)


def validate_tool_call(name: str, arguments: Mapping[str, Any] | None) -> dict[str, Any]:
    """Ensure *name* refers to a known tool and *arguments* match its schema."""

    if name not in _VALIDATORS:
        tools = ", ".join(sorted(KNOWN_TOOLS))
        raise ToolValidationError(
            f"Unknown MCP tool: {name}. Expected one of: {tools}"
        )
    if arguments is None:
        raise ToolValidationError("Tool arguments must be an object, got null")
    if not isinstance(arguments, Mapping):
        raise ToolValidationError("Tool arguments must be a JSON object")

    data = dict(arguments)
    validator = _VALIDATORS[name]
    try:
        validator.validate(data)
    except ValidationError as exc:
        detail = _format_validation_error(exc)
        raise ToolValidationError(
            f"Invalid arguments for {name}: {detail}"
        ) from exc
    _enforce_additional_constraints(name, data)
    return data


def _enforce_additional_constraints(name: str, data: dict[str, Any]) -> None:
    """Apply manual post-validation checks for *name* using *data*."""

    if name != "update_requirement_field":
        return
    field = data.get("field")
    if field == "status":
        _ensure_enum_value(name, "value", data.get("value"), _STATUS_VALUES)
    elif field == "type":
        _ensure_enum_value(name, "value", data.get("value"), _TYPE_VALUES)
    elif field == "priority":
        _ensure_enum_value(name, "value", data.get("value"), _PRIORITY_VALUES)
    elif field == "verification":
        _ensure_enum_value(name, "value", data.get("value"), _VERIFICATION_VALUES)


def _ensure_enum_value(
    tool: str, field: str, value: Any, allowed: frozenset[str]
) -> None:
    """Ensure *value* is contained in *allowed* for ``field`` of ``tool``."""

    if not isinstance(value, str) or value not in allowed:
        expected = ", ".join(sorted(allowed))
        raise ToolValidationError(
            "Invalid arguments for "
            f"{tool}: {field}: {value!r} is not one of [{expected}]"
        )


def _format_validation_error(error: ValidationError) -> str:
    """Return a concise, human-readable description of *error*."""

    # Prefer more specific context errors when available (oneOf/anyOf, etc.).
    contexts = list(error.context) or [error]
    messages: list[str] = []
    seen: set[str] = set()
    for err in contexts:
        path = ".".join(str(part) for part in err.absolute_path)
        text = f"{path}: {err.message}" if path else err.message
        if text not in seen:
            messages.append(text)
            seen.add(text)
    return "; ".join(messages)
