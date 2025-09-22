import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from app.llm.tokenizer import TokenCountResult

import pytest


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
):
    wx = pytest.importorskip("wx")
    from app.ui.agent_chat_panel import AgentChatPanel

    frame = wx.Frame(None)
    panel = AgentChatPanel(
        frame,
        agent_supplier=lambda: agent,
        history_path=tmp_path / "history.json",
        command_executor=executor or SynchronousAgentCommandExecutor(),
        context_provider=context_provider,
        context_window_resolver=lambda: context_window,
    )
    return wx, frame, panel


def destroy_panel(frame, panel):
    panel.Destroy()
    frame.Destroy()


def test_agent_chat_panel_sends_and_saves_history(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None):
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

    saved = json.loads((tmp_path / "history.json").read_text())
    assert saved["version"] == 2
    assert isinstance(saved.get("active_id"), str)
    conversations = saved["conversations"]
    assert len(conversations) == 1
    entry_payload = conversations[0]["entries"][0]
    assert entry_payload["prompt"] == "run"
    assert entry_payload["response"].strip().startswith("{")
    assert entry_payload.get("token_info") is not None
    assert entry_payload["token_info"]["tokens"] == entry_payload["tokens"]
    assert "context_messages" in entry_payload
    assert entry_payload["context_messages"] is None

    history_entry = panel.history[0]
    assert history_entry.context_messages is None

    panel._on_clear_input(None)
    assert panel.input.GetValue() == ""

    panel.input.SetValue("draft")

    panel._activate_conversation_by_index(0)
    assert panel.input.GetValue() == "draft"

    destroy_panel(frame, panel)


def test_agent_chat_panel_regenerates_last_response(tmp_path, wx_app):
    class CountingAgent:
        def __init__(self) -> None:
            self.calls: int = 0

        def run_command(self, text, *, history=None, context=None, cancellation=None):
            self.calls += 1
            return f"answer {self.calls}"

    wx, frame, panel = create_panel(tmp_path, wx_app, CountingAgent())

    try:
        panel.input.SetValue("regen")
        panel._on_send(None)
        flush_wx_events(wx, count=5)

        assert panel.history
        assert len(panel.history) == 1
        first_entry = panel.history[0]
        assert first_entry.response.endswith("1")

        def find_regenerate_button(window):
            for child in window.GetChildren():
                if isinstance(child, wx.Button) and child.GetLabel() == "Перегенерить":
                    return child
                found = find_regenerate_button(child)
                if found is not None:
                    return found
            return None

        transcript_children = panel.transcript_panel.GetChildren()
        assert transcript_children
        regen_button = find_regenerate_button(transcript_children[-1])
        assert regen_button is not None
        assert regen_button.IsEnabled()

        evt = wx.CommandEvent(wx.EVT_BUTTON.typeId, regen_button.GetId())
        evt.SetEventObject(regen_button)
        regen_button.GetEventHandler().ProcessEvent(evt)
        flush_wx_events(wx, count=6)

        assert panel.history
        assert len(panel.history) == 1
        entry = panel.history[0]
        assert entry.response.endswith("2")
        transcript = panel.get_transcript_text()
        assert "answer 2" in transcript
        assert "answer 1" not in transcript
    finally:
        destroy_panel(frame, panel)


def test_agent_response_normalizes_dash_characters(tmp_path, wx_app):
    class HyphenAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None):
            return "одно\u2010папочный"

    wx, frame, panel = create_panel(tmp_path, wx_app, HyphenAgent())

    panel.input.SetValue("dash")
    panel._on_send(None)
    flush_wx_events(wx)

    transcript = panel.get_transcript_text()
    assert "одно-папочный" in transcript

    assert panel.history
    entry = panel.history[0]
    assert entry.response == "одно-папочный"
    assert entry.display_response == "одно-папочный"

    destroy_panel(frame, panel)


def test_agent_chat_panel_handles_error(tmp_path, wx_app):
    class FailingAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None):
            return {"ok": False, "error": {"code": "FAIL", "message": "bad"}}

    wx, frame, panel = create_panel(tmp_path, wx_app, FailingAgent())

    panel.input.SetValue("go")
    panel._on_send(None)
    flush_wx_events(wx)

    transcript = panel.get_transcript_text()
    assert "FAIL" in transcript
    entry = panel.history[0]
    assert entry.token_info is not None
    assert entry.token_info.tokens is not None
    assert entry.token_info.tokens >= 1

    destroy_panel(frame, panel)


