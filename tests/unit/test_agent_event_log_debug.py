from pathlib import Path

from app.ui.agent_chat_panel.log_export import (
    render_event_log_debug,
    write_event_log_debug,
)


def test_render_event_log_debug_formats_sequence_and_payload() -> None:
    events = [
        {
            "kind": "llm_step",
            "sequence": 3,
            "payload": "hello",
            "source": "stream",
            "occurred_at": "2024-01-01T01:00:00Z",
        },
        {"kind": "tool_completed", "payload": {"result": "ok"}},
    ]

    output = render_event_log_debug(
        events,
        conversation_id="conv 1",
        entry_index=2,
        stage="final",
        timestamp="t0",
    )

    lines = output.splitlines()
    assert lines[0] == "conversation=conv 1 | entry=2 | stage=final | timestamp=t0"
    assert "#000 | seq=3 | kind=llm_step | source=stream | at=2024-01-01T01:00:00Z | payload=`hello`" in lines
    assert "#001 | seq=- | kind=tool_completed | source=- | payload=keys: result" in lines


def test_write_event_log_debug_creates_file(tmp_path: Path) -> None:
    events = [
        {"kind": "response", "sequence": 0, "payload": "ok", "source": "final"}
    ]

    path = write_event_log_debug(
        events,
        directory=tmp_path,
        conversation_id="conv id",
        entry_index=5,
        stage="complete",
        timestamp="2024-01-02T03:04:05Z",
    )

    assert path.parent == tmp_path
    assert path.name.startswith("conv-id-5-complete")
    content = path.read_text(encoding="utf-8")
    assert "conversation=conv id" in content
    assert "#000 | seq=0 | kind=response" in content
