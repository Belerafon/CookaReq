"""Panel displaying documents in a tree."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Dict

import wx

from ..core.doc_store import Document
from ..i18n import _


class DocumentTree(wx.Panel):
    """Tree view of documents with selection callback."""

    def __init__(self, parent: wx.Window, *, on_select: Callable[[str], None] | None = None) -> None:
        super().__init__(parent)
        self._on_select = on_select
        self.tree = wx.TreeCtrl(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.tree, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self._node_for_prefix: Dict[str, wx.TreeItemId] = {}
        self._prefix_for_id: Dict[wx.TreeItemId, str] = {}
        self.root = self.tree.AddRoot(_("Documents"))
        self.tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._handle_select)

    def set_documents(self, docs: Dict[str, Document]) -> None:
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

    def _handle_select(self, event: wx.TreeEvent) -> None:
        item = event.GetItem()
        prefix = self._prefix_for_id.get(item)
        if prefix and self._on_select:
            self._on_select(prefix)
        event.Skip()
