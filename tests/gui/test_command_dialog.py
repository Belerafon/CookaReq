"""Tests for command dialog."""

import json

import pytest

from app.agent.local_agent import LocalAgent

pytestmark = [pytest.mark.gui, pytest.mark.integration]


def test_command_dialog_shows_result_and_saves_history(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.command_dialog import CommandDialog

    class DummyLLM:
        def parse_command(self, text):
            return "list_requirements", {"per_page": 1}

    class DummyMCP:
        def call_tool(self, name, arguments):
            return {"ok": True, "error": None, "result": {"value": 42}}

    agent = LocalAgent(llm=DummyLLM(), mcp=DummyMCP())
    history_file = tmp_path / "history.json"
    dlg = CommandDialog(None, agent=agent, history_path=history_file)
    dlg.input.SetValue("run")
    dlg._on_run(None)
    data = json.loads(dlg.output.GetValue())
    assert data == {"value": 42}
    assert dlg.history_list.GetCount() == 1
    saved = json.loads(history_file.read_text())
    assert saved[0]["command"] == "run"
    assert saved[0]["tokens"] == len(["run"]) + len(dlg.output.GetValue().split())

    # clear and reload from history
    dlg._on_clear(None)
    assert dlg.output.GetValue() == ""
    evt = wx.CommandEvent(wx.EVT_LISTBOX.typeId, dlg.history_list.GetId())
    evt.SetInt(0)
    dlg._on_select_history(evt)
    assert json.loads(dlg.output.GetValue()) == {"value": 42}

    dlg.Destroy()


def test_command_dialog_shows_error(tmp_path, wx_app):
    pytest.importorskip("wx")
    from app.ui.command_dialog import CommandDialog

    class DummyLLM:
        def parse_command(self, text):
            return "list_requirements", {}

    class DummyMCP:
        def call_tool(self, name, arguments):
            return {"ok": False, "error": {"code": "FAIL", "message": "bad"}}

    agent = LocalAgent(llm=DummyLLM(), mcp=DummyMCP())
    history_file = tmp_path / "history.json"
    dlg = CommandDialog(None, agent=agent, history_path=history_file)
    dlg.input.SetValue("run")
    dlg._on_run(None)
    assert "FAIL" in dlg.output.GetValue()
    assert dlg.history[0].tokens == len(["run"]) + len(dlg.output.GetValue().split())
    dlg.Destroy()


def test_command_dialog_persists_between_instances(tmp_path, wx_app):
    pytest.importorskip("wx")
    from app.ui.command_dialog import CommandDialog

    class DummyAgent:
        def run_command(self, text):
            return {"ok": True, "error": None, "result": {"echo": text}}

    history_file = tmp_path / "history.json"

    dlg1 = CommandDialog(None, agent=DummyAgent(), history_path=history_file)
    dlg1.input.SetValue("hello")
    dlg1._on_run(None)
    dlg1.Destroy()

    dlg2 = CommandDialog(None, agent=DummyAgent(), history_path=history_file)
    assert len(dlg2.history) == 1
    assert dlg2.history[0].command == "hello"
    assert json.loads(dlg2.history[0].response)["echo"] == "hello"
    dlg2.Destroy()


def test_command_dialog_handles_invalid_history(tmp_path, wx_app):
    pytest.importorskip("wx")
    from app.ui.command_dialog import CommandDialog

    bad_file = tmp_path / "history.json"
    bad_file.write_text("{not json}")

    class DummyAgent:
        def run_command(self, text):
            return {"ok": True, "error": None, "result": {}}

    dlg = CommandDialog(None, agent=DummyAgent(), history_path=bad_file)
    assert dlg.history == []
    dlg.Destroy()
