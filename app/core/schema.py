"""JSON Schema for requirement files."""

from __future__ import annotations

from typing import Any

from jsonschema import validate as _validate
from jsonschema.exceptions import ValidationError

from .model import Priority, RequirementType, Status, Verification

SCHEMA: dict[str, Any] = {
    "type": "object",
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
        "revision",
    ],
    "properties": {
        "id": {"type": "integer"},
        "title": {"type": "string"},
        "statement": {"type": "string"},
        "type": {"enum": [e.value for e in RequirementType]},
        "status": {"enum": [e.value for e in Status]},
        "owner": {"type": "string"},
        "priority": {"enum": [e.value for e in Priority]},
        "source": {"type": "string"},
        "verification": {"enum": [e.value for e in Verification]},
        "acceptance": {"type": "string"},
        "conditions": {"type": "string"},
        "trace_up": {"type": "string"},
        "trace_down": {"type": "string"},
        "version": {"type": "string"},
        "modified_at": {"type": "string"},
        "labels": {"type": "array", "items": {"type": "string"}},
        "attachments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "note": {"type": "string"},
                },
            },
        },
        "derived_from": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source_id", "source_revision"],
                "properties": {
                    "source_id": {"type": "integer"},
                    "source_revision": {"type": "integer"},
                    "suspect": {"type": "boolean"},
                },
            },
        },
        "parent": {
            "type": "object",
            "required": ["source_id", "source_revision"],
            "properties": {
                "source_id": {"type": "integer"},
                "source_revision": {"type": "integer"},
                "suspect": {"type": "boolean"},
            },
        },
        "links": {
            "type": "object",
            "properties": {
                "verifies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["source_id", "source_revision"],
                        "properties": {
                            "source_id": {"type": "integer"},
                            "source_revision": {"type": "integer"},
                            "suspect": {"type": "boolean"},
                        },
                    },
                },
                "relates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["source_id", "source_revision"],
                        "properties": {
                            "source_id": {"type": "integer"},
                            "source_revision": {"type": "integer"},
                            "suspect": {"type": "boolean"},
                        },
                    },
                },
            },
            "additionalProperties": False,
        },
        "derivation": {
            "type": "object",
            "required": ["rationale", "assumptions"],
            "properties": {
                "rationale": {"type": "string"},
                "assumptions": {"type": "array", "items": {"type": "string"}},
            },
        },
        "revision": {"type": "integer", "minimum": 1},
        "approved_at": {"type": ["string", "null"]},
        "notes": {"type": "string"},
    },
}


def validate(data: dict[str, Any]) -> None:
    """Validate *data* against :data:`SCHEMA`.

    Raises :class:`ValueError` if validation fails.
    """
    try:
        _validate(data, SCHEMA)
    except ValidationError as exc:  # pragma: no cover - branch hit when raising
        raise ValueError(str(exc)) from exc