def test_agent_chat_panel_passes_context(tmp_path, wx_app):
    captured: list[dict[str, Any]] = []

    class RecordingAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None):
            captured.append({"text": text, "context": context})
            return {"ok": True, "error": None, "result": "ok"}

    context_payload = {"role": "system", "content": "Active requirements list: SYS"}

    wx, frame, panel = create_panel(
        tmp_path,
        wx_app,
        RecordingAgent(),
        context_provider=lambda: context_payload,
    )

    panel.input.SetValue("context run")
    panel._on_send(None)
    flush_wx_events(wx)

    try:
        assert captured
        first_call = captured[0]
        assert first_call["text"] == "context run"
        assert first_call["context"] == (
            {"role": "system", "content": "Active requirements list: SYS"},
        )
        assert panel.history
        stored_entry = panel.history[0]
        assert stored_entry.context_messages == (
            {"role": "system", "content": "Active requirements list: SYS"},
        )
    finally:
        destroy_panel(frame, panel)


def test_agent_response_allows_text_selection(tmp_path, wx_app):
    class EchoAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None):
            return f"agent: {text}"

    wx, frame, panel = create_panel(tmp_path, wx_app, EchoAgent())

    panel.input.SetValue("hello world")
    panel._on_send(None)
    flush_wx_events(wx)

    transcript_children = panel.transcript_panel.GetChildren()
    assert transcript_children
    entry_panel = transcript_children[0]

    from app.ui.widgets.markdown_view import MarkdownContent

    text_controls: list[wx.TextCtrl] = []
    markdown_controls: list[MarkdownContent] = []

    def collect_text_controls(window) -> None:
        for child in window.GetChildren():
            if isinstance(child, wx.TextCtrl):
                text_controls.append(child)
            if isinstance(child, MarkdownContent):
                markdown_controls.append(child)
            collect_text_controls(child)

    collect_text_controls(entry_panel)
    if markdown_controls:
        agent_markdown = markdown_controls[0]
        assert agent_markdown.GetPlainText().strip() == "agent: hello world"
        agent_markdown.SelectAll()
        assert agent_markdown.HasSelection()
        assert agent_markdown.GetSelectionText().strip().startswith("agent: hello world")
    else:
        assert text_controls, "Expected agent message to expose a selectable control"
        agent_text = text_controls[0]
        assert agent_text.GetValue() == "agent: hello world"
        assert not agent_text.IsEditable()

    destroy_panel(frame, panel)


