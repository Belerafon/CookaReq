"""Tests for the document tree widget."""

from __future__ import annotations

import importlib
import sys
import types

import pytest

from app.core.document_store import Document


def _build_wx_stub() -> types.SimpleNamespace:
    class TreeItemId:
        def __init__(self, node: dict | None = None):
            self.node = node

        def IsOk(self) -> bool:
            return self.node is not None

    class Window:
        _next_id = 1000

        def __init__(self, parent=None):
            self._parent = parent
            self._bindings: dict = {}

        @classmethod
        def NewControlId(cls) -> int:
            cls._next_id += 1
            return cls._next_id

        def Bind(self, event, handler, **kwargs) -> None:  # pragma: no cover - stub
            self._bindings[event] = handler

        def GetParent(self):  # pragma: no cover - stub
            return self._parent

    class Panel(Window):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._sizer = None

        def SetSizer(self, sizer) -> None:  # pragma: no cover - stub
            self._sizer = sizer

    class BoxSizer:
        def __init__(self, orient):
            self.children: list = []

        def Add(self, window, proportion, flag, border=0) -> None:  # pragma: no cover - stub
            self.children.append(window)

    class MenuItem:
        def __init__(self, item_id: int, label: str):
            self._id = item_id
            self.label = label
            self.enabled = True

        def Enable(self, enable: bool) -> None:  # pragma: no cover - stub
            self.enabled = bool(enable)

        def GetId(self) -> int:  # pragma: no cover - stub
            return self._id

    class Menu:
        def __init__(self):
            self.items: list[MenuItem] = []
            self.destroyed = False

        def Append(self, item_id: int, label: str) -> MenuItem:
            item = MenuItem(item_id, label)
            self.items.append(item)
            return item

        def Destroy(self) -> None:
            self.destroyed = True

    class TreeCtrl(Window):
        def __init__(self, parent=None, style: int = 0):
            super().__init__(parent)
            self.style = style
            self._selection = TreeItemId()
            self._root: TreeItemId | None = None
            self._last_menu: Menu | None = None

        def AddRoot(self, label: str) -> TreeItemId:
            node = {"label": label, "children": []}
            self._root = TreeItemId(node)
            return self._root

        def DeleteChildren(self, item: TreeItemId) -> None:
            if item.IsOk():
                item.node["children"].clear()

        def AppendItem(self, parent: TreeItemId, label: str) -> TreeItemId:
            node = {"label": label, "children": []}
            item = TreeItemId(node)
            parent.node["children"].append(item)
            return item

        def ExpandAll(self) -> None:  # pragma: no cover - stub
            pass

        def SelectItem(self, item: TreeItemId) -> None:
            self._selection = item

        def EnsureVisible(self, item: TreeItemId) -> None:  # pragma: no cover - stub
            self._ensure_visible = item

        def GetSelection(self) -> TreeItemId:
            return self._selection

        def PopupMenu(self, menu: Menu) -> None:
            self._last_menu = menu

        def HitTest(self, pt):
            return TreeItemId(), 0

        def ScreenToClient(self, pt):  # pragma: no cover - stub
            return pt

    class TreeEvent:
        def __init__(self, item=None):
            self._item = item

        def GetItem(self):
            return self._item

        def Skip(self):  # pragma: no cover - stub
            pass

    class ContextMenuEvent:
        def __init__(self, pos=None):
            self._pos = pos
            self.skipped: bool | None = None

        def GetPosition(self):
            return self._pos

        def Skip(self, flag=True):
            self.skipped = flag

    return types.SimpleNamespace(
        Panel=Panel,
        TreeCtrl=TreeCtrl,
        Menu=Menu,
        MenuItem=MenuItem,
        BoxSizer=BoxSizer,
        Window=Window,
        TreeEvent=TreeEvent,
        ContextMenuEvent=ContextMenuEvent,
        EVT_TREE_SEL_CHANGED=object(),
        EVT_TREE_ITEM_MENU=object(),
        EVT_MENU=object(),
        EVT_CONTEXT_MENU=object(),
        VERTICAL=0,
        EXPAND=0,
        TR_DEFAULT_STYLE=0x01,
        TR_HIDE_ROOT=0x02,
    )


@pytest.fixture
def document_tree_module(monkeypatch):
    wx_stub = _build_wx_stub()
    monkeypatch.setitem(sys.modules, "wx", wx_stub)
    module = importlib.import_module("app.ui.document_tree")
    module = importlib.reload(module)
    try:
        yield wx_stub, module
    finally:
        sys.modules.pop("app.ui.document_tree", None)


def test_document_tree_hides_placeholder_root(document_tree_module):
    wx_stub, module = document_tree_module
    parent = wx_stub.Panel(None)
    tree = module.DocumentTree(parent)
    assert tree.tree.style & wx_stub.TR_HIDE_ROOT


def test_background_context_menu_targets_root(document_tree_module, monkeypatch):
    wx_stub, module = document_tree_module
    parent = wx_stub.Panel(None)
    tree = module.DocumentTree(parent)
    called: list[tuple[object, bool]] = []

    def recorder(item, *, allow_selection_fallback=True):
        called.append((item, allow_selection_fallback))

    monkeypatch.setattr(tree, "_show_menu_for_item", recorder)
    event = wx_stub.ContextMenuEvent(pos=(0, 0))
    tree._show_background_menu(event)
    assert called == [(None, False)]
    assert event.skipped is False


def test_root_context_keeps_existing_selection(document_tree_module):
    wx_stub, module = document_tree_module
    parent = wx_stub.Panel(None)
    tree = module.DocumentTree(parent)
    docs = {
        "SYS": Document(prefix="SYS", title="System", digits=3),
    }
    tree.set_documents(docs)
    node = tree._node_for_prefix["SYS"]
    tree.tree.SelectItem(node)
    tree._show_menu_for_item(None, allow_selection_fallback=False)
    assert tree.tree.GetSelection() is node


def test_document_tree_ignores_invalid_selection(document_tree_module):
    wx_stub, module = document_tree_module
    parent = wx_stub.Panel(None)
    selected: list[str] = []

    tree = module.DocumentTree(parent, on_select=selected.append)
    event = wx_stub.TreeEvent()
    tree._handle_select(event)

    assert selected == []
