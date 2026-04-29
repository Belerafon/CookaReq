"""Requirement editor panel."""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass
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
from ..core.document_store.documents import is_ancestor
from ..core.model import (
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
)
from ..util.time import local_now_str, normalize_timestamp
from ..i18n import _
from . import locale
from .enums import ENUMS
from .helpers import AutoHeightListCtrl, HelpStaticBox, dip, inherit_background, make_help_button
from .label_selection_dialog import LabelSelectionDialog
from .list_panel import ListPanel
from .resources import load_editor_config
from .widgets.markdown_view import MarkdownContent

logger = logging.getLogger(__name__)


@dataclass
class _TextHistoryState:
    entries: list[str]
    index: int = 0
    applying: bool = False


class VerificationMethodsDialog(wx.Dialog):
    """Dialog for selecting multiple verification methods."""

    def __init__(self, parent: wx.Window, selected_codes: list[str]):
        super().__init__(parent, title=locale.field_label("verification"))
        self.SetMinSize((dip(self, 320), -1))

        choices = [locale.code_to_label("verification", method.value) for method in Verification]
        checklist = wx.CheckListBox(self, choices=choices)
        self._checklist = checklist
        selected = set(selected_codes)
        for idx, method in enumerate(Verification):
            checklist.Check(idx, method.value in selected)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(checklist, 1, wx.EXPAND | wx.ALL, dip(self, 10))
        root.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, dip(self, 10))
        self.SetSizerAndFit(root)

    def selected_codes(self) -> list[str]:
        """Return selected verification method codes in enum order."""
        selected: list[str] = []
        for idx, method in enumerate(Verification):
            if self._checklist.IsChecked(idx):
                selected.append(method.value)
        return selected or [Verification.NOT_DEFINED.value]


class RequirementLinkPickerDialog(wx.Dialog):
    """Resizable multi-select dialog for choosing linked requirement RIDs."""

    _CONFIG_PREFIX = "/editor/link_picker"

    def __init__(
        self,
        parent: wx.Window,
        candidates: list[dict[str, str]],
        selected_rids: set[str] | None = None,
        current_prefix: str | None = None,
        list_columns: list[str] | None = None,
    ):
        super().__init__(
            parent,
            title=_("Select linked requirements"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX,
        )
        self.SetMinSize((dip(self, 920), dip(self, 620)))
        self._all_candidates = candidates
        self._visible_candidates: list[dict[str, str]] = []
        self._selected_rids = {rid.strip().upper() for rid in (selected_rids or set()) if rid.strip()}
        self._selected_visible_rids: set[str] = set()
        self._current_prefix = (current_prefix or "").strip().upper()
        self._source_options: list[tuple[str, str]] = []
        self._source_filter_key = ""
        self._list_columns = list_columns or ["labels", "id", "source", "status"]

        root = wx.BoxSizer(wx.VERTICAL)
        search_row = wx.BoxSizer(wx.HORIZONTAL)
        source_label = wx.StaticText(self, label=_("List"))
        self._source_choice = wx.Choice(self)
        self._source_choice.Bind(wx.EVT_CHOICE, self._on_source_change)
        search_row.Add(source_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, dip(self, 8))
        search_row.Add(self._source_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, dip(self, 12))
        search_row.Add((0, 0), 1, wx.EXPAND)
        root.Add(search_row, 0, wx.ALL | wx.EXPAND, dip(self, 10))

        self._list_panel = ListPanel(self)
        self._list_panel.document_summary.Hide()
        self._list_panel.set_columns(self._list_columns)
        self._list_panel.filter_btn.Bind(wx.EVT_BUTTON, self._on_filter_button)
        self._list_panel.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_item_selected)
        self._list_panel.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._on_item_deselected)
        self._list_panel.list.Bind(wx.EVT_MOTION, self._on_list_motion)
        self._list_panel.list.Bind(wx.EVT_LEAVE_WINDOW, self._on_list_leave)
        root.Add(self._list_panel, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, dip(self, 10))

        buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if buttons is not None:
            root.Add(buttons, 0, wx.ALL | wx.EXPAND, dip(self, 10))
        self.SetSizer(root)

        self._build_source_options()
        self._apply_filter()
        self._restore_layout()
        self.Bind(wx.EVT_CLOSE, self._on_close)

    @property
    def selected_rids(self) -> list[str]:
        hidden = sorted(rid for rid in self._selected_rids if rid not in {row["rid"] for row in self._all_candidates})
        return sorted(self._selected_visible_rids) + hidden

    def _read_int(self, config: wx.ConfigBase, key: str, default: int) -> int:
        try:
            value = config.ReadInt(f"{self._CONFIG_PREFIX}/{key}")
        except Exception:
            return default
        return value if isinstance(value, int) else default

    def _write_int(self, config: wx.ConfigBase, key: str, value: int) -> None:
        config.WriteInt(f"{self._CONFIG_PREFIX}/{key}", int(value))

    def _restore_layout(self) -> None:
        config = wx.Config.Get()
        if config is None:
            self.SetSize((dip(self, 1020), dip(self, 720)))
            self.CentreOnParent()
            return
        width = self._read_int(config, "w", dip(self, 1020))
        height = self._read_int(config, "h", dip(self, 720))
        width = max(dip(self, 920), min(width, 2400))
        height = max(dip(self, 620), min(height, 1600))
        self.SetSize((width, height))
        x = self._read_int(config, "x", -1)
        y = self._read_int(config, "y", -1)
        if x != -1 and y != -1:
            self.SetPosition((x, y))
            rect = self.GetRect()
            if not any(wx.Display(i).GetGeometry().Intersects(rect) for i in range(wx.Display.GetCount())):
                self.CentreOnParent()
        else:
            self.CentreOnParent()

    def _save_layout(self) -> None:
        config = wx.Config.Get()
        if config is None:
            return
        width, height = self.GetSize()
        x, y = self.GetPosition()
        self._write_int(config, "w", width)
        self._write_int(config, "h", height)
        self._write_int(config, "x", x)
        self._write_int(config, "y", y)
        config.Flush()

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._save_layout()
        event.Skip()

    def Destroy(self) -> bool:  # pragma: no cover - GUI side effect
        self._save_layout()
        return super().Destroy()

    def _on_source_change(self, _event: wx.CommandEvent) -> None:
        index = self._source_choice.GetSelection()
        if 0 <= index < len(self._source_options):
            self._source_filter_key = self._source_options[index][0]
        self._apply_filter()

    def _on_list_motion(self, event: wx.MouseEvent) -> None:
        index, _flags = self._list_panel.list.HitTest(event.GetPosition())
        self._apply_list_tooltip(index)
        event.Skip()

    def _on_list_leave(self, event: wx.MouseEvent) -> None:
        self._apply_list_tooltip(wx.NOT_FOUND)
        event.Skip()

    def _apply_list_tooltip(self, index: int) -> None:
        if not (0 <= index < len(self._visible_candidates)):
            self._list_panel.list.SetToolTip(None)
            return
        row = self._visible_candidates[index]
        statement = str(row.get("statement", "")).strip()
        title = str(row.get("title", "")).strip()
        tooltip = statement or title
        self._list_panel.list.SetToolTip(tooltip or None)

    def _build_source_options(self) -> None:
        docs: dict[str, tuple[str, int]] = {}
        for row in self._all_candidates:
            prefix = str(row.get("prefix", "")).strip().upper()
            if not prefix:
                continue
            title = str(row.get("document", "")).strip()
            distance_raw = row.get("distance")
            try:
                distance = int(distance_raw)
            except (TypeError, ValueError):
                distance = 0
            existing = docs.get(prefix)
            if existing is None or distance > existing[1]:
                docs[prefix] = (title, distance)
        ordered_prefixes = sorted(
            docs.keys(),
            key=lambda item: (-docs[item][1], item),
        )
        options: list[tuple[str, str]] = []
        for prefix in ordered_prefixes:
            title, _distance = docs[prefix]
            label = f"{prefix}: {title}" if title else prefix
            options.append((prefix, label))
        self._source_options = options
        self._source_choice.Clear()
        for _key, label in options:
            self._source_choice.Append(label)
        default_key = next((key for key, _label in options), "")
        self._source_filter_key = default_key
        selected = next((index for index, (key, _label) in enumerate(options) if key == default_key), 0)
        if options:
            self._source_choice.SetSelection(selected)

    def _matches_source_filter(self, row: dict[str, str], key: str) -> bool:
        prefix = str(row.get("prefix", "")).strip().upper()
        if not key:
            return True
        return prefix == key

    def _on_filter_button(self, _event: wx.CommandEvent) -> None:
        for req in self._list_panel.model.get_visible():
            rid = str(getattr(req, "rid", "")).strip().upper()
            if rid:
                self._selected_visible_rids.add(rid)

    def _on_item_selected(self, event: wx.ListEvent) -> None:
        index = event.GetIndex()
        visible = self._list_panel.model.get_visible()
        if 0 <= index < len(visible):
            rid = str(getattr(visible[index], "rid", "")).strip().upper()
            if rid:
                self._selected_visible_rids.add(rid)
        event.Skip()

    def _on_item_deselected(self, event: wx.ListEvent) -> None:
        index = event.GetIndex()
        visible = self._list_panel.model.get_visible()
        if 0 <= index < len(visible):
            rid = str(getattr(visible[index], "rid", "")).strip().upper()
            if rid:
                self._selected_visible_rids.discard(rid)
        event.Skip()

    def _apply_filter(self) -> None:
        filtered_by_source = [
            row for row in self._all_candidates if self._matches_source_filter(row, self._source_filter_key)
        ]
        self._visible_candidates = list(filtered_by_source)
        requirements = []
        for idx, row in enumerate(self._visible_candidates, start=1):
            labels = row.get("labels")
            if not isinstance(labels, list):
                labels = []
            requirements.append(
                Requirement.from_mapping(
                    {
                        "id": idx,
                        "title": str(row.get("title", "")),
                        "statement": str(row.get("statement", "")),
                        "status": str(row.get("status", Status.DRAFT.value)),
                        "type": str(row.get("type", RequirementType.REQUIREMENT.value)),
                        "priority": str(row.get("priority", Priority.MEDIUM.value)),
                        "owner": str(row.get("owner", "")),
                        "source": str(row.get("source", "")),
                        "labels": labels,
                        "verification": row.get("verification", Verification.NOT_DEFINED.value),
                    },
                    doc_prefix=str(row.get("prefix", "")),
                    rid=row["rid"],
                )
            )
        self._list_panel.set_requirements(requirements)
        self._restore_selection()

    def _restore_selection(self) -> None:
        selected = self._selected_visible_rids | self._selected_rids
        visible = self._list_panel.model.get_visible()
        for idx, req in enumerate(visible):
            rid = str(getattr(req, "rid", "")).strip().upper()
            self._list_panel.list.Select(idx, rid in selected)