def test_transcript_scrolls_to_bottom_on_new_messages(tmp_path, wx_app):
    class EchoAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None):
            return text

    wx, frame, panel = create_panel(tmp_path, wx_app, EchoAgent())

    try:
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(panel, 1, wx.EXPAND)
        frame.SetSizer(sizer)
        frame.SetClientSize((panel.FromDIP(320), panel.FromDIP(220)))
        frame.Layout()
        frame.SendSizeEvent()
        flush_wx_events(wx, count=3)

        base_response = "\n".join(f"entry line {line}" for line in range(30))
        for idx in range(4):
            prompt = f"prompt {idx}"
            panel._append_history(prompt, base_response, base_response, None, None, None)
            panel._render_transcript()
        flush_wx_events(wx, count=5)

        transcript_panel = panel.transcript_panel
        assert transcript_panel.GetVirtualSize().GetHeight() > transcript_panel.GetClientSize().GetHeight()

        transcript_panel.Scroll(0, 0)
        flush_wx_events(wx, count=2)
        view_x, view_y = transcript_panel.GetViewStart()
        assert view_y == 0

        long_response = "\n".join(f"final line {line}" for line in range(40))
        panel._append_history("final prompt", long_response, long_response, None, None, None)
        panel._render_transcript()
        flush_wx_events(wx, count=6)

        view_x, view_y = transcript_panel.GetViewStart()
        assert view_y > 0

        children = transcript_panel.GetChildren()
        assert children, "expected transcript to contain message panels"
        last_panel = children[-1]
        last_top = last_panel.GetPosition().y
        last_bottom = last_top + last_panel.GetSize().GetHeight()
        client_height = transcript_panel.GetClientSize().GetHeight()
        assert last_bottom <= client_height
        tolerance = max(panel.FromDIP(64), last_panel.GetSize().GetHeight() // 4)
        assert client_height - last_bottom <= tolerance
    finally:
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
        def run_command(self, text, *, history=None, context=None, cancellation=None):
            return f"response to {text}"

    wx, frame, panel = create_panel(tmp_path, wx_app, SimpleAgent())
    monkeypatch.setattr(wx, "TheClipboard", DummyClipboard())

    assert panel._copy_conversation_btn is not None
    assert not panel._copy_conversation_btn.IsEnabled()

    panel.input.SetValue("copy me")
    panel._on_send(None)
    flush_wx_events(wx)

    assert panel._copy_conversation_btn.IsEnabled()

    panel._on_copy_conversation(None)

    assert "response to copy me" in clipboard["text"]

    destroy_panel(frame, panel)


def test_agent_chat_panel_hides_tool_results_and_exposes_log(tmp_path, wx_app):
    class ToolAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None):
            return {
                "ok": True,
                "error": None,
                "result": "done",
                "tool_results": [
                    {
                        "tool_name": "demo_tool",
                        "ok": True,
                        "tool_arguments": {"query": text},
                        "result": {"status": "ok"},
                    }
                ],
            }

    wx, frame, panel = create_panel(tmp_path, wx_app, ToolAgent())

    panel.input.SetValue("inspect")
    panel._on_send(None)
    flush_wx_events(wx)

    try:
        def collect_collapsible(window):
            panes: list[wx.CollapsiblePane] = []
            for child in window.GetChildren():
                if isinstance(child, wx.CollapsiblePane):
                    panes.append(child)
                panes.extend(collect_collapsible(child))
            return panes

        assert not collect_collapsible(panel.transcript_panel)

        transcript_text = panel.get_transcript_text()
        assert "demo_tool" not in transcript_text
        assert "tool_results" not in transcript_text

        log_text = panel.get_transcript_log_text()
        assert "demo_tool" in log_text
        assert "Tool calls" in log_text
        assert "query" in log_text
        assert "LLM system prompt" in log_text
        assert "LLM tool specification" in log_text
        assert "Context messages" in log_text
        assert "LLM request messages" in log_text
    finally:
        destroy_panel(frame, panel)


def test_agent_message_copy_selection(monkeypatch, wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.widgets.chat_message import MessageBubble

    clipboard: dict[str, str] = {}

    class DummyClipboard:
        def Open(self) -> bool:  # noqa: N802 - wx naming convention
            return True

        def Close(self) -> None:  # noqa: N802 - wx naming convention
            pass

        def SetData(self, data) -> None:  # noqa: N802 - wx naming convention
            clipboard["text"] = data.GetText()

    monkeypatch.setattr(wx, "TheClipboard", DummyClipboard())

    frame = wx.Frame(None)
    bubble = MessageBubble(
        frame,
        role_label="Agent",
        timestamp="",
        text="selectable text",
        align="left",
        allow_selection=True,
        render_markdown=True,
    )

    from app.ui.widgets.markdown_view import MarkdownContent

    assert isinstance(bubble._text, MarkdownContent)
    bubble._text.SelectAll()

    bubble._on_copy_selection(None)

    assert clipboard.get("text", "").strip().startswith("selectable text")

    bubble.Destroy()
    frame.Destroy()


def test_agent_chat_panel_stop_cancels_generation(tmp_path, wx_app):
    from app.i18n import _
    from app.ui.agent_chat_panel import ThreadedAgentCommandExecutor

    class BlockingAgent:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.completed = threading.Event()
            self.release = threading.Event()
            self.cancel_seen = threading.Event()

        def run_command(self, text, *, history=None, context=None, cancellation=None):
            self.started.set()
            try:
                while True:
                    if cancellation is not None and cancellation.wait(0.05):
                        self.cancel_seen.set()
                        cancellation.raise_if_cancelled()
                    if self.release.wait(0.05):
                        break
                return {"ok": True, "error": None, "result": text.upper()}
            finally:
                self.completed.set()

    agent = BlockingAgent()
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="TestAgentChat")
    frame = panel = None
    try:
        wx, frame, panel = create_panel(
            tmp_path,
            wx_app,
            agent,
            executor=ThreadedAgentCommandExecutor(pool),
        )

        panel.input.SetValue("stop me")
        panel._on_send(None)

        assert agent.started.wait(1.0)
        assert panel._stop_btn is not None and panel._stop_btn.IsEnabled()

        panel._on_stop(None)

        assert panel.input.GetValue() == "stop me"
        assert panel.status_label.GetLabel() == _("Generation cancelled")
        assert panel._stop_btn is not None and not panel._stop_btn.IsEnabled()

        assert agent.cancel_seen.wait(1.0)
        assert agent.completed.wait(1.0)
        wx.Yield()

        assert panel.history == []
    finally:
        if frame is not None and panel is not None:
            destroy_panel(frame, panel)
        pool.shutdown(wait=True, cancel_futures=True)


