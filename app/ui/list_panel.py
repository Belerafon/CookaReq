"""Panel displaying requirements list and simple filters."""

from __future__ import annotations

from ..i18n import _

import wx
from wx.lib.mixins.listctrl import ColumnSorterMixin

from typing import Callable, List, Sequence, TYPE_CHECKING
from enum import Enum

from ..core.model import Priority, RequirementType, Status, Verification, Requirement
from ..core.labels import Label, _color_from_name
from .requirement_model import RequirementModel
from .filter_dialog import FilterDialog
from . import locale

if TYPE_CHECKING:  # pragma: no cover
    from wx import ListEvent, ContextMenuEvent


class ListPanel(wx.Panel, ColumnSorterMixin):
    """Panel with a filter button and list of requirement fields."""

    MIN_COL_WIDTH = 50
    MAX_COL_WIDTH = 1000

    def __init__(
        self,
        parent: wx.Window,
        *,
        model: RequirementModel | None = None,
        on_clone: Callable[[int], None] | None = None,
        on_delete: Callable[[int], None] | None = None,
        on_sort_changed: Callable[[int, bool], None] | None = None,
        on_derive: Callable[[int], None] | None = None,
    ):
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
        self._labels: list[Label] = []
        self.current_filters: dict = {}
        self._image_list: wx.ImageList | None = None
        self._label_images: dict[tuple[str, ...], int] = {}
        ColumnSorterMixin.__init__(self, 1)
        self.columns: List[str] = []
        self._on_clone = on_clone
        self._on_delete = on_delete
        self._on_sort_changed = on_sort_changed
        self._on_derive = on_derive
        self.derived_map: dict[int, List[int]] = {}
        self._sort_column = -1
        self._sort_ascending = True
        self._setup_columns()
        sizer.Add(btn_row, 0, wx.ALL, 5)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(sizer)
        self.list.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self._on_right_click)
        self.list.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self.filter_btn.Bind(wx.EVT_BUTTON, self._on_filter)
        self.reset_btn.Bind(wx.EVT_BUTTON, lambda evt: self.reset_filters())

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

    # label rendering -------------------------------------------------
    def _label_color(self, name: str) -> str:
        for lbl in self._labels:
            if lbl.name == name:
                return lbl.color
        return _color_from_name(name)

    def _ensure_image_list_size(self, width: int, height: int) -> None:
        if self._image_list is None:
            self._image_list = wx.ImageList(width or 1, height or 1)
            self.list.SetImageList(self._image_list, wx.IMAGE_LIST_SMALL)
            return
        cur_w, cur_h = self._image_list.GetSize()  # pragma: no cover - simple accessors
        if width <= cur_w and height <= cur_h:
            return
        new_list = wx.ImageList(max(width, cur_w), max(height, cur_h))
        count = self._image_list.GetImageCount()
        for idx in range(count):  # pragma: no cover - trivial loop
            bmp = self._image_list.GetBitmap(idx)
            new_list.Add(bmp)
        self._image_list = new_list
        self.list.SetImageList(self._image_list, wx.IMAGE_LIST_SMALL)

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
            color_hex = self._label_color(name)
            colour = wx.Colour(color_hex)
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
            return
        key = tuple(labels)
        img_id = self._label_images.get(key)
        if img_id is None:
            bmp = self._create_label_bitmap(labels)
            self._ensure_image_list_size(bmp.GetWidth(), bmp.GetHeight())
            img_id = self._image_list.Add(bmp)
            self._label_images[key] = img_id
        self.list.SetItem(index, col, "")
        if hasattr(self.list, "SetItemColumnImage"):
            try:
                self.list.SetItemColumnImage(index, col, img_id)
            except Exception:  # pragma: no cover - platform dependent
                pass
        elif hasattr(wx, "ListItem"):
            item = wx.ListItem()
            item.SetId(index)
            item.SetColumn(col)
            item.SetImage(img_id)
            try:  # pragma: no cover - platform dependent
                self.list.SetItem(item)
            except Exception:
                pass
        else:  # pragma: no cover - stub fallback
            self.list.SetItem(index, col, ", ".join(labels))

    def _setup_columns(self) -> None:
        """Configure list control columns based on selected fields."""
        self.list.ClearAll()
        self.list.InsertColumn(0, _("Title"))
        for idx, field in enumerate(self.columns, start=1):
            self.list.InsertColumn(idx, field)
        ColumnSorterMixin.__init__(self, self.list.GetColumnCount())
        try:  # remove mixin's default binding and use our own
            self.list.Unbind(wx.EVT_LIST_COL_CLICK)
        except Exception:  # pragma: no cover - Unbind may not exist
            pass
        self.list.Bind(wx.EVT_LIST_COL_CLICK, self._on_col_click)

    # Columns ---------------------------------------------------------
    def load_column_widths(self, config: wx.Config) -> None:
        """Restore column widths from config with sane bounds."""
        count = self.list.GetColumnCount()
        for i in range(count):
            width = config.ReadInt(f"col_width_{i}", -1)
            if width != -1:
                width = max(self.MIN_COL_WIDTH, min(width, self.MAX_COL_WIDTH))
                self.list.SetColumnWidth(i, width)

    def save_column_widths(self, config: wx.Config) -> None:
        """Persist current column widths to config."""
        count = self.list.GetColumnCount()
        for i in range(count):
            width = self.list.GetColumnWidth(i)
            width = max(self.MIN_COL_WIDTH, min(width, self.MAX_COL_WIDTH))
            config.WriteInt(f"col_width_{i}", width)

    def load_column_order(self, config: wx.Config) -> None:
        """Restore column ordering from config."""
        value = config.Read("col_order", "")
        if not value:
            return
        names = [n for n in value.split(",") if n]
        order: List[int] = []
        for name in names:
            if name == "title":
                order.append(0)
            elif name in self.columns:
                order.append(self.columns.index(name) + 1)
        count = self.list.GetColumnCount()
        for idx in range(count):
            if idx not in order:
                order.append(idx)
        try:  # pragma: no cover - depends on GUI backend
            self.list.SetColumnsOrder(order)
        except Exception:
            pass

    def save_column_order(self, config: wx.Config) -> None:
        """Persist current column ordering to config."""
        try:  # pragma: no cover - depends on GUI backend
            order = self.list.GetColumnsOrder()
        except Exception:
            return
        names: List[str] = []
        for idx in order:
            if idx == 0:
                names.append("title")
            elif 1 <= idx <= len(self.columns):
                names.append(self.columns[idx - 1])
        config.Write("col_order", ",".join(names))

    def reorder_columns(self, from_col: int, to_col: int) -> None:
        """Move column from ``from_col`` index to ``to_col`` index."""
        if from_col == to_col or from_col <= 0 or to_col <= 0:
            return
        fields = list(self.columns)
        field = fields.pop(from_col - 1)
        fields.insert(to_col - 1, field)
        self.columns = fields
        self._setup_columns()
        self._refresh()

    def set_columns(self, fields: List[str]) -> None:
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
        derived_map: dict[int, List[int]] | None = None,
    ) -> None:
        """Populate list control with requirement data via model."""
        self.model.set_requirements(requirements)
        if derived_map is None:
            derived_map = {}
            for req in requirements:
                for link in getattr(req, "derived_from", []):
                    derived_map.setdefault(link.source_id, []).append(req.id)
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
        self.model.set_suspect_only(self.current_filters.get("suspect_only", False))
        self._refresh()
        self._update_filter_summary()
        self._toggle_reset_button()

    def set_label_filter(self, labels: List[str]) -> None:
        """Apply label filter to the model."""

        self.apply_filters({"labels": labels})

    def set_search_query(self, query: str, fields: Sequence[str] | None = None) -> None:
        """Apply text ``query`` with optional field restriction."""

        filters = {"query": query}
        if fields is not None:
            filters["fields"] = list(fields)
        self.apply_filters(filters)

    def update_labels_list(self, labels: list[Label]) -> None:
        """Update available labels for the filter dialog."""
        self._labels = list(labels)

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
            parts.append(_("Status") + f": {locale.STATUS.get(status, status)}")
        if self.current_filters.get("is_derived"):
            parts.append(_("Derived only"))
        if self.current_filters.get("has_derived"):
            parts.append(_("Has derived"))
        if self.current_filters.get("suspect_only"):
            parts.append(_("Suspect only"))
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
        if self.current_filters.get("suspect_only"):
            return True
        field_queries = self.current_filters.get("field_queries", {})
        if any(v for v in field_queries.values()):
            return True
        return False

    def _toggle_reset_button(self) -> None:
        """Show or hide the reset button based on active filters."""
        if self._has_active_filters():
            if hasattr(self.reset_btn, "Show"):
                self.reset_btn.Show()
        else:
            if hasattr(self.reset_btn, "Hide"):
                self.reset_btn.Hide()
        if hasattr(self, "Layout"):
            try:
                self.Layout()
            except Exception:  # pragma: no cover - some stubs lack Layout
                pass

    def _refresh(self) -> None:
        """Reload list control from the model."""
        items = self.model.get_visible()
        self.list.DeleteAllItems()
        for req in items:
            title = getattr(req, "title", "")
            index = self.list.InsertItem(self.list.GetItemCount(), title)
            req_id = getattr(req, "id", 0)
            try:
                self.list.SetItemData(index, int(req_id))
            except Exception:
                self.list.SetItemData(index, 0)
            suspect_row = False
            for col, field in enumerate(self.columns, start=1):
                if field == "derived_from":
                    links = getattr(req, "derived_from", [])
                    texts: list[str] = []
                    for link in links:
                        txt = str(getattr(link, "source_id", ""))
                        if getattr(link, "suspect", False):
                            txt = f"!{txt}"
                            suspect_row = True
                        texts.append(txt)
                    value = ", ".join(texts)
                    self.list.SetItem(index, col, value)
                    continue
                if field in {"verifies", "relates"}:
                    links = getattr(getattr(req, "links", None), field, [])
                    texts: list[str] = []
                    for link in links:
                        txt = str(getattr(link, "source_id", ""))
                        if getattr(link, "suspect", False):
                            txt = f"!{txt}"
                            suspect_row = True
                        texts.append(txt)
                    value = ", ".join(texts)
                    self.list.SetItem(index, col, value)
                    continue
                if field == "parent":
                    link = getattr(req, "parent", None)
                    value = ""
                    if link:
                        value = str(getattr(link, "source_id", ""))
                        if getattr(link, "suspect", False):
                            value = f"!{value}"
                            suspect_row = True
                    self.list.SetItem(index, col, value)
                    continue
                if field == "derived_count":
                    count = len(self.derived_map.get(req.id, []))
                    self.list.SetItem(index, col, str(count))
                    continue
                if field == "attachments":
                    value = ", ".join(getattr(a, "path", "") for a in getattr(req, "attachments", []))
                    self.list.SetItem(index, col, value)
                    continue
                value = getattr(req, field, "")
                if isinstance(value, Enum):
                    value = locale.code_to_label(field, value.value)
                if field == "labels" and isinstance(value, list):
                    self._set_label_image(index, col, value)
                    continue
                self.list.SetItem(index, col, str(value))
            if suspect_row and hasattr(self.list, "SetItemTextColour"):
                try:
                    colour = getattr(wx, "RED", None) or wx.Colour(255, 0, 0)
                    self.list.SetItemTextColour(index, colour)
                except Exception:
                    pass

    def refresh(self) -> None:
        """Public wrapper to reload list control."""
        self._refresh()

    def add_derived_link(self, source_id: int, derived_id: int) -> None:
        """Record that ``derived_id`` is derived from ``source_id``."""

        self.derived_map.setdefault(source_id, []).append(derived_id)

    def recalc_derived_map(self, requirements: list[Requirement]) -> None:
        """Rebuild derived requirements map from ``requirements``."""

        derived_map: dict[int, List[int]] = {}
        for req in requirements:
            for link in getattr(req, "derived_from", []):
                derived_map.setdefault(link.source_id, []).append(req.id)
        self.derived_map = derived_map
        self._refresh()

    def _on_col_click(self, event: "ListEvent") -> None:  # pragma: no cover - GUI event
        col = event.GetColumn()
        if col == self._sort_column:
            ascending = not self._sort_ascending
        else:
            ascending = True
        self.sort(col, ascending)

    def sort(self, column: int, ascending: bool) -> None:
        """Sort list by ``column`` with ``ascending`` order."""
        self._sort_column = column
        self._sort_ascending = ascending
        field = "title" if column == 0 else self.columns[column - 1]
        self.model.sort(field, ascending)
        self._refresh()
        if self._on_sort_changed:
            self._on_sort_changed(self._sort_column, self._sort_ascending)

    # context menu ----------------------------------------------------
    def _popup_context_menu(self, index: int, column: int | None) -> None:
        menu, _, _, _ = self._create_context_menu(index, column)
        self.PopupMenu(menu)
        menu.Destroy()

    def _on_right_click(self, event: "ListEvent") -> None:  # pragma: no cover - GUI event
        x, y = event.GetPoint()
        if hasattr(self.list, "HitTestSubItem"):
            _, _, col = self.list.HitTestSubItem((x, y))
        else:  # pragma: no cover - fallback for older wx
            _, _ = self.list.HitTest((x, y))
            col = None
        self._popup_context_menu(event.GetIndex(), col)

    def _on_context_menu(self, event: "ContextMenuEvent") -> None:  # pragma: no cover - GUI event
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
        if col is None or col < 0:
            return None
        if col == 0:
            return "title"
        if 1 <= col <= len(self.columns):
            return self.columns[col - 1]
        return None

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
            menu.Bind(wx.EVT_MENU, lambda evt, c=column: self._on_edit_field(c), edit_item)
        if self._on_clone:
            menu.Bind(wx.EVT_MENU, lambda evt, i=req_id: self._on_clone(i), clone_item)
        if self._on_delete:
            menu.Bind(wx.EVT_MENU, lambda evt, i=req_id: self._on_delete(i), delete_item)
        if self._on_derive:
            menu.Bind(wx.EVT_MENU, lambda evt, i=req_id: self._on_derive(i), derive_item)
        return menu, clone_item, delete_item, edit_item

    def _get_selected_indices(self) -> List[int]:
        indices: List[int] = []
        idx = self.list.GetFirstSelected()
        while idx != -1:
            indices.append(idx)
            idx = self.list.GetNextSelected(idx)
        return indices

    def _prompt_value(self, field: str) -> object | None:
        enum_map = {
            "type": RequirementType,
            "status": Status,
            "priority": Priority,
            "verification": Verification,
        }
        if field in enum_map:
            choices = [locale.code_to_label(field, e.value) for e in enum_map[field]]
            dlg = wx.SingleChoiceDialog(self, _("Select {field}").format(field=field), _("Edit"), choices)
            if dlg.ShowModal() == wx.ID_OK:
                label = dlg.GetStringSelection()
                code = locale.label_to_code(field, label)
                value = enum_map[field](code)
            else:
                value = None
            dlg.Destroy()
            return value
        dlg = wx.TextEntryDialog(self, _("New value for {field}").format(field=field), _("Edit"))
        if dlg.ShowModal() == wx.ID_OK:
            value = dlg.GetValue()
        else:
            value = None
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
            setattr(req, field, value)
            self.model.update(req)
            display = value.value if isinstance(value, Enum) else value
            self.list.SetItem(idx, column, str(display))
