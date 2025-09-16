"""Requirement editor panel."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

import wx
import wx.adv
from wx.lib.scrolledpanel import ScrolledPanel

from ..core.document_store import (
    Document,
    LabelDef,
    RequirementIDCollisionError,
    label_color,
    list_item_ids,
    save_item,
    stable_color,
    parse_rid,
    rid_for,
    load_document,
    load_item,
)
from ..core.model import (
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
    requirement_fingerprint,
    requirement_from_dict,
    requirement_to_dict,
)
from ..util.time import local_now_str, normalize_timestamp
from ..i18n import _
from . import locale
from .enums import ENUMS
from .helpers import AutoHeightListCtrl, HelpStaticBox, make_help_button
from .label_selection_dialog import LabelSelectionDialog
from .resources import load_editor_config

logger = logging.getLogger(__name__)


class EditorPanel(ScrolledPanel):
    """Panel for creating and editing requirements."""

    def __init__(
        self,
        parent: wx.Window,
        on_save: Callable[[], None] | None = None,
    ):
        """Initialize requirement editor widgets."""
        super().__init__(parent)
        self.fields: dict[str, wx.TextCtrl] = {}
        self.enums: dict[str, wx.Choice] = {}
        self._autosize_fields: list[wx.TextCtrl] = []
        self._suspend_events = False
        self.original_modified_at = ""
        self._on_save_callback = on_save
        self.directory: Path | None = None
        self.original_id: int | None = None
        self._document: Document | None = None
        self._known_ids: set[int] | None = None
        self._id_conflict = False
        self._saved_state: dict[str, Any] | None = None

        config = load_editor_config()
        labels = {name: locale.field_label(name) for name in config.field_names}
        self._help_texts = config.localized_help()

        sizer = wx.BoxSizer(wx.VERTICAL)

        for spec in config.text_fields:
            label = wx.StaticText(self, label=labels[spec.name])
            help_btn = make_help_button(self, self._help_texts[spec.name])
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            sizer.Add(row, 0, wx.ALL, 5)

            style = wx.TE_MULTILINE if spec.multiline else 0
            ctrl = wx.TextCtrl(self, style=style)
            if spec.multiline:
                self._bind_autosize(ctrl)
            self.fields[spec.name] = ctrl
            # Высоту многострочных полей мы управляем вручную,
            # поэтому не передаём sizer'у коэффициент роста.
            sizer.Add(ctrl, 0, wx.EXPAND | wx.ALL, 5)
            if spec.hint:
                ctrl.SetHint(_(spec.hint))
            if spec.name == "id":
                ctrl.Bind(wx.EVT_TEXT, self._on_id_change)

        grid = wx.FlexGridSizer(cols=2, hgap=5, vgap=5)
        grid.AddGrowableCol(0, 1)
        grid.AddGrowableCol(1, 1)

        for spec in config.grid_fields:
            container = wx.BoxSizer(wx.VERTICAL)
            label = wx.StaticText(self, label=labels[spec.name])
            help_btn = make_help_button(self, self._help_texts[spec.name])
            if spec.control == "enum":
                enum_cls = ENUMS[spec.name]
                choices = [locale.code_to_label(spec.name, e.value) for e in enum_cls]
                choice = wx.Choice(self, choices=choices)
                row = wx.BoxSizer(wx.HORIZONTAL)
                row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
                row.Add(choice, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
                row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
                self.enums[spec.name] = choice
                container.Add(row, 0, wx.EXPAND | wx.ALL, 5)
            else:
                row = wx.BoxSizer(wx.HORIZONTAL)
                row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
                row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
                container.Add(row, 0, wx.ALL, 5)
                ctrl = wx.TextCtrl(self)
                if spec.hint:
                    ctrl.SetHint(_(spec.hint))
                self.fields[spec.name] = ctrl
                container.Add(ctrl, 0, wx.EXPAND | wx.ALL, 5)

            grid.Add(container, 1, wx.EXPAND)

        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 5)

        # attachments section --------------------------------------------
        a_sizer = HelpStaticBox(
            self,
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
        a_sizer.Add(self.attachments_list, 0, wx.EXPAND | wx.ALL, 5)
        a_sizer.Add(btn_row, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        sizer.Add(a_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # approval date and notes ---------------------------------------
        container = wx.BoxSizer(wx.VERTICAL)
        row = wx.BoxSizer(wx.HORIZONTAL)
        label = wx.StaticText(self, label=_("Approved at"))
        help_btn = make_help_button(self, self._help_texts["approved_at"])
        row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
        row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        container.Add(row, 0, wx.ALL, 5)
        self.approved_picker = wx.adv.DatePickerCtrl(
            self,
            style=wx.adv.DP_ALLOWNONE,
        )
        container.Add(self.approved_picker, 0, wx.ALL, 5)
        sizer.Add(container, 0, wx.ALL, 5)

        container = wx.BoxSizer(wx.VERTICAL)
        row = wx.BoxSizer(wx.HORIZONTAL)
        label = wx.StaticText(self, label=_("Notes"))
        help_btn = make_help_button(self, self._help_texts["notes"])
        row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
        row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        container.Add(row, 0, wx.ALL, 5)
        self.notes_ctrl = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        self._bind_autosize(self.notes_ctrl)
        container.Add(self.notes_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(container, 0, wx.EXPAND | wx.ALL, 5)

        # grouped links and metadata ------------------------------------
        links_grid = wx.FlexGridSizer(cols=2, hgap=5, vgap=5)
        links_grid.AddGrowableCol(0, 1)
        links_grid.AddGrowableCol(1, 1)
        links_grid.AddGrowableRow(0, 1)

        # labels section -------------------------------------------------
        box_sizer = HelpStaticBox(
            self,
            _("Labels"),
            self._help_texts["labels"],
        )
        box = box_sizer.GetStaticBox()
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.labels_panel = wx.Panel(box)
        self.labels_panel.SetSizer(wx.BoxSizer(wx.HORIZONTAL))
        # ограничиваем высоту меток одной строкой
        line_height = self.GetCharHeight() + 6
        self.labels_panel.SetMinSize((-1, line_height))
        self.labels_panel.Bind(wx.EVT_LEFT_DOWN, self._on_labels_click)
        row.Add(self.labels_panel, 1, wx.EXPAND | wx.RIGHT, 5)
        edit_labels_btn = wx.Button(box, label=_("Edit..."))
        edit_labels_btn.Bind(wx.EVT_BUTTON, self._on_labels_click)
        row.Add(edit_labels_btn, 0)
        box_sizer.Add(row, 0, wx.EXPAND | wx.ALL, 5)
        links_grid.Add(box_sizer, 0, wx.EXPAND | wx.ALL, 5)
        self._label_defs: list[LabelDef] = []
        self._labels_allow_freeform = False

        # generic links section ----------------------------------------
        ln_sizer = self._create_links_section(
            _("IDs of linked requirements"),
            "links",
            help_key="links",
        )
        links_grid.Add(ln_sizer, 0, wx.EXPAND | wx.ALL, 5)

        sizer.Add(links_grid, 0, wx.EXPAND | wx.ALL, 5)

        self.save_btn = wx.Button(self, label=_("Save"))
        self.save_btn.Bind(wx.EVT_BUTTON, self._on_save_button)
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row.Add(self.save_btn, 0, wx.ALL, 5)
        sizer.Add(btn_row, 0, wx.ALIGN_RIGHT)

        self.SetSizer(sizer)
        self.SetupScrolling()

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

    # helpers -------------------------------------------------------------
    def _load_document(self) -> Document | None:
        if not self.directory:
            return None
        if self._document is not None:
            return self._document
        try:
            self._document = load_document(self.directory)
        except Exception:  # pragma: no cover - filesystem errors
            logger.exception("Failed to load document metadata from %s", self.directory)
            self._document = None
        return self._document

    def _refresh_known_ids(self, doc: Document | None = None) -> set[int]:
        if doc is not None:
            self._document = doc
        document = doc or self._load_document()
        if not document or not self.directory:
            self._known_ids = set()
            return self._known_ids
        try:
            ids = list_item_ids(self.directory, document)
        except Exception:  # pragma: no cover - filesystem errors
            logger.exception("Failed to enumerate requirement ids in %s", self.directory)
            ids = set()
        self._known_ids = ids
        return ids

    def _get_known_ids(self) -> set[int]:
        if self._known_ids is None:
            return self._refresh_known_ids()
        return self._known_ids

    def _has_id_conflict(self, req_id: int, *, doc: Document | None = None) -> bool:
        if not self.directory or req_id <= 0:
            return False
        if self.original_id is not None and req_id == self.original_id:
            return False
        ids = self._refresh_known_ids(doc) if doc is not None else self._get_known_ids()
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
        sizer = HelpStaticBox(
            self,
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
        sizer.Add(row, 0, wx.EXPAND | wx.ALL, 5)
        lst = wx.ListCtrl(box, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        lst.InsertColumn(0, _("ID"))
        lst.InsertColumn(1, _("Title"))
        lst.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
        lst.SetColumnWidth(1, wx.LIST_AUTOSIZE_USEHEADER)
        lst.Bind(
            wx.EVT_SIZE,
            lambda evt, lc=lst: (evt.Skip(), self._autosize_link_columns(lc)),
        )
        sizer.Add(lst, 1, wx.EXPAND | wx.ALL, 5)
        # по умолчанию список и кнопка удаления скрыты
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

    def _link_widgets(self, attr: str):
        id_attr = f"{attr}_id"
        list_attr = f"{attr}_list"
        return getattr(self, id_attr), getattr(self, list_attr), getattr(self, attr)

    def _refresh_links_visibility(self, attr: str) -> None:
        """Show list and remove button only when links exist."""
        _, list_ctrl, links_list = self._link_widgets(attr)
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

    def _rebuild_links_list(self, attr: str) -> None:
        """Repopulate ListCtrl for given link attribute."""
        _, list_ctrl, links_list = self._link_widgets(attr)
        list_ctrl.DeleteAllItems()
        for link in links_list:
            src_rid = link["rid"]
            idx = list_ctrl.InsertItem(list_ctrl.GetItemCount(), src_rid)
            note = str(link.get("title", ""))
            if link.get("suspect"):
                warning = _("Suspect link")
                note = f"⚠ {warning}" + (f" — {note}" if note else "")
                list_ctrl.SetItemTextColour(idx, wx.RED)
            else:
                list_ctrl.SetItemTextColour(idx, wx.NullColour)
            list_ctrl.SetItem(idx, 1, note)

    # basic operations -------------------------------------------------
    def set_directory(self, directory: str | Path | None) -> None:
        """Set working directory for ID validation."""
        self.directory = Path(directory) if directory else None
        self._document = None
        self._known_ids = None
        self._id_conflict = False
        self._on_id_change()

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
                    Verification.ANALYSIS.value,
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
            data = requirement_to_dict(data)
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
            self.links = parsed_links
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
        self.mark_clean()

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
                raise ValueError(_("Revision must be a positive integer"))
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
        return requirement_from_dict(
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

    def _on_add_attachment(self, _event: wx.CommandEvent) -> None:
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
        self.attachments.append({"path": path, "note": note})
        self._refresh_attachments()

    def _on_remove_attachment(self, _event: wx.CommandEvent) -> None:
        idx = self.attachments_list.GetFirstSelected()
        if idx != -1:
            del self.attachments[idx]
            self._refresh_attachments()

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
        revision = 1  # preserved for compatibility but unused afterwards
        title = ""
        fingerprint = None
        if self.directory:
            try:
                root = Path(self.directory).parent
                doc = load_document(root / prefix)
                data, _ = load_item(root / prefix, doc, item_id)
                revision = int(data.get("revision", 1))
                title = str(data.get("title", ""))
                fingerprint = requirement_fingerprint(data)
            except Exception:  # pragma: no cover - lookup errors
                logger.exception("Failed to load requirement %s", value)
        links_list.append(
            {
                "rid": value,
                "fingerprint": fingerprint,
                "suspect": False,
                "title": title,
            }
        )
        idx = list_ctrl.InsertItem(list_ctrl.GetItemCount(), value)
        list_ctrl.SetItem(idx, 1, title)
        id_ctrl.ChangeValue("")
        self._refresh_links_visibility(attr)

    def _on_remove_link_generic(self, attr: str) -> None:
        _, list_ctrl, links_list = self._link_widgets(attr)
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
        if not self.directory:
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

    def save(self, directory: str | Path, *, doc: Document) -> Path:
        """Persist editor contents to ``directory`` within ``doc`` and return path."""

        req = self.get_data()
        self._document = doc
        if self._has_id_conflict(req.id, doc=doc):
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
        data = requirement_to_dict(req)
        path = save_item(directory, doc, data)
        self.fields["modified_at"].ChangeValue(req.modified_at)
        self.original_modified_at = req.modified_at
        self.current_path = path
        self.mtime = path.stat().st_mtime
        self.directory = Path(directory)
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

    def is_dirty(self) -> bool:
        """Return True when editor content differs from saved baseline."""

        if self._saved_state is None:
            return False
        return self._snapshot_state() != self._saved_state

    def add_attachment(self, path: str, note: str = "") -> None:
        """Append attachment with ``path`` and optional ``note``."""

        self.attachments.append({"path": path, "note": note})
        if hasattr(self, "attachments_list"):
            idx = self.attachments_list.InsertItem(
                self.attachments_list.GetItemCount(),
                path,
            )
            self.attachments_list.SetItem(idx, 1, note)
