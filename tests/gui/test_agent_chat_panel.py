import json

import pytest


pytestmark = [pytest.mark.gui, pytest.mark.integration]


def create_panel(tmp_path, wx_app, agent):
    wx = pytest.importorskip("wx")
    from app.ui.agent_chat_panel import AgentChatPanel

    frame = wx.Frame(None)
    panel = AgentChatPanel(
        frame,
        agent_supplier=lambda: agent,
        history_path=tmp_path / "history.json",
    )
    return wx, frame, panel


def destroy_panel(frame, panel):
    panel.Destroy()
    frame.Destroy()


def test_agent_chat_panel_sends_and_saves_history(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, text, *, history=None):
            return {"ok": True, "error": None, "result": {"echo": text}}

    wx, frame, panel = create_panel(tmp_path, wx_app, DummyAgent())

    panel.input.SetValue("run")
    panel._on_send(None)

    transcript = panel.transcript.GetValue()
    assert "run" in transcript
    assert "\"echo\": \"run\"" in transcript
    assert panel.history_list.GetCount() == 1

    saved = json.loads((tmp_path / "history.json").read_text())
    assert saved[0]["prompt"] == "run"
    assert saved[0]["response"].strip().startswith("{")

    panel._on_clear_input(None)
    assert panel.input.GetValue() == ""

    evt = wx.CommandEvent(wx.EVT_LISTBOX.typeId, panel.history_list.GetId())
    evt.SetInt(0)
    panel._on_select_history(evt)
    assert panel.input.GetValue() == "run"

    destroy_panel(frame, panel)


def test_agent_chat_panel_handles_error(tmp_path, wx_app):
    class FailingAgent:
        def run_command(self, text, *, history=None):
            return {"ok": False, "error": {"code": "FAIL", "message": "bad"}}

    wx, frame, panel = create_panel(tmp_path, wx_app, FailingAgent())

    panel.input.SetValue("go")
    panel._on_send(None)

    transcript = panel.transcript.GetValue()
    assert "FAIL" in transcript
    assert panel.history[0].tokens >= 2

    destroy_panel(frame, panel)


def test_agent_chat_panel_persists_between_instances(tmp_path, wx_app):
    class EchoAgent:
        def run_command(self, text, *, history=None):
            return {"ok": True, "error": None, "result": text}

    wx, frame1, panel1 = create_panel(tmp_path, wx_app, EchoAgent())
    panel1.input.SetValue("hello")
    panel1._on_send(None)
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
        def run_command(self, text, *, history=None):
            return {"ok": True, "error": None, "result": {}}

    frame = wx.Frame(None)
    panel = AgentChatPanel(frame, agent_supplier=lambda: DummyAgent(), history_path=bad_file)
    assert panel.history == []
    destroy_panel(frame, panel)


def test_agent_chat_panel_provides_history_context(tmp_path, wx_app):
    class RecordingAgent:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def run_command(self, text, *, history=None):
            recorded_history = list(history or [])
            self.calls.append({"text": text, "history": recorded_history})
            return {"ok": True, "error": None, "result": f"answer {len(self.calls)}"}

    agent = RecordingAgent()
    wx, frame, panel = create_panel(tmp_path, wx_app, agent)

    panel.input.SetValue("first question")
    panel._on_send(None)
    assert agent.calls[0]["history"] == []
    first_response = panel.history[0].response

    panel.input.SetValue("second question")
    panel._on_send(None)

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

        def run_command(self, text, *, history=None):
            recorded_history = list(history or [])
            self.calls.append({"text": text, "history": recorded_history})
            return {"ok": True, "error": None, "result": f"answer {len(self.calls)}"}

    agent = RecordingAgent()
    wx, frame, panel = create_panel(tmp_path, wx_app, agent)

    panel.input.SetValue("keep this")
    panel._on_send(None)
    assert agent.calls[0]["history"] == []

    panel._on_clear_history(None)
    assert panel.history == []
    assert panel.history_list.GetCount() == 0
    assert "Start chatting" in panel.transcript.GetValue()

    panel.input.SetValue("after clear")
    panel._on_send(None)
    assert agent.calls[-1]["history"] == []

    destroy_panel(frame, panel)
