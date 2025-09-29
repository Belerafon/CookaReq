from __future__ import annotations

import pytest

from app.llm import logging as llm_logging
from app.llm.harmony import convert_tools_for_harmony, render_harmony_prompt
from app.llm.spec import SYSTEM_PROMPT, TOOLS


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_prompt_log_state() -> None:
    llm_logging._reset_prompt_log_state()
    yield
    llm_logging._reset_prompt_log_state()


def _capture_logging(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    captured: list[dict[str, object]] = []

    def fake_debug(event: str, payload: dict[str, object] | None = None, **_: object) -> None:
        if payload is not None:
            captured.append(payload)

    def fake_event(event: str, payload: dict[str, object] | None = None, **_: object) -> None:
        if payload is not None:
            captured.append(payload)

    monkeypatch.setattr(llm_logging, "log_debug_payload", fake_debug)
    monkeypatch.setattr(llm_logging, "log_event", fake_event)
    return captured


def test_chat_request_collapses_prompt_after_first_occurrence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_logging(monkeypatch)
    payload = {
        "model": "meta-llama", 
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
                + "\n\n[Workspace context]\nSelected requirement RIDs: SYS1",
            },
            {"role": "user", "content": "Ping"},
        ],
        "tools": TOOLS[:2],
    }

    llm_logging.log_request(payload)
    llm_logging.log_request(payload)

    assert captured, "expected payloads recorded by logging"
    first_payload = captured[0]
    second_payload = captured[-1]

    system_first = first_payload["messages"][0]["content"]  # type: ignore[index]
    system_second = second_payload["messages"][0]["content"]  # type: ignore[index]

    assert isinstance(system_first, str) and system_first.startswith(SYSTEM_PROMPT)
    assert isinstance(system_second, str)
    assert system_second.startswith(llm_logging._PROMPT_PLACEHOLDER_TEXT)
    assert "Selected requirement RIDs" in system_second

    assert isinstance(first_payload["tools"], list)
    assert second_payload["tools"] == llm_logging._PROMPT_PLACEHOLDER_TEXT

    # Original payload must remain intact for the actual API call
    assert payload["messages"][0]["content"].startswith(SYSTEM_PROMPT)


def test_harmony_request_collapses_prompt_after_first_occurrence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_logging(monkeypatch)
    harmony_prompt = render_harmony_prompt(
        instruction_blocks=[
            SYSTEM_PROMPT,
            "[Workspace context]\nSelected requirement RIDs: SYS5",
        ],
        history=[],
        tools=TOOLS[:1],
        reasoning_level="high",
        current_date="2024-07-20",
        knowledge_cutoff="2024-06",
    )
    payload = {
        "model": "meta-llama",
        "input": harmony_prompt.prompt,
        "tools": convert_tools_for_harmony(TOOLS[:1]),
        "reasoning": {"effort": "high"},
    }

    llm_logging.log_request(payload)
    llm_logging.log_request(payload)

    assert captured, "expected payloads recorded by logging"
    first_payload = captured[0]
    second_payload = captured[-1]

    assert SYSTEM_PROMPT in first_payload["input"]  # type: ignore[index]
    assert llm_logging._PROMPT_PLACEHOLDER_TEXT in second_payload["input"]  # type: ignore[index]
    assert "Selected requirement RIDs: SYS5" in second_payload["input"]  # type: ignore[index]

    assert isinstance(first_payload["tools"], list)
    assert second_payload["tools"] == llm_logging._PROMPT_PLACEHOLDER_TEXT
