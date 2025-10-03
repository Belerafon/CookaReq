"""Tests for recovering malformed tool argument payloads."""

from app.llm.response_parser import LLMResponseParser, normalise_tool_calls
from app.settings import LLMSettings


def _parser() -> LLMResponseParser:
    settings = LLMSettings()
    return LLMResponseParser(settings, settings.message_format)


class _StringableArguments:
    def __init__(self, text: str) -> None:
        self._text = text

    def __str__(self) -> str:
        return self._text


def test_parse_tool_calls_merges_concatenated_json_fragments() -> None:
    parser = _parser()
    arguments_text = (
        '{"rid":"DEMO6"}'
        '{"field":"title","value":"Перевод"}'
    )
    tool_calls = [
        {
            "id": "call-0",
            "type": "function",
            "function": {
                "name": "update_requirement_field",
                "arguments": arguments_text,
            },
        }
    ]

    parsed = parser.parse_tool_calls(tool_calls)

    assert len(parsed) == 1
    call = parsed[0]
    assert call.name == "update_requirement_field"
    assert call.arguments["rid"] == "DEMO6"
    assert call.arguments["field"] == "title"
    assert call.arguments["value"] == "Перевод"


def test_parse_tool_calls_allows_missing_required_fields() -> None:
    parser = _parser()
    tool_calls = [
        {
            "id": "call-0",
            "type": "function",
            "function": {
                "name": "update_requirement_field",
                "arguments": '{"field":"title","value":"Перевод"}',
            },
        }
    ]

    parsed = parser.parse_tool_calls(tool_calls)

    assert len(parsed) == 1
    call = parsed[0]
    assert call.name == "update_requirement_field"
    assert call.arguments == {"field": "title", "value": "Перевод"}


def test_normalise_tool_calls_preserves_stringable_arguments() -> None:
    parser = _parser()
    arguments = _StringableArguments(
        '{"rid":"DEMO7","field":"title","value":"Локализация"}'
    )
    tool_calls = [
        {
            "id": "call-0",
            "type": "function",
            "function": {
                "name": "update_requirement_field",
                "arguments": arguments,
            },
        }
    ]

    normalised = normalise_tool_calls(tool_calls)
    parsed = parser.parse_tool_calls(normalised)

    assert parsed[0].arguments["rid"] == "DEMO7"
    assert parsed[0].arguments["field"] == "title"
    assert parsed[0].arguments["value"] == "Локализация"
