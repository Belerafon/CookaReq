import json
from pathlib import Path

import pytest

from app.mcp.server import start_server, stop_server
from app.settings import MCPSettings
from tests.llm_utils import settings_from_env
from tests.mcp_utils import _wait_until_ready
import app.ui.main_frame as main_frame
import app.ui.command_dialog as cmd



def test_main_frame_creates_requirement_via_llm(tmp_path: Path, monkeypatch) -> None:
    wx = pytest.importorskip("wx")
    port = 8155
    stop_server()
    start_server(port=port, base_path=str(tmp_path))
    try:
        _wait_until_ready(port)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        settings = settings_from_env(tmp_path)
        config = main_frame.ConfigManager(app_name="CookaReqTest")
        config.set_llm_settings(settings.llm)
        config.set_mcp_settings(
            MCPSettings(
                host="127.0.0.1",
                port=port,
                base_path=str(tmp_path),
                require_token=False,
                token="",
            )
        )
        history_file = tmp_path / "history.json"
        monkeypatch.setattr(cmd, "_default_history_path", lambda: history_file)
        command = (
            "Our users complain about slow logins and missing reports. "
            "Please create a requirement with id 99 titled 'Pain points test' "
            "and statement 'The system shall fix slow logins and missing reports', "
            "type requirement, status draft, owner bob, priority medium, source spec, "
            "verification analysis."
        )

        class AutoDialog(cmd.CommandDialog):
            def ShowModal(self) -> int:  # pragma: no cover - GUI side effect
                self.input.SetValue(command)
                self._on_run(None)
                return wx.ID_OK

        monkeypatch.setattr(main_frame, "CommandDialog", AutoDialog)
        app = wx.App()
        frame = main_frame.MainFrame(None, config=config)
        try:
            evt = wx.CommandEvent(wx.EVT_MENU.typeId, frame.navigation.run_command_id)
            frame.ProcessEvent(evt)
            data = json.loads((tmp_path / "99.json").read_text())
            assert data["title"] == "Pain points test"
            stmt = data["statement"].lower()
            assert "slow logins" in stmt
            assert "missing reports" in stmt
        finally:
            frame.Destroy()
            app.Destroy()
    finally:
        stop_server()
