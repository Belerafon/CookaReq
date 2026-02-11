"""Panel displaying requirements list and simple filters."""
from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from enum import Enum
from typing import TYPE_CHECKING
from dataclasses import replace

import wx
from wx.lib.mixins.listctrl import ColumnSorterMixin

from .. import columns
from ..services.requirements import LabelDef, label_color, parse_rid, stable_color
from ..core.model import Requirement, Status
from ..core.markdown_utils import strip_markdown
from ..i18n import _
from ..log import logger
from . import locale
from .helpers import dip, inherit_background
from .label_selection_dialog import LabelSelectionDialog
from .enums import ENUMS
from .filter_dialog import FilterDialog
from .requirement_model import RequirementModel


def _apply_item_selection(list_ctrl: wx.ListCtrl, index: int, selected: bool) -> None:
    """Set ``index`` selection on ``list_ctrl`` while swallowing backend quirks."""
    select_flag = getattr(wx, "LIST_STATE_SELECTED", 0x0002)
    focus_flag = getattr(wx, "LIST_STATE_FOCUSED", 0x0001)
    mask = select_flag | focus_flag
    if hasattr(list_ctrl, "SetItemState"):
        with suppress(Exception):
            list_ctrl.SetItemState(index, mask if selected else 0, mask)
            return
    if hasattr(list_ctrl, "Select"):
        try:
            list_ctrl.Select(index, selected)
        except TypeError:
            if selected:
                list_ctrl.Select(index)
            else:
                with suppress(Exception):
                    list_ctrl.Select(index, False)
        except Exception:
            return
    if selected and hasattr(list_ctrl, "Focus"):
        with suppress(Exception):
            list_ctrl.Focus(index)


