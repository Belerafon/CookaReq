"""Shared system prompt and tool schemas for LLM integration.

This module centralises the description of available MCP tools and the
system prompt used when asking the language model to translate user text
into structured tool calls.  Having a single source of truth simplifies
testing and keeps the LLM contract consistent across components.
"""

from __future__ import annotations

from typing import Any

__all__ = ["SYSTEM_PROMPT", "TOOLS"]


_STATUS_VALUES = [
    "draft",
    "in_review",
    "approved",
    "baselined",
    "retired",
]
_STATUS_VALUES_WITH_NULL = _STATUS_VALUES + [None]


# Prompt instructing the model to prefer MCP tool calls while allowing
# conversational fallbacks when tools are not relevant.
SYSTEM_PROMPT = (
    "Translate the user request into a call to one of the MCP tools whenever "
    "the action relates to the requirements workspace. Use the provided "
    "function schemas for tool calls and ensure the arguments are valid JSON. "
    "If the prompt is purely conversational or tools are not applicable, "
    "reply in natural language without calling a tool. When listing or "
    "searching requirements you may combine filters: "
    "`list_requirements` accepts optional `page`, `per_page`, `status` and "
    "`labels`; `search_requirements` accepts `query`, `labels`, `status`, "
    "`page` and `per_page`. Status values: draft, in_review, approved, "
    "baselined, retired. Labels must be arrays of strings."
)


# JSON Schemas for the MCP tools that the model may invoke.  Each entry
# follows the structure expected by the OpenAI `tools` parameter.
TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_requirements",
            "description": "List requirements with optional pagination",
            "parameters": {
                "type": "object",
                "properties": {
                    "page": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "page number (1-based)",
                    },
                    "per_page": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "number of items per page",
                    },
                    "status": {
                        "type": ["string", "null"],
                        "enum": _STATUS_VALUES_WITH_NULL,
                        "description": "filter by lifecycle status",
                    },
                    "labels": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                        "description": "return requirements containing all labels",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_requirement",
            "description": "Retrieve a requirement by identifier",
            "parameters": {
                "type": "object",
                "properties": {"rid": {"type": "string"}},
                "required": ["rid"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_requirements",
            "description": "Search requirements by text or labels",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": ["string", "null"]},
                    "labels": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                    },
                    "status": {
                        "type": ["string", "null"],
                        "enum": _STATUS_VALUES_WITH_NULL,
                        "description": "filter search results by lifecycle status",
                    },
                    "page": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "page number (1-based)",
                    },
                    "per_page": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "number of items per page",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_requirement",
            "description": "Create a new requirement from JSON data",
            "parameters": {
                "type": "object",
                "properties": {
                    "prefix": {"type": "string"},
                    "data": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "statement": {"type": "string"},
                            "type": {
                                "enum": [
                                    "requirement",
                                    "constraint",
                                    "interface",
                                ],
                            },
                            "status": {
                                "enum": _STATUS_VALUES,
                            },
                            "owner": {"type": "string"},
                            "priority": {
                                "enum": ["low", "medium", "high"],
                            },
                            "source": {"type": "string"},
                            "verification": {
                                "enum": [
                                    "inspection",
                                    "analysis",
                                    "demonstration",
                                    "test",
                                ],
                            },
                            "labels": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "title",
                            "statement",
                            "type",
                            "status",
                            "owner",
                            "priority",
                            "source",
                            "verification",
                        ],
                        "additionalProperties": True,
                    },
                },
                "required": ["prefix", "data"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_requirement",
            "description": "Apply a JSON patch to a requirement",
            "parameters": {
                "type": "object",
                "properties": {
                    "rid": {"type": "string"},
                    "patch": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                    "rev": {"type": "integer"},
                },
                "required": ["rid", "patch", "rev"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_requirement",
            "description": "Delete a requirement",
            "parameters": {
                "type": "object",
                "properties": {
                    "rid": {"type": "string"},
                    "rev": {"type": "integer"},
                },
                "required": ["rid", "rev"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "link_requirements",
            "description": "Create a link between two requirements",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_rid": {"type": "string"},
                    "derived_rid": {"type": "string"},
                    "link_type": {
                        "type": "string",
                        "enum": ["parent"],
                    },
                    "rev": {"type": "integer"},
                },
                "required": [
                    "source_rid",
                    "derived_rid",
                    "link_type",
                    "rev",
                ],
                "additionalProperties": False,
            },
        },
    },
]
