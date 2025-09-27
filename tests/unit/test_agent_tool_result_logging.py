import logging
from types import SimpleNamespace

import pytest

from app.ui.main_frame.agent import MainFrameAgentMixin


class _StubPanel:
    def recalc_derived_map(self, _items):
        return None

    def focus_requirement(self, _req_id: int) -> None:  # pragma: no cover - noop
        return None


class _StubFrame(MainFrameAgentMixin):
    def __init__(self) -> None:
        self.current_doc_prefix = "SYS"
        self.model = SimpleNamespace(get_all=list)
        self.panel = _StubPanel()
        self.editor = SimpleNamespace(load=lambda *_args, **_kwargs: None)
        self._selected_requirement_id = None


@pytest.fixture()
def caplog_agent(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.WARNING, logger="cookareq.ui.main_frame.agent")
    return caplog


def test_logs_non_mapping_tool_payload(caplog_agent: pytest.LogCaptureFixture) -> None:
    frame = _StubFrame()

    frame._on_agent_tool_results(["unexpected"])

    assert any(
        "not a mapping" in record.getMessage() for record in caplog_agent.records
    )


def test_logs_failed_tool_payload(caplog_agent: pytest.LogCaptureFixture) -> None:
    frame = _StubFrame()

    frame._on_agent_tool_results(
        [
            {
                "ok": False,
                "tool_name": "update_requirement_field",
                "error": {"code": "VALIDATION_ERROR"},
            }
        ]
    )

    assert any(
        "reported failure" in record.getMessage() for record in caplog_agent.records
    )


def test_logs_missing_requirement_id(caplog_agent: pytest.LogCaptureFixture) -> None:
    frame = _StubFrame()

    frame._on_agent_tool_results(
        [
            {
                "ok": True,
                "tool_name": "update_requirement_field",
                "result": {"title": "Example"},
            }
        ]
    )

    assert any(
        "missing requirement id" in record.getMessage()
        for record in caplog_agent.records
    )
