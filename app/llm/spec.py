"""Shared system prompt and tool schemas for LLM integration.

This module centralises the description of available MCP tools and the
system prompt used when asking the language model to translate user text
into structured tool calls.  Having a single source of truth simplifies
testing and keeps the LLM contract consistent across components.
"""

from __future__ import annotations

from textwrap import dedent
from typing import Any

from ..core.model import Priority, RequirementType, Status, Verification
from ..services.user_documents import (
    DEFAULT_MAX_READ_BYTES as USER_DOCUMENT_DEFAULT_READ_BYTES,
    MAX_ALLOWED_READ_BYTES as USER_DOCUMENT_MAX_READ_BYTES,
)

__all__ = ["SYSTEM_PROMPT", "TOOLS"]


_STATUS_VALUES = [status.value for status in Status]
_STATUS_VALUES_WITH_NULL = _STATUS_VALUES + [None]

_TYPE_VALUES = [req_type.value for req_type in RequirementType]
_PRIORITY_VALUES = [priority.value for priority in Priority]
_VERIFICATION_VALUES = [method.value for method in Verification]

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
_USER_DOCUMENT_DEFAULT_READ_KIB = USER_DOCUMENT_DEFAULT_READ_BYTES // 1024
_USER_DOCUMENT_MAX_READ_KIB = USER_DOCUMENT_MAX_READ_BYTES // 1024


