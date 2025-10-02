from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.llm.client import LLMClient
from app.llm.types import LLMReasoningSegment
from app.settings import LLMSettings


class _DummyCompletions:
    def create(self, **kwargs):  # noqa: D401 - minimal stub
        return object()


class _DummyOpenAI:
    def __init__(self, *args, **kwargs):  # noqa: D401 - minimal stub
        self.chat = SimpleNamespace(completions=_DummyCompletions())


@pytest.fixture(autouse=True)
def _stub_openai(monkeypatch):
    monkeypatch.setattr("openai.OpenAI", _DummyOpenAI)


def _make_client(monkeypatch: pytest.MonkeyPatch) -> LLMClient:
    settings = LLMSettings(api_key="dummy")
    client = LLMClient(settings)
    monkeypatch.setattr(LLMClient, "_chat_completion", lambda self, **kwargs: object())

    def fake_build_chat_request(conversation, **kwargs):
        return SimpleNamespace(request_args={"stream": False}, snapshot=tuple(conversation))

    monkeypatch.setattr(client._request_builder, "build_chat_request", fake_build_chat_request)
    monkeypatch.setattr(client._response_parser, "parse_tool_calls", lambda payload: ())
    return client


def test_log_payload_uses_rendered_reasoning_text(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr("app.llm.client.log_request", lambda payload: None)
    monkeypatch.setattr("app.llm.client.log_response", lambda payload, **_: events.append(payload))
    client = _make_client(monkeypatch)

    expected_segments = (
        LLMReasoningSegment(type="reasoning", text="First", trailing_whitespace=" "),
        LLMReasoningSegment(type="analysis", text="Second", leading_whitespace=" "),
    )

    def fake_parse_chat_completion(_completion):
        return ("Done", [], [{"type": "reasoning", "text": "ignored"}])

    monkeypatch.setattr(
        client._response_parser,
        "parse_chat_completion",
        fake_parse_chat_completion,
    )
    monkeypatch.setattr(
        client._response_parser,
        "finalize_reasoning_segments",
        lambda entries: expected_segments,
    )

    response = client.respond([{"role": "user", "content": "hi"}])
    assert response.reasoning == expected_segments
    assert events, "log_response was not invoked"
    reasoning_payload = events[-1].get("reasoning")
    assert reasoning_payload == [
        {"type": "reasoning", "preview": "First "},
        {"type": "analysis", "preview": " Second"},
    ]


def test_tool_validation_error_exposes_full_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.llm.client.log_request", lambda payload: None)
    monkeypatch.setattr("app.llm.client.log_response", lambda payload, **kwargs: None)
    client = _make_client(monkeypatch)

    expected_segments = (
        LLMReasoningSegment(type="reasoning", text="First", trailing_whitespace=" "),
        LLMReasoningSegment(type="analysis", text="Second", leading_whitespace=" "),
    )

    def fake_parse_chat_completion(_completion):
        return ("", [], [{"type": "reasoning", "text": "ignored"}])

    monkeypatch.setattr(
        client._response_parser,
        "parse_chat_completion",
        fake_parse_chat_completion,
    )
    monkeypatch.setattr(
        client._response_parser,
        "finalize_reasoning_segments",
        lambda entries: expected_segments,
    )

    with pytest.raises(Exception) as caught:
        client.respond([{"role": "user", "content": "hi"}])

    exc = caught.value
    assert getattr(exc, "llm_reasoning", None) == [
        {"type": "reasoning", "text": "First "},
        {"type": "analysis", "text": " Second"},
    ]
