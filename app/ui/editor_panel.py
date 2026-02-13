"""Requirement editor panel."""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from collections.abc import Callable

import wx
import wx.adv
from wx.lib.scrolledpanel import ScrolledPanel

from ..services.requirements import (
    Document,
    LabelDef,
    RequirementsService,
    RequirementIDCollisionError,
    label_color,
    parse_rid,
    rid_for,
    stable_color,
)
from ..core.model import (
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
    requirement_fingerprint,
)
from ..util.time import local_now_str, normalize_timestamp
from ..i18n import _
from . import locale
from .enums import ENUMS
from .helpers import AutoHeightListCtrl, HelpStaticBox, dip, inherit_background, make_help_button
from .label_selection_dialog import LabelSelectionDialog
from .resources import load_editor_config
from .widgets.markdown_view import MarkdownContent

logger = logging.getLogger(__name__)


class EditorPanel(wx.Panel):
    """Panel for creating and editing requirements."""

    def __init__(
        self,
        parent: wx.Window,
        on_save: Callable[[], None] | None = None,
        on_discard: Callable[[], bool] | None = None,
    ):
        """Initialize requirement editor widgets."""
        super().__init__(parent)
        inherit_background(self, parent)
        self.fields: dict[str, wx.TextCtrl] = {}
        self.enums: dict[str, wx.Choice] = {}
        self._autosize_fields: list[wx.TextCtrl] = []
        self._suspend_events = False
        self.original_modified_at = ""
        self._on_save_callback = on_save
        self._on_discard_callback = on_discard
        self._service: RequirementsService | None = None
        self._doc_prefix: str | None = None
        self.original_id: int | None = None
        self._document: Document | None = None
        self._known_ids: set[int] | None = None
        self._id_conflict = False
        self._saved_state: dict[str, Any] | None = None
        self._link_metadata_cache: dict[str, dict[str, Any]] = {}
        self._statement_mode: wx.Choice | None = None
        self._statement_preview: MarkdownContent | None = None
        self._insert_image_btn: wx.Button | None = None
        self._insert_table_btn: wx.Button | None = None
        self._insert_formula_btn: wx.Button | None = None
        self._insert_heading_btn: wx.Button | None = None
        self._insert_bold_btn: wx.Button | None = None
        self._label_defs: list[LabelDef] = []
        self._labels_allow_freeform = False
        self._requirement_selected = True

        self._attachment_link_re = re.compile(r"attachment:([A-Za-z0-9_-]+)")

        config = load_editor_config()
        labels = {name: locale.field_label(name) for name in config.field_names}
        self._help_texts = config.localized_help()

        self._content_panel = ScrolledPanel(self)
        self._content_panel.SetAutoLayout(True)
        inherit_background(self._content_panel, self)
        content = self._content_panel
        content_sizer = wx.BoxSizer(wx.VERTICAL)
        border = dip(self, 5)

        compact_text_fields = {"id"}
        text_specs = {spec.name: spec for spec in config.text_fields}
        grid_specs = {spec.name: spec for spec in config.grid_fields}

        def add_text_field(spec_name: str) -> None:
            spec = text_specs[spec_name]
            label = wx.StaticText(content, label=labels[spec.name])
            help_btn = make_help_button(content, self._help_texts[spec.name])
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            if spec.name == "statement":
                mode = wx.Choice(content, choices=[_("Edit"), _("View")])
                mode.SetSelection(0)
                mode.Bind(wx.EVT_CHOICE, self._on_statement_mode_change)
                row.Add(mode, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
                self._statement_mode = mode
                insert_btn = self._create_icon_button(
                    content,
                    art_ids=(wx.ART_FILE_OPEN, wx.ART_NORMAL_FILE),
                    tooltip=_("Insert image"),
                    handler=self._on_insert_image,
                )
                row.Add(insert_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
                self._insert_image_btn = insert_btn
                table_btn = self._create_icon_button(
                    content,
                    art_ids=(wx.ART_REPORT_VIEW, wx.ART_LIST_VIEW),
                    tooltip=_("Insert table"),
                    handler=self._on_insert_table,
                )
                row.Add(table_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
                self._insert_table_btn = table_btn
                formula_btn = self._create_icon_button(
                    content,
                    art_ids=(wx.ART_TIP, wx.ART_QUESTION),
                    tooltip=_("Insert formula"),
                    handler=self._on_insert_formula,
                )
                row.Add(formula_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
                self._insert_formula_btn = formula_btn
                heading_btn = self._create_icon_button(
                    content,
                    art_ids=(wx.ART_HELP_BOOK, wx.ART_INFORMATION),
                    tooltip=_("Insert heading"),
                    handler=self._on_insert_heading,
                )
                row.Add(heading_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
                self._insert_heading_btn = heading_btn
                bold_btn = self._create_icon_button(
                    content,
                    art_ids=(wx.ART_TICK_MARK, wx.ART_EXECUTABLE_FILE),
                    tooltip=_("Insert bold text"),
                    handler=self._on_insert_bold,
                )
                row.Add(bold_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
                self._insert_bold_btn = bold_btn
            style = wx.TE_MULTILINE if spec.multiline else 0
            ctrl = wx.TextCtrl(content, style=style)
            if spec.multiline:
                self._bind_autosize(ctrl)
            if spec.name == "statement":
                ctrl.Bind(wx.EVT_TEXT, self._on_statement_text_change)
            self.fields[spec.name] = ctrl

            if spec.name in compact_text_fields:
                row.Add(ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
                content_sizer.Add(row, 0, wx.EXPAND | wx.TOP, border)
            else:
                content_sizer.Add(row, 0, wx.TOP, border)
                # Multiline controls are sized manually, so the sizer receives no grow factor.
                content_sizer.Add(ctrl, 0, wx.EXPAND | wx.TOP, border)

            if spec.hint:
                ctrl.SetHint(_(spec.hint))
            if spec.name == "id":
                ctrl.Bind(wx.EVT_TEXT, self._on_id_change)
            if spec.name == "statement":
                preview = MarkdownContent(
                    content,
                    markdown="",
                    foreground_colour=content.GetForegroundColour(),
                    background_colour=wx.WHITE,
                    render_math=True,
                )
                preview.SetMinSize(wx.Size(-1, dip(self, 160)))
                preview.Hide()
                self._statement_preview = preview
                content_sizer.Add(preview, 1, wx.EXPAND | wx.TOP, border)

        def add_grid_field(spec_name: str) -> None:
            spec = grid_specs[spec_name]
            container = wx.BoxSizer(wx.VERTICAL)
            label = wx.StaticText(content, label=labels[spec.name])
            help_btn = make_help_button(content, self._help_texts[spec.name])
            if spec.control == "enum":
                enum_cls = ENUMS[spec.name]
                choices = [locale.code_to_label(spec.name, e.value) for e in enum_cls]
                choice = wx.Choice(content, choices=choices)
                row = wx.BoxSizer(wx.HORIZONTAL)
                row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
                row.Add(choice, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
                row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
                self.enums[spec.name] = choice
                container.Add(row, 0, wx.EXPAND | wx.TOP, border)
            else:
                row = wx.BoxSizer(wx.HORIZONTAL)
                row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
                ctrl = wx.TextCtrl(content)
                if spec.hint:
                    ctrl.SetHint(_(spec.hint))
                self.fields[spec.name] = ctrl
                row.Add(ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
                row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
                container.Add(row, 0, wx.EXPAND | wx.TOP, border)
            content_sizer.Add(container, 0, wx.EXPAND)

        for name in ("id", "title", "statement", "conditions", "rationale"):
            add_text_field(name)

        # Notes are promoted to the primary requirement block.
        container = wx.BoxSizer(wx.VERTICAL)
        row = wx.BoxSizer(wx.HORIZONTAL)
        label = wx.StaticText(content, label=_("Notes"))
        help_btn = make_help_button(content, self._help_texts["notes"])
        row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
        row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        container.Add(row, 0, wx.TOP, border)
        self.notes_ctrl = wx.TextCtrl(content, style=wx.TE_MULTILINE)
        self._bind_autosize(self.notes_ctrl)
        container.Add(self.notes_ctrl, 0, wx.EXPAND | wx.TOP, border)
        content_sizer.Add(container, 0, wx.EXPAND | wx.TOP, border)

        add_text_field("source")
        add_grid_field("status")

        labels_sizer = self._create_labels_section(content)
        content_sizer.Add(labels_sizer, 0, wx.EXPAND | wx.TOP, border)

        # attachments section --------------------------------------------
        a_sizer = HelpStaticBox(
            content,
            _("Attachments"),
            self._help_texts["attachments"],
        )
        a_box = a_sizer.GetStaticBox()
        self.attachments_list = AutoHeightListCtrl(
            a_box,
            style=wx.LC_REPORT | wx.BORDER_SUNKEN | wx.LC_SINGLE_SEL,
        )
        self.attachments_list.InsertColumn(0, _("File"))
        self.attachments_list.InsertColumn(1, _("Note"))
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.add_attachment_btn = wx.Button(a_box, label=_("Add"))
        self.remove_attachment_btn = wx.Button(a_box, label=_("Remove"))
        self.add_attachment_btn.Bind(wx.EVT_BUTTON, self._on_add_attachment)
        self.remove_attachment_btn.Bind(wx.EVT_BUTTON, self._on_remove_attachment)
        btn_row.Add(self.add_attachment_btn, 0)
        btn_row.Add(self.remove_attachment_btn, 0, wx.LEFT, 5)
        a_sizer.Add(self.attachments_list, 0, wx.EXPAND | wx.TOP, border)
        a_sizer.Add(btn_row, 0, wx.ALIGN_RIGHT | wx.TOP, border)
        content_sizer.Add(a_sizer, 0, wx.EXPAND | wx.TOP, border)

        for name in ("acceptance", "assumptions"):
            add_text_field(name)

        for name in ("modified_at", "owner", "revision"):
            add_grid_field(name)

        # grouped links and metadata ------------------------------------
        links_grid = wx.FlexGridSizer(cols=2, hgap=5, vgap=5)
        links_grid.AddGrowableCol(0, 1)
        links_grid.AddGrowableCol(1, 1)
        links_grid.AddGrowableRow(0, 1)

        # generic links section ----------------------------------------
        ln_sizer = self._create_links_section(
            _("Derived from"),
            "links",
            help_key="links",
        )
        links_grid.Add(ln_sizer, 0, wx.EXPAND | wx.TOP, border)

        content_sizer.Add(links_grid, 0, wx.EXPAND | wx.TOP, border)

        for name in ("type", "priority", "verification"):
            add_grid_field(name)

        row = wx.BoxSizer(wx.HORIZONTAL)
        label = wx.StaticText(content, label=_("Approved at"))
        help_btn = make_help_button(content, self._help_texts["approved_at"])
        row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.approved_picker = wx.adv.DatePickerCtrl(
            content,
            style=wx.adv.DP_ALLOWNONE,
        )
        row.Add(self.approved_picker, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        content_sizer.Add(row, 0, wx.EXPAND | wx.TOP, border)

        self._content_panel.SetSizer(content_sizer)
        self._content_panel.SetupScrolling()

        separator = wx.StaticLine(self)
        footer = wx.Panel(self)
        inherit_background(footer, self)
        footer_sizer = wx.BoxSizer(wx.HORIZONTAL)
        footer.SetSizer(footer_sizer)
        footer_sizer.AddStretchSpacer()
        self.save_btn = wx.Button(footer, label=_("Save"))
        self.save_btn.Bind(wx.EVT_BUTTON, self._on_save_button)
        footer_sizer.Add(self.save_btn, 0, wx.RIGHT, border)
        self.cancel_btn = wx.Button(footer, label=_("Cancel"))
        self.cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel_button)
        footer_sizer.Add(self.cancel_btn, 0)

        root_sizer = wx.BoxSizer(wx.VERTICAL)
        root_sizer.Add(self._content_panel, 1, wx.EXPAND)
        root_sizer.Add(separator, 0, wx.EXPAND)
        root_sizer.Add(footer, 0, wx.EXPAND)
        self.SetSizer(root_sizer)

        self.attachments: list[dict[str, str]] = []
        self.extra: dict[str, Any] = {
            "labels": [],
            "approved_at": None,
            "notes": "",
        }
        self.current_path: Path | None = None
        self.mtime: float | None = None
        self._refresh_labels_display()
        self._refresh_attachments()
        self.mark_clean()

    def set_requirement_selected(self, selected: bool) -> None:
        """Toggle edit controls based on whether a requirement is selected."""
        self._requirement_selected = bool(selected)
        self._content_panel.Enable(self._requirement_selected)
        self.save_btn.Enable(self._requirement_selected)
        self.cancel_btn.Enable(self._requirement_selected)

    def FitInside(self) -> None:  # noqa: N802 - wxWidgets API casing
        """Recalculate the scrollable area of the editor form."""
        self._content_panel.FitInside()
        self._content_panel.Layout()
        super().Layout()

    def Layout(self) -> bool:  # noqa: N802 - wxWidgets API casing
        """Layout both the scrollable content and the outer panel."""
        self._content_panel.Layout()
        return super().Layout()

    def _create_labels_section(self, content: wx.Window) -> wx.StaticBoxSizer:
        """Create compact labels selector section placed near requirement text."""
        box_sizer = HelpStaticBox(
            content,
            _("Labels"),
            self._help_texts["labels"],
        )
        box = box_sizer.GetStaticBox()
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.labels_panel = wx.Panel(box)
        self.labels_panel.SetBackgroundColour(box.GetBackgroundColour())
        self.labels_panel.SetSizer(wx.BoxSizer(wx.HORIZONTAL))
        line_height = self.GetCharHeight() + 6
        self.labels_panel.SetMinSize((-1, line_height))
        self.labels_panel.Bind(wx.EVT_LEFT_DOWN, self._on_labels_click)
        row.Add(self.labels_panel, 1, wx.EXPAND | wx.RIGHT, 5)
        edit_labels_btn = wx.Button(box, label=_("Edit..."))
        edit_labels_btn.Bind(wx.EVT_BUTTON, self._on_labels_click)
        row.Add(edit_labels_btn, 0)
        box_sizer.Add(row, 0, wx.EXPAND | wx.TOP, dip(self, 5))
        return box_sizer

    def _reset_scroll_position(self) -> None:
        """Return the editor viewport to the top of the form."""
        self._content_panel.Scroll(0, 0)

    # helpers -------------------------------------------------------------
    def set_service(self, service: RequirementsService | None) -> None:
        """Configure requirements service used by the editor."""
        self._service = service
        self._document = None
        self._known_ids = None
        self._id_conflict = False
        self._link_metadata_cache = {}
        self._on_id_change()

    def set_document(self, prefix: str | None) -> None:
        """Select active document ``prefix`` for ID validation."""
        self._doc_prefix = prefix
        self.extra["doc_prefix"] = prefix or ""
        self._document = None
        self._known_ids = None
        self._id_conflict = False
        self._link_metadata_cache = {}
        self._on_id_change()

    def _effective_prefix(self) -> str | None:
        prefix = self._doc_prefix or str(self.extra.get("doc_prefix", "")).strip()
        return prefix or None

    def _require_service(self) -> RequirementsService:
        if self._service is None:
            raise RuntimeError("requirements service is not configured")
        return self._service

    def _resolve_document(self, prefix: str | None = None) -> Document | None:
        service = self._service
        target = prefix or self._effective_prefix()
        if service is None or not target:
            return None
        if self._document is not None and self._document.prefix == target:
            return self._document
        try:
            doc = service.get_document(target)
        except Exception:  # pragma: no cover - service errors surfaced via UI
            logger.exception("Failed to load document metadata for %s", target)
            return None
        if target == self._doc_prefix:
            self._document = doc
        return doc

    def _refresh_known_ids(
        self,
        *,
        prefix: str | None = None,
        doc: Document | None = None,
    ) -> set[int]:
        service = self._service
        target = prefix or (doc.prefix if doc else self._effective_prefix())
        if service is None or not target:
            self._known_ids = set()
            return self._known_ids
        try:
            ids = set(service.list_item_ids(target))
        except Exception:  # pragma: no cover - filesystem/service errors
            logger.exception("Failed to enumerate requirement ids in %s", target)
            ids = set()
        if target == self._effective_prefix():
            self._known_ids = ids
        return ids

    def _get_known_ids(self) -> set[int]:
        if self._known_ids is None:
            return self._refresh_known_ids()
        return self._known_ids

    def _has_id_conflict(
        self,
        req_id: int,
        *,
        prefix: str | None = None,
        doc: Document | None = None,
    ) -> bool:
        if req_id <= 0:
            return False
        if self.original_id is not None and req_id == self.original_id:
            return False
        ids = self._refresh_known_ids(prefix=prefix, doc=doc) if doc is not None else self._get_known_ids()
        return req_id in ids

    def _bind_autosize(self, ctrl: wx.TextCtrl) -> None:
        """Register multiline text control for dynamic height."""
        self._autosize_fields.append(ctrl)

        def _handler(evt: wx.Event) -> None:
            self._auto_resize_text(ctrl)
            evt.Skip()

        ctrl.Bind(wx.EVT_TEXT, _handler)
        ctrl.Bind(wx.EVT_SIZE, _handler)
        self._auto_resize_text(ctrl)

    def _auto_resize_text(self, ctrl: wx.TextCtrl) -> None:
        if self._suspend_events:
            return
        lines = max(ctrl.GetNumberOfLines(), 1)
        line_height = ctrl.GetCharHeight()
        border = ctrl.GetWindowBorderSize().height * 2
        padding = 4
        height = line_height * (lines + 1) + border + padding
        if ctrl.GetMinSize().height != height:
            ctrl.SetMinSize((-1, height))
            ctrl.SetSize((-1, height))
            self.FitInside()
            self.Layout()

    def _auto_resize_all(self) -> None:
        for ctrl in self._autosize_fields:
            self._auto_resize_text(ctrl)

    @contextmanager
    def _bulk_update(self):
        """Temporarily disable events and redraws during bulk updates."""
        self._suspend_events = True
        self.Freeze()
        try:
            yield
        finally:
            self.Thaw()
            self._suspend_events = False

    def _create_links_section(
        self,
        label: str,
        attr: str,
        *,
        help_key: str,
        id_name: str | None = None,
        list_name: str | None = None,
    ) -> wx.StaticBoxSizer:
        pad = dip(self, 5)
        sizer = HelpStaticBox(
            self._content_panel,
            label,
            self._help_texts[help_key],
        )
        box = sizer.GetStaticBox()
        row = wx.BoxSizer(wx.HORIZONTAL)
        id_ctrl = wx.TextCtrl(box)
        id_ctrl.SetHint(_("Requirement ID"))
        row.Add(id_ctrl, 1, wx.EXPAND | wx.RIGHT, 5)
        add_btn = wx.Button(box, label=_("Add"))
        add_btn.Bind(wx.EVT_BUTTON, lambda _evt, a=attr: self._on_add_link_generic(a))
        row.Add(add_btn, 0, wx.RIGHT, 5)
        remove_btn = wx.Button(box, label=_("Remove"))
        remove_btn.Bind(
            wx.EVT_BUTTON,
            lambda _evt, a=attr: self._on_remove_link_generic(a),
        )
        row.Add(remove_btn, 0)
        sizer.Add(row, 0, wx.EXPAND | wx.TOP, pad)
        lst = wx.ListCtrl(box, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        lst.InsertColumn(0, _("ID"))
        lst.InsertColumn(1, _("Title"))
        lst.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
        lst.SetColumnWidth(1, wx.LIST_AUTOSIZE_USEHEADER)
        lst.Bind(
            wx.EVT_SIZE,
            lambda evt, lc=lst: (evt.Skip(), self._autosize_link_columns(lc)),
        )
        lst.Bind(
            wx.EVT_CONTEXT_MENU,
            lambda evt, a=attr: self._on_links_context_menu(a, evt),
        )
        sizer.Add(lst, 1, wx.EXPAND | wx.TOP, pad)
        # Hide the list and the remove button by default.
        lst.Hide()
        sizer.Show(lst, False)
        remove_btn.Hide()
        row.Show(remove_btn, False)
        id_attr = id_name or f"{attr}_id"
        list_attr = list_name or f"{attr}_list"
        setattr(self, id_attr, id_ctrl)
        setattr(self, list_attr, lst)
        setattr(self, f"{attr}_remove", remove_btn)
        setattr(self, attr, [])
        return sizer

    def _lookup_link_metadata(self, rid: str) -> dict[str, Any] | None:
        """Return cached metadata for ``rid`` or load it from storage."""
        rid = rid.strip()
        if not rid:
            return None
        cached = self._link_metadata_cache.get(rid)
        if cached is not None:
            return cached or None
        service = self._service
        if service is None:
            self._link_metadata_cache[rid] = {}
            return None
        try:
            prefix, item_id = parse_rid(rid)
        except ValueError:
            self._link_metadata_cache[rid] = {}
            return None
        try:
            doc = service.get_document(prefix)
            data, _mtime = service.load_item(prefix, item_id)
        except Exception:  # pragma: no cover - filesystem errors
            logger.exception("Failed to load metadata for parent requirement %s", rid)
            self._link_metadata_cache[rid] = {}
            return None
        metadata = {
            "title": str(data.get("title", "")),
            "fingerprint": requirement_fingerprint(data),
            "doc_prefix": doc.prefix,
            "doc_title": doc.title,
        }
        self._link_metadata_cache[rid] = metadata
        return metadata

    def _augment_links_with_metadata(
        self, links: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Enrich serialized ``links`` with cached metadata when available."""
        enriched: list[dict[str, Any]] = []
        for entry in links:
            rid = str(entry.get("rid", "")).strip()
            if not rid:
                continue
            metadata = self._lookup_link_metadata(rid)
            if metadata:
                if metadata.get("title") and not entry.get("title"):
                    entry["title"] = metadata["title"]
                if metadata.get("fingerprint") and not entry.get("fingerprint"):
                    entry["fingerprint"] = metadata["fingerprint"]
                if metadata.get("doc_prefix"):
                    entry["doc_prefix"] = metadata["doc_prefix"]
                if metadata.get("doc_title"):
                    entry["doc_title"] = metadata["doc_title"]
            enriched.append(entry)
        return enriched

    def _format_link_note(self, link: dict[str, Any]) -> str:
        """Return human-readable text for ``link`` entry."""
        rid = str(link.get("rid", "")).strip()
        title = str(link.get("title", "")).strip()
        doc_title = str(link.get("doc_title", "")).strip()
        text = (f"{rid} — {title}" if rid else title) if title else rid
        if doc_title and doc_title not in text:
            suffix = f"({doc_title})"
            text = f"{text} {suffix}" if text else suffix
        return text.strip()

    def _link_widgets(self, attr: str):
        id_attr = f"{attr}_id"
        list_attr = f"{attr}_list"
        return getattr(self, id_attr), getattr(self, list_attr), getattr(self, attr)

    def _refresh_links_visibility(self, attr: str) -> None:
        """Show list and remove button only when links exist."""
        _id_ctrl, list_ctrl, links_list = self._link_widgets(attr)
        remove_btn = getattr(self, f"{attr}_remove", None)
        visible = bool(links_list)
        list_ctrl.Show(visible)
        sizer = list_ctrl.GetContainingSizer()
        if sizer:
            sizer.Show(list_ctrl, visible)
            sizer.Layout()
        if remove_btn:
            remove_btn.Show(visible)
            btn_sizer = remove_btn.GetContainingSizer()
            if btn_sizer:
                btn_sizer.Show(remove_btn, visible)
                btn_sizer.Layout()
        box = list_ctrl.GetParent()
        box.Layout()
        self.Layout()
        self.FitInside()
        if visible:
            self._autosize_link_columns(list_ctrl)

    def _autosize_link_columns(self, list_ctrl: wx.ListCtrl) -> None:
        """Adjust column widths for a two-column link list."""
        list_ctrl.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
        total = list_ctrl.GetClientSize().width
        id_width = list_ctrl.GetColumnWidth(0)
        if total > id_width:
            list_ctrl.SetColumnWidth(1, total - id_width)
        else:
            list_ctrl.SetColumnWidth(1, wx.LIST_AUTOSIZE)

    def _rebuild_links_list(self, attr: str, *, select: int | None = None) -> None:
        """Repopulate ListCtrl for given link attribute."""
        _id_ctrl, list_ctrl, links_list = self._link_widgets(attr)
        if links_list:
            enriched = self._augment_links_with_metadata(list(links_list))
            links_list[:] = enriched
        list_ctrl.DeleteAllItems()
        for link in links_list:
            src_rid = link["rid"]
            idx = list_ctrl.InsertItem(list_ctrl.GetItemCount(), src_rid)
            display = self._format_link_note(link)
            if link.get("suspect"):
                warning = _("Suspect link")
                prefix = f"⚠ {warning}"
                display = f"{prefix} — {display}" if display else prefix
                list_ctrl.SetItemTextColour(idx, wx.RED)
            else:
                list_ctrl.SetItemTextColour(idx, wx.NullColour)
            list_ctrl.SetItem(idx, 1, display)
        if select is not None and 0 <= select < list_ctrl.GetItemCount():
            list_ctrl.Select(select)
            list_ctrl.Focus(select)
            list_ctrl.EnsureVisible(select)

    def set_link_suspect(self, attr: str, index: int, value: bool) -> None:
        """Set suspect flag for a link and refresh list display."""
        _id_ctrl, _list_ctrl, links_list = self._link_widgets(attr)
        if not (0 <= index < len(links_list)):
            return
        new_value = bool(value)
        current = bool(links_list[index].get("suspect", False))
        links_list[index]["suspect"] = new_value
        if current == new_value:
            return
        self._rebuild_links_list(attr, select=index)

    def _on_links_context_menu(self, attr: str, event: wx.ContextMenuEvent) -> None:
        """Handle context menu requests for link lists."""
        _id_ctrl, list_ctrl, links_list = self._link_widgets(attr)
        if not links_list or event.GetEventObject() is not list_ctrl:
            return
        position = event.GetPosition()
        index = list_ctrl.GetFirstSelected()
        if position != wx.DefaultPosition:
            local_pos = list_ctrl.ScreenToClient(position)
            hit, _flags = list_ctrl.HitTest(local_pos)
            if hit != wx.NOT_FOUND:
                list_ctrl.Select(hit)
                list_ctrl.Focus(hit)
                index = hit
        if index == -1 or not (0 <= index < len(links_list)):
            return
        suspect = bool(links_list[index].get("suspect", False))
        menu = wx.Menu()
        label = _("Clear suspect mark") if suspect else _("Mark as suspect")
        item = menu.Append(wx.ID_ANY, label)
        menu.Bind(
            wx.EVT_MENU,
            lambda _evt, a=attr, i=index, value=not suspect: self.set_link_suspect(a, i, value),
            source=item,
        )
        list_ctrl.PopupMenu(menu)
        menu.Destroy()

    # basic operations -------------------------------------------------
    def new_requirement(self) -> None:
        """Reset UI fields to create a new requirement."""
        with self._bulk_update():
            for ctrl in self.fields.values():
                ctrl.ChangeValue("")
            if "revision" in self.fields:
                self.fields["revision"].ChangeValue("1")
            defaults = {
                "type": locale.code_to_label("type", RequirementType.REQUIREMENT.value),
                "status": locale.code_to_label("status", Status.DRAFT.value),
                "priority": locale.code_to_label("priority", Priority.MEDIUM.value),
                "verification": locale.code_to_label(
                    "verification",
                    Verification.NOT_DEFINED.value,
                ),
            }
            for name, choice in self.enums.items():
                choice.SetStringSelection(defaults[name])
            self.attachments = []
            self.links = []
            self.current_path = None
            self.mtime = None
            self.original_id = None
            self.extra.update(
                {
                    "labels": [],
                    "approved_at": None,
                    "notes": "",
                    "doc_prefix": "",
                    "rid": "",
                },
            )
            self.approved_picker.SetValue(wx.DefaultDateTime)
            self.notes_ctrl.ChangeValue("")
            self._refresh_attachments()
            self.links_list.DeleteAllItems()
            self.links_id.ChangeValue("")
            self._refresh_links_visibility("links")
            self._refresh_labels_display()
        self.original_modified_at = ""
        self._auto_resize_all()
        self._on_id_change()
        self._reset_scroll_position()
        self.mark_clean()

    def load(
        self,
        data: Requirement | dict[str, Any],
        *,
        path: str | Path | None = None,
        mtime: float | None = None,
    ) -> None:
        """Populate editor fields from ``data``."""
        if isinstance(data, Requirement):
            self.extra["doc_prefix"] = data.doc_prefix
            self.extra["rid"] = data.rid
            data = data.to_mapping()
        else:
            self.extra["doc_prefix"] = data.get("doc_prefix", "")
            self.extra["rid"] = data.get("rid", "")
        self.original_id = data.get("id")
        with self._bulk_update():
            for name, ctrl in self.fields.items():
                ctrl.ChangeValue(str(data.get(name, "")))
            self.attachments = list(data.get("attachments", []))
            raw_links = data.get("links", [])
            parsed_links: list[dict[str, Any]] = []
            if isinstance(raw_links, list):
                for entry in raw_links:
                    if isinstance(entry, dict):
                        rid = str(entry.get("rid", "")).strip()
                        if not rid:
                            continue
                        link_info: dict[str, Any] = {"rid": rid}
                        fingerprint = entry.get("fingerprint")
                        if isinstance(fingerprint, str) and fingerprint:
                            link_info["fingerprint"] = fingerprint
                        elif fingerprint not in (None, ""):
                            link_info["fingerprint"] = str(fingerprint)
                        else:
                            link_info["fingerprint"] = None
                        link_info["suspect"] = bool(entry.get("suspect", False))
                        if "title" in entry and entry["title"]:
                            link_info["title"] = str(entry["title"])
                        parsed_links.append(link_info)
                    elif isinstance(entry, str):
                        rid = entry.strip()
                        if rid:
                            parsed_links.append({"rid": rid, "fingerprint": None, "suspect": False})
            self.links = self._augment_links_with_metadata(parsed_links)
            self._rebuild_links_list("links")
            self.links_id.ChangeValue("")
            self._refresh_links_visibility("links")
            for name, choice in self.enums.items():
                enum_cls = ENUMS[name]
                default_code = next(iter(enum_cls)).value
                code = data.get(name, default_code)
                choice.SetStringSelection(locale.code_to_label(name, code))
            labels = data.get("labels")
            self.extra.update(
                {
                    "labels": list(labels) if isinstance(labels, list) else [],
                    "approved_at": data.get("approved_at"),
                    "notes": data.get("notes", ""),
                },
            )
            if self.extra.get("approved_at"):
                dt = wx.DateTime()
                dt.ParseISODate(str(self.extra["approved_at"]))
                self.approved_picker.SetValue(
                    dt if dt.IsValid() else wx.DefaultDateTime,
                )
            else:
                self.approved_picker.SetValue(wx.DefaultDateTime)
            self.notes_ctrl.ChangeValue(self.extra.get("notes", ""))
            self._refresh_attachments()
            self.current_path = Path(path) if path else None
            self.mtime = mtime
            self._refresh_labels_display()
        self.original_modified_at = self.fields["modified_at"].GetValue()
        self._auto_resize_all()
        self._on_id_change()
        self._reset_scroll_position()
        self.mark_clean()
        self.set_requirement_selected(True)

    def clone(self, new_id: int) -> None:
        """Copy current requirement into a new one with ``new_id``."""
        with self._bulk_update():
            self.fields["id"].ChangeValue(str(new_id))
            self.fields["modified_at"].ChangeValue("")
            self.current_path = None
            self.mtime = None
            self.original_id = None
            self.links = []
            self.links_list.DeleteAllItems()
            self._refresh_links_visibility("links")
            self.extra["rid"] = ""
            self._refresh_labels_display()
        self.original_modified_at = ""
        self._auto_resize_all()
        self._on_id_change()

    # data helpers -----------------------------------------------------
    def get_data(self) -> Requirement:
        """Collect form data into a :class:`Requirement`."""
        self._sync_attachments_with_statement()
        id_value = self.fields["id"].GetValue().strip()
        if not id_value:
            raise ValueError(_("ID is required"))
        try:
            req_id = int(id_value)
        except ValueError as exc:  # pragma: no cover - error path
            raise ValueError(_("ID must be an integer")) from exc
        if req_id <= 0:
            raise ValueError(_("ID must be positive"))

        data = {
            "id": req_id,
            "title": self.fields["title"].GetValue(),
            "statement": self.fields["statement"].GetValue(),
            "type": locale.label_to_code(
                "type",
                self.enums["type"].GetStringSelection(),
            ),
            "status": locale.label_to_code(
                "status",
                self.enums["status"].GetStringSelection(),
            ),
            "owner": self.fields["owner"].GetValue(),
            "priority": locale.label_to_code(
                "priority",
                self.enums["priority"].GetStringSelection(),
            ),
            "source": self.fields["source"].GetValue(),
            "verification": locale.label_to_code(
                "verification",
                self.enums["verification"].GetStringSelection(),
            ),
            "acceptance": self.fields["acceptance"].GetValue(),
            "conditions": self.fields["conditions"].GetValue(),
            "rationale": self.fields["rationale"].GetValue(),
            "assumptions": self.fields["assumptions"].GetValue(),
            "modified_at": self.fields["modified_at"].GetValue(),
            "labels": list(self.extra.get("labels", [])),
            "attachments": list(self.attachments),
        }
        revision_ctrl = self.fields.get("revision")
        revision_text = revision_ctrl.GetValue().strip() if revision_ctrl else ""
        if revision_text:
            try:
                revision = int(revision_text)
            except (TypeError, ValueError):
                raise ValueError(
                    _("Revision must be a positive integer")
                ) from None
        else:
            revision = 1
        if revision <= 0:
            raise ValueError(_("Revision must be a positive integer"))
        if revision_ctrl:
            revision_ctrl.ChangeValue(str(revision))
        data["revision"] = revision
        if self.links:
            serialized_links: list[dict[str, Any]] = []
            for link in self.links:
                rid = str(link.get("rid", "")).strip()
                if not rid:
                    continue
                entry: dict[str, Any] = {"rid": rid}
                fingerprint = link.get("fingerprint")
                if isinstance(fingerprint, str) and fingerprint:
                    entry["fingerprint"] = fingerprint
                suspect = bool(link.get("suspect", False))
                if suspect:
                    entry["suspect"] = True
                serialized_links.append(entry)
            if serialized_links:
                data["links"] = serialized_links
        dt = self.approved_picker.GetValue()
        approved_at = dt.FormatISODate() if dt.IsValid() else None
        data["approved_at"] = approved_at
        notes = self.notes_ctrl.GetValue()
        data["notes"] = notes
        self.extra["labels"] = data["labels"]
        self.extra["approved_at"] = approved_at
        self.extra["notes"] = notes
        return Requirement.from_mapping(
            data,
            doc_prefix=self.extra.get("doc_prefix", ""),
            rid=self.extra.get("rid", ""),
        )

    # labels helpers ---------------------------------------------------
    def update_labels_list(self, labels: list[LabelDef], allow_freeform: bool = False) -> None:
        """Update available labels, free-form policy and reapply selection."""
        self._label_defs = [LabelDef(lbl.key, lbl.title, lbl.color) for lbl in labels]
        self._labels_allow_freeform = allow_freeform
        current = [
            lbl
            for lbl in self.extra.get("labels", [])
            if allow_freeform or any(label.key == lbl for label in labels)
        ]
        self.extra["labels"] = current
        self._refresh_labels_display()

    def apply_label_selection(self, labels: list[str]) -> None:
        """Apply selected ``labels`` to requirement and refresh display."""
        if self._labels_allow_freeform:
            cleaned: list[str] = []
            for lbl in labels:
                if lbl and lbl not in cleaned:
                    cleaned.append(lbl)
            self.extra["labels"] = cleaned
        else:
            available = {label.key for label in self._label_defs}
            self.extra["labels"] = [lbl for lbl in labels if lbl in available]
        self._refresh_labels_display()

    def _refresh_labels_display(self) -> None:
        if not wx.GetApp():
            return
        sizer = self.labels_panel.GetSizer()
        if sizer:
            sizer.Clear(True)
        labels = self.extra.get("labels", [])
        if not labels:
            placeholder = wx.StaticText(self.labels_panel, label=_("(none)"))
            placeholder.SetForegroundColour(wx.Colour("grey"))
            placeholder.Bind(wx.EVT_LEFT_DOWN, self._on_labels_click)
            sizer.Add(placeholder, 0)
        else:
            for i, name in enumerate(labels):
                lbl_def = next(
                    (
                        label_def
                        for label_def in self._label_defs
                        if label_def.key == name
                    ),
                    None,
                )
                color = label_color(lbl_def) if lbl_def else stable_color(name)
                txt = wx.StaticText(self.labels_panel, label=name)
                txt.SetBackgroundColour(color)
                txt.Bind(wx.EVT_LEFT_DOWN, self._on_labels_click)
                sizer.Add(txt, 0, wx.RIGHT, 2)
                if i < len(labels) - 1:
                    comma = wx.StaticText(self.labels_panel, label=", ")
                    comma.Bind(wx.EVT_LEFT_DOWN, self._on_labels_click)
                    sizer.Add(comma, 0, wx.RIGHT, 2)
        self.labels_panel.Layout()

    def _on_labels_click(self, _event: wx.Event) -> None:
        if not self._label_defs and not self._labels_allow_freeform:
            return
        selected = self.extra.get("labels", [])
        dlg = LabelSelectionDialog(
            self,
            self._label_defs,
            selected,
            allow_freeform=self._labels_allow_freeform,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self.apply_label_selection(dlg.get_selected())
        dlg.Destroy()

    def _refresh_attachments(self) -> None:
        self.attachments_list.Freeze()
        try:
            self.attachments_list.DeleteAllItems()
            for att in self.attachments:
                idx = self.attachments_list.InsertItem(
                    self.attachments_list.GetItemCount(),
                    att.get("path", ""),
                )
                self.attachments_list.SetItem(idx, 1, att.get("note", ""))
        finally:
            self.attachments_list.Thaw()
        self.attachments_list.InvalidateBestSize()
        visible = bool(self.attachments)
        sizer = self.attachments_list.GetContainingSizer()
        if sizer:
            sizer.ShowItems(visible)
            sizer.Layout()
        self.attachments_list.Show(visible)
        self.remove_attachment_btn.Enable(visible)
        self.remove_attachment_btn.Show(visible)
        btn_sizer = self.remove_attachment_btn.GetContainingSizer()
        if btn_sizer:
            btn_sizer.Show(self.remove_attachment_btn, visible)
            btn_sizer.Layout()
        if visible:
            self.attachments_list.SendSizeEvent()
        self.Layout()
        self.FitInside()
        if self._statement_preview and self._is_statement_preview_mode():
            self._update_statement_preview()

    def _on_add_attachment(self, _event: wx.CommandEvent) -> None:
        service = self._service
        prefix = self._effective_prefix()
        if service is None or not prefix:
            wx.MessageBox(
                _("Select a document before adding attachments."),
                _("Error"),
                style=wx.ICON_ERROR,
            )
            return
        dlg = wx.FileDialog(
            self,
            _("Select attachment"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        path = dlg.GetPath()
        dlg.Destroy()
        note = ""
        ndlg = wx.TextEntryDialog(self, _("Note"), "")
        if ndlg.ShowModal() == wx.ID_OK:
            note = ndlg.GetValue()
        ndlg.Destroy()
        try:
            attachment = service.upload_requirement_attachment(
                prefix, Path(path), note=note
            )
        except Exception as exc:  # pragma: no cover - UI error guard
            logger.exception("Failed to add attachment %s", path)
            wx.MessageBox(str(exc), _("Error"), style=wx.ICON_ERROR)
            return
        self.attachments.append(attachment)
        self._refresh_attachments()

    def _on_remove_attachment(self, _event: wx.CommandEvent) -> None:
        idx = self.attachments_list.GetFirstSelected()
        if idx != -1:
            del self.attachments[idx]
            self._refresh_attachments()

    def _create_icon_button(
        self,
        parent: wx.Window,
        *,
        art_ids: tuple[str, ...],
        tooltip: str,
        handler: Callable[[wx.CommandEvent], None],
    ) -> wx.BitmapButton:
        icon_size = wx.Size(dip(parent, 16), dip(parent, 16))
        bitmap = wx.NullBitmap
        for art_id in art_ids:
            candidate = wx.ArtProvider.GetBitmap(art_id, wx.ART_BUTTON, icon_size)
            if candidate.IsOk():
                bitmap = candidate
                break
        if not bitmap.IsOk():
            bitmap = wx.ArtProvider.GetBitmap(wx.ART_MISSING_IMAGE, wx.ART_BUTTON, icon_size)
        button = wx.BitmapButton(
            parent,
            bitmap=bitmap,
            style=wx.BU_EXACTFIT | wx.BORDER_NONE,
        )
        button.SetToolTip(tooltip)
        inherit_background(button, parent)
        button.Bind(wx.EVT_BUTTON, handler)
        return button

    def _on_insert_image(self, _event: wx.CommandEvent) -> None:
        service = self._service
        prefix = self._effective_prefix()
        if service is None or not prefix:
            wx.MessageBox(
                _("Select a document before adding attachments."),
                _("Error"),
                style=wx.ICON_ERROR,
            )
            return
        dlg = wx.FileDialog(
            self,
            _("Select image"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        path = dlg.GetPath()
        dlg.Destroy()
        try:
            attachment = service.upload_requirement_attachment(
                prefix, Path(path), note=""
            )
        except Exception as exc:  # pragma: no cover - UI error guard
            logger.exception("Failed to add attachment %s", path)
            wx.MessageBox(str(exc), _("Error"), style=wx.ICON_ERROR)
            return
        self.attachments.append(attachment)
        self._refresh_attachments()
        alt_text = Path(path).stem or _("Image")
        self._insert_attachment_markdown(attachment["id"], alt_text)

    def _on_insert_table(self, _event: wx.CommandEvent) -> None:
        snippet = _(
            "| Column | Value |\n"
            "| --- | --- |\n"
            "| Item | Description |"
        )
        self._insert_statement_block_snippet(snippet)

    def _on_insert_formula(self, _event: wx.CommandEvent) -> None:
        snippet = "\\(E = mc^2\\)\n\n$$E = mc^2$$"
        self._insert_statement_block_snippet(snippet)

    def _on_insert_heading(self, _event: wx.CommandEvent) -> None:
        snippet = _("# Heading\n")
        self._insert_statement_snippet(snippet)

    def _on_insert_bold(self, _event: wx.CommandEvent) -> None:
        snippet = _("**Bold text**")
        self._insert_statement_snippet(snippet)

    def _on_statement_mode_change(self, _event: wx.CommandEvent) -> None:
        self._set_statement_preview_mode(self._is_statement_preview_mode())

    def _on_statement_text_change(self, event: wx.CommandEvent) -> None:
        if self._suspend_events:
            event.Skip()
            return
        if self._statement_preview and self._is_statement_preview_mode():
            self._update_statement_preview()
        event.Skip()

    def _is_statement_preview_mode(self) -> bool:
        if self._statement_mode is None:
            return False
        return self._statement_mode.GetSelection() == 1

    def _set_statement_preview_mode(self, enabled: bool) -> None:
        preview = self._statement_preview
        statement_ctrl = self.fields.get("statement")
        if preview is None or statement_ctrl is None:
            return
        statement_ctrl.Show(not enabled)
        preview.Show(enabled)
        if enabled:
            self._update_statement_preview()
        self.Layout()
        self.FitInside()

    def _update_statement_preview(self) -> None:
        preview = self._statement_preview
        if preview is None:
            return
        markdown = self._statement_markdown_for_preview()
        preview.SetMarkdown(markdown)

    def _statement_markdown_for_preview(self) -> str:
        statement_ctrl = self.fields.get("statement")
        if statement_ctrl is None:
            return ""
        raw = statement_ctrl.GetValue()
        if not raw:
            return ""
        if not self.attachments:
            return raw
        attachment_map: dict[str, str] = {}
        for attachment in self.attachments:
            if not isinstance(attachment, dict):
                continue
            attachment_id = str(attachment.get("id", "")).strip()
            path = str(attachment.get("path", "")).strip()
            if attachment_id and path:
                attachment_map[attachment_id] = path
        if not attachment_map:
            return raw

        prefix = self._effective_prefix()
        root = self._service.root if self._service is not None else None

        def _replace(match: re.Match[str]) -> str:
            attachment_id = match.group(1)
            path = attachment_map.get(attachment_id)
            if not path:
                return match.group(0)
            candidate = Path(path)
            if not candidate.is_absolute() and root is not None and prefix:
                candidate = Path(root) / prefix / candidate
            if candidate.is_absolute():
                return candidate.resolve().as_uri()
            return match.group(0)

        return self._attachment_link_re.sub(_replace, raw)

    def _insert_attachment_markdown(self, attachment_id: str, alt_text: str) -> None:
        statement_ctrl = self.fields.get("statement")
        if statement_ctrl is None:
            return
        if not attachment_id:
            return
        safe_alt = alt_text.strip() or _("Image")
        snippet = f"![{safe_alt}](attachment:{attachment_id})"
        self._insert_statement_snippet(snippet)

    def _insert_statement_snippet(self, snippet: str) -> None:
        statement_ctrl = self.fields.get("statement")
        if statement_ctrl is None:
            return
        if not snippet:
            return
        statement_ctrl.WriteText(snippet)
        if self._statement_preview and self._is_statement_preview_mode():
            self._update_statement_preview()

    def _insert_statement_block_snippet(self, snippet: str) -> None:
        statement_ctrl = self.fields.get("statement")
        if statement_ctrl is None:
            return
        if not snippet:
            return
        value = statement_ctrl.GetValue() or ""
        start, end = statement_ctrl.GetSelection()
        if start > end:
            start, end = end, start
        before = value[:start]
        after = value[end:]

        def _block_separator_before(text: str) -> str:
            if not text:
                return ""
            if text.endswith("\n\n"):
                return ""
            if text.endswith("\n"):
                return "\n"
            return "\n\n"

        def _block_separator_after(text: str) -> str:
            if not text:
                return ""
            if text.startswith("\n\n"):
                return ""
            if text.startswith("\n"):
                return "\n"
            return "\n\n"

        prefix = _block_separator_before(before)
        suffix = _block_separator_after(after)
        payload = f"{prefix}{snippet}{suffix}"
        statement_ctrl.Replace(start, end, payload)
        statement_ctrl.SetInsertionPoint(start + len(payload))
        if self._statement_preview and self._is_statement_preview_mode():
            self._update_statement_preview()

    def _referenced_attachment_ids(self) -> set[str]:
        statement_ctrl = self.fields.get("statement")
        if statement_ctrl is None:
            return set()
        raw = statement_ctrl.GetValue() or ""
        return {match.group(1) for match in self._attachment_link_re.finditer(raw)}

    def _sync_attachments_with_statement(self) -> None:
        referenced = self._referenced_attachment_ids()
        current_attachments = list(self.attachments)
        removed = [
            att
            for att in current_attachments
            if str(att.get("id", "")).strip() not in referenced
        ]
        if removed:
            proceed = self._prompt_attachment_cleanup(removed)
            if not proceed:
                return
        if not referenced:
            self.attachments = []
        else:
            self.attachments = [
                att
                for att in current_attachments
                if str(att.get("id", "")).strip() in referenced
            ]
        self._refresh_attachments()

    def _prompt_attachment_cleanup(self, removed: list[dict[str, str]]) -> bool:
        service = self._service
        prefix = self._effective_prefix()
        if service is None or not prefix:
            return True
        for attachment in removed:
            path = attachment.get("path", "")
            if not path:
                continue
            file_path = Path(path)
            if not file_path.is_absolute():
                file_path = Path(service.root) / prefix / file_path
            if not file_path.exists():
                continue
            message = _("Delete attachment file?\n{path}").format(path=file_path)
            dlg = wx.MessageDialog(
                self,
                message,
                _("Delete attachment"),
                style=wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION,
            )
            dlg.SetYesNoLabels(_("Delete"), _("Skip"))
            dlg.SetCancelLabel(_("Cancel"))
            result = dlg.ShowModal()
            dlg.Destroy()
            if result == wx.ID_CANCEL:
                return False
            if result != wx.ID_YES:
                continue
            try:
                file_path.unlink()
            except OSError:  # pragma: no cover - filesystem errors
                wx.MessageBox(
                    _("Failed to delete attachment file:\n{path}").format(
                        path=file_path
                    ),
                    _("Error"),
                    style=wx.ICON_ERROR,
                )
        return True

    # generic link handlers -------------------------------------------
    def _on_add_link_generic(self, attr: str) -> None:
        id_ctrl, list_ctrl, links_list = self._link_widgets(attr)
        value = id_ctrl.GetValue().strip().upper()
        if not value:
            return
        try:
            prefix, item_id = parse_rid(value)
        except ValueError:
            wx.MessageBox(_("Invalid requirement ID"), _("Error"), style=wx.ICON_ERROR)
            return
        title = ""
        fingerprint = None
        doc_title = ""
        doc_prefix = ""
        service = self._service
        if service is not None:
            try:
                doc = service.get_document(prefix)
                data, _metadata = service.load_item(prefix, item_id)
            except Exception:  # pragma: no cover - lookup errors
                logger.exception("Failed to load requirement %s", value)
                self._link_metadata_cache[value] = {}
            else:
                title = str(data.get("title", ""))
                fingerprint = requirement_fingerprint(data)
                doc_title = doc.title
                doc_prefix = doc.prefix
                self._link_metadata_cache[value] = {
                    "title": title,
                    "fingerprint": fingerprint,
                    "doc_prefix": doc_prefix,
                    "doc_title": doc_title,
                }
        links_list.append(
            {
                "rid": value,
                "fingerprint": fingerprint,
                "suspect": False,
                "title": title,
                "doc_prefix": doc_prefix,
                "doc_title": doc_title,
            }
        )
        idx = list_ctrl.InsertItem(list_ctrl.GetItemCount(), value)
        list_ctrl.SetItem(idx, 1, self._format_link_note(links_list[-1]))
        id_ctrl.ChangeValue("")
        self._refresh_links_visibility(attr)

    def _on_remove_link_generic(self, attr: str) -> None:
        _id_ctrl, list_ctrl, links_list = self._link_widgets(attr)
        idx = (
            list_ctrl.GetFirstSelected()
            if hasattr(list_ctrl, "GetFirstSelected")
            else getattr(list_ctrl, "GetSelection", lambda: -1)()
        )
        if idx != -1:
            del links_list[idx]
            if hasattr(list_ctrl, "DeleteItem"):
                list_ctrl.DeleteItem(idx)
            else:
                list_ctrl.Delete(idx)
        self._refresh_links_visibility(attr)

    def _on_id_change(self, _event: wx.CommandEvent | None = None) -> None:
        if self._suspend_events:
            return
        ctrl = self.fields["id"]
        ctrl.SetBackgroundColour(wx.NullColour)
        self._id_conflict = False
        if self._service is None or self._effective_prefix() is None:
            ctrl.Refresh()
            return
        value = ctrl.GetValue().strip()
        if not value:
            ctrl.Refresh()
            return
        try:
            req_id = int(value)
        except (TypeError, ValueError):
            ctrl.SetBackgroundColour(wx.Colour(255, 200, 200))
            ctrl.Refresh()
            return
        if req_id <= 0:
            ctrl.SetBackgroundColour(wx.Colour(255, 200, 200))
            ctrl.Refresh()
            return
        if self._has_id_conflict(req_id):
            ctrl.SetBackgroundColour(wx.Colour(255, 200, 200))
            self._id_conflict = True
        else:
            ctrl.SetBackgroundColour(wx.NullColour)
        ctrl.Refresh()

    def _on_save_button(self, _evt: wx.Event) -> None:
        if self._on_save_callback:
            self._on_save_callback()

    def _on_cancel_button(self, _evt: wx.Event) -> None:
        self.discard_changes()

    def save(self, prefix: str) -> Path:
        """Persist editor contents within document ``prefix`` and return path."""
        service = self._require_service()
        try:
            doc = service.get_document(prefix)
        except Exception as exc:
            raise RuntimeError(f"Unknown document prefix: {prefix}") from exc

        req = self.get_data()
        self._document = doc
        if self._has_id_conflict(req.id, prefix=prefix, doc=doc):
            rid = rid_for(doc, req.id)
            message = _("Requirement {rid} already exists").format(rid=rid)
            wx.MessageBox(message, _("Error"), style=wx.ICON_ERROR)
            self._id_conflict = True
            ctrl = self.fields["id"]
            ctrl.SetBackgroundColour(wx.Colour(255, 200, 200))
            ctrl.Refresh()
            raise RequirementIDCollisionError(doc.prefix, req.id, rid=rid)
        self._id_conflict = False
        mod = (
            req.modified_at
            if req.modified_at and req.modified_at != self.original_modified_at
            else None
        )
        req.modified_at = normalize_timestamp(mod) if mod else local_now_str()
        data = req.to_mapping()
        path = service.save_requirement_payload(prefix, data)
        self.fields["modified_at"].ChangeValue(req.modified_at)
        self.original_modified_at = req.modified_at
        self.current_path = path
        self.mtime = path.stat().st_mtime
        self._doc_prefix = prefix
        self.extra["doc_prefix"] = prefix
        self._refresh_known_ids(prefix=prefix, doc=doc)
        self.original_id = req.id
        self._known_ids = None
        self._on_id_change()
        self.mark_clean()
        return path

    def _snapshot_state(self) -> dict[str, Any]:
        """Return immutable snapshot of current editor contents."""
        fields_state = {
            name: ctrl.GetValue()
            for name, ctrl in self.fields.items()
        }
        enums_state = {
            name: locale.label_to_code(name, choice.GetStringSelection())
            for name, choice in self.enums.items()
        }
        attachments_state = [dict(att) for att in self.attachments]
        links_state = [dict(link) for link in self.links]
        dt = self.approved_picker.GetValue()
        approved_at = dt.FormatISODate() if dt.IsValid() else None
        snapshot = {
            "fields": fields_state,
            "enums": enums_state,
            "attachments": attachments_state,
            "links": links_state,
            "labels": list(self.extra.get("labels", [])),
            "approved_at": approved_at,
            "notes": self.notes_ctrl.GetValue(),
        }
        return snapshot

    def mark_clean(self) -> None:
        """Store current state as the latest saved baseline."""
        self._saved_state = self._snapshot_state()

    def has_meaningful_content(self) -> bool:
        """Return True when editor contains user-entered content."""
        defaults = {
            "type": locale.code_to_label("type", RequirementType.REQUIREMENT.value),
            "status": locale.code_to_label("status", Status.DRAFT.value),
            "priority": locale.code_to_label("priority", Priority.MEDIUM.value),
            "verification": locale.code_to_label(
                "verification", Verification.NOT_DEFINED.value
            ),
        }
        for name, ctrl in self.fields.items():
            value = ctrl.GetValue().strip()
            if not value:
                continue
            if name == "revision" and value == "1":
                continue
            return True
        for name, choice in self.enums.items():
            if choice.GetStringSelection() != defaults[name]:
                return True
        if self.attachments or self.links:
            return True
        if self.extra.get("labels"):
            return True
        if self.extra.get("notes"):
            return True
        dt = self.approved_picker.GetValue()
        if dt.IsValid():
            return True
        return False

    def is_dirty(self) -> bool:
        """Return True when editor content differs from saved baseline."""
        if self._saved_state is None:
            return False
        return self._snapshot_state() != self._saved_state

    def discard_changes(self) -> None:
        """Revert editor fields to the latest stored version."""
        handled = False
        if self._on_discard_callback:
            handled = bool(self._on_discard_callback())
        if handled:
            return

        state = self._saved_state
        if state is None:
            return

        with self._bulk_update():
            fields_state = state.get("fields", {})
            for name, ctrl in self.fields.items():
                value = fields_state.get(name, "")
                ctrl.ChangeValue(str(value))

            enums_state = state.get("enums", {})
            for name, choice in self.enums.items():
                code = enums_state.get(name)
                if code is None:
                    if choice.GetCount():
                        choice.SetSelection(0)
                    continue
                label = locale.code_to_label(name, code)
                if not choice.SetStringSelection(label) and choice.GetCount():
                    choice.SetSelection(0)

            self.attachments = [dict(att) for att in state.get("attachments", [])]
            self._refresh_attachments()

            if hasattr(self, "links"):
                links_state = [dict(link) for link in state.get("links", [])]
                self.links = self._augment_links_with_metadata(links_state)
                try:
                    id_ctrl, _list_ctrl, _links_list = self._link_widgets("links")
                except AttributeError:
                    id_ctrl = None
                else:
                    self._rebuild_links_list("links")
                    if id_ctrl:
                        id_ctrl.ChangeValue("")
                    self._refresh_links_visibility("links")

            labels_state = list(state.get("labels", []))
            self.extra["labels"] = labels_state
            self._refresh_labels_display()

            approved_at = state.get("approved_at")
            self.extra["approved_at"] = approved_at
            if approved_at:
                dt = wx.DateTime()
                dt.ParseISODate(str(approved_at))
                self.approved_picker.SetValue(dt if dt.IsValid() else wx.DefaultDateTime)
            else:
                self.approved_picker.SetValue(wx.DefaultDateTime)

            notes = state.get("notes", "")
            self.extra["notes"] = notes
            self.notes_ctrl.ChangeValue(notes)

        self._auto_resize_all()
        self._on_id_change()
        self.original_modified_at = self.fields["modified_at"].GetValue()
        self.mark_clean()

    def add_attachment(self, attachment_id: str, path: str, note: str = "") -> None:
        """Append attachment with ``attachment_id``, ``path`` and optional ``note``."""
        self.attachments.append({"id": attachment_id, "path": path, "note": note})
        if hasattr(self, "attachments_list"):
            idx = self.attachments_list.InsertItem(
                self.attachments_list.GetItemCount(),
                path,
            )
            self.attachments_list.SetItem(idx, 1, note)
