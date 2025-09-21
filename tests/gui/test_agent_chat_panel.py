import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor

import pytest


pytestmark = [pytest.mark.gui, pytest.mark.integration]


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


def create_panel(tmp_path, wx_app, agent, executor=None):
    wx = pytest.importorskip("wx")
    from app.ui.agent_chat_panel import AgentChatPanel

    frame = wx.Frame(None)
    panel = AgentChatPanel(
        frame,
        agent_supplier=lambda: agent,
        history_path=tmp_path / "history.json",
        command_executor=executor or SynchronousAgentCommandExecutor(),
    )
    return wx, frame, panel


def destroy_panel(frame, panel):
    panel.Destroy()
    frame.Destroy()


def test_agent_chat_panel_sends_and_saves_history(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, text, *, history=None, cancellation=None):
            return {"ok": True, "error": None, "result": {"echo": text}}

    wx, frame, panel = create_panel(tmp_path, wx_app, DummyAgent())

    panel.input.SetValue("run")
    panel._on_send(None)
    flush_wx_events(wx)

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
    assert conversations[0]["entries"][0]["prompt"] == "run"
    assert conversations[0]["entries"][0]["response"].strip().startswith("{")

    panel._on_clear_input(None)
    assert panel.input.GetValue() == ""

    panel.input.SetValue("draft")

    panel._activate_conversation_by_index(0)
    assert panel.input.GetValue() == "draft"

    destroy_panel(frame, panel)


def test_agent_chat_panel_handles_error(tmp_path, wx_app):
    class FailingAgent:
        def run_command(self, text, *, history=None, cancellation=None):
            return {"ok": False, "error": {"code": "FAIL", "message": "bad"}}

    wx, frame, panel = create_panel(tmp_path, wx_app, FailingAgent())

    panel.input.SetValue("go")
    panel._on_send(None)
    flush_wx_events(wx)

    transcript = panel.get_transcript_text()
    assert "FAIL" in transcript
    assert panel.history[0].tokens >= 2

    destroy_panel(frame, panel)


def test_agent_chat_panel_stop_cancels_generation(tmp_path, wx_app):
    from app.i18n import _
    from app.ui.agent_chat_panel import ThreadedAgentCommandExecutor

    class BlockingAgent:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.completed = threading.Event()
            self.release = threading.Event()
            self.cancel_seen = threading.Event()

        def run_command(self, text, *, history=None, cancellation=None):
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


def test_agent_chat_panel_shuts_down_executor_pool_on_destroy(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, text, *, history=None, cancellation=None):  # pragma: no cover - defensive
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
        def run_command(self, text, *, history=None, cancellation=None):
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
        def run_command(self, text, *, history=None, cancellation=None):
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
        def run_command(self, text, *, history=None, cancellation=None):
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

        def run_command(self, text, *, history=None, cancellation=None):
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

        def run_command(self, text, *, history=None, cancellation=None):
            recorded_history = list(history or [])
            self.calls.append({"text": text, "history": recorded_history})
            return {"ok": True, "error": None, "result": f"answer {len(self.calls)}"}

    agent = RecordingAgent()
    wx, frame, panel = create_panel(tmp_path, wx_app, agent)

    panel.input.SetValue("keep this")
    panel._on_send(None)
    flush_wx_events(wx)
    assert agent.calls[0]["history"] == []

    panel._on_clear_history(None)
    assert panel.history == []
    assert panel.history_list.GetItemCount() == 0
    assert "Start chatting" in panel.get_transcript_text()

    panel.input.SetValue("after clear")
    panel._on_send(None)
    flush_wx_events(wx)
    assert agent.calls[-1]["history"] == []

    destroy_panel(frame, panel)


def test_agent_chat_panel_new_chat_creates_separate_conversation(tmp_path, wx_app):
    class RecordingAgent:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def run_command(self, text, *, history=None, cancellation=None):
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
        def run_command(self, text, *, history=None, cancellation=None):
            return {"ok": True, "error": None, "result": text.upper()}

    wx, frame, panel = create_panel(tmp_path, wx_app, EchoAgent())

    panel.input.SetValue("check metadata")
    panel._on_send(None)
    flush_wx_events(wx)

    assert panel.history_list.GetItemCount() == 1
    title = panel.history_list.GetTextValue(0, 0)
    last_activity = panel.history_list.GetTextValue(0, 1)
    summary = panel.history_list.GetTextValue(0, 2)

    assert "check metadata" in title
    assert last_activity != ""
    assert "Messages: 1" in summary
    assert "Tokens:" in summary
    assert "check metadata" in summary

    destroy_panel(frame, panel)


def test_agent_history_sash_waits_for_ready_size(tmp_path, wx_app, monkeypatch):
    class DummyAgent:
        def run_command(self, text, *, history=None, cancellation=None):
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
    assert panel._desired_history_sash == desired
    assert panel._history_sash_pending
    assert not panel._history_sash_idle_bound

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
    assert panel._desired_history_sash == desired
    assert not panel._history_sash_pending
    assert panel.history_sash == splitter.GetSashPosition()
    assert splitter.GetSashPosition() >= minimum

    wx_app.Yield()
    assert attempts[-1] == desired
    assert not panel._history_sash_pending
    assert not panel._history_sash_idle_bound

    destroy_panel(frame, panel)
    wx_app.Yield()
