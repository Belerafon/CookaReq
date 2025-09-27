import shutil
import threading
import time
from concurrent.futures import Future
from pathlib import Path

import pytest

from app.core.model import requirement_to_dict
from app.mcp.events import notify_tool_success

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
    _wx = pytest.importorskip("wx")
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
    _wx = pytest.importorskip("wx")

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
            def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None):
                notify_tool_success(
                    "update_requirement_field",
                    base_path=frame.mcp_settings.base_path,
                    arguments={
                        "rid": original.rid,
                        "field": "title",
                        "value": new_title,
                    },
                    result=payload,
                )
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
        frame.agent_panel._agent_supplier = lambda **_overrides: UpdateAgent()
        frame.agent_panel._initialize_controller()

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


def test_agent_streaming_tool_updates_refresh_list_during_run(tmp_path, wx_app):
    _wx = pytest.importorskip("wx")

    repository = _copy_sample_repository(tmp_path)
    frame = _create_main_frame(tmp_path)

    try:
        wx_app.Yield()
        frame._load_directory(repository)
        wx_app.Yield()

        original = frame.model.get_visible()[0]
        english_title = f"{original.title} (EN)"
        translated_title = f"{original.title} (RU)"

        payload_en = requirement_to_dict(original)
        payload_en["rid"] = original.rid
        payload_en["title"] = english_title
        payload_en["revision"] = original.revision + 1

        payload_ru = requirement_to_dict(original)
        payload_ru["rid"] = original.rid
        payload_ru["title"] = translated_title
        payload_ru["revision"] = original.revision + 2

        tool_payload_en = {
            "ok": True,
            "tool_name": "update_requirement_field",
            "tool_call_id": "call-0",
            "call_id": "call-0",
            "tool_arguments": {
                "rid": original.rid,
                "field": "title",
                "value": english_title,
            },
            "result": payload_en,
        }

        tool_payload_ru = {
            "ok": True,
            "tool_name": "update_requirement_field",
            "tool_call_id": "call-1",
            "call_id": "call-1",
            "tool_arguments": {
                "rid": original.rid,
                "field": "title",
                "value": translated_title,
            },
            "result": payload_ru,
        }

        class StreamingAgent:
            def __init__(self):
                self.started = threading.Event()
                self.first_sent = threading.Event()
                self.allow_finish = threading.Event()
                self.completed = threading.Event()

            def run_command(
                self,
                text,
                *,
                history=None,
                context=None,
                cancellation=None,
                on_tool_result=None,
            ):
                self.started.set()
                if on_tool_result is not None:
                    on_tool_result(dict(tool_payload_en))
                notify_tool_success(
                    "update_requirement_field",
                    base_path=frame.mcp_settings.base_path,
                    arguments=tool_payload_en["tool_arguments"],
                    result=tool_payload_en["result"],
                )
                self.first_sent.set()
                if not self.allow_finish.wait(timeout=5):
                    raise TimeoutError("Agent run did not finish in time")
                if on_tool_result is not None:
                    on_tool_result(dict(tool_payload_ru))
                notify_tool_success(
                    "update_requirement_field",
                    base_path=frame.mcp_settings.base_path,
                    arguments=tool_payload_ru["tool_arguments"],
                    result=tool_payload_ru["result"],
                )
                result_payload = [dict(tool_payload_en), dict(tool_payload_ru)]
                self.completed.set()
                return {
                    "ok": True,
                    "error": None,
                    "result": "done",
                    "tool_results": result_payload,
                }

        agent = StreamingAgent()
        frame.agent_panel._agent_supplier = lambda **_overrides: agent
        frame.agent_panel._initialize_controller()

        frame._selected_requirement_id = original.id
        frame.editor.load(original)

        list_ctrl = frame.panel.list
        title_col = frame.panel._field_order.index("title")

        def _current_list_title() -> str | None:
            for idx in range(list_ctrl.GetItemCount()):
                if list_ctrl.GetItemData(idx) == original.id:
                    return list_ctrl.GetItemText(idx, title_col)
            return None

        initial_title = _current_list_title()
        assert initial_title is not None and initial_title.endswith(original.title)

        def wait_for(condition, timeout=5.0) -> bool:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                wx_app.Yield()
                if condition():
                    return True
                time.sleep(0.01)
            return False

        frame.agent_panel.input.SetValue("rename requirement twice")
        frame.agent_panel._on_send(None)

        assert agent.started.wait(timeout=2.0)
        assert agent.first_sent.wait(timeout=2.0)

        assert wait_for(
            lambda: frame.model.get_by_id(original.id).title == english_title,
            timeout=5.0,
        )
        assert wait_for(
            lambda: (
                (_current_list_title() or "").endswith(english_title)
            ),
            timeout=5.0,
        )

        agent.allow_finish.set()
        assert agent.completed.wait(timeout=5.0)

        assert wait_for(
            lambda: frame.model.get_by_id(original.id).title == translated_title,
            timeout=5.0,
        )
        assert wait_for(
            lambda: (
                (_current_list_title() or "").endswith(translated_title)
            ),
            timeout=5.0,
        )
        assert wait_for(
            lambda: frame.editor.fields["title"].GetValue() == translated_title,
            timeout=5.0,
        )
    finally:
        frame.agent_panel._cleanup_executor()
        frame.Destroy()
        wx_app.Yield()
