"""Panel displaying requirements list and simple filters."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from contextlib import suppress
from enum import Enum
from typing import TYPE_CHECKING, ClassVar

import wx
from wx.lib.mixins.listctrl import ColumnSorterMixin

from ..core.document_store import LabelDef, label_color, load_item, parse_rid, stable_color
from ..core.model import Requirement
from ..i18n import _
from ..log import logger
from . import locale
from .helpers import dip, inherit_background
from .enums import ENUMS
from .filter_dialog import FilterDialog
from .requirement_model import RequirementModel
from ..settings import MAX_LIST_PANEL_DEBUG_LEVEL

if TYPE_CHECKING:
    from ..config import ConfigManager
    from .controllers import DocumentsController

if TYPE_CHECKING:  # pragma: no cover
    from wx import ContextMenuEvent, ListEvent


@dataclass(frozen=True)
class ListPanelDebugProfile:
    """Feature toggles for :class:`ListPanel` based on debug level."""

    FEATURE_LABELS: ClassVar[dict[str, str]] = {
        "context_menu": "context menu",
        "label_bitmaps": "label bitmaps",
        "derived_formatting": "derived formatting",
        "filter_summary": "filter summary",
        "filter_button": "filter button",
        "filter_logic": "filter logic",
        "column_persistence": "column persistence",
        "extra_columns": "extra columns",
        "sorting": "sorting",
        "derived_map": "derived map",
        "doc_lookup": "document lookup",
        "subitem_images": "subitem images",
        "inherit_background": "background inheritance",
        "sorter_mixin": "column sorter mixin",
        "rich_rendering": "rich rendering",
        "documents_integration": "documents integration",
        "callbacks": "action callbacks",
        "selection_events": "list selection events",
        "model_driven": "model-driven refresh",
        "model_cache": "requirement model cache",
        "report_width_retry": "report width retry queue",
        "report_column_widths": "report column width enforcement",
        "report_list_item": "report header listitem setup",
        "report_clear_all": "report ClearAll column reset",
        "report_batch_delete": "report bulk DeleteAllItems",
        "report_column_align": "report column alignment",
        "report_lazy_refresh": "implicit report refresh",
        "report_placeholder_text": "report placeholder insert",
        "report_column0_setitem": "report column-0 SetItem",
        "report_image_list": "report image list attachment",
        "report_item_images": "report item image management",
        "report_item_data": "report item client data",
        "report_refresh_items": "report RefreshItems fallback",
        "report_immediate_refresh": "report immediate repaint",
        "report_style": "report-style layout",
        "sizer_layout": "panel box sizer",
    }

    level: int
    context_menu: bool
    label_bitmaps: bool
    derived_formatting: bool
    filter_summary: bool
    filter_button: bool
    filter_logic: bool
    column_persistence: bool
    extra_columns: bool
    sorting: bool
    derived_map: bool
    doc_lookup: bool
    subitem_images: bool
    inherit_background: bool
    sorter_mixin: bool
    rich_rendering: bool
    documents_integration: bool
    callbacks: bool
    selection_events: bool
    model_driven: bool
    model_cache: bool
    report_width_retry: bool
    report_column_widths: bool
    report_list_item: bool
    report_clear_all: bool
    report_batch_delete: bool
    report_column_align: bool
    report_lazy_refresh: bool
    report_placeholder_text: bool
    report_column0_setitem: bool
    report_image_list: bool
    report_item_images: bool
    report_item_data: bool
    report_refresh_items: bool
    report_immediate_refresh: bool
    report_style: bool
    sizer_layout: bool

    @classmethod
    def from_level(cls, level: int | None) -> "ListPanelDebugProfile":
        """Return profile for ``level`` clamped to supported range."""

        raw = 0 if level is None else int(level)
        clamped = max(0, min(MAX_LIST_PANEL_DEBUG_LEVEL, raw))
        return cls(
            level=clamped,
            context_menu=clamped < 1,
            label_bitmaps=clamped < 2,
            derived_formatting=clamped < 3,
            filter_summary=clamped < 4,
            filter_button=clamped < 5,
            filter_logic=clamped < 5,
            column_persistence=clamped < 6,
            extra_columns=clamped < 7,
            sorting=clamped < 8,
            derived_map=clamped < 9,
            doc_lookup=clamped < 10,
            subitem_images=clamped < 11,
            inherit_background=clamped < 12,
            sorter_mixin=clamped < 13,
            rich_rendering=clamped < 14,
            documents_integration=clamped < 15,
            callbacks=clamped < 16,
            selection_events=clamped < 17,
            model_driven=clamped < 18,
            model_cache=clamped < 19,
            report_width_retry=clamped < 20,
            report_column_widths=clamped < 21,
            report_list_item=clamped < 22,
            report_clear_all=clamped < 23,
            report_batch_delete=clamped < 24,
            report_column_align=clamped < 25,
            report_lazy_refresh=clamped < 26,
            report_placeholder_text=clamped < 27,
            report_column0_setitem=clamped < 28,
            report_image_list=clamped < 29,
            report_item_images=clamped < 30,
            report_item_data=clamped < 31,
            report_refresh_items=clamped < 32,
            report_immediate_refresh=clamped < 33,
            report_style=clamped < 34,
            sizer_layout=clamped < 35,
        )

    def disabled_features(self) -> list[str]:
        """Return human-readable names of features disabled at this level."""

        disabled: list[str] = []
        for attr, label in self.FEATURE_LABELS.items():
            if not getattr(self, attr):
                disabled.append(label)
        return disabled


class ListPanel(wx.Panel, ColumnSorterMixin):
    """Panel with a filter button and list of requirement fields."""

    DIAGNOSTIC_LOG_THRESHOLD = 19
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
        debug_level: int | None = None,
    ):
        """Initialize list view and controls for requirements."""
        wx.Panel.__init__(self, parent)
        self.debug = ListPanelDebugProfile.from_level(debug_level)
        self.debug_level = self.debug.level
        self._diagnostic_logging = self.debug_level >= self.DIAGNOSTIC_LOG_THRESHOLD
        if self.debug.inherit_background:
            inherit_background(self, parent)
        disabled = self.debug.disabled_features()
        if disabled:
            self._debug_summary = (
                "ListPanel debug level %s disabled features: %s"
                % (self.debug_level, ", ".join(disabled))
            )
        else:
            self._debug_summary = "ListPanel debug level %s: all features enabled" % (
                self.debug_level,
            )
        logger.info(self._debug_summary)
        if self.debug.model_cache:
            self.model = model if model is not None else RequirementModel()
        else:
            self.model = None
        self._plain_source: list[Requirement] = []
        self._plain_items: list[tuple[int, str]] = []
        self._pending_column_widths: dict[int, tuple[int, int]] = {}
        self._column_widths_scheduled = False
        self._report_refresh_scheduled = False
        self._report_refresh_attempts = 0
        sizer = wx.BoxSizer(wx.VERTICAL) if self.debug.sizer_layout else None
        vertical_pad = dip(self, 5)
        orient = getattr(wx, "HORIZONTAL", 0)
        right = getattr(wx, "RIGHT", 0)
        top_flag = getattr(wx, "TOP", 0)
        align_center = getattr(wx, "ALIGN_CENTER_VERTICAL", 0)
        btn_row: wx.Sizer | None = None
        self.filter_btn: wx.Button | None = None
        self.reset_btn: wx.BitmapButton | None = None
        self.filter_summary: wx.StaticText | None = None
        if self.debug.filter_button or self.debug.filter_summary:
            btn_row = wx.BoxSizer(orient)
            if self.debug.filter_button:
                self.filter_btn = wx.Button(self, label=_("Filters"))
                btn_row.Add(self.filter_btn, 0, right, vertical_pad)
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
                btn_row.Add(self.reset_btn, 0, right, vertical_pad)
            if self.debug.filter_summary:
                self.filter_summary = wx.StaticText(self, label="")
                btn_row.Add(self.filter_summary, 0, align_center, 0)
        list_style = wx.LC_REPORT if self.debug.report_style else wx.LC_LIST
        self.list = wx.ListCtrl(self, style=list_style)
        if self.debug.subitem_images and hasattr(self.list, "SetExtraStyle"):
            extra = getattr(wx, "LC_EX_SUBITEMIMAGES", 0)
            if extra:
                with suppress(Exception):  # pragma: no cover - backend quirks
                    self.list.SetExtraStyle(self.list.GetExtraStyle() | extra)
        self._labels: list[LabelDef] = []
        self.current_filters: dict = {}
        self._image_list: wx.ImageList | None = None
        self._label_images: dict[tuple[str, ...], int] = {}
        self._rid_lookup: dict[str, Requirement] = {}
        self._doc_titles: dict[str, str] = {}
        self._link_display_cache: dict[str, str] = {}
        if self.debug.sorter_mixin:
            ColumnSorterMixin.__init__(self, 1)
        self.columns: list[str] = []
        if self.debug.callbacks:
            self._on_clone = on_clone
            self._on_delete = on_delete
            self._on_delete_many = on_delete_many
            self._on_sort_changed = on_sort_changed
            self._on_derive = on_derive
        else:
            self._on_clone = None
            self._on_delete = None
            self._on_delete_many = None
            self._on_sort_changed = None
            self._on_derive = None
        self.derived_map: dict[str, list[int]] = {}
        self._sort_column = -1
        self._sort_ascending = True
        self._docs_controller = docs_controller if self.debug.documents_integration else None
        self._current_doc_prefix: str | None = None
        self._context_menu_open = False
        self._setup_columns()
        if sizer is not None:
            if btn_row is not None:
                sizer.Add(btn_row, 0, wx.EXPAND, 0)
            sizer.Add(self.list, 1, wx.EXPAND | top_flag, vertical_pad)
            self.SetSizer(sizer)
        else:
            self.list.SetPosition((0, 0))
            self.Bind(wx.EVT_SIZE, self._on_size_plain)
            self._on_size_plain(None)
        if self.debug.context_menu:
            self.list.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self._on_right_click)
            self.list.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        if self.debug.filter_button and self.filter_btn is not None:
            self.filter_btn.Bind(wx.EVT_BUTTON, self._on_filter)
        if self.reset_btn is not None:
            self.reset_btn.Bind(wx.EVT_BUTTON, lambda _evt: self.reset_filters())

    # ColumnSorterMixin requirement
    def log_debug_profile(self) -> None:
        """Log the cached summary of disabled features."""

        if getattr(self, "_debug_summary", None):
            logger.info(self._debug_summary)

    def _log_diagnostics(self, message: str, *args) -> None:
        """Emit verbose diagnostic information when high debug levels are active."""

        if not getattr(self, "_diagnostic_logging", False):
            return
        logger.info("ListPanel diagnostics: " + message, *args)

    def _use_item_images(self) -> bool:
        """Return ``True`` when report item images should be attached."""

        return self.debug.report_item_images and self.debug.report_image_list

    def _capture_column_width(self, column: int) -> int:
        """Return current width of ``column`` or ``-1`` if unavailable."""

        actual = -1
        with suppress(Exception):
            actual = self.list.GetColumnWidth(column)
        return actual

    def _capture_item_rect(
        self,
        row: int,
        code: int,
    ) -> tuple[int, int, int, int] | None:
        """Return ``wx.ListCtrl`` rectangle metrics for diagnostics."""

        rect = wx.Rect()
        try:
            ok = self.list.GetItemRect(row, rect, code)
        except Exception:
            return None
        if not ok:
            return None
        return (rect.x, rect.y, rect.width, rect.height)

    def _capture_item_position(self, row: int) -> tuple[int, int] | None:
        """Return the position of ``row`` within the control, if available."""

        point = wx.Point()
        try:
            ok = self.list.GetItemPosition(row, point)
        except Exception:
            return None
        if not ok:
            return None
        return (point.x, point.y)

    def _describe_colour(self, colour: wx.Colour | None) -> str | None:
        """Convert ``wx.Colour`` values into a hex triplet for logs."""

        if colour is None:
            return None
        try:
            if hasattr(colour, "IsOk") and not colour.IsOk():
                return None
            red = colour.Red()
            green = colour.Green()
            blue = colour.Blue()
        except Exception:
            return None
        return f"#{red:02x}{green:02x}{blue:02x}"

    def _snapshot_column_widths(self, column_count: int) -> list[int]:
        """Return a list of current column widths."""

        widths: list[int] = []
        for idx in range(column_count):
            widths.append(self._capture_column_width(idx))
        return widths

    def _snapshot_row_geometry(self, limit: int = 3) -> list[dict[str, object]]:
        """Collect geometry diagnostics for the first ``limit`` rows."""

        rows: list[dict[str, object]] = []
        try:
            count = self.list.GetItemCount()
        except Exception:
            return rows
        if count <= 0:
            return rows
        safe_limit = max(0, min(limit, count))
        bounds_code = getattr(wx, "LIST_RECT_BOUNDS", 0)
        label_code = getattr(wx, "LIST_RECT_LABEL", 0)
        for row in range(safe_limit):
            info: dict[str, object] = {"row": row}
            bounds = self._capture_item_rect(row, bounds_code)
            label_rect = self._capture_item_rect(row, label_code)
            if bounds is not None:
                info["bounds"] = bounds
            if label_rect is not None and label_rect != bounds:
                info["label_rect"] = label_rect
            position = self._capture_item_position(row)
            if position is not None:
                info["position"] = position
            with suppress(Exception):
                state_mask = 0
                for attr in ("LIST_STATE_SELECTED", "LIST_STATE_FOCUSED", "LIST_STATE_DROPHILITED"):
                    state_mask |= getattr(wx, attr, 0)
                if state_mask:
                    info["state"] = self.list.GetItemState(row, state_mask)
            with suppress(Exception):
                info["data"] = self.list.GetItemData(row)
            with suppress(Exception):
                colour = self.list.GetItemTextColour(row)
                described = self._describe_colour(colour)
                if described is not None:
                    info["text_colour"] = described
            with suppress(Exception):
                colour = self.list.GetItemBackgroundColour(row)
                described = self._describe_colour(colour)
                if described is not None:
                    info["background_colour"] = described
            rows.append(info)
        return rows

    def _collect_control_metrics(self) -> dict[str, object]:
        """Gather assorted control-level metrics for diagnostics."""

        metrics: dict[str, object] = {}
        with suppress(Exception):
            metrics["style"] = format(self.list.GetWindowStyleFlag(), "x")
        with suppress(Exception):
            metrics["is_shown"] = bool(self.list.IsShownOnScreen())
        with suppress(Exception):
            metrics["is_enabled"] = bool(self.list.IsEnabled())
        with suppress(Exception):
            metrics["has_focus"] = bool(self.list.HasFocus())
        with suppress(Exception):
            metrics["is_frozen"] = bool(self.list.IsFrozen())
        with suppress(Exception):
            size = self.list.GetClientSize()
            metrics["client_size"] = (size.width, size.height)
        with suppress(Exception):
            vsize = self.list.GetVirtualSize()
            metrics["virtual_size"] = (vsize.width, vsize.height)
        with suppress(Exception):
            rect = self.list.GetViewRect()
            metrics["view_rect"] = (rect.x, rect.y, rect.width, rect.height)
        with suppress(Exception):
            metrics["top_item"] = self.list.GetTopItem()
        with suppress(Exception):
            metrics["count_per_page"] = self.list.GetCountPerPage()
        if hasattr(self.list, "GetItemSpacing"):
            with suppress(Exception):
                spacing = self.list.GetItemSpacing()
                if isinstance(spacing, tuple) and len(spacing) == 2:
                    metrics["item_spacing"] = spacing
        with suppress(Exception):
            header = self.list.GetHeaderCtrl()
            if header:
                size = header.GetSize()
                metrics["header_size"] = (size.width, size.height)
        for orient_name in ("HORIZONTAL", "VERTICAL"):
            orient = getattr(wx, orient_name, None)
            if orient is None:
                continue
            key = orient_name.lower()
            with suppress(Exception):
                pos = self.list.GetScrollPos(orient)
                metrics[f"scroll_{key}_pos"] = pos
            with suppress(Exception):
                rng = self.list.GetScrollRange(orient)
                metrics[f"scroll_{key}_range"] = rng
        return metrics

    def _snapshot_rows(self, limit: int = 3) -> list[list[str]]:
        """Return up to ``limit`` rows of visible text for diagnostics."""

        rows: list[list[str]] = []
        try:
            count = self.list.GetItemCount()
            columns = self.list.GetColumnCount()
        except Exception:
            return rows
        if count <= 0 or columns <= 0:
            return rows
        safe_limit = max(0, min(limit, count))
        for row in range(safe_limit):
            cells: list[str] = []
            for col in range(columns):
                text = ""
                with suppress(Exception):
                    text = self.list.GetItemText(row, col)
                cells.append(text)
            rows.append(cells)
        return rows

    def _log_population_snapshot(self, stage: str) -> None:
        """Dump a short textual snapshot of the current list contents."""

        if not getattr(self, "_diagnostic_logging", False):
            return
        item_count = -1
        column_count = -1
        with suppress(Exception):
            item_count = self.list.GetItemCount()
        with suppress(Exception):
            column_count = self.list.GetColumnCount()
        rows = self._snapshot_rows()
        widths: list[int] = []
        if column_count > 0:
            widths = self._snapshot_column_widths(column_count)
        geometry = self._snapshot_row_geometry()
        metrics = self._collect_control_metrics()
        self._log_diagnostics(
            "%s — items=%s columns=%s sample=%s",
            stage,
            item_count,
            column_count,
            rows,
        )
        if widths:
            self._log_diagnostics("%s column-widths=%s", stage, widths)
        if geometry:
            self._log_diagnostics("%s row-geometry=%s", stage, geometry)
        if metrics:
            self._log_diagnostics("%s control-metrics=%s", stage, metrics)

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
        on_delete_many: Callable[[Sequence[int]], None] | None = None,
        on_derive: Callable[[int], None] | None = None,
    ) -> None:
        """Set callbacks for context menu actions."""
        if not self.debug.callbacks:
            return
        if on_clone is not None:
            self._on_clone = on_clone
        if on_delete is not None:
            self._on_delete = on_delete
        if on_delete_many is not None:
            self._on_delete_many = on_delete_many
        if on_derive is not None:
            self._on_derive = on_derive

    def set_documents_controller(
        self, controller: DocumentsController | None
    ) -> None:
        """Set documents controller used for persistence."""

        if not self.debug.documents_integration:
            self._docs_controller = None
            self._doc_titles = {}
            self._link_display_cache.clear()
            self._rid_lookup = {}
            return
        self._docs_controller = controller
        self._doc_titles = {}
        self._link_display_cache.clear()
        self._rid_lookup = {}
        if controller is not None and self.debug.doc_lookup:
            with suppress(Exception):
                all_requirements = self.model.get_all()
            if isinstance(all_requirements, list):
                self._rebuild_rid_lookup(all_requirements)

    def set_active_document(self, prefix: str | None) -> None:
        """Record currently active document prefix for persistence."""

        if not self.debug.documents_integration:
            return
        self._current_doc_prefix = prefix

    def _label_color(self, name: str) -> str:
        for lbl in self._labels:
            if lbl.key == name:
                return label_color(lbl)
        return stable_color(name)

    def _ensure_image_list_size(self, width: int, height: int) -> None:
        if not self.debug.report_image_list:
            return
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
        if self.debug.report_image_list:
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
        if not self.debug.doc_lookup:
            return ""
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
        if not self.debug.doc_lookup:
            return
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
        if not self.debug.doc_lookup:
            return rid
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
            doc = self._docs_controller.documents.get(prefix)
            if doc:
                doc_title = self._doc_title_for_prefix(prefix)
                directory = self._docs_controller.root / prefix
                try:
                    data, _mtime = load_item(directory, doc, item_id)
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

    def _update_plain_items(self, requirements: list[Requirement] | None = None) -> None:
        """Build cached plain entries for simplified rendering."""

        source: list[Requirement]
        if requirements is not None:
            source = list(requirements)
        elif self.debug.model_cache and self.model is not None:
            try:
                source = self.model.get_visible()
            except Exception:
                source = []
        else:
            source = list(self._plain_source)
        plain: list[tuple[int, str]] = []
        for req in source:
            try:
                req_id = int(getattr(req, "id", 0))
            except Exception:
                req_id = 0
            title = str(getattr(req, "title", ""))
            plain.append((req_id, title))
        self._plain_items = plain

    def _populate_plain_items(self) -> None:
        """Render cached plain entries into the list control."""

        self._clear_items()
        for req_id, title in self._plain_items:
            index = self.list.InsertItem(self.list.GetItemCount(), title)
            if self.debug.report_column0_setitem:
                with suppress(Exception):
                    # Ensure column 0 text is committed even if InsertItem label is ignored
                    self.list.SetItem(index, 0, title)
            if self.debug.report_item_data:
                try:
                    self.list.SetItemData(index, int(req_id))
                except Exception:
                    self.list.SetItemData(index, 0)
        self._post_population_refresh()
        self._log_population_snapshot("populate-plain")

    def _on_size_plain(self, event: wx.Event | None) -> None:
        """Resize the list control to fill the panel without sizers."""

        size = self.GetClientSize()
        if size.width > 0 and size.height > 0:
            self.list.SetSize(size)
        if event is not None and hasattr(event, "Skip"):
            event.Skip()

    def _first_parent_text(self, req: Requirement) -> str:
        links = getattr(req, "links", []) or []
        if not links:
            return ""
        parent = links[0]
        rid = getattr(parent, "rid", parent)
        text = str(rid)
        if not self.debug.doc_lookup:
            return text
        return self._link_display_text(text)

    def _set_label_text(self, index: int, col: int, labels: list[str]) -> None:
        text = ", ".join(labels)
        self.list.SetItem(index, col, text)
        if not self._use_item_images():
            return
        if col == 0 and hasattr(self.list, "SetItemImage"):
            with suppress(Exception):
                self.list.SetItemImage(index, -1)
            return
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
        if not self.debug.label_bitmaps or not self._use_item_images():
            self._set_label_text(index, col, labels)
            return
        if not labels:
            self.list.SetItem(index, col, "")
            if self._use_item_images() and hasattr(self.list, "SetItemImage") and col == 0:
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
            if self._use_item_images() and hasattr(self.list, "SetItemImage"):
                with suppress(Exception):
                    self.list.SetItemImage(index, img_id)
        else:
            self.list.SetItem(index, col, "")
            if self._use_item_images():
                self.list.SetItemColumnImage(index, col, img_id)
            if self._use_item_images() and hasattr(self.list, "SetItemImage"):
                with suppress(Exception):
                    self.list.SetItemImage(index, -1)

    def _setup_columns(self) -> None:
        """Configure list control columns based on selected fields.

        On Windows ``wx.ListCtrl`` always reserves space for an image in the
        first physical column. Placing ``labels`` at index 0 removes the extra
        padding before ``Title``. Another workaround is to insert a hidden
        dummy column before ``Title``.
        """
        if self.debug.report_clear_all:
            self.list.ClearAll()
        else:
            self._clear_items()
            self._remove_all_columns()
        self._pending_column_widths.clear()
        self._field_order: list[str] = []
        if not self.debug.report_style:
            with suppress(Exception):
                self.list.Unbind(wx.EVT_LIST_COL_CLICK)
            return
        if not self.debug.rich_rendering:
            self._add_report_column(0, "title", _("Title"))
            with suppress(Exception):
                self.list.Unbind(wx.EVT_LIST_COL_CLICK)
            return
        active_columns = self.columns if self.debug.extra_columns else []
        include_labels = self.debug.extra_columns and "labels" in active_columns
        if include_labels:
            self._add_report_column(0, "labels", _("Labels"))
            self._add_report_column(1, "title", _("Title"))
        else:
            self._add_report_column(0, "title", _("Title"))
        if self.debug.extra_columns:
            for field in active_columns:
                if field == "labels":
                    continue
                idx = self.list.GetColumnCount()
                self._add_report_column(idx, field, locale.field_label(field))
        if self.debug.sorting and self.debug.sorter_mixin:
            ColumnSorterMixin.__init__(self, self.list.GetColumnCount())
            with suppress(Exception):  # remove mixin's default binding and use our own
                self.list.Unbind(wx.EVT_LIST_COL_CLICK)
            self.list.Bind(wx.EVT_LIST_COL_CLICK, self._on_col_click)
        else:
            with suppress(Exception):
                self.list.Unbind(wx.EVT_LIST_COL_CLICK)
        style_flag = -1
        column_count = -1
        with suppress(Exception):
            style_flag = self.list.GetWindowStyleFlag()
        with suppress(Exception):
            column_count = self.list.GetColumnCount()
        self._log_diagnostics(
            "setup_columns complete — order=%s style=0x%s count=%s",
            self._field_order,
            format(style_flag if style_flag >= 0 else 0, "x"),
            column_count,
        )

    def _add_report_column(self, index: int, field: str, label: str) -> None:
        """Insert a report-style column and ensure it has a visible width."""

        width = self._default_column_width(field)
        inserted = False
        list_item_cls = getattr(wx, "ListItem", None)
        if self.debug.report_list_item and list_item_cls is not None:
            try:
                item = list_item_cls()
            except Exception:
                item = None
            if item is not None:
                if hasattr(item, "SetText"):
                    item.SetText(label)
                align_flag = getattr(wx, "LIST_FORMAT_LEFT", None) if self.debug.report_column_align else None
                if align_flag is not None and hasattr(item, "SetAlign"):
                    with suppress(Exception):
                        item.SetAlign(align_flag)
                if hasattr(item, "SetWidth"):
                    item.SetWidth(width)
                try:
                    self.list.InsertColumn(index, item)
                except (TypeError, ValueError):
                    inserted = False
                else:
                    inserted = True
        if not inserted:
            align_flag = (
                getattr(wx, "LIST_FORMAT_LEFT", None)
                if self.debug.report_column_align
                else None
            )
            if align_flag is None:
                self.list.InsertColumn(index, label)
            else:
                width_arg = width if self.debug.report_column_widths else -1
                try:
                    self.list.InsertColumn(index, label, align_flag, width_arg)
                except TypeError:
                    self.list.InsertColumn(index, label)
        self._field_order.append(field)
        self._ensure_column_width(index, width)
        actual = self._capture_column_width(index)
        self._log_diagnostics(
            "column %s (%s) inserted — requested=%s actual=%s",
            index,
            field,
            width,
            actual,
        )

    def _clear_items(self) -> None:
        """Remove all items from the control respecting debug fallbacks."""

        if self.debug.report_batch_delete:
            try:
                self.list.DeleteAllItems()
            except Exception:
                pass
            else:
                return
        try:
            count = self.list.GetItemCount()
        except Exception:
            return
        for idx in range(count - 1, -1, -1):
            with suppress(Exception):
                self.list.DeleteItem(idx)

    def _remove_all_columns(self) -> None:
        """Drop all report-style columns without relying on ``ClearAll``."""

        try:
            count = self.list.GetColumnCount()
        except Exception:
            return
        for idx in range(count - 1, -1, -1):
            try:
                self.list.DeleteColumn(idx)
            except Exception:
                logger.debug(
                    "Failed to delete ListPanel column %s during fallback removal",
                    idx,
                    exc_info=True,
                )

    def _post_population_refresh(self) -> None:
        """Force a repaint when implicit refresh is disabled."""

        if self.debug.report_lazy_refresh:
            self._schedule_report_refresh()
            return
        self._apply_immediate_refresh()

    def _apply_immediate_refresh(self) -> None:
        """Request the list control to repaint immediately."""

        if not self.debug.report_immediate_refresh:
            return
        with suppress(Exception):
            self.list.Refresh()
        with suppress(Exception):
            self.list.Update()

    def _schedule_report_refresh(self) -> None:
        """Fallback for report mode when lazy refresh fails to repaint."""

        if not self.debug.report_style:
            return
        if self._report_refresh_scheduled:
            return
        self._report_refresh_scheduled = True
        self._log_diagnostics("scheduled explicit report refresh fallback")
        call_after = getattr(wx, "CallAfter", None)
        if callable(call_after):
            call_after(self._flush_report_refresh)
            return
        self._log_diagnostics("executing report refresh immediately — CallAfter unavailable")
        self._flush_report_refresh()

    def _flush_report_refresh(self) -> None:
        """Execute a deferred refresh scheduled by ``_schedule_report_refresh``."""

        self._report_refresh_scheduled = False
        list_ctrl = getattr(self, "list", None)
        if not list_ctrl:
            return
        with suppress(Exception):
            if list_ctrl.IsBeingDeleted():
                return
        shown = True
        with suppress(Exception):
            shown = bool(list_ctrl.IsShownOnScreen())
        if not shown:
            attempts = self._report_refresh_attempts + 1
            self._report_refresh_attempts = attempts
            call_after = getattr(wx, "CallAfter", None)
            if attempts >= 5 or not callable(call_after):
                if attempts >= 5:
                    self._log_diagnostics(
                        "report refresh giving up after %s deferred attempts",
                        attempts,
                    )
                else:
                    self._log_diagnostics(
                        "report refresh fallback without CallAfter (attempt %s)",
                        attempts,
                    )
                self._apply_immediate_refresh()
                return
            self._log_diagnostics(
                "report refresh deferred — control not yet shown (attempt %s)",
                attempts,
            )
            self._schedule_report_refresh()
            return
        self._report_refresh_attempts = 0
        count = 0
        with suppress(Exception):
            count = list_ctrl.GetItemCount()
        if self.debug.report_refresh_items and hasattr(list_ctrl, "RefreshItems") and count > 0:
            try:
                list_ctrl.RefreshItems(0, max(0, count - 1))
            except Exception:
                logger.debug(
                    "RefreshItems failed during report refresh fallback",
                    exc_info=True,
                )
        self._apply_immediate_refresh()
        self._log_diagnostics("report refresh applied — count=%s", count)

    def _ensure_column_width(self, column: int, width: int) -> None:
        """Guarantee that a column remains visible even if the backend rejects it."""

        width = max(self.MIN_COL_WIDTH, min(width, self.MAX_COL_WIDTH))
        if not self.debug.report_column_widths:
            self._log_diagnostics(
                "width enforcement disabled — single attempt for column %s (requested=%s)",
                column,
                width,
            )
            success = self._apply_column_width_now(column, width)
            if not success:
                self._log_diagnostics(
                    "column %s width still collapsed with enforcement disabled",
                    column,
                )
            return
        if self._apply_column_width_now(column, width):
            self._pending_column_widths.pop(column, None)
            return
        self._queue_column_width(column, width)

    def _apply_column_width_now(self, column: int, width: int) -> bool:
        """Try to set the column width immediately, using several fallbacks."""

        try:
            self.list.SetColumnWidth(column, width)
        except Exception:
            logger.debug("SetColumnWidth(%s, %s) failed immediately", column, width, exc_info=True)
        actual = self._capture_column_width(column)
        self._log_diagnostics(
            "column %s width attempt — requested=%s actual=%s",
            column,
            width,
            actual,
        )
        if actual and actual > 0:
            return True
        fallbacks: list[int] = []
        if width != self.MIN_COL_WIDTH:
            fallbacks.append(max(width, self.MIN_COL_WIDTH))
        header_auto = getattr(wx, "LIST_AUTOSIZE_USEHEADER", None)
        if isinstance(header_auto, int):
            fallbacks.append(header_auto)
        auto = getattr(wx, "LIST_AUTOSIZE", None)
        if isinstance(auto, int):
            fallbacks.append(auto)
        if self.MIN_COL_WIDTH not in fallbacks:
            fallbacks.append(self.MIN_COL_WIDTH)
        for candidate in fallbacks:
            try:
                self.list.SetColumnWidth(column, candidate)
            except Exception:
                logger.debug(
                    "SetColumnWidth(%s, %s) failed during fallback", column, candidate, exc_info=True
                )
                continue
            actual = self._capture_column_width(column)
            self._log_diagnostics(
                "column %s width fallback — candidate=%s actual=%s",
                column,
                candidate,
                actual,
            )
            if actual and actual > 0:
                return True
        return False

    def _queue_column_width(self, column: int, width: int) -> None:
        """Schedule a deferred attempt to enforce a report column width."""

        if not self.debug.report_width_retry:
            return
        attempts = 0
        if column in self._pending_column_widths:
            stored_width, attempts = self._pending_column_widths[column]
            width = max(width, stored_width)
        self._pending_column_widths[column] = (width, attempts)
        self._log_diagnostics(
            "column %s width queued — requested=%s attempts=%s",
            column,
            width,
            attempts,
        )
        if not self._column_widths_scheduled:
            self._column_widths_scheduled = True
            wx.CallAfter(self._flush_pending_column_widths)
            self._log_diagnostics("scheduled deferred column width flush")

    def _flush_pending_column_widths(self) -> None:
        """Retry collapsed column widths once the widget is fully realized."""

        self._column_widths_scheduled = False
        pending = list(self._pending_column_widths.items())
        self._pending_column_widths.clear()
        if not pending:
            return
        self._log_diagnostics("processing %s pending column width attempts", len(pending))
        for column, (width, attempts) in pending:
            try:
                count = self.list.GetColumnCount()
            except Exception:
                return
            if column >= count:
                continue
            success = self._apply_column_width_now(column, width)
            if success:
                self._log_diagnostics("column %s width recovered after retry", column)
                continue
            attempts += 1
            if attempts >= 3:
                logger.warning(
                    "ListPanel column %s remains collapsed after retries; giving up", column
                )
                with suppress(Exception):
                    self.list.SetColumnWidth(column, max(width, self.MIN_COL_WIDTH))
                actual = self._capture_column_width(column)
                self._log_diagnostics(
                    "column %s width give-up — requested=%s actual=%s",
                    column,
                    width,
                    actual,
                )
                continue
            self._pending_column_widths[column] = (width, attempts)
        if self._pending_column_widths:
            self._log_diagnostics(
                "retry queue still has %s column(s)", len(self._pending_column_widths)
            )
        if self._pending_column_widths and not self._column_widths_scheduled:
            self._column_widths_scheduled = True
            wx.CallAfter(self._flush_pending_column_widths)
            self._log_diagnostics("rescheduled deferred column width flush")

    # Columns ---------------------------------------------------------
    def load_column_widths(self, config: ConfigManager) -> None:
        """Restore column widths from config with sane bounds."""
        if not self.debug.column_persistence:
            return
        count = self.list.GetColumnCount()
        for i in range(count):
            width = config.read_int(f"col_width_{i}", -1)
            if width <= 0:
                field = self._field_order[i] if i < len(self._field_order) else ""
                width = self._default_column_width(field)
            width = max(self.MIN_COL_WIDTH, min(width, self.MAX_COL_WIDTH))
            self._ensure_column_width(i, width)

    def save_column_widths(self, config: ConfigManager) -> None:
        """Persist current column widths to config."""
        if not self.debug.column_persistence:
            return
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
        if not self.debug.column_persistence:
            return
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
        if not self.debug.column_persistence:
            return
        try:  # pragma: no cover - depends on GUI backend
            order = self.list.GetColumnsOrder()
        except Exception:
            return
        names = [self._field_order[idx] for idx in order if idx < len(self._field_order)]
        config.write("col_order", ",".join(names))

    def reorder_columns(self, from_col: int, to_col: int) -> None:
        """Move column from ``from_col`` index to ``to_col`` index."""
        if not self.debug.extra_columns:
            return
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
        if not self.debug.rich_rendering:
            self.columns = []
        else:
            self.columns = list(fields) if self.debug.extra_columns else []
        self._setup_columns()
        # repopulate with existing requirements after changing columns
        self._refresh()

    def set_requirements(
        self,
        requirements: list,
        derived_map: dict[str, list[int]] | None = None,
    ) -> None:
        """Populate list control with requirement data via model."""
        self._plain_source = list(requirements)
        if self.debug.model_cache and self.model is not None:
            self.model.set_requirements(requirements)
        if (
            not self.debug.model_driven
            or not self.debug.model_cache
            or self.model is None
        ):
            self._update_plain_items(requirements)
            self._populate_plain_items()
            return
        self._rebuild_rid_lookup(self.model.get_all())
        if not self.debug.derived_map:
            self.derived_map = {}
            self._refresh()
            return
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
        if not self.debug.filter_logic:
            self.current_filters = {}
            if self.debug.model_cache and self.model is not None:
                self.model.set_label_filter([])
                self.model.set_label_match_all(True)
                self.model.set_search_query("", None)
                self.model.set_field_queries({})
                self.model.set_status(None)
                self.model.set_is_derived(False)
                self.model.set_has_derived(False)
            self._refresh()
            self._update_filter_summary()
            self._toggle_reset_button()
            return
        self.current_filters.update(filters)
        if self.debug.model_cache and self.model is not None:
            self.model.set_label_filter(self.current_filters.get("labels", []))
            self.model.set_label_match_all(
                not self.current_filters.get("match_any", False)
            )
        fields = self.current_filters.get("fields")
        if self.debug.model_cache and self.model is not None:
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
        if not self.debug.filter_summary or self.filter_summary is None:
            return
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
        if self.reset_btn is None:
            return
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
        if (
            not self.debug.model_driven
            or not self.debug.model_cache
            or self.model is None
        ):
            self._update_plain_items()
            self._populate_plain_items()
            self._log_population_snapshot("refresh-plain")
            return
        try:
            items = self.model.get_visible()
        except Exception:
            items = []
        self._clear_items()
        if not self.debug.rich_rendering:
            for req in items:
                title = getattr(req, "title", "")
                index = self.list.InsertItem(
                    self.list.GetItemCount(),
                    str(title),
                )
                if self.debug.report_item_data:
                    req_id = getattr(req, "id", 0)
                    try:
                        self.list.SetItemData(index, int(req_id))
                    except Exception:
                        self.list.SetItemData(index, 0)
            self._post_population_refresh()
            self._log_population_snapshot("refresh-report-simple")
            return
        for req in items:
            raw_title = getattr(req, "title", "")
            derived = bool(getattr(req, "links", []))
            display_title = (
                f"↳ {raw_title}".strip()
                if derived and self.debug.derived_formatting
                else str(raw_title)
            )
            placeholder_enabled = (
                self.debug.report_placeholder_text and self.debug.report_column0_setitem
            )
            initial_text = "" if placeholder_enabled else display_title
            if self._use_item_images():
                index = self.list.InsertItem(self.list.GetItemCount(), initial_text, -1)
            else:
                index = self.list.InsertItem(self.list.GetItemCount(), initial_text)
            # Windows ListCtrl may still assign image 0; clear explicitly
            if self._use_item_images() and hasattr(self.list, "SetItemImage"):
                with suppress(Exception):
                    self.list.SetItemImage(index, -1)
            if self.debug.report_item_data:
                req_id = getattr(req, "id", 0)
                try:
                    self.list.SetItemData(index, int(req_id))
                except Exception:
                    self.list.SetItemData(index, 0)
            for col, field in enumerate(self._field_order):
                if field == "title":
                    if self.debug.report_column0_setitem:
                        self.list.SetItem(index, col, display_title)
                    continue
                if field == "labels":
                    value = getattr(req, "labels", [])
                    if self.debug.label_bitmaps:
                        self._set_label_image(index, col, value)
                    else:
                        self._set_label_text(index, col, value)
                    continue
                if field == "derived_from":
                    if self.debug.derived_formatting:
                        value = self._first_parent_text(req)
                    else:
                        links = getattr(req, "links", []) or []
                        if links:
                            parent = links[0]
                            value = str(getattr(parent, "rid", parent))
                        else:
                            value = ""
                    self.list.SetItem(index, col, value)
                    continue
                if field == "links":
                    links = getattr(req, "links", [])
                    formatted: list[str] = []
                    for link in links:
                        rid = getattr(link, "rid", str(link))
                        suspect = getattr(link, "suspect", False)
                        if suspect and self.debug.derived_formatting:
                            formatted.append(f"{rid} ⚠")
                        else:
                            formatted.append(str(rid))
                    value = ", ".join(formatted)
                    self.list.SetItem(index, col, value)
                    continue
                if field == "derived_count":
                    if self.debug.derived_map:
                        rid = getattr(req, "rid", None) or str(getattr(req, "id", ""))
                        count = len(self.derived_map.get(rid, []))
                    else:
                        count = len(getattr(req, "links", []) or [])
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
        self._post_population_refresh()
        self._log_population_snapshot("refresh-report-full")

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

        if not self.debug.report_item_data:
            return
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

    def record_link(self, parent_rid: str, child_id: int) -> None:
        """Record that ``child_id`` links to ``parent_rid``."""

        if not self.debug.derived_map or not self.debug.documents_integration:
            return
        self.derived_map.setdefault(parent_rid, []).append(child_id)

    def recalc_derived_map(self, requirements: list[Requirement]) -> None:
        """Rebuild derived requirements map from ``requirements``."""

        if not self.debug.derived_map or not self.debug.documents_integration:
            self._rebuild_rid_lookup(requirements)
            self._refresh()
            return
        derived_map: dict[str, list[int]] = {}
        for req in requirements:
            for parent in getattr(req, "links", []):
                parent_rid = getattr(parent, "rid", parent)
                derived_map.setdefault(parent_rid, []).append(req.id)
        self.derived_map = derived_map
        self._rebuild_rid_lookup(requirements)
        self._refresh()

    def _on_col_click(self, event: ListEvent) -> None:  # pragma: no cover - GUI event
        if not self.debug.sorting:
            return
        col = event.GetColumn()
        ascending = not self._sort_ascending if col == self._sort_column else True
        self.sort(col, ascending)

    def sort(self, column: int, ascending: bool) -> None:
        """Sort list by ``column`` with ``ascending`` order."""
        if not self.debug.sorting:
            return
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
        if not self.debug.context_menu:
            return
        if self._context_menu_open:
            return
        menu, _, _, _ = self._create_context_menu(index, column)
        if not menu.GetMenuItemCount():
            menu.Destroy()
            return
        self._context_menu_open = True
        try:
            self.PopupMenu(menu)
        finally:
            menu.Destroy()
            self._context_menu_open = False

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
        selected_indices = self._get_selected_indices()
        if index != wx.NOT_FOUND and (not selected_indices or index not in selected_indices):
            selected_indices = [index]
        single_selection = len(selected_indices) == 1
        selected_ids = self._indices_to_ids(selected_indices)
        req_id = selected_ids[0] if selected_ids else None
        derive_item = clone_item = None
        if single_selection:
            derive_item = menu.Append(wx.ID_ANY, _("Derive"))
            clone_item = menu.Append(wx.ID_ANY, _("Clone"))
        delete_item = menu.Append(wx.ID_ANY, _("Delete"))
        field = self._field_from_column(column)
        edit_item = None
        if field and field != "title":
            edit_item = menu.Append(wx.ID_ANY, _("Edit {field}").format(field=field))
            menu.Bind(
                wx.EVT_MENU,
                lambda _evt, c=column: self._on_edit_field(c),
                edit_item,
            )
        if clone_item and self._on_clone and req_id is not None:
            menu.Bind(wx.EVT_MENU, lambda _evt, i=req_id: self._on_clone(i), clone_item)
        if len(selected_ids) > 1:
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
        elif self._on_delete and req_id is not None:
            menu.Bind(
                wx.EVT_MENU,
                lambda _evt, i=req_id: self._on_delete(i),
                delete_item,
            )
        if derive_item and self._on_derive and req_id is not None:
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

    def _indices_to_ids(self, indices: Sequence[int]) -> list[int]:
        if not self.debug.report_item_data:
            return []
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

    def _persist_requirement(self, req: Requirement) -> None:
        """Persist edited ``req`` if controller and document are available."""

        if (
            not self.debug.documents_integration
            or not self._docs_controller
            or not self._current_doc_prefix
        ):
            return
        try:
            self._docs_controller.save_requirement(self._current_doc_prefix, req)
        except Exception:  # pragma: no cover - log and continue
            rid = getattr(req, "rid", req.id)
            logger.exception("Failed to save requirement %s", rid)
