"""Simplified requirement list panel for debugging text rendering."""

from __future__ import annotations

import os
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
from .helpers import dip, inherit_background
from .requirement_model import RequirementModel

if TYPE_CHECKING:  # pragma: no cover - only used in type checking
    from ..config import ConfigManager
    from .controllers import DocumentsController


class ListPanelRenderingMode(Enum):
    """Rendering presets for ListPanel."""

    DEBUG = "debug"
    FULL = "full"


def _determine_rendering_mode() -> ListPanelRenderingMode:
    """Return rendering mode for ListPanel, defaulting to debug."""

    explicit = os.environ.get("COOKAREQ_LIST_PANEL_RENDERING")
    if explicit:
        normalized = explicit.strip().lower()
        if normalized in {"full", "prod", "production", "release"}:
            return ListPanelRenderingMode.FULL
        if normalized in {"debug", "diagnostic", "safe"}:
            return ListPanelRenderingMode.DEBUG
        logger.warning(
            "Unknown COOKAREQ_LIST_PANEL_RENDERING value %r; falling back to debug mode.",
            explicit,
        )
        return ListPanelRenderingMode.DEBUG

    legacy = os.environ.get("COOKAREQ_LIST_PANEL_DEBUG")
    if legacy is not None:
        normalized = legacy.strip().lower()
        if normalized in {"0", "false", "no", "off"}:
            return ListPanelRenderingMode.FULL
        return ListPanelRenderingMode.DEBUG

    return ListPanelRenderingMode.DEBUG


_RENDERING_MODE = _determine_rendering_mode()
if _RENDERING_MODE is ListPanelRenderingMode.FULL:
    logger.warning(
        "ListPanel full rendering mode is temporarily unavailable; forcing debug layout while "
        "the repaint regression is investigated.",
    )
    _RENDERING_MODE = ListPanelRenderingMode.DEBUG


