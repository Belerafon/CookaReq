"""MCP tool registry construction and schema metadata."""

from __future__ import annotations

import inspect
from copy import deepcopy
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ..services.user_documents import UserDocumentsService

ToolCallable = Callable[..., dict | None]
BasePathProvider = Callable[[], str]
DocumentsServiceProvider = Callable[[], UserDocumentsService | None]


def _schema_copy(schema: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if schema is None:
        return None
    return deepcopy(dict(schema))


TOOL_ARGUMENT_SCHEMAS: dict[str, dict[str, Any]] = {
    "list_requirements": {
        "type": "object",
        "properties": {
            "prefix": {"type": "string"},
            "page": {"type": "integer", "minimum": 1, "default": 1},
            "per_page": {"type": "integer", "minimum": 1, "default": 50},
            "status": {"type": ["string", "null"]},
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
            },
            "fields": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
            },
        },
        "required": ["prefix"],
        "additionalProperties": False,
    },
    "get_requirement": {
        "type": "object",
        "properties": {
            "rid": {
                "oneOf": [
                    {"type": "string"},
                    {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "uniqueItems": True,
                    },
                ]
            },
            "fields": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "uniqueItems": True,
            },
        },
        "required": ["rid"],
        "additionalProperties": False,
    },
    "search_requirements": {
        "type": "object",
        "properties": {
            "query": {"type": ["string", "null"]},
            "labels": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "uniqueItems": True,
            },
            "status": {"type": ["string", "null"]},
            "page": {"type": "integer", "minimum": 1, "default": 1},
            "per_page": {"type": "integer", "minimum": 1, "default": 50},
            "fields": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "uniqueItems": True,
            },
        },
        "additionalProperties": False,
    },
    "list_labels": {
        "type": "object",
        "properties": {
            "prefix": {"type": "string"},
        },
        "required": ["prefix"],
        "additionalProperties": False,
    },
    "create_requirement": {
        "type": "object",
        "properties": {
            "prefix": {"type": "string"},
            "data": {"type": "object"},
        },
        "required": ["prefix", "data"],
        "additionalProperties": False,
    },
    "update_requirement_field": {
        "type": "object",
        "properties": {
            "rid": {"type": "string"},
            "field": {"type": "string"},
            "value": {},
        },
        "required": ["rid", "field", "value"],
        "additionalProperties": False,
    },
    "set_requirement_labels": {
        "type": "object",
        "properties": {
            "rid": {"type": "string"},
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
            },
        },
        "required": ["rid", "labels"],
        "additionalProperties": False,
    },
    "set_requirement_attachments": {
        "type": "object",
        "properties": {
            "rid": {"type": "string"},
            "attachments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "path": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "required": ["id", "path"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["rid", "attachments"],
        "additionalProperties": False,
    },
    "set_requirement_links": {
        "type": "object",
        "properties": {
            "rid": {"type": "string"},
            "links": {
                "type": "array",
                "items": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "object"},
                    ]
                },
            },
        },
        "required": ["rid", "links"],
        "additionalProperties": False,
    },
    "delete_requirement": {
        "type": "object",
        "properties": {
            "rid": {"type": "string"},
        },
        "required": ["rid"],
        "additionalProperties": False,
    },
    "create_label": {
        "type": "object",
        "properties": {
            "prefix": {"type": "string"},
            "key": {"type": "string"},
            "title": {"type": ["string", "null"]},
            "color": {"type": ["string", "null"]},
        },
        "required": ["prefix", "key"],
        "additionalProperties": False,
    },
    "update_label": {
        "type": "object",
        "properties": {
            "prefix": {"type": "string"},
            "key": {"type": "string"},
            "new_key": {"type": ["string", "null"]},
            "title": {"type": ["string", "null"]},
            "color": {"type": ["string", "null"]},
            "propagate": {"type": "boolean", "default": False},
        },
        "required": ["prefix", "key"],
        "additionalProperties": False,
    },
    "delete_label": {
        "type": "object",
        "properties": {
            "prefix": {"type": "string"},
            "key": {"type": "string"},
            "remove_from_requirements": {"type": "boolean", "default": False},
        },
        "required": ["prefix", "key"],
        "additionalProperties": False,
    },
    "link_requirements": {
        "type": "object",
        "properties": {
            "source_rid": {"type": "string"},
            "derived_rid": {"type": "string"},
            "link_type": {"type": "string"},
        },
        "required": ["source_rid", "derived_rid", "link_type"],
        "additionalProperties": False,
    },
    "list_user_documents": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "read_user_document": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1, "default": 1},
            "max_bytes": {"type": ["integer", "null"], "minimum": 1},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    "create_user_document": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string", "default": ""},
            "exist_ok": {"type": "boolean", "default": False},
            "encoding": {"type": ["string", "null"]},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    "delete_user_document": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
}




def _tools_read_module():
    from . import tools_read

    return tools_read


def _tools_write_module():
    from . import tools_write

    return tools_write


def _tools_documents_module():
    from . import tools_documents

    return tools_documents


