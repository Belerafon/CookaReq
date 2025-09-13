"""Panel displaying requirements using wx.dataview.DataViewCtrl."""

from __future__ import annotations

from typing import Callable, List, Sequence, TYPE_CHECKING
from enum import Enum

import wx
import wx.dataview as dv

from ..i18n import _
from ..core.model import Priority, RequirementType, Status, Verification, Requirement
from ..core.labels import Label
from .requirement_model import RequirementModel
from .filter_dialog import FilterDialog
from . import locale

if TYPE_CHECKING:  # pragma: no cover
    from wx.dataview import DataViewColumn, DataViewEvent


class LabelBadgeRenderer(dv.DataViewCustomRenderer):
    """Custom renderer drawing colored label badges."""

    def __init__(self, panel: "ListPanel") -> None:
        super().__init__("string", dv.DATAVIEW_CELL_INERT)
        self.panel = panel
        self._value: list[str] = []

    def Render(self, rect: wx.Rect, dc: wx.DC, state: int) -> bool:  # pragma: no cover - GUI drawing
        x = rect.x + self.panel.LABEL_GAP
        for text in self._value:
            colour = self.panel._label_colors.get(text, "#dcdcdc")
            tw, th = dc.GetTextExtent(text)
            w = tw + self.panel.LABEL_PADDING_X * 2
            h = th + self.panel.LABEL_PADDING_Y * 2
            y = rect.y + (rect.height - h) // 2
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(wx.Colour(colour)))
            dc.DrawRectangle(x, y, w, h)
            dc.DrawText(text, x + self.panel.LABEL_PADDING_X, y + self.panel.LABEL_PADDING_Y)
            x += w + self.panel.LABEL_GAP
        return True

    def SetValue(self, value) -> bool:  # pragma: no cover - trivial
        self._value = list(value or [])
        return True

    def GetValue(self):  # pragma: no cover - trivial
        return self._value


class RequirementListModel(dv.DataViewIndexListModel):
    """Adapter between :class:`RequirementModel` and ``DataViewCtrl``."""

    def __init__(self, panel: "ListPanel") -> None:
        super().__init__(0)
        self.panel = panel

    # Basic structure -------------------------------------------------
    def GetColumnCount(self) -> int:  # pragma: no cover - simple forwarding
        return 1 + len(self.panel.columns)

    def GetRowCount(self) -> int:  # pragma: no cover - simple forwarding
        return len(self.panel.model.get_visible())

    def GetColumnType(self, col: int) -> str:  # pragma: no cover - uniform types
        return "string"

    # Value access ----------------------------------------------------
    def GetValueByRow(self, row: int, col: int):  # pragma: no cover - GUI adapter
        items = self.panel.model.get_visible()
        req = items[row]
        if col == 0:
            return getattr(req, "title", "")
        field = self.panel.columns[col - 1]
        if field == "derived_from":
            links = getattr(req, "derived_from", [])
            texts: list[str] = []
            for link in links:
                txt = str(getattr(link, "source_id", ""))
                if getattr(link, "suspect", False):
                    txt = f"!{txt}"
                texts.append(txt)
            return ", ".join(texts)
        if field in {"verifies", "relates"}:
            links = getattr(getattr(req, "links", None), field, [])
            texts: list[str] = []
            for link in links:
                txt = str(getattr(link, "source_id", ""))
                if getattr(link, "suspect", False):
                    txt = f"!{txt}"
                texts.append(txt)
            return ", ".join(texts)
        if field == "parent":
            link = getattr(req, "parent", None)
            if link:
                txt = str(getattr(link, "source_id", ""))
                if getattr(link, "suspect", False):
                    txt = f"!{txt}"
                return txt
            return ""
        if field == "derived_count":
            return str(len(self.panel.derived_map.get(req.id, [])))
        if field == "attachments":
            return ", ".join(getattr(a, "path", "") for a in getattr(req, "attachments", []))
        value = getattr(req, field, "")
        if isinstance(value, Enum):
            return locale.code_to_label(field, value.value)
        if field == "labels" and isinstance(value, list):
            return value
        return str(value)

    def SetValueByRow(self, value, row: int, col: int) -> bool:  # pragma: no cover - unused
        items = self.panel.model.get_visible()
        req = items[row]
        field = "title" if col == 0 else self.panel.columns[col - 1]
        setattr(req, field, value)
        self.panel.model.update(req)
        return True