def test_agent_chat_panel_activity_indicator_layout(tmp_path, wx_app):
    class IdleAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None):  # pragma: no cover - defensive
            return {"ok": True, "error": None, "result": text}

    wx, frame, panel = create_panel(tmp_path, wx_app, IdleAgent())

    try:
        panel._set_wait_state(True)
        flush_wx_events(wx)

        activity_pos = panel.activity.GetPosition()
        status_pos = panel.status_label.GetPosition()
        indicator_height = max(1, panel.activity.GetSize().GetHeight())

        assert abs(activity_pos.y - status_pos.y) <= indicator_height
    finally:
        panel._set_wait_state(False)
        destroy_panel(frame, panel)


def test_agent_chat_panel_shuts_down_executor_pool_on_destroy(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None):  # pragma: no cover - defensive
            raise AssertionError("Should not be called")

    class DummyPool:
        def __init__(self) -> None:
            self.shutdown_called = False

        def submit(self, func):
            future = Future()
            future.set_result(None)
            return future

        def shutdown(self, wait=True, cancel_futures=False):
            self.shutdown_called = True

    from app.ui.agent_chat_panel import ThreadedAgentCommandExecutor

    pool = DummyPool()
    wx, frame, panel = create_panel(
        tmp_path,
        wx_app,
        DummyAgent(),
        executor=ThreadedAgentCommandExecutor(pool),
    )

    destroy_panel(frame, panel)

    assert pool.shutdown_called


def test_agent_chat_panel_persists_between_instances(tmp_path, wx_app):
    class EchoAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None):
            return {"ok": True, "error": None, "result": text}

    wx, frame1, panel1 = create_panel(tmp_path, wx_app, EchoAgent())
    panel1.input.SetValue("hello")
    panel1._on_send(None)
    flush_wx_events(wx)
    destroy_panel(frame1, panel1)

    wx, frame2, panel2 = create_panel(tmp_path, wx_app, EchoAgent())
    assert len(panel2.history) == 1
    assert panel2.history[0].prompt == "hello"
    destroy_panel(frame2, panel2)


def test_agent_chat_panel_handles_invalid_history(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.agent_chat_panel import AgentChatPanel

    bad_file = tmp_path / "history.json"
    bad_file.write_text("{not json}")

    class DummyAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None):
            return {"ok": True, "error": None, "result": {}}

    frame = wx.Frame(None)
    panel = AgentChatPanel(frame, agent_supplier=lambda: DummyAgent(), history_path=bad_file)
    assert panel.history == []
    destroy_panel(frame, panel)


def test_agent_chat_panel_ignores_flat_legacy_history(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.agent_chat_panel import AgentChatPanel

    legacy_file = tmp_path / "history.json"
    legacy_file.write_text(
        json.dumps(
            [
                {
                    "prompt": "old request",
                    "response": "old response",
                    "tokens": 2,
                }
            ]
        )
    )

    class DummyAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None):
            return {"ok": True, "error": None, "result": {}}

    frame = wx.Frame(None)
    panel = AgentChatPanel(frame, agent_supplier=lambda: DummyAgent(), history_path=legacy_file)

    assert panel.history == []
    assert panel.history_list.GetItemCount() == 0
    assert "Start chatting" in panel.get_transcript_text()

    destroy_panel(frame, panel)


def test_agent_chat_panel_provides_history_context(tmp_path, wx_app):
    class RecordingAgent:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def run_command(self, text, *, history=None, context=None, cancellation=None):
            recorded_history = list(history or [])
            self.calls.append({"text": text, "history": recorded_history})
            return {"ok": True, "error": None, "result": f"answer {len(self.calls)}"}

    agent = RecordingAgent()
    wx, frame, panel = create_panel(tmp_path, wx_app, agent)

    panel.input.SetValue("first question")
    panel._on_send(None)
    flush_wx_events(wx)
    assert agent.calls[0]["history"] == []
    first_response = panel.history[0].response

    panel.input.SetValue("second question")
    panel._on_send(None)
    flush_wx_events(wx)

    expected_history = [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": first_response},
    ]
    assert agent.calls[1]["history"] == expected_history

    destroy_panel(frame, panel)


