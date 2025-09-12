"""Panel displaying requirements list and simple filters."""

from gettext import gettext as _

import wx
from wx.lib.mixins.listctrl import ColumnSorterMixin

from typing import Callable, List, Sequence, TYPE_CHECKING

from app.core.model import Priority, RequirementType, Status, Verification
from .requirement_model import RequirementModel
from . import locale

if TYPE_CHECKING:  # pragma: no cover
    from wx import ListEvent


class ListPanel(wx.Panel, ColumnSorterMixin):
    """Panel with a search box and list of requirement fields."""

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
    ):
        wx.Panel.__init__(self, parent)
        self.model = model if model is not None else RequirementModel()
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.search = wx.SearchCtrl(self)
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT)
        ColumnSorterMixin.__init__(self, 1)
        self.columns: List[str] = []
        self._on_clone = on_clone
        self._on_delete = on_delete
        self._on_sort_changed = on_sort_changed
        self._sort_column = -1
        self._sort_ascending = True
        self._setup_columns()
        sizer.Add(self.search, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(sizer)
        self.list.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self._on_right_click)
        self.search.Bind(wx.EVT_TEXT, self._on_search)

    # ColumnSorterMixin requirement
    def GetListCtrl(self):  # pragma: no cover - simple forwarding
        return self.list

    def GetSortImages(self):  # pragma: no cover - default arrows
        return (-1, -1)

    def set_handlers(
        self,
        *,
        on_clone: Callable[[int], None] | None = None,
        on_delete: Callable[[int], None] | None = None,
    ) -> None:
        """Set callbacks for context menu actions."""
        if on_clone is not None:
            self._on_clone = on_clone
        if on_delete is not None:
            self._on_delete = on_delete

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

    def set_columns(self, fields: List[str]) -> None:
        """Set additional columns (beyond Title) to display."""
        self.columns = fields
        self._setup_columns()
        # repopulate with existing requirements after changing columns
        self._refresh()

    def set_requirements(self, requirements: list) -> None:
        """Populate list control with requirement data via model."""
        self.model.set_requirements(requirements)
        self._refresh()

    # filtering -------------------------------------------------------
    def set_label_filter(self, labels: List[str]) -> None:
        """Filter by requirement labels."""
        self.model.set_label_filter(labels)
        self._refresh()

    def set_search_query(self, query: str, fields: Sequence[str] | None = None) -> None:
        """Apply text search across ``fields``."""
        self.model.set_search_query(query, fields)
        self._refresh()

    def _on_search(self, event):  # pragma: no cover - simple event binding
        self.set_search_query(self.search.GetValue())
        event.Skip()

    def _refresh(self) -> None:
        """Reload list control from the model."""
        items = self.model.get_visible()
        self.list.DeleteAllItems()
        for req in items:
            title = req.get("title", "")
            index = self.list.InsertItem(self.list.GetItemCount(), title)
            req_id = req.get("id", 0)
            try:
                self.list.SetItemData(index, int(req_id))
            except Exception:
                self.list.SetItemData(index, 0)
            for col, field in enumerate(self.columns, start=1):
                value = req.get(field, "")
                self.list.SetItem(index, col, str(value))

    def refresh(self) -> None:
        """Public wrapper to reload list control."""
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
    def _on_right_click(self, event: "ListEvent") -> None:  # pragma: no cover - GUI event
        x, y = event.GetPoint()
        _, _, col = self.list.HitTest((x, y))
        menu, _, _, _ = self._create_context_menu(event.GetIndex(), col)
        self.PopupMenu(menu)
        menu.Destroy()

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
        return menu, clone_item, delete_item, edit_item

    def _get_selected_indices(self) -> List[int]:
        indices: List[int] = []
        idx = self.list.GetFirstSelected()
        while idx != -1:
            indices.append(idx)
            idx = self.list.GetNextSelected(idx)
        return indices

    def _prompt_value(self, field: str) -> str | None:
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
                value = locale.label_to_code(field, label)
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
            req[field] = value
            self.model.update(req)
            self.list.SetItem(idx, column, str(value))
