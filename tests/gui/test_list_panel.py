"""Regression-focused tests for :mod:`app.ui.list_panel`."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from app.core.model import Priority, Requirement, RequirementType, Status, Verification
from app.ui.requirement_model import RequirementModel

REQUIRES_GUI = True


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


def _reload_list_panel(flags=None):
    import app.ui.list_panel as list_panel

    module = importlib.reload(list_panel)
    if flags is not None:
        module.set_feature_flags(flags)
    return module


def _make_panel(wx_app, *, flags=None):
    wx = pytest.importorskip("wx")
    list_panel = _reload_list_panel(flags)
    frame = wx.Frame(None)
    panel = list_panel.ListPanel(frame, model=RequirementModel())
    frame.SetSizer(wx.BoxSizer(wx.VERTICAL))
    frame.GetSizer().Add(panel, 1, wx.EXPAND)
    frame.Layout()
    return wx, frame, panel, list_panel


def test_list_panel_basic_layout(wx_app):
    wx, frame, panel, _module = _make_panel(wx_app)
    try:
        assert panel.filter_btn.GetLabel() == "Filters"
        assert not panel.reset_btn.IsShown()
        assert panel.filter_summary.GetLabel() == ""
        assert panel.list.GetColumnCount() == 1
        assert panel.list.GetColumn(0).GetText() == "Title"
    finally:
        frame.Destroy()
        wx_app.Yield()


def test_set_columns_includes_labels_column(wx_app):
    wx, frame, panel, _module = _make_panel(wx_app)
    try:
        panel.set_columns(["labels", "status", "priority"])
        headers = [panel.list.GetColumn(i).GetText() for i in range(panel.list.GetColumnCount())]
        assert headers[:2] == ["Labels", "Title"]
        assert panel._field_order[:2] == ["labels", "title"]
        assert "status" in panel._field_order
    finally:
        frame.Destroy()
        wx_app.Yield()


def test_set_requirements_populates_rows_and_counts(wx_app):
    wx, frame, panel, _module = _make_panel(wx_app)
    try:
        panel.set_columns(["labels", "derived_count", "status"])
        parent = _req(1, "Parent", rid="REQ-001", labels=["One", "Two"])
        child = _req(2, "Child", links=[SimpleNamespace(rid="REQ-001")])
        panel.set_requirements([parent, child])

        title_idx = panel._field_order.index("title")
        titles = [panel.list.GetItemText(i, title_idx) for i in range(panel.list.GetItemCount())]
        assert "Parent" in titles
        assert any(title.endswith("Child") for title in titles)

        parent_row = next(i for i, title in enumerate(titles) if title == "Parent")
        derived_col = panel._field_order.index("derived_count")
        assert panel.list.GetItemText(parent_row, derived_col) == "1"

        labels_text = panel.list.GetItemText(parent_row, 0)
        assert labels_text == "One, Two"
    finally:
        frame.Destroy()
        wx_app.Yield()


def test_sort_orders_items(wx_app):
    wx, frame, panel, _module = _make_panel(wx_app)
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
        wx_app.Yield()


def test_labels_render_as_text_without_bitmaps(wx_app):
    wx, frame, panel, _module = _make_panel(wx_app)
    try:
        panel.set_columns(["labels"])
        panel.set_requirements([_req(1, "T1", labels=["Red", "Blue"])])
        assert panel.list.GetItemText(0, 0) == "Red, Blue"
        assert panel.list.GetItem(0).GetImage() == -1
    finally:
        frame.Destroy()
        wx_app.Yield()


def test_labels_use_bitmaps_when_enabled(wx_app):
    wx = pytest.importorskip("wx")
    module = _reload_list_panel()
    flags = module.ListPanelFeatureFlags(label_bitmaps=True)
    wx, frame, panel, _ = _make_panel(wx_app, flags=flags)
    try:
        panel.set_columns(["labels"])
        panel.set_requirements([_req(1, "T1", labels=["Alpha", "Beta"])])
        item = panel.list.GetItem(0)
        assert item.GetImage() >= 0
        # When bitmaps are used the textual fallback should be cleared
        assert panel.list.GetItemText(0, 0) == ""
    finally:
        frame.Destroy()
        wx_app.Yield()


def test_filter_summary_updates_and_reset_button(wx_app):
    wx, frame, panel, _module = _make_panel(wx_app)
    try:
        panel.apply_filters({"status": Status.DRAFT.value, "labels": ["UI"], "match_any": True})
        summary = panel.filter_summary.GetLabel()
        assert "Status" in summary
        assert "Labels" in summary
        assert panel.reset_btn.IsShown()

        panel.reset_filters()
        assert panel.filter_summary.GetLabel() == ""
        assert not panel.reset_btn.IsShown()
    finally:
        frame.Destroy()
        wx_app.Yield()
