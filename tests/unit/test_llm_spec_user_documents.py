from __future__ import annotations

import pytest

from app.llm.spec import SYSTEM_PROMPT, TOOLS
from app.services.user_documents import (
    DEFAULT_MAX_READ_BYTES,
    MAX_ALLOWED_READ_BYTES,
)


pytestmark = pytest.mark.unit


def _tool_entry(name: str) -> dict[str, object]:
    for tool in TOOLS:
        function = tool.get("function", {})
        if isinstance(function, dict) and function.get("name") == name:
            return function
    raise AssertionError(f"tool {name} not found in spec")


def test_tools_include_user_document_operations() -> None:
    for name in (
        "list_user_documents",
        "read_user_document",
        "create_user_document",
        "delete_user_document",
    ):
        entry = _tool_entry(name)
        assert entry["parameters"]["type"] == "object"  # type: ignore[index]


def test_read_user_document_schema_enforces_limits() -> None:
    entry = _tool_entry("read_user_document")
    params = entry["parameters"]  # type: ignore[index]
    properties = params["properties"]  # type: ignore[index]
    max_bytes = properties["max_bytes"]  # type: ignore[index]
    assert max_bytes["minimum"] == 1
    assert max_bytes["maximum"] == MAX_ALLOWED_READ_BYTES
    assert max_bytes["default"] == DEFAULT_MAX_READ_BYTES
    start_line = properties["start_line"]  # type: ignore[index]
    assert start_line["minimum"] == 1


def test_create_user_document_schema_includes_encoding() -> None:
    entry = _tool_entry("create_user_document")
    params = entry["parameters"]  # type: ignore[index]
    properties = params["properties"]  # type: ignore[index]
    assert "encoding" in properties
    encoding = properties["encoding"]  # type: ignore[index]
    assert "Python codec" in encoding["description"]


def test_system_prompt_mentions_user_document_guidance() -> None:
    prompt = SYSTEM_PROMPT
    assert "list_user_documents" in prompt
    assert "read_user_document" in prompt
    assert "default 10 KiB" in prompt
    assert "never exceeding 512 KiB" in prompt
    assert "encoding" in prompt
    assert "clamped_to_limit" in prompt
    assert "continuation_hint" in prompt
