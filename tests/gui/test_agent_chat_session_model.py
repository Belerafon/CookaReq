from unittest.mock import Mock

import pytest

from app.ui.agent_chat_panel.controller import AgentRunController
from app.ui.agent_chat_panel.coordinator import AgentChatCoordinator
from app.ui.agent_chat_panel.history import AgentChatHistory
from app.ui.agent_chat_panel.session import AgentChatSession
from app.llm.tokenizer import TokenCountResult


pytestmark = [pytest.mark.gui, pytest.mark.gui_full]


class _StubExecutor:
    def submit(self, func):  # pragma: no cover - protocol compatibility
        raise NotImplementedError


def _create_session(tmp_path, wx):
    frame = wx.Frame(None)
    history = AgentChatHistory(
        history_path=tmp_path / "agent_chats.sqlite",
        on_active_changed=None,
    )
    session = AgentChatSession(history=history, timer_owner=frame)
    return frame, session


def test_agent_chat_session_emits_events(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    frame, session = _create_session(tmp_path, wx)
    running_changes: list[bool] = []
    tokens_updates: list[TokenCountResult] = []
    elapsed_updates: list[float] = []

    session.events.running_changed.connect(running_changes.append)
    session.events.tokens_changed.connect(tokens_updates.append)
    session.events.elapsed.connect(elapsed_updates.append)

    start_tokens = TokenCountResult.exact(12)
    session.begin_run(tokens=start_tokens)
    assert session.is_running
    assert session.tokens == start_tokens
    assert running_changes[-1] is True

    finish_tokens = TokenCountResult.exact(8)
    session.finalize_run(tokens=finish_tokens)
    assert not session.is_running
    assert session.tokens == finish_tokens
    assert running_changes[-1] is False
    assert finish_tokens in tokens_updates
    assert elapsed_updates[0] == pytest.approx(0.0)

    session.shutdown()
    frame.Destroy()


def test_agent_chat_session_history_switch(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    frame, session = _create_session(tmp_path, wx)
    history_events: list[AgentChatHistory] = []
    session.events.history_changed.connect(history_events.append)

    new_path = tmp_path / "other.sqlite"
    changed = session.set_history_path(new_path)
    assert changed
    assert history_events
    session.shutdown()
    frame.Destroy()


def test_agent_chat_coordinator_forwards_calls(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    frame, session = _create_session(tmp_path, wx)
    run_controller = Mock(spec=AgentRunController)
    executor = _StubExecutor()
    coordinator = AgentChatCoordinator(
        session=session,
        run_controller=run_controller,
        command_executor=executor,
    )

    coordinator.submit_prompt("hello")
    run_controller.submit_prompt.assert_called_once_with("hello", prompt_at=None)

    coordinator.submit_prompt_with_context(
        "batch",
        conversation_id="c1",
        context_messages=None,
        prompt_at=None,
    )
    run_controller.submit_prompt_with_context.assert_called_once()

    run_controller.stop.return_value = object()
    handle = coordinator.cancel_active_run()
    assert handle is run_controller.stop.return_value

    coordinator.stop()
    assert run_controller.stop.call_count >= 2

    session.shutdown()
    frame.Destroy()
