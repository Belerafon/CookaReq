from app.agent.run_contract import (
    AgentEvent,
    AgentEventLog,
    AgentRunPayload,
    LlmStep,
    LlmTrace,
    ToolResultSnapshot,
)
from app.ui.agent_chat_panel.history_utils import ensure_canonical_agent_payload

def test_ensure_canonical_agent_payload_promotes_preview_and_snapshots() -> None:
    payload = AgentRunPayload(
        ok=True,
        status="succeeded",
        result_text="done",
        events=AgentEventLog(events=()),
        tool_results=(),
        llm_trace=LlmTrace(steps=()),
        timeline=(),
    )

    preview = (
        {
            "step": 1,
            "occurred_at": "2025-12-01T09:00:00+00:00",
            "request": ({"role": "user", "content": "hello"},),
            "response": {"content": "thinking"},
        },
    )
    snapshots = (
        ToolResultSnapshot(
            call_id="call-xyz",
            tool_name="alpha",
            status="succeeded",
            result={"value": 42},
            started_at="2025-12-01T09:00:01+00:00",
            completed_at="2025-12-01T09:00:05+00:00",
        ),
    )

    canonical = ensure_canonical_agent_payload(
        payload, tool_snapshots=snapshots, llm_trace_preview=preview
    )

    assert [snapshot.call_id for snapshot in canonical.tool_results] == ["call-xyz"]
    assert [step.index for step in canonical.llm_trace.steps] == [1]
    assert [entry.kind for entry in canonical.timeline] == ["llm_step", "tool_call"]
    assert [entry.sequence for entry in canonical.timeline] == [0, 1]
    tool_entry = canonical.timeline[1]
    assert tool_entry.call_id == "call-xyz"
    assert tool_entry.status == "succeeded"
