from __future__ import annotations

import json
from pathlib import Path

from app.ui.agent_chat_panel.history_store import HistoryStore


def _entry_payload(*, prompt: str, response: str) -> dict[str, object]:
    return {
        "prompt": prompt,
        "response": response,
        "tokens": 0,
        "display_response": response,
        "raw_result": None,
        "token_info": {"tokens": 1, "approximate": False, "model": "cl100k_base"},
        "prompt_at": "2024-01-01T00:00:00Z",
        "response_at": "2024-01-01T00:01:00Z",
        "context_messages": None,
        "reasoning": None,
        "diagnostic": None,
        "regenerated": False,
    }


def _conversation_payload(conversation_id: str, title: str) -> dict[str, object]:
    return {
        "id": conversation_id,
        "title": title,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:05:00Z",
        "entries": [
            _entry_payload(prompt=f"Question {conversation_id}", response="Answer"),
        ],
    }


def _write_history(path: Path, *, active_id: str) -> None:
    payload = {
        "version": 2,
        "active_id": active_id,
        "conversations": [
            _conversation_payload("conv-1", "First"),
            _conversation_payload("conv-2", "Second"),
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_save_active_id_writes_sidecar_without_touching_history(tmp_path) -> None:
    history_path = tmp_path / "agent_chats.json"
    _write_history(history_path, active_id="conv-1")
    store = HistoryStore(history_path)
    conversations, selected = store.load()
    assert selected == "conv-1"
    initial_mtime = history_path.stat().st_mtime_ns

    store.save_active_id("conv-2")

    assert history_path.stat().st_mtime_ns == initial_mtime
    assert _read_json(store.active_path)["active_id"] == "conv-2"
    # Ensure cached payload tracks the override by saving again.
    store.save(conversations, "conv-2")
    assert _read_json(history_path)["active_id"] == "conv-2"


def test_load_prefers_active_override(tmp_path) -> None:
    history_path = tmp_path / "agent_chats.json"
    _write_history(history_path, active_id="conv-1")
    override_path = history_path.with_name("agent_chats_active.json")
    override_path.write_text(
        json.dumps({"active_id": "conv-2"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    store = HistoryStore(history_path)
    conversations, selected = store.load()

    assert len(conversations) == 2
    assert selected == "conv-2"


def test_save_updates_active_override(tmp_path) -> None:
    history_path = tmp_path / "agent_chats.json"
    _write_history(history_path, active_id="conv-1")
    store = HistoryStore(history_path)
    conversations, _ = store.load()

    store.save(conversations, "conv-2")

    saved = _read_json(history_path)
    assert saved["active_id"] == "conv-2"
    assert _read_json(store.active_path)["active_id"] == "conv-2"
