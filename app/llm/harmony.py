"""Utilities for rendering Harmony prompts and tool definitions."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date
import json
from typing import Any
from collections.abc import Iterable, Mapping, Sequence


HARMONY_KNOWLEDGE_CUTOFF = "2024-06"
"""Default knowledge cutoff advertised in Harmony system messages."""

HARMONY_NAMESPACE = "functions"
"""Namespace used when exposing MCP tools to Harmony models."""


def convert_tools_for_harmony(
    tools: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Convert Chat Completions tool definitions for the Responses API.

    The OpenAI Python client expects function tools passed to ``responses.create``
    to follow the new schema without the nested ``{"function": {...}}`` block
    that Chat Completions used. When Harmony is enabled we still keep the
    original structure for prompt rendering, but outbound API calls must use
    the flattened representation. This helper preserves non-function tools and
    performs a deep copy so the caller can safely mutate the result.
    """

    if not tools:
        return []

    converted: list[dict[str, Any]] = []
    for entry in tools:
        if not isinstance(entry, Mapping):
            continue
        tool_type = entry.get("type")
        if tool_type != "function":
            converted.append(copy.deepcopy(dict(entry)))
            continue
        function = entry.get("function")
        if isinstance(function, Mapping):
            name = function.get("name")
            if not name:
                continue
            flattened: dict[str, Any] = {"type": "function", "name": str(name)}
            description = function.get("description")
            if description:
                flattened["description"] = str(description)
            parameters = function.get("parameters")
            if isinstance(parameters, Mapping):
                flattened["parameters"] = copy.deepcopy(dict(parameters))
            strict = function.get("strict")
            if strict is not None:
                flattened["strict"] = bool(strict)
            converted.append(flattened)
            continue
        # Already flattened or malformed; keep best-effort copy.
        converted.append(
            copy.deepcopy({k: v for k, v in entry.items() if k != "function"})
        )

    return converted


@dataclass(frozen=True, slots=True)
class HarmonyPrompt:
    """Container with the rendered Harmony prompt and its components."""

    prompt: str
    system_message: str
    developer_message: str
    history_messages: tuple[str, ...]

    def snapshot(self) -> Mapping[str, Any]:
        """Return a serialisable snapshot for logging and debugging."""

        return {
            "format": "harmony",
            "system_message": self.system_message,
            "developer_message": self.developer_message,
            "history_messages": list(self.history_messages),
            "prompt": self.prompt,
        }


def render_harmony_prompt(
    *,
    instruction_blocks: Sequence[str],
    history: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]] | None,
    reasoning_level: str = "high",
    current_date: str | None = None,
    knowledge_cutoff: str = HARMONY_KNOWLEDGE_CUTOFF,
) -> HarmonyPrompt:
    """Render conversation *history* into a Harmony prompt string."""

    system_message = _render_system_message(
        reasoning_level=reasoning_level,
        current_date=current_date or date.today().isoformat(),
        knowledge_cutoff=knowledge_cutoff,
        has_tools=bool(tools),
    )
    developer_message = _render_developer_message(
        instruction_blocks,
        tools or (),
    )
    history_messages = tuple(
        message
        for rendered in (_render_history_message(entry) for entry in history)
        if (message := rendered.strip())
    )
    prompt_parts = [system_message, developer_message, *history_messages, "<|start|>assistant"]
    prompt = "\n".join(prompt_parts)
    return HarmonyPrompt(
        prompt=prompt,
        system_message=system_message,
        developer_message=developer_message,
        history_messages=history_messages,
    )


def _render_system_message(
    *,
    reasoning_level: str,
    current_date: str,
    knowledge_cutoff: str,
    has_tools: bool,
) -> str:
    lines = [
        "You are ChatGPT, a large language model trained by OpenAI.",
        f"Knowledge cutoff: {knowledge_cutoff}",
        f"Current date: {current_date}",
        f"Reasoning: {reasoning_level}",
        "# Valid channels: analysis, commentary, final. Channel must be included for every message.",
    ]
    if has_tools:
        lines.append(
            "Calls to these tools must go to the commentary channel: 'functions'."
        )
    content = "\n".join(lines)
    return f"<|start|>system<|message|>{content}<|end|>"


def _render_developer_message(
    instruction_blocks: Sequence[str],
    tools: Sequence[Mapping[str, Any]],
) -> str:
    sections: list[str] = []
    instructions_text = "\n\n".join(
        block.strip() for block in instruction_blocks if block and block.strip()
    )
    if instructions_text:
        sections.append("# Instructions")
        sections.append(instructions_text)
    tools_block = _format_tools_namespace(tools)
    if tools_block:
        sections.append(tools_block)
    developer_content = "\n".join(sections) if sections else ""
    return f"<|start|>developer<|message|>{developer_content}<|end|>"


def _render_history_message(message: Mapping[str, Any]) -> str:
    role = str(message.get("role") or "").lower()
    content = str(message.get("content") or "")
    if role == "user":
        return f"<|start|>user<|message|>{content}<|end|>"
    if role == "assistant":
        rendered: list[str] = []
        tool_calls = message.get("tool_calls")
        for tool_call in _normalise_tool_call_entries(tool_calls):
            rendered.append(_render_tool_call(tool_call))
        if content:
            rendered.append(
                f"<|start|>assistant<|channel|>final<|message|>{content}<|end|>"
            )
        return "\n".join(rendered)
    if role == "tool":
        tool_name = str(message.get("name") or "tool")
        call_id = message.get("tool_call_id")
        header = f"<|start|>{tool_name}"
        if call_id:
            header += f" call_id={call_id}"
        header += " to=assistant<|channel|>commentary"
        return f"{header}<|message|>{content}<|end|>"
    if role == "system":
        # System messages are appended to developer instructions separately.
        return ""
    return f"<|start|>{role or 'assistant'}<|message|>{content}<|end|>"