class RequirementsListCtrl(wx.ListCtrl):
    """List control with marquee selection starting from any cell."""

    _MARQUEE_THRESHOLD = 3

    def __init__(self, *args, **kwargs) -> None:
        """Initialise base list control wiring marquee interactions."""
        super().__init__(*args, **kwargs)
        self._marquee_origin: wx.Point | None = None
        self._marquee_active = False
        self._marquee_overlay: wx.Overlay | None = None
        self._marquee_base: set[int] = set()
        self._marquee_additive = False
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_MOTION, self._on_mouse_move)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_mouse_leave)
        self.Bind(wx.EVT_KILL_FOCUS, self._on_mouse_leave)

    def _selected_indices(self) -> list[int]:
        indices: list[int] = []
        idx = self.GetFirstSelected()
        while idx != -1:
            indices.append(idx)
            idx = self.GetNextSelected(idx)
        return indices

    def _clear_overlay(self) -> None:
        if not self._marquee_overlay:
            return
        dc = wx.ClientDC(self)
        overlay_dc = wx.DCOverlay(self._marquee_overlay, dc)
        overlay_dc.Clear()
        del overlay_dc
        self._marquee_overlay.Reset()
        self._marquee_overlay = None

    def _draw_overlay(self, rect: wx.Rect) -> None:
        if not hasattr(wx, "Overlay") or not hasattr(wx, "DCOverlay"):
            return
        if self._marquee_overlay is None:
            self._marquee_overlay = wx.Overlay()
        dc = wx.ClientDC(self)
        overlay_dc = wx.DCOverlay(self._marquee_overlay, dc)
        overlay_dc.Clear()
        pen = wx.Pen(wx.Colour(0, 120, 215), 1)
        brush = wx.Brush(wx.Colour(0, 120, 215, 40))
        dc.SetPen(pen)
        dc.SetBrush(brush)
        dc.DrawRectangle(rect)
        del overlay_dc

    def _update_marquee_selection(self, current: wx.Point) -> None:
        if self._marquee_origin is None:
            return
        left = min(self._marquee_origin.x, current.x)
        top = min(self._marquee_origin.y, current.y)
        right = max(self._marquee_origin.x, current.x)
        bottom = max(self._marquee_origin.y, current.y)
        rect = wx.Rect(left, top, max(right - left, 1), max(bottom - top, 1))
        self._draw_overlay(rect)
        selected: set[int] = set()
        for idx in range(self.GetItemCount()):
            try:
                item_rect = self.GetItemRect(idx)
            except Exception:
                continue
            if isinstance(item_rect, tuple):
                item_rect = item_rect[0]
            if not isinstance(item_rect, wx.Rect):
                continue
            if rect.Intersects(item_rect):
                selected.add(idx)
        if self._marquee_additive:
            selected.update(self._marquee_base)
        self._apply_selection(selected)

    def _apply_selection(self, indices: set[int]) -> None:
        count = self.GetItemCount()
        for idx in range(count):
            should_select = idx in indices
            try:
                is_selected = bool(
                    self.GetItemState(idx, getattr(wx, "LIST_STATE_SELECTED", 0x0002))
                    & getattr(wx, "LIST_STATE_SELECTED", 0x0002)
                )
            except Exception:
                is_selected = False
            if should_select == is_selected:
                continue
            _apply_item_selection(self, idx, should_select)
        if indices:
            focus_idx = min(indices)
            with suppress(Exception):
                self.Focus(focus_idx)

    def _start_marquee(self) -> None:
        self._marquee_active = True
        if not self._marquee_additive:
            for idx in list(self._marquee_base):
                _apply_item_selection(self, idx, False)
            self._marquee_base.clear()
        if not self.HasCapture():  # pragma: no cover - defensive
            with suppress(Exception):  # pragma: no cover - defensive
                self.CaptureMouse()

    def _finish_marquee(self) -> None:
        self._clear_overlay()
        self._marquee_origin = None
        self._marquee_base.clear()
        self._marquee_active = False
        if self.HasCapture():  # pragma: no cover - defensive
            with suppress(Exception):
                self.ReleaseMouse()

    def _on_left_down(self, event: wx.MouseEvent) -> None:
        self._marquee_origin = event.GetPosition()
        self._marquee_base = set(self._selected_indices())
        self._marquee_additive = event.ControlDown() or event.CmdDown() or event.ShiftDown()
        self._marquee_active = False
        self._clear_overlay()
        event.Skip()

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        if self._marquee_origin and self._marquee_active:
            self._update_marquee_selection(event.GetPosition())
            self._finish_marquee()
            return
        self._marquee_origin = None
        self._marquee_base.clear()
        self._marquee_active = False
        self._clear_overlay()
        event.Skip()

    def _on_mouse_move(self, event: wx.MouseEvent) -> None:
        if not self._marquee_origin or not event.LeftIsDown():
            event.Skip()
            return
        if not self._marquee_active:
            origin = self._marquee_origin
            pos = event.GetPosition()
            if abs(pos.x - origin.x) <= self._MARQUEE_THRESHOLD and abs(pos.y - origin.y) <= self._MARQUEE_THRESHOLD:
                event.Skip()
                return
            self._start_marquee()
        self._update_marquee_selection(event.GetPosition())
        event.Skip(False)

    def _on_mouse_leave(self, event: wx.Event) -> None:
        if not self._marquee_origin:
            event.Skip()
            return
        left_down = False
        if hasattr(event, "LeftIsDown"):
            try:
                left_down = bool(event.LeftIsDown())
            except Exception:
                left_down = False
        else:
            try:
                ms = wx.GetMouseState()
                if hasattr(ms, "LeftIsDown"):
                    left_down = bool(ms.LeftIsDown())
                else:
                    left_down = bool(getattr(ms, "leftDown", False))
            except Exception:
                left_down = False
        if not left_down:
            self._finish_marquee()
        event.Skip()

if TYPE_CHECKING:
    from ..config import ConfigManager
    from .controllers import DocumentsController

if TYPE_CHECKING:  # pragma: no cover
    from wx import ContextMenuEvent, ListEvent


