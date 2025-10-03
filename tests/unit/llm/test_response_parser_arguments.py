"""Tests for recovering malformed tool argument payloads."""

import json
from typing import Any
from collections.abc import Mapping

from openai.types.responses.response_function_tool_call import (
    ResponseFunctionToolCall,
)

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


class _ShadowMappingArguments(Mapping[str, str]):
    """Mapping that pretends to be empty but stringifies to JSON."""

    def __init__(self, text: str) -> None:
        self._text = text

    def __iter__(self):  # pragma: no cover - iterator required by Mapping
        return iter(())

    def __len__(self) -> int:  # pragma: no cover - simple constant
        return 0

    def __getitem__(self, key: str) -> str:
        raise KeyError(key)

    def __str__(self) -> str:
        return self._text


class _OpenAIObjectArguments:
    """Mimic OpenAI SDK tool arguments with a descriptive ``repr``."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = dict(payload)

    def model_dump(self) -> Mapping[str, Any]:
        return dict(self._payload)

    def __str__(self) -> str:  # pragma: no cover - representational helper
        return f"OpenAIObject(json={json.dumps(self._payload, ensure_ascii=False)})"


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


def test_normalise_tool_calls_falls_back_to_string_repr_for_shadow_mappings() -> None:
    parser = _parser()
    arguments = _ShadowMappingArguments(
        '{"rid":"DEMO8","field":"statement","value":"Перевести"}'
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

    assert parsed[0].arguments["rid"] == "DEMO8"
    assert parsed[0].arguments["field"] == "statement"
    assert parsed[0].arguments["value"] == "Перевести"


def test_normalise_tool_calls_uses_model_dump_for_openai_objects() -> None:
    parser = _parser()
    arguments = _OpenAIObjectArguments(
        {
            "rid": "DEMO9",
            "field": "title",
            "value": "Русификация",
        }
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

    assert parsed[0].arguments["rid"] == "DEMO9"
    assert parsed[0].arguments["field"] == "title"
    assert parsed[0].arguments["value"] == "Русификация"


def test_normalise_tool_calls_handles_response_function_tool_call() -> None:
    parser = _parser()
    tool_call = ResponseFunctionToolCall(
        id="resp-tool-1",
        call_id="resp-tool-1",
        name="update_requirement_field",
        arguments=(
            '{"rid":"DEMO10","field":"status","value":"approved"}'
        ),
        type="function_call",
    )

    normalised = normalise_tool_calls([tool_call])
    parsed = parser.parse_tool_calls(normalised)

    assert len(parsed) == 1
    arguments = parsed[0].arguments
    assert arguments["rid"] == "DEMO10"
    assert arguments["field"] == "status"
    assert arguments["value"] == "approved"


def test_consume_stream_collects_response_function_tool_call() -> None:
    parser = _parser()
    tool_call = ResponseFunctionToolCall(
        id="resp-tool-2",
        call_id="resp-tool-2",
        name="update_requirement_field",
        arguments=(
            '{"rid":"DEMO12","field":"statement","value":"Обновить"}'
        ),
        type="function_call",
    )
    stream = [
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [tool_call],
                        "content": [
                            {"type": "output_text", "text": "Processing"}
                        ],
                    },
                }
            ]
        }
    ]

    message, tool_calls, _reasoning = parser.consume_stream(stream, cancellation=None)

    assert message.strip() == "Processing"
    assert tool_calls, "Stream parser should recover tool calls from response chunks"
    function = tool_calls[0]["function"]
    assert function["name"] == "update_requirement_field"
    assert json.loads(function["arguments"])["rid"] == "DEMO12"