def _render_tool_call(tool_call: Mapping[str, Any]) -> str:
    function = tool_call.get("function") if isinstance(tool_call, Mapping) else None
    if isinstance(function, Mapping):
        name = function.get("name")
        arguments = function.get("arguments")
    else:
        name = None
        arguments = None
    name = str(name or "")
    call_id = tool_call.get("id") if isinstance(tool_call, Mapping) else None
    recipient = f"{HARMONY_NAMESPACE}.{name}" if name else ""
    header = "<|start|>assistant<|channel|>commentary"
    if recipient:
        header += f" to={recipient}"
    if call_id:
        header += f" call_id={call_id}"
    header += " <|constrain|>json"
    arguments_text = _tool_arguments_text(arguments)
    return f"{header}<|message|>{arguments_text}<|end|>"


def _normalise_tool_call_entries(tool_calls: Any) -> Iterable[Mapping[str, Any]]:
    if not tool_calls:
        return ()
    if isinstance(tool_calls, Mapping):
        return (tool_calls,)
    if isinstance(tool_calls, Sequence) and not isinstance(tool_calls, (str, bytes, bytearray)):
        return tuple(entry for entry in tool_calls if isinstance(entry, Mapping))
    return ()


def _tool_arguments_text(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments
    try:
        return json.dumps(arguments or {}, ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}"


def _format_tools_namespace(tools: Sequence[Mapping[str, Any]]) -> str:
    if not tools:
        return ""
    lines = ["# Tools", f"## {HARMONY_NAMESPACE}", f"namespace {HARMONY_NAMESPACE} {{"]
    first = True
    for entry in tools:
        function = entry.get("function") if isinstance(entry, Mapping) else None
        if not isinstance(function, Mapping):
            continue
        name = function.get("name")
        if not name:
            continue
        description = function.get("description")
        parameters = function.get("parameters") if isinstance(function, Mapping) else None
        if not first:
            lines.append("")
        first = False
        if description:
            lines.append(f"    // {description}")
        signature = _format_function_signature(str(name), parameters)
        lines.append(f"    {signature}")
    lines.append(f"}} // namespace {HARMONY_NAMESPACE}")
    return "\n".join(lines).rstrip()


def _format_function_signature(name: str, parameters: Mapping[str, Any] | None) -> str:
    if not parameters:
        return f"type {name} = () => any;"
    annotation = _schema_to_typescript(parameters, indent_level=2)
    return f"type {name} = (_: {annotation}) => any;"


def _schema_to_typescript(schema: Mapping[str, Any], *, indent_level: int) -> str:
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        variants = [
            _schema_to_typescript({**schema, "type": variant}, indent_level=indent_level)
            for variant in schema_type
        ]
        unique = []
        for item in variants:
            if item not in unique:
                unique.append(item)
        return " | ".join(unique) if unique else "any"
    if schema_type == "object":
        return _format_object_schema(schema, indent_level)
    if schema_type == "array":
        items = schema.get("items")
        inner = (
            _schema_to_typescript(items, indent_level=indent_level)
            if isinstance(items, Mapping)
            else "any"
        )
        return f"Array<{inner}>"
    if schema_type == "string":
        return _enum_or_default(schema, fallback="string")
    if schema_type in {"integer", "number"}:
        return "number"
    if schema_type == "boolean":
        return "boolean"
    if schema_type == "null":
        return "null"
    if "enum" in schema:
        return _enum_or_default(schema, fallback="any")
    return "any"


def _format_object_schema(schema: Mapping[str, Any], indent_level: int) -> str:
    indent = "    " * indent_level
    inner_indent = indent + "    "
    properties = schema.get("properties")
    required = set(schema.get("required") or [])
    lines = ["{"]
    if isinstance(properties, Mapping):
        for name, subschema in properties.items():
            if not isinstance(subschema, Mapping):
                continue
            field_optional = name not in required
            comment_lines = []
            description = subschema.get("description")
            if description:
                comment_lines.append(f"{inner_indent}// {description}")
            if "default" in subschema:
                default_value = json.dumps(subschema["default"], ensure_ascii=False)
                comment_lines.append(f"{inner_indent}// default: {default_value}")
            field_type = _schema_to_typescript(subschema, indent_level=indent_level + 1)
            lines.extend(comment_lines)
            optional_suffix = "?" if field_optional else ""
            lines.append(
                f"{inner_indent}{name}{optional_suffix}: {field_type},"
            )
    additional = schema.get("additionalProperties")
    if additional:
        additional_type = (
            _schema_to_typescript(additional, indent_level=indent_level + 1)
            if isinstance(additional, Mapping)
            else "any"
        )
        lines.append(f"{inner_indent}[key: string]: {additional_type},")
    lines.append(f"{indent}}}")
    return "\n".join(lines)


def _enum_or_default(schema: Mapping[str, Any], *, fallback: str) -> str:
    values = schema.get("enum")
    if not values:
        return fallback
    formatted: list[str] = []
    for value in values:
        if value is None:
            formatted.append("null")
        else:
            formatted.append(json.dumps(value, ensure_ascii=False))
    unique = []
    for item in formatted:
        if item not in unique:
            unique.append(item)
    return " | ".join(unique)
