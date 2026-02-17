from __future__ import annotations

import json
import os
from pathlib import Path
from collections.abc import Sequence

import pytest

from app.llm.client import LLMClient
from app.llm.reasoning import normalise_reasoning_segments
from app.ui.agent_chat_panel.log_export import (
    compose_transcript_log_text,
    compose_transcript_text,
)
from app.ui.agent_chat_panel.view_model import build_conversation_timeline
from app.ui.chat_entry import ChatConversation, ChatEntry
from app.util.time import utc_now_iso
from tests.env_utils import load_secret_from_env
from tests.llm_utils import require_real_llm_tests_flag, settings_with_llm

REQUIRES_REAL_LLM = True

pytestmark = [pytest.mark.integration, pytest.mark.real_llm]

JSON_LOG_NAME = "cookareq.jsonl"
DEFAULT_REASONING_MODEL = "openai/gpt-oss-120b"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_openrouter_key() -> str | None:
    secret = load_secret_from_env("OPEN_ROUTER", search_from=Path(__file__).resolve())
    return secret.get_secret_value() if secret else None


def _select_reasoning_model() -> str:
    model = os.getenv("OPENROUTER_REASONING_MODEL")
    if model and model.strip():
        return model.strip()
    return DEFAULT_REASONING_MODEL


def _read_json_lines(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _new_log_entries(path: Path, previous_count: int) -> list[dict[str, object]]:
    entries = _read_json_lines(path)
    if previous_count >= len(entries):
        return []
    return entries[previous_count:]


def _load_requirement_summaries(ids: Sequence[int]) -> list[tuple[str, str, str]]:
    items_dir = _REPO_ROOT / "requirements" / "SYS" / "items"
    results: list[tuple[str, str, str]] = []
    for rid in ids:
        path = items_dir / f"{rid}.json"
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
        label = f"SYS{rid}"
        title = str(payload.get("title") or "")
        statement = str(payload.get("statement") or "")
        results.append((label, title, statement))
    return results


def _compose_context(requirements: Sequence[tuple[str, str, str]]) -> str:
    rid_list = ", ".join(label for label, _, _ in requirements)
    lines = [
        "[Workspace context]",
        "Active document: SYS — System Requirements",
        f"Selected requirement RIDs: {rid_list}",
    ]
    for label, title, statement in requirements:
        lines.append(f"{label} — {title} — {statement}")
    return "\n".join(lines)


@pytest.mark.parametrize("target_language", ["испанский"])
def test_openrouter_transcript_logs(tmp_path: Path, real_llm_log_dir: Path, target_language: str) -> None:
    require_real_llm_tests_flag()
    key = _load_openrouter_key()
    if not key:
        pytest.skip("OPEN_ROUTER key not available")

    settings = settings_with_llm(tmp_path, api_key=key, stream=False)
    settings.llm.model = _select_reasoning_model()
    client = LLMClient(settings.llm)

    json_log_path = real_llm_log_dir / JSON_LOG_NAME
    before_count = len(_read_json_lines(json_log_path))

    requirement_payloads = _load_requirement_summaries((1, 2))
    system_message = _compose_context(requirement_payloads)
    rid_labels = ", ".join(label for label, _, _ in requirement_payloads)
    user_prompt = (
        f"Переведи требования {rid_labels} на {target_language} язык. "
        "Для каждого требования дай новый заголовок и формулировку, "
        "чтобы было понятно, что текст уже переведён."
    )
    conversation = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_prompt},
    ]

    response = client.respond(conversation)
    assert response.content is not None and response.content.strip()

    normalized_reasoning = normalise_reasoning_segments(response.reasoning)
    assert normalized_reasoning, "model did not return reasoning segments"
    types = [segment["type"] for segment in normalized_reasoning]
    assert all(prev != curr for prev, curr in zip(types, types[1:], strict=False))

    conversation_history = ChatConversation.new()
    timestamp = utc_now_iso()
    entry = ChatEntry(
        prompt=user_prompt,
        response=response.content or "",
        tokens=0,
        prompt_at=timestamp,
        response_at=timestamp,
        raw_result={
            "content": response.content,
            "reasoning": normalized_reasoning,
        },
    )
    entry.reasoning = tuple(dict(segment) for segment in normalized_reasoning)
    conversation_history.append_entry(entry)

    plain_text = compose_transcript_text(conversation_history)
    log_text = compose_transcript_log_text(conversation_history)

    (tmp_path / "transcript.txt").write_text(plain_text, encoding="utf-8")
    (tmp_path / "transcript_log.txt").write_text(log_text, encoding="utf-8")

    assert "Agent:" in plain_text
    assert "Model reasoning" in log_text

    timeline = build_conversation_timeline(conversation_history)
    assert timeline.entries, "conversation timeline is empty"
    turn = timeline.entries[0].agent_turn
    assert turn is not None and turn.reasoning
    assert list(turn.reasoning) == [dict(segment) for segment in normalized_reasoning]

    for segment in normalized_reasoning:
        full_text = (
            segment.get("leading_whitespace", "")
            + segment["text"]
            + segment.get("trailing_whitespace", "")
        )
        if full_text.strip():
            encoded = json.dumps(full_text, ensure_ascii=False)
            assert (
                encoded in log_text
            ), "reasoning text was not preserved in transcript log"

    new_entries = _new_log_entries(json_log_path, before_count)
    assert any(entry.get("event") == "LLM_REQUEST" for entry in new_entries)
    response_entries = [entry for entry in new_entries if entry.get("event") == "LLM_RESPONSE"]
    assert response_entries, "missing LLM_RESPONSE entries"
    assert any(entry.get("payload", {}).get("reasoning") for entry in response_entries)
