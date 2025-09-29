from __future__ import annotations

from types import MappingProxyType

import pytest

from app.llm.validation import ToolValidationError, validate_tool_call


def test_validate_tool_call_accepts_list_filters():
    arguments = MappingProxyType(
        {
            "page": 2,
            "per_page": 25,
            "status": "approved",
            "labels": ["ui", "ux"],
            "fields": ["title", "status"],
        }
    )

    result = validate_tool_call("list_requirements", arguments)

    assert result == {
        "page": 2,
        "per_page": 25,
        "status": "approved",
        "labels": ["ui", "ux"],
        "fields": ["title", "status"],
    }
    assert isinstance(result, dict)


def test_validate_tool_call_accepts_search_filters_with_nulls():
    arguments = {
        "query": None,
        "labels": None,
        "status": None,
        "page": 3,
        "per_page": 10,
        "fields": None,
    }

    result = validate_tool_call("search_requirements", arguments)

    assert result == arguments


def test_validate_tool_call_accepts_string_fields():
    arguments = {"rid": "SYS1", "fields": "title"}

    result = validate_tool_call("get_requirement", arguments)

    assert result == arguments


def test_validate_tool_call_accepts_rid_list():
    arguments = {"rid": ["SYS1", "SYS2"], "fields": ["title"]}

    result = validate_tool_call("get_requirement", arguments)

    assert result == arguments


@pytest.mark.parametrize(
    "arguments,expected_message",
    [
        (
            {"status": "invalid"},
            "Invalid arguments for list_requirements",
        ),
        (
            {"page": 0},
            "Invalid arguments for list_requirements",
        ),
        (
            {"unknown": 1},
            "Invalid arguments for list_requirements",
        ),
    ],
)
def test_validate_tool_call_rejects_invalid_list_filters(arguments, expected_message):
    with pytest.raises(ToolValidationError) as exc:
        validate_tool_call("list_requirements", arguments)

    assert expected_message in str(exc.value)


def test_validate_tool_call_rejects_invalid_search_status():
    with pytest.raises(ToolValidationError) as exc:
        validate_tool_call("search_requirements", {"status": "unknown"})

    assert "Invalid arguments for search_requirements" in str(exc.value)


def test_validate_tool_call_accepts_status_update():
    arguments = {"rid": "SYS1", "field": "status", "value": "approved"}

    result = validate_tool_call("update_requirement_field", arguments)

    assert result == arguments


def test_validate_tool_call_rejects_unknown_status_update():
    with pytest.raises(ToolValidationError) as exc:
        validate_tool_call(
            "update_requirement_field",
            {"rid": "SYS1", "field": "status", "value": "pending approval"},
        )

    message = str(exc.value)
    assert "Invalid arguments for update_requirement_field" in message
    assert "value" in message


def test_update_requirement_field_rejects_wrapped_value():
    with pytest.raises(ToolValidationError) as exc:
        validate_tool_call(
            "update_requirement_field",
            {
                "rid": "SYS1",
                "field": "title",
                "value": {"type": "string", "value": "Demo Layer Map"},
            },
        )

    message = str(exc.value)
    assert "Invalid arguments for update_requirement_field" in message
    assert "value" in message


def test_update_requirement_field_rejects_null_value():
    with pytest.raises(ToolValidationError) as exc:
        validate_tool_call(
            "update_requirement_field",
            {"rid": "SYS1", "field": "notes", "value": None},
        )

    message = str(exc.value)
    assert "Invalid arguments for update_requirement_field" in message
    assert "value" in message
