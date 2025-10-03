from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from concurrent.futures import Future
from typing import Any

import pytest

from app.confirm import (
    ConfirmDecision,
    reset_requirement_update_preference,
    set_confirm,
    set_requirement_update_confirm,
)
from app.ui.agent_chat_panel import AgentProjectSettings
from app.ui.agent_chat_panel.time_formatting import format_entry_timestamp
from app.ui.chat_entry import ChatConversation, ChatEntry

pytestmark = [pytest.mark.gui, pytest.mark.integration, pytest.mark.gui_smoke]


class SynchronousAgentCommandExecutor:
    """Executor that runs submitted functions immediately on the caller thread."""

    def submit(self, func):
        future: Future = Future()
        if not future.set_running_or_notify_cancel():
            return future
        try:
            result = func()
        except BaseException as exc:  # pragma: no cover - defensive
            future.set_exception(exc)
        else:
            future.set_result(result)
        return future


def flush_wx_events(wx, count: int = 3) -> None:
    for _ in range(count):
        wx.Yield()


def create_panel(
    tmp_path,
    wx_app,
    agent,
    executor=None,
    context_provider=None,
    context_window=4096,
    confirm_preference=None,
    persist_confirm_preference=None,
    use_default_executor: bool = False,
):
    wx = pytest.importorskip("wx")
    from app.ui.agent_chat_panel import AgentChatPanel
    import app.confirm as confirm_mod

    frame = wx.Frame(None)
    command_executor = None if use_default_executor else executor or SynchronousAgentCommandExecutor()
    panel = AgentChatPanel(
        frame,
        agent_supplier=lambda **_overrides: agent,
        history_path=tmp_path / "history.json",
        command_executor=command_executor,
        context_provider=context_provider,
        context_window_resolver=lambda: context_window,
        confirm_preference=confirm_preference,
        persist_confirm_preference=persist_confirm_preference,
    )
    panel.set_project_settings_path(tmp_path / "agent_settings.json")

    previous_confirm = confirm_mod._callback
    previous_update = confirm_mod._requirement_update_callback
    reset_requirement_update_preference()
    set_confirm(lambda _message: True)
    set_requirement_update_confirm(lambda _prompt: ConfirmDecision.YES)

    def _restore_confirm() -> None:
        confirm_mod._callback = previous_confirm
        confirm_mod._requirement_update_callback = previous_update
        reset_requirement_update_preference()

    panel._restore_confirm = _restore_confirm
    return wx, frame, panel


def destroy_panel(frame, panel):
    restore = getattr(panel, "_restore_confirm", None)
    if callable(restore):
        restore()
    panel.Destroy()
    frame.Destroy()


def build_entry(
    *,
    prompt: str = "prompt",
    response: str = "response",
    prompt_at: str = "2024-01-01T10:00:00+00:00",
    response_at: str = "2024-01-01T10:02:00+00:00",
    context_messages: Sequence[Mapping[str, Any]] | None = None,
    reasoning_segments: Sequence[Mapping[str, Any]] | None = None,
    tool_results: Sequence[Mapping[str, Any]] | None = None,
) -> ChatEntry:
    return ChatEntry(
        prompt=prompt,
        response=response,
        tokens=0,
        display_response=response,
        prompt_at=prompt_at,
        response_at=response_at,
        context_messages=tuple(context_messages or ()),
        reasoning=tuple(reasoning_segments or ()),
        tool_results=list(tool_results or ()),
    )


def test_transcript_rows_populate_after_send(tmp_path, wx_app):
    class EchoAgent:
        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
            on_llm_step=None,
        ):
            return f"response: {text}"

    wx, frame, panel = create_panel(tmp_path, wx_app, EchoAgent())
    try:
        panel.input.SetValue("hello world")
        panel._on_send(None)
        flush_wx_events(wx)

        rows = panel._transcript_rows
        assert rows, "expected transcript rows after sending"
        assert any("hello world" in row.text for row in rows)
        assert any("response" in row.text for row in rows)
        assert len(panel._transcript_segments) == len(rows)
        value = panel._transcript_view.GetValue()
        assert "hello world" in value
        assert "response" in value
    finally:
        destroy_panel(frame, panel)