class ListPanel(wx.Panel):
    """Panel with a minimal requirement list."""

    DEFAULT_COLUMN_WIDTH = 200

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
    ):
        super().__init__(parent)
        inherit_background(self, parent)

        self.model = model if model is not None else RequirementModel()
        self.columns: list[str] = []
        self._field_order: list[str] = ["title"]
        self.derived_map: dict[str, list[int]] = {}
        self.current_filters: dict = {}
        self._labels: list[LabelDef] = []
        self._docs_controller = docs_controller
        self._current_doc_prefix: str | None = None
        self._sort_column = 0
        self._sort_ascending = True
        self._on_clone = on_clone
        self._on_delete = on_delete
        self._on_delete_many = on_delete_many
        self._on_sort_changed = on_sort_changed
        self._on_derive = on_derive

        self.filter_summary = wx.StaticText(self, label="")
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.filter_summary, 0, wx.EXPAND | wx.BOTTOM, dip(self, 4))
        sizer.Add(self.list, 1, wx.EXPAND)
        self.SetSizer(sizer)

        self._apply_columns()
        logger.info(
            "ListPanel running in heavily simplified debug mode: filters, context menus, "
            "custom label rendering, and bitmap handling are disabled."
        )

    # ------------------------------------------------------------------
    # Simplified configuration helpers
    # ------------------------------------------------------------------
    def set_documents_controller(self, controller: DocumentsController | None) -> None:
        self._docs_controller = controller

    def set_active_document(self, prefix: str | None) -> None:
        self._current_doc_prefix = prefix

    def update_labels_list(self, labels: list[LabelDef]) -> None:
        self._labels = list(labels)

    # Columns -----------------------------------------------------------
    def _apply_columns(self) -> None:
        self.list.ClearAll()
        for idx, field in enumerate(self._field_order):
            if field == "title":
                label = _("Title")
            else:
                label = locale.field_label(field)
            self.list.InsertColumn(idx, label)

    def set_columns(self, fields: list[str]) -> None:
        filtered: list[str] = []
        for field in fields:
            if field == "labels":
                continue
            filtered.append(field)
        self.columns = filtered
        self._field_order = ["title", *self.columns]
        self._apply_columns()
        self._refresh()

    def load_column_widths(self, config: ConfigManager) -> None:
        for idx in range(self.list.GetColumnCount()):
            width = config.read_int(f"col_width_{idx}", self.DEFAULT_COLUMN_WIDTH)
            if width <= 0:
                width = self.DEFAULT_COLUMN_WIDTH
            self.list.SetColumnWidth(idx, width)

    def save_column_widths(self, config: ConfigManager) -> None:
        for idx in range(self.list.GetColumnCount()):
            width = self.list.GetColumnWidth(idx)
            if width <= 0:
                width = self.DEFAULT_COLUMN_WIDTH
            config.write_int(f"col_width_{idx}", width)

    def load_column_order(self, config: ConfigManager) -> None:
        # Column reordering is disabled in the simplified panel. Keep the stored
        # order so that later restorations (when the full panel returns) do not
        # crash, but ignore the value during debug mode.
        _ = config.read("col_order", "")

    def save_column_order(self, config: ConfigManager) -> None:
        config.write("col_order", ",".join(self._field_order))

    def reorder_columns(self, from_col: int, to_col: int) -> None:
        # Reordering was handled by the complex implementation. In debug mode we
        # leave the layout static to reduce repaint surface.
        return

    # Data --------------------------------------------------------------
    def set_requirements(
        self,
        requirements: list[Requirement],
        derived_map: dict[str, list[int]] | None = None,
    ) -> None:
        self.model.set_requirements(requirements)
        if derived_map is None:
            derived_map = {}
            for req in requirements:
                for link in getattr(req, "links", []) or []:
                    rid = self._link_rid(link)
                    if not rid:
                        continue
                    derived_map.setdefault(rid, []).append(req.id)
        self.derived_map = derived_map
        self._refresh()

    def recalc_derived_map(self, requirements: list[Requirement]) -> None:
        derived_map: dict[str, list[int]] = {}
        for req in requirements:
            for link in getattr(req, "links", []) or []:
                rid = self._link_rid(link)
                if not rid:
                    continue
                derived_map.setdefault(rid, []).append(req.id)
        self.derived_map = derived_map
        self._refresh()

    def record_link(self, parent_rid: str, child_id: int) -> None:
        self.derived_map.setdefault(parent_rid, []).append(child_id)

    def refresh(self, *, select_id: int | None = None) -> None:
        self._refresh()
        if select_id is not None:
            self.focus_requirement(select_id)

    def _refresh(self) -> None:
        items = self.model.get_visible()
        self.list.DeleteAllItems()
        for req in items:
            index = self.list.InsertItem(
                self.list.GetItemCount(), self._basic_cell_text(req, "title"), -1
            )
            try:
                req_id = int(getattr(req, "id", 0))
            except (TypeError, ValueError):
                req_id = 0
            self.list.SetItemData(index, req_id)
            for col, field in enumerate(self._field_order[1:], start=1):
                self.list.SetItem(index, col, self._basic_cell_text(req, field))

    # Sorting -----------------------------------------------------------
    def sort(self, column: int, ascending: bool) -> None:
        if column < 0 or column >= len(self._field_order):
            return
        field = self._field_order[column]
        self._sort_column = column
        self._sort_ascending = ascending
        self.model.sort(field, ascending)
        self._refresh()
        if self._on_sort_changed:
            self._on_sort_changed(column, ascending)

    # Selection ---------------------------------------------------------
    def focus_requirement(self, req_id: int) -> None:
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
        if hasattr(self.list, "EnsureVisible"):
            with suppress(Exception):
                self.list.EnsureVisible(target_index)

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
    # Basic text helpers
    # ------------------------------------------------------------------
    def _link_rid(self, link: object) -> str:
        """Return the RID associated with ``link`` in a robust manner."""

        if isinstance(link, dict):
            value = link.get("rid") or link.get("id") or ""
            return str(value)
        value = getattr(link, "rid", link)
        if value is None:
            return ""
        return str(value)

    def _basic_cell_text(self, req: Requirement, field: str) -> str:
        if field == "derived_count":
            rid = getattr(req, "rid", "") or str(getattr(req, "id", ""))
            return str(len(self.derived_map.get(rid, [])))
        value = getattr(req, field, "")
        if field == "links":
            links = value or []
            return ", ".join(filter(None, (self._link_rid(link) for link in links)))
        if field == "labels":
            labels = value or []
            return ", ".join(str(label) for label in labels)
        if field == "attachments":
            attachments = value or []
            return ", ".join(str(getattr(att, "path", att)) for att in attachments)
        if isinstance(value, Enum):
            return locale.code_to_label(field, value.value)
        if value is None:
            return ""
        return str(value)