class ListPanel(wx.Panel, ColumnSorterMixin):
    """Panel with a filter button and list of requirement fields."""

    MIN_COL_WIDTH = 50
    MAX_COL_WIDTH = 1000
    STATEMENT_PREVIEW_LIMIT = 160

    def __init__(
        self,
        parent: wx.Window,
        *,
        model: RequirementModel | None = None,
        docs_controller: DocumentsController | None = None,
        on_clone: Callable[[int], None] | None = None,
        on_transfer: Callable[[Sequence[int]], None] | None = None,
        on_delete: Callable[[int], None] | None = None,
        on_delete_many: Callable[[Sequence[int]], None] | None = None,
        on_sort_changed: Callable[[int, bool], None] | None = None,
        on_derive: Callable[[int], None] | None = None,
        on_new_requirement: Callable[[], None] | None = None,
    ):
        """Initialize list view and controls for requirements."""
        wx.Panel.__init__(self, parent)
        inherit_background(self, parent)
        self.model = model if model is not None else RequirementModel()
        sizer = wx.BoxSizer(wx.VERTICAL)
        vertical_pad = dip(self, 5)
        orient = getattr(wx, "HORIZONTAL", 0)
        right = getattr(wx, "RIGHT", 0)
        top_flag = getattr(wx, "TOP", 0)
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
        btn_row.Add(self.filter_btn, 0, right, vertical_pad)
        btn_row.Add(self.reset_btn, 0, right, vertical_pad)
        btn_row.Add(self.filter_summary, 0, align_center, 0)
        self.list = RequirementsListCtrl(self, style=wx.LC_REPORT)
        if hasattr(self.list, "SetExtraStyle"):
            extra = getattr(wx, "LC_EX_SUBITEMIMAGES", 0)
            if extra:
                with suppress(Exception):  # pragma: no cover - backend quirks
                    self.list.SetExtraStyle(self.list.GetExtraStyle() | extra)
        self._labels: list[LabelDef] = []
        self._labels_allow_freeform = False
        self.current_filters: dict = {}
        self._image_list: wx.ImageList | None = None
        self._label_images: dict[tuple[str, ...], int] = {}
        self._rid_lookup: dict[str, Requirement] = {}
        self._doc_titles: dict[str, str] = {}
        self._link_display_cache: dict[str, str] = {}
        ColumnSorterMixin.__init__(self, 1)
        self.columns: list[str] = []
        self._on_clone = on_clone
        self._on_transfer = on_transfer
        self._on_delete = on_delete
        self._on_delete_many = on_delete_many
        self._on_sort_changed = on_sort_changed
        self._on_derive = on_derive
        self._on_new_requirement = on_new_requirement
        self.derived_map: dict[str, list[int]] = {}
        self._sort_column = -1
        self._sort_ascending = True
        self._docs_controller = docs_controller
        self._current_doc_prefix: str | None = None
        self._context_menu_open = False
        self._setup_columns()
        sizer.Add(btn_row, 0, wx.EXPAND, 0)
        sizer.Add(self.list, 1, wx.EXPAND | top_flag, vertical_pad)
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
        on_transfer: Callable[[Sequence[int]], None] | None = None,
        on_delete: Callable[[int], None] | None = None,
        on_delete_many: Callable[[Sequence[int]], None] | None = None,
        on_derive: Callable[[int], None] | None = None,
        on_new_requirement: Callable[[], None] | None = None,
    ) -> None:
        """Set callbacks for context menu actions."""
        if on_clone is not None:
            self._on_clone = on_clone
        if on_transfer is not None:
            self._on_transfer = on_transfer
        if on_delete is not None:
            self._on_delete = on_delete
        if on_delete_many is not None:
            self._on_delete_many = on_delete_many
        if on_derive is not None:
            self._on_derive = on_derive
        if on_new_requirement is not None:
            self._on_new_requirement = on_new_requirement

    def set_documents_controller(
        self, controller: DocumentsController | None
    ) -> None:
        """Set documents controller used for persistence."""
        self._docs_controller = controller
        self._doc_titles = {}
        self._link_display_cache.clear()
        if controller is not None:
            with suppress(Exception):
                all_requirements = self.model.get_all()
            if isinstance(all_requirements, list):
                self._rebuild_rid_lookup(all_requirements)

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

    def _doc_title_for_prefix(self, prefix: str) -> str:
        if not prefix:
            return ""
        if prefix in self._doc_titles:
            return self._doc_titles[prefix]
        if self._docs_controller:
            doc = self._docs_controller.documents.get(prefix)
            if doc:
                self._doc_titles[prefix] = doc.title
                return doc.title
        self._doc_titles[prefix] = ""
        return ""

    def _rebuild_rid_lookup(self, requirements: list[Requirement]) -> None:
        self._rid_lookup = {}
        self._link_display_cache.clear()
        self._doc_titles = {}
        for req in requirements:
            rid = getattr(req, "rid", "")
            if rid:
                self._rid_lookup[rid] = req
            prefix = getattr(req, "doc_prefix", "")
            if prefix and prefix not in self._doc_titles:
                self._doc_titles[prefix] = self._doc_title_for_prefix(prefix)

    def _link_display_text(self, rid: str) -> str:
        rid = str(rid or "").strip()
        if not rid:
            return ""
        cached = self._link_display_cache.get(rid)
        if cached is not None:
            return cached
        title = ""
        doc_title = ""
        req = self._rid_lookup.get(rid)
        if req is not None:
            title = getattr(req, "title", "")
            doc_title = self._doc_title_for_prefix(getattr(req, "doc_prefix", ""))
        elif self._docs_controller:
            try:
                prefix, item_id = parse_rid(rid)
            except ValueError:
                self._link_display_cache[rid] = rid
                return rid
            service = getattr(self._docs_controller, "service", None)
            if service:
                doc_title = self._doc_title_for_prefix(prefix)
                try:
                    data, _mtime = service.load_item(prefix, item_id)
                except Exception:
                    logger.exception("Failed to load linked requirement %s", rid)
                else:
                    title = str(data.get("title", ""))
        base = rid
        if title:
            base = f"{rid} — {title}"
        if doc_title and doc_title not in base:
            base = f"{base} ({doc_title})"
        self._link_display_cache[rid] = base
        return base

    def _first_parent_text(self, req: Requirement) -> str:
        links = getattr(req, "links", []) or []
        if not links:
            return ""
        parent = links[0]
        rid = getattr(parent, "rid", str(parent))
        return self._link_display_text(rid)

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
        for name, w in zip(names, widths, strict=True):
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
            width = config.get_column_width(i, default=-1)
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
            config.set_column_width(i, width)

    def _default_column_width(self, field: str) -> int:
        """Return sensible default width for a given column field."""
        return columns.default_column_width(field)

    def load_column_order(self, config: ConfigManager) -> None:
        """Restore column ordering from config."""
        names = config.get_column_order()
        if not names:
            return
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
        config.set_column_order(names)

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
        self._rebuild_rid_lookup(self.model.get_all())
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

    def update_labels_list(self, labels: list[LabelDef], allow_freeform: bool) -> None:
        """Update available labels and whether custom labels are allowed."""
        self._labels = [LabelDef(lbl.key, lbl.title, lbl.color) for lbl in labels]
        self._labels_allow_freeform = bool(allow_freeform)

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

    def has_active_filters(self) -> bool:
        """Return ``True`` when the list currently has any active filters."""
        return self._has_active_filters()

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
                is_unsaved = bool(getattr(self.model, "is_unsaved", None)) and self.model.is_unsaved(req)
                if field == "title":
                    title = getattr(req, "title", "")
                    derived = bool(getattr(req, "links", []))
                    parts: list[str] = []
                    if is_unsaved:
                        parts.append("*")
                    if derived:
                        parts.append("↳")
                    if title:
                        parts.append(title)
                    display = " ".join(parts)
                    self.list.SetItem(index, col, display)
                    continue
                if field == "labels":
                    value = getattr(req, "labels", [])
                    self._set_label_image(index, col, value)
                    continue
                if field == "id":
                    value = getattr(req, "id", "")
                    display = f"* {value}".strip() if is_unsaved else str(value)
                    self.list.SetItem(index, col, display)
                    continue
                if field == "derived_from":
                    value = self._first_parent_text(req)
                    self.list.SetItem(index, col, value)
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
                if field == "statement":
                    value = self._statement_preview_text(getattr(req, "statement", ""))
                    self.list.SetItem(index, col, value)
                    continue
                value = getattr(req, field, "")
                if isinstance(value, Enum):
                    value = locale.code_to_label(field, value.value)
                self.list.SetItem(index, col, str(value))

    def _statement_preview_text(self, value: str) -> str:
        text = strip_markdown(str(value))
        text = " ".join(text.split())
        if len(text) <= self.STATEMENT_PREVIEW_LIMIT:
            return text
        trimmed = text[: self.STATEMENT_PREVIEW_LIMIT - 1].rstrip()
        return f"{trimmed}…"

    def refresh(self, *, select_id: int | None = None) -> None:
        """Public wrapper to reload list control.

        When ``select_id`` is provided, the list selects the matching
        requirement and scrolls to it after reloading the contents.
        """
        self._refresh()
        if select_id is not None:
            self.focus_requirement(select_id)

    def focus_requirement(self, req_id: int) -> None:
        """Select and ensure visibility of requirement ``req_id``."""
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

        if hasattr(self.list, "Focus"):
            with suppress(Exception):
                self.list.Focus(target_index)
        if hasattr(self.list, "EnsureVisible"):
            with suppress(Exception):
                self.list.EnsureVisible(target_index)

    def _set_item_selected(self, index: int, selected: bool) -> None:
        """Apply selection state without propagating backend errors."""
        _apply_item_selection(self.list, index, selected)

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
        self._rebuild_rid_lookup(requirements)
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
        if self._context_menu_open:
            return
        menu, _, _, _, _ = self._create_context_menu(index, column)
        if not menu.GetMenuItemCount():
            menu.Destroy()
            return
        self._context_menu_open = True
        try:
            self.PopupMenu(menu)
        finally:
            menu.Destroy()
            reset = getattr(wx, "CallAfter", None)
            if callable(reset):
                reset(self._reset_context_menu_flag)
            else:  # pragma: no cover - fallback for minimal wx builds
                self._reset_context_menu_flag()

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
            self._popup_context_menu(index, col)
            return
        self.list.Select(index)
        self._popup_context_menu(index, col)

    def _field_from_column(self, col: int | None) -> str | None:
        if col is None or col < 0 or col >= len(self._field_order):
            return None
        return self._field_order[col]

    def _reset_context_menu_flag(self) -> None:
        """Allow opening the context menu again after the current popup closes."""
        self._context_menu_open = False

    def _create_context_menu(self, index: int, column: int | None):
        menu = wx.Menu()
        selected_indices = self._get_selected_indices()
        if index != wx.NOT_FOUND and (not selected_indices or index not in selected_indices):
            selected_indices = [index]
        if index == wx.NOT_FOUND:
            selected_indices = []
        single_selection = len(selected_indices) == 1
        selected_ids = self._indices_to_ids(selected_indices)
        req_id = selected_ids[0] if selected_ids else None
        derive_item = clone_item = transfer_item = None
        create_item = None
        if self._on_new_requirement is not None:
            create_item = menu.Append(wx.ID_NEW, _("&New Requirement\tCtrl+N"))
        if single_selection:
            derive_item = menu.Append(wx.ID_ANY, _("Derive"))
            clone_item = menu.Append(wx.ID_ANY, _("Clone"))
        delete_item = None
        if selected_ids:
            delete_item = menu.Append(wx.ID_ANY, _("Delete"))
        status_menu = None
        labels_item = None
        if selected_ids:
            status_menu = self._build_status_menu(selected_ids)
            labels_item = menu.Append(wx.ID_ANY, _("Set labels…"))
            menu.Bind(
                wx.EVT_MENU,
                lambda _evt, ids=tuple(selected_ids): self._show_labels_dialog(ids),
                labels_item,
            )
        if status_menu is not None:
            label = _("Set status for selected") if len(selected_ids) > 1 else _("Set status")
            menu.AppendSubMenu(status_menu, label)
        field = self._field_from_column(column)
        edit_item = None
        if field and field not in {"title", "status"}:
            edit_item = menu.Append(wx.ID_ANY, _("Edit {field}").format(field=field))
            menu.Bind(
                wx.EVT_MENU,
                lambda _evt, c=column: self._on_edit_field(c),
                edit_item,
            )
        if clone_item and self._on_clone and req_id is not None:
            menu.Bind(wx.EVT_MENU, lambda _evt, i=req_id: self._on_clone(i), clone_item)
        if self._on_transfer and selected_ids:
            transfer_item = menu.Append(wx.ID_ANY, _("Move or copy…"))
            menu.Bind(
                wx.EVT_MENU,
                lambda _evt, ids=tuple(selected_ids): self._on_transfer(ids),
                transfer_item,
            )
        if len(selected_ids) > 1 and delete_item is not None:
            if self._on_delete_many:
                menu.Bind(
                    wx.EVT_MENU,
                    lambda _evt, ids=tuple(selected_ids): self._on_delete_many(ids),
                    delete_item,
                )
            elif self._on_delete:
                menu.Bind(
                    wx.EVT_MENU,
                    lambda _evt, ids=tuple(selected_ids): self._invoke_delete_each(ids),
                    delete_item,
                )
        elif self._on_delete and req_id is not None and delete_item is not None:
            menu.Bind(
                wx.EVT_MENU,
                lambda _evt, i=req_id: self._on_delete(i),
                delete_item,
            )
        if create_item is not None:
            menu.Bind(wx.EVT_MENU, lambda _evt: self._on_new_requirement(), create_item)
        if derive_item and self._on_derive and req_id is not None:
            menu.Bind(
                wx.EVT_MENU,
                lambda _evt, i=req_id: self._on_derive(i),
                derive_item,
            )
        base_count = menu.GetMenuItemCount()
        total_items = 0
        try:
            total_items = self.list.GetItemCount()
        except Exception:
            total_items = 0
        if total_items:
            select_all_item = menu.Insert(0, wx.ID_SELECTALL, _("Select all"))
            if base_count:
                menu.InsertSeparator(1)
            menu.Bind(
                wx.EVT_MENU,
                lambda _evt: self._select_all_requirements(),
                id=select_all_item.GetId(),
            )
        return menu, clone_item, delete_item, edit_item, transfer_item

    def _build_status_menu(self, selected_ids: Sequence[int]) -> wx.Menu | None:
        if not selected_ids:
            return None

        menu = wx.Menu()
        for status in Status:
            label = locale.code_to_label("status", status.value)
            item = menu.Append(wx.ID_ANY, label)
            menu.Bind(
                wx.EVT_MENU,
                lambda _evt, s=status, ids=tuple(selected_ids): self._set_status(ids, s),
                item,
            )
        return menu

    def _get_selected_indices(self) -> list[int]:
        indices: list[int] = []
        idx = self.list.GetFirstSelected()
        while idx != -1:
            indices.append(idx)
            idx = self.list.GetNextSelected(idx)
        return indices

    @contextmanager
    def _suspend_selection_events(self) -> Iterator[bool]:
        """Temporarily block selection events from bubbling to observers."""

        evt_handler_cls = getattr(wx, "EvtHandler", None)
        push = getattr(self.list, "PushEventHandler", None)
        pop = getattr(self.list, "PopEventHandler", None)
        if evt_handler_cls is None or not callable(push) or not callable(pop):
            yield False
            return

        blocker = evt_handler_cls()

        def _block(event: wx.Event) -> None:
            event.StopPropagation()

        try:
            blocker.Bind(wx.EVT_LIST_ITEM_SELECTED, _block)
            blocker.Bind(wx.EVT_LIST_ITEM_DESELECTED, _block)
        except Exception:
            yield False
            return

        try:
            push(blocker)
        except Exception:
            yield False
            return

        try:
            yield True
        finally:
            with suppress(Exception):
                pop(True)

    def _post_selection_event(self, index: int) -> None:
        """Notify listeners about a selection change for ``index``."""

        if index < 0:
            return
        list_id = getattr(self.list, "GetId", None)
        if not callable(list_id):
            return
        event_type = getattr(wx, "wxEVT_LIST_ITEM_SELECTED", None)
        event_cls = getattr(wx, "ListEvent", None)
        post_event = getattr(wx, "PostEvent", None)
        if event_type is None or event_cls is None or post_event is None:
            return
        try:
            event = event_cls(event_type, list_id())
        except Exception:
            return
        event.SetEventObject(self.list)
        set_index = getattr(event, "SetIndex", None)
        if callable(set_index):
            try:
                set_index(index)
            except Exception:
                pass
        else:  # pragma: no cover - compatibility with exotic backends
            try:
                event.m_itemIndex = index
            except Exception:
                pass
        get_item = getattr(self.list, "GetItem", None)
        if callable(get_item):
            with suppress(Exception):
                item = get_item(index)
                set_item = getattr(event, "SetItem", None)
                if callable(set_item):
                    set_item(item)
                else:  # pragma: no cover - compatibility with exotic backends
                    event.m_item = item
        post_event(self.list, event)

    def _select_all_requirements(self) -> None:
        try:
            count = self.list.GetItemCount()
        except Exception:
            return
        if count <= 0:
            return
        existing = self._get_selected_indices()
        existing_set = set(existing)
        if existing_set and len(existing_set) >= count:
            return
        focus_index = existing[0] if existing else 0
        should_emit_event = not existing_set
        with self._suspend_selection_events() as events_blocked:
            handled = False
            if hasattr(self.list, "SelectAll"):
                select_all = getattr(self.list, "SelectAll")
                if callable(select_all):
                    try:
                        select_all()
                        handled = True
                    except Exception:
                        handled = False
            if not handled:
                thaw_handler: Callable[[], None] | None = None
                freeze = getattr(self.list, "Freeze", None)
                thaw = getattr(self.list, "Thaw", None)
                if callable(freeze) and callable(thaw):
                    try:
                        freeze()
                    except Exception:
                        thaw = None
                    else:
                        thaw_handler = thaw
                try:
                    for idx in range(count):
                        if idx in existing_set:
                            continue
                        self._set_item_selected(idx, True)
                finally:
                    if thaw_handler is not None:
                        with suppress(Exception):
                            thaw_handler()
        if should_emit_event and events_blocked and 0 <= focus_index < count:
            self._post_selection_event(focus_index)
        if hasattr(self.list, "Focus") and 0 <= focus_index < count:
            with suppress(Exception):
                self.list.Focus(focus_index)
        if hasattr(self.list, "EnsureVisible") and 0 <= focus_index < count:
            with suppress(Exception):
                self.list.EnsureVisible(focus_index)
        if hasattr(self.list, "SetFocus"):
            with suppress(Exception):
                self.list.SetFocus()

    def get_selected_ids(self) -> list[int]:
        """Return identifiers of currently selected requirements."""
        ordered: list[int] = []
        seen: set[int] = set()
        for req_id in self._indices_to_ids(self._get_selected_indices()):
            if req_id in seen:
                continue
            seen.add(req_id)
            ordered.append(req_id)
        return ordered

    def _indices_to_ids(self, indices: Sequence[int]) -> list[int]:
        ids: list[int] = []
        for idx in indices:
            if idx == wx.NOT_FOUND:
                continue
            try:
                raw_id = self.list.GetItemData(idx)
            except Exception:
                continue
            try:
                ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue
        return ids

    def _invoke_delete_each(self, req_ids: Sequence[int]) -> None:
        if not self._on_delete:
            return
        for req_id in req_ids:
            self._on_delete(req_id)

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

    def _ordered_unique_ids(self, req_ids: Sequence[int]) -> list[int]:
        """Return ``req_ids`` without duplicates preserving order."""
        unique: list[int] = []
        seen: set[int] = set()
        for req_id in req_ids:
            if not isinstance(req_id, int):
                continue
            if req_id in seen:
                continue
            seen.add(req_id)
            unique.append(req_id)
        return unique

    def _set_status(self, req_ids: Sequence[int], status: Status) -> None:
        unique_order = self._ordered_unique_ids(req_ids)

        updates: list[Requirement] = []
        for req_id in unique_order:
            requirement = self.model.get_by_id(
                req_id, doc_prefix=self._current_doc_prefix
            )
            if requirement is None:
                continue
            if getattr(requirement, "status", None) == status:
                continue
            updates.append(replace(requirement, status=status))

        if not updates:
            return

        self.model.update_many(updates)
        for updated in updates:
            self._persist_requirement(updated)
        self._refresh()
        self._restore_selection(unique_order)

    def _show_labels_dialog(self, req_ids: Sequence[int]) -> None:
        """Open dialog to adjust labels for ``req_ids``."""
        unique_order = self._ordered_unique_ids(req_ids)
        if not unique_order:
            return

        requirements: list[Requirement] = []
        existing_labels: list[list[str]] = []
        for req_id in unique_order:
            requirement = self.model.get_by_id(
                req_id, doc_prefix=self._current_doc_prefix
            )
            if requirement is None:
                continue
            requirements.append(requirement)
            labels = list(getattr(requirement, "labels", []) or [])
            existing_labels.append(labels)

        if not requirements:
            return

        available = [LabelDef(lbl.key, lbl.title, lbl.color) for lbl in self._labels]
        known_keys = {lbl.key for lbl in available}
        for labels in existing_labels:
            for name in labels:
                if name in known_keys:
                    continue
                known_keys.add(name)
                available.append(LabelDef(name, name, stable_color(name)))

        initial: list[str] = []
        if existing_labels:
            common = list(dict.fromkeys(existing_labels[0]))
            for labels in existing_labels[1:]:
                common = [name for name in common if name in labels]
            initial = common

        dlg = LabelSelectionDialog(
            self,
            labels=available,
            selected=initial,
            allow_freeform=self._labels_allow_freeform,
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            chosen = dlg.get_selected()
        finally:
            dlg.Destroy()

        self._set_labels(unique_order, chosen)

    def _set_labels(self, req_ids: Sequence[int], labels: Sequence[str]) -> None:
        """Apply ``labels`` to requirements identified by ``req_ids``."""
        unique_order = self._ordered_unique_ids(req_ids)
        if not unique_order:
            return

        sanitized: list[str] = []
        seen: set[str] = set()
        for label in labels:
            if not isinstance(label, str):
                continue
            text = label.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            sanitized.append(text)

        updates: list[Requirement] = []
        for req_id in unique_order:
            requirement = self.model.get_by_id(
                req_id, doc_prefix=self._current_doc_prefix
            )
            if requirement is None:
                continue
            current = list(getattr(requirement, "labels", []) or [])
            if current == sanitized:
                continue
            updates.append(replace(requirement, labels=list(sanitized)))

        if not updates:
            return

        self.model.update_many(updates)
        for updated in updates:
            self._persist_requirement(updated)

        self._refresh()
        self._restore_selection(unique_order)

    def _restore_selection(self, req_ids: Sequence[int]) -> None:
        if not req_ids:
            return

        desired = [req_id for req_id in req_ids if isinstance(req_id, int)]
        if not desired:
            return

        desired_set = set(desired)
        focus_index: int | None = None
        for idx in range(self.list.GetItemCount()):
            try:
                raw_id = self.list.GetItemData(idx)
            except Exception:
                continue
            try:
                req_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            should_select = req_id in desired_set
            self._set_item_selected(idx, should_select)
            if should_select and focus_index is None and req_id == desired[0]:
                focus_index = idx

        if focus_index is not None:
            if hasattr(self.list, "Focus"):
                with suppress(Exception):
                    self.list.Focus(focus_index)
            if hasattr(self.list, "EnsureVisible"):
                with suppress(Exception):
                    self.list.EnsureVisible(focus_index)

    def _persist_requirement(self, req: Requirement) -> None:
        """Persist edited ``req`` if controller and document are available."""
        if not self._docs_controller or not self._current_doc_prefix:
            return
        try:
            self._docs_controller.save_requirement(self._current_doc_prefix, req)
            if hasattr(self.model, "clear_unsaved"):
                self.model.clear_unsaved(req)
        except Exception:  # pragma: no cover - log and continue
            rid = getattr(req, "rid", req.id)
            logger.exception("Failed to save requirement %s", rid)