class EditorPanel(wx.Panel):
    """Panel for creating and editing requirements."""

    def __init__(
        self,
        parent: wx.Window,
        on_save: Callable[[], None] | None = None,
        on_discard: Callable[[], bool] | None = None,
        *,
        detached_mode: bool = False,
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
        self._has_persisted_unsaved_changes = False
        self._statement_mode: wx.Choice | None = None
        self._statement_preview: MarkdownContent | None = None
        self._insert_image_btn: wx.Button | None = None
        self._insert_table_btn: wx.Button | None = None
        self._insert_formula_btn: wx.Button | None = None
        self._insert_heading_btn: wx.Button | None = None
        self._insert_bold_btn: wx.Button | None = None
        self._context_docs_list: AutoHeightListCtrl | None = None
        self._label_defs: list[LabelDef] = []
        self._labels_allow_freeform = False
        self._verification_methods_panel: wx.Panel | None = None
        self._selected_verification_codes: list[str] = [Verification.NOT_DEFINED.value]
        self._requirement_selected = True
        self._text_history_limit = 10
        self._text_histories: dict[wx.TextCtrl, _TextHistoryState] = {}
        self._defer_autosize_layout = False
        self._id_display_link: wx.adv.HyperlinkCtrl | None = None
        self._detached_mode = bool(detached_mode)

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
            label_text = labels[spec.name]
            if spec.name == "id":
                label_text = _("Requirement RID")
            label = wx.StaticText(content, label=label_text)
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
                    tooltip=_(r"Insert formula (inline: \(...\), block: $$...$$)"),
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
                if spec.name == "id":
                    rid_link = wx.adv.HyperlinkCtrl(content, label="—", url="#")
                    rid_link.Bind(wx.adv.EVT_HYPERLINK, self._on_rid_link_clicked)
                    row.Add(rid_link, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
                    self._id_display_link = rid_link
                    ctrl.Hide()
                else:
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
            self._install_text_history(ctrl)
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
                self._install_text_history(ctrl)
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
        self._install_text_history(self.notes_ctrl)
        container.Add(self.notes_ctrl, 0, wx.EXPAND | wx.TOP, border)
        content_sizer.Add(container, 0, wx.EXPAND | wx.TOP, border)

        source_spec = text_specs["source"]
        source_row = wx.BoxSizer(wx.VERTICAL)
        source_label_row = wx.BoxSizer(wx.HORIZONTAL)
        source_label = wx.StaticText(content, label=labels[source_spec.name])
        source_help_btn = make_help_button(content, self._help_texts[source_spec.name])
        source_label_row.Add(source_label, 0, wx.ALIGN_CENTER_VERTICAL)
        source_label_row.Add(source_help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        source_row.Add(source_label_row, 0, wx.TOP, border)
        source_ctrl = wx.TextCtrl(content, style=wx.TE_MULTILINE)
        self._bind_autosize(source_ctrl)
        self.fields[source_spec.name] = source_ctrl
        self._install_text_history(source_ctrl)
        source_row.Add(source_ctrl, 0, wx.EXPAND | wx.TOP, border)
        content_sizer.Add(source_row, 0, wx.EXPAND | wx.TOP, border)
        links_sizer = self._create_links_section(
            locale.field_label("links"),
            "links",
            help_key="links",
        )
        content_sizer.Add(links_sizer, 0, wx.EXPAND | wx.TOP, border)

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
        self.attachments_list.Bind(
            wx.EVT_SIZE,
            lambda evt: (evt.Skip(), self._autosize_attachment_columns()),
        )
        attachment_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.add_attachment_btn = wx.Button(a_box, label=_("Add"))
        self.remove_attachment_btn = wx.Button(a_box, label=_("Remove"))
        self.add_attachment_btn.Bind(wx.EVT_BUTTON, self._on_add_attachment)
        self.remove_attachment_btn.Bind(wx.EVT_BUTTON, self._on_remove_attachment)
        btn_row.Add(self.add_attachment_btn, 0)
        btn_row.Add(self.remove_attachment_btn, 0, wx.LEFT, 5)
        attachment_row.Add(self.attachments_list, 1, wx.EXPAND | wx.RIGHT, border)
        attachment_row.Add(btn_row, 0, wx.ALIGN_CENTER_VERTICAL)
        a_sizer.Add(attachment_row, 0, wx.EXPAND | wx.TOP, border)
        content_sizer.Add(a_sizer, 0, wx.EXPAND | wx.TOP, border)

        # context docs section -------------------------------------------
        c_sizer = HelpStaticBox(
            content,
            locale.field_label("context_docs"),
            self._help_texts["context_docs"],
        )
        c_box = c_sizer.GetStaticBox()
        self.context_docs_list = AutoHeightListCtrl(
            c_box,
            style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.BORDER_SUNKEN | wx.LC_SINGLE_SEL,
        )
        self.context_docs_list.InsertColumn(0, "")
        self.context_docs_list.Bind(
            wx.EVT_SIZE,
            lambda evt: (evt.Skip(), self._autosize_context_docs_columns()),
        )
        self._context_docs_list = self.context_docs_list
        context_row = wx.BoxSizer(wx.HORIZONTAL)
        context_btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.add_context_doc_btn = wx.Button(c_box, label=_("Add"))
        self.remove_context_doc_btn = wx.Button(c_box, label=_("Remove"))
        self.add_context_doc_btn.Bind(wx.EVT_BUTTON, self._on_add_context_doc)
        self.remove_context_doc_btn.Bind(wx.EVT_BUTTON, self._on_remove_context_doc)
        context_btn_row.Add(self.add_context_doc_btn, 0)
        context_btn_row.Add(self.remove_context_doc_btn, 0, wx.LEFT, 5)
        context_row.Add(self.context_docs_list, 1, wx.EXPAND | wx.RIGHT, border)
        context_row.Add(context_btn_row, 0, wx.ALIGN_CENTER_VERTICAL)
        c_sizer.Add(context_row, 0, wx.EXPAND | wx.TOP, border)
        content_sizer.Add(c_sizer, 0, wx.EXPAND | wx.TOP, border)

        for name in ("acceptance", "assumptions"):
            add_text_field(name)

        for name in ("modified_at", "owner", "revision"):
            add_grid_field(name)

        for name in ("type", "priority"):
            add_grid_field(name)

        verification_sizer = self._create_verification_methods_section(content)
        content_sizer.Add(verification_sizer, 0, wx.EXPAND | wx.TOP, border)

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
        if self._detached_mode:
            outer_sizer = wx.BoxSizer(wx.VERTICAL)
            outer_sizer.Add(root_sizer, 1, wx.EXPAND | wx.ALL, dip(self, 8))
            self.SetSizer(outer_sizer)
        else:
            self.SetSizer(root_sizer)

        self.attachments: list[dict[str, str]] = []
        self.context_docs: list[str] = []
        self.extra: dict[str, Any] = {
            "labels": [],
            "approved_at": None,
            "notes": "",
        }
        self.current_path: Path | None = None
        self.mtime: float | None = None
        self._refresh_labels_display()
        self._refresh_verification_methods_display()
        self._refresh_attachments()
        self._refresh_context_docs()
        self._bind_action_state_tracking()
        self._update_rid_display_label()
        self.mark_clean()

    def set_requirement_selected(self, selected: bool) -> None:
        """Toggle edit controls based on whether a requirement is selected."""
        self._requirement_selected = bool(selected)
        self._content_panel.Enable(self._requirement_selected)
        self._update_action_buttons()

    def set_persisted_unsaved_changes(self, value: bool) -> None:
        """Track whether loaded data differs from persisted storage."""
        self._has_persisted_unsaved_changes = bool(value)
        self._update_action_buttons()

    def _bind_action_state_tracking(self) -> None:
        """Bind change events that should refresh Save/Cancel enabled state."""
        for ctrl in self.fields.values():
            ctrl.Bind(wx.EVT_TEXT, self._on_editor_content_changed)
        for choice in self.enums.values():
            choice.Bind(wx.EVT_CHOICE, self._on_editor_content_changed)
        self.notes_ctrl.Bind(wx.EVT_TEXT, self._on_editor_content_changed)
        self.approved_picker.Bind(wx.adv.EVT_DATE_CHANGED, self._on_editor_content_changed)

    def _on_editor_content_changed(self, event: wx.Event) -> None:
        if not self._suspend_events:
            self._update_action_buttons()
        event.Skip()

    def _update_action_buttons(self) -> None:
        can_edit = bool(self._requirement_selected)
        has_changes = can_edit and (self.is_dirty() or self._has_persisted_unsaved_changes)
        self.save_btn.Enable(has_changes)
        self.cancel_btn.Enable(has_changes)

    def FitInside(self) -> None:  # noqa: N802 - wxWidgets API casing
        """Recalculate the scrollable area of the editor form."""
        self._content_panel.FitInside()
        self._content_panel.Layout()
        super().Layout()

    def Layout(self) -> bool:  # noqa: N802 - wxWidgets API casing
        """Layout both the scrollable content and the outer panel."""
        self._content_panel.Layout()
        return super().Layout()


    def _create_verification_methods_section(self, content: wx.Window) -> wx.StaticBoxSizer:
        """Create compact verification methods selector section."""
        box_sizer = HelpStaticBox(
            content,
            locale.field_label("verification"),
            self._help_texts["verification"],
        )
        box = box_sizer.GetStaticBox()
        row = wx.BoxSizer(wx.HORIZONTAL)
        self._verification_methods_panel = wx.Panel(box)
        self._verification_methods_panel.SetBackgroundColour(box.GetBackgroundColour())
        self._verification_methods_panel.SetSizer(wx.BoxSizer(wx.HORIZONTAL))
        line_height = self.GetCharHeight() + 6
        self._verification_methods_panel.SetMinSize((-1, line_height))
        self._verification_methods_panel.Bind(wx.EVT_LEFT_DOWN, self._on_verification_methods_click)
        row.Add(self._verification_methods_panel, 1, wx.EXPAND | wx.RIGHT, 5)
        edit_btn = wx.Button(box, label=_("Edit..."))
        edit_btn.Bind(wx.EVT_BUTTON, self._on_verification_methods_click)
        row.Add(edit_btn, 0)
        box_sizer.Add(row, 0, wx.EXPAND | wx.TOP, dip(self, 5))
        return box_sizer

    def _selected_verification_methods(self) -> list[str]:
        """Return selected verification method codes in enum order."""
        return list(self._selected_verification_codes) or [Verification.NOT_DEFINED.value]

    def _set_verification_methods(self, codes: list[str] | tuple[str, ...]) -> None:
        """Apply selected verification methods and refresh compact display."""
        normalized: list[str] = []
        for code in codes:
            value = str(code).strip()
            if not value:
                continue
            try:
                method = Verification(value).value
            except ValueError:
                continue
            if method not in normalized:
                normalized.append(method)
        if not normalized:
            normalized = [Verification.NOT_DEFINED.value]
        self._selected_verification_codes = normalized
        self._refresh_verification_methods_display()
        self._update_action_buttons()

    def _refresh_verification_methods_display(self) -> None:
        panel = self._verification_methods_panel
        if panel is None or not wx.GetApp():
            return
        sizer = panel.GetSizer()
        if sizer:
            sizer.Clear(True)
        codes = self._selected_verification_methods()
        for i, code in enumerate(codes):
            label = locale.code_to_label("verification", code)
            txt = wx.StaticText(panel, label=label)
            txt.SetBackgroundColour(stable_color(code))
            txt.Bind(wx.EVT_LEFT_DOWN, self._on_verification_methods_click)
            sizer.Add(txt, 0, wx.RIGHT, 2)
            if i < len(codes) - 1:
                comma = wx.StaticText(panel, label=", ")
                comma.Bind(wx.EVT_LEFT_DOWN, self._on_verification_methods_click)
                sizer.Add(comma, 0, wx.RIGHT, 2)
        panel.Layout()

    def _on_verification_methods_click(self, _event: wx.Event) -> None:
        dlg = VerificationMethodsDialog(self, self._selected_verification_methods())
        if dlg.ShowModal() == wx.ID_OK:
            self._set_verification_methods(dlg.selected_codes())
        dlg.Destroy()

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
        self._update_rid_display_label()
        self._on_id_change()

    def set_document(self, prefix: str | None) -> None:
        """Select active document ``prefix`` for ID validation."""
        self._doc_prefix = prefix
        self.extra["doc_prefix"] = prefix or ""
        self._document = None
        self._known_ids = None
        self._id_conflict = False
        self._link_metadata_cache = {}
        self._update_rid_display_label()
        self._on_id_change()

    def _format_rid_display(self) -> str:
        prefix = self._effective_prefix()
        value = self.fields["id"].GetValue().strip()
        if prefix and value:
            return f"{prefix}-{value}"
        if prefix:
            return f"{prefix}-…"
        if value:
            return value
        return "—"

    def _update_rid_display_label(self) -> None:
        link = self._id_display_link
        if link is None:
            return
        link.SetLabel(self._format_rid_display())
        link.SetURL("#")
        link.Layout()

    def _on_rid_link_clicked(self, _event: wx.adv.HyperlinkEvent) -> None:
        prefix = self._effective_prefix() or _("(no prefix)")
        current_value = self.fields["id"].GetValue().strip()
        while True:
            dialog = wx.TextEntryDialog(
                self,
                _(
                    "Changing RID manually is not recommended because it can break traceability links.\n\n"
                    "Enter requirement number:"
                ),
                _("Edit RID: {prefix}").format(prefix=prefix),
                value=current_value,
            )
            result = dialog.ShowModal()
            value = dialog.GetValue().strip()
            dialog.Destroy()
            if result != wx.ID_OK:
                return
            if not value:
                wx.MessageBox(
                    _("Requirement number is required"),
                    _("Error"),
                    style=wx.ICON_ERROR,
                )
                continue
            try:
                req_id = int(value)
            except ValueError:
                wx.MessageBox(
                    _("Requirement number must be an integer"),
                    _("Error"),
                    style=wx.ICON_ERROR,
                )
                current_value = value
                continue
            if req_id <= 0:
                wx.MessageBox(
                    _("Requirement number must be positive"),
                    _("Error"),
                    style=wx.ICON_ERROR,
                )
                current_value = value
                continue
            self.fields["id"].ChangeValue(str(req_id))
            self._on_id_change()
            return

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

    def _install_text_history(self, ctrl: wx.TextCtrl) -> None:
        if ctrl in self._text_histories:
            return
        self._text_histories[ctrl] = _TextHistoryState(entries=[ctrl.GetValue()])
        ctrl.Bind(wx.EVT_TEXT, lambda evt, c=ctrl: self._on_text_history_change(c, evt))
        ctrl.Bind(wx.EVT_CHAR_HOOK, lambda evt, c=ctrl: self._on_text_history_key(c, evt))

    def _on_text_history_change(self, ctrl: wx.TextCtrl, event: wx.CommandEvent) -> None:
        state = self._text_histories.get(ctrl)
        if state is None or state.applying or self._suspend_events:
            event.Skip()
            return
        value = ctrl.GetValue()
        if value == state.entries[state.index]:
            event.Skip()
            return
        if state.index < len(state.entries) - 1:
            state.entries = state.entries[: state.index + 1]
        state.entries.append(value)
        max_entries = self._text_history_limit + 1
        if len(state.entries) > max_entries:
            overflow = len(state.entries) - max_entries
            state.entries = state.entries[overflow:]
            state.index = max(state.index - overflow, 0)
        state.index = len(state.entries) - 1
        event.Skip()

    def _on_text_history_key(self, ctrl: wx.TextCtrl, event: wx.KeyEvent) -> None:
        if event.GetModifiers() == wx.MOD_CONTROL and event.GetKeyCode() in (ord("Z"), ord("z")) and self._undo_text_history(ctrl):
            return
        if (
            event.GetModifiers() == (wx.MOD_CONTROL | wx.MOD_SHIFT)
            and event.GetKeyCode() in (ord("Z"), ord("z"))
        ) and self._redo_text_history(ctrl):
            return
        if event.GetModifiers() == wx.MOD_CONTROL and event.GetKeyCode() in (ord("Y"), ord("y")) and self._redo_text_history(ctrl):
            return
        event.Skip()

    def _undo_text_history(self, ctrl: wx.TextCtrl) -> bool:
        state = self._text_histories.get(ctrl)
        if state is None or state.index <= 0:
            return False
        state.index -= 1
        self._apply_text_history(ctrl, state)
        return True

    def _redo_text_history(self, ctrl: wx.TextCtrl) -> bool:
        state = self._text_histories.get(ctrl)
        if state is None or state.index >= len(state.entries) - 1:
            return False
        state.index += 1
        self._apply_text_history(ctrl, state)
        return True

    def _apply_text_history(self, ctrl: wx.TextCtrl, state: _TextHistoryState) -> None:
        state.applying = True
        try:
            ctrl.ChangeValue(state.entries[state.index])
            ctrl.SetInsertionPointEnd()
        finally:
            state.applying = False

    def _reset_text_histories(self) -> None:
        for ctrl, state in self._text_histories.items():
            state.entries = [ctrl.GetValue()]
            state.index = 0
            state.applying = False

    def _auto_resize_text(self, ctrl: wx.TextCtrl) -> None:
        if self._suspend_events:
            return
        height = self._compute_text_height(ctrl)
        if ctrl.GetMinSize().height != height:
            ctrl.SetMinSize((-1, height))
            ctrl.SetSize((-1, height))
            if self._defer_autosize_layout:
                return
            self.FitInside()
            self.Layout()

    def _compute_text_height(self, ctrl: wx.TextCtrl) -> int:
        lines = max(ctrl.GetNumberOfLines(), 1)
        line_height = ctrl.GetCharHeight()
        border = ctrl.GetWindowBorderSize().height * 2
        padding = 4
        return line_height * (lines + 1) + border + padding

    def _auto_resize_all(self) -> None:
        changed = False
        self._defer_autosize_layout = True
        try:
            for ctrl in self._autosize_fields:
                height = self._compute_text_height(ctrl)
                if ctrl.GetMinSize().height == height:
                    continue
                ctrl.SetMinSize((-1, height))
                ctrl.SetSize((-1, height))
                changed = True
        finally:
            self._defer_autosize_layout = False
        if changed:
            self.FitInside()
            self.Layout()

    @contextmanager
    def _bulk_update(self):
        """Temporarily disable events and redraws during bulk updates."""
        self._suspend_events = True
        self.Freeze()
        self._content_panel.Freeze()
        try:
            yield
        finally:
            self._content_panel.Thaw()
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
        links_list = AutoHeightListCtrl(
            box,
            style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.BORDER_SUNKEN | wx.LC_SINGLE_SEL,
        )
        links_list.InsertColumn(0, _("RID"))
        links_list.InsertColumn(1, _("Title"))
        links_list.Bind(
            wx.EVT_SIZE,
            lambda evt, control=links_list: (evt.Skip(), self._autosize_links_columns(control)),
        )
        links_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda evt, a=attr: self._on_links_click(a, evt))
        links_list.Bind(wx.EVT_LEFT_DCLICK, lambda evt, a=attr: self._on_links_click(a, evt))
        links_list.Bind(
            wx.EVT_LIST_ITEM_RIGHT_CLICK,
            lambda evt, a=attr, control=links_list: self._on_links_item_context_menu(a, control, evt),
        )
        links_list.Bind(wx.EVT_MOTION, lambda evt, a=attr, control=links_list: self._on_links_list_motion(a, control, evt))
        links_list.Bind(wx.EVT_LEAVE_WINDOW, lambda evt, control=links_list: self._clear_list_tooltip(control, evt))
        links_list.Show(False)
        links_list.SetMinSize(wx.Size(-1, 0))
        row.Add(links_list, 1, wx.EXPAND | wx.RIGHT, 5)
        add_btn = wx.Button(box, label=_("Add"))
        add_btn.Bind(wx.EVT_BUTTON, lambda _evt, a=attr: self._on_add_link_generic(a))
        row.Add(add_btn, 0)
        sizer.Add(row, 0, wx.EXPAND | wx.TOP, pad)
        id_attr = id_name or f"{attr}_id"
        list_attr = list_name or f"{attr}_list"
        setattr(self, id_attr, None)
        setattr(self, list_attr, links_list)
        setattr(self, f"{attr}_panel", links_list)
        setattr(self, f"{attr}_add", add_btn)
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
            "statement": str(data.get("statement", "")),
            "revision": data.get("revision"),
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
                if metadata.get("statement") and not entry.get("statement"):
                    entry["statement"] = metadata["statement"]
                if metadata.get("revision") and not entry.get("revision"):
                    entry["revision"] = metadata["revision"]
                if metadata.get("doc_prefix"):
                    entry["doc_prefix"] = metadata["doc_prefix"]
                if metadata.get("doc_title"):
                    entry["doc_title"] = metadata["doc_title"]
            enriched.append(entry)
        return enriched

    def _link_widgets(self, attr: str):
        id_attr = f"{attr}_id"
        list_attr = f"{attr}_list"
        return getattr(self, id_attr), getattr(self, list_attr), getattr(self, attr)

    def _refresh_links_visibility(self, attr: str) -> None:
        """Refresh compact comma-separated links display."""
        self._rebuild_links_list(attr)

    def _collect_link_picker_candidates(self, attr: str) -> list[dict[str, str]]:
        """Return selectable requirements for link picker."""
        service = self._service
        if service is None:
            return []
        try:
            requirements = service.load_requirements()
            docs_map = service.load_documents()
            docs = {doc.prefix: doc.title for doc in docs_map.values()}
        except Exception:  # pragma: no cover - service errors
            logger.exception("Failed to collect link picker candidates")
            return []
        _id_ctrl, _list_ctrl, _links_list = self._link_widgets(attr)
        current_rid = str(self.extra.get("rid", "")).strip()
        current_prefix = (self._effective_prefix() or "").strip().upper()

        def _ancestor_distance(child: str, ancestor: str) -> int:
            if not child or not ancestor:
                return 0
            if child == ancestor:
                return 0
            distance = 0
            current = docs_map.get(child)
            while current and current.parent:
                distance += 1
                parent = current.parent
                if parent == ancestor:
                    return distance
                current = docs_map.get(parent)
            return 0

        rows: list[dict[str, str]] = []
        for requirement in requirements:
            rid = str(getattr(requirement, "rid", "") or "").strip()
            if not rid or rid == current_rid:
                continue
            prefix = str(getattr(requirement, "doc_prefix", "") or "").strip()
            if current_prefix and prefix and not is_ancestor(current_prefix, prefix, docs_map):
                continue
            rows.append(
                {
                    "rid": rid,
                    "title": str(getattr(requirement, "title", "") or "").strip(),
                    "statement": str(getattr(requirement, "statement", "") or "").strip(),
                    "status": str(getattr(requirement, "status", Status.DRAFT.value)),
                    "type": str(getattr(requirement, "type", RequirementType.REQUIREMENT.value)),
                    "priority": str(getattr(requirement, "priority", Priority.MEDIUM.value)),
                    "owner": str(getattr(requirement, "owner", "") or "").strip(),
                    "source": str(getattr(requirement, "source", "") or "").strip(),
                    "labels": list(getattr(requirement, "labels", []) or []),
                    "verification": str(
                        getattr(requirement, "verification", Verification.NOT_DEFINED.value)
                        or Verification.NOT_DEFINED.value
                    ),
                    "document": docs.get(prefix, prefix),
                    "prefix": prefix.upper(),
                    "distance": _ancestor_distance(current_prefix, prefix.upper()),
                }
            )
        rows.sort(key=lambda row: (row["rid"], row["title"]))
        return rows

    def _resolve_link_picker_columns(self) -> list[str]:
        """Reuse configured main-list columns in the links picker."""
        config = getattr(self, "config", None)
        if config is None:
            top_level = wx.GetTopLevelParent(self)
            config = getattr(top_level, "config", None) if top_level is not None else None
        if config is None:
            return ["labels", "id", "source", "status"]
        try:
            columns = list(config.get_columns())
        except Exception:
            logger.exception("Failed to read columns from config for link picker")
            return ["labels", "id", "source", "status"]
        return columns or ["labels", "id", "source", "status"]

    def _show_link_picker(self, attr: str, selected_rids: set[str] | None = None) -> list[str]:
        """Open picker dialog and return selected RIDs."""
        dialog = RequirementLinkPickerDialog(
            self,
            self._collect_link_picker_candidates(attr),
            selected_rids=selected_rids,
            current_prefix=self._effective_prefix(),
            list_columns=self._resolve_link_picker_columns(),
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return []
            return dialog.selected_rids
        finally:
            dialog.Destroy()

    def _on_links_click(self, attr: str, _event: wx.Event) -> None:
        self._open_links_picker(attr)

    def _validate_link_target(self, rid: str, *, attr: str) -> tuple[bool, bool]:
        """Validate link target and return (is_valid, mark_suspect)."""
        rid_value = rid.strip().upper()
        if not rid_value:
            return False, False
        try:
            prefix, item_id = parse_rid(rid_value)
        except ValueError:
            return False, False
        _id_ctrl, _list_ctrl, links_list = self._link_widgets(attr)
        if any(str(entry.get("rid", "")).strip().upper() == rid_value for entry in links_list):
            return False, False
        service = self._service
        own_prefix = self._effective_prefix()
        if service is None or not own_prefix:
            return True, False
        try:
            docs = service.load_documents()
        except Exception:
            logger.exception("Failed to load documents for link validation")
            return True, False
        if prefix not in docs:
            return False, False
        if not is_ancestor(own_prefix, prefix, docs):
            return False, False
        try:
            service.load_item(prefix, item_id)
        except Exception:
            return True, True
        return True, False

    def _open_links_picker(self, attr: str) -> None:
        """Open multi-select picker and apply the chosen links."""
        _id_ctrl, _display_panel, links_list = self._link_widgets(attr)
        selected = {str(entry.get("rid", "")).strip().upper() for entry in links_list if str(entry.get("rid", "")).strip()}
        picked = self._show_link_picker(attr, selected_rids=selected)
        if not picked and selected:
            return
        existing_by_rid = {
            str(entry.get("rid", "")).strip().upper(): dict(entry)
            for entry in links_list
            if str(entry.get("rid", "")).strip()
        }
        updated: list[dict[str, Any]] = []
        for rid in picked:
            canonical = rid.strip().upper()
            if not canonical:
                continue
            existing = existing_by_rid.get(canonical)
            if existing is not None:
                updated.append(existing)
                continue
            is_valid, mark_suspect = self._validate_link_target(canonical, attr=attr)
            if not is_valid:
                continue
            metadata = self._lookup_link_metadata(canonical) or {}
            updated.append(
                {
                    "rid": canonical,
                    "revision": metadata.get("revision"),
                    "suspect": mark_suspect,
                    "title": metadata.get("title", ""),
                    "doc_prefix": metadata.get("doc_prefix", ""),
                    "doc_title": metadata.get("doc_title", ""),
                }
            )
        links_list[:] = updated
        self._refresh_links_visibility(attr)

    def _autosize_attachment_columns(self) -> None:
        """Resize attachment columns so file path stays readable."""
        list_ctrl = self.attachments_list
        if not list_ctrl or not list_ctrl.IsShown():
            return
        total = list_ctrl.GetClientSize().width
        if total <= 0:
            return
        list_ctrl.SetColumnWidth(1, wx.LIST_AUTOSIZE_USEHEADER)
        note_width = list_ctrl.GetColumnWidth(1)
        min_file_width = dip(self, 220)
        if total > note_width + min_file_width:
            list_ctrl.SetColumnWidth(0, total - note_width)
        else:
            list_ctrl.SetColumnWidth(0, wx.LIST_AUTOSIZE)
            file_width = list_ctrl.GetColumnWidth(0)
            if file_width + note_width < total:
                list_ctrl.SetColumnWidth(0, total - note_width)

    def _autosize_context_docs_columns(self) -> None:
        """Stretch context path column to the available list width."""
        list_ctrl = self._context_docs_list
        if list_ctrl is None or not list_ctrl.IsShown():
            return
        total = list_ctrl.GetClientSize().width
        if total > 0:
            list_ctrl.SetColumnWidth(0, total)

    def _autosize_links_columns(self, list_ctrl: wx.ListCtrl) -> None:
        """Keep RID compact and allocate the rest of the width to the title."""
        if not list_ctrl or not list_ctrl.IsShown():
            return
        total = list_ctrl.GetClientSize().width
        if total <= 0:
            return
        list_ctrl.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
        rid_width = list_ctrl.GetColumnWidth(0)
        min_title_width = dip(self, 200)
        available_title = max(total - rid_width, 0)
        if available_title >= min_title_width:
            list_ctrl.SetColumnWidth(1, available_title)
        else:
            list_ctrl.SetColumnWidth(1, wx.LIST_AUTOSIZE_USEHEADER)
            title_width = list_ctrl.GetColumnWidth(1)
            if rid_width + title_width < total:
                list_ctrl.SetColumnWidth(1, total - rid_width)

    def _apply_compact_list_height(self, list_ctrl: wx.ListCtrl, item_count: int) -> None:
        """Set list height to match the amount of visible data."""
        if item_count <= 0:
            list_ctrl.SetMinSize(wx.Size(-1, 0))
            return
        row_height = list_ctrl.GetCharHeight() + dip(self, 8)
        header_height = list_ctrl.GetCharHeight() + dip(self, 6)
        vertical_padding = dip(self, 6)
        target_height = header_height + row_height * item_count + vertical_padding
        list_ctrl.SetMinSize(wx.Size(-1, target_height))

    def _apply_links_list_height(self, list_ctrl: wx.ListCtrl, item_count: int) -> None:
        """Keep links table visible and grow it with each added item."""
        visible_rows = max(int(item_count), 1)
        row_height = list_ctrl.GetCharHeight() + dip(self, 8)
        header_height = list_ctrl.GetCharHeight() + dip(self, 6)
        vertical_padding = dip(self, 6)
        target_height = header_height + row_height * visible_rows + vertical_padding
        list_ctrl.SetMinSize(wx.Size(-1, target_height))

    def _on_links_list_motion(self, attr: str, list_ctrl: wx.ListCtrl, event: wx.MouseEvent) -> None:
        hit = list_ctrl.HitTest(event.GetPosition())
        index = hit[0] if isinstance(hit, tuple) else hit
        try:
            item_index = int(index)
        except (TypeError, ValueError):
            item_index = wx.NOT_FOUND
        _id_ctrl, _list_ctrl, links_list = self._link_widgets(attr)
        if 0 <= item_index < len(links_list):
            statement = str(links_list[item_index].get("statement", "")).strip()
            list_ctrl.SetToolTip(statement or None)
        else:
            list_ctrl.SetToolTip(None)
        event.Skip()

    def _clear_list_tooltip(self, list_ctrl: wx.ListCtrl, event: wx.MouseEvent) -> None:
        list_ctrl.SetToolTip(None)
        event.Skip()

    def _on_links_item_context_menu(self, attr: str, list_ctrl: wx.ListCtrl, event: wx.ListEvent) -> None:
        row = event.GetIndex()
        if row < 0:
            return
        menu = wx.Menu()
        remove_item = menu.Append(wx.ID_ANY, _("Remove linked requirement"))
        self.Bind(
            wx.EVT_MENU,
            lambda _evt, a=attr, index=row: self._remove_link_by_index(a, index),
            remove_item,
        )
        self.PopupMenu(menu)
        menu.Destroy()

    def _remove_link_by_index(self, attr: str, index: int) -> None:
        _id_ctrl, _list_ctrl, links_list = self._link_widgets(attr)
        if not (0 <= index < len(links_list)):
            return
        del links_list[index]
        self._refresh_links_visibility(attr)

    def _rebuild_links_list(self, attr: str, *, select: int | None = None) -> None:
        """Render links as a two-column table (RID + title)."""
        _id_ctrl, list_ctrl, links_list = self._link_widgets(attr)
        if not isinstance(list_ctrl, wx.ListCtrl):
            return
        if links_list:
            links_list[:] = self._augment_links_with_metadata(list(links_list))
        list_ctrl.Freeze()
        try:
            list_ctrl.DeleteAllItems()
            for index, link in enumerate(links_list):
                rid = str(link.get("rid", "")).strip()
                if not rid:
                    continue
                rid_label = rid
                if link.get("suspect"):
                    rid_label = f"⚠ {rid_label}"
                title = str(link.get("title", "")).strip()
                row = list_ctrl.InsertItem(list_ctrl.GetItemCount(), rid_label)
                list_ctrl.SetItem(row, 1, title)
        finally:
            list_ctrl.Thaw()
        list_ctrl.InvalidateBestSize()
        has_rows = list_ctrl.GetItemCount() > 0
        self._apply_links_list_height(list_ctrl, list_ctrl.GetItemCount())
        self._autosize_links_columns(list_ctrl)
        container = list_ctrl.GetContainingSizer()
        if container is not None:
            container.Show(list_ctrl, has_rows)
        list_ctrl.Show(has_rows)
        if not has_rows:
            list_ctrl.SetToolTip(None)
            list_ctrl.SetMinSize(wx.Size(-1, 0))
        if select is not None and 0 <= select < list_ctrl.GetItemCount():
            list_ctrl.Select(select)
        self.Layout()
        self.FitInside()
        self._update_action_buttons()

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
            }
            for name, choice in self.enums.items():
                choice.SetStringSelection(defaults[name])
            self._set_verification_methods([Verification.NOT_DEFINED.value])
            self.attachments = []
            self.context_docs = []
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
            self._refresh_context_docs()
            self._refresh_links_visibility("links")
            self._refresh_labels_display()
        self.original_modified_at = ""
        self._auto_resize_all()
        self._update_rid_display_label()
        self._on_id_change()
        self._reset_scroll_position()
        self._reset_text_histories()
        self.mark_clean()
        self.set_persisted_unsaved_changes(False)

    def load(
        self,
        data: Requirement | dict[str, Any],
        *,
        path: str | Path | None = None,
        mtime: float | None = None,
        persisted_unsaved: bool = False,
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
            raw_context_docs = data.get("context_docs", [])
            if isinstance(raw_context_docs, list):
                self.context_docs = [str(path).strip() for path in raw_context_docs if str(path).strip()]
            else:
                self.context_docs = []
            raw_links = data.get("links", [])
            parsed_links: list[dict[str, Any]] = []
            if isinstance(raw_links, list):
                for entry in raw_links:
                    if isinstance(entry, dict):
                        rid = str(entry.get("rid", "")).strip()
                        if not rid:
                            continue
                        link_info: dict[str, Any] = {"rid": rid}
                        revision_raw = entry.get("revision")
                        if revision_raw in (None, ""):
                            link_info["revision"] = None
                        else:
                            try:
                                revision_value = int(revision_raw)
                            except (TypeError, ValueError):
                                revision_value = None
                            link_info["revision"] = revision_value if revision_value and revision_value > 0 else None
                        link_info["suspect"] = bool(entry.get("suspect", False))
                        if "title" in entry and entry["title"]:
                            link_info["title"] = str(entry["title"])
                        parsed_links.append(link_info)
                    elif isinstance(entry, str):
                        rid = entry.strip()
                        if rid:
                            parsed_links.append({"rid": rid, "revision": None, "suspect": False})
            self.links = self._augment_links_with_metadata(parsed_links)
            self._rebuild_links_list("links")
            self._refresh_links_visibility("links")
            for name, choice in self.enums.items():
                enum_cls = ENUMS[name]
                default_code = next(iter(enum_cls)).value
                code = data.get(name, default_code)
                choice.SetStringSelection(locale.code_to_label(name, code))
            raw_methods = data.get("verification_methods")
            methods: list[str]
            if isinstance(raw_methods, list):
                methods = [str(item) for item in raw_methods]
            else:
                methods = [str(data.get("verification", Verification.NOT_DEFINED.value))]
            self._set_verification_methods(methods)
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
            self._refresh_context_docs()
            self.current_path = Path(path) if path else None
            self.mtime = mtime
            self._refresh_labels_display()
        self.original_modified_at = self.fields["modified_at"].GetValue()
        self._auto_resize_all()
        self._update_rid_display_label()
        self._on_id_change()
        self._reset_scroll_position()
        self._reset_text_histories()
        self.mark_clean()
        self.set_persisted_unsaved_changes(persisted_unsaved)
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
            self._refresh_links_visibility("links")
            self.extra["rid"] = ""
            self._refresh_labels_display()
        self.original_modified_at = ""
        self._auto_resize_all()
        self._update_rid_display_label()
        self._on_id_change()
        self._reset_text_histories()
        self.set_persisted_unsaved_changes(False)

    # data helpers -----------------------------------------------------
    def get_data(self) -> Requirement:
        """Collect form data into a :class:`Requirement`."""
        self._sync_attachments_with_statement()
        id_value = self.fields["id"].GetValue().strip()
        if not id_value:
            raise ValueError(_("Requirement number is required"))
        try:
            req_id = int(id_value)
        except ValueError as exc:  # pragma: no cover - error path
            raise ValueError(_("Requirement number must be an integer")) from exc
        if req_id <= 0:
            raise ValueError(_("Requirement number must be positive"))

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
            "verification_methods": self._selected_verification_methods(),
            "acceptance": self.fields["acceptance"].GetValue(),
            "conditions": self.fields["conditions"].GetValue(),
            "rationale": self.fields["rationale"].GetValue(),
            "assumptions": self.fields["assumptions"].GetValue(),
            "modified_at": self.fields["modified_at"].GetValue(),
            "labels": list(self.extra.get("labels", [])),
            "attachments": list(self.attachments),
            "context_docs": list(self.context_docs),
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
                revision_raw = link.get("revision")
                if revision_raw not in (None, ""):
                    try:
                        revision = int(revision_raw)
                    except (TypeError, ValueError):
                        revision = None
                    if revision is not None and revision > 0:
                        entry["revision"] = revision
                suspect = bool(link.get("suspect", False))
                if suspect:
                    entry["suspect"] = True
                serialized_links.append(entry)
            if serialized_links:
                data["links"] = serialized_links
        dt = self.approved_picker.GetValue()
        approved_at = dt.FormatISODate() if dt.IsValid() else None
        data["approved_at"] = approved_at
        data["verification"] = data["verification_methods"][0]
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
        self._update_action_buttons()

    def _on_labels_click(self, _event: wx.Event) -> None:
        if not self._label_defs and not self._labels_allow_freeform:
            return
        selected = self.extra.get("labels", [])
        inherited_defs = [LabelDef(lbl.key, lbl.title, lbl.color) for lbl in self._label_defs]
        local_sources: dict[str, str] = {}
        inherited_sources: dict[str, str] = {}
        prefix = str(self._doc_prefix or self.extra.get("doc_prefix", "")).strip()
        service = self._service
        if service and prefix:
            try:
                defs, _ = service.collect_label_defs(prefix, include_inherited=True)
            except Exception:
                defs = []
            if defs:
                inherited_defs = [LabelDef(lbl.key, lbl.title, lbl.color) for lbl in defs]
            try:
                details = service.describe_label_definitions(prefix)
            except Exception:
                details = {}
            for entry in details.get("labels", []) if isinstance(details, dict) else []:
                if not isinstance(entry, dict):
                    continue
                key = str(entry.get("key", "")).strip()
                source = str(entry.get("defined_in", "")).strip()
                if not key:
                    continue
                if source:
                    inherited_sources[key] = source
                if bool(entry.get("editable", False)) and source:
                    local_sources[key] = source
        if prefix:
            for label in self._label_defs:
                local_sources.setdefault(label.key, prefix)

        inherited_known = {lbl.key for lbl in inherited_defs}
        for name in selected:
            if not isinstance(name, str) or not name.strip():
                continue
            key = name.strip()
            if key in inherited_known:
                continue
            inherited_known.add(key)
            inherited_defs.append(LabelDef(key, key, stable_color(key)))
            inherited_sources.setdefault(key, "")
            local_sources.setdefault(key, prefix)

        dlg = LabelSelectionDialog(
            self,
            self._label_defs,
            selected,
            allow_freeform=self._labels_allow_freeform,
            inherited_labels=inherited_defs,
            label_sources=local_sources,
            inherited_label_sources=inherited_sources,
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
        self._apply_compact_list_height(self.attachments_list, len(self.attachments))
        visible = bool(self.attachments)
        sizer = self.attachments_list.GetContainingSizer()
        if sizer:
            sizer.Show(self.attachments_list, visible)
            parent = self.attachments_list.GetParent()
            if parent:
                parent.Layout()
        self.attachments_list.Show(visible)
        self.remove_attachment_btn.Enable(visible)
        self.remove_attachment_btn.Show(visible)
        btn_sizer = self.remove_attachment_btn.GetContainingSizer()
        if btn_sizer:
            btn_sizer.Show(self.remove_attachment_btn, visible)
            btn_sizer.Layout()
        if visible:
            self._autosize_attachment_columns()
            self.attachments_list.SendSizeEvent()
        self.Layout()
        self.FitInside()
        if self._statement_preview and self._is_statement_preview_mode():
            self._update_statement_preview()
        self._update_action_buttons()

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
        snippet = r"\(\sqrt{a^2 + b^2} = c\)\n\n$$\frac{-b \pm \sqrt{b^2 - 4ac}}{2a}$$"
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
        self._open_links_picker(attr)

    def _on_id_change(self, _event: wx.CommandEvent | None = None) -> None:
        if self._suspend_events:
            return
        ctrl = self.fields["id"]
        ctrl.SetBackgroundColour(wx.NullColour)
        display_link = self._id_display_link
        if display_link is not None:
            display_link.SetForegroundColour(wx.NullColour)
        self._id_conflict = False
        self._update_rid_display_label()
        if self._service is None or self._effective_prefix() is None:
            ctrl.Refresh()
            if display_link is not None:
                display_link.Refresh()
            return
        value = ctrl.GetValue().strip()
        if not value:
            ctrl.Refresh()
            if display_link is not None:
                display_link.Refresh()
            return
        try:
            req_id = int(value)
        except (TypeError, ValueError):
            ctrl.SetBackgroundColour(wx.Colour(255, 200, 200))
            if display_link is not None:
                display_link.SetForegroundColour(wx.Colour(170, 0, 0))
            ctrl.Refresh()
            if display_link is not None:
                display_link.Refresh()
            return
        if req_id <= 0:
            ctrl.SetBackgroundColour(wx.Colour(255, 200, 200))
            if display_link is not None:
                display_link.SetForegroundColour(wx.Colour(170, 0, 0))
            ctrl.Refresh()
            if display_link is not None:
                display_link.Refresh()
            return
        if self._has_id_conflict(req_id):
            ctrl.SetBackgroundColour(wx.Colour(255, 200, 200))
            self._id_conflict = True
            if display_link is not None:
                display_link.SetForegroundColour(wx.Colour(170, 0, 0))
        else:
            ctrl.SetBackgroundColour(wx.NullColour)
            if display_link is not None:
                display_link.SetForegroundColour(wx.NullColour)
        ctrl.Refresh()
        if display_link is not None:
            display_link.Refresh()

    def _on_save_button(self, _evt: wx.Event) -> None:
        if self._on_save_callback:
            self._on_save_callback()

    def _on_cancel_button(self, _evt: wx.Event) -> None:
        self.discard_changes()

    def save(self, prefix: str) -> Requirement:
        """Persist editor contents within document ``prefix`` and return saved requirement."""
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
        saved_payload, _mtime = service.load_item(prefix, req.id)
        saved_req = Requirement.from_mapping(saved_payload)
        saved_req.doc_prefix = prefix
        with self._bulk_update():
            self.fields["modified_at"].ChangeValue(saved_req.modified_at)
            if "revision" in self.fields:
                self.fields["revision"].ChangeValue(str(saved_req.revision))
        self.original_modified_at = saved_req.modified_at
        self.current_path = path
        self.mtime = path.stat().st_mtime
        self._doc_prefix = prefix
        self.extra["doc_prefix"] = prefix
        self._update_rid_display_label()
        self._refresh_known_ids(prefix=prefix, doc=doc)
        self.original_id = req.id
        self._known_ids = None
        self._on_id_change()
        self.mark_clean()
        self.set_persisted_unsaved_changes(False)
        return saved_req

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
        context_docs_state = list(self.context_docs)
        links_state = [dict(link) for link in self.links]
        dt = self.approved_picker.GetValue()
        approved_at = dt.FormatISODate() if dt.IsValid() else None
        snapshot = {
            "fields": fields_state,
            "enums": enums_state,
            "verification_methods": self._selected_verification_methods(),
            "attachments": attachments_state,
            "context_docs": context_docs_state,
            "links": links_state,
            "labels": list(self.extra.get("labels", [])),
            "approved_at": approved_at,
            "notes": self.notes_ctrl.GetValue(),
        }
        return snapshot

    def mark_clean(self) -> None:
        """Store current state as the latest saved baseline."""
        self._saved_state = self._snapshot_state()
        self._update_action_buttons()

    def has_meaningful_content(self) -> bool:
        """Return True when editor contains user-entered content."""
        defaults = {
            "type": locale.code_to_label("type", RequirementType.REQUIREMENT.value),
            "status": locale.code_to_label("status", Status.DRAFT.value),
            "priority": locale.code_to_label("priority", Priority.MEDIUM.value),
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
        if self._selected_verification_methods() != [Verification.NOT_DEFINED.value]:
            return True
        if self.attachments or self.links or self.context_docs:
            return True
        if self.extra.get("labels"):
            return True
        if self.extra.get("notes"):
            return True
        dt = self.approved_picker.GetValue()
        return bool(dt.IsValid())

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
            verification_methods = state.get("verification_methods", [Verification.NOT_DEFINED.value])
            if isinstance(verification_methods, list):
                self._set_verification_methods([str(value) for value in verification_methods])
            else:
                self._set_verification_methods([Verification.NOT_DEFINED.value])

            self.attachments = [dict(att) for att in state.get("attachments", [])]
            self._refresh_attachments()
            self.context_docs = [
                str(path).strip()
                for path in state.get("context_docs", [])
                if str(path).strip()
            ]
            self._refresh_context_docs()

            if hasattr(self, "links"):
                links_state = [dict(link) for link in state.get("links", [])]
                self.links = self._augment_links_with_metadata(links_state)
                try:
                    id_ctrl, _list_ctrl, _links_list = self._link_widgets("links")
                except AttributeError:
                    id_ctrl = None
                else:
                    self._rebuild_links_list("links")
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
        self._reset_text_histories()
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

    def _refresh_context_docs(self) -> None:
        list_ctrl = self._context_docs_list
        if list_ctrl is None:
            return
        list_ctrl.Freeze()
        try:
            list_ctrl.DeleteAllItems()
            for rel_path in self.context_docs:
                list_ctrl.InsertItem(list_ctrl.GetItemCount(), rel_path)
        finally:
            list_ctrl.Thaw()
        list_ctrl.InvalidateBestSize()
        self._apply_compact_list_height(list_ctrl, len(self.context_docs))
        visible = bool(self.context_docs)
        sizer = list_ctrl.GetContainingSizer()
        if sizer is not None:
            sizer.Show(list_ctrl, visible)
            parent = list_ctrl.GetParent()
            if parent:
                parent.Layout()
        list_ctrl.Show(visible)
        if visible:
            self._autosize_context_docs_columns()
            list_ctrl.SendSizeEvent()
        if hasattr(self, "_content_panel") and self._content_panel:
            self._content_panel.FitInside()
        self._update_action_buttons()

    def _on_add_context_doc(self, _event: wx.Event) -> None:
        prefix = self._effective_prefix()
        service = self._service
        if service is None or not prefix:
            wx.MessageBox(
                _("Select a document before adding context docs."),
                _("Context docs"),
                style=wx.OK | wx.ICON_INFORMATION,
            )
            return
        root_dir = service.root / prefix
        if not root_dir.exists():
            wx.MessageBox(
                _("Document folder does not exist: {path}").format(path=root_dir),
                _("Error"),
                style=wx.OK | wx.ICON_ERROR,
            )
            return
        with wx.FileDialog(
            self,
            _("Select context Markdown file"),
            defaultDir=str(root_dir),
            wildcard=_("Markdown files (*.md)|*.md"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            selected = Path(dlg.GetPath()).resolve()
        try:
            rel_path = selected.relative_to(root_dir.resolve())
        except ValueError:
            wx.MessageBox(
                _("Selected file must be inside the current document folder."),
                _("Error"),
                style=wx.OK | wx.ICON_ERROR,
            )
            return
        rel_posix = rel_path.as_posix()
        if rel_posix not in self.context_docs:
            self.context_docs.append(rel_posix)
            self._refresh_context_docs()

    def _on_remove_context_doc(self, _event: wx.Event) -> None:
        idx = self.context_docs_list.GetFirstSelected()
        if idx >= 0:
            del self.context_docs[idx]
            self._refresh_context_docs()