class ListPanel(wx.Panel):
    """Panel with a filter button and DataViewCtrl list."""

    MIN_COL_WIDTH = 50
    MAX_COL_WIDTH = 1000
    LABEL_PADDING_X = 2
    LABEL_PADDING_Y = 1
    LABEL_GAP = 3

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
        super().__init__(parent)
        self.model = model if model is not None else RequirementModel()
        self._on_clone = on_clone
        self._on_delete = on_delete
        self._on_sort_changed = on_sort_changed
        self._on_derive = on_derive

        self.columns: List[str] = []
        self.current_filters: dict = {}
        self.derived_map: dict[int, List[int]] = {}
        self._sort_column = -1
        self._sort_ascending = True
        self._label_choices: list[str] = []
        self._label_colors: dict[str, str] = {}

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.filter_btn = wx.Button(self, label=_("Filters"))
        self.list = dv.DataViewCtrl(self, style=dv.DV_ROW_LINES | dv.DV_VERT_RULES)
        self.renderer: LabelBadgeRenderer | None = None
        self.dvc_model = RequirementListModel(self)
        self.list.AssociateModel(self.dvc_model)

        sizer.Add(self.filter_btn, 0, wx.ALL, 5)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(sizer)

        self.filter_btn.Bind(wx.EVT_BUTTON, self._on_filter)
        self.list.Bind(dv.EVT_DATAVIEW_COLUMN_HEADER_CLICK, self._on_col_click)

        self._setup_columns()

    # Columns ---------------------------------------------------------
    def _setup_columns(self) -> None:
        self.list.ClearColumns()
        self.list.AppendTextColumn(_("Title"), 0)
        for idx, field in enumerate(self.columns, start=1):

            if field == "labels":
                self.renderer = LabelBadgeRenderer(self)
                col = dv.DataViewColumn(_("Labels"), self.renderer, idx)
                self.list.AppendColumn(col)
            else:
                self.list.AppendTextColumn(field, idx)

            self.list.InsertColumn(idx, locale.field_label(field))
        ColumnSorterMixin.__init__(self, self.list.GetColumnCount())
        try:  # remove mixin's default binding and use our own
            self.list.Unbind(wx.EVT_LIST_COL_CLICK)
        except Exception:  # pragma: no cover - Unbind may not exist
            pass
        self.list.Bind(wx.EVT_LIST_COL_CLICK, self._on_col_click)


    def load_column_widths(self, config: wx.Config) -> None:
        count = self.list.GetColumnCount()
        for i in range(count):
            width = config.ReadInt(f"col_width_{i}", -1)
            if width != -1:
                width = max(self.MIN_COL_WIDTH, min(width, self.MAX_COL_WIDTH))
                self.list.GetColumn(i).SetWidth(width)

    def save_column_widths(self, config: wx.Config) -> None:
        count = self.list.GetColumnCount()
        for i in range(count):
            width = self.list.GetColumn(i).GetWidth()
            width = max(self.MIN_COL_WIDTH, min(width, self.MAX_COL_WIDTH))
            config.WriteInt(f"col_width_{i}", width)

    def load_column_order(self, config: wx.Config) -> None:
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
        try:  # pragma: no cover - depends on backend
            self.list.SetColumnsOrder(order)
        except Exception:
            pass

    def save_column_order(self, config: wx.Config) -> None:
        try:  # pragma: no cover - depends on backend
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

    def set_columns(self, fields: List[str]) -> None:
        self.columns = fields
        self._setup_columns()
        self._refresh()

    # Data ------------------------------------------------------------
    def set_requirements(
        self,
        requirements: list,
        derived_map: dict[int, List[int]] | None = None,
    ) -> None:
        self.model.set_requirements(requirements)
        if derived_map is None:
            derived_map = {}
            for req in requirements:
                for link in getattr(req, "derived_from", []):
                    derived_map.setdefault(link.source_id, []).append(req.id)
        self.derived_map = derived_map
        self._refresh()

    def _refresh(self) -> None:
        self.dvc_model.Reset(len(self.model.get_visible()))

    def refresh(self) -> None:
        self._refresh()

    # Filtering -------------------------------------------------------
    def apply_filters(self, filters: dict) -> None:
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

    def set_label_filter(self, labels: List[str]) -> None:
        self.apply_filters({"labels": labels})

    def set_search_query(self, query: str, fields: Sequence[str] | None = None) -> None:
        filters = {"query": query}
        if fields is not None:
            filters["fields"] = list(fields)
        self.apply_filters(filters)

    def update_labels_list(self, labels: list[Label]) -> None:
        self._label_colors = {lbl.name: lbl.color for lbl in labels}
        self._label_choices = sorted(self._label_colors)

    def _on_filter(self, event):  # pragma: no cover - simple event binding
        dlg = FilterDialog(self, labels=self._label_choices, values=self.current_filters)
        if dlg.ShowModal() == wx.ID_OK:
            self.apply_filters(dlg.get_filters())
        dlg.Destroy()
        if hasattr(event, "Skip"):
            event.Skip()

    # callbacks -------------------------------------------------------
    def set_handlers(
        self,
        *,
        on_clone: Callable[[int], None] | None = None,
        on_delete: Callable[[int], None] | None = None,
        on_derive: Callable[[int], None] | None = None,
    ) -> None:
        if on_clone is not None:
            self._on_clone = on_clone
        if on_delete is not None:
            self._on_delete = on_delete
        if on_derive is not None:
            self._on_derive = on_derive

    # Sorting ---------------------------------------------------------
    def _on_col_click(self, event: "DataViewEvent") -> None:  # pragma: no cover - GUI event
        col = event.GetColumn().GetModelColumn()
        if col == self._sort_column:
            ascending = not self._sort_ascending
        else:
            ascending = True
        self.sort(col, ascending)

    def sort(self, column: int, ascending: bool) -> None:
        self._sort_column = column
        self._sort_ascending = ascending
        field = "title" if column == 0 else self.columns[column - 1]
        self.model.sort(field, ascending)
        self._refresh()
        if self._on_sort_changed:
            self._on_sort_changed(self._sort_column, self._sort_ascending)

    # Context menu ----------------------------------------------------
    def _popup_context_menu(self, index: int, column: int | None) -> None:
        menu, _, _, _ = self._create_context_menu(index, column)
        self.PopupMenu(menu)
        menu.Destroy()

    def _on_context_menu(self, event):  # pragma: no cover - GUI event
        item = event.GetItem()
        if not item:
            return
        row = self.list.ItemToRow(item)
        col_obj = event.GetColumn()
        col = col_obj.GetModelColumn() if col_obj else None
        self._popup_context_menu(row, col)

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
        reqs = self.model.get_visible()
        req_id = reqs[index].id if index < len(reqs) else 0
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

    # Bulk edit -------------------------------------------------------
    def _get_selected_indices(self) -> List[int]:
        indices: List[int] = []
        items = self.list.GetSelections()
        for item in items:
            row = self.list.ItemToRow(item)
            if row != wx.NOT_FOUND:
                indices.append(row)
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
            label = locale.field_label(field)
            dlg = wx.SingleChoiceDialog(self, _("Select {field}").format(field=label), _("Edit"), choices)
            if dlg.ShowModal() == wx.ID_OK:
                label = dlg.GetStringSelection()
                code = locale.label_to_code(field, label)
                value = enum_map[field](code)
            else:
                value = None
            dlg.Destroy()
            return value
        label = locale.field_label(field)
        dlg = wx.TextEntryDialog(self, _("New value for {field}").format(field=label), _("Edit"))
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
        self._refresh()


__all__ = ["ListPanel", "LabelBadgeRenderer", "RequirementListModel"]

