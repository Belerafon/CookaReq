"""Extremely reduced ListPanel used while debugging text rendering."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import suppress
from typing import TYPE_CHECKING

import wx

from ..core.model import Requirement
from ..i18n import _
from ..log import logger
from .requirement_model import RequirementModel

if TYPE_CHECKING:  # pragma: no cover - only used in type checking
    from ..config import ConfigManager
    from .controllers import DocumentsController
    from ..core.document_store import LabelDef


class ListPanel(wx.Panel):
    """Minimal text-only panel wrapping :class:`wx.ListCtrl`."""

    DEFAULT_COLUMN_WIDTH = 200

    def __init__(
        self,
        parent: wx.Window,
        *,
        model: RequirementModel | None = None,
        docs_controller: DocumentsController | None = None,
        on_clone: Callable[[int], None] | None = None,
        on_delete: Callable[[int], None] | None = None,
        on_delete_many: Callable[[Sequence[int]], None] | None = None,
        on_sort_changed: Callable[[int, bool], None] | None = None,
        on_derive: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(parent)

        self.model = model if model is not None else RequirementModel()
        self._docs_controller = docs_controller
        self._on_clone = on_clone
        self._on_delete = on_delete
        self._on_delete_many = on_delete_many
        self._on_sort_changed = on_sort_changed
        self._on_derive = on_derive

        self._field_order: list[str] = ["title"]
        self._sort_column = 0
        self._sort_ascending = True
        self._current_doc_prefix: str | None = None
        self.current_filters: dict[str, object] = {}
        self.filter_summary = None
        self.derived_map: dict[str, list[int]] = {}
        self._labels: list[LabelDef] = []

        self.list = wx.ListCtrl(
            self,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_NONE,
        )
        self.list.InsertColumn(0, _("Title"))

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.list, 1, wx.EXPAND)
        self.SetSizer(sizer)

        logger.info(
            "ListPanel running in ultra-minimal mode: only the Title column is rendered; "
            "filters, labels, context menus, and custom bitmaps are disabled to isolate "
            "text rendering issues.",
        )

    # ------------------------------------------------------------------
    # Basic compatibility helpers
    # ------------------------------------------------------------------
    def set_documents_controller(self, controller: DocumentsController | None) -> None:
        self._docs_controller = controller

    def set_active_document(self, prefix: str | None) -> None:
        self._current_doc_prefix = prefix

    def update_labels_list(self, labels: list[LabelDef]) -> None:
        self._labels = list(labels)

    # Columns -----------------------------------------------------------
    def _apply_columns(self) -> None:
        """Ensure the single Title column exists."""

        self.list.ClearAll()
        self.list.InsertColumn(0, _("Title"))

    def set_columns(self, fields: list[str]) -> None:  # pragma: no cover - trivial
        """Ignore column requests while debugging."""

        self._field_order = ["title"]
        self._apply_columns()
        self._refresh()

    def load_column_widths(self, config: ConfigManager) -> None:  # pragma: no cover
        width = config.read_int("col_width_0", self.DEFAULT_COLUMN_WIDTH)
        if width <= 0:
            width = self.DEFAULT_COLUMN_WIDTH
        self.list.SetColumnWidth(0, width)

    def save_column_widths(self, config: ConfigManager) -> None:  # pragma: no cover
        width = self.list.GetColumnWidth(0)
        if width <= 0:
            width = self.DEFAULT_COLUMN_WIDTH
        config.write_int("col_width_0", width)

    def load_column_order(self, config: ConfigManager) -> None:  # pragma: no cover
        _ = config.read("col_order", "title")

    def save_column_order(self, config: ConfigManager) -> None:  # pragma: no cover
        config.write("col_order", "title")

    def reorder_columns(self, from_col: int, to_col: int) -> None:  # pragma: no cover
        return

    # Data --------------------------------------------------------------
    def set_requirements(
        self,
        requirements: list[Requirement],
        derived_map: dict[str, list[int]] | None = None,
    ) -> None:
        self.model.set_requirements(requirements)
        self.derived_map = derived_map or {}
        self._refresh()

    def recalc_derived_map(self, requirements: list[Requirement]) -> None:
        derived: dict[str, list[int]] = {}
        for req in requirements:
            links = getattr(req, "links", []) or []
            for link in links:
                rid = self._link_rid(link)
                if not rid:
                    continue
                derived.setdefault(rid, []).append(req.id)
        self.derived_map = derived
        self._refresh()

    def record_link(self, parent_rid: str, child_id: int) -> None:
        self.derived_map.setdefault(parent_rid, []).append(child_id)

    def refresh(self, *, select_id: int | None = None) -> None:
        self._refresh()
        if select_id is not None:
            self.focus_requirement(select_id)

    def _refresh(self) -> None:
        try:
            items = list(self.model.get_visible())
        except Exception:  # pragma: no cover - defensive fallback
            items = []
        self.list.DeleteAllItems()
        for req in items:
            text = self._title_text(req)
            index = self.list.InsertItem(self.list.GetItemCount(), text)
            try:
                req_id = int(getattr(req, "id", 0))
            except (TypeError, ValueError):
                req_id = 0
            self.list.SetItemData(index, req_id)

    # Sorting -----------------------------------------------------------
    def sort(self, column: int, ascending: bool) -> None:
        self._sort_column = 0
        self._sort_ascending = ascending
        self.model.sort("title", ascending)
        self._refresh()
        if self._on_sort_changed:
            self._on_sort_changed(0, ascending)

    # Selection ---------------------------------------------------------
    def focus_requirement(self, req_id: int) -> None:
        target_index: int | None = None
        try:
            count = self.list.GetItemCount()
        except Exception:  # pragma: no cover - backend quirks
            return
        for idx in range(count):
            try:
                item_id = self.list.GetItemData(idx)
            except Exception:
                continue
            if item_id == req_id:
                target_index = idx
                break
        if target_index is None:
            return
        for idx in range(count):
            self._set_item_selected(idx, idx == target_index)
        if hasattr(self.list, "EnsureVisible"):
            with suppress(Exception):
                self.list.EnsureVisible(target_index)

    def _set_item_selected(self, index: int, selected: bool) -> None:
        select_flag = getattr(wx, "LIST_STATE_SELECTED", 0x0002)
        focus_flag = getattr(wx, "LIST_STATE_FOCUSED", 0x0001)
        mask = select_flag | focus_flag
        if hasattr(self.list, "SetItemState"):
            with suppress(Exception):
                self.list.SetItemState(index, mask if selected else 0, mask)
                return
        if hasattr(self.list, "Select"):
            try:
                self.list.Select(index, selected)
            except TypeError:
                if selected:
                    self.list.Select(index)
                else:
                    with suppress(Exception):
                        self.list.Select(index, False)
            except Exception:
                return
        if selected and hasattr(self.list, "Focus"):
            with suppress(Exception):
                self.list.Focus(index)

    # ------------------------------------------------------------------
    # Basic text helpers
    # ------------------------------------------------------------------
    def _link_rid(self, link: object) -> str:
        if isinstance(link, dict):
            value = link.get("rid") or link.get("id") or ""
            return str(value)
        value = getattr(link, "rid", link)
        if value is None:
            return ""
        return str(value)

    def _title_text(self, req: Requirement) -> str:
        title = getattr(req, "title", "")
        if title:
            return str(title)
        rid = getattr(req, "rid", None)
        if rid:
            return str(rid)
        identifier = getattr(req, "id", None)
        if identifier is not None:
            return str(identifier)
        return ""
