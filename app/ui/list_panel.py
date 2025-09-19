"""Simplified requirements list panel built on top of wx.ListCtrl."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

import wx

from ..core.document_store import LabelDef
from ..core.model import Requirement
from ..i18n import _
from . import locale
from .helpers import dip
from .requirement_model import RequirementModel

if TYPE_CHECKING:
    from ..config import ConfigManager
    from .controllers import DocumentsController


class ListPanel(wx.Panel):
    """Lightweight wrapper around :class:`wx.ListCtrl` for debugging."""

    MIN_COL_WIDTH = 60
    DEFAULT_COLUMN_WIDTH = 160
    DEFAULT_COLUMN_WIDTHS: dict[str, int] = {
        "title": 340,
        "labels": 200,
        "id": 90,
        "status": 140,
        "priority": 130,
        "type": 150,
        "owner": 180,
        "doc_prefix": 140,
        "rid": 150,
        "derived_count": 120,
        "derived_from": 260,
        "modified_at": 180,
    }

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

        self.columns: list[str] = []
        self._field_order: list[str] = ["title"]
        self._labels: list[LabelDef] = []
        self.current_filters: dict[str, Any] = {}
        self.derived_map: dict[str, list[int]] = {}
        self._current_doc_prefix: str | None = None
        self._after_refresh_callback: Callable[["ListPanel"], None] | None = None
        self._sort_column: int = 0
        self._sort_ascending: bool = True

        padding = dip(self, 4)
        sizer = wx.BoxSizer(wx.VERTICAL)
        button_row = wx.BoxSizer(wx.HORIZONTAL)

        self.filter_btn = wx.Button(self, label=_("Filters"))
        self.filter_btn.Disable()
        self.reset_btn = wx.Button(self, label=_("Reset"))
        self.reset_btn.Hide()
        self.filter_summary = wx.StaticText(self, label="")

        button_row.Add(self.filter_btn, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, padding)
        button_row.Add(self.reset_btn, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, padding)
        button_row.Add(self.filter_summary, 0, wx.ALIGN_CENTER_VERTICAL, 0)

        list_style = wx.LC_REPORT | wx.LC_SINGLE_SEL
        self.list = wx.ListCtrl(self, style=list_style)

        sizer.Add(button_row, 0, wx.EXPAND | wx.ALL, padding)
        sizer.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, padding)
        self.SetSizer(sizer)

        self.list.Bind(wx.EVT_LIST_COL_CLICK, self._on_col_click)
        self.list.Bind(wx.EVT_SIZE, self._on_list_resize)

        self._setup_columns()
        self._populate_list()

    # ------------------------------------------------------------------
    # public API expected by the rest of the application
    # ------------------------------------------------------------------
    def set_handlers(
        self,
        *,
        on_clone: Callable[[int], None] | None = None,
        on_delete: Callable[[int], None] | None = None,
        on_delete_many: Callable[[Sequence[int]], None] | None = None,
        on_derive: Callable[[int], None] | None = None,
    ) -> None:
        if on_clone is not None:
            self._on_clone = on_clone
        if on_delete is not None:
            self._on_delete = on_delete
        if on_delete_many is not None:
            self._on_delete_many = on_delete_many
        if on_derive is not None:
            self._on_derive = on_derive

    def set_after_refresh_callback(
        self, callback: Callable[["ListPanel"], None] | None
    ) -> None:
        self._after_refresh_callback = callback

    def set_documents_controller(
        self, controller: DocumentsController | None
    ) -> None:
        self._docs_controller = controller

    def set_active_document(self, prefix: str | None) -> None:
        self._current_doc_prefix = prefix

    def set_columns(self, fields: list[str]) -> None:
        unique: list[str] = []
        for field in fields:
            if field == "title":
                continue
            if field not in unique:
                unique.append(field)
        self.columns = unique
        self._setup_columns()
        self._populate_list()

    def load_column_widths(self, config: ConfigManager) -> None:
        for index in range(self.list.GetColumnCount()):
            width = config.read_int(f"col_width_{index}", -1)
            if width <= 0:
                field = self._field_order[index]
                width = self._default_column_width(field)
            width = max(self.MIN_COL_WIDTH, width)
            try:
                self.list.SetColumnWidth(index, width)
            except Exception:
                continue

    def save_column_widths(self, config: ConfigManager) -> None:
        for index in range(self.list.GetColumnCount()):
            width = self.list.GetColumnWidth(index)
            config.write_int(f"col_width_{index}", int(width))

    def load_column_order(self, config: ConfigManager) -> None:
        order_raw = config.read("col_order", "")
        if not order_raw:
            return
        requested = [name for name in order_raw.split(",") if name in self._field_order]
        if not requested:
            return
        order: list[int] = [self._field_order.index(name) for name in requested]
        for index in range(self.list.GetColumnCount()):
            if index not in order:
                order.append(index)
        try:
            self.list.SetColumnsOrder(order)
        except Exception:
            return

    def save_column_order(self, config: ConfigManager) -> None:
        try:
            order = self.list.GetColumnsOrder()
        except Exception:
            return
        names = [self._field_order[index] for index in order if index < len(self._field_order)]
        config.write("col_order", ",".join(names))

    def reorder_columns(self, from_col: int, to_col: int) -> None:
        offset = 1  # keep Title at index 0
        if from_col == to_col or from_col < offset or to_col < offset:
            return
        fields = list(self.columns)
        src = from_col - offset
        dst = to_col - offset
        if src < 0 or dst < 0 or src >= len(fields) or dst >= len(fields):
            return
        field = fields.pop(src)
        fields.insert(dst, field)
        self.set_columns(fields)

    def set_requirements(
        self,
        requirements: Sequence[Requirement],
        derived_map: dict[str, list[int]] | None = None,
    ) -> None:
        self.model.set_requirements(list(requirements))
        if derived_map is not None:
            self.derived_map = {str(key): list(value) for key, value in derived_map.items()}
        else:
            self.derived_map = self._build_derived_map(self.model.get_all())
        self._populate_list()

    def recalc_derived_map(self, requirements: Sequence[Requirement]) -> None:
        self.derived_map = self._build_derived_map(requirements)
        self._populate_list()

    def record_link(self, parent_rid: str, child_id: int) -> None:
        rid = str(parent_rid or "")
        if not rid:
            return
        children = self.derived_map.setdefault(rid, [])
        if child_id not in children:
            children.append(child_id)

    def refresh(self, select_id: int | None = None) -> None:
        self._populate_list(select_id=select_id)

    def sort(self, column: int, ascending: bool) -> None:
        if column < 0 or column >= len(self._field_order):
            return
        field = self._field_order[column]
        self._sort_column = column
        self._sort_ascending = ascending
        self.model.sort(field, ascending)
        self._populate_list()
        if self._on_sort_changed:
            self._on_sort_changed(column, ascending)

    def apply_filters(self, filters: dict[str, Any]) -> None:
        self.current_filters = dict(filters)
        self._update_filter_summary()
        self._toggle_reset_button()

    def set_label_filter(self, labels: list[str]) -> None:
        self.apply_filters({"labels": list(labels)})

    def set_search_query(self, query: str, fields: Sequence[str] | None = None) -> None:
        payload: dict[str, Any] = {"query": query}
        if fields is not None:
            payload["fields"] = list(fields)
        self.apply_filters(payload)

    def update_labels_list(self, labels: list[LabelDef]) -> None:
        self._labels = list(labels)

    def reset_filters(self) -> None:
        self.current_filters = {}
        self._update_filter_summary()
        self._toggle_reset_button()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _setup_columns(self) -> None:
        self.list.ClearAll()
        self._field_order = ["title"] + list(self.columns)
        for index, field in enumerate(self._field_order):
            label = _("Title") if index == 0 else locale.field_label(field)
            self.list.InsertColumn(index, label)
            width = self._default_column_width(field)
            try:
                self.list.SetColumnWidth(index, max(self.MIN_COL_WIDTH, width))
            except Exception:
                continue

    def _populate_list(self, *, select_id: int | None = None) -> None:
        items = list(self.model.get_visible())
        self.list.DeleteAllItems()
        for row, req in enumerate(items):
            title = self._format_cell(req, "title")
            index = self.list.InsertItem(row, title)
            req_id = getattr(req, "id", 0)
            try:
                numeric_id = int(req_id)
            except (TypeError, ValueError):
                numeric_id = 0
            self.list.SetItemData(index, numeric_id)
            for offset, field in enumerate(self._field_order[1:], start=1):
                value = self._format_cell(req, field)
                self.list.SetItem(index, offset, value)
        if select_id is not None:
            self._select_by_id(select_id)
        self.list.Refresh()
        self.list.Update()
        if self._after_refresh_callback:
            self._after_refresh_callback(self)

    def _select_by_id(self, req_id: int) -> None:
        for row in range(self.list.GetItemCount()):
            if self.list.GetItemData(row) == req_id:
                self.list.Select(row)
                self.list.EnsureVisible(row)
                break

    def _default_column_width(self, field: str) -> int:
        return self.DEFAULT_COLUMN_WIDTHS.get(field, self.DEFAULT_COLUMN_WIDTH)

    def _format_cell(self, req: Requirement, field: str) -> str:
        value = getattr(req, field, "") if field != "title" else getattr(req, "title", "")
        if value is None:
            return ""
        if field == "labels":
            if isinstance(value, (list, tuple, set)):
                return ", ".join(str(item) for item in value)
            return str(value)
        if field == "derived_count":
            rid = getattr(req, "rid", "")
            return str(len(self.derived_map.get(str(rid), [])))
        if field == "derived_from":
            links = getattr(req, "links", []) or []
            readable: list[str] = []
            for link in links:
                readable.append(str(getattr(link, "rid", link)))
            return ", ".join(readable)
        if field in {"status", "priority", "type"}:
            try:
                code = getattr(value, "value", value)
                return locale.code_to_label(field, code)
            except Exception:
                return str(value)
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(item) for item in value)
        return str(value)

    def _build_derived_map(
        self, requirements: Sequence[Requirement]
    ) -> dict[str, list[int]]:
        mapping: dict[str, list[int]] = {}
        for req in requirements:
            links = getattr(req, "links", []) or []
            for link in links:
                rid = str(getattr(link, "rid", link))
                if not rid:
                    continue
                mapping.setdefault(rid, []).append(getattr(req, "id", 0))
        return mapping

    def _update_filter_summary(self) -> None:
        if not self.current_filters:
            self.filter_summary.SetLabel("")
            return
        fragments: list[str] = []
        query = self.current_filters.get("query")
        if query:
            fragments.append(_("Query") + f": {query}")
        labels = self.current_filters.get("labels") or []
        if labels:
            fragments.append(_("Labels") + ": " + ", ".join(map(str, labels)))
        status = self.current_filters.get("status")
        if status:
            fragments.append(_("Status") + f": {status}")
        self.filter_summary.SetLabel("; ".join(fragments))

    def _toggle_reset_button(self) -> None:
        if self.current_filters:
            self.reset_btn.Show()
        else:
            self.reset_btn.Hide()
        try:
            self.Layout()
        except Exception:
            pass

    def _on_col_click(self, event: wx.ListEvent) -> None:  # pragma: no cover - GUI event
        column = event.GetColumn()
        ascending = not self._sort_ascending if column == self._sort_column else True
        self.sort(column, ascending)
        event.Skip()

    def _on_list_resize(self, event: wx.SizeEvent) -> None:  # pragma: no cover - GUI event
        self.list.Refresh()
        self.list.Update()
        event.Skip()
