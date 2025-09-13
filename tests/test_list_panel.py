"""Tests for list panel."""

import sys
import types
import importlib

from app.core.model import Requirement, RequirementType, Status, Priority, Verification
from app.core.labels import Label


def _build_wx_stub():
    class Window:
        def __init__(self, parent=None):
            self._parent = parent
            self._bindings = {}
        def GetParent(self):
            return self._parent
        def Bind(self, event, handler):
            self._bindings[event] = handler

        # helper for tests
        def get_bound_handler(self, event):
            return self._bindings.get(event)

    class Panel(Window):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._sizer = None
        def SetSizer(self, sizer):
            self._sizer = sizer
        def GetSizer(self):
            return self._sizer

    class SearchCtrl(Window):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._value = ""
        def SetValue(self, value):
            self._value = value
        def GetValue(self):
            return self._value

    class TextCtrl(SearchCtrl):
        pass

    class ComboCtrl(SearchCtrl):
        pass

    class CheckBox(Window):
        def __init__(self, parent=None, label=""):
            super().__init__(parent)
            self._value = False
        def SetValue(self, value):
            self._value = bool(value)
        def GetValue(self):
            return self._value

    class Button(Window):
        def __init__(self, parent=None, label=""):
            super().__init__(parent)
            self._label = label
        def GetLabel(self):
            return self._label

    class Dialog(Window):
        def __init__(self, parent=None, title=""):
            super().__init__(parent)
            self._title = title
        def CreateButtonSizer(self, flags):
            return BoxSizer(0)
        def SetSizerAndFit(self, sizer):
            self._sizer = sizer
        def ShowModal(self):
            return 0
        def Destroy(self):
            pass

    class CheckListBox(Window):
        def __init__(self, parent=None, choices=None):
            super().__init__(parent)
            self._choices = choices or []
            self._checked: set[int] = set()
        def GetCount(self):
            return len(self._choices)
        def IsChecked(self, idx):
            return idx in self._checked
        def Check(self, idx, check=True):
            if check:
                self._checked.add(idx)
            else:
                self._checked.discard(idx)

    class StaticText(Window):
        def __init__(self, parent=None, label=""):
            super().__init__(parent)
            self.label = label

    class _BaseList(Window):
        def __init__(self, parent=None, style=0):
            super().__init__(parent)
            self._items = []
            self._data = []
            self._cols = []
        def InsertColumn(self, col, heading):
            if col >= len(self._cols):
                self._cols.extend([None] * (col - len(self._cols) + 1))
            self._cols[col] = heading
        def ClearAll(self):
            self._items.clear()
            self._data.clear()
            self._cols.clear()
        def DeleteAllItems(self):
            self._items.clear()
            self._data.clear()
        def GetItemCount(self):
            return len(self._items)
        def GetColumnCount(self):
            return len(self._cols)
        def InsertStringItem(self, index, text):
            self._items.insert(index, text)
            self._data.insert(index, 0)
            return index
        def SetStringItem(self, index, col, text):
            pass
        def SetItemData(self, index, data):
            self._data[index] = data
        def GetItemData(self, index):
            return self._data[index]
        def HitTest(self, pt):
            return -1, 0
        def HitTestSubItem(self, pt):
            return -1, 0, -1

    class UltimateListItem:
        def __init__(self):
            self._id = 0
            self._col = 0
            self._text = ""
            self._renderer = None
        def SetId(self, value):
            self._id = value
        def GetId(self):
            return self._id
        def SetColumn(self, value):
            self._col = value
        def GetColumn(self):
            return self._col
        def SetText(self, text):
            self._text = text
        def GetText(self):
            return self._text
        def SetCustomRenderer(self, rend):
            self._renderer = rend
        def GetCustomRenderer(self):
            return self._renderer

    class UltimateListCtrl(_BaseList):
        def __init__(self, parent=None, agwStyle=0, **kwargs):
            super().__init__(parent)
        def SetItem(self, item):
            pass

    class ListCtrl(_BaseList):
        # kept for compatibility if needed elsewhere
        pass

    class BoxSizer:
        def __init__(self, orient):
            self._children = []
        def Add(self, window, proportion, flag, border):
            self._children.append(window)
        def GetChildren(self):
            return [types.SimpleNamespace(GetWindow=lambda w=child: w) for child in self._children]

    class Config:
        def ReadInt(self, key, default):
            return default
        def WriteInt(self, key, value):
            pass

    wx_mod = types.SimpleNamespace(
        Panel=Panel,
        SearchCtrl=SearchCtrl,
        TextCtrl=TextCtrl,
        ComboCtrl=ComboCtrl,
        CheckBox=CheckBox,
        Button=Button,
        Dialog=Dialog,
        CheckListBox=CheckListBox,
        StaticText=StaticText,
        ListCtrl=ListCtrl,
        BoxSizer=BoxSizer,
        Window=Window,
        VERTICAL=0,
        EXPAND=0,
        ALL=0,
        OK=1,
        CANCEL=2,
        EVT_BUTTON=object(),
        LC_REPORT=0,
        EVT_LIST_ITEM_RIGHT_CLICK=object(),
        EVT_CONTEXT_MENU=object(),
        EVT_LIST_COL_CLICK=object(),
        EVT_TEXT=object(),
        EVT_CHECKBOX=object(),
        Config=Config,
        ContextMenuEvent=types.SimpleNamespace,
    )
    class ColumnSorterMixin:
        def __init__(self, *args, **kwargs):
            ctrl = self.GetListCtrl()
            ctrl.Bind(wx_mod.EVT_LIST_COL_CLICK, self._mixin_col_click)

        def _mixin_col_click(self, event):
            # default mixin handler does nothing in stub
            pass

    mixins_mod = types.SimpleNamespace(ColumnSorterMixin=ColumnSorterMixin)
    ulc_mod = types.SimpleNamespace(
        UltimateListCtrl=UltimateListCtrl,
        UltimateListItem=UltimateListItem,
        ULC_REPORT=0,
    )
    return wx_mod, mixins_mod, ulc_mod


