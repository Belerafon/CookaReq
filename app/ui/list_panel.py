"""Panel displaying requirements list and simple filters."""

import wx

from typing import Callable, List, Sequence, TYPE_CHECKING

from app.core import search as core_search
from app.core.model import Priority, RequirementType, Status, Verification

if TYPE_CHECKING:  # pragma: no cover
    from wx import ListEvent


class ListPanel(wx.Panel):
    """Panel with a search box and list of requirement fields."""

    MIN_COL_WIDTH = 50
    MAX_COL_WIDTH = 1000

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_clone: Callable[[int], None] | None = None,
        on_delete: Callable[[int], None] | None = None,
    ):
        super().__init__(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.search = wx.SearchCtrl(self)
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT)
        self.columns: List[str] = []
        self._requirements: List = []
        self._all_requirements: List = []
        self._labels: List[str] = []
        self._query: str = ""
        self._fields: Sequence[str] | None = None
        self._on_clone = on_clone
        self._on_delete = on_delete
        self._sort_column = -1
        self._sort_ascending = True
        self._setup_columns()
        sizer.Add(self.search, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(sizer)
        self.list.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self._on_right_click)
        self.list.Bind(wx.EVT_LIST_COL_CLICK, self._on_col_click)
        self.search.Bind(wx.EVT_TEXT, self._on_search)

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
        self.list.InsertColumn(0, "Title")
        for idx, field in enumerate(self.columns, start=1):
            self.list.InsertColumn(idx, field)

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

    def set_columns(self, fields: List[str]) -> None:
        """Set additional columns (beyond Title) to display."""
        self.columns = fields
        self._setup_columns()
        # repopulate with existing requirements after changing columns
        self.set_requirements(self._requirements)

    def set_requirements(self, requirements: list) -> None:
        """Populate list control with requirement data."""
        self._all_requirements = requirements
        self._apply_filters()

    # filtering -------------------------------------------------------
    def set_label_filter(self, labels: List[str]) -> None:
        """Filter by requirement labels."""
        self._labels = labels
        self._apply_filters()

    def set_search_query(self, query: str, fields: Sequence[str] | None = None) -> None:
        """Apply text search across ``fields``."""
        self._query = query
        self._fields = fields
        self._apply_filters()

    def _on_search(self, event):  # pragma: no cover - simple event binding
        self.set_search_query(self.search.GetValue())
        event.Skip()

    def _apply_filters(self) -> None:
        """Apply current search and label filters to the requirement list."""
        self._requirements = core_search.search(
            self._all_requirements,
            labels=self._labels,
            query=self._query,
            fields=self._fields,
        )
        self.list.DeleteAllItems()
        for req in self._requirements:
            title = req.get("title") if isinstance(req, dict) else getattr(req, "title", "")
            index = self.list.InsertItem(self.list.GetItemCount(), title)
            for col, field in enumerate(self.columns, start=1):
                if isinstance(req, dict):
                    value = req.get(field, "")
                else:
                    value = getattr(req, field, "")
                self.list.SetItem(index, col, str(value))

    def _on_col_click(self, event: "ListEvent") -> None:  # pragma: no cover - GUI event
        col = event.GetColumn()
        if col == self._sort_column:
            self._sort_ascending = not self._sort_ascending
        else:
            self._sort_column = col
            self._sort_ascending = True
        field = "title" if col == 0 else self.columns[col - 1]
        def get_value(req):
            return req.get(field, "") if isinstance(req, dict) else getattr(req, field, "")
        sorted_reqs = sorted(
            self._requirements,
            key=get_value,
            reverse=not self._sort_ascending,
        )
        self.set_requirements(sorted_reqs)

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
        clone_item = menu.Append(wx.ID_ANY, "Клонировать")
        delete_item = menu.Append(wx.ID_ANY, "Удалить")
        field = self._field_from_column(column)
        edit_item = None
        if field and field != "title":
            edit_item = menu.Append(wx.ID_ANY, f"Изменить {field}")
            self.Bind(wx.EVT_MENU, lambda evt, c=column: self._on_edit_field(c), edit_item)
        if self._on_clone:
            self.Bind(wx.EVT_MENU, lambda evt: self._on_clone(index), clone_item)
        if self._on_delete:
            self.Bind(wx.EVT_MENU, lambda evt: self._on_delete(index), delete_item)
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
            choices = [e.value for e in enum_map[field]]
            dlg = wx.SingleChoiceDialog(self, f"Выберите {field}", "Редактирование", choices)
            if dlg.ShowModal() == wx.ID_OK:
                value = dlg.GetStringSelection()
            else:
                value = None
            dlg.Destroy()
            return value
        dlg = wx.TextEntryDialog(self, f"Новое значение для {field}", "Редактирование")
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
            if idx >= len(self._requirements):
                continue
            req = self._requirements[idx]
            if isinstance(req, dict):
                req[field] = value
            else:
                setattr(req, field, value)
            self.list.SetItem(idx, column, str(value))
