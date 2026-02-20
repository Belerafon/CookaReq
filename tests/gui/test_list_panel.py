"""Tests for list panel."""

import importlib
import json
import types

import pytest

from app import columns
from app.core.document_store import Document, item_path, save_document, save_item
from app.core.model import (
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
)
from app.services.requirements import RequirementsService

pytestmark = pytest.mark.gui
pytest_plugins = ("tests.gui.wx_stub_utils",)

def _req(req_id: int, title: str, **kwargs) -> Requirement:
    base = {
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
    base.update(kwargs)
    return Requirement(**base)


def test_list_panel_has_filter_and_list(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    wx_stub = env.wx
    panel = env.create_panel()

    assert isinstance(panel.filter_btn, wx_stub.Button)
    assert isinstance(panel.reset_btn, wx_stub.BitmapButton)
    assert isinstance(panel.list, wx_stub.ListCtrl)
    assert panel.filter_btn.GetParent() is panel
    assert panel.reset_btn.GetParent() is panel
    assert panel.list.GetParent() is panel
    assert not panel.reset_btn.IsShown()

    sizer = panel.GetSizer()
    children = [child.GetWindow() for child in sizer.GetChildren()]
    assert len(children) == 2
    btn_row = children[0]
    assert isinstance(btn_row, wx_stub.BoxSizer)
    inner = [child.GetWindow() for child in btn_row.GetChildren()]
    assert inner == [panel.filter_btn, panel.reset_btn, panel.filter_summary]
    assert children[1] is panel.list


def test_column_click_sorts(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    panel = env.create_panel()
    panel.set_columns(["id"])
    panel.set_requirements(
        [
            _req(2, "B"),
            _req(1, "A"),
        ],
    )

    panel._on_col_click(types.SimpleNamespace(GetColumn=lambda: 0))
    assert [r.id for r in panel.model.get_visible()] == [1, 2]

    panel._on_col_click(types.SimpleNamespace(GetColumn=lambda: 1))
    assert [r.id for r in panel.model.get_visible()] == [1, 2]

    panel._on_col_click(types.SimpleNamespace(GetColumn=lambda: 1))
    assert [r.id for r in panel.model.get_visible()] == [2, 1]


def test_column_click_after_set_columns_triggers_sort(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    wx_stub = env.wx
    panel = env.create_panel()
    panel.set_columns(["id"])
    panel.set_requirements(
        [
            _req(2, "B"),
            _req(1, "A"),
        ],
    )

    handler = panel.list.get_bound_handler(wx_stub.EVT_LIST_COL_CLICK)
    handler(types.SimpleNamespace(GetColumn=lambda: 1))
    assert [r.id for r in panel.model.get_visible()] == [1, 2]


def test_search_and_label_filters(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    panel = env.create_panel()
    panel.set_requirements(
        [
            _req(1, "Login", labels=["ui"]),
            _req(2, "Export", labels=["report"]),
        ],
    )

    panel.set_label_filter(["ui"])
    assert [r.id for r in panel.model.get_visible()] == [1]

    panel.set_label_filter([])
    panel.set_search_query("Export", fields=["title"])
    assert [r.id for r in panel.model.get_visible()] == [2]

    panel.set_label_filter(["ui"])
    panel.set_search_query("Export", fields=["title"])
    assert panel.model.get_visible() == []


def test_apply_filters(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    panel = env.create_panel()
    panel.set_requirements(
        [
            _req(1, "Login", labels=["ui"], owner="alice"),
            _req(2, "Export", labels=["report"], owner="bob"),
        ],
    )

    panel.apply_filters({"labels": ["ui"]})
    assert [r.id for r in panel.model.get_visible()] == [1]

    panel.apply_filters({"labels": [], "field_queries": {"owner": "bob"}})
    assert [r.id for r in panel.model.get_visible()] == [2]


def test_reset_button_visibility(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    panel = env.create_panel()
    assert not panel.reset_btn.IsShown()
    panel.set_search_query("X")
    assert panel.reset_btn.IsShown()
    panel.reset_filters()
    assert not panel.reset_btn.IsShown()


def test_apply_status_filter(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    panel = env.create_panel()
    panel.set_requirements(
        [
            _req(1, "A", status=Status.DRAFT),
            _req(2, "B", status=Status.APPROVED),
        ],
    )

    panel.apply_filters({"status": "approved"})
    assert [r.id for r in panel.model.get_visible()] == [2]
    panel.apply_filters({"status": None})
    assert [r.id for r in panel.model.get_visible()] == [1, 2]


def test_labels_column_uses_imagelist(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    panel = env.create_panel()
    panel.set_columns(["labels"])
    panel.set_requirements([
        _req(1, "A", labels=["ui", "backend"]),
    ])
    labels_col = panel._field_order.index("labels")
    title_col = panel._field_order.index("title")
    # labels column uses main image slot when placed at index 0
    if labels_col == 0:
        assert panel.list._item_images[0] >= 0
        assert panel.list._col_images.get((0, title_col), -1) == -1
    else:
        assert panel.list._col_images[(0, labels_col)] >= 0
        assert panel.list._item_images[0] == -1


def test_statement_column_shows_plain_preview(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    panel = env.create_panel()
    panel.set_columns(["statement"])
    statement = (
        "Intro **bold** text with [link](https://example.com) and more "
        + ("A" * 200)
    )
    panel.set_requirements([_req(1, "Title", statement=statement)])

    statement_col = panel._field_order.index("statement")
    display = panel.list.GetItem(0, statement_col).GetText()

    assert "**" not in display
    assert "bold" in display
    assert "link" in display
    assert len(display) <= panel.STATEMENT_PREVIEW_LIMIT
    assert display.endswith("…")


def test_label_imagelist_handles_resizes(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    wx_stub = env.wx
    panel = env.create_panel()
    panel.set_columns(["labels"])

    # initial narrow label
    panel.set_requirements([_req(1, "A", labels=["aa"])])
    first_w, first_h = panel.list.GetImageList(wx_stub.IMAGE_LIST_SMALL).GetSize()
    assert first_w > 0
    assert first_h > 0
    assert panel._label_images[("aa",)] == 0

    # introduce wider label, which should resize the list but keep the first image
    panel.set_requirements(
        [
            _req(1, "A", labels=["aa"]),
            _req(2, "B", labels=["averylonglabelhere"]),
        ]
    )
    second_w, second_h = panel.list.GetImageList(wx_stub.IMAGE_LIST_SMALL).GetSize()
    assert second_w >= first_w
    assert second_h >= first_h
    assert panel._label_images[("aa",)] >= 0
    assert panel._label_images[("averylonglabelhere",)] >= 0

    # add a shorter label after resizing to ensure padding works
    panel.set_requirements(
        [
            _req(1, "A", labels=["aa"]),
            _req(2, "B", labels=["averylonglabelhere"]),
            _req(3, "C", labels=["mid"]),
        ]
    )
    third_w, third_h = panel.list.GetImageList(wx_stub.IMAGE_LIST_SMALL).GetSize()
    assert third_w == second_w
    assert third_h == second_h
    assert panel._label_images[("mid",)] >= 0

    labels_col = panel._field_order.index("labels")
    for row in range(3):
        if labels_col == 0:
            assert panel.list._item_images[row] >= 0
        else:
            assert panel.list._col_images[(row, labels_col)] >= 0


def test_label_image_add_failure_falls_back_to_text(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    wx_stub = env.wx
    panel = env.create_panel()
    panel.set_columns(["labels"])
    panel.set_requirements([_req(1, "A", labels=["aa"])])

    # ensure next addition triggers fallback
    panel._label_images.clear()
    panel._image_list = panel.list.GetImageList(wx_stub.IMAGE_LIST_SMALL)

    def fail_add(_bmp):
        return -1

    panel._image_list.Add = fail_add
    panel.set_requirements([_req(2, "B", labels=["bb"])])

    labels_col = panel._field_order.index("labels")
    if labels_col == 0:
        assert panel.list._item_images[0] == -1
        assert panel.list._items[0] == "bb"
    else:
        assert panel.list._col_images[(0, labels_col)] == -1
        assert panel.list._cells[(0, labels_col)] == "bb"
        assert panel.list._item_images[0] == -1
    assert panel._label_images[("bb",)] == -1


def test_sort_by_labels(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    panel = env.create_panel()
    panel.set_columns(["labels"])
    panel.set_requirements(
        [
            _req(1, "A", labels=["beta"]),
            _req(2, "B", labels=["alpha"]),
        ],
    )

    panel.sort(0, True)
    assert [r.id for r in panel.model.get_visible()] == [2, 1]


def test_sort_by_multiple_labels(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    panel = env.create_panel()
    panel.set_columns(["labels"])
    panel.set_requirements(
        [
            _req(1, "A", labels=["alpha", "zeta"]),
            _req(2, "B", labels=["alpha", "beta"]),
        ],
    )

    panel.sort(0, True)
    assert [r.id for r in panel.model.get_visible()] == [2, 1]


def test_bulk_edit_updates_requirements(stubbed_list_panel_env, monkeypatch):
    env = stubbed_list_panel_env
    panel = env.create_panel()
    panel.set_columns(["revision"])
    reqs = [
        _req(1, "A", revision=1),
        _req(2, "B", revision=1),
    ]
    panel.set_requirements(reqs)
    monkeypatch.setattr(panel, "_get_selected_indices", lambda: [0, 1])
    monkeypatch.setattr(panel, "_prompt_value", lambda field: "2")
    panel._on_edit_field(1)
    assert [r.revision for r in reqs] == [2, 2]


def test_context_edit_saves_to_disk(
    stubbed_list_panel_env, monkeypatch, tmp_path
):
    env = stubbed_list_panel_env
    requirement_model_cls = env.requirement_model_cls
    documents_controller_cls = importlib.import_module(
        "app.ui.controllers.documents",
    ).DocumentsController

    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    original = _req(1, "Base", owner="alice")
    save_item(doc_dir, doc, original.to_mapping())

    model = requirement_model_cls()
    controller = documents_controller_cls(RequirementsService(tmp_path), model)
    controller.load_documents()
    derived_map = controller.load_items("SYS")

    panel = env.create_panel(model=model, docs_controller=controller)
    panel.set_columns(["owner"])
    panel.set_active_document("SYS")
    panel.set_requirements(model.get_all(), derived_map)

    monkeypatch.setattr(panel, "_get_selected_indices", lambda: [0])
    monkeypatch.setattr(panel, "_prompt_value", lambda field: "bob")

    panel._on_edit_field(1)

    data_path = item_path(doc_dir, doc, 1)
    with data_path.open(encoding="utf-8") as fh:
        stored = json.load(fh)

    assert stored["owner"] == "bob"




def test_context_edit_statement_syncs_revision_in_model_and_list(
    stubbed_list_panel_env, monkeypatch, tmp_path
):
    env = stubbed_list_panel_env
    requirement_model_cls = env.requirement_model_cls
    documents_controller_cls = importlib.import_module(
        "app.ui.controllers.documents",
    ).DocumentsController

    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    original = _req(1, "Base", statement="original", revision=1)
    save_item(doc_dir, doc, original.to_mapping())

    model = requirement_model_cls()
    controller = documents_controller_cls(RequirementsService(tmp_path), model)
    controller.load_documents()
    derived_map = controller.load_items("SYS")

    panel = env.create_panel(model=model, docs_controller=controller)
    panel.set_columns(["statement", "revision"])
    panel.set_active_document("SYS")
    panel.set_requirements(model.get_all(), derived_map)

    monkeypatch.setattr(panel, "_get_selected_indices", lambda: [0])
    monkeypatch.setattr(panel, "_prompt_value", lambda field: "updated statement")

    panel._on_edit_field(1)

    data_path = item_path(doc_dir, doc, 1)
    with data_path.open(encoding="utf-8") as fh:
        stored = json.load(fh)

    assert stored["statement"] == "updated statement"
    assert stored["revision"] == 2

    saved_req = model.get_by_id(1, doc_prefix="SYS")
    assert saved_req is not None
    assert saved_req.revision == 2
    assert panel.list.GetItem(0, 2).GetText() == "2"

def test_sort_method_and_callback(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    calls = []
    panel = env.create_panel(on_sort_changed=lambda c, a: calls.append((c, a)))
    panel.set_columns(["id"])
    panel.set_requirements(
        [
            _req(2, "B"),
            _req(1, "A"),
        ],
    )

    panel.sort(1, True)
    assert [r.id for r in panel.model.get_visible()] == [1, 2]
    assert calls[-1] == (1, True)

    panel.sort(1, False)
    assert [r.id for r in panel.model.get_visible()] == [2, 1]
    assert calls[-1] == (1, False)


def test_reorder_columns(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    panel = env.create_panel()
    list_panel_module = env.list_panel_module
    panel.set_columns(["id", "status", "priority"])
    panel.reorder_columns(1, 3)
    assert panel.columns == ["status", "priority", "id"]
    _ = list_panel_module._
    field_label = list_panel_module.locale.field_label
    assert panel.list._cols == [
        _("Title"),
        field_label("status"),
        field_label("priority"),
        field_label("id"),
    ]


def test_load_column_widths_assigns_defaults(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    panel = env.create_panel()
    panel.set_columns(["labels", "id", "status", "priority"])

    config = types.SimpleNamespace(
        get_column_width=lambda index, default=-1: default,
    )
    panel.load_column_widths(config)

    assert panel.list._col_widths == {
        0: columns.default_column_width("labels"),
        1: columns.default_column_width("title"),
        2: columns.default_column_width("id"),
        3: columns.default_column_width("status"),
        4: columns.default_column_width("priority"),
    }
