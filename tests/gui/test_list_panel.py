"""Tests for list panel."""

import importlib
import json
import sys
import types

import pytest

from app.core.document_store import Document, item_path, save_document, save_item
from app.core.model import (
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
    requirement_to_dict,
)

pytestmark = pytest.mark.gui


def _build_wx_stub():
    class Window:
        def __init__(self, parent=None):
            self._parent = parent
            self._bindings = {}
            self._shown = True
            self._tooltip = None

        def GetParent(self):
            return self._parent

        def Bind(self, event, handler):
            self._bindings[event] = handler

        def Show(self, show=True):
            self._shown = bool(show)

        def Hide(self):
            self._shown = False

        def IsShown(self):
            return self._shown

        def SetToolTip(self, tip):
            self._tooltip = tip

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

    class BitmapButton(Button):
        def __init__(self, parent=None, bitmap=None, style=0):
            super().__init__(parent)
            self._bitmap = bitmap

    class ArtProvider:
        @staticmethod
        def GetBitmap(*args, **kwargs):
            return object()

    class Font:
        pass

    class Colour:
        def __init__(self, *args, **kwargs):
            pass

    class Brush:
        def __init__(self, colour):
            self._colour = colour

    class Pen:
        def __init__(self, colour):
            self._colour = colour

    class Bitmap:
        def __init__(self, width, height):
            self._w = width
            self._h = height

        def GetWidth(self):
            return self._w

        def GetHeight(self):
            return self._h

    class MemoryDC:
        def __init__(self):
            self._bmp = None

        def SelectObject(self, bmp):
            self._bmp = bmp

        def SetFont(self, font):
            pass

        def SetBackground(self, brush):
            pass

        def Clear(self):
            pass

        def SetBrush(self, brush):
            pass

        def SetPen(self, pen):
            pass

        def DrawRectangle(self, x, y, w, h):
            pass

        def SetTextForeground(self, colour):
            pass

        def DrawText(self, text, x, y):
            pass

        def GetTextExtent(self, text):
            return (len(text) * 6, 10)

        def DrawBitmap(self, bmp, x, y, use_mask=False):
            pass

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
            self._imagelist = None
            self._col_images = {}
            self._item_images = []
            self._cells = {}
            self._col_widths = {}

        def InsertColumn(self, col, heading):
            if col >= len(self._cols):
                self._cols.extend([None] * (col - len(self._cols) + 1))
            self._cols[col] = heading

        def ClearAll(self):
            self._items.clear()
            self._data.clear()
            self._cols.clear()
            self._col_images.clear()
            self._item_images.clear()
            self._cells.clear()

        def DeleteAllItems(self):
            self._items.clear()
            self._data.clear()
            self._col_images.clear()
            self._item_images.clear()
            self._cells.clear()

        def GetItemCount(self):
            return len(self._items)

        def GetColumnCount(self):
            return len(self._cols)

        def InsertItem(self, index, text, image=-1):
            self._items.insert(index, text)
            self._data.insert(index, 0)
            self._item_images.insert(index, image)
            return index

        InsertStringItem = InsertItem

        def SetItem(self, index, col, text, image=-1):
            if col == 0:
                self._items[index] = text
            self._cells[(index, col)] = text

        SetStringItem = SetItem

        def SetItemData(self, index, data):
            self._data[index] = data

        def GetItemData(self, index):
            return self._data[index]

        def HitTest(self, pt):
            return -1, 0

        def HitTestSubItem(self, pt):
            return -1, 0, -1

        def SetItemColumnImage(self, index, col, img):
            self._col_images[(index, col)] = img

        def SetItemImage(self, index, img):
            if index >= len(self._item_images):
                self._item_images.extend([-1] * (index - len(self._item_images) + 1))
            self._item_images[index] = img

        def GetItem(self, index, col=0):
            text = self._items[index] if col == 0 else self._cells.get((index, col), "")
            img = (
                self._item_images[index]
                if col == 0
                else self._col_images.get((index, col), -1)
            )
            return types.SimpleNamespace(GetText=lambda: text, GetImage=lambda: img)

        def GetFont(self):
            return Font()

        def GetBackgroundColour(self):
            return Colour("#ffffff")

        def SetImageList(self, il, which):
            self._imagelist = il

        def GetImageList(self, which):
            return self._imagelist

        def SetColumnWidth(self, col, width):
            self._col_widths[col] = width

        def GetColumnWidth(self, col):
            return self._col_widths.get(col, 0)

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
        def __init__(self, parent=None, agw_style=0, **kwargs):
            super().__init__(parent)

        def SetItem(self, item):
            pass

    class ListCtrl(_BaseList):
        # kept for compatibility if needed elsewhere
        pass

    class ImageList:
        def __init__(self, width, height):
            self._w = width
            self._h = height
            self._images = []

        def Add(self, bmp):
            if bmp.GetWidth() != self._w or bmp.GetHeight() != self._h:
                raise ValueError("bitmap size mismatch")
            self._images.append(bmp)
            return len(self._images) - 1

        def GetSize(self):
            return self._w, self._h

        def GetImageCount(self):
            return len(self._images)

        def GetBitmap(self, idx):
            return self._images[idx]

    class BoxSizer:
        def __init__(self, orient):
            self._children = []

        def Add(self, window, proportion, flag, border):
            self._children.append(window)

        def GetChildren(self):
            return [
                types.SimpleNamespace(GetWindow=lambda w=child: w)
                for child in self._children
            ]

    class Config:
        def read_int(self, key, default):
            return default

        def write_int(self, key, value):
            pass

        def read(self, key, default=""):
            return default

        def write(self, key, value):
            pass

    wx_mod = types.SimpleNamespace(
        Panel=Panel,
        SearchCtrl=SearchCtrl,
        TextCtrl=TextCtrl,
        ComboCtrl=ComboCtrl,
        CheckBox=CheckBox,
        Button=Button,
        BitmapButton=BitmapButton,
        Dialog=Dialog,
        CheckListBox=CheckListBox,
        StaticText=StaticText,
        ListCtrl=ListCtrl,
        ImageList=ImageList,
        BoxSizer=BoxSizer,
        Window=Window,
        VERTICAL=0,
        EXPAND=0,
        ALL=0,
        BU_EXACTFIT=0,
        ART_CLOSE="close",
        ART_BUTTON="button",
        OK=1,
        CANCEL=2,
        EVT_BUTTON=object(),
        LC_REPORT=0,
        EVT_LIST_ITEM_RIGHT_CLICK=object(),
        EVT_CONTEXT_MENU=object(),
        EVT_LIST_COL_CLICK=object(),
        EVT_TEXT=object(),
        EVT_CHECKBOX=object(),
        IMAGE_LIST_SMALL=0,
        Config=Config,
        ContextMenuEvent=types.SimpleNamespace,
        ArtProvider=ArtProvider,
        Font=Font,
        Colour=Colour,
        Brush=Brush,
        Pen=Pen,
        Bitmap=Bitmap,
        MemoryDC=MemoryDC,
        NullBitmap=object(),
        BLACK=Colour(0, 0, 0),
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
    list_panel_cls = list_panel_module.ListPanel
    requirement_model_cls = model_module.RequirementModel

    frame = wx_stub.Panel(None)
    panel = list_panel_cls(frame, model=requirement_model_cls())

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


def test_column_click_sorts(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    requirement_model_cls = importlib.import_module(
        "app.ui.requirement_model",
    ).RequirementModel
    list_panel_cls = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = list_panel_cls(frame, model=requirement_model_cls())
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


def test_column_click_after_set_columns_triggers_sort(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    requirement_model_cls = importlib.import_module(
        "app.ui.requirement_model",
    ).RequirementModel
    list_panel_cls = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = list_panel_cls(frame, model=requirement_model_cls())
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


def test_search_and_label_filters(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    requirement_model_cls = importlib.import_module(
        "app.ui.requirement_model",
    ).RequirementModel
    list_panel_cls = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = list_panel_cls(frame, model=requirement_model_cls())
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


def test_apply_filters(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    requirement_model_cls = importlib.import_module(
        "app.ui.requirement_model",
    ).RequirementModel
    list_panel_cls = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = list_panel_cls(frame, model=requirement_model_cls())
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


def test_reset_button_visibility(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    requirement_model_cls = importlib.import_module(
        "app.ui.requirement_model",
    ).RequirementModel
    list_panel_cls = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = list_panel_cls(frame, model=requirement_model_cls())
    assert not panel.reset_btn.IsShown()
    panel.set_search_query("X")
    assert panel.reset_btn.IsShown()
    panel.reset_filters()
    assert not panel.reset_btn.IsShown()


def test_apply_status_filter(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    requirement_model_cls = importlib.import_module(
        "app.ui.requirement_model",
    ).RequirementModel
    list_panel_cls = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = list_panel_cls(frame, model=requirement_model_cls())
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


def test_labels_column_displays_plain_text(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    requirement_model_cls = importlib.import_module(
        "app.ui.requirement_model",
    ).RequirementModel
    list_panel_cls = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = list_panel_cls(frame, model=requirement_model_cls())
    panel.set_columns(["labels"])
    panel.set_requirements([
        _req(1, "A", labels=["ui", "backend"]),
    ])
    labels_col = panel._field_order.index("labels")
    title_col = panel._field_order.index("title")
    label_item = panel.list.GetItem(0, labels_col)
    assert label_item.GetText() == "ui, backend"
    assert label_item.GetImage() == -1
    title_item = panel.list.GetItem(0, title_col)
    assert title_item.GetText() == "A"
    assert title_item.GetImage() == -1


def test_labels_column_updates_text_on_refresh(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    requirement_model_cls = importlib.import_module(
        "app.ui.requirement_model",
    ).RequirementModel
    list_panel_cls = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = list_panel_cls(frame, model=requirement_model_cls())
    panel.set_columns(["labels"])

    panel.set_requirements([_req(1, "A", labels=["aa"])])
    labels_col = panel._field_order.index("labels")
    assert panel.list.GetItem(0, labels_col).GetText() == "aa"

    panel.set_requirements(
        [
            _req(1, "A", labels=["aa"]),
            _req(2, "B", labels=["averylonglabelhere"]),
        ]
    )
    assert panel.list.GetItem(0, labels_col).GetText() == "aa"
    assert panel.list.GetItem(1, labels_col).GetText() == "averylonglabelhere"

    panel.set_requirements(
        [
            _req(1, "A", labels=["aa"]),
            _req(2, "B", labels=["averylonglabelhere"]),
            _req(3, "C", labels=["mid"]),
        ]
    )
    assert panel.list.GetItem(2, labels_col).GetText() == "mid"
    for row in range(panel.list.GetItemCount()):
        item = panel.list.GetItem(row, labels_col)
        assert item.GetImage() == -1


def test_labels_column_handles_empty_values(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    requirement_model_cls = importlib.import_module(
        "app.ui.requirement_model",
    ).RequirementModel
    list_panel_cls = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = list_panel_cls(frame, model=requirement_model_cls())
    panel.set_columns(["labels"])
    panel.set_requirements(
        [
            _req(1, "A", labels=[]),
            _req(2, "B", labels=["bb"]),
        ]
    )

    labels_col = panel._field_order.index("labels")
    first_item = panel.list.GetItem(0, labels_col)
    assert first_item.GetText() == ""
    assert first_item.GetImage() == -1
    second_item = panel.list.GetItem(1, labels_col)
    assert second_item.GetText() == "bb"
    assert second_item.GetImage() == -1


def test_sort_by_labels(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    requirement_model_cls = importlib.import_module(
        "app.ui.requirement_model",
    ).RequirementModel
    list_panel_cls = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = list_panel_cls(frame, model=requirement_model_cls())
    panel.set_columns(["labels"])
    panel.set_requirements(
        [
            _req(1, "A", labels=["beta"]),
            _req(2, "B", labels=["alpha"]),
        ],
    )

    panel.sort(0, True)
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
    requirement_model_cls = importlib.import_module(
        "app.ui.requirement_model",
    ).RequirementModel
    list_panel_cls = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = list_panel_cls(frame, model=requirement_model_cls())
    panel.set_columns(["labels"])
    panel.set_requirements(
        [
            _req(1, "A", labels=["alpha", "zeta"]),
            _req(2, "B", labels=["alpha", "beta"]),
        ],
    )

    panel.sort(0, True)
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
    requirement_model_cls = importlib.import_module(
        "app.ui.requirement_model",
    ).RequirementModel
    list_panel_cls = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = list_panel_cls(frame, model=requirement_model_cls())
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


def test_context_edit_saves_to_disk(monkeypatch, tmp_path):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    requirement_model_cls = importlib.import_module(
        "app.ui.requirement_model",
    ).RequirementModel
    documents_controller_cls = importlib.import_module(
        "app.ui.controllers.documents",
    ).DocumentsController
    list_panel_cls = list_panel_module.ListPanel

    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    original = _req(1, "Base", owner="alice")
    save_item(doc_dir, doc, requirement_to_dict(original))

    model = requirement_model_cls()
    controller = documents_controller_cls(tmp_path, model)
    controller.load_documents()
    derived_map = controller.load_items("SYS")

    frame = wx_stub.Panel(None)
    panel = list_panel_cls(
        frame,
        model=model,
        docs_controller=controller,
    )
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


def test_sort_method_and_callback(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    requirement_model_cls = importlib.import_module(
        "app.ui.requirement_model",
    ).RequirementModel
    list_panel_cls = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    calls = []
    panel = list_panel_cls(
        frame,
        model=requirement_model_cls(),
        on_sort_changed=lambda c, a: calls.append((c, a)),
    )
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


def test_reorder_columns(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    requirement_model_cls = importlib.import_module(
        "app.ui.requirement_model",
    ).RequirementModel
    list_panel_cls = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = list_panel_cls(frame, model=requirement_model_cls())
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


def test_load_column_widths_assigns_defaults(monkeypatch):
    wx_stub, mixins, ulc = _build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    monkeypatch.setitem(sys.modules, "wx.lib.mixins.listctrl", mixins)
    monkeypatch.setitem(sys.modules, "wx.lib.agw", agw)
    monkeypatch.setitem(sys.modules, "wx.lib.agw.ultimatelistctrl", ulc)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    requirement_model_cls = importlib.import_module(
        "app.ui.requirement_model",
    ).RequirementModel
    list_panel_cls = list_panel_module.ListPanel

    frame = wx_stub.Panel(None)
    panel = list_panel_cls(frame, model=requirement_model_cls())
    panel.set_columns(["labels", "id", "status", "priority"])

    config = types.SimpleNamespace(read_int=lambda key, default: -1)
    panel.load_column_widths(config)

    assert panel.list._col_widths == {
        0: list_panel_cls.DEFAULT_COLUMN_WIDTHS["labels"],
        1: list_panel_cls.DEFAULT_COLUMN_WIDTHS["title"],
        2: list_panel_cls.DEFAULT_COLUMN_WIDTHS["id"],
        3: list_panel_cls.DEFAULT_COLUMN_WIDTHS["status"],
        4: list_panel_cls.DEFAULT_COLUMN_WIDTHS["priority"],
    }
