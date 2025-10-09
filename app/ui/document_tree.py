"""Panel displaying documents in a tree."""
from __future__ import annotations

from contextlib import suppress
from collections.abc import Callable

import wx

from ..services.requirements import Document
from ..i18n import _


class DocumentTree(wx.Panel):
    """Tree view of documents with selection callback."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_select: Callable[[str], None] | None = None,
        on_new_document: Callable[[str | None], None] | None = None,
        on_rename_document: Callable[[str], None] | None = None,
        on_delete_document: Callable[[str], None] | None = None,
    ) -> None:
        """Initialise the tree widget and wire optional callbacks."""
        super().__init__(parent)
        self._on_select = on_select
        self._on_new_document = on_new_document
        self._on_rename_document = on_rename_document
        self._on_delete_document = on_delete_document
        style = getattr(wx, "TR_DEFAULT_STYLE", 0) | getattr(wx, "TR_HIDE_ROOT", 0)
        self.tree = wx.TreeCtrl(self, style=style)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.tree, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self._node_for_prefix: dict[str, wx.TreeItemId] = {}
        self._prefix_for_id: dict[wx.TreeItemId, str] = {}
        self.root = self.tree.AddRoot(_("Documents"))
        self.tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._handle_select)
        self.tree.Bind(wx.EVT_TREE_ITEM_MENU, self._show_context_menu)
        if hasattr(wx, "EVT_CONTEXT_MENU"):
            self.tree.Bind(wx.EVT_CONTEXT_MENU, self._show_background_menu)
        self._menu_target_prefix: str | None = None

    def set_documents(self, docs: dict[str, Document]) -> None:
        """Populate tree from mapping ``docs``."""
        self.tree.DeleteChildren(self.root)
        self._node_for_prefix.clear()
        self._prefix_for_id.clear()

        def add(prefix: str) -> wx.TreeItemId:
            if prefix in self._node_for_prefix:
                return self._node_for_prefix[prefix]
            doc = docs[prefix]
            parent_id = self.root
            if doc.parent:
                parent_id = add(doc.parent)
            label = f"{doc.prefix}: {doc.title}" if doc.title else doc.prefix
            node = self.tree.AppendItem(parent_id, label)
            self._node_for_prefix[prefix] = node
            self._prefix_for_id[node] = prefix
            return node

        for prefix in sorted(docs):
            add(prefix)
        self.tree.ExpandAll()

    def select(self, prefix: str) -> None:
        """Select tree item corresponding to ``prefix`` if present."""
        node = self._node_for_prefix.get(prefix)
        if node:
            self.tree.SelectItem(node)
            self.tree.EnsureVisible(node)

    def get_selected_prefix(self) -> str | None:
        """Return prefix associated with the currently selected node."""
        item = self.tree.GetSelection()
        if not item.IsOk():
            return None
        return self._prefix_for_id.get(item)

    def _handle_select(self, event: wx.TreeEvent) -> None:
        item = event.GetItem()
        if not item or not getattr(item, "IsOk", lambda: False)():
            event.Skip()
            return
        prefix = self._prefix_for_id.get(item)
        if prefix and self._on_select:
            self._on_select(prefix)
        event.Skip()

    def _show_context_menu(self, event: wx.TreeEvent) -> None:
        self._show_menu_for_item(event.GetItem())

    def _show_menu_for_item(
        self,
        item: wx.TreeItemId | None,
        *,
        allow_selection_fallback: bool = True,
    ) -> None:
        target: wx.TreeItemId | None = None
        prefix: str | None = None
        if item and item.IsOk():
            prefix = self._prefix_for_id.get(item)
            if prefix:
                target = item
        if prefix is None and allow_selection_fallback:
            selected = self.tree.GetSelection()
            if selected and selected.IsOk():
                selected_prefix = self._prefix_for_id.get(selected)
                if selected_prefix:
                    target = selected
                    prefix = selected_prefix
        if target:
            self.tree.SelectItem(target)
        self._menu_target_prefix = prefix
        menu = wx.Menu()

        def _next_menu_id() -> int:
            if hasattr(wx, "ID_ANY"):
                return wx.ID_ANY
            if hasattr(wx, "Window") and hasattr(wx.Window, "NewControlId"):
                return wx.Window.NewControlId()
            # Fallback for extremely limited stubs.
            return -1

        new_item = menu.Append(_next_menu_id(), _("New document"))
        rename_item = menu.Append(_next_menu_id(), _("Rename"))
        delete_item = menu.Append(_next_menu_id(), _("Delete"))

        def _bind(item: wx.MenuItem, handler: Callable[[wx.CommandEvent], None]) -> None:
            if hasattr(menu, "Bind"):
                menu.Bind(wx.EVT_MENU, handler, item)
            else:  # pragma: no cover - exercised via stub in unit tests
                self.Bind(wx.EVT_MENU, handler, id=item.GetId())

        _bind(new_item, self._handle_menu_new)
        _bind(rename_item, self._handle_menu_rename)
        _bind(delete_item, self._handle_menu_delete)
        if self._on_new_document is None:
            new_item.Enable(False)
        if prefix is None or self._on_rename_document is None:
            rename_item.Enable(False)
        if prefix is None or self._on_delete_document is None:
            delete_item.Enable(False)
        self.tree.PopupMenu(menu)
        menu.Destroy()
        self._menu_target_prefix = None

    def _show_background_menu(self, event: wx.ContextMenuEvent) -> None:
        hit_item: wx.TreeItemId | None = None
        get_position = getattr(event, "GetPosition", None)
        hit_test = getattr(self.tree, "HitTest", None)
        if get_position and hit_test:
            pos = get_position()
            screen_to_client = getattr(self.tree, "ScreenToClient", None)
            if screen_to_client and pos is not None:
                with suppress(Exception):  # pragma: no cover - backend quirks
                    pos = screen_to_client(pos)
            hit = hit_test(pos)
            hit_item = hit[0] if isinstance(hit, tuple) else hit
            if hit_item and hasattr(hit_item, "IsOk") and hit_item.IsOk():
                if hasattr(event, "Skip"):
                    event.Skip()
                return
        if hasattr(event, "Skip"):
            event.Skip(False)
        self._show_menu_for_item(None, allow_selection_fallback=False)

    def _handle_menu_new(self, _event: wx.CommandEvent) -> None:
        if self._on_new_document is None:
            return
        parent_prefix = self._menu_target_prefix
        self._menu_target_prefix = None
        self._on_new_document(parent_prefix)

    def _handle_menu_rename(self, _event: wx.CommandEvent) -> None:
        if self._on_rename_document is None:
            return
        if self._menu_target_prefix is None:
            return
        prefix = self._menu_target_prefix
        self._menu_target_prefix = None
        self._on_rename_document(prefix)

    def _handle_menu_delete(self, _event: wx.CommandEvent) -> None:
        if self._on_delete_document is None:
            return
        if self._menu_target_prefix is None:
            return
        prefix = self._menu_target_prefix
        self._menu_target_prefix = None
        self._on_delete_document(prefix)
