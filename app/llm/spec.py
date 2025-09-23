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

_EDITABLE_FIELDS = [
    "title",
    "statement",
    "type",
    "status",
    "owner",
    "priority",
    "source",
    "verification",
    "acceptance",
    "conditions",
    "rationale",
    "assumptions",
    "notes",
    "modified_at",
    "approved_at",
]


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
    "baselined, retired. Labels must be arrays of strings. "
    "When editing a requirement use the specialised tools instead of JSON patches: "
    "`update_requirement_field` changes exactly one field at a time. Allowed "
    "field names: "
    + ", ".join(_EDITABLE_FIELDS)
    + ". Provide the new content via the `value` argument (use plain strings for "
    "text, ISO 8601 for timestamps). The server increments the revision automatically.\n"
    "`set_requirement_labels` replaces the full label list; pass an array of "
    "strings (use [] to clear all labels).\n"
    "`set_requirement_attachments` replaces attachments; supply an array of "
    "objects such as {\"path\": \"docs/spec.pdf\", \"note\": \"optional comment\"} or [] to "
    "remove them.\n"
    "`set_requirement_links` replaces outgoing trace links; provide an array of "
    "link objects (with at least `rid`) or plain RID strings; unknown RIDs will be marked suspect automatically. "
    "When the user references a requirement, always use its requirement identifier (RID) "
    "exactly as shown in the workspace context using the `<prefix><number>` "
    "format (case-sensitive). Each context entry follows the pattern `<RID> (id=..., prefix=...) — <title>`; "
    "the RID is the concatenation of the prefix and number (for example, `HLR1`). The workspace context may "
    "include a `Selected requirements` section listing highlighted items—if the user refers to the highlighted or "
    "selected requirement(s), resolve them using the RID(s) from that section. When a single requirement is selected, "
    "assume that RID is implied without requesting it again unless the user asks otherwise. Never pass only the numeric `id`. Examples:\n"
    "- Context entry \"SYS11 (id=11, prefix=SYS)\" and user request \"Write the text of the "
    "first requirement\" → call `get_requirement` with {\"rid\": \"SYS11\"}.\n"
    "- Context entry \"SYS3 (id=3, prefix=SYS)\" and user request \"Update the status of SYS3 "
    "to approved\" → call `update_requirement_field` with {\"rid\": \"SYS3\", "
    "\"field\": \"status\", \"value\": \"approved\"}.\n"
    "- Context entry \"SYS4 (id=4, prefix=SYS)\" and request \"Очисти все метки у SYS4\" → call "
    "`set_requirement_labels` with {\"rid\": \"SYS4\", \"labels\": []}.\n"
    "- Context entries \"HLR5 (id=5, prefix=HLR)\" and \"SYS11 (id=11, prefix=SYS)\" with user "
    "request \"Link SYS11 as a child of HLR5\" → call `link_requirements` with "
    "{\"source_rid\": \"HLR5\", \"derived_rid\": \"SYS11\", \"link_type\": \"parent\", \"rev\": 1}.\n"
    "- User request \"Find requirements with the UI label\" → call `search_requirements` with "
    "{\"labels\": [\"UI\"]}."
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
            "name": "update_requirement_field",
            "description": "Update a single field of a requirement",
            "parameters": {
                "type": "object",
                "properties": {
                    "rid": {"type": "string"},
                    "field": {"type": "string", "enum": _EDITABLE_FIELDS},
                    "value": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "number"},
                            {"type": "boolean"},
                            {"type": "object"},
                            {"type": "array"},
                            {"type": "null"},
                        ]
                    },
                },
                "required": ["rid", "field", "value"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_requirement_labels",
            "description": "Replace all labels attached to a requirement",
            "parameters": {
                "type": "object",
                "properties": {
                    "rid": {"type": "string"},
                    "labels": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                    },
                },
                "required": ["rid", "labels"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_requirement_attachments",
            "description": "Replace the attachment list of a requirement",
            "parameters": {
                "type": "object",
                "properties": {
                    "rid": {"type": "string"},
                    "attachments": {
                        "type": ["array", "null"],
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "note": {"type": "string"},
                            },
                            "required": ["path"],
                            "additionalProperties": True,
                        },
                    },
                },
                "required": ["rid", "attachments"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_requirement_links",
            "description": "Replace outgoing trace links of a requirement",
            "parameters": {
                "type": "object",
                "properties": {
                    "rid": {"type": "string"},
                    "links": {
                        "type": ["array", "null"],
                        "items": {
                            "oneOf": [
                                {"type": "string"},
                                {
                                    "type": "object",
                                    "properties": {
                                        "rid": {"type": "string"},
                                        "fingerprint": {"type": ["string", "null"]},
                                        "suspect": {"type": "boolean"},
                                    },
                                    "required": ["rid"],
                                    "additionalProperties": True,
                                },
                            ]
                        },
                    },
                },
                "required": ["rid", "links"],
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
