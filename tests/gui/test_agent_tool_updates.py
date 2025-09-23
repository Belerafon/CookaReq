import shutil
from concurrent.futures import Future
from pathlib import Path

import pytest

from app.core.model import requirement_to_dict

pytestmark = pytest.mark.gui


class SynchronousExecutor:
    """Run submitted functions immediately on the caller thread."""

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


def _copy_sample_repository(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[2] / "requirements"
    destination = tmp_path / "requirements"
    shutil.copytree(source, destination)
    return destination


def _create_main_frame(tmp_path: Path):
    wx = pytest.importorskip("wx")
    from app.config import ConfigManager
    from app.settings import MCPSettings
    from app.ui.main_frame import MainFrame
    from app.ui.requirement_model import RequirementModel

    config = ConfigManager(path=tmp_path / "agent.ini")
    config.set_mcp_settings(MCPSettings(auto_start=False))
    frame = MainFrame(None, config=config, model=RequirementModel())
    frame.Show()
    return frame


def test_agent_tool_updates_reflect_in_ui(tmp_path, wx_app):
    wx = pytest.importorskip("wx")

    repository = _copy_sample_repository(tmp_path)
    frame = _create_main_frame(tmp_path)

    try:
        wx_app.Yield()
        frame._load_directory(repository)
        wx_app.Yield()

        original = frame.model.get_visible()[0]
        new_title = f"{original.title} (renamed)"

        payload = requirement_to_dict(original)
        payload["rid"] = original.rid
        payload["title"] = new_title
        payload["revision"] = original.revision + 1

        class UpdateAgent:
            def run_command(self, text, *, history=None, context=None, cancellation=None):
                return {
                    "ok": True,
                    "error": None,
                    "result": "done",
                    "tool_results": [
                        {
                            "ok": True,
                            "tool_name": "update_requirement_field",
                            "tool_call_id": "call-0",
                            "call_id": "call-0",
                            "tool_arguments": {
                                "rid": original.rid,
                                "field": "title",
                                "value": new_title,
                            },
                            "result": payload,
                        }
                    ],
                }

        frame.agent_panel._cleanup_executor()
        frame.agent_panel._command_executor = SynchronousExecutor()
        frame.agent_panel._executor_pool = None
        frame.agent_panel._agent_supplier = lambda: UpdateAgent()

        frame._selected_requirement_id = original.id
        frame.editor.load(original)

        frame.agent_panel.input.SetValue("rename requirement")
        frame.agent_panel._on_send(None)
        wx_app.Yield()
        wx_app.Yield()

        updated = frame.model.get_by_id(original.id)
        assert updated is not None
        assert updated.title == new_title

        list_ctrl = frame.panel.list
        title_col = frame.panel._field_order.index("title")
        index = None
        for idx in range(list_ctrl.GetItemCount()):
            if list_ctrl.GetItemData(idx) == original.id:
                index = idx
                break
        assert index is not None
        assert new_title in list_ctrl.GetItemText(index, title_col)

        assert frame.editor.fields["title"].GetValue() == new_title
    finally:
        frame.Destroy()
        wx_app.Yield()
