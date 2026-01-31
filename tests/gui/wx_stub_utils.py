"""Shared helpers for GUI tests that stub out ``wx`` and related modules."""

from __future__ import annotations

import importlib
import sys
import types
from contextlib import contextmanager
from dataclasses import dataclass

import pytest


__all__ = [
    "build_wx_stub",
    "ListPanelTestEnv",
    "stub_list_panel_env",
    "stubbed_list_panel_env",
]


def build_wx_stub() -> tuple[types.SimpleNamespace, types.SimpleNamespace, types.SimpleNamespace]:
    """Build a lightweight ``wx`` replacement used by list panel tests."""

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
        def __init__(self, parent=None, label="", style=0):
            super().__init__(parent)
            self._label = label
            self._style = style

        def GetLabel(self):
            return self._label

        def GetWindowStyle(self):
            return self._style

    class BitmapButton(Button):
        def __init__(self, parent=None, bitmap=None, style=0):
            super().__init__(parent, style=style)
            self._bitmap = bitmap

        def GetBitmap(self):
            return self._bitmap

    class ArtProvider:
        @staticmethod
        def GetBitmap(*args, **kwargs):
            return Bitmap(ok=False)

    class Size:
        def __init__(self, width, height):
            self.width = width
            self.height = height

        def GetWidth(self):
            return self.width

        def GetHeight(self):
            return self.height

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
        def __init__(self, width=0, height=0, *, ok=True):
            self._w = width
            self._h = height
            self._ok = ok

        def GetWidth(self):
            return self._w

        def GetHeight(self):
            return self._h

        def IsOk(self):
            return self._ok

    class StaticBox(Window):
        def __init__(self, parent=None, label=""):
            super().__init__(parent)
            self._label = label

        def GetLabel(self):
            return self._label

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
            self._orient = orient

        def Add(self, window, proportion=0, flag=0, border=0, userData=None):
            self._children.append(window)
            return types.SimpleNamespace(window=window)

        def Prepend(self, window, proportion=0, flag=0, border=0, userData=None):
            self._children.insert(0, window)
            return types.SimpleNamespace(window=window)

        def Insert(self, index, window, proportion=0, flag=0, border=0, userData=None):
            if index >= len(self._children):
                self._children.append(window)
            else:
                self._children.insert(index, window)
            return types.SimpleNamespace(window=window)

        def GetChildren(self):
            return [
                types.SimpleNamespace(GetWindow=lambda w=child: w)
                for child in self._children
            ]

    class StaticBoxSizer(BoxSizer):
        def __init__(self, box, orient):
            super().__init__(orient)
            self._box = box

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
        StaticBox=StaticBox,
        StaticBoxSizer=StaticBoxSizer,
        Size=Size,
        BoxSizer=BoxSizer,
        Window=Window,
        VERTICAL=0,
        HORIZONTAL=1,
        EXPAND=0,
        ALL=0,
        LEFT=0x0004,
        ALIGN_CENTER_VERTICAL=0x0020,
        BU_EXACTFIT=0,
        BORDER_NONE=0,
        ART_CLOSE="close",
        ART_BUTTON="button",
        ART_COPY="copy",
        OK=1,
        CANCEL=2,
        EVT_BUTTON=object(),
        EVT_LEFT_DOWN=object(),
        EVT_LEFT_UP=object(),
        EVT_MOTION=object(),
        EVT_LEAVE_WINDOW=object(),
        EVT_KILL_FOCUS=object(),
        LC_REPORT=0,
        EVT_LIST_ITEM_RIGHT_CLICK=object(),
        EVT_CONTEXT_MENU=object(),
        EVT_LIST_COL_CLICK=object(),
        EVT_TEXT=object(),
        EVT_CHECKBOX=object(),
        IMAGE_LIST_SMALL=0,
        Config=Config,
        ContextMenuEvent=types.SimpleNamespace,
        Event=types.SimpleNamespace,
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


@dataclass
class ListPanelTestEnv:
    wx: types.SimpleNamespace
    mixins: types.SimpleNamespace
    agw: types.SimpleNamespace
    ulc: types.SimpleNamespace
    list_panel_module: types.ModuleType
    list_panel_cls: type
    requirement_model_module: types.ModuleType
    requirement_model_cls: type

    def create_panel(self, parent=None, model=None, **kwargs):
        frame = parent if parent is not None else self.wx.Panel(None)
        model_instance = model if model is not None else self.requirement_model_cls()
        return self.list_panel_cls(frame, model=model_instance, **kwargs)


@contextmanager
def stub_list_panel_env(monkeypatch: pytest.MonkeyPatch):
    """Context manager that installs ``wx`` stubs and yields a list panel env."""

    wx_stub, mixins, ulc = build_wx_stub()
    agw = types.SimpleNamespace(ultimatelistctrl=ulc)
    patched_modules = {
        "wx": wx_stub,
        "wx.lib.mixins.listctrl": mixins,
        "wx.lib.agw": agw,
        "wx.lib.agw.ultimatelistctrl": ulc,
    }
    for module_name, module in patched_modules.items():
        monkeypatch.setitem(sys.modules, module_name, module)

    list_panel_module = importlib.import_module("app.ui.list_panel")
    importlib.reload(list_panel_module)
    requirement_model_module = importlib.import_module("app.ui.requirement_model")
    importlib.reload(requirement_model_module)

    env = ListPanelTestEnv(
        wx=wx_stub,
        mixins=mixins,
        agw=agw,
        ulc=ulc,
        list_panel_module=list_panel_module,
        list_panel_cls=list_panel_module.ListPanel,
        requirement_model_module=requirement_model_module,
        requirement_model_cls=requirement_model_module.RequirementModel,
    )

    try:
        yield env
    finally:
        monkeypatch.undo()
        importlib.reload(importlib.import_module("app.ui.list_panel"))
        importlib.reload(importlib.import_module("app.ui.requirement_model"))


@pytest.fixture
def stubbed_list_panel_env(monkeypatch: pytest.MonkeyPatch):
    """Fixture that provides a ``ListPanelTestEnv`` with stubbed ``wx`` modules."""

    with stub_list_panel_env(monkeypatch) as env:
        yield env
