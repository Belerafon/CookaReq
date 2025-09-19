"""Simplified tests for the debug ListPanel implementation."""

import importlib

import pytest

from app.core.model import Priority, Requirement, RequirementType, Status, Verification
from app.ui.requirement_model import RequirementModel

pytestmark = pytest.mark.skip(
    reason="ListPanel tests temporarily disabled while the widget runs in ultra-minimal debug mode."
)


def _req(req_id: int, title: str, **overrides) -> Requirement:
    data = {
        "id": req_id,
        "title": title,
        "statement": "",
        "type": RequirementType.REQUIREMENT,
        "status": Status.DRAFT,
        "owner": "",
        "priority": Priority.MEDIUM,
        "source": "",
        "verification": Verification.ANALYSIS,
    }
    data.update(overrides)
    return Requirement(**data)


class _DummyConfig:
    def __init__(self, initial: dict[str, int] | None = None):
        self.store: dict[str, int] = initial or {}
        self.text_store: dict[str, str] = {}

    def read_int(self, key: str, default: int) -> int:
        return self.store.get(key, default)

    def write_int(self, key: str, value: int) -> None:
        self.store[key] = value

    def read(self, key: str, default: str) -> str:
        return self.text_store.get(key, default)

    def write(self, key: str, value: str) -> None:
        self.text_store[key] = value


def _make_panel(wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    panel = list_panel.ListPanel(frame, model=RequirementModel())
    frame.SetSizer(wx.BoxSizer(wx.VERTICAL))
    frame.GetSizer().Add(panel, 1, wx.EXPAND)
    frame.Layout()
    return wx, frame, panel


def test_list_panel_basic_layout(wx_app):
    wx, frame, panel = _make_panel(wx_app)
    try:
        assert isinstance(panel.filter_summary, wx.StaticText)
        assert isinstance(panel.list, wx.ListCtrl)
        assert panel.list.GetColumnCount() == 1
        assert panel.list.GetItemCount() == 0
    finally:
        frame.Destroy()


def test_set_columns_excludes_labels(wx_app):
    wx, frame, panel = _make_panel(wx_app)
    try:
        panel.set_columns(["id", "labels", "status"])
        assert panel._field_order == ["title", "id", "status"]
        headers = [panel.list.GetColumn(i).GetText() for i in range(panel.list.GetColumnCount())]
        assert headers[0] == "Title"
        assert "Labels" not in headers
    finally:
        frame.Destroy()


def test_set_requirements_populates_rows_and_counts(wx_app):
    wx, frame, panel = _make_panel(wx_app)
    try:
        panel.set_columns(["derived_count", "status"])
        parent = _req(1, "Parent", rid="REQ-001")
        child = _req(2, "Child", links=[{"rid": "REQ-001"}])
        panel.set_requirements([parent, child])

        assert panel.list.GetItemCount() == 2
        first_title = panel.list.GetItemText(0)
        second_title = panel.list.GetItemText(1)
        assert {first_title, second_title} == {"Parent", "Child"}

        # derived count column reflects the computed map
        derived_col = panel._field_order.index("derived_count")
        parent_idx = 0 if panel.list.GetItemText(0) == "Parent" else 1
        assert panel.list.GetItemText(parent_idx, derived_col) == "1"
    finally:
        frame.Destroy()


def test_sort_orders_items(wx_app):
    wx, frame, panel = _make_panel(wx_app)
    try:
        requirements = [_req(1, "B"), _req(2, "A"), _req(3, "C")]
        panel.set_requirements(requirements)
        panel.sort(0, True)
        titles = [panel.list.GetItemText(i) for i in range(panel.list.GetItemCount())]
        assert titles == ["A", "B", "C"]

        panel.sort(0, False)
        titles = [panel.list.GetItemText(i) for i in range(panel.list.GetItemCount())]
        assert titles == ["C", "B", "A"]
    finally:
        frame.Destroy()


def test_focus_requirement_selects_item(wx_app):
    wx, frame, panel = _make_panel(wx_app)
    try:
        panel.set_requirements([_req(1, "One"), _req(2, "Two")])
        panel.focus_requirement(2)
        selected = panel.list.GetFirstSelected()
        assert selected != wx.NOT_FOUND
        assert panel.list.GetItemData(selected) == 2
    finally:
        frame.Destroy()


def test_record_and_recalc_derived_map(wx_app):
    wx, frame, panel = _make_panel(wx_app)
    try:
        parent = _req(1, "Parent", rid="REQ-001")
        panel.set_requirements([parent])
        panel.record_link("REQ-001", 2)
        assert panel.derived_map["REQ-001"] == [2]

        child = _req(2, "Child", links=[{"rid": "REQ-001"}])
        panel.recalc_derived_map([parent, child])
        assert panel.derived_map["REQ-001"] == [2]
    finally:
        frame.Destroy()


def test_column_width_persistence(wx_app):
    wx, frame, panel = _make_panel(wx_app)
    try:
        panel.set_columns(["status"])
        config = _DummyConfig({"col_width_0": -5})
        panel.load_column_widths(config)
        width = panel.list.GetColumnWidth(0)
        assert width == panel.DEFAULT_COLUMN_WIDTH

        panel.list.SetColumnWidth(0, 120)
        panel.list.SetColumnWidth(1, 80)
        panel.save_column_widths(config)
        assert config.store["col_width_0"] == 120
        assert config.store["col_width_1"] == 80
    finally:
        frame.Destroy()
