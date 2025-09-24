from types import SimpleNamespace

from app.ui.main_frame.agent import MainFrameAgentMixin


class DummyFrame(MainFrameAgentMixin):
    def __init__(self, rid: str) -> None:
        self._summary = "SYS — Demo"
        requirement = SimpleNamespace(rid=rid, title="Sample requirement")
        self._requirements = {1: requirement}
        self.model = SimpleNamespace(get_by_id=self._requirements.get)

    def _current_document_summary(self) -> str | None:
        return self._summary

    def _selected_requirement_ids_for_agent(self):
        return [1]


def test_agent_context_accepts_lowercase_prefix() -> None:
    frame = DummyFrame("sys1")

    content = frame._agent_context_messages()[0]["content"]

    assert "Invalid requirement identifiers detected" not in content
    assert "Selected requirement RIDs: sys1" in content


def test_agent_context_reports_invalid_rids() -> None:
    frame = DummyFrame("SYS-1")

    messages = frame._agent_context_messages()
    assert messages, "context snapshot should not be empty"

    system_snapshot = messages[0]
    assert system_snapshot["role"] == "system"

    content = system_snapshot["content"]
    assert "Invalid requirement identifiers detected" in content
    assert "SYS-1" in content
    assert "<PREFIX><NUMBER>" in content
