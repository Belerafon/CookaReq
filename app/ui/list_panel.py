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
class ListPanelDebugDelta:
    """Describe feature toggles that changed between two debug profiles."""

    enabled_features: tuple[str, ...]
    disabled_features: tuple[str, ...]
    enabled_instrumentation: tuple[str, ...]
    disabled_instrumentation: tuple[str, ...]


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
        "report_width_retry_async": "report width CallAfter scheduling",
        "report_width_fallbacks": "report width fallback attempts",
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
        "report_immediate_refresh": "report Refresh() request",
        "report_immediate_update": "report Update() request",
        "report_send_size_event": "report SendSizeEvent fallback",
        "plain_deferred_callafter": "plain deferred CallAfter scheduling",
        "plain_deferred_timer": "plain deferred CallLater retries",
        "plain_deferred_queue": "plain deferred payload queue",
        "plain_deferred_population": "plain deferred population",
        "plain_cached_items": "plain item cache",
        "plain_post_refresh": "plain post-refresh hook",
        "report_style": "report-style layout",
        "sizer_layout": "panel box sizer",
    }

    INSTRUMENTATION_LABELS: ClassVar[dict[str, str]] = {
        "probe_force_refresh": "force-refresh probe",
        "probe_column_reset": "column reset audit",
        "probe_deferred_population": "deferred population probe",
    }

    level: int
    base_level: int
    instrumentation_tier: int
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
    report_width_retry_async: bool
    report_width_fallbacks: bool
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
    report_immediate_update: bool
    report_send_size_event: bool
    plain_deferred_callafter: bool
    plain_deferred_timer: bool
    plain_deferred_queue: bool
    plain_deferred_population: bool
    plain_cached_items: bool
    plain_post_refresh: bool
    report_style: bool
    sizer_layout: bool
    probe_force_refresh: bool
    probe_column_reset: bool
    probe_deferred_population: bool

    @classmethod
    def from_level(cls, level: int | None) -> "ListPanelDebugProfile":
        """Return profile for ``level`` clamped to supported range."""

        raw = 0 if level is None else int(level)
        clamped = max(0, min(MAX_LIST_PANEL_DEBUG_LEVEL, raw))
        tier, base = divmod(clamped, 100)
        base_clamped = max(0, min(50, base))
        return cls(
            level=clamped,
            base_level=base_clamped,
            instrumentation_tier=tier,
            context_menu=base_clamped < 1,
            label_bitmaps=base_clamped < 2,
            derived_formatting=base_clamped < 3,
            filter_summary=base_clamped < 4,
            filter_button=base_clamped < 5,
            filter_logic=base_clamped < 5,
            column_persistence=base_clamped < 6,
            extra_columns=base_clamped < 7,
            sorting=base_clamped < 8,
            derived_map=base_clamped < 9,
            doc_lookup=base_clamped < 10,
            subitem_images=base_clamped < 11,
            inherit_background=base_clamped < 12,
            sorter_mixin=base_clamped < 13,
            rich_rendering=base_clamped < 14,
            documents_integration=base_clamped < 15,
            callbacks=base_clamped < 16,
            selection_events=base_clamped < 17,
            model_driven=base_clamped < 18,
            model_cache=base_clamped < 19,
            report_width_fallbacks=base_clamped < 36,
            report_width_retry_async=base_clamped < 37,
            report_width_retry=base_clamped < 38,
            report_column_widths=base_clamped < 39,
            report_list_item=base_clamped < 22,
            report_clear_all=base_clamped < 23,
            report_batch_delete=base_clamped < 24,
            report_column_align=base_clamped < 25,
            report_lazy_refresh=base_clamped < 26,
            report_placeholder_text=base_clamped < 27,
            report_column0_setitem=base_clamped < 28,
            report_image_list=base_clamped < 29,
            report_item_images=base_clamped < 30,
            report_item_data=base_clamped < 31,
            report_refresh_items=base_clamped < 32,
            report_immediate_refresh=base_clamped < 33,
            report_immediate_update=base_clamped < 34,
            report_send_size_event=base_clamped < 35,
            plain_deferred_callafter=base_clamped < 40,
            plain_deferred_timer=base_clamped < 41,
            plain_deferred_queue=base_clamped < 42,
            plain_deferred_population=base_clamped < 43,
            plain_cached_items=base_clamped < 44,
            plain_post_refresh=base_clamped < 45,
            report_style=base_clamped < 49,
            sizer_layout=base_clamped < 49,
            probe_force_refresh=tier >= 1,
            probe_column_reset=tier >= 2,
            probe_deferred_population=tier >= 3,
        )

    @property
    def rollback_stage(self) -> int:
        """Return how many post-commit rollback tiers are enabled."""

        # Post-fcbd3c rollbacks (legacy splitters, placeholders, etc.) start
        # only after the column-width recovery toggles at levels 36–39.  This
        # keeps the intermediate steps focused on width handling so each
        # feature can be isolated independently.
        return max(0, self.base_level - 39)

    def disabled_features(self) -> list[str]:
        """Return human-readable names of features disabled at this level."""

        disabled: list[str] = []
        for attr, label in self.FEATURE_LABELS.items():
            if not getattr(self, attr):
                disabled.append(label)
        return disabled

    def instrumentation_features(self) -> list[str]:
        """Return human-readable names of active instrumentation probes."""

        enabled: list[str] = []
        for attr, label in self.INSTRUMENTATION_LABELS.items():
            if getattr(self, attr, False):
                enabled.append(label)
        return enabled

    def diff(self, previous: "ListPanelDebugProfile") -> ListPanelDebugDelta:
        """Return feature and instrumentation changes relative to ``previous``."""

        enabled_features: list[str] = []
        disabled_features: list[str] = []
        for attr, label in self.FEATURE_LABELS.items():
            current = bool(getattr(self, attr))
            before = bool(getattr(previous, attr))
            if current == before:
                continue
            if current:
                enabled_features.append(label)
            else:
                disabled_features.append(label)
        enabled_instrumentation: list[str] = []
        disabled_instrumentation: list[str] = []
        for attr, label in self.INSTRUMENTATION_LABELS.items():
            current = bool(getattr(self, attr, False))
            before = bool(getattr(previous, attr, False))
            if current == before:
                continue
            if current:
                enabled_instrumentation.append(label)
            else:
                disabled_instrumentation.append(label)
        return ListPanelDebugDelta(
            enabled_features=tuple(enabled_features),
            disabled_features=tuple(disabled_features),
            enabled_instrumentation=tuple(enabled_instrumentation),
            disabled_instrumentation=tuple(disabled_instrumentation),
        )


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
        self.debug_raw_level = self.debug.level
        self.debug_level = self.debug.base_level
        self._diagnostic_logging = self.debug_level >= self.DIAGNOSTIC_LOG_THRESHOLD
        if self.debug.inherit_background:
            inherit_background(self, parent)
        self._refresh_debug_summaries(log=True)
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
        self._report_refresh_stage = ""
        self._probe_refresh_pending = False
        self._probe_refresh_last_stage = "initial"
        self._probe_deferred_plain_pending = False
        self._probe_deferred_plain_payload: list[Requirement] | None = None
        self._probe_deferred_plain_stage = ""
        self._probe_deferred_plain_attempts = 0
        self._basic_refresh_pending = False
        self._basic_refresh_attempts = 0
        self._basic_refresh_stage = ""
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
        if hasattr(wx, "EVT_SHOW"):
            self.list.Bind(wx.EVT_SHOW, self._on_list_show)
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
        self._field_order: list[str] = []
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
    def _refresh_debug_summaries(self, *, log: bool) -> None:
        """Update cached debug summaries and optionally log them."""

        disabled = self.debug.disabled_features()
        if disabled:
            self._debug_summary = (
                "ListPanel debug level %s (base %s) disabled features: %s"
                % (self.debug_raw_level, self.debug_level, ", ".join(disabled))
            )
        else:
            self._debug_summary = (
                "ListPanel debug level %s (base %s): all features enabled"
                % (self.debug_raw_level, self.debug_level)
            )
        if log:
            logger.info(self._debug_summary)
        instrumentation = self.debug.instrumentation_features()
        if instrumentation:
            self._instrumentation_summary = (
                "ListPanel debug instrumentation tier %s enabled: %s"
                % (
                    self.debug.instrumentation_tier,
                    ", ".join(instrumentation),
                )
            )
            if log:
                logger.info(self._instrumentation_summary)
        else:
            self._instrumentation_summary = ""

    def log_debug_profile(self) -> None:
        """Log the cached summary of disabled features."""

        if getattr(self, "_debug_summary", None):
            logger.info(self._debug_summary)
        if getattr(self, "_instrumentation_summary", None):
            logger.info(self._instrumentation_summary)

    def try_apply_debug_profile(self, profile: ListPanelDebugProfile) -> bool:
        """Attempt to apply ``profile`` without rebuilding the control."""

        previous = getattr(self, "debug", None)
        if previous is None:
            return False
        if profile == previous:
            self.debug = profile
            self.debug_raw_level = profile.level
            self.debug_level = profile.base_level
            self._diagnostic_logging = (
                self.debug_level >= self.DIAGNOSTIC_LOG_THRESHOLD
            )
            self._refresh_debug_summaries(log=False)
            return True
        changed_features = {
            name
            for name in ListPanelDebugProfile.FEATURE_LABELS
            if getattr(previous, name) != getattr(profile, name)
        }
        allowed_toggles = {
            "report_width_retry_async",
            "report_width_retry",
            "report_width_fallbacks",
            "report_column_widths",
        }
        instrumentation_changed = any(
            getattr(previous, name, False) != getattr(profile, name, False)
            for name in ListPanelDebugProfile.INSTRUMENTATION_LABELS
        )
        if changed_features - allowed_toggles or instrumentation_changed:
            return False
        delta = profile.diff(previous)
        self.debug = profile
        self.debug_raw_level = profile.level
        self.debug_level = profile.base_level
        self._diagnostic_logging = (
            self.debug_level >= self.DIAGNOSTIC_LOG_THRESHOLD
        )
        self._refresh_debug_summaries(log=True)
        toggled_chunks: list[str] = []
        if delta.enabled_features:
            toggled_chunks.append(
                "enabled features: %s" % ", ".join(delta.enabled_features)
            )
        if delta.disabled_features:
            toggled_chunks.append(
                "disabled features: %s" % ", ".join(delta.disabled_features)
            )
        if delta.enabled_instrumentation:
            toggled_chunks.append(
                "enabled instrumentation: %s"
                % ", ".join(delta.enabled_instrumentation)
            )
        if delta.disabled_instrumentation:
            toggled_chunks.append(
                "disabled instrumentation: %s"
                % ", ".join(delta.disabled_instrumentation)
            )
        if toggled_chunks:
            logger.info(
                "ListPanel debug transition %s→%s — %s",
                previous.base_level,
                profile.base_level,
                "; ".join(toggled_chunks),
            )
        self._apply_width_debug_transition(previous, profile)
        return True

    def _apply_width_debug_transition(
        self,
        previous: ListPanelDebugProfile,
        current: ListPanelDebugProfile,
    ) -> None:
        """Synchronize width enforcement state after a debug profile change."""

        if not current.report_column_widths:
            self._pending_column_widths.clear()
            self._column_widths_scheduled = False
        if not current.report_width_retry:
            self._pending_column_widths.clear()
            self._column_widths_scheduled = False
        elif (
            previous.report_width_retry_async
            and not current.report_width_retry_async
            and self._pending_column_widths
        ):
            self._log_diagnostics("forcing immediate retry flush after debug toggle")
            self._flush_pending_column_widths()
        if current.report_column_widths and not previous.report_column_widths:
            try:
                count = self.list.GetColumnCount()
            except Exception:
                return
            for column in range(count):
                width = self.list.GetColumnWidth(column)
                if width <= 0:
                    field = (
                        self._field_order[column]
                        if column < len(self._field_order)
                        else ""
                    )
                    width = (
                        self._default_column_width(field)
                        if field
                        else self.DEFAULT_COLUMN_WIDTH
                    )
                self._ensure_column_width(column, width)

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

    def _populate_plain_items(
        self,
        direct_source: Sequence[Requirement] | Sequence[tuple[int, str]] | None = None,
    ) -> None:
        """Render plain entries into the list control."""

        if direct_source is None:
            plain_iterable = list(self._plain_items)
        else:
            plain_iterable: list[tuple[int, str]] = []
            for entry in direct_source:
                if isinstance(entry, Requirement):
                    try:
                        req_id = int(getattr(entry, "id", 0))
                    except Exception:
                        req_id = 0
                    title = str(getattr(entry, "title", ""))
                    plain_iterable.append((req_id, title))
                else:
                    try:
                        raw_id, raw_title = entry
                    except Exception:
                        plain_iterable.append((0, ""))
                    else:
                        try:
                            req_id = int(raw_id)
                        except Exception:
                            req_id = 0
                        plain_iterable.append((req_id, str(raw_title)))
            self._plain_items = list(plain_iterable)
            plain_iterable = self._plain_items
        self._clear_items()
        for req_id, title in plain_iterable:
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
        if self.debug.plain_post_refresh:
            self._post_population_refresh(stage="populate-plain")
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
        if self.debug.probe_column_reset:
            self._probe_log_column_inventory("pre-reset")
        if self.debug.report_clear_all:
            self.list.ClearAll()
            if self.debug.probe_column_reset:
                self._probe_log_column_inventory("post-clearall")
        else:
            if self.debug.probe_column_reset:
                self._probe_log_column_inventory("pre-fallback-removal")
            self._clear_items()
            removed_all = self._remove_all_columns()
            if not removed_all:
                self._log_diagnostics(
                    "fallback column removal incomplete — invoking ClearAll()",
                )
                with suppress(Exception):
                    self.list.ClearAll()
            self._probe_verify_column_removal("fallback-removal")
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
        if self.debug.probe_column_reset:
            self._probe_log_column_inventory("post-setup")

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

    def _remove_all_columns(self) -> bool:
        """Drop all report-style columns without relying on ``ClearAll``."""

        try:
            count = self.list.GetColumnCount()
        except Exception:
            return True
        success = True
        for idx in range(count - 1, -1, -1):
            try:
                self.list.DeleteColumn(idx)
            except Exception:
                success = False
                logger.debug(
                    "Failed to delete ListPanel column %s during fallback removal",
                    idx,
                    exc_info=True,
                )
        remaining = 0
        with suppress(Exception):
            remaining = self.list.GetColumnCount()
        if remaining:
            success = False
        return success

    def _probe_log_column_inventory(self, stage: str) -> dict[str, object]:
        """Emit diagnostics about current columns for tier-2 probes."""

        if not self.debug.probe_column_reset:
            return {}
        info: dict[str, object] = {"field_order": list(self._field_order)}
        with suppress(Exception):
            info["count"] = self.list.GetColumnCount()
        if info.get("count", 0):
            info["widths"] = self._snapshot_column_widths(int(info["count"]))
        with suppress(Exception):
            style_flag = format(self.list.GetWindowStyleFlag(), "x")
            info["style"] = style_flag
        logger.info("ListPanel column reset probe (%s) — %s", stage, info)
        return info

    def _probe_verify_column_removal(self, stage: str) -> None:
        """Validate fallback column removal and fall back to ``ClearAll``."""

        if not self.debug.probe_column_reset:
            return
        info = self._probe_log_column_inventory(stage)
        remaining = int(info.get("count", 0) or 0)
        if remaining <= 0:
            return
        logger.warning(
            "ListPanel column reset probe: %s left %s column(s); invoking ClearAll()",
            stage,
            remaining,
        )
        with suppress(Exception):
            self.list.ClearAll()
        self._probe_log_column_inventory(stage + "-after-clearall")

    def _post_population_refresh(self, stage: str | None = None) -> None:
        """Force a repaint when implicit refresh is disabled."""

        stage_name = stage or "post-population"
        if self.debug.report_lazy_refresh:
            self._schedule_report_refresh(stage_name)
        else:
            self._apply_immediate_refresh(stage_name)
        if self.debug.probe_force_refresh:
            self._schedule_force_refresh_probe(stage_name)

    def _request_size_event(self) -> bool:
        """Trigger a size event on the list (and panel) for diagnostics."""

        issued = False
        targets: tuple[wx.Window | None, ...] = (self.list, self)
        for target in targets:
            if target is None or not hasattr(target, "SendSizeEvent"):
                continue
            try:
                target.SendSizeEvent()
            except Exception:
                if self._diagnostic_logging:
                    logger.debug(
                        "ListPanel SendSizeEvent failed for %r", target, exc_info=True
                    )
            else:
                issued = True
        return issued

    def _apply_immediate_refresh(self, stage: str | None = None) -> None:
        """Request the list control to repaint immediately."""

        stage_name = stage or "immediate"
        issued_refresh = False
        issued_update = False
        issued_size_event = False
        if self.debug.report_immediate_refresh:
            try:
                self.list.Refresh()
            except Exception:
                if self._diagnostic_logging:
                    logger.debug("ListPanel Refresh() call failed", exc_info=True)
            else:
                issued_refresh = True
        if self.debug.report_immediate_update:
            try:
                self.list.Update()
            except Exception:
                if self._diagnostic_logging:
                    logger.debug("ListPanel Update() call failed", exc_info=True)
            else:
                issued_update = True
        if self.debug.report_send_size_event:
            issued_size_event = self._request_size_event()
        if (
            self.debug.report_style
            and not (issued_refresh or issued_update or issued_size_event)
        ):
            self._ensure_basic_refresh(stage_name)
        if not self._diagnostic_logging:
            return
        column0 = None
        if self.debug.report_style:
            column0 = self._capture_column_width(0)
        self._log_diagnostics(
            "immediate repaint requests — refresh=%s update=%s send_size=%s column0=%s",
            issued_refresh,
            issued_update,
            issued_size_event,
            column0,
        )

    def _probe_filter_metrics(self, metrics: dict[str, object]) -> dict[str, object]:
        """Return a filtered view of metrics suited for human-readable logs."""

        keys = (
            "is_shown",
            "is_enabled",
            "has_focus",
            "is_frozen",
            "client_size",
            "virtual_size",
            "view_rect",
            "top_item",
            "count_per_page",
            "scroll_horizontal_pos",
            "scroll_horizontal_range",
            "scroll_vertical_pos",
            "scroll_vertical_range",
        )
        return {key: metrics.get(key) for key in keys if key in metrics}

    def _schedule_force_refresh_probe(self, stage: str) -> None:
        """Schedule the tier-1 instrumentation that forces a repaint."""

        if not self.debug.probe_force_refresh:
            return
        self._probe_refresh_last_stage = stage
        if self._probe_refresh_pending:
            self._log_diagnostics(
                "refresh probe already pending — stage=%s", stage
            )
            return
        self._probe_refresh_pending = True
        call_after = getattr(wx, "CallAfter", None)
        if callable(call_after):
            call_after(self._execute_force_refresh_probe)
            return
        self._log_diagnostics(
            "executing refresh probe immediately — CallAfter unavailable"
        )
        self._execute_force_refresh_probe()

    def _execute_force_refresh_probe(self) -> None:
        """Perform the force-refresh probe and log the resulting metrics."""

        self._probe_refresh_pending = False
        list_ctrl = getattr(self, "list", None)
        if not list_ctrl:
            return
        with suppress(Exception):
            if list_ctrl.IsBeingDeleted():
                logger.info(
                    "ListPanel refresh probe skipped — control destroyed (stage %s)",
                    self._probe_refresh_last_stage,
                )
                return
        metrics_before = self._collect_control_metrics()
        is_shown_flag = None
        with suppress(Exception):
            is_shown_flag = bool(list_ctrl.IsShown())
        if is_shown_flag is not None:
            metrics_before.setdefault("is_shown_flag", is_shown_flag)
        bounds_code = getattr(wx, "LIST_RECT_BOUNDS", 0)
        bounds_before = (
            self._capture_item_rect(0, bounds_code) if bounds_code else None
        )
        rows_before = self._snapshot_rows()
        logger.info(
            "ListPanel refresh probe (%s) before — metrics=%s bounds=%s rows=%s",
            self._probe_refresh_last_stage,
            self._probe_filter_metrics(metrics_before),
            bounds_before,
            rows_before,
        )
        operations: list[str] = []
        for name in ("Refresh", "Update"):
            method = getattr(list_ctrl, name, None)
            if not callable(method):
                continue
            try:
                method()
            except Exception:
                logger.exception(
                    "ListPanel refresh probe (%s) %s() failed",
                    self._probe_refresh_last_stage,
                    name,
                )
            else:
                operations.append(name.lower())
        size_event = self._request_size_event()
        metrics_after = self._collect_control_metrics()
        if is_shown_flag is not None:
            metrics_after.setdefault("is_shown_flag", is_shown_flag)
        bounds_after = (
            self._capture_item_rect(0, bounds_code) if bounds_code else None
        )
        rows_after = self._snapshot_rows()
        logger.info(
            "ListPanel refresh probe (%s) after — operations=%s size_event=%s metrics=%s bounds=%s rows=%s",
            self._probe_refresh_last_stage,
            operations,
            size_event,
            self._probe_filter_metrics(metrics_after),
            bounds_after,
            rows_after,
        )
        if self.debug.probe_deferred_population:
            self._flush_deferred_plain_population("refresh-probe")

    def _ensure_basic_refresh(self, stage: str) -> None:
        """Schedule a minimal repaint when all immediate hooks are disabled."""

        if not self.debug.report_style:
            return
        self._basic_refresh_stage = stage
        if self._basic_refresh_pending:
            if self._diagnostic_logging:
                self._log_diagnostics(
                    "basic refresh already pending — stage=%s attempts=%s",
                    stage,
                    self._basic_refresh_attempts,
                )
            return
        self._basic_refresh_pending = True
        self._basic_refresh_attempts = 0
        self._log_diagnostics("scheduled basic refresh fallback — stage=%s", stage)
        self._schedule_basic_refresh()

    def _schedule_basic_refresh(self, delay: int | None = None) -> None:
        """Dispatch the basic refresh attempt via ``CallAfter``/``CallLater``."""

        if delay is not None:
            call_later = getattr(wx, "CallLater", None)
            if callable(call_later):
                call_later(delay, self._perform_basic_refresh)
                return
        call_after = getattr(wx, "CallAfter", None)
        if callable(call_after):
            call_after(self._perform_basic_refresh)
            return
        self._perform_basic_refresh()

    def _perform_basic_refresh(self) -> None:
        """Run (or re-schedule) the fallback repaint once the list is ready."""

        if not self._basic_refresh_pending:
            return
        ready, metrics = self._probe_list_ready()
        if not ready:
            self._basic_refresh_attempts += 1
            self._log_diagnostics(
                "basic refresh deferred — stage=%s attempts=%s metrics=%s",
                self._basic_refresh_stage,
                self._basic_refresh_attempts,
                metrics,
            )
            if self._basic_refresh_attempts >= 10:
                self._log_diagnostics(
                    "basic refresh forcing repaint after %s attempts — stage=%s",
                    self._basic_refresh_attempts,
                    self._basic_refresh_stage,
                )
                self._force_basic_refresh()
                self._basic_refresh_pending = False
                return
            delay = min(200, 25 * self._basic_refresh_attempts)
            self._schedule_basic_refresh(delay)
            return
        self._force_basic_refresh()
        self._basic_refresh_pending = False

    def _force_basic_refresh(self) -> None:
        """Invoke a manual Refresh/Update + size event sequence for report mode."""

        list_ctrl = getattr(self, "list", None)
        if not list_ctrl:
            return
        operations: list[str] = []
        for name in ("Refresh", "Update"):
            method = getattr(list_ctrl, name, None)
            if not callable(method):
                continue
            try:
                method()
            except Exception:
                if self._diagnostic_logging:
                    logger.debug(
                        "ListPanel basic refresh %s() failed", name.lower(), exc_info=True
                    )
            else:
                operations.append(name.lower())
        size_event = self._request_size_event()
        if self._diagnostic_logging:
            metrics = self._probe_filter_metrics(self._collect_control_metrics())
            self._log_diagnostics(
                "basic refresh executed — stage=%s operations=%s size_event=%s metrics=%s attempts=%s",
                self._basic_refresh_stage,
                operations,
                size_event,
                metrics,
                self._basic_refresh_attempts,
            )
        self._basic_refresh_stage = ""

    def _schedule_report_refresh(self, stage: str) -> None:
        """Fallback for report mode when lazy refresh fails to repaint."""

        if not self.debug.report_style:
            return
        if self._report_refresh_scheduled:
            return
        self._report_refresh_scheduled = True
        self._report_refresh_stage = stage
        self._log_diagnostics(
            "scheduled explicit report refresh fallback — stage=%s",
            stage,
        )
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
                        "report refresh giving up after %s deferred attempts — stage=%s",
                        attempts,
                        self._report_refresh_stage,
                    )
                else:
                    self._log_diagnostics(
                        "report refresh fallback without CallAfter (attempt %s) — stage=%s",
                        attempts,
                        self._report_refresh_stage,
                    )
                self._apply_immediate_refresh(
                    self._report_refresh_stage or "report-refresh"
                )
                return
            self._log_diagnostics(
                "report refresh deferred — control not yet shown (attempt %s) stage=%s",
                attempts,
                self._report_refresh_stage,
            )
            self._schedule_report_refresh(self._report_refresh_stage or "post-population")
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
        self._apply_immediate_refresh(self._report_refresh_stage or "report-refresh")
        self._log_diagnostics(
            "report refresh applied — stage=%s count=%s",
            self._report_refresh_stage,
            count,
        )
        self._report_refresh_stage = ""

    def _probe_plain_preview(
        self,
        requirements: Sequence[Requirement],
        limit: int = 3,
    ) -> list[tuple[int, str]]:
        """Return a condensed preview of requirement ids and titles."""

        preview: list[tuple[int, str]] = []
        for req in list(requirements)[:limit]:
            try:
                req_id = int(getattr(req, "id", 0))
            except Exception:
                req_id = 0
            preview.append((req_id, str(getattr(req, "title", ""))))
        return preview

    def _probe_list_ready(self) -> tuple[bool, dict[str, object]]:
        """Return whether the list is ready for population along with metrics."""

        list_ctrl = getattr(self, "list", None)
        if not list_ctrl:
            return True, {}
        metrics: dict[str, object] = {}
        shown_flag = None
        with suppress(Exception):
            shown_flag = bool(list_ctrl.IsShown())
        metrics["is_shown_flag"] = shown_flag
        shown_screen = None
        with suppress(Exception):
            shown_screen = bool(list_ctrl.IsShownOnScreen())
        metrics["is_shown_on_screen"] = shown_screen
        size_tuple = (0, 0)
        with suppress(Exception):
            size = list_ctrl.GetClientSize()
            size_tuple = (size.width, size.height)
        metrics["client_size"] = size_tuple
        ready = bool(size_tuple[0] > 0 and size_tuple[1] > 0)
        if shown_screen is not None:
            ready = ready and shown_screen
        elif shown_flag is not None:
            ready = ready and bool(shown_flag)
        return ready, metrics

    def _maybe_schedule_deferred_plain_population(
        self,
        requirements: Sequence[Requirement],
        stage: str,
    ) -> bool:
        """Delay plain population until the widget becomes visible."""

        if not self.debug.plain_deferred_population:
            return False
        ready, metrics = self._probe_list_ready()
        if ready:
            if self._probe_deferred_plain_pending:
                if self.debug.probe_deferred_population:
                    logger.info(
                        "ListPanel deferred population probe: control became ready during %s",
                        stage,
                    )
                self._flush_deferred_plain_population(f"auto:{stage}")
            return False
        payload = list(requirements)
        preview: list[str] | None = None
        if self.debug.probe_deferred_population:
            preview = self._probe_plain_preview(payload)
            if self._probe_deferred_plain_pending:
                logger.info(
                    "ListPanel deferred population probe: updating pending payload — previous_stage=%s new_stage=%s metrics=%s sample=%s",
                    self._probe_deferred_plain_stage,
                    stage,
                    metrics,
                    preview,
                )
            else:
                logger.info(
                    "ListPanel deferred population probe: deferring plain update (%s) metrics=%s sample=%s",
                    stage,
                    metrics,
                    preview,
                )
        if not self.debug.plain_deferred_queue:
            if self.debug.probe_deferred_population:
                logger.info(
                    "ListPanel deferred population probe: queue disabled — executing plain update immediately (%s)",
                    stage,
                )
            return False
        self._probe_deferred_plain_payload = payload
        self._probe_deferred_plain_pending = True
        self._probe_deferred_plain_stage = stage
        self._probe_deferred_plain_attempts = 0
        if not self.debug.plain_deferred_callafter:
            self._flush_deferred_plain_population(f"immediate:{stage}")
            return True
        call_after = getattr(wx, "CallAfter", None)
        if callable(call_after):
            call_after(self._flush_deferred_plain_population, f"CallAfter:{stage}")
            return True
        self._flush_deferred_plain_population(f"fallback:{stage}")
        return True

    def _flush_deferred_plain_population(self, reason: str | None = None) -> None:
        """Execute any delayed plain population when the control is ready."""

        if not self._probe_deferred_plain_pending:
            return
        descriptor = reason or self._probe_deferred_plain_stage or "manual"
        ready, metrics = self._probe_list_ready()
        if not ready:
            if self.debug.probe_deferred_population:
                logger.info(
                    "ListPanel deferred population probe: still waiting (%s) pending_stage=%s metrics=%s",
                    descriptor,
                    self._probe_deferred_plain_stage,
                    metrics,
                )
            self._probe_deferred_plain_attempts += 1
            if (
                self._probe_deferred_plain_attempts >= 20
                or not self.debug.plain_deferred_timer
            ):
                if self.debug.probe_deferred_population:
                    logger.warning(
                        "ListPanel deferred population probe: giving up after %s attempts (%s)",
                        self._probe_deferred_plain_attempts,
                        descriptor,
                    )
                ready = True
            else:
                delay = min(200, 10 * max(1, self._probe_deferred_plain_attempts))
                call_later = (
                    getattr(wx, "CallLater", None)
                    if self.debug.plain_deferred_timer
                    else None
                )
                if callable(call_later):
                    call_later(delay, self._flush_deferred_plain_population, descriptor)
                    return
                if self.debug.plain_deferred_callafter:
                    call_after = getattr(wx, "CallAfter", None)
                    if callable(call_after):
                        call_after(self._flush_deferred_plain_population, descriptor)
                        return
                ready = True
        else:
            self._probe_deferred_plain_attempts = 0
        payload = self._probe_deferred_plain_payload or list(self._plain_source)
        if self.debug.probe_deferred_population:
            preview = self._probe_plain_preview(payload)
            logger.info(
                "ListPanel deferred population probe: executing deferred fill (%s) metrics=%s count=%s sample=%s",
                descriptor,
                metrics,
                len(payload),
                preview,
            )
        self._probe_deferred_plain_pending = False
        self._probe_deferred_plain_payload = None
        self._probe_deferred_plain_stage = ""
        if self.debug.plain_cached_items:
            self._update_plain_items(payload)
            self._populate_plain_items()
        else:
            self._populate_plain_items(payload)

    def _on_list_show(self, event: wx.Event) -> None:
        """Handle show/hide transitions for the underlying list control."""

        shown = False
        if hasattr(event, "IsShown"):
            with suppress(Exception):
                shown = bool(event.IsShown())
        self._on_probe_list_show(shown)
        if hasattr(event, "Skip"):
            event.Skip()

    def _on_probe_list_show(self, shown: bool) -> None:
        """Flush deferred population once the list becomes visible."""

        if self.debug.probe_deferred_population:
            logger.info(
                "ListPanel deferred population probe: EVT_SHOW shown=%s pending=%s stage=%s",
                shown,
                self._probe_deferred_plain_pending,
                self._probe_deferred_plain_stage,
            )
        if shown and self._probe_deferred_plain_pending:
            self._flush_deferred_plain_population("EVT_SHOW")

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
        if not self.debug.report_width_fallbacks:
            return False
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
        if self._column_widths_scheduled:
            return
        self._column_widths_scheduled = True
        if self.debug.report_width_retry_async:
            wx.CallAfter(self._flush_pending_column_widths)
            self._log_diagnostics("scheduled deferred column width flush")
            return
        self._log_diagnostics("executing column width flush synchronously")
        self._flush_pending_column_widths()

    def _flush_pending_column_widths(self) -> None:
        """Retry collapsed column widths once the widget is fully realized."""

        while True:
            self._column_widths_scheduled = False
            pending = list(self._pending_column_widths.items())
            self._pending_column_widths.clear()
            if not pending:
                return
            self._log_diagnostics(
                "processing %s pending column width attempts",
                len(pending),
            )
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
                        "ListPanel column %s remains collapsed after retries; giving up",
                        column,
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
            if not self._pending_column_widths:
                return
            self._log_diagnostics(
                "retry queue still has %s column(s)", len(self._pending_column_widths)
            )
            if not self.debug.report_width_retry_async:
                continue
            if not self._column_widths_scheduled:
                self._column_widths_scheduled = True
                wx.CallAfter(self._flush_pending_column_widths)
                self._log_diagnostics("rescheduled deferred column width flush")
            return

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
            if self._maybe_schedule_deferred_plain_population(
                self._plain_source,
                "set_requirements",
            ):
                return
            if self.debug.plain_cached_items:
                self._update_plain_items(requirements)
                self._populate_plain_items()
            else:
                self._populate_plain_items(self._plain_source)
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
            if self._maybe_schedule_deferred_plain_population(
                self._plain_source,
                "refresh-plain",
            ):
                return
            if self.debug.plain_cached_items:
                self._update_plain_items()
                self._populate_plain_items()
            else:
                self._populate_plain_items(self._plain_source)
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
            self._post_population_refresh(stage="refresh-report-simple")
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
        self._post_population_refresh(stage="refresh-report-full")
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