def test_transcript_includes_context_reasoning_and_tool_rows(tmp_path, wx_app):
    wx, frame, panel = create_panel(tmp_path, wx_app, agent=lambda **_: None)
    try:
        context_messages = (
            {"role": "system", "content": "remember this"},
            {"role": "user", "content": [{"text": "fragment"}]},
        )
        reasoning_segments = (
            {"type": "thought", "text": "consider"},
            {"type": "thought", "text": "decide"},
        )
        tool_results = (
            {
                "tool_name": "write_file",
                "status": "completed",
                "arguments": {"path": "README.md"},
            },
        )
        entry = build_entry(
            prompt="do it",
            response="done",
            context_messages=context_messages,
            reasoning_segments=reasoning_segments,
            tool_results=tool_results,
        )
        conversation = ChatConversation(
            conversation_id="conv-1",
            title="Test",
            created_at=entry.prompt_at,
            updated_at=entry.response_at,
            entries=[entry],
        )
        panel._session.history.set_conversations([conversation])
        panel._session.history.set_active_id(conversation.conversation_id)
        panel._render_transcript()

        sources = {row.source for row in panel._transcript_rows}
        assert {"Context", "Agent reasoning", "Tool"}.issubset(sources)
        tool_row = next(row for row in panel._transcript_rows if row.source == "Tool")
        assert "write_file" in tool_row.text
    finally:
        destroy_panel(frame, panel)


def test_switching_to_previous_chat_after_starting_new_one(tmp_path, wx_app):
    class DummyAgent:
        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
            on_llm_step=None,
        ):
            return {"ok": True, "error": None, "result": {"echo": text}}

    wx, frame, panel = create_panel(tmp_path, wx_app, DummyAgent())

    try:
        panel.input.SetValue("first message")
        panel._on_send(None)
        flush_wx_events(wx)

        assert panel.history_list.GetItemCount() == 1
        assert "first message" in panel.get_transcript_text()

        panel._on_new_chat(None)
        flush_wx_events(wx)

        assert panel.history_list.GetItemCount() == 2
        assert panel._active_index() == 1

        panel._on_history_row_activated(0)
        flush_wx_events(wx)

        assert panel._active_index() == 0
        transcript = panel.get_transcript_text()
        assert "first message" in transcript
    finally:
        destroy_panel(frame, panel)


def test_agent_custom_system_prompt_appended(tmp_path, wx_app):
    class CaptureAgent:
        def __init__(self) -> None:
            self.last_history: list[dict[str, str]] | None = None

        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
            on_llm_step=None,
        ):
            self.last_history = list(history or [])
            return {"ok": True, "result": {"echo": text}}

    agent = CaptureAgent()
    wx, frame, panel = create_panel(tmp_path, wx_app, agent)

    try:
        custom_prompt = "Follow project conventions"
        panel._apply_project_settings(
            AgentProjectSettings(custom_system_prompt=custom_prompt)
        )
        panel.input.SetValue("Plan release")
        panel._on_send(None)
        flush_wx_events(wx)

        history = agent.last_history
        assert history is not None
        assert history[0]["role"] == "system"
        assert history[0]["content"] == custom_prompt

        assert panel.history
        entry = panel.history[0]
        assert entry.diagnostic
        assert entry.diagnostic.get("custom_system_prompt") == custom_prompt
        assert entry.diagnostic["history_messages"][0]["role"] == "system"
        assert entry.diagnostic["history_messages"][0]["content"] == custom_prompt
    finally:
        destroy_panel(frame, panel)


