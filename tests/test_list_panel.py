import sys
import types
import importlib


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

    class ListCtrl(Window):
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
        def InsertItem(self, index, text):
            self._items.insert(index, text)
            self._data.insert(index, 0)
            return index
        def SetItem(self, index, col, text):
            pass
        def SetItemData(self, index, data):
            self._data[index] = data
        def GetItemData(self, index):
            return self._data[index]

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
        ListCtrl=ListCtrl,
        BoxSizer=BoxSizer,
        Window=Window,
        VERTICAL=0,
        EXPAND=0,
        ALL=0,
        LC_REPORT=0,
        EVT_LIST_ITEM_RIGHT_CLICK=object(),
        EVT_LIST_COL_CLICK=object(),
        EVT_TEXT=object(),
        Config=Config,
    )
    class ColumnSorterMixin:
        def __init__(self, *args, **kwargs):
            ctrl = self.GetListCtrl()
            ctrl.Bind(wx_mod.EVT_LIST_COL_CLICK, self._mixin_col_click)

        def _mixin_col_click(self, event):
            # default mixin handler does nothing in stub
            pass

    mixins_mod = types.SimpleNamespace(ColumnSorterMixin=ColumnSorterMixin)
    return wx_mod, mixins_mod


def test_list_panel_has_search_and_list(monkeypatch):
    wx_stub, mixins = _build_wx_stub()
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    model_module = importlib.import_module("app.ui.requirement_model")
    importlib.reload(model_module)
    ListPanel = list_panel_module.ListPanel
    RequirementModel = model_module.RequirementModel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame, model=RequirementModel())

    assert isinstance(panel.search, wx_stub.SearchCtrl)
    assert isinstance(panel.list, wx_stub.ListCtrl)
    assert panel.search.GetParent() is panel
    assert panel.list.GetParent() is panel

    sizer = panel.GetSizer()
    children = [child.GetWindow() for child in sizer.GetChildren()]
    assert children == [panel.search, panel.list]


def test_column_click_sorts(monkeypatch):
    wx_stub, mixins = _build_wx_stub()
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    RequirementModel = importlib.import_module("app.ui.requirement_model").RequirementModel
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame, model=RequirementModel())
    panel.set_columns(["id"])
    panel.set_requirements([
        {"id": 2, "title": "B"},
        {"id": 1, "title": "A"},
    ])

    panel._on_col_click(types.SimpleNamespace(GetColumn=lambda: 0))
    assert [r["id"] for r in panel.model.get_visible()] == [1, 2]

    panel._on_col_click(types.SimpleNamespace(GetColumn=lambda: 1))
    assert [r["id"] for r in panel.model.get_visible()] == [1, 2]

    panel._on_col_click(types.SimpleNamespace(GetColumn=lambda: 1))
    assert [r["id"] for r in panel.model.get_visible()] == [2, 1]


def test_column_click_after_set_columns_triggers_sort(monkeypatch):
    wx_stub, mixins = _build_wx_stub()
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    RequirementModel = importlib.import_module("app.ui.requirement_model").RequirementModel
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame, model=RequirementModel())
    panel.set_columns(["id"])
    panel.set_requirements([
        {"id": 2, "title": "B"},
        {"id": 1, "title": "A"},
    ])

    handler = panel.list.get_bound_handler(wx_stub.EVT_LIST_COL_CLICK)
    handler(types.SimpleNamespace(GetColumn=lambda: 1))
    assert [r["id"] for r in panel.model.get_visible()] == [1, 2]


def test_search_and_label_filters(monkeypatch):
    wx_stub, mixins = _build_wx_stub()
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    RequirementModel = importlib.import_module("app.ui.requirement_model").RequirementModel
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame, model=RequirementModel())
    panel.set_requirements([
        {"id": 1, "title": "Login", "labels": ["ui"]},
        {"id": 2, "title": "Export", "labels": ["report"]},
    ])

    panel.set_label_filter(["ui"])
    assert [r["id"] for r in panel.model.get_visible()] == [1]

    panel.set_label_filter([])
    panel.set_search_query("Export", fields=["title"])
    assert [r["id"] for r in panel.model.get_visible()] == [2]

    panel.set_label_filter(["ui"])
    panel.set_search_query("Export", fields=["title"])
    assert panel.model.get_visible() == []


def test_bulk_edit_updates_requirements(monkeypatch):
    wx_stub, mixins = _build_wx_stub()
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    RequirementModel = importlib.import_module("app.ui.requirement_model").RequirementModel
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame, model=RequirementModel())
    panel.set_columns(["version"])
    reqs = [
        {"id": 1, "title": "A", "version": "1"},
        {"id": 2, "title": "B", "version": "1"},
    ]
    panel.set_requirements(reqs)
    monkeypatch.setattr(panel, "_get_selected_indices", lambda: [0, 1])
    monkeypatch.setattr(panel, "_prompt_value", lambda field: "2")
    panel._on_edit_field(1)
    assert [r["version"] for r in reqs] == ["2", "2"]


def test_sort_method_and_callback(monkeypatch):
    wx_stub, mixins = _build_wx_stub()
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    RequirementModel = importlib.import_module("app.ui.requirement_model").RequirementModel
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    calls = []
    panel = ListPanel(frame, model=RequirementModel(), on_sort_changed=lambda c, a: calls.append((c, a)))
    panel.set_columns(["id"])
    panel.set_requirements([
        {"id": 2, "title": "B"},
        {"id": 1, "title": "A"},
    ])

    panel.sort(1, True)
    assert [r["id"] for r in panel.model.get_visible()] == [1, 2]
    assert calls[-1] == (1, True)

    panel.sort(1, False)
    assert [r["id"] for r in panel.model.get_visible()] == [2, 1]
    assert calls[-1] == (1, False)
