import json
from datetime import UTC, datetime

from app.llm.spec import SYSTEM_PROMPT
from app.ui.agent_chat_panel.log_export import (
    SYSTEM_PROMPT_PLACEHOLDER,
    compose_transcript_log_text,
    compose_transcript_text,
)
from app.ui.chat_entry import ChatConversation, ChatEntry


_SYSTEM_PROMPT_TEXT = str(SYSTEM_PROMPT).strip()


def _iso(ts: str) -> str:
    """Return ISO8601 timestamp for tests."""

    return datetime.fromisoformat(ts).astimezone(UTC).isoformat()


def _build_tool_payloads() -> list[dict[str, object]]:
    error_payload = {
        "type": "VALIDATION_ERROR",
        "message": "update_requirement_field() missing 1 required positional argument: 'rid'",
    }
    base_started = "2025-10-02T11:19:15+00:00"
    successes = [
        {
            "tool": "get_requirement",
            "ok": True,
            "agent_status": "completed",
            "started_at": base_started,
            "completed_at": "2025-10-02T11:19:16+00:00",
            "result": {
                "items": [
                    {"rid": "DEMO17"},
                    {"rid": "DEMO18"},
                ]
            },
        }
    ]
    failures: list[dict[str, object]] = []
    for index, stamp in enumerate(
        [
            "2025-10-02T11:27:02+00:00",
            "2025-10-02T11:28:10+00:00",
            "2025-10-02T11:31:28+00:00",
            "2025-10-02T11:35:56+00:00",
            "2025-10-02T11:38:04+00:00",
        ],
        start=1,
    ):
        failures.append(
            {
                "tool": "update_requirement_field",
                "ok": False,
                "agent_status": "failed",
                "started_at": stamp,
                "completed_at": stamp,
                "error": error_payload,
                "tool_arguments": {
                    "field": "title" if index % 2 else "statement",
                    "value": "Тестовое значение",
                },
            }
        )
    return successes + failures


def _conversation_with_failed_updates() -> ChatConversation:
    conversation = ChatConversation.new()
    prompt_text = "Переведи выделенные требования на русский (включая названия) и сохрани"
    response_text = (
        "VALIDATION_ERROR: update_requirement_field() missing 1 required positional argument: 'rid'"
    )
    entry = ChatEntry(
        prompt=prompt_text,
        response=response_text,
        display_response="Waiting for agent response…",
        tokens=0,
        prompt_at=_iso("2025-10-02T11:19:15+00:00"),
        response_at=_iso("2025-10-02T11:38:04+00:00"),
        raw_result={"tool_results": _build_tool_payloads()},
        diagnostic={
            "llm_request_messages": (
                {"role": "system", "content": _SYSTEM_PROMPT_TEXT},
                {"role": "user", "content": prompt_text},
            ),
            "llm_request_messages_sequence": (
                {
                    "step": 1,
                    "messages": (
                        {"role": "system", "content": _SYSTEM_PROMPT_TEXT},
                        {"role": "user", "content": prompt_text},
                    ),
                },
                {
                    "step": 2,
                    "messages": (
                        {"role": "system", "content": _SYSTEM_PROMPT_TEXT},
                        {"role": "assistant", "content": "Calling update_requirement_field"},
                    ),
                },
            ),
        },
    )
    conversation.append_entry(entry)
    return conversation


def _conversation_with_streamed_responses() -> ChatConversation:
    conversation = ChatConversation.new()
    prompt_text = "Привет"
    entry = ChatEntry(
        prompt=prompt_text,
        response="",
        display_response="Waiting for agent response…",
        tokens=0,
        prompt_at=_iso("2025-10-02T11:00:00+00:00"),
        response_at=_iso("2025-10-02T11:00:05+00:00"),
        diagnostic={
            "llm_steps": [
                {
                    "step": 1,
                    "response": {
                        "content": "Обрабатываю запрос",
                        "timestamp": "2025-10-02T11:00:03+00:00",
                    },
                },
                {
                    "step": 2,
                    "response": {
                        "content": "Готово: итоговое сообщение",
                        "timestamp": "2025-10-02T11:00:05+00:00",
                    },
                },
            ]
        },
    )
    conversation.append_entry(entry)
    return conversation