def test_agent_chat_panel_clear_history_resets_context(tmp_path, wx_app):
    class RecordingAgent:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def run_command(self, text, *, history=None, context=None, cancellation=None):
            recorded_history = list(history or [])
            self.calls.append({"text": text, "history": recorded_history})
            return {"ok": True, "error": None, "result": f"answer {len(self.calls)}"}

    agent = RecordingAgent()
    wx, frame, panel = create_panel(tmp_path, wx_app, agent)

    panel.input.SetValue("keep this")
    panel._on_send(None)
    flush_wx_events(wx)
    assert agent.calls[0]["history"] == []

    panel.history_list.SelectRow(0)
    panel._on_clear_history(None)
    assert panel.history == []
    assert panel.history_list.GetItemCount() == 0
    assert "Start chatting" in panel.get_transcript_text()

    panel.input.SetValue("after clear")
    panel._on_send(None)
    flush_wx_events(wx)
    assert agent.calls[-1]["history"] == []

    destroy_panel(frame, panel)


def test_agent_chat_panel_delete_multiple_chats(tmp_path, wx_app):
    class RecordingAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None):
            return {"ok": True, "error": None, "result": f"answer {text}"}

    wx, frame, panel = create_panel(tmp_path, wx_app, RecordingAgent())

    panel.input.SetValue("first request")
    panel._on_send(None)
    flush_wx_events(wx)

    panel._on_new_chat(None)
    panel.input.SetValue("second request")
    panel._on_send(None)
    flush_wx_events(wx)

    panel._on_new_chat(None)
    panel.input.SetValue("third request")
    panel._on_send(None)
    flush_wx_events(wx)

    assert len(panel.conversations) == 3
    to_remove = list(panel.conversations[:2])
    last_id = panel.conversations[-1].conversation_id
    panel.input.SetValue("draft text")

    panel._remove_conversations(to_remove)

    assert len(panel.conversations) == 1
    assert panel.history_list.GetItemCount() == 1
    assert panel.conversations[0].conversation_id == last_id
    assert panel._active_conversation_id == last_id
    assert panel.input.GetValue() == "draft text"

    destroy_panel(frame, panel)


def test_agent_chat_panel_history_context_menu_handles_multiselect(
    monkeypatch, tmp_path, wx_app
):
    class QuietAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None):
            return {"ok": True, "error": None, "result": text}

    wx, frame, panel = create_panel(tmp_path, wx_app, QuietAgent())

    try:
        for idx in range(3):
            panel._append_history(
                f"prompt {idx}",
                f"response {idx}",
                f"response {idx}",
                None,
                None,
                TokenCountResult.exact(1),
            )
            flush_wx_events(wx)
            if idx < 2:
                panel._create_conversation(persist=True)
                flush_wx_events(wx)

        assert panel.history_list.GetItemCount() == 3

        panel.history_list.UnselectAll()
        first_item = panel.history_list.RowToItem(0)
        second_item = panel.history_list.RowToItem(1)
        panel.history_list.Select(first_item)
        panel._activate_conversation_by_index(0, refresh_history=False)
        flush_wx_events(wx)
        panel.history_list.Select(second_item)
        panel._activate_conversation_by_index(1, refresh_history=False)
        flush_wx_events(wx)

        assert panel._selected_history_rows() == [0, 1]
        assert panel._active_index() == 1

        captured_labels: list[list[str]] = []

        def fake_popup(menu, pos=wx.DefaultPosition):
            labels = [item.GetItemLabelText() for item in menu.GetMenuItems()]
            captured_labels.append(labels)
            return True

        monkeypatch.setattr(panel.history_list, "PopupMenu", fake_popup)

        panel._show_history_context_menu(1)
        flush_wx_events(wx)
        assert captured_labels and captured_labels[0][0] == "Delete selected chats"
        assert panel._selected_history_rows() == [0, 1]

        panel._show_history_context_menu(2)
        flush_wx_events(wx)
        assert len(captured_labels) >= 2 and captured_labels[1][0] == "Delete chat"
        assert panel._selected_history_rows() == [2]
    finally:
        destroy_panel(frame, panel)


