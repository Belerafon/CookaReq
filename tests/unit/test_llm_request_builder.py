from __future__ import annotations

import pytest

from app.llm.request_builder import LLMRequestBuilder
from app.llm.spec import SYSTEM_PROMPT
from app.settings import LLMSettings


@pytest.fixture()
def request_builder() -> LLMRequestBuilder:
    settings = LLMSettings()
    return LLMRequestBuilder(settings, message_format="openai-chat")


def test_system_messages_are_collapsed(request_builder: LLMRequestBuilder) -> None:
    conversation = [
        {"role": "system", "content": "[User selection]\n- SYS1"},
        {"role": "user", "content": "Hello"},
        {"role": "system", "content": "[Workspace context]\n- File: README.md"},
        {"role": "assistant", "content": "Hi!"},
    ]

    prepared = request_builder.build_chat_request(conversation).messages

    assert prepared
    first_message = prepared[0]
    assert first_message["role"] == "system"
    system_content = first_message["content"]
    assert system_content.startswith(SYSTEM_PROMPT)
    assert system_content.count("[User selection]") == 1
    assert system_content.count("[Workspace context]") == 1
    assert system_content.index("[User selection]") < system_content.index("[Workspace context]")
    assert sum(1 for message in prepared if message["role"] == "system") == 1