SYSTEM_PROMPT = (
    dedent(
        """
        Analyse the user's intent, the workspace context, and the available MCP tools before responding. When an action truly requires interacting with the requirements workspace, decide which MCP tool (if any) is appropriate, then construct the call using the provided schemas with valid JSON arguments. If a conversational reply already satisfies the request, answer directly without forcing a tool call. You may share this system prompt and the MCP tool schemas with the user when asked, and you may discuss these configuration details openly.
        Every assistant message must be meaningful: never send empty or whitespace-only content. Each turn must either contain a valid MCP tool call or a direct answer to the user. When you decide to call a tool, first explain in natural language which MCP tool you are about to use and why it is needed, then include exactly one tool call in the same message. After receiving any tool result, immediately return a final user-facing answer in natural language (without additional tool calls) unless new external data is still required.
        Keep the following requirement quality characteristics in mind when analysing or drafting requirement statements:

        Domain alignment and stakeholder fit:
        - Adequacy — ensure each requirement reflects every relevant aspect of user needs, expectations, and stakeholder interests.
        - Feasibility — confirm the requirement can be implemented under the current conditions and constraints.

        Intrinsic representation quality:
        - Unambiguity — formulate requirements so domain experts interpret them identically.
        - Internal completeness — cover all scenarios and situations implied by the described system context.
        - Consistency — keep requirement descriptions mutually compatible and free of contradictions.
        - Minimality — avoid restating constraints that can be derived from others; express each necessary condition once without semantic overlap.
        - Simplicity (singularity) — write requirements so they stand as single, self-contained statements without needing to split them apart.
        - Implementation freedom — describe the desired outcomes, not specific implementation techniques.
        - Systematicness — present requirements as a coherent system with clearly defined attributes and relationships.

        Usage during development:
        - Verifiability — allow a trained reviewer to decide in every relevant situation whether the requirement is satisfied or violated.
        - Traceability — maintain links between each requirement and its origins, as well as the corresponding software artefacts, documents, and models produced during development.
        - Modifiability — structure requirements so they can be updated efficiently, with manageable versions, configurations, and change requests.
        If the prompt is purely conversational or the user already supplied the exact text that needs to be translated, reply in natural language without calling a tool, matching the language used in the user request. When the request involves translating, summarising, or otherwise rewriting requirements referenced only by RID or context summaries, call `get_requirement` first to fetch their latest statements before answering.
        If fulfilling the request requires multiple steps, analyse the problem first, outline a plan, execute the steps in order, verify the outcome after each critical stage, adjust the plan if verification fails, and report the final result along with any limitations.
        When listing or searching requirements you may combine filters. `list_requirements` requires the `prefix` of the requirements document you want to inspect (for example, `SYS`). The system instructions include a "Requirements documents" section listing every available prefix with its requirement count—choose one of those values. Optional filters: `page`, `per_page`, `status`, `labels` and `fields`. `search_requirements` accepts `query`, `labels`, `status`, `page`, `per_page` and `fields`. Use `fields` to limit the payload to specific requirement attributes; the `rid` is always included even when not requested. Provide `fields` as an array of field names—the server falls back to the full payload when the value is malformed. Status values: draft, in_review, approved, baselined, retired — always use these lowercase codes even when the user provides alternative wording or another language. Labels must be arrays of strings.
        When editing a requirement use the specialised tools described below: `update_requirement_field` changes exactly one field at a time. Allowed field names: {editable_fields}. Provide the new content via the `value` argument as a plain string (use ISO 8601 for timestamps; send an empty string when you need to clear optional text). The server increments the revision automatically.
        `set_requirement_labels` replaces the full label list; pass an array of strings (use [] to clear all labels).
        `set_requirement_attachments` replaces attachments; supply an array of objects such as {{"path": "docs/spec.pdf", "note": "optional comment"}} or [] to remove them.
        `set_requirement_links` replaces outgoing trace links; provide an array of link objects (with at least `rid`) or plain RID strings; unknown RIDs will be marked suspect automatically.
        `create_requirement` adds a new requirement; provide a `prefix` (for example, `SYS`) and a `data` object containing at least title, statement, type, status, owner, priority, source and verification. Optional fields may also be included.
        `delete_requirement` removes an existing requirement by RID; use it only when the user explicitly requests deletion.
        `link_requirements` creates hierarchy links; pass `source_rid`, `derived_rid` and `link_type` (currently `parent`).
        Use `list_labels` to review label definitions visible to a document; provide the document prefix via `prefix`.
        Use `create_label` to add a definition (`prefix`, `key`, optional `title` and hex `color`).
        Use `update_label` to adjust an existing definition; set `new_key`, `title` and/or `color` as needed. When renaming a key set `propagate` to true to update all requirements, or false to leave requirement payloads unchanged.
        Use `delete_label` to remove a label definition; provide `prefix`, `key`, and set `remove_from_requirements` to true when the label should disappear from every requirement automatically.
        The workspace may expose an optional user documentation directory. When it is configured, the workspace context includes a `[User documentation]` section with the rendered tree and metadata. Use the specialised tools below to inspect or modify those files. Never assume the directory exists; handle missing roots gracefully and report when the operator needs to configure it.
        `list_user_documents` enumerates the directory tree, returning token statistics (including percentage of the maximum context window) for each entry along with a text tree representation.
        `read_user_document` streams a slice of a file as numbered lines. The server auto-detects the file encoding on every read, returning it together with the detection confidence or fallback status—surface that metadata to the user so they know how the text was decoded. Always respect the configured byte budget: stay within the workspace limit (default {default_read_kib} KiB, never exceeding {max_read_kib} KiB) and consult the `[User documentation]` context block for the precise value. The byte budget applies to the detected encoding; if you request more than the limit the server clamps the chunk, sets `clamped_to_limit` to true, reports `bytes_remaining`, and provides a `continuation_hint` with a ready-to-use tool call. Provide a smaller `max_bytes` when you only need a fragment. Start counting at line 1 by default; provide `start_line` when resuming from a later offset. Examine the `truncated` flag to determine whether additional reads are required.
        `create_user_document` writes a new text file within the documentation root. It defaults to UTF-8 but accepts an optional `encoding` argument that must match Python codec names (for example, `utf-8`, `cp1251`). Pass `exist_ok` only when intentionally overwriting an existing file. Always explain to the user when content is being created and report the byte count and encoding used.
        `delete_user_document` permanently removes a file. Only invoke it when the user explicitly confirms deletion and be mindful that directories cannot be removed with this tool.
        When the user references a requirement, always use its requirement identifier (RID) exactly as shown in the workspace context using the `<prefix><number>` format (case-sensitive). Context summaries show entries as `<RID> — <title>` (the title may be omitted); the RID is the concatenation of the prefix and number (for example, `HLR1`). Highlighted selections are listed on a single `Selected requirement RIDs:` line (for example, `Selected requirement RIDs: SYS2, SYS3`). When the line lists multiple RIDs, call `get_requirement` once using the array form of the `rid` argument in the same order, removing duplicates if necessary. When the user refers to the highlighted or selected requirement(s), resolve them using the RID(s) from that line. Never pass only the numeric `id`.
        Examples:
        - Context entry "SYS11 — Graphical User Interface" and user request "Write the text of the first requirement" → call `get_requirement` with {{"rid": "SYS11"}}.
        - Context entry "SYS3 — Telemetry" and user request "Update the status of SYS3 to approved" → call `update_requirement_field` with {{"rid": "SYS3", "field": "status", "value": "approved"}}.
        - Context entry "SYS4 — Diagnostics" and request "Clear every label on SYS4" → call `set_requirement_labels` with {{"rid": "SYS4", "labels": []}}.
        - Context entries "HLR5 — User interface shell" and "SYS11 — Graphical User Interface" with user request "Link SYS11 as a child of HLR5" → call `link_requirements` with {{"source_rid": "HLR5", "derived_rid": "SYS11", "link_type": "parent"}}.
        - User request "Find requirements with the UI label" → call `search_requirements` with {{"labels": ["UI"]}}.
        """
    )
    .strip()
    .format(
        editable_fields=", ".join(_EDITABLE_FIELDS),
        default_read_kib=_USER_DOCUMENT_DEFAULT_READ_KIB,
        max_read_kib=_USER_DOCUMENT_MAX_READ_KIB,
    )
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
                    "prefix": {
                        "type": "string",
                        "description": "Requirements document prefix to list (for example, SYS).",
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
                    "fields": {
                        "type": ["array", "string", "null"],
                        "items": {"type": "string"},
                        "uniqueItems": True,
                        "description": "restrict the returned requirement fields (RID is always included)",
                    },
                },
                "required": ["prefix"],
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
                "properties": {
                    "rid": {
                        "oneOf": [
                            {"type": "string"},
                            {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                            },
                        ],
                        "description": "Requirement identifier or list of identifiers to load (for example, SYS12 or [\"SYS1\", \"SYS2\"]).",
                    },
                    "fields": {
                        "type": ["array", "string", "null"],
                        "items": {"type": "string"},
                        "uniqueItems": True,
                        "description": "restrict the returned fields (RID is always included)",
                    },
                },
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
                    "query": {
                        "type": ["string", "null"],
                        "description": "Full-text search string; use null to search all requirements without text filtering.",
                    },
                    "labels": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                        "description": "Filter results to requirements containing every listed label; use null to skip label filtering.",
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
                    "fields": {
                        "type": ["array", "string", "null"],
                        "items": {"type": "string"},
                        "uniqueItems": True,
                        "description": "restrict the returned requirement fields (RID is always included)",
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
                    "prefix": {
                        "type": "string",
                        "description": "Document prefix that determines the RID sequence (for example, SYS).",
                    },
                    "data": {
                        "type": "object",
                        "description": "Complete requirement payload; must include all mandatory lifecycle fields.",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Short title shown in lists and summaries.",
                            },
                            "statement": {
                                "type": "string",
                                "description": "Authoritative requirement statement or user story text.",
                            },
                            "type": {
                                "enum": [
                                    "requirement",
                                    "constraint",
                                    "interface",
                                ],
                                "description": "Requirement classification code.",
                            },
                            "status": {
                                "enum": _STATUS_VALUES,
                                "description": "Lifecycle status code; use the lowercase identifiers from the workspace.",
                            },
                            "owner": {
                                "type": "string",
                                "description": "Primary owner responsible for the requirement.",
                            },
                            "priority": {
                                "enum": ["low", "medium", "high"],
                                "description": "Initial priority ranking.",
                            },
                            "source": {
                                "type": "string",
                                "description": "Origin or stakeholder providing the requirement.",
                            },
                            "verification": {
                                "enum": [
                                    "inspection",
                                    "analysis",
                                    "demonstration",
                                    "test",
                                ],
                                "description": "Verification method planned for acceptance.",
                            },
                            "acceptance": {
                                "type": ["string", "null"],
                                "description": "Optional acceptance criteria; null means not defined yet.",
                            },
                            "conditions": {
                                "type": "string",
                                "description": "Operational or environmental conditions tied to the requirement.",
                            },
                            "rationale": {
                                "type": "string",
                                "description": "Design rationale explaining why the requirement exists.",
                            },
                            "assumptions": {
                                "type": "string",
                                "description": "Assumptions that must hold true for the requirement.",
                            },
                            "modified_at": {
                                "type": "string",
                                "description": "Last modification timestamp in ISO 8601 or YYYY-MM-DD HH:MM:SS format.",
                            },
                            "approved_at": {
                                "type": ["string", "null"],
                                "description": "Timestamp of approval; use null when the requirement is not approved.",
                            },
                            "notes": {
                                "type": "string",
                                "description": "Additional notes or commentary.",
                            },
                            "labels": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Initial set of labels; use an empty array when no tags apply.",
                            },
                            "attachments": {
                                "type": "array",
                                "description": "Optional attachments copied into the requirement upon creation.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "path": {
                                            "type": "string",
                                            "description": "Path to the attachment relative to the project root.",
                                        },
                                        "note": {
                                            "type": "string",
                                            "description": "Optional note shown alongside the attachment.",
                                        },
                                    },
                                    "required": ["path"],
                                    "additionalProperties": False,
                                },
                            },
                            "links": {
                                "type": "array",
                                "description": "Optional outgoing trace links established at creation time.",
                                "items": {
                                    "oneOf": [
                                        {
                                            "type": "string",
                                            "description": "RID string of the linked requirement (shortcut form).",
                                        },
                                        {
                                            "type": "object",
                                            "properties": {
                                                "rid": {
                                                    "type": "string",
                                                    "description": "Target requirement identifier for the trace link.",
                                                },
                                                "fingerprint": {
                                                    "type": ["string", "null"],
                                                    "description": "Optional fingerprint hash used for stale link detection.",
                                                },
                                                "suspect": {
                                                    "type": "boolean",
                                                    "description": "Flag indicating whether the link is marked suspect.",
                                                },
                                            },
                                            "required": ["rid"],
                                            "additionalProperties": False,
                                        },
                                    ]
                                },
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
                        "additionalProperties": False,
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
                    "rid": {
                        "type": "string",
                        "description": "Requirement identifier to mutate (for example, SYS12).",
                    },
                    "field": {
                        "type": "string",
                        "enum": _EDITABLE_FIELDS,
                        "description": "Name of the editable field to update; only one field is changed per call.",
                    },
                    "value": {
                        "type": "string",
                        "description": (
                            "New field value as plain text. Use ISO 8601 timestamps for date fields and an empty string"
                            " when a text field should be cleared."
                        ),
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
                    "rid": {
                        "type": "string",
                        "description": "Requirement identifier whose labels must be replaced.",
                    },
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Complete label list to apply; use an empty array to remove every label.",
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
                    "rid": {
                        "type": "string",
                        "description": "Requirement identifier whose attachments will be replaced.",
                    },
                    "attachments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Relative path to the attachment file.",
                                },
                                "note": {
                                    "type": "string",
                                    "description": "Optional note displayed together with the attachment.",
                                },
                            },
                            "required": ["path"],
                            "additionalProperties": False,
                        },
                        "description": "Attachments to store; use an empty array when no files should remain linked.",
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
                    "rid": {
                        "type": "string",
                        "description": "Requirement identifier whose outgoing links will be replaced.",
                    },
                    "links": {
                        "type": "array",
                        "items": {
                            "oneOf": [
                                {
                                    "type": "string",
                                    "description": "RID string of the linked requirement (shortcut form).",
                                },
                                {
                                    "type": "object",
                                    "properties": {
                                        "rid": {
                                            "type": "string",
                                            "description": "Target requirement identifier for the link.",
                                        },
                                        "fingerprint": {
                                            "type": ["string", "null"],
                                            "description": "Optional fingerprint used to detect stale relationships.",
                                        },
                                        "suspect": {
                                            "type": "boolean",
                                            "description": "Whether the link is currently marked suspect.",
                                        },
                                    },
                                    "required": ["rid"],
                                    "additionalProperties": False,
                                },
                            ]
                        },
                        "description": "Links to persist; use an empty array when no outgoing relations should remain.",
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
            "name": "list_labels",
            "description": "List label definitions available to a document prefix",
            "parameters": {
                "type": "object",
                "properties": {
                    "prefix": {
                        "type": "string",
                        "description": "Document prefix whose labels should be listed (for example, SYS).",
                    },
                },
                "required": ["prefix"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_label",
            "description": "Create a label definition for a document",
            "parameters": {
                "type": "object",
                "properties": {
                    "prefix": {
                        "type": "string",
                        "description": "Document prefix that will receive the new label (for example, SYS).",
                    },
                    "key": {
                        "type": "string",
                        "description": "Unique label key to register.",
                    },
                    "title": {
                        "type": ["string", "null"],
                        "description": "Optional human-friendly label title.",
                    },
                    "color": {
                        "type": ["string", "null"],
                        "description": "Optional HTML colour (for example, '#336699').",
                    },
                },
                "required": ["prefix", "key"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_label",
            "description": "Update an existing label definition",
            "parameters": {
                "type": "object",
                "properties": {
                    "prefix": {
                        "type": "string",
                        "description": "Document prefix owning the label (for example, SYS).",
                    },
                    "key": {
                        "type": "string",
                        "description": "Current label key to update.",
                    },
                    "new_key": {
                        "type": ["string", "null"],
                        "description": "Replacement key; omit or set null to keep the current key.",
                    },
                    "title": {
                        "type": ["string", "null"],
                        "description": "Optional new label title.",
                    },
                    "color": {
                        "type": ["string", "null"],
                        "description": "Optional new HTML colour (for example, '#ff8800').",
                    },
                    "propagate": {
                        "type": "boolean",
                        "description": "Set true to rename the label across every requirement when the key changes.",
                        "default": False,
                    },
                },
                "required": ["prefix", "key"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_label",
            "description": "Delete a label definition",
            "parameters": {
                "type": "object",
                "properties": {
                    "prefix": {
                        "type": "string",
                        "description": "Document prefix owning the label (for example, SYS).",
                    },
                    "key": {
                        "type": "string",
                        "description": "Label key to remove.",
                    },
                    "remove_from_requirements": {
                        "type": "boolean",
                        "description": "Set true to strip the label from every requirement that currently uses it.",
                        "default": False,
                    },
                },
                "required": ["prefix", "key"],
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
                    "rid": {
                        "type": "string",
                        "description": "Requirement identifier that should be removed.",
                    },
                },
                "required": ["rid"],
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
                    "source_rid": {
                        "type": "string",
                        "description": "Identifier of the upstream requirement (for example, the parent).",
                    },
                    "derived_rid": {
                        "type": "string",
                        "description": "Identifier of the downstream requirement that depends on the source.",
                    },
                    "link_type": {
                        "type": "string",
                        "enum": ["parent"],
                        "description": "Relationship type to create; currently only parent-child links are supported.",
                    },
                },
                "required": [
                    "source_rid",
                    "derived_rid",
                    "link_type",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_user_documents",
            "description": "Enumerate user-provided documentation files as a tree",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_user_document",
            "description": "Read a slice of a documentation file with numbered lines",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the target file relative to the configured documentation root.",
                    },
                    "start_line": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "First line number to include (1-based).",
                    },
                    "max_bytes": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": USER_DOCUMENT_MAX_READ_BYTES,
                        "default": USER_DOCUMENT_DEFAULT_READ_BYTES,
                        "description": (
                            "Maximum number of bytes to read in the detected "
                            "file encoding "
                            f"(defaults to {USER_DOCUMENT_DEFAULT_READ_BYTES} "
                            f"and never exceeds {USER_DOCUMENT_MAX_READ_BYTES})."
                        ),
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_user_document",
            "description": "Create or overwrite a documentation file with optional content",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path of the file to create relative to the documentation root.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Text to persist in the file (encoded with the selected encoding, UTF-8 when omitted).",
                    },
                    "exist_ok": {
                        "type": "boolean",
                        "description": "Allow overwriting an existing file when true (defaults to false).",
                    },
                    "encoding": {
                        "type": "string",
                        "description": (
                            "Optional text encoding (Python codec name such as 'utf-8', 'cp1251'); defaults to UTF-8."
                        ),
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_user_document",
            "description": "Delete a documentation file from the user directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path of the file to remove relative to the documentation root.",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
]



