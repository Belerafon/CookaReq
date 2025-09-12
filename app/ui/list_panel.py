"""Panel displaying requirements list and simple filters."""

from gettext import gettext as _

import wx
from wx.lib.agw import ultimatelistctrl as ULC
from wx.lib.mixins.listctrl import ColumnSorterMixin

from typing import Callable, List, Sequence, TYPE_CHECKING
from enum import Enum

from app.core.model import Priority, RequirementType, Status, Verification, Requirement
from .requirement_model import RequirementModel
from . import locale

if TYPE_CHECKING:  # pragma: no cover
    from wx import ListEvent, ContextMenuEvent


class _LabelsRenderer:
    """Simple renderer drawing labels as filled rectangles with text."""

    PADDING_X = 2
    PADDING_Y = 1
    GAP = 3

    def __init__(self, labels: list[str]):
        self.labels = labels

    def DrawSubItem(self, dc, rect, _line, _highlighted, _enabled):  # pragma: no cover - GUI
        x = rect.x + self.GAP
        dc.SetPen(wx.TRANSPARENT_PEN)
        for text in self.labels:
            tw, th = dc.GetTextExtent(text)
            w = tw + self.PADDING_X * 2
            h = th + self.PADDING_Y * 2
            y = rect.y + (rect.height - h) // 2
            dc.SetBrush(wx.Brush(wx.Colour(220, 220, 220)))
            dc.DrawRectangle(x, y, w, h)
            dc.DrawText(text, x + self.PADDING_X, y + self.PADDING_Y)
            x += w + self.GAP

    def GetLineHeight(self):  # pragma: no cover - GUI
        dc = wx.ScreenDC()
        _, h = dc.GetTextExtent("Hg")
        return h + self.PADDING_Y * 2

    def GetSubItemWidth(self):  # pragma: no cover - GUI
        dc = wx.ScreenDC()
        width = self.GAP
        for text in self.labels:
            tw, _ = dc.GetTextExtent(text)
            width += tw + self.PADDING_X * 2 + self.GAP
        return width


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
        on_derive: Callable[[int], None] | None = None,
    ):
        wx.Panel.__init__(self, parent)
        self.model = model if model is not None else RequirementModel()
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.search = wx.SearchCtrl(self)
        self.labels = wx.TextCtrl(self)
        self._label_choices: list[str] = []
        self._ignore_label_event = False
        self.match_any = wx.CheckBox(self, label=_("Match any labels"))
        self.is_derived = wx.CheckBox(self, label=_("Derived only"))
        self.has_derived = wx.CheckBox(self, label=_("Has derived"))
        self.suspect_only = wx.CheckBox(self, label=_("Suspect only"))
        # На Windows ``SearchCtrl`` рисует пустые белые квадраты вместо
        # иконок поиска/сброса, если битмапы не заданы. Загрузим стандартные
        # изображения через ``wx.ArtProvider`` и включим обе кнопки. Для
        # тестов, где используется упрощённый заглушечный ``wx``, все вызовы
        # защищены через ``hasattr``.
        if hasattr(wx, "ArtProvider"):
            size = (16, 16)
            if hasattr(self.search, "SetSearchBitmap"):
                bmp = wx.ArtProvider.GetBitmap(wx.ART_FIND, wx.ART_TOOLBAR, size)
                if bmp.IsOk():
                    self.search.SetSearchBitmap(bmp)
            if hasattr(self.search, "SetCancelBitmap"):
                bmp = wx.ArtProvider.GetBitmap(wx.ART_CROSS_MARK, wx.ART_TOOLBAR, size)
                if bmp.IsOk():
                    self.search.SetCancelBitmap(bmp)
        if hasattr(self.search, "ShowSearchButton"):
            self.search.ShowSearchButton(True)
        if hasattr(self.search, "ShowCancelButton"):
            self.search.ShowCancelButton(True)
        self.list = ULC.UltimateListCtrl(self, agwStyle=ULC.ULC_REPORT)
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
        sizer.Add(self.search, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self.labels, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self.match_any, 0, wx.ALL, 5)
        sizer.Add(self.is_derived, 0, wx.ALL, 5)
        sizer.Add(self.has_derived, 0, wx.ALL, 5)
        sizer.Add(self.suspect_only, 0, wx.ALL, 5)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(sizer)
        self.list.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self._on_right_click)
        self.list.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self.search.Bind(wx.EVT_TEXT, self._on_search)
        self.labels.Bind(wx.EVT_TEXT, self._on_labels_changed)
        self.match_any.Bind(wx.EVT_CHECKBOX, self._on_match_any)
        self.is_derived.Bind(wx.EVT_CHECKBOX, self._on_is_derived)
        self.has_derived.Bind(wx.EVT_CHECKBOX, self._on_has_derived)
        self.suspect_only.Bind(wx.EVT_CHECKBOX, self._on_suspect_only)

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
        on_derive: Callable[[int], None] | None = None,
    ) -> None:
        """Set callbacks for context menu actions."""
        if on_clone is not None:
            self._on_clone = on_clone
        if on_delete is not None:
            self._on_delete = on_delete
        if on_derive is not None:
            self._on_derive = on_derive

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
    def set_label_filter(self, labels: List[str]) -> None:
        """Filter by requirement labels."""
        self.model.set_label_filter(labels)
        self._refresh()

    def update_labels_list(self, labels: list[str]) -> None:
        """Update available labels and reapply current filter."""
        # keep unique order
        seen: dict[str, None] = {}
        for lbl in labels:
            seen.setdefault(lbl, None)
        self._label_choices = list(seen.keys())
        if hasattr(self.labels, "AutoComplete"):
            self.labels.AutoComplete(self._label_choices)
        self._apply_label_filter()

    def _sanitize_labels(self, raw: str) -> list[str]:
        labels: list[str] = []
        for part in [l.strip() for l in raw.split(",") if l.strip()]:
            if part in self._label_choices and part not in labels:
                labels.append(part)
        return labels

    def _apply_label_filter(self) -> None:
        labels = self._sanitize_labels(self.labels.GetValue())
        text = ", ".join(labels)
        if self.labels.GetValue() != text:
            self._ignore_label_event = True
            self.labels.SetValue(text)
            self._ignore_label_event = False
        self.set_label_filter(labels)

    def _on_labels_changed(self, event):  # pragma: no cover - simple event binding
        if self._ignore_label_event:
            if hasattr(event, "Skip"):
                event.Skip()
            return
        self._apply_label_filter()
        if hasattr(event, "Skip"):
            event.Skip()

    def _on_match_any(self, event):  # pragma: no cover - simple event binding
        self.model.set_label_match_all(not self.match_any.GetValue())
        if hasattr(event, "Skip"):
            event.Skip()

    def _on_is_derived(self, event):  # pragma: no cover - simple event binding
        self.model.set_is_derived(self.is_derived.GetValue())
        if hasattr(event, "Skip"):
            event.Skip()

    def _on_has_derived(self, event):  # pragma: no cover - simple event binding
        self.model.set_has_derived(self.has_derived.GetValue())
        if hasattr(event, "Skip"):
            event.Skip()

    def _on_suspect_only(self, event):  # pragma: no cover - simple event binding
        self.model.set_suspect_only(self.suspect_only.GetValue())
        if hasattr(event, "Skip"):
            event.Skip()

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
            title = getattr(req, "title", "")
            index = self.list.InsertStringItem(self.list.GetItemCount(), title)
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
                    self.list.SetStringItem(index, col, value)
                    continue
                if field == "derived_count":
                    count = len(self.derived_map.get(req.id, []))
                    self.list.SetStringItem(index, col, str(count))
                    continue
                value = getattr(req, field, "")
                if isinstance(value, Enum):
                    value = value.value
                if field == "labels" and isinstance(value, list):
                    item = ULC.UltimateListItem()
                    item.SetId(index)
                    item.SetColumn(col)
                    item.SetText("")
                    item.SetCustomRenderer(_LabelsRenderer(value))
                    self.list.SetItem(item)
                    continue
                self.list.SetStringItem(index, col, str(value))
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
        self.derived_map.setdefault(source_id, []).append(derived_id)

    def recalc_derived_map(self, requirements: list[Requirement]) -> None:
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
            self.list.SetStringItem(idx, column, str(display))