def _req(id: int, title: str, **kwargs) -> Requirement:
    base = dict(
        id=id,
        title=title,
        statement="",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="",
        priority=Priority.MEDIUM,
        source="",
        verification=Verification.ANALYSIS,
    )
    base.update(kwargs)
    return Requirement(**base)


def test_list_panel_has_filter_and_list(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    model_module = importlib.import_module("app.ui.requirement_model")
    importlib.reload(model_module)
    ListPanel = list_panel_module.ListPanel
    RequirementModel = model_module.RequirementModel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame, model=RequirementModel())

    assert isinstance(panel.filter_btn, wx_stub.Button)
    assert isinstance(panel.list, ulc.UltimateListCtrl)
    assert panel.filter_btn.GetParent() is panel
    assert panel.list.GetParent() is panel

    sizer = panel.GetSizer()
    children = [child.GetWindow() for child in sizer.GetChildren()]
    assert children == [panel.filter_btn, panel.list]


def test_column_click_sorts(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    RequirementModel = importlib.import_module("app.ui.requirement_model").RequirementModel
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame, model=RequirementModel())
    panel.set_columns(["id"])
    panel.set_requirements([
        _req(2, "B"),
        _req(1, "A"),
    ])

    panel._on_col_click(types.SimpleNamespace(GetColumn=lambda: 0))
    assert [r.id for r in panel.model.get_visible()] == [1, 2]

    panel._on_col_click(types.SimpleNamespace(GetColumn=lambda: 1))
    assert [r.id for r in panel.model.get_visible()] == [1, 2]

    panel._on_col_click(types.SimpleNamespace(GetColumn=lambda: 1))
    assert [r.id for r in panel.model.get_visible()] == [2, 1]


def test_column_click_after_set_columns_triggers_sort(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    RequirementModel = importlib.import_module("app.ui.requirement_model").RequirementModel
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame, model=RequirementModel())
    panel.set_columns(["id"])
    panel.set_requirements([
        _req(2, "B"),
        _req(1, "A"),
    ])

    handler = panel.list.get_bound_handler(wx_stub.EVT_LIST_COL_CLICK)
    handler(types.SimpleNamespace(GetColumn=lambda: 1))
    assert [r.id for r in panel.model.get_visible()] == [1, 2]


def test_search_and_label_filters(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    RequirementModel = importlib.import_module("app.ui.requirement_model").RequirementModel
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame, model=RequirementModel())
    panel.set_requirements([
        _req(1, "Login", labels=["ui"]),
        _req(2, "Export", labels=["report"]),
    ])

    panel.set_label_filter(["ui"])
    assert [r.id for r in panel.model.get_visible()] == [1]

    panel.set_label_filter([])
    panel.set_search_query("Export", fields=["title"])
    assert [r.id for r in panel.model.get_visible()] == [2]

    panel.set_label_filter(["ui"])
    panel.set_search_query("Export", fields=["title"])
    assert panel.model.get_visible() == []