def test_agent_chat_panel_sends_and_saves_history(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {"ok": True, "error": None, "result": {"echo": text}}

    wx, frame, panel = create_panel(tmp_path, wx_app, DummyAgent())

    baseline_total = panel._compute_context_token_breakdown().total
    baseline_label = panel._conversation_label.GetLabel()

    panel.input.SetValue("run")
    panel._on_send(None)
    flush_wx_events(wx)

    updated_total = panel._compute_context_token_breakdown().total
    updated_label = panel._conversation_label.GetLabel()
    assert updated_label != baseline_label
    assert (updated_total.tokens or 0) >= (baseline_total.tokens or 0)
    expected_tokens = panel._format_tokens_for_status(updated_total)
    assert expected_tokens in updated_label
    expected_percent = panel._format_context_percentage(
        updated_total, panel._context_token_limit()
    )
    assert expected_percent in updated_label

    transcript = panel.get_transcript_text()
    assert "run" in transcript
    assert "\"echo\": \"run\"" in transcript
    assert panel.history_list.GetItemCount() == 1
    assert panel.input.GetValue() == ""
    assert len(panel.history) == 1
    assert len(panel._transcript_segments) == len(panel._transcript_rows)

    saved = json.loads((tmp_path / "history.json").read_text())
    assert saved["version"] == 2
    assert isinstance(saved.get("active_id"), str)
    conversations = saved["conversations"]
    assert len(conversations) == 1
    assert conversations[0]["entries"], "expected serialized entries"

    destroy_panel(frame, panel)


def test_agent_chat_panel_regenerates_last_response(tmp_path, wx_app):
    class CountingAgent:
        def __init__(self) -> None:
            self.calls: int = 0
            self.history_snapshots: list[Sequence[Mapping[str, Any]] | None] = []

        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            self.calls += 1
            if history is None:
                self.history_snapshots.append(None)
            else:
                try:
                    cloned = [dict(message) for message in history]
                except Exception:
                    cloned = list(history)
                self.history_snapshots.append(cloned)
            return f"answer {self.calls}"

    agent = CountingAgent()
    wx, frame, panel = create_panel(tmp_path, wx_app, agent)

    try:
        panel.input.SetValue("regen")
        panel._on_send(None)
        flush_wx_events(wx, count=5)

        assert panel.history
        assert len(panel.history) == 1
        first_entry = panel.history[0]
        assert first_entry.response.endswith("1")

        agent_row_index = next(
            idx for idx, row in enumerate(panel._transcript_rows) if row.can_regenerate
        )
        panel._trigger_regenerate_from_row(agent_row_index)
        flush_wx_events(wx, count=6)

        assert panel.history
        assert len(panel.history) == 1
        regenerated_entry = panel.history[0]
        assert regenerated_entry.response.endswith("2")
        transcript = panel.get_transcript_text()
        assert "answer 1" not in transcript
        assert "answer 2" in transcript
        assert agent.history_snapshots[1] in (None, [])
    finally:
        destroy_panel(frame, panel)


def test_agent_response_normalizes_dash_characters(tmp_path, wx_app):
    class HyphenAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return "single\u2010folder"

    wx, frame, panel = create_panel(tmp_path, wx_app, HyphenAgent())

    panel.input.SetValue("dash")
    panel._on_send(None)
    flush_wx_events(wx)

    transcript = panel.get_transcript_text()
    assert "single-folder" in transcript

    assert panel.history
    entry = panel.history[0]
    assert entry.response == "single-folder"
    assert entry.display_response == "single-folder"

    destroy_panel(frame, panel)


def test_agent_chat_panel_handles_error(tmp_path, wx_app):
    class FailingAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {"ok": False, "error": {"code": "FAIL", "message": "bad"}}

    wx, frame, panel = create_panel(tmp_path, wx_app, FailingAgent())

    panel.input.SetValue("go")
    panel._on_send(None)
    flush_wx_events(wx)

    transcript = panel.get_transcript_text()
    assert "FAIL" in transcript
    entry = panel.history[0]
    assert entry.raw_result == {"ok": False, "error": {"code": "FAIL", "message": "bad"}}

    destroy_panel(frame, panel)


def test_copy_conversation_button_copies_transcript(monkeypatch, tmp_path, wx_app):
    clipboard: dict[str, str] = {}

    class DummyClipboard:
        def __init__(self) -> None:
            self.opened = False

        def Open(self) -> bool:  # noqa: N802 - wx naming convention
            self.opened = True
            return True

        def Close(self) -> None:  # noqa: N802 - wx naming convention
            self.opened = False

        def SetData(self, data) -> None:  # noqa: N802 - wx naming convention
            clipboard["text"] = data.GetText()

    class SimpleAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return f"response to {text}"

    wx, frame, panel = create_panel(tmp_path, wx_app, SimpleAgent())
    monkeypatch.setattr(wx, "TheClipboard", DummyClipboard())

    try:
        panel.input.SetValue("copy")
        panel._on_send(None)
        flush_wx_events(wx)

        panel._on_copy_conversation(None)
        assert "copy" in clipboard.get("text", "")
        assert "response to copy" in clipboard.get("text", "")
    finally:
        destroy_panel(frame, panel)


def test_copy_selected_rows_uses_clipboard(monkeypatch, tmp_path, wx_app):
    clipboard: dict[str, str] = {}

    class DummyClipboard:
        def __init__(self) -> None:
            self.opened = False

        def Open(self) -> bool:  # noqa: N802 - wx naming convention
            self.opened = True
            return True

        def Close(self) -> None:  # noqa: N802 - wx naming convention
            self.opened = False

        def SetData(self, data) -> None:  # noqa: N802 - wx naming convention
            clipboard["text"] = data.GetText()

    class EchoAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return text

    wx, frame, panel = create_panel(tmp_path, wx_app, EchoAgent())
    monkeypatch.setattr(wx, "TheClipboard", DummyClipboard())

    try:
        panel.input.SetValue("copy rows")
        panel._on_send(None)
        flush_wx_events(wx)

        text_ctrl = panel._transcript_view
        assert text_ctrl is not None
        value = text_ctrl.GetValue()
        assert "copy rows" in value
        text_ctrl.SetSelection(0, len(value))
        selected = text_ctrl.GetStringSelection()
        assert selected
        panel._copy_text_to_clipboard(selected)
        copied = clipboard.get("text", "")
        assert "copy rows" in copied
    finally:
        destroy_panel(frame, panel)


def test_transcript_segment_lookup_handles_trailing_offset(tmp_path, wx_app):
    class EchoAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return f"echo {text}"

    wx, frame, panel = create_panel(tmp_path, wx_app, EchoAgent())

    try:
        panel.input.SetValue("segment")
        panel._on_send(None)
        flush_wx_events(wx)

        text_value = panel._transcript_view.GetValue()
        assert text_value
        offset = len(text_value) + 5
        segment_info = panel._find_transcript_segment(offset)
        assert segment_info is not None
        row_index, row = segment_info
        assert 0 <= row_index < len(panel._transcript_rows)
        assert row.source.startswith("Agent")
    finally:
        destroy_panel(frame, panel)


def test_transcript_rows_clear_after_history_removal(tmp_path, wx_app):
    class EchoAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return text

    wx, frame, panel = create_panel(tmp_path, wx_app, EchoAgent())

    try:
        panel.input.SetValue("first")
        panel._on_send(None)
        flush_wx_events(wx)

        assert panel._transcript_rows
        panel._delete_history_rows([0])
        flush_wx_events(wx)
        assert not panel._transcript_rows
        assert panel._transcript_view.GetValue() == ""
    finally:
        destroy_panel(frame, panel)


def test_format_entry_timestamp_handles_invalid_input():
    assert format_entry_timestamp(None) == ""
    assert format_entry_timestamp("") == ""


def test_reasoning_merge_handles_whitespace(tmp_path, wx_app):
    wx, frame, panel = create_panel(tmp_path, wx_app, agent=lambda **_: None)
    try:
        entry = build_entry(
            prompt="prompt",
            response="response",
            reasoning_segments=(
                {"type": "thought", "text": "first", "trailing_whitespace": ""},
                {"type": "thought", "text": "second", "leading_whitespace": " "},
            ),
        )
        conversation = ChatConversation(
            conversation_id="conv-merge",
            title="Merge",
            created_at=entry.prompt_at,
            updated_at=entry.response_at,
            entries=[entry],
        )
        panel._session.history.set_conversations([conversation])
        panel._session.history.set_active_id(conversation.conversation_id)
        panel._render_transcript()

        reasoning_row = next(row for row in panel._transcript_rows if row.source == "Agent reasoning")
        assert "first" in reasoning_row.text and "second" in reasoning_row.text
    finally:
        destroy_panel(frame, panel)


def test_copy_buttons_initial_state(tmp_path, wx_app):
    wx, frame, panel = create_panel(tmp_path, wx_app, agent=lambda **_: "")

    try:
        assert not panel._copy_conversation_btn.IsEnabled()
        assert not panel._copy_transcript_log_btn.IsEnabled()
        panel.input.SetValue("run")
        panel._on_send(None)
        flush_wx_events(wx)
        assert panel._copy_conversation_btn.IsEnabled()
        assert panel._copy_transcript_log_btn.IsEnabled()
    finally:
        destroy_panel(frame, panel)


