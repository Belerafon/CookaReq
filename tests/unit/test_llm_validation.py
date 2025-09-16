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
        }
    )

    result = validate_tool_call("list_requirements", arguments)

    assert result == {
        "page": 2,
        "per_page": 25,
        "status": "approved",
        "labels": ["ui", "ux"],
    }
    assert isinstance(result, dict)


def test_validate_tool_call_accepts_search_filters_with_nulls():
    arguments = {
        "query": None,
        "labels": None,
        "status": None,
        "page": 3,
        "per_page": 10,
    }

    result = validate_tool_call("search_requirements", arguments)

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