def test_apply_filters(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    RequirementModel = importlib.import_module("app.ui.requirement_model").RequirementModel
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame, model=RequirementModel())
    panel.set_requirements([
        _req(1, "Login", labels=["ui"], owner="alice"),
        _req(2, "Export", labels=["report"], owner="bob"),
    ])

    panel.apply_filters({"labels": ["ui"]})
    assert [r.id for r in panel.model.get_visible()] == [1]

    panel.apply_filters({"labels": [], "field_queries": {"owner": "bob"}})
    assert [r.id for r in panel.model.get_visible()] == [2]


def test_apply_status_filter(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    RequirementModel = importlib.import_module("app.ui.requirement_model").RequirementModel
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame, model=RequirementModel())
    panel.set_requirements([
        _req(1, "A", status=Status.DRAFT),
        _req(2, "B", status=Status.APPROVED),
    ])

    panel.apply_filters({"status": "approved"})
    assert [r.id for r in panel.model.get_visible()] == [2]
    panel.apply_filters({"status": None})
    assert [r.id for r in panel.model.get_visible()] == [1, 2]


def test_labels_column_renders_joined(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    RequirementModel = importlib.import_module("app.ui.requirement_model").RequirementModel
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame, model=RequirementModel())
    panel.set_columns(["labels"])

    captured: list[object] = []
    panel.list.SetItem = lambda item: captured.append(item)
    panel.set_requirements([
        _req(1, "A", labels=["ui", "backend"]),
    ])

    item = next((i for i in captured if i.GetColumn() == 1), None)
    assert item is not None
    renderer = item.GetCustomRenderer()
    assert renderer is not None
    assert renderer.labels == ["ui", "backend"]


def test_labels_column_uses_colors(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    RequirementModel = importlib.import_module("app.ui.requirement_model").RequirementModel
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame, model=RequirementModel())
    panel.update_labels_list([Label("ui", "#123456")])
    panel.set_columns(["labels"])

    captured: list[object] = []
    panel.list.SetItem = lambda item: captured.append(item)
    panel.set_requirements([_req(1, "A", labels=["ui"])])

    item = next((i for i in captured if i.GetColumn() == 1), None)
    renderer = item.GetCustomRenderer()
    assert renderer.colors["ui"] == "#123456"


def test_sort_by_labels(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    RequirementModel = importlib.import_module("app.ui.requirement_model").RequirementModel
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame, model=RequirementModel())
    panel.set_columns(["labels"])
    panel.set_requirements([
        _req(1, "A", labels=["beta"]),
        _req(2, "B", labels=["alpha"]),
    ])

    panel.sort(1, True)
    assert [r.id for r in panel.model.get_visible()] == [2, 1]


def test_sort_by_multiple_labels(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    RequirementModel = importlib.import_module("app.ui.requirement_model").RequirementModel
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame, model=RequirementModel())
    panel.set_columns(["labels"])
    panel.set_requirements([
        _req(1, "A", labels=["alpha", "zeta"]),
        _req(2, "B", labels=["alpha", "beta"]),
    ])

    panel.sort(1, True)
    assert [r.id for r in panel.model.get_visible()] == [2, 1]


def test_bulk_edit_updates_requirements(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    RequirementModel = importlib.import_module("app.ui.requirement_model").RequirementModel
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame, model=RequirementModel())
    panel.set_columns(["version"])
    reqs = [
        _req(1, "A", version="1"),
        _req(2, "B", version="1"),
    ]
    panel.set_requirements(reqs)
    monkeypatch.setattr(panel, "_get_selected_indices", lambda: [0, 1])
    monkeypatch.setattr(panel, "_prompt_value", lambda field: "2")
    panel._on_edit_field(1)
    assert [r.version for r in reqs] == ["2", "2"]


def test_sort_method_and_callback(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    RequirementModel = importlib.import_module("app.ui.requirement_model").RequirementModel
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    calls = []
    panel = ListPanel(frame, model=RequirementModel(), on_sort_changed=lambda c, a: calls.append((c, a)))
    panel.set_columns(["id"])
    panel.set_requirements([
        _req(2, "B"),
        _req(1, "A"),
    ])

    panel.sort(1, True)
    assert [r.id for r in panel.model.get_visible()] == [1, 2]
    assert calls[-1] == (1, True)

    panel.sort(1, False)
    assert [r.id for r in panel.model.get_visible()] == [2, 1]
    assert calls[-1] == (1, False)
