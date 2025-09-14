"""Shared system prompt and tool schemas for LLM integration.

This module centralises the description of available MCP tools and the
system prompt used when asking the language model to translate user text
into structured tool calls.  Having a single source of truth simplifies
testing and keeps the LLM contract consistent across components.
"""

from __future__ import annotations

from typing import Any

__all__ = ["SYSTEM_PROMPT", "TOOLS"]


# Prompt instructing the model to always return a tool call in the
# OpenAI-compatible "function calling" format.
SYSTEM_PROMPT = (
    "Translate the user request into a call to one of the MCP tools. "
    "Always respond with a tool call and use the provided function schemas."
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
                    "per_page": {
                        "type": "integer",
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
            "name": "get_requirement",
            "description": "Retrieve a requirement by id",
            "parameters": {
                "type": "object",
                "properties": {"req_id": {"type": "integer"}},
                "required": ["req_id"],
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
                    "query": {"type": "string"},
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
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
                    "data": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
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
                                "enum": [
                                    "draft",
                                    "in_review",
                                    "approved",
                                    "baselined",
                                    "retired",
                                ],
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
                            "id",
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
                "required": ["data"],
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
                    "req_id": {"type": "integer"},
                    "patch": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                    "rev": {"type": "integer"},
                },
                "required": ["req_id", "patch", "rev"],
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
                    "req_id": {"type": "integer"},
                    "rev": {"type": "integer"},
                },
                "required": ["req_id", "rev"],
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
                    "source_id": {"type": "integer"},
                    "derived_id": {"type": "integer"},
                    "link_type": {"type": "string"},
                    "rev": {"type": "integer"},
                },
                "required": [
                    "source_id",
                    "derived_id",
                    "link_type",
                    "rev",
                ],
                "additionalProperties": False,
            },
        },
    },
]
