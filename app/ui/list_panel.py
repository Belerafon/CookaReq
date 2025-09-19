"""Text-first ListPanel used to debug missing text rendering."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import suppress
from enum import Enum
from typing import TYPE_CHECKING

import wx

from ..core.document_store import LabelDef
from ..core.model import Requirement
from ..i18n import _
from ..log import logger
from . import locale
from .enums import ENUMS
from .filter_dialog import FilterDialog
from .requirement_model import RequirementModel

if TYPE_CHECKING:  # pragma: no cover - runtime optional
    from ..config import ConfigManager
    from .controllers import DocumentsController


class ListPanel(wx.Panel):
    """List of requirements rendered strictly with text columns."""

    MIN_COL_WIDTH = 50
    MAX_COL_WIDTH = 1000
    DEFAULT_COLUMN_WIDTH = 200
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
        """Create stripped-down panel without custom bitmaps or styling."""

        super().__init__(parent)

        self.model = model if model is not None else RequirementModel()
        self._docs_controller = docs_controller
        self._on_clone = on_clone
        self._on_delete = on_delete
        self._on_delete_many = on_delete_many
        self._on_sort_changed = on_sort_changed
        self._on_derive = on_derive
        self.current_filters: dict[str, object] = {}
        self.derived_map: dict[str, list[int]] = {}
        self._labels: list[LabelDef] = []
        self._field_order: list[str] = ["title"]
        self._show_labels = False
        self.columns: list[str] = []
        self._sort_column = 0
        self._sort_ascending = True
        self._current_doc_prefix: str | None = None
        self._filter_dialog_factory: Callable[..., FilterDialog] = FilterDialog

        pad = max(self.FromDIP(6), 2)

        self.filter_btn = wx.Button(self, label=_("Filters"))
        self.reset_btn = wx.Button(self, label=_("Clear filters"))
        self.reset_btn.Hide()
        self.filter_summary = wx.StaticText(self, label="")

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        button_row.Add(self.filter_btn, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, pad)
        button_row.Add(self.reset_btn, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, pad)
        button_row.Add(self.filter_summary, 0, wx.ALIGN_CENTER_VERTICAL)

        self.list = wx.ListCtrl(
            self,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_NONE,
        )
        self._apply_columns()

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(button_row, 0, wx.EXPAND | wx.ALL, pad)
        main_sizer.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, pad)
        self.SetSizer(main_sizer)

        self.filter_btn.Bind(wx.EVT_BUTTON, self._on_filter_button)
        self.reset_btn.Bind(wx.EVT_BUTTON, self._on_reset_button)

        logger.info(
            "ListPanel running in text-only debug mode: Title column with optional "
            "plain-text extras; background inheritance, sub-item images, and "
            "label bitmaps stay disabled while investigating rendering issues.",
        )

    # ------------------------------------------------------------------
    # Integration helpers
    # ------------------------------------------------------------------
    def set_documents_controller(self, controller: DocumentsController | None) -> None:
        self._docs_controller = controller

    def set_active_document(self, prefix: str | None) -> None:
        self._current_doc_prefix = prefix

    def update_labels_list(self, labels: list[LabelDef]) -> None:
        self._labels = [LabelDef(lbl.key, lbl.title, lbl.color) for lbl in labels]

    # ------------------------------------------------------------------
    # Columns
    # ------------------------------------------------------------------
    def _apply_columns(self) -> None:
        """Create columns for title and all requested fields."""

        self.list.ClearAll()
        self._field_order = []

        column_index = 0
        if self._show_labels:
            self.list.InsertColumn(column_index, _("Labels"))
            self._field_order.append("labels")
            column_index += 1

        self.list.InsertColumn(column_index, _("Title"))
        self._field_order.append("title")
        column_index += 1

        for field in self.columns:
            if field in {"title", "labels"}:
                continue
            header = locale.field_label(field)
            self.list.InsertColumn(self.list.GetColumnCount(), header)
            self._field_order.append(field)

        for index, field in enumerate(self._field_order):
            default_width = self._default_column_width(field)
            with suppress(Exception):  # pragma: no cover - GUI quirks
                self.list.SetColumnWidth(index, default_width)

    def set_columns(self, fields: list[str]) -> None:
        """Register extra text columns, skipping rich label rendering for now."""

        sanitized: list[str] = []
        seen = {"title"}
        show_labels = False
        for field in fields:
            if not field:
                continue
            if field == "labels":
                show_labels = True
                continue
            if field in seen:
                continue
            sanitized.append(field)
            seen.add(field)
        self._show_labels = show_labels
        self.columns = sanitized
        self._apply_columns()
        self._refresh()

    def load_column_widths(self, config: ConfigManager) -> None:
        """Restore stored column widths with sensible bounds."""

        for index, field in enumerate(self._field_order):
            width = config.read_int(f"col_width_{index}", self._default_column_width(field))
            if width <= 0:
                width = self._default_column_width(field)
            width = max(self.MIN_COL_WIDTH, min(width, self.MAX_COL_WIDTH))
            with suppress(Exception):  # pragma: no cover - GUI quirks
                self.list.SetColumnWidth(index, width)

    def save_column_widths(self, config: ConfigManager) -> None:
        """Persist current column widths."""

        for index in range(self.list.GetColumnCount()):
            width = self.list.GetColumnWidth(index)
            width = max(self.MIN_COL_WIDTH, min(width, self.MAX_COL_WIDTH))
            config.write_int(f"col_width_{index}", width)

    def load_column_order(self, config: ConfigManager) -> None:
        """Restore column order if the backend supports it."""

        order_spec = config.read("col_order", "")
        if not order_spec:
            return
        desired = [name for name in order_spec.split(",") if name]
        order: list[int] = []
        for name in desired:
            try:
                order.append(self._field_order.index(name))
            except ValueError:
                continue
        for index in range(self.list.GetColumnCount()):
            if index not in order:
                order.append(index)
        if hasattr(self.list, "SetColumnsOrder"):
            with suppress(Exception):  # pragma: no cover - platform specific
                self.list.SetColumnsOrder(order)

    def save_column_order(self, config: ConfigManager) -> None:
        """Persist current column order if available."""

        if not hasattr(self.list, "GetColumnsOrder"):
            return
        try:
            order = self.list.GetColumnsOrder()
        except Exception:  # pragma: no cover - platform specific
            return
        names = [self._field_order[i] for i in order if i < len(self._field_order)]
        config.write("col_order", ",".join(names))

    def reorder_columns(self, from_col: int, to_col: int) -> None:
        """Allow reordering user columns while keeping Title fixed."""

        anchor = 2 if self._show_labels else 1
        if from_col == to_col or from_col < anchor or to_col < anchor:
            return
        if from_col >= len(self._field_order) or to_col >= len(self._field_order):
            return
        fields = list(self._field_order[anchor:])
        moved = fields.pop(from_col - anchor)
        fields.insert(to_col - anchor, moved)
        self.columns = fields
        self._apply_columns()
        self._refresh()

    def _default_column_width(self, field: str) -> int:
        if field in self.DEFAULT_COLUMN_WIDTHS:
            return self.DEFAULT_COLUMN_WIDTHS[field]
        if field.endswith("_at"):
            return 180
        if field in {"revision", "doc_prefix", "derived_count", "id"}:
            return 90
        return self.DEFAULT_COLUMN_WIDTH

    # ------------------------------------------------------------------
    # Filtering (simplified)
    # ------------------------------------------------------------------
    def apply_filters(self, filters: dict[str, object]) -> None:
        """Apply a subset of filters to the underlying model."""

        sanitized: dict[str, object] = {}

        labels = filters.get("labels", [])
        if isinstance(labels, list):
            label_list = [str(lbl) for lbl in labels if str(lbl)]
        else:
            label_list = []
        if label_list:
            sanitized["labels"] = label_list
        self.model.set_label_filter(label_list)

        match_any = bool(filters.get("match_any", False))
        if match_any:
            sanitized["match_any"] = True
        self.model.set_label_match_all(not match_any)

        query = str(filters.get("query", "") or "")
        if query:
            sanitized["query"] = query

        fields = filters.get("fields")
        if isinstance(fields, list):
            field_names = [str(name) for name in fields if str(name)]
        else:
            field_names = None
        if field_names:
            sanitized["fields"] = field_names
        self.model.set_search_query(query, field_names)

        field_queries_input = filters.get("field_queries", {})
        if isinstance(field_queries_input, dict):
            casted = {
                str(key): str(value)
                for key, value in field_queries_input.items()
                if value
            }
        else:
            casted = {}
        if casted:
            sanitized["field_queries"] = casted
        self.model.set_field_queries(casted)

        status = filters.get("status")
        status_value = str(status) if status else ""
        if status_value:
            sanitized["status"] = status_value
        self.model.set_status(status_value or None)

        is_derived = bool(filters.get("is_derived", False))
        has_derived = bool(filters.get("has_derived", False))
        if is_derived:
            sanitized["is_derived"] = True
        if has_derived:
            sanitized["has_derived"] = True
        self.model.set_is_derived(is_derived)
        self.model.set_has_derived(has_derived)

        self.current_filters = sanitized
        self._refresh()
        self._update_filter_summary()
        self._toggle_reset_button()

    def reset_filters(self) -> None:
        """Clear applied filters."""

        self.apply_filters({})

    def _create_filter_dialog(self) -> FilterDialog:
        """Construct a filter dialog instance (split for testing)."""

        return self._filter_dialog_factory(
            self,
            labels=self._labels,
            values=self.current_filters,
        )

    def _on_filter_button(self, _event: wx.Event | None) -> None:  # pragma: no cover - UI
        dialog: FilterDialog | None = None
        try:
            dialog = self._create_filter_dialog()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Unable to open filter dialog")
            return
        try:
            result = dialog.ShowModal()
            if result == wx.ID_OK:
                try:
                    filters = dialog.get_filters()
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Filter dialog produced invalid filters")
                    return
                self.apply_filters(filters)
        finally:
            dialog.Destroy()

    def _on_reset_button(self, _event: wx.Event) -> None:  # pragma: no cover - UI
        self.reset_filters()

    def _toggle_reset_button(self) -> None:
        has_filters = any(self.current_filters.values())
        if has_filters:
            self.reset_btn.Show()
        else:
            self.reset_btn.Hide()
        self.GetSizer().Layout()

    def _update_filter_summary(self) -> None:
        parts: list[str] = []
        query = self.current_filters.get("query")
        if query:
            parts.append(_("Query: %s") % query)
        labels = self.current_filters.get("labels")
        if labels:
            parts.append(_("Labels: %s") % ", ".join(str(lbl) for lbl in labels))
        status = self.current_filters.get("status")
        if status:
            parts.append(
                _("Status: %s")
                % locale.code_to_label("status", str(status)),
            )
        derived = self.current_filters.get("is_derived")
        if derived:
            parts.append(_("Derived only"))
        has_children = self.current_filters.get("has_derived")
        if has_children:
            parts.append(_("With children"))
        field_queries = self.current_filters.get("field_queries")
        if isinstance(field_queries, dict):
            for field, value in field_queries.items():
                if value:
                    parts.append(f"{locale.field_label(field)}: {value}")
        self.filter_summary.SetLabel("; ".join(parts))

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def set_requirements(
        self,
        requirements: list[Requirement],
        derived_map: dict[str, list[int]] | None = None,
    ) -> None:
        self.model.set_requirements(requirements)
        if derived_map:
            # ensure we don't mutate the incoming mapping in place
            self.derived_map = {str(k): list(v) for k, v in derived_map.items()}
        else:
            computed: dict[str, list[int]] = {}
            for req in requirements:
                for rid in self._parent_rids(req):
                    computed.setdefault(rid, []).append(req.id)
            self.derived_map = computed
        self._refresh()

    def recalc_derived_map(self, requirements: list[Requirement]) -> None:
        derived: dict[str, list[int]] = {}
        for req in requirements:
            for rid in self._parent_rids(req):
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
        except Exception:  # pragma: no cover - defensive
            items = []
        self.list.DeleteAllItems()
        for req in items:
            row = self.list.InsertItem(
                self.list.GetItemCount(),
                self._field_text(req, "title"),
            )
            try:
                req_id = int(getattr(req, "id", 0))
            except (TypeError, ValueError):
                req_id = 0
            self.list.SetItemData(row, req_id)
            for col, field in enumerate(self._field_order):
                value = self._field_text(req, field)
                if col == 0:
                    self.list.SetItem(row, 0, value)
                else:
                    self.list.SetItem(row, col, value)

    # ------------------------------------------------------------------
    # Sorting & selection
    # ------------------------------------------------------------------
    def sort(self, column: int, ascending: bool) -> None:
        if column < 0 or column >= len(self._field_order):
            return
        field = self._field_order[column]
        if field in {"derived_count", "derived_from"}:
            # Derived data lives outside Requirement model; fallback to title
            field = "title"
        self._sort_column = column
        self._sort_ascending = ascending
        self.model.sort(field, ascending)
        self._refresh()
        if self._on_sort_changed:
            self._on_sort_changed(column, ascending)

    def focus_requirement(self, req_id: int) -> None:
        target: int | None = None
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
                target = idx
                break
        if target is None:
            return
        for idx in range(count):
            self._set_item_selected(idx, idx == target)
        if hasattr(self.list, "EnsureVisible"):
            with suppress(Exception):
                self.list.EnsureVisible(target)

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
    # Text helpers
    # ------------------------------------------------------------------
    def _parent_rids(self, req: Requirement) -> list[str]:
        parents: list[str] = []
        for link in getattr(req, "links", []) or []:
            rid = self._link_rid(link)
            if rid:
                parents.append(rid)
        return parents

    def _link_rid(self, link: object) -> str:
        if isinstance(link, dict):
            value = link.get("rid") or link.get("id") or ""
            return str(value)
        value = getattr(link, "rid", link)
        if value is None:
            return ""
        return str(value)

    def _field_text(self, req: Requirement, field: str) -> str:
        if field == "title":
            return self._title_text(req)
        if field == "labels":
            labels = getattr(req, "labels", []) or []
            return ", ".join(str(label) for label in labels)
        if field == "derived_count":
            rid = getattr(req, "rid", "")
            children = self.derived_map.get(str(rid), [])
            return str(len(children)) if children else "0"
        if field == "derived_from":
            parents = self._parent_rids(req)
            seen: dict[str, None] = {}
            ordered: list[str] = []
            for parent in parents:
                if parent not in seen:
                    seen[parent] = None
                    ordered.append(parent)
            return ", ".join(ordered)
        value = getattr(req, field, "")
        if isinstance(value, Enum):
            return self._enum_label(field, value)
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        if value is None:
            return ""
        return str(value)

    def _enum_label(self, field: str, value: Enum) -> str:
        enum_cls = ENUMS.get(field)
        if enum_cls and isinstance(value, enum_cls):
            code = value.value
        else:
            code = getattr(value, "value", str(value))
        return locale.code_to_label(field, str(code))

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