def test_plain_transcript_uses_agent_turn_text_and_tool_summaries():
    conversation = _conversation_with_failed_updates()

    plain_text = compose_transcript_text(conversation)

    assert "VALIDATION_ERROR" in plain_text
    assert "Waiting for agent response" not in plain_text
    assert "[02 Oct 2025 11:19:15] You:" in plain_text
    assert "[02 Oct 2025 11:38:04] Agent:" in plain_text
    assert (
        "[02 Oct 2025 11:19:15] Agent: tool call 1: get_requirement"
        in plain_text
    )
    assert (
        "[02 Oct 2025 11:27:02] Agent: tool call 2: update_requirement_field"
        in plain_text
    )
    assert (
        "• Error: update_requirement_field() missing 1 required positional argument: 'rid'"
        in plain_text
    )


def test_plain_transcript_includes_streamed_responses():
    conversation = _conversation_with_streamed_responses()

    plain_text = compose_transcript_text(conversation)

    assert "[02 Oct 2025 11:00:03] Agent (step 1):" in plain_text
    assert "Обрабатываю запрос" in plain_text
    assert "[02 Oct 2025 11:00:05] Agent (step 2):" in plain_text
    assert "Готово: итоговое сообщение" in plain_text
    assert "Waiting for agent response" not in plain_text


def test_transcript_log_replaces_repeated_system_prompt():
    conversation = _conversation_with_failed_updates()

    log_text = compose_transcript_log_text(conversation)
    encoded_prompt = json.dumps(_SYSTEM_PROMPT_TEXT, ensure_ascii=False)

    assert log_text.count(encoded_prompt) == 1
    assert log_text.count(SYSTEM_PROMPT_PLACEHOLDER) >= 1


def test_transcript_log_replaces_prefixed_system_prompt_but_keeps_context():
    conversation = ChatConversation.new()
    prompt_text = "Переведи требования"
    combined_prompt = _SYSTEM_PROMPT_TEXT + "\n\nContext:\n- File: README.md"
    entry = ChatEntry(
        prompt=prompt_text,
        response="Готово",
        tokens=0,
        prompt_at=_iso("2025-10-02T12:00:00+00:00"),
        response_at=_iso("2025-10-02T12:00:05+00:00"),
        raw_result={
            "llm_requests": [
                {
                    "messages": [
                        {"role": "system", "content": combined_prompt},
                        {"role": "user", "content": prompt_text},
                    ]
                },
                {
                    "messages": [
                        {"role": "system", "content": combined_prompt},
                        {"role": "assistant", "content": "Работаю"},
                    ]
                },
            ]
        },
    )
    conversation.append_entry(entry)

    log_text = compose_transcript_log_text(conversation)
    encoded_prompt = json.dumps(combined_prompt, ensure_ascii=False)
    encoded_placeholder_with_context = json.dumps(
        SYSTEM_PROMPT_PLACEHOLDER + "\n\nContext:\n- File: README.md",
        ensure_ascii=False,
    )

    assert log_text.count(encoded_prompt) == 1
    assert encoded_placeholder_with_context in log_text
    assert log_text.count(SYSTEM_PROMPT_PLACEHOLDER) >= 1


def test_transcript_log_sanitises_raw_payload_prompts():
    conversation = ChatConversation.new()
    entry = ChatEntry(
        prompt="Запрос",
        response="Ответ",
        tokens=0,
        prompt_at=_iso("2025-10-02T09:00:00+00:00"),
        response_at=_iso("2025-10-02T09:00:01+00:00"),
        raw_result={
            "llm_requests": [
                {"messages": [{"role": "system", "content": _SYSTEM_PROMPT_TEXT}]}
            ],
            "diagnostic": {
                "llm_steps": [
                    {
                        "step": 1,
                        "response": {
                            "content": "",
                            "messages": [
                                {
                                    "role": "system",
                                    "content": _SYSTEM_PROMPT_TEXT,
                                }
                            ],
                        },
                    }
                ]
            },
        },
    )
    conversation.append_entry(entry)

    log_text = compose_transcript_log_text(conversation)
    encoded_prompt = json.dumps(_SYSTEM_PROMPT_TEXT, ensure_ascii=False)

    assert log_text.count(encoded_prompt) == 1
    assert log_text.count(SYSTEM_PROMPT_PLACEHOLDER) >= 2


