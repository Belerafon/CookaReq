from app.ui.agent_chat_panel.controller import AgentRunController
from app.ui.agent_chat_panel.execution import _AgentRunHandle
from app.llm.tokenizer import TokenCountResult
from app.util.cancellation import CancellationEvent


def test_capture_llm_step_payload_preserves_reasoning_whitespace() -> None:
    handle = _AgentRunHandle(
        run_id=1,
        prompt="demo",
        prompt_tokens=TokenCountResult.exact(0),
        cancel_event=CancellationEvent(),
        prompt_at="2025-10-02T00:00:00Z",
    )

    payload = {
        "step": 1,
        "response": {
            "content": "Interpreting request",
            "reasoning": [
                {"type": "analysis", "text": "First", "trailing_whitespace": " "},
                {
                    "type": "thinking",
                    "text": "Second",
                    "leading_whitespace": " ",
                    "trailing_whitespace": " ",
                },
            ],
        },
    }

    safe_payload = AgentRunController._capture_llm_step_payload(handle, payload)

    assert safe_payload == {
        "step": 1,
        "response": {
            "content": "Interpreting request",
            "reasoning": [
                {"type": "analysis", "text": "First", "trailing_whitespace": " "},
                {
                    "type": "thinking",
                    "text": "Second",
                    "leading_whitespace": " ",
                    "trailing_whitespace": " ",
                },
            ],
        },
    }
    assert handle.llm_steps == [safe_payload]
    assert handle.latest_llm_response == "Interpreting request"
    assert handle.latest_reasoning_segments == (
        {"type": "analysis", "text": "First", "trailing_whitespace": " "},
        {
            "type": "thinking",
            "text": "Second",
            "leading_whitespace": " ",
            "trailing_whitespace": " ",
        },
    )
