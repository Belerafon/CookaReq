import pytest

from app.core.doc_store import LabelDef
from app.ui.filter_dialog import FilterDialog

pytestmark = pytest.mark.gui


def _make_dialog(wx_app):
    labels = [
        LabelDef(key="foo", title="Foo", color="#000000"),
        LabelDef(key="bar", title="Bar", color="#ffffff"),
    ]
    values = {
        "query": "search",
        "field_queries": {"title": "abc"},
        "labels": ["foo", "bar"],
        "match_any": True,
        "status": "draft",
        "is_derived": True,
        "has_derived": True,
    }
    return FilterDialog(None, labels=labels, values=values)


def test_clear_button_resets_all_filters(wx_app):
    dlg = _make_dialog(wx_app)
    dlg._on_clear(None)
    assert dlg.get_filters() == {
        "query": "",
        "labels": [],
        "match_any": False,
        "status": None,
        "is_derived": False,
        "has_derived": False,
        "field_queries": {},
    }
    dlg.Destroy()