def test_agent_chat_panel_new_chat_creates_separate_conversation(tmp_path, wx_app):
    class RecordingAgent:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def run_command(self, text, *, history=None, context=None, cancellation=None):
            recorded_history = list(history or [])
            self.calls.append({"text": text, "history": recorded_history})
            return {"ok": True, "error": None, "result": f"echo {len(self.calls)}"}

    agent = RecordingAgent()
    wx, frame, panel = create_panel(tmp_path, wx_app, agent)

    panel.input.SetValue("first request")
    panel._on_send(None)
    flush_wx_events(wx)
    assert agent.calls[0]["history"] == []
    assert len(panel.history) == 1

    panel._on_new_chat(None)
    assert panel.history == []
    assert panel.history_list.GetItemCount() == 2
    assert "does not have any messages yet" in panel.get_transcript_text()

    panel.input.SetValue("second request")
    panel._on_send(None)
    flush_wx_events(wx)
    assert agent.calls[-1]["history"] == []
    assert len(panel.history) == 1

    panel._activate_conversation_by_index(0)
    assert "first request" in panel.get_transcript_text()

    panel._activate_conversation_by_index(1)
    assert "second request" in panel.get_transcript_text()

    saved = json.loads((tmp_path / "history.json").read_text())
    prompts = [conv["entries"][0]["prompt"] for conv in saved["conversations"]]
    assert prompts == ["first request", "second request"]

    destroy_panel(frame, panel)


def test_agent_chat_panel_history_columns_show_metadata(tmp_path, wx_app):
    class EchoAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None):
            return {"ok": True, "error": None, "result": text.upper()}

    wx, frame, panel = create_panel(tmp_path, wx_app, EchoAgent())

    panel.input.SetValue("check metadata")
    panel._on_send(None)
    flush_wx_events(wx)

    assert panel.history_list.GetItemCount() == 1
    assert panel.history_list.GetColumnCount() == 2
    title = panel.history_list.GetTextValue(0, 0)
    last_activity = panel.history_list.GetTextValue(0, 1)

    assert "check metadata" in title
    assert last_activity != ""

    destroy_panel(frame, panel)


def test_agent_chat_panel_handles_tokenizer_failure(tmp_path, wx_app, monkeypatch):
    class EchoAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None):
            return {"ok": True, "error": None, "result": text}

    def failing_counter(*_args, **_kwargs) -> TokenCountResult:
        return TokenCountResult.unavailable(reason="boom")

    monkeypatch.setattr(
        "app.ui.agent_chat_panel.count_text_tokens",
        failing_counter,
    )

    wx, frame, panel = create_panel(tmp_path, wx_app, EchoAgent())

    panel.input.SetValue("token failure")
    panel._on_send(None)
    flush_wx_events(wx)

    assert "n/a" in panel.status_label.GetLabel()
    entry = panel.history[0]
    assert entry.token_info is not None
    assert entry.token_info.tokens is None

    destroy_panel(frame, panel)


def test_agent_history_sash_waits_for_ready_size(tmp_path, wx_app, monkeypatch):
    class DummyAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None):
            return {"ok": True, "error": None, "result": text}

    wx, frame, panel = create_panel(tmp_path, wx_app, DummyAgent())

    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(panel, 1, wx.EXPAND)
    frame.SetSizer(sizer)

    splitter = panel._horizontal_splitter
    minimum = splitter.GetMinimumPaneSize()
    desired = minimum + panel.FromDIP(180)
    attempts: list[int] = []
    original_attempt = panel._attempt_set_history_sash

    def tracking_attempt(target: int) -> bool:
        attempts.append(target)
        if len(attempts) == 1:
            return False
        return original_attempt(target)

    monkeypatch.setattr(panel, "_attempt_set_history_sash", tracking_attempt)

    panel.apply_history_sash(desired)

    assert attempts[0] == desired
    assert len(attempts) == 1
    assert panel._history_sash_goal == desired
    assert panel._history_sash_dirty

    wx_app.Yield()
    assert attempts == [desired]

    frame.Show()
    large_width = desired + panel.FromDIP(320)
    frame.SetClientSize((int(large_width), int(panel.FromDIP(400))))
    frame.Layout()
    frame.SendSizeEvent()
    wx_app.Yield()
    wx_app.Yield()

    assert attempts[0] == desired
    assert attempts[-1] == desired
    assert len(attempts) >= 2
    assert panel._history_sash_goal == desired
    assert not panel._history_sash_dirty
    assert panel.history_sash == splitter.GetSashPosition()
    assert splitter.GetSashPosition() >= minimum

    wx_app.Yield()
    assert attempts[-1] == desired
    assert not panel._history_sash_dirty

    destroy_panel(frame, panel)
    wx_app.Yield()
