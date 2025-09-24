import logging
from types import SimpleNamespace

import pytest

from app.core.model import (
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
)

from app.ui.main_frame.agent import MainFrameAgentMixin


class _StubPanel:
    def recalc_derived_map(self, _items):
        return None

    def focus_requirement(self, _req_id: int) -> None:  # pragma: no cover - noop
        return None


class _StubFrame(MainFrameAgentMixin):
    def __init__(self) -> None:
        self.current_doc_prefix = "SYS"
        self.model = SimpleNamespace(get_all=lambda: [])
        self.panel = _StubPanel()
        self.editor = SimpleNamespace(load=lambda *_args, **_kwargs: None)
        self._selected_requirement_id = None


class _RecordingPanel(_StubPanel):
    def __init__(self) -> None:
        self.recalc_calls: list[list[Requirement]] = []
        self.focused: list[int] = []

    def recalc_derived_map(self, items):
        self.recalc_calls.append(list(items))

    def focus_requirement(self, req_id: int) -> None:
        self.focused.append(req_id)


class _RecordingEditor:
    def __init__(self) -> None:
        self.loaded: list[Requirement] = []

    def load(self, requirement: Requirement) -> None:
        self.loaded.append(requirement)


class _RecordingModel:
    def __init__(self, requirements: list[Requirement]):
        self._all = list(requirements)
        self.updated: list[Requirement] = []
        self.deleted: list[int] = []

    def get_all(self) -> list[Requirement]:
        return list(self._all)

    def update(self, requirement: Requirement) -> None:
        self.updated.append(requirement)
        for idx, existing in enumerate(self._all):
            if existing.id == requirement.id:
                self._all[idx] = requirement
                break
        else:
            self._all.append(requirement)

    def delete(self, req_id: int) -> None:
        self.deleted.append(req_id)
        self._all = [req for req in self._all if req.id != req_id]


class _RecordingFrame(MainFrameAgentMixin):
    def __init__(self, prefix: str, requirements: list[Requirement]):
        self.current_doc_prefix = prefix
        self.model = _RecordingModel(requirements)
        self.panel = _RecordingPanel()
        self.editor = _RecordingEditor()
        self._selected_requirement_id = requirements[0].id if requirements else None
        self.editor_cleared = False

    def _clear_editor_panel(self) -> None:
        self.editor_cleared = True


def _base_requirement(req_id: int, title: str, *, prefix: str) -> Requirement:
    req = Requirement(
        id=req_id,
        title=title,
        statement="Statement",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="",
        priority=Priority.MEDIUM,
        source="",
        verification=Verification.ANALYSIS,
    )
    req.doc_prefix = prefix
    req.rid = f"{prefix}{req_id}"
    return req


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


def test_tool_update_applies_with_case_insensitive_prefix() -> None:
    existing = _base_requirement(1, "Original", prefix="sys")
    frame = _RecordingFrame("sys", [existing])
    frame._selected_requirement_id = 1

    payload = {
        "ok": True,
        "tool_name": "update_requirement_field",
        "result": {
            "id": 1,
            "title": "Renamed",
            "statement": "Statement",
            "type": "requirement",
            "status": "draft",
            "owner": "",
            "priority": "medium",
            "source": "",
            "verification": "analysis",
            "conditions": "",
            "rationale": "",
            "assumptions": "",
            "notes": "",
            "modified_at": "",
            "labels": [],
            "attachments": [],
            "links": [],
            "revision": existing.revision + 1,
            "rid": "SYS1",
        },
    }

    frame._on_agent_tool_results([payload])

    assert frame.model.updated, "expected requirement update to be applied"
    updated = frame.model.updated[0]
    assert updated.doc_prefix == "sys"
    assert updated.rid == "sys1"
    assert updated.title == "Renamed"
    assert frame.panel.recalc_calls and frame.panel.recalc_calls[-1][0].title == "Renamed"
    assert frame.editor.loaded and frame.editor.loaded[-1].title == "Renamed"
    assert frame.panel.focused == [1]


def test_tool_delete_respects_case_insensitive_prefix() -> None:
    existing = _base_requirement(1, "Original", prefix="sys")
    frame = _RecordingFrame("sys", [existing])
    frame._selected_requirement_id = 1

    payload = {
        "ok": True,
        "tool_name": "delete_requirement",
        "result": {"rid": "SYS1"},
    }

    frame._on_agent_tool_results([payload])

    assert frame.model.deleted == [1]
    assert frame.panel.recalc_calls and frame.panel.recalc_calls[-1] == []
    assert frame.editor_cleared is True
    assert frame._selected_requirement_id is None
    assert frame.panel.focused == []