def build_tool_registry(
    *,
    base_path_provider: BasePathProvider,
    documents_service_provider: DocumentsServiceProvider,
) -> tuple[dict[str, ToolCallable], dict[str, dict[str, Any]]]:
    """Return MCP tool callables and metadata bound to runtime providers."""
    tools: dict[str, ToolCallable] = {}
    tool_metadata: dict[str, dict[str, Any]] = {}

    def register_tool(
        func: ToolCallable | None = None,
        *,
        name: str | None = None,
        schema: Mapping[str, Any] | None = None,
        result_schema: Mapping[str, Any] | None = None,
    ) -> ToolCallable | Callable[[ToolCallable], ToolCallable]:
        def decorator(target: ToolCallable) -> ToolCallable:
            tool_name = name or target.__name__
            if tool_name in tools:
                raise ValueError(f"duplicate MCP tool registered: {tool_name}")
            tools[tool_name] = target
            description = inspect.getdoc(target) or ""
            entry: dict[str, Any] = {"name": tool_name, "description": description}
            schema_payload = _schema_copy(schema)
            if schema_payload is not None:
                entry["arguments_schema"] = schema_payload
            result_payload = _schema_copy(result_schema)
            if result_payload is not None:
                entry["result_schema"] = result_payload
            tool_metadata[tool_name] = entry
            return target

        if func is not None:
            return decorator(func)
        return decorator

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["list_requirements"])
    def list_requirements(
        *,
        prefix: str,
        page: int = 1,
        per_page: int = 50,
        status: str | None = None,
        labels: list[str] | None = None,
        fields: list[str] | None = None,
    ) -> dict:
        return _tools_read_module().list_requirements(
            base_path_provider(),
            prefix=prefix,
            page=page,
            per_page=per_page,
            status=status,
            labels=labels,
            fields=fields,
        )

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["get_requirement"])
    def get_requirement(rid: str | Sequence[str], fields: list[str] | None = None) -> dict:
        return _tools_read_module().get_requirement(base_path_provider(), rid, fields=fields)

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["search_requirements"])
    def search_requirements(
        *,
        query: str | None = None,
        labels: list[str] | None = None,
        status: str | None = None,
        page: int = 1,
        per_page: int = 50,
        fields: list[str] | None = None,
    ) -> dict:
        return _tools_read_module().search_requirements(
            base_path_provider(),
            query=query,
            labels=labels,
            status=status,
            page=page,
            per_page=per_page,
            fields=fields,
        )

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["list_labels"])
    def list_labels(prefix: str) -> dict:
        return _tools_read_module().list_labels(base_path_provider(), prefix=prefix)

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["create_requirement"])
    def create_requirement(prefix: str, data: Mapping[str, object]) -> dict:
        return _tools_write_module().create_requirement(base_path_provider(), prefix=prefix, data=data)

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["update_requirement_field"])
    def update_requirement_field(rid: str, *, field: str, value: Any) -> dict:
        return _tools_write_module().update_requirement_field(
            base_path_provider(),
            rid,
            field=field,
            value=value,
        )

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["set_requirement_labels"])
    def set_requirement_labels(rid: str, labels: Sequence[str]) -> dict:
        return _tools_write_module().set_requirement_labels(base_path_provider(), rid, labels)

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["set_requirement_attachments"])
    def set_requirement_attachments(
        rid: str, attachments: Sequence[Mapping[str, Any]]
    ) -> dict:
        return _tools_write_module().set_requirement_attachments(base_path_provider(), rid, attachments)

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["set_requirement_links"])
    def set_requirement_links(rid: str, links: Sequence[Mapping[str, Any] | str]) -> dict:
        return _tools_write_module().set_requirement_links(base_path_provider(), rid, links)

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["delete_requirement"])
    def delete_requirement(rid: str) -> dict | None:
        return _tools_write_module().delete_requirement(base_path_provider(), rid)

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["create_label"])
    def create_label(
        prefix: str,
        *,
        key: str,
        title: str | None = None,
        color: str | None = None,
    ) -> dict:
        return _tools_write_module().create_label(
            base_path_provider(),
            prefix=prefix,
            key=key,
            title=title,
            color=color,
        )

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["update_label"])
    def update_label(
        prefix: str,
        *,
        key: str,
        new_key: str | None = None,
        title: str | None = None,
        color: str | None = None,
        propagate: bool = False,
    ) -> dict:
        return _tools_write_module().update_label(
            base_path_provider(),
            prefix=prefix,
            key=key,
            new_key=new_key,
            title=title,
            color=color,
            propagate=propagate,
        )

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["delete_label"])
    def delete_label(
        prefix: str,
        *,
        key: str,
        remove_from_requirements: bool = False,
    ) -> dict:
        return _tools_write_module().delete_label(
            base_path_provider(),
            prefix=prefix,
            key=key,
            remove_from_requirements=remove_from_requirements,
        )

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["link_requirements"])
    def link_requirements(
        *,
        source_rid: str,
        derived_rid: str,
        link_type: str,
    ) -> dict:
        return _tools_write_module().link_requirements(
            base_path_provider(),
            source_rid=source_rid,
            derived_rid=derived_rid,
            link_type=link_type,
        )

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["list_user_documents"])
    def list_user_documents() -> dict:
        return _tools_documents_module().list_user_documents(documents_service_provider())

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["read_user_document"])
    def read_user_document(
        path: str,
        *,
        start_line: int = 1,
        max_bytes: int | None = None,
    ) -> dict:
        return _tools_documents_module().read_user_document(
            documents_service_provider(),
            path,
            start_line=start_line,
            max_bytes=max_bytes,
        )

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["create_user_document"])
    def create_user_document(
        path: str,
        *,
        content: str = "",
        exist_ok: bool = False,
        encoding: str | None = None,
    ) -> dict:
        return _tools_documents_module().create_user_document(
            documents_service_provider(),
            path,
            content=content,
            exist_ok=exist_ok,
            encoding=encoding,
        )

    @register_tool(schema=TOOL_ARGUMENT_SCHEMAS["delete_user_document"])
    def delete_user_document(path: str) -> dict:
        return _tools_documents_module().delete_user_document(documents_service_provider(), path)

    return tools, tool_metadata
