import sys
import types
import importlib


def _build_wx_stub():
    class Window:
        def __init__(self, parent=None):
            self._parent = parent
        def GetParent(self):
            return self._parent
        def Bind(self, event, handler):
            pass

    class Panel(Window):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._sizer = None
        def SetSizer(self, sizer):
            self._sizer = sizer
        def GetSizer(self):
            return self._sizer

    class SearchCtrl(Window):
        pass

    class ListCtrl(Window):
        def __init__(self, parent=None, style=0):
            super().__init__(parent)
            self._items = []
        def InsertColumn(self, col, heading):
            pass
        def ClearAll(self):
            self._items.clear()
        def DeleteAllItems(self):
            self._items.clear()
        def GetItemCount(self):
            return len(self._items)
        def InsertItem(self, index, text):
            self._items.insert(index, text)
            return index
        def SetItem(self, index, col, text):
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

    return types.SimpleNamespace(
        Panel=Panel,
        SearchCtrl=SearchCtrl,
        ListCtrl=ListCtrl,
        BoxSizer=BoxSizer,
        Window=Window,
        VERTICAL=0,
        EXPAND=0,
        ALL=0,
        LC_REPORT=0,
        EVT_LIST_ITEM_RIGHT_CLICK=types.SimpleNamespace(),
        EVT_LIST_COL_CLICK=types.SimpleNamespace(),
        Config=Config,
    )


def test_list_panel_has_search_and_list(monkeypatch):
    wx_stub = _build_wx_stub()
    monkeypatch.setitem(sys.modules, "wx", wx_stub)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame)

    assert isinstance(panel.search, wx_stub.SearchCtrl)
    assert isinstance(panel.list, wx_stub.ListCtrl)
    assert panel.search.GetParent() is panel
    assert panel.list.GetParent() is panel

    sizer = panel.GetSizer()
    children = [child.GetWindow() for child in sizer.GetChildren()]
    assert children == [panel.search, panel.list]


def test_column_click_sorts(monkeypatch):
    wx_stub = _build_wx_stub()
    monkeypatch.setitem(sys.modules, "wx", wx_stub)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    ListPanel = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = ListPanel(frame)
    panel.set_columns(["id"])
    panel.set_requirements([
        {"id": "2", "title": "B"},
        {"id": "1", "title": "A"},
    ])

    panel._on_col_click(types.SimpleNamespace(GetColumn=lambda: 0))
    assert [r["id"] for r in panel._requirements] == ["1", "2"]

    panel._on_col_click(types.SimpleNamespace(GetColumn=lambda: 1))
    assert [r["id"] for r in panel._requirements] == ["1", "2"]

    panel._on_col_click(types.SimpleNamespace(GetColumn=lambda: 1))
    assert [r["id"] for r in panel._requirements] == ["2", "1"]
