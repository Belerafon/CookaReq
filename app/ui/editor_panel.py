"""Requirement editor panel."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

import wx
import wx.adv
from wx.lib.scrolledpanel import ScrolledPanel

from ..core import requirements as req_ops
from ..core.doc_store import Document, save_item
from ..core.labels import Label
from ..core.model import (
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
    requirement_from_dict,
    requirement_to_dict,
)
from ..util.time import local_now_str, normalize_timestamp
from ..i18n import _
from . import locale
from .enums import ENUMS
from .helpers import HelpStaticBox, make_help_button, show_help
from .label_selection_dialog import LabelSelectionDialog

logger = logging.getLogger(__name__)


class EditorPanel(ScrolledPanel):
    """Panel for creating and editing requirements."""

    def __init__(
        self,
        parent: wx.Window,
        on_save: Callable[[], None] | None = None,
        on_add_derived: Callable[[Requirement], None] | None = None,
    ):
        """Initialize requirement editor widgets."""
        super().__init__(parent)
        self.fields: dict[str, wx.TextCtrl] = {}
        self.enums: dict[str, wx.Choice] = {}
        self.derivation_fields: dict[str, wx.TextCtrl] = {}
        self._autosize_fields: list[wx.TextCtrl] = []
        self._suspend_events = False
        self.original_modified_at = ""
        self._on_save_callback = on_save
        self._on_add_derived_callback = on_add_derived
        self.directory: Path | None = None
        self.original_id: int | None = None

        field_names = [
            "id",
            "title",
            "statement",
            "acceptance",
            "conditions",
            "trace_up",
            "trace_down",
            "version",
            "modified_at",
            "owner",
            "source",
            "type",
            "status",
            "priority",
            "verification",
            "rationale",
            "assumptions",
        ]
        labels = {name: locale.field_label(name) for name in field_names}

        help_texts = {
            "id": _(
                "The 'Requirement ID' is a unique integer used as the stable anchor for a requirement. "
                "Teams refer to it in traceability matrices, change requests and test reports to ensure everyone talks about the same item. "
                "Once the identifier appears in external documents it should not be changed to avoid broken references.",
            ),
            "title": _(
                "A concise human-readable summary shown in lists and diagrams. "
                "It lets stakeholders skim large sets of requirements and quickly find relevant topics. "
                "Use clear keywords so search and sorting produce meaningful results.",
            ),
            "statement": _(
                "The full requirement statement describing what the system must do or the constraint it imposes. "
                "This wording becomes the authoritative baseline for implementation and contractual obligations. "
                "Detailed phrasing here prevents ambiguity during design and review.",
            ),
            "acceptance": _(
                "Acceptance criteria explain how to verify that the requirement is satisfied. "
                "They may include test scenarios, measurable thresholds or review checklists. "
                "Well-defined criteria let QA teams plan tests and give product owners a clear basis for acceptance.",
            ),
            "conditions": _(
                "Operating conditions and modes under which the requirement applies. "
                "Describe environments, performance ranges or user roles that influence validity. "
                "Such context helps engineers design correctly and testers reproduce the right setup.",
            ),
            "trace_up": _(
                "Links to higher-level requirements or stakeholder needs. "
                "Upward traceability shows why this requirement exists and simplifies impact analysis when parents change. "
                "Use it to prove coverage of system objectives.",
            ),
            "trace_down": _(
                "References to lower-level derived requirements, design elements or test cases. "
                "Downward traceability reveals how the requirement will be implemented and verified. "
                "It supports audits and helps detect missing implementation pieces.",
            ),
            "version": _(
                "Sequential version number for change control. "
                "Increase it whenever the requirement text changes to keep a revision history. "
                "Versioning enables baselining and comparison of snapshots during reviews.",
            ),
            "modified_at": _(
                "Date and time of the last edit. "
                "The value is filled automatically and aids audit trails. "
                "Reviewers can sort by this field to focus on recently modified items.",
            ),
            "owner": _(
                "Person or team responsible for the requirement. "
                "The owner coordinates discussions, approves updates and answers questions from other stakeholders. "
                "Assigning ownership clarifies accountability and speeds up decisions.",
            ),
            "source": _(
                "Origin of the requirement such as a customer request, regulation or design document. "
                "Recording the source explains why the requirement exists and where to look for additional context. "
                "This trace is essential when validating compliance or revisiting negotiations.",
            ),
            "type": _(
                "Classification of the requirement: functional, constraint, interface or quality attribute. "
                "Types help filter large sets, assign specialists and apply different review processes. "
                "Consistent categorization improves reporting and reuse.",
            ),
            "status": _(
                "Lifecycle state like draft, in review, approved or retired. "
                "The status communicates readiness and controls workflow gates. "
                "Dashboards and metrics rely on it to show project progress.",
            ),
            "priority": _(
                "Relative importance or urgency of the requirement. "
                "High-priority items drive planning and resource allocation. "
                "Use priority to focus effort on the capabilities that deliver most value.",
            ),
            "verification": _(
                "Preferred method to prove compliance: inspection, analysis, demonstration or test. "
                "Selecting a method early guides preparation of verification activities and needed tools. "
                "It also clarifies expectations for acceptance.",
            ),
            "rationale": _(
                "Explanation of why the requirement exists or how it was derived. "
                "Capturing rationale preserves design intent and helps future maintainers understand trade-offs. "
                "This background is valuable during change discussions or audits.",
            ),
            "assumptions": _(
                "Assumptions made while formulating the requirement, such as available technologies or expected user behavior. "
                "Listing assumptions exposes risks and clarifies the context that might change. "
                "Revisit them regularly to ensure the requirement remains valid.",
            ),
            "attachments": _(
                "Supplementary files that give additional context like diagrams, logs or calculations. "
                "Attachments travel with the requirement so reviewers and implementers see the same supporting evidence. "
                "Keep file notes concise to explain relevance.",
            ),
            "approved_at": _(
                "Date when the requirement was formally accepted by stakeholders. "
                "Recording the approval moment is useful for audits and for tracking baselines. "
                "Leave empty while the requirement is still under discussion.",
            ),
            "notes": _(
                "Free-form remarks that do not fit other fields. "
                "Use notes to capture review feedback, open questions or implementation hints. "
                "Unlike acceptance criteria they are not part of the requirement contract.",
            ),
            "labels": _(
                "Tags that categorize the requirement. "
                "Consistent labeling enables powerful filtering and helps group related items. "
                "Use shared presets to avoid typos and duplicates.",
            ),
            "parent": _(
                "Reference to the immediate higher-level requirement. "
                "Establishing parenthood keeps the traceability chain intact and simplifies impact analysis. "
                "Clear links are essential during audits and design reviews.",
            ),
            "verifies": _(
                "Links to requirements that this one verifies or tests. "
                "Use it to show downward traceability towards implementation or validation artifacts.",
            ),
            "relates": _(
                "Associations with requirements touching the same topic. "
                "Related links help discover dependencies and avoid conflicting decisions. "
                "They are informational and do not imply hierarchy.",
            ),
            "derived_from": _(
                "Source requirements from which this one was derived. "
                "Capturing derivation clarifies reasoning and lets teams propagate changes upstream.",
            ),
        }

        self._help_texts = help_texts

        sizer = wx.BoxSizer(wx.VERTICAL)

        for name, multiline in [
            ("id", False),
            ("title", False),
            ("statement", True),
            ("acceptance", True),
            ("conditions", True),
            ("trace_up", True),
            ("trace_down", True),
            ("source", True),
        ]:
            label = wx.StaticText(self, label=labels[name])
            help_btn = make_help_button(self, self._help_texts[name])
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            sizer.Add(row, 0, wx.ALL, 5)

            style = wx.TE_MULTILINE if multiline else 0
            ctrl = wx.TextCtrl(self, style=style)
            if multiline:
                self._bind_autosize(ctrl)
            self.fields[name] = ctrl
            # Высоту многострочных полей мы управляем вручную,
            # поэтому не передаём sizer'у коэффициент роста.
            sizer.Add(ctrl, 0, wx.EXPAND | wx.ALL, 5)
            if name == "id":
                ctrl.SetHint(_("Unique integer identifier"))
                ctrl.Bind(wx.EVT_TEXT, self._on_id_change)

        def add_text_field(name: str) -> None:
            container = wx.BoxSizer(wx.VERTICAL)
            label = wx.StaticText(self, label=labels[name])
            help_btn = make_help_button(self, self._help_texts[name])
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            container.Add(row, 0, wx.ALL, 5)
            ctrl = wx.TextCtrl(self)
            self.fields[name] = ctrl
            container.Add(ctrl, 0, wx.EXPAND | wx.ALL, 5)
            grid.Add(container, 1, wx.EXPAND)

        def add_enum_field(name: str) -> None:
            container = wx.BoxSizer(wx.VERTICAL)
            label = wx.StaticText(self, label=labels[name])
            enum_cls = ENUMS[name]
            choices = [locale.code_to_label(name, e.value) for e in enum_cls]
            choice = wx.Choice(self, choices=choices)
            help_btn = make_help_button(self, self._help_texts[name])
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            row.Add(choice, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            self.enums[name] = choice
            container.Add(row, 0, wx.EXPAND | wx.ALL, 5)
            grid.Add(container, 1, wx.EXPAND)

        grid = wx.FlexGridSizer(cols=2, hgap=5, vgap=5)
        grid.AddGrowableCol(0, 1)
        grid.AddGrowableCol(1, 1)

        items = [
            ("type", "enum"),
            ("status", "enum"),
            ("priority", "enum"),
            ("verification", "enum"),
            ("modified_at", "text"),
            ("owner", "text"),
            ("version", "text"),
        ]
        for name, kind in items:
            if kind == "enum":
                add_enum_field(name)
            else:
                add_text_field(name)

        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 5)

        # attachments section --------------------------------------------
        a_sizer = HelpStaticBox(
            self,
            _("Attachments"),
            self._help_texts["attachments"],
            lambda msg: show_help(self, msg),
        )
        a_box = a_sizer.GetStaticBox()
        self.attachments_list = wx.ListCtrl(
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
        links_grid.AddGrowableRow(1, 1)
        links_grid.AddGrowableRow(2, 1)

        # labels section -------------------------------------------------
        box_sizer = HelpStaticBox(
            self,
            _("Labels"),
            self._help_texts["labels"],
            lambda msg: show_help(self, msg),
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
        self._label_defs: list[Label] = []
        self._labels_allow_freeform = False
        self.parent: dict[str, Any] | None = None

        # parent section -------------------------------------------------
        pr_sizer = HelpStaticBox(
            self,
            _("Parent"),
            self._help_texts["parent"],
            lambda msg: show_help(self, msg),
        )
        pr_box = pr_sizer.GetStaticBox()
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.parent_id = wx.TextCtrl(pr_box, size=(120, -1))
        row.Add(self.parent_id, 0, wx.RIGHT, 5)
        set_parent_btn = wx.Button(pr_box, label=_("Set"))
        set_parent_btn.Bind(wx.EVT_BUTTON, self._on_set_parent)
        row.Add(set_parent_btn, 0, wx.RIGHT, 5)
        clear_parent_btn = wx.Button(pr_box, label=_("Clear"))
        clear_parent_btn.Bind(wx.EVT_BUTTON, self._on_clear_parent)
        row.Add(clear_parent_btn, 0)
        pr_sizer.Add(row, 0, wx.ALL, 5)
        self.parent_display = wx.StaticText(pr_box, label=_("(none)"))
        pr_sizer.Add(self.parent_display, 0, wx.ALL, 5)
        links_grid.Add(pr_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # verifies section ----------------------------------------------
        ver_sizer = self._create_links_section(
            _("IDs of requirements this one verifies"),
            "verifies",
            help_key="verifies",
        )
        links_grid.Add(ver_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # relates section -----------------------------------------------
        rel_sizer = self._create_links_section(
            _("IDs of related requirements"),
            "relates",
            help_key="relates",
        )
        links_grid.Add(rel_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # derived from section -------------------------------------------
        df_sizer = self._create_links_section(
            _("IDs of source requirements"),
            "derived_from",
            help_key="derived_from",
            id_name="derived_id",
            list_name="derived_list",
        )
        links_grid.Add(df_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # placeholder to balance grid when odd number of items
        links_grid.Add((0, 0))

        sizer.Add(links_grid, 0, wx.EXPAND | wx.ALL, 5)

        # derivation details ---------------------------------------------
        deriv_box = wx.StaticBox(self, label=_("Derivation"))
        deriv_sizer = wx.StaticBoxSizer(deriv_box, wx.VERTICAL)
        for name, multiline in [
            ("rationale", True),
            ("assumptions", True),
        ]:
            label = wx.StaticText(deriv_box, label=labels[name])
            help_btn = make_help_button(self, self._help_texts[name])
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            deriv_sizer.Add(row, 0, wx.ALL, 5)
            style = wx.TE_MULTILINE if multiline else 0
            ctrl = wx.TextCtrl(deriv_box, style=style)
            if multiline:
                self._bind_autosize(ctrl)
            self.derivation_fields[name] = ctrl
            deriv_sizer.Add(ctrl, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(deriv_sizer, 0, wx.EXPAND | wx.ALL, 5)

        self.save_btn = wx.Button(self, label=_("Save"))
        self.save_btn.Bind(wx.EVT_BUTTON, self._on_save_button)
        self.add_derived_btn = wx.Button(self, label=_("Add derived"))
        self.add_derived_btn.Bind(wx.EVT_BUTTON, self._on_add_derived_button)
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row.Add(self.add_derived_btn, 0, wx.ALL, 5)
        btn_row.Add(self.save_btn, 0, wx.ALL, 5)
        sizer.Add(btn_row, 0, wx.ALIGN_RIGHT)

        self.SetSizer(sizer)
        self.SetupScrolling()

        self.attachments: list[dict[str, str]] = []
        self.derived_from: list[dict[str, Any]] = []
        self.extra: dict[str, Any] = {
            "labels": [],
            "revision": 1,
            "approved_at": None,
            "notes": "",
        }
        self.current_path: Path | None = None
        self.mtime: float | None = None
        self._refresh_labels_display()
        self._refresh_attachments()
        self._refresh_parent_display()

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
            lambda msg: show_help(self, msg),
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
        id_attr = "derived_id" if attr == "derived_from" else f"{attr}_id"
        list_attr = "derived_list" if attr == "derived_from" else f"{attr}_list"
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
            src_id = link["source_id"]
            title = ""
            if self.directory:
                try:
                    req = req_ops.get_requirement(self.directory, src_id)
                    title = req.title or ""
                except Exception:  # pragma: no cover - lookup errors
                    logger.exception("Failed to load requirement %s", src_id)
            idx = list_ctrl.InsertItem(list_ctrl.GetItemCount(), str(src_id))
            list_ctrl.SetItem(idx, 1, title)

    # basic operations -------------------------------------------------
    def set_directory(self, directory: str | Path | None) -> None:
        """Set working directory for ID validation."""
        self.directory = Path(directory) if directory else None
        self._on_id_change()

    def new_requirement(self) -> None:
        """Reset UI fields to create a new requirement."""

        with self._bulk_update():
            for ctrl in self.fields.values():
                ctrl.ChangeValue("")
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
            self.derived_from = []
            self.verifies = []
            self.relates = []
            self.parent = None
            self.current_path = None
            self.mtime = None
            self.original_id = None
            self.extra.update(
                {
                    "labels": [],
                    "revision": 1,
                    "approved_at": None,
                    "notes": "",
                },
            )
            self.approved_picker.SetValue(wx.DefaultDateTime)
            self.notes_ctrl.ChangeValue("")
            self._refresh_attachments()
            self.derived_list.DeleteAllItems()
            self.derived_id.ChangeValue("")
            self.verifies_list.DeleteAllItems()
            self.verifies_id.ChangeValue("")
            self.relates_list.DeleteAllItems()
            self.relates_id.ChangeValue("")
            self._refresh_links_visibility("derived_from")
            self._refresh_links_visibility("verifies")
            self._refresh_links_visibility("relates")
            self._refresh_parent_display()
            for ctrl in self.derivation_fields.values():
                ctrl.ChangeValue("")
            self._refresh_labels_display()
        self.original_modified_at = ""
        self._auto_resize_all()
        self._on_id_change()

    def load(
        self,
        data: Requirement | dict[str, Any],
        *,
        path: str | Path | None = None,
        mtime: float | None = None,
    ) -> None:
        """Populate editor fields from ``data``."""

        if isinstance(data, Requirement):
            data = requirement_to_dict(data)
        self.original_id = data.get("id")
        with self._bulk_update():
            for name, ctrl in self.fields.items():
                ctrl.ChangeValue(str(data.get(name, "")))
            self.attachments = list(data.get("attachments", []))
            self.derived_from = [dict(link) for link in data.get("derived_from", [])]
            self._rebuild_links_list("derived_from")
            self.derived_id.ChangeValue("")
            self._refresh_links_visibility("derived_from")
            links = data.get("links", {})
            self.verifies = [dict(link) for link in links.get("verifies", [])]
            self._rebuild_links_list("verifies")
            self.verifies_id.ChangeValue("")
            self._refresh_links_visibility("verifies")
            self.relates = [dict(link) for link in links.get("relates", [])]
            self._rebuild_links_list("relates")
            self.relates_id.ChangeValue("")
            self._refresh_links_visibility("relates")
            self.parent = dict(data.get("parent", {})) or None
            self._refresh_parent_display()
            for name, choice in self.enums.items():
                enum_cls = ENUMS[name]
                default_code = next(iter(enum_cls)).value
                code = data.get(name, default_code)
                choice.SetStringSelection(locale.code_to_label(name, code))
            labels = data.get("labels")
            self.extra = {
                "labels": list(labels) if isinstance(labels, list) else [],
                "revision": data.get("revision", 1),
                "approved_at": data.get("approved_at"),
                "notes": data.get("notes", ""),
            }
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
            derivation = data.get("derivation", {})
            for name, ctrl in self.derivation_fields.items():
                if name == "assumptions":
                    ctrl.ChangeValue("\n".join(derivation.get(name, [])))
                else:
                    ctrl.ChangeValue(derivation.get(name, ""))
        self.original_modified_at = self.fields["modified_at"].GetValue()
        self._auto_resize_all()
        self._on_id_change()

    def clone(self, new_id: int) -> None:
        """Copy current requirement into a new one with ``new_id``."""

        with self._bulk_update():
            self.fields["id"].ChangeValue(str(new_id))
            self.fields["modified_at"].ChangeValue("")
            self.current_path = None
            self.mtime = None
            self.original_id = None
            self.derived_from = []
            self.derived_list.DeleteAllItems()
            self.verifies = []
            self.verifies_list.DeleteAllItems()
            self.relates = []
            self.relates_list.DeleteAllItems()
            self._refresh_links_visibility("derived_from")
            self._refresh_links_visibility("verifies")
            self._refresh_links_visibility("relates")
            self.parent = None
            self._refresh_parent_display()
            for ctrl in self.derivation_fields.values():
                ctrl.ChangeValue("")
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
            "trace_up": self.fields["trace_up"].GetValue(),
            "trace_down": self.fields["trace_down"].GetValue(),
            "version": self.fields["version"].GetValue(),
            "modified_at": self.fields["modified_at"].GetValue(),
            "labels": list(self.extra.get("labels", [])),
            "attachments": list(self.attachments),
            "revision": self.extra.get("revision", 1),
            "derived_from": list(self.derived_from),
        }
        if self.parent:
            data["parent"] = dict(self.parent)
        if self.verifies or self.relates:
            data["links"] = {
                "verifies": list(self.verifies),
                "relates": list(self.relates),
            }
        dt = self.approved_picker.GetValue()
        approved_at = dt.FormatISODate() if dt.IsValid() else None
        data["approved_at"] = approved_at
        notes = self.notes_ctrl.GetValue()
        data["notes"] = notes
        self.extra["labels"] = data["labels"]
        self.extra["approved_at"] = approved_at
        self.extra["notes"] = notes
        if any(ctrl.GetValue().strip() for ctrl in self.derivation_fields.values()):
            assumptions = [
                s.strip()
                for s in self.derivation_fields["assumptions"].GetValue().splitlines()
                if s.strip()
            ]
            data["derivation"] = {
                "rationale": self.derivation_fields["rationale"].GetValue(),
                "assumptions": assumptions,
            }
        return requirement_from_dict(data)

    # labels helpers ---------------------------------------------------
    def update_labels_list(self, labels: list[Label], allow_freeform: bool = False) -> None:
        """Update available labels, free-form policy and reapply selection."""
        self._label_defs = list(labels)
        self._labels_allow_freeform = allow_freeform
        current = [
            lbl
            for lbl in self.extra.get("labels", [])
            if allow_freeform or any(label.name == lbl for label in labels)
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
            available = {label.name for label in self._label_defs}
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
                        if label_def.name == name
                    ),
                    None,
                )
                color = lbl_def.color if lbl_def else "#cccccc"
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
        self.attachments_list.DeleteAllItems()
        for att in self.attachments:
            idx = self.attachments_list.InsertItem(
                self.attachments_list.GetItemCount(),
                att.get("path", ""),
            )
            self.attachments_list.SetItem(idx, 1, att.get("note", ""))
        visible = bool(self.attachments)
        self.attachments_list.Show(visible)
        sizer = self.attachments_list.GetContainingSizer()
        if sizer:
            sizer.Show(self.attachments_list, visible)
            sizer.Layout()
        self.remove_attachment_btn.Enable(visible)
        self.remove_attachment_btn.Show(visible)
        btn_sizer = self.remove_attachment_btn.GetContainingSizer()
        if btn_sizer:
            btn_sizer.Show(self.remove_attachment_btn, visible)
            btn_sizer.Layout()
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
        value = id_ctrl.GetValue().strip()
        if not value:
            return
        try:
            src_id = int(value)
        except ValueError:
            wx.MessageBox(_("ID must be a number"), _("Error"), style=wx.ICON_ERROR)
            return
        revision = 1
        title = ""
        if self.directory:
            try:
                req = req_ops.get_requirement(self.directory, src_id)
                revision = req.revision or 1
                title = req.title or ""
            except Exception:  # pragma: no cover - lookup errors
                logger.exception("Failed to load requirement %s", src_id)
        links_list.append(
            {"source_id": src_id, "source_revision": revision, "suspect": False},
        )
        idx = list_ctrl.InsertItem(list_ctrl.GetItemCount(), str(src_id))
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

    def _on_set_parent(self, _event: wx.CommandEvent) -> None:
        value = self.parent_id.GetValue().strip()
        if not value:
            return
        try:
            src_id = int(value)
        except ValueError:
            return
        revision = 1
        if self.directory:
            try:
                req = req_ops.get_requirement(self.directory, src_id)
                revision = req.revision or 1
            except Exception:
                logger.exception("Failed to load requirement %s", src_id)
        self.parent = {
            "source_id": src_id,
            "source_revision": revision,
            "suspect": False,
        }
        self.parent_id.ChangeValue("")
        self._refresh_parent_display()

    def _on_clear_parent(self, _event: wx.CommandEvent) -> None:
        self.parent = None
        self._refresh_parent_display()

    def _refresh_parent_display(self) -> None:
        if self.parent:
            txt = f"{self.parent['source_id']} (r{self.parent['source_revision']})"
        else:
            txt = _("(none)")
        self.parent_display.SetLabel(txt)

    def _on_add_derived_button(self, _evt: wx.Event) -> None:
        if not self._on_add_derived_callback:
            return
        try:
            req = self.get_data()
        except Exception:
            return
        self._on_add_derived_callback(req)

    def _on_id_change(self, _event: wx.CommandEvent | None = None) -> None:
        if self._suspend_events:
            return
        ctrl = self.fields["id"]
        ctrl.SetBackgroundColour(wx.NullColour)
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
        ids = req_ops.list_ids(self.directory)
        if self.original_id is not None:
            ids.discard(self.original_id)
        if req_id in ids:
            ctrl.SetBackgroundColour(wx.Colour(255, 200, 200))
        else:
            ctrl.SetBackgroundColour(wx.NullColour)
        ctrl.Refresh()

    def _on_save_button(self, _evt: wx.Event) -> None:
        if self._on_save_callback:
            self._on_save_callback()

    def save(self, directory: str | Path, *, doc: Document | None = None) -> Path:
        """Persist editor contents to ``directory`` and return path."""

        req = self.get_data()
        mod = (
            req.modified_at
            if req.modified_at and req.modified_at != self.original_modified_at
            else None
        )
        if doc:
            req.modified_at = normalize_timestamp(mod) if mod else local_now_str()
            data = requirement_to_dict(req)
            path = save_item(directory, doc, data)
        else:
            path = req_ops.save_requirement(
                directory,
                req,
                mtime=self.mtime,
                modified_at=mod,
            )
        self.fields["modified_at"].ChangeValue(req.modified_at)
        self.original_modified_at = req.modified_at
        self.current_path = path
        self.mtime = path.stat().st_mtime
        self.directory = Path(directory)
        self.original_id = req.id
        self._on_id_change()
        return path

    def delete(self) -> None:
        """Remove currently loaded requirement file if present."""

        if self.current_path and self.current_path.exists():
            req_ops.delete_requirement(
                self.current_path.parent,
                int(self.current_path.stem),
            )
        self.current_path = None
        self.mtime = None
        self.original_id = None

    def add_attachment(self, path: str, note: str = "") -> None:
        """Append attachment with ``path`` and optional ``note``."""

        self.attachments.append({"path": path, "note": note})
        if hasattr(self, "attachments_list"):
            idx = self.attachments_list.InsertItem(
                self.attachments_list.GetItemCount(),
                path,
            )
            self.attachments_list.SetItem(idx, 1, note)
