"""Panel displaying requirements list and simple filters."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import suppress
from enum import Enum
from typing import TYPE_CHECKING

import wx
from wx.lib.mixins.listctrl import ColumnSorterMixin

from ..core.document_store import LabelDef, label_color, stable_color
from ..core.model import Requirement
from ..i18n import _
from ..log import logger
from . import locale
from .enums import ENUMS
from .filter_dialog import FilterDialog
from .requirement_model import RequirementModel

if TYPE_CHECKING:
    from ..config import ConfigManager
    from .controllers import DocumentsController

if TYPE_CHECKING:  # pragma: no cover
    from wx import ContextMenuEvent, ListEvent


class ListPanel(wx.Panel, ColumnSorterMixin):
    """Panel with a filter button and list of requirement fields."""

    MIN_COL_WIDTH = 50
    MAX_COL_WIDTH = 1000
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
        on_sort_changed: Callable[[int, bool], None] | None = None,
        on_derive: Callable[[int], None] | None = None,
    ):
        """Initialize list view and controls for requirements."""
        wx.Panel.__init__(self, parent)
        self.model = model if model is not None else RequirementModel()
        sizer = wx.BoxSizer(wx.VERTICAL)
        orient = getattr(wx, "HORIZONTAL", 0)
        right = getattr(wx, "RIGHT", 0)
        align_center = getattr(wx, "ALIGN_CENTER_VERTICAL", 0)
        btn_row = wx.BoxSizer(orient)
        self.filter_btn = wx.Button(self, label=_("Filters"))
        bmp = wx.ArtProvider.GetBitmap(
            getattr(wx, "ART_CLOSE", "wxART_CLOSE"),
            getattr(wx, "ART_BUTTON", "wxART_BUTTON"),
            (16, 16),
        )
        self.reset_btn = wx.BitmapButton(
            self,
            bitmap=bmp,
            style=getattr(wx, "BU_EXACTFIT", 0),
        )
        self.reset_btn.SetToolTip(_("Clear filters"))
        self.reset_btn.Hide()
        self.filter_summary = wx.StaticText(self, label="")
        btn_row.Add(self.filter_btn, 0, right, 5)
        btn_row.Add(self.reset_btn, 0, right, 5)
        btn_row.Add(self.filter_summary, 0, align_center, 0)
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT)
        if hasattr(self.list, "SetExtraStyle"):
            extra = getattr(wx, "LC_EX_SUBITEMIMAGES", 0)
            if extra:
                with suppress(Exception):  # pragma: no cover - backend quirks
                    self.list.SetExtraStyle(self.list.GetExtraStyle() | extra)
        self._labels: list[LabelDef] = []
        self.current_filters: dict = {}
        self._image_list: wx.ImageList | None = None
        self._label_images: dict[tuple[str, ...], int] = {}
        ColumnSorterMixin.__init__(self, 1)
        self.columns: list[str] = []
        self._on_clone = on_clone
        self._on_delete = on_delete
        self._on_sort_changed = on_sort_changed
        self._on_derive = on_derive
        self.derived_map: dict[str, list[int]] = {}
        self._sort_column = -1
        self._sort_ascending = True
        self._docs_controller = docs_controller
        self._current_doc_prefix: str | None = None
        self._setup_columns()
        sizer.Add(btn_row, 0, wx.ALL, 5)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(sizer)
        self.list.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self._on_right_click)
        self.list.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self.filter_btn.Bind(wx.EVT_BUTTON, self._on_filter)
        self.reset_btn.Bind(wx.EVT_BUTTON, lambda _evt: self.reset_filters())

    # ColumnSorterMixin requirement
    def GetListCtrl(self):  # pragma: no cover - simple forwarding
        """Return internal ``wx.ListCtrl`` for sorting mixin."""

        return self.list

    def GetSortImages(self):  # pragma: no cover - default arrows
        """Return image ids for sort arrows (unused)."""

        return (-1, -1)

    def set_handlers(
        self,
        *,
        on_clone: Callable[[int], None] | None = None,
        on_delete: Callable[[int], None] | None = None,
        on_derive: Callable[[int], None] | None = None,
    ) -> None:
        """Set callbacks for context menu actions."""
        if on_clone is not None:
            self._on_clone = on_clone
        if on_delete is not None:
            self._on_delete = on_delete
        if on_derive is not None:
            self._on_derive = on_derive

    def set_documents_controller(
        self, controller: DocumentsController | None
    ) -> None:
        """Set documents controller used for persistence."""

        self._docs_controller = controller

    def set_active_document(self, prefix: str | None) -> None:
        """Record currently active document prefix for persistence."""

        self._current_doc_prefix = prefix

    def _label_color(self, name: str) -> str:
        for lbl in self._labels:
            if lbl.key == name:
                return label_color(lbl)
        return stable_color(name)

    def _ensure_image_list_size(self, width: int, height: int) -> None:
        width = max(width, 1)
        height = max(height, 1)
        if self._image_list is None:
            self._image_list = wx.ImageList(width, height)
            self.list.SetImageList(self._image_list, wx.IMAGE_LIST_SMALL)
            return
        cur_w, cur_h = self._image_list.GetSize()
        if width <= cur_w and height <= cur_h:
            return
        new_w = max(width, cur_w)
        new_h = max(height, cur_h)
        new_list = wx.ImageList(new_w, new_h)
        count = self._image_list.GetImageCount()
        for idx in range(count):
            bmp = self._image_list.GetBitmap(idx)
            bmp = self._pad_bitmap(bmp, new_w, new_h)
            new_list.Add(bmp)
        self._image_list = new_list
        self.list.SetImageList(self._image_list, wx.IMAGE_LIST_SMALL)

    def _pad_bitmap(self, bmp: wx.Bitmap, width: int, height: int) -> wx.Bitmap:
        if bmp.GetWidth() == width and bmp.GetHeight() == height:
            return bmp
        padded = wx.Bitmap(max(width, 1), max(height, 1))
        dc = wx.MemoryDC()
        dc.SelectObject(padded)
        try:
            bg = self.list.GetBackgroundColour()
            dc.SetBackground(wx.Brush(bg))
            dc.Clear()
            dc.DrawBitmap(bmp, 0, 0, True)
        finally:
            dc.SelectObject(wx.NullBitmap)
        return padded

    def _set_label_text(self, index: int, col: int, labels: list[str]) -> None:
        text = ", ".join(labels)
        self.list.SetItem(index, col, text)
        if col == 0 and hasattr(self.list, "SetItemImage"):
            with suppress(Exception):
                self.list.SetItemImage(index, -1)
        else:
            with suppress(Exception):
                self.list.SetItemColumnImage(index, col, -1)
            if hasattr(self.list, "SetItemImage"):
                with suppress(Exception):
                    self.list.SetItemImage(index, -1)

    def _create_label_bitmap(self, names: list[str]) -> wx.Bitmap:
        padding_x, padding_y, gap = 4, 2, 2
        font = self.list.GetFont()
        dc = wx.MemoryDC()
        dc.SelectObject(wx.Bitmap(1, 1))
        dc.SetFont(font)
        widths: list[int] = []
        height = 0
        for name in names:
            w, h = dc.GetTextExtent(name)
            widths.append(w)
            height = max(height, h)
        height += padding_y * 2
        total = sum(w + padding_x * 2 for w in widths) + gap * (len(names) - 1)
        bmp = wx.Bitmap(total or 1, height or 1)
        dc.SelectObject(bmp)
        dc.SetBackground(wx.Brush(self.list.GetBackgroundColour()))
        dc.Clear()
        x = 0
        for name, w in zip(names, widths):
            colour = wx.Colour(self._label_color(name))
            dc.SetBrush(wx.Brush(colour))
            dc.SetPen(wx.Pen(colour))
            box_w = w + padding_x * 2
            dc.DrawRectangle(x, 0, box_w, height)
            dc.SetTextForeground(wx.BLACK)
            dc.DrawText(name, x + padding_x, padding_y)
            x += box_w + gap
        dc.SelectObject(wx.NullBitmap)
        return bmp

    def _set_label_image(self, index: int, col: int, labels: list[str]) -> None:
        if not labels:
            self.list.SetItem(index, col, "")
            if hasattr(self.list, "SetItemImage") and col == 0:
                with suppress(Exception):
                    self.list.SetItemImage(index, -1)
            return
        key = tuple(labels)
        img_id = self._label_images.get(key)
        if img_id == -1:
            self._set_label_text(index, col, labels)
            return
        if img_id is None:
            bmp = self._create_label_bitmap(labels)
            self._ensure_image_list_size(bmp.GetWidth(), bmp.GetHeight())
            if self._image_list is None:
                self._label_images[key] = -1
                self._set_label_text(index, col, labels)
                return
            list_w, list_h = self._image_list.GetSize()
            bmp = self._pad_bitmap(bmp, list_w, list_h)
            try:
                img_id = self._image_list.Add(bmp)
            except Exception:
                logger.exception("Failed to add labels image; using text fallback")
                img_id = -1
            if img_id == -1:
                logger.warning("Image list rejected labels bitmap; using text fallback")
                self._label_images[key] = -1
                self._set_label_text(index, col, labels)
                return
            self._label_images[key] = img_id
        if col == 0:
            # Column 0 uses the main item image slot
            self.list.SetItem(index, col, "")
            if hasattr(self.list, "SetItemImage"):
                with suppress(Exception):
                    self.list.SetItemImage(index, img_id)
        else:
            self.list.SetItem(index, col, "")
            self.list.SetItemColumnImage(index, col, img_id)
            if hasattr(self.list, "SetItemImage"):
                with suppress(Exception):
                    self.list.SetItemImage(index, -1)

    def _setup_columns(self) -> None:
        """Configure list control columns based on selected fields.

        On Windows ``wx.ListCtrl`` always reserves space for an image in the
        first physical column. Placing ``labels`` at index 0 removes the extra
        padding before ``Title``. Another workaround is to insert a hidden
        dummy column before ``Title``.
        """
        self.list.ClearAll()
        self._field_order: list[str] = []
        include_labels = "labels" in self.columns
        if include_labels:
            self.list.InsertColumn(0, _("Labels"))
            self._field_order.append("labels")
            self.list.InsertColumn(1, _("Title"))
            self._field_order.append("title")
        else:
            self.list.InsertColumn(0, _("Title"))
            self._field_order.append("title")
        for field in self.columns:
            if field == "labels":
                continue
            idx = self.list.GetColumnCount()
            self.list.InsertColumn(idx, locale.field_label(field))
            self._field_order.append(field)
        ColumnSorterMixin.__init__(self, self.list.GetColumnCount())
        with suppress(Exception):  # remove mixin's default binding and use our own
            self.list.Unbind(wx.EVT_LIST_COL_CLICK)
        self.list.Bind(wx.EVT_LIST_COL_CLICK, self._on_col_click)

    # Columns ---------------------------------------------------------
    def load_column_widths(self, config: ConfigManager) -> None:
        """Restore column widths from config with sane bounds."""
        count = self.list.GetColumnCount()
        for i in range(count):
            width = config.read_int(f"col_width_{i}", -1)
            if width <= 0:
                field = self._field_order[i] if i < len(self._field_order) else ""
                width = self._default_column_width(field)
            width = max(self.MIN_COL_WIDTH, min(width, self.MAX_COL_WIDTH))
            self.list.SetColumnWidth(i, width)

    def save_column_widths(self, config: ConfigManager) -> None:
        """Persist current column widths to config."""
        count = self.list.GetColumnCount()
        for i in range(count):
            width = self.list.GetColumnWidth(i)
            width = max(self.MIN_COL_WIDTH, min(width, self.MAX_COL_WIDTH))
            config.write_int(f"col_width_{i}", width)

    def _default_column_width(self, field: str) -> int:
        """Return sensible default width for a given column field."""

        width = self.DEFAULT_COLUMN_WIDTHS.get(field)
        if width is not None:
            return width
        if field.endswith("_at"):
            return 180
        if field in {"revision", "id", "doc_prefix", "derived_count"}:
            return 90
        return self.DEFAULT_COLUMN_WIDTH

    def load_column_order(self, config: ConfigManager) -> None:
        """Restore column ordering from config."""
        value = config.read("col_order", "")
        if not value:
            return
        names = [n for n in value.split(",") if n]
        order = [self._field_order.index(n) for n in names if n in self._field_order]
        count = self.list.GetColumnCount()
        for idx in range(count):
            if idx not in order:
                order.append(idx)
        with suppress(Exception):  # pragma: no cover - depends on GUI backend
            self.list.SetColumnsOrder(order)

    def save_column_order(self, config: ConfigManager) -> None:
        """Persist current column ordering to config."""
        try:  # pragma: no cover - depends on GUI backend
            order = self.list.GetColumnsOrder()
        except Exception:
            return
        names = [self._field_order[idx] for idx in order if idx < len(self._field_order)]
        config.write("col_order", ",".join(names))

    def reorder_columns(self, from_col: int, to_col: int) -> None:
        """Move column from ``from_col`` index to ``to_col`` index."""
        offset = 2 if "labels" in self.columns else 1
        if from_col == to_col or from_col < offset or to_col < offset:
            return
        fields = [f for f in self.columns if f != "labels"]
        field = fields.pop(from_col - offset)
        fields.insert(to_col - offset, field)
        if "labels" in self.columns:
            self.columns = ["labels", *fields]
        else:
            self.columns = fields
        self._setup_columns()
        self._refresh()

    def set_columns(self, fields: list[str]) -> None:
        """Set additional columns (beyond Title) to display.

        ``labels`` is treated specially and rendered as a comma-separated list.
        """
        self.columns = fields
        self._setup_columns()
        # repopulate with existing requirements after changing columns
        self._refresh()

    def set_requirements(
        self,
        requirements: list,
        derived_map: dict[str, list[int]] | None = None,
    ) -> None:
        """Populate list control with requirement data via model."""
        self.model.set_requirements(requirements)
        if derived_map is None:
            derived_map = {}
            for req in requirements:
                for parent in getattr(req, "links", []):
                    parent_rid = getattr(parent, "rid", parent)
                    derived_map.setdefault(parent_rid, []).append(req.id)
        self.derived_map = derived_map
        self._refresh()

    # filtering -------------------------------------------------------
    def apply_filters(self, filters: dict) -> None:
        """Apply filters to the underlying model."""
        self.current_filters.update(filters)
        self.model.set_label_filter(self.current_filters.get("labels", []))
        self.model.set_label_match_all(not self.current_filters.get("match_any", False))
        fields = self.current_filters.get("fields")
        self.model.set_search_query(self.current_filters.get("query", ""), fields)
        self.model.set_field_queries(self.current_filters.get("field_queries", {}))
        self.model.set_status(self.current_filters.get("status"))
        self.model.set_is_derived(self.current_filters.get("is_derived", False))
        self.model.set_has_derived(self.current_filters.get("has_derived", False))
        self._refresh()
        self._update_filter_summary()
        self._toggle_reset_button()

    def set_label_filter(self, labels: list[str]) -> None:
        """Apply label filter to the model."""

        self.apply_filters({"labels": labels})

    def set_search_query(self, query: str, fields: Sequence[str] | None = None) -> None:
        """Apply text ``query`` with optional field restriction."""

        filters = {"query": query}
        if fields is not None:
            filters["fields"] = list(fields)
        self.apply_filters(filters)

    def update_labels_list(self, labels: list[LabelDef]) -> None:
        """Update available labels for the filter dialog."""
        self._labels = [LabelDef(lbl.key, lbl.title, lbl.color) for lbl in labels]

    def _on_filter(self, event):  # pragma: no cover - simple event binding
        dlg = FilterDialog(self, labels=self._labels, values=self.current_filters)
        if dlg.ShowModal() == wx.ID_OK:
            self.apply_filters(dlg.get_filters())
        dlg.Destroy()
        if hasattr(event, "Skip"):
            event.Skip()

    def reset_filters(self) -> None:
        """Clear all applied filters and update UI."""
        self.current_filters = {}
        self.apply_filters({})

    def _update_filter_summary(self) -> None:
        """Update text describing currently active filters."""
        parts: list[str] = []
        if self.current_filters.get("query"):
            parts.append(_("Query") + f": {self.current_filters['query']}")
        labels = self.current_filters.get("labels") or []
        if labels:
            parts.append(_("Labels") + ": " + ", ".join(labels))
        status = self.current_filters.get("status")
        if status:
            parts.append(_("Status") + f": {locale.code_to_label('status', status)}")
        if self.current_filters.get("is_derived"):
            parts.append(_("Derived only"))
        if self.current_filters.get("has_derived"):
            parts.append(_("Has derived"))
        field_queries = self.current_filters.get("field_queries", {})
        for field, value in field_queries.items():
            if value:
                parts.append(f"{locale.field_label(field)}: {value}")
        summary = "; ".join(parts)
        if hasattr(self.filter_summary, "SetLabel"):
            self.filter_summary.SetLabel(summary)
        else:  # pragma: no cover - test stub
            self.filter_summary.label = summary

    def _has_active_filters(self) -> bool:
        """Return ``True`` if any filters are currently applied."""
        if self.current_filters.get("query"):
            return True
        if self.current_filters.get("labels"):
            return True
        if self.current_filters.get("status"):
            return True
        if self.current_filters.get("is_derived"):
            return True
        if self.current_filters.get("has_derived"):
            return True
        field_queries = self.current_filters.get("field_queries", {})
        return bool(any(field_queries.values()))

    def _toggle_reset_button(self) -> None:
        """Show or hide the reset button based on active filters."""
        if self._has_active_filters():
            if hasattr(self.reset_btn, "Show"):
                self.reset_btn.Show()
        else:
            if hasattr(self.reset_btn, "Hide"):
                self.reset_btn.Hide()
        if hasattr(self, "Layout"):
            with suppress(Exception):  # pragma: no cover - some stubs lack Layout
                self.Layout()

    def _refresh(self) -> None:
        """Reload list control from the model."""
        items = self.model.get_visible()
        self.list.DeleteAllItems()
        for req in items:
            index = self.list.InsertItem(self.list.GetItemCount(), "", -1)
            # Windows ListCtrl may still assign image 0; clear explicitly
            if hasattr(self.list, "SetItemImage"):
                with suppress(Exception):
                    self.list.SetItemImage(index, -1)
            req_id = getattr(req, "id", 0)
            try:
                self.list.SetItemData(index, int(req_id))
            except Exception:
                self.list.SetItemData(index, 0)
            for col, field in enumerate(self._field_order):
                if field == "title":
                    self.list.SetItem(index, col, getattr(req, "title", ""))
                    continue
                if field == "labels":
                    value = getattr(req, "labels", [])
                    self._set_label_image(index, col, value)
                    continue
                if field == "links":
                    links = getattr(req, "links", [])
                    formatted: list[str] = []
                    for link in links:
                        rid = getattr(link, "rid", str(link))
                        if getattr(link, "suspect", False):
                            formatted.append(f"{rid} ⚠")
                        else:
                            formatted.append(str(rid))
                    value = ", ".join(formatted)
                    self.list.SetItem(index, col, value)
                    continue
                if field == "derived_count":
                    rid = req.rid or str(req.id)
                    count = len(self.derived_map.get(rid, []))
                    self.list.SetItem(index, col, str(count))
                    continue
                if field == "attachments":
                    value = ", ".join(
                        getattr(a, "path", "") for a in getattr(req, "attachments", [])
                    )
                    self.list.SetItem(index, col, value)
                    continue
                value = getattr(req, field, "")
                if isinstance(value, Enum):
                    value = locale.code_to_label(field, value.value)
                self.list.SetItem(index, col, str(value))

    def refresh(self) -> None:
        """Public wrapper to reload list control."""
        self._refresh()

    def record_link(self, parent_rid: str, child_id: int) -> None:
        """Record that ``child_id`` links to ``parent_rid``."""

        self.derived_map.setdefault(parent_rid, []).append(child_id)

    def recalc_derived_map(self, requirements: list[Requirement]) -> None:
        """Rebuild derived requirements map from ``requirements``."""

        derived_map: dict[str, list[int]] = {}
        for req in requirements:
            for parent in getattr(req, "links", []):
                parent_rid = getattr(parent, "rid", parent)
                derived_map.setdefault(parent_rid, []).append(req.id)
        self.derived_map = derived_map
        self._refresh()

    def _on_col_click(self, event: ListEvent) -> None:  # pragma: no cover - GUI event
        col = event.GetColumn()
        ascending = not self._sort_ascending if col == self._sort_column else True
        self.sort(col, ascending)

    def sort(self, column: int, ascending: bool) -> None:
        """Sort list by ``column`` with ``ascending`` order."""
        self._sort_column = column
        self._sort_ascending = ascending
        if column < len(self._field_order):
            field = self._field_order[column]
            self.model.sort(field, ascending)
        self._refresh()
        if self._on_sort_changed:
            self._on_sort_changed(self._sort_column, self._sort_ascending)

    # context menu ----------------------------------------------------
    def _popup_context_menu(self, index: int, column: int | None) -> None:
        menu, _, _, _ = self._create_context_menu(index, column)
        self.PopupMenu(menu)
        menu.Destroy()

    def _on_right_click(self, event: ListEvent) -> None:  # pragma: no cover - GUI event
        x, y = event.GetPoint()
        if hasattr(self.list, "HitTestSubItem"):
            _, _, col = self.list.HitTestSubItem((x, y))
        else:  # pragma: no cover - fallback for older wx
            _, _ = self.list.HitTest((x, y))
            col = None
        self._popup_context_menu(event.GetIndex(), col)

    def _on_context_menu(
        self,
        event: ContextMenuEvent,
    ) -> None:  # pragma: no cover - GUI event
        pos = event.GetPosition()
        if pos == wx.DefaultPosition:
            pos = wx.GetMousePosition()
        pt = self.list.ScreenToClient(pos)
        if hasattr(self.list, "HitTestSubItem"):
            index, _, col = self.list.HitTestSubItem(pt)
            if col == -1:
                col = None
        else:  # pragma: no cover - fallback for older wx
            index, _ = self.list.HitTest(pt)
            col = None
        if index == wx.NOT_FOUND:
            return
        self.list.Select(index)
        self._popup_context_menu(index, col)

    def _field_from_column(self, col: int | None) -> str | None:
        if col is None or col < 0 or col >= len(self._field_order):
            return None
        return self._field_order[col]

    def _create_context_menu(self, index: int, column: int | None):
        menu = wx.Menu()
        derive_item = menu.Append(wx.ID_ANY, _("Derive"))
        clone_item = menu.Append(wx.ID_ANY, _("Clone"))
        delete_item = menu.Append(wx.ID_ANY, _("Delete"))
        req_id = self.list.GetItemData(index)
        field = self._field_from_column(column)
        edit_item = None
        if field and field != "title":
            edit_item = menu.Append(wx.ID_ANY, _("Edit {field}").format(field=field))
            menu.Bind(
                wx.EVT_MENU,
                lambda _evt, c=column: self._on_edit_field(c),
                edit_item,
            )
        if self._on_clone:
            menu.Bind(wx.EVT_MENU, lambda _evt, i=req_id: self._on_clone(i), clone_item)
        if self._on_delete:
            menu.Bind(
                wx.EVT_MENU,
                lambda _evt, i=req_id: self._on_delete(i),
                delete_item,
            )
        if self._on_derive:
            menu.Bind(
                wx.EVT_MENU,
                lambda _evt, i=req_id: self._on_derive(i),
                derive_item,
            )
        return menu, clone_item, delete_item, edit_item

    def _get_selected_indices(self) -> list[int]:
        indices: list[int] = []
        idx = self.list.GetFirstSelected()
        while idx != -1:
            indices.append(idx)
            idx = self.list.GetNextSelected(idx)
        return indices

    def _prompt_value(self, field: str) -> object | None:
        if field in ENUMS:
            enum_cls = ENUMS[field]
            choices = [locale.code_to_label(field, e.value) for e in enum_cls]
            dlg = wx.SingleChoiceDialog(
                self,
                _("Select {field}").format(field=field),
                _("Edit"),
                choices,
            )
            if dlg.ShowModal() == wx.ID_OK:
                label = dlg.GetStringSelection()
                code = locale.label_to_code(field, label)
                value = enum_cls(code)
            else:
                value = None
            dlg.Destroy()
            return value
        dlg = wx.TextEntryDialog(
            self,
            _("New value for {field}").format(field=field),
            _("Edit"),
        )
        value = dlg.GetValue() if dlg.ShowModal() == wx.ID_OK else None
        dlg.Destroy()
        return value

    def _on_edit_field(self, column: int) -> None:  # pragma: no cover - GUI event
        field = self._field_from_column(column)
        if not field:
            return
        value = self._prompt_value(field)
        if value is None:
            return
        for idx in self._get_selected_indices():
            items = self.model.get_visible()
            if idx >= len(items):
                continue
            req = items[idx]
            if field == "revision":
                try:
                    numeric = int(str(value).strip())
                except (TypeError, ValueError):
                    continue
                if numeric <= 0:
                    continue
                value = numeric
            setattr(req, field, value)
            self.model.update(req)
            if isinstance(value, Enum):
                display = (
                    locale.code_to_label(field, value.value)
                    if field in ENUMS
                    else value.value
                )
            else:
                display = value
            self.list.SetItem(idx, column, str(display))
            self._persist_requirement(req)

    def _persist_requirement(self, req: Requirement) -> None:
        """Persist edited ``req`` if controller and document are available."""

        if not self._docs_controller or not self._current_doc_prefix:
            return
        try:
            self._docs_controller.save_requirement(self._current_doc_prefix, req)
        except Exception:  # pragma: no cover - log and continue
            rid = getattr(req, "rid", req.id)
            logger.exception("Failed to save requirement %s", rid)
