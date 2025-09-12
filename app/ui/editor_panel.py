"""Requirement editor panel."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from gettext import gettext as _

import wx
from wx.lib.dialogs import ScrolledMessageDialog
from wx.lib.scrolledpanel import ScrolledPanel

from app.core import store
from app.core.labels import Label
from app.core.model import (
    Requirement,
    RequirementType,
    Status,
    Priority,
    Verification,
    Attachment,
    requirement_from_dict,
    requirement_to_dict,
)
from . import locale


class EditorPanel(ScrolledPanel):
    """Panel for creating and editing requirements."""

    def __init__(
        self,
        parent: wx.Window,
        on_save: Callable[[], None] | None = None,
        on_add_derived: Callable[[Requirement], None] | None = None,
    ):
        super().__init__(parent)
        self.fields: dict[str, wx.TextCtrl] = {}
        self.enums: dict[str, wx.Choice] = {}
        self.derivation_fields: dict[str, wx.TextCtrl] = {}
        self._autosize_fields: list[wx.TextCtrl] = []
        self._on_save_callback = on_save
        self._on_add_derived_callback = on_add_derived
        self.directory: Path | None = None
        self.original_id: int | None = None

        labels = {
            "id": _("Requirement ID (number)"),
            "title": _("Short title"),
            "statement": _("Requirement text"),
            "acceptance": _("Acceptance criteria"),
            "conditions": _("Conditions"),
            "trace_up": _("Trace up"),
            "trace_down": _("Trace down"),
            "version": _("Requirement version"),
            "modified_at": _("Modified at"),
            "owner": _("Owner"),
            "source": _("Source"),
            "type": _("Requirement type"),
            "status": _("Status"),
            "priority": _("Priority"),
            "verification": _("Verification method"),
            "rationale": _("Rationale"),
            "assumptions": _("Assumptions"),
            "method": _("Method"),
            "margin": _("Margin"),
        }

        help_texts = {
            "id": _(
                "The 'Requirement ID' field must contain a unique integer without prefixes. "
                "It is used to reference the requirement in documentation and tests."
            ),
            "title": _(
                "Short descriptive title displayed in lists. Helps to quickly understand the requirement."
            ),
            "statement": _(
                "Full description of what the system must do or which constraints exist."
            ),
            "acceptance": _(
                "Describe how to verify the requirement. Can be scenarios or measurable criteria."
            ),
            "conditions": _("Conditions of execution and modes for the requirement."),
            "trace_up": _("Related higher level requirements."),
            "trace_down": _("Related lower level requirements."),
            "version": _("Current requirement version."),
            "modified_at": _("Date of last change (set automatically)."),
            "owner": _(
                "Person or team responsible for the requirement. Provide a name or role."
            ),
            "source": _(
                "Source of the requirement: document, customer request or regulation."
            ),
            "type": _("Choose requirement type: functional, constraint, interface, etc."),
            "status": _(
                "Current processing status: draft, in review, approved, etc."
            ),
            "priority": _(
                "Importance of the requirement. High priority is implemented earlier."
            ),
            "verification": _(
                "Method of verification: inspection, analysis, demonstration, test."
            ),
            "rationale": _("Reasoning for the derivation."),
            "assumptions": _("Assumptions used during derivation."),
            "method": _("Derivation method."),
            "margin": _("Applied margin."),
        }

        def make_help_button(message: str) -> wx.Button:
            btn = wx.Button(self, label="?", style=wx.BU_EXACTFIT)
            btn.Bind(wx.EVT_BUTTON, lambda _evt, msg=message: self._show_help(msg))
            return btn

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
            help_btn = make_help_button(help_texts[name])
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
            help_btn = make_help_button(help_texts[name])
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            container.Add(row, 0, wx.ALL, 5)
            ctrl = wx.TextCtrl(self)
            if name == "modified_at":
                ctrl.SetEditable(False)
            self.fields[name] = ctrl
            container.Add(ctrl, 0, wx.EXPAND | wx.ALL, 5)
            grid.Add(container, 1, wx.EXPAND)

        def add_enum_field(name: str) -> None:
            container = wx.BoxSizer(wx.VERTICAL)
            label = wx.StaticText(self, label=labels[name])
            codes = getattr(locale, name.upper()).keys()
            choices = [locale.code_to_label(name, code) for code in codes]
            choice = wx.Choice(self, choices=choices)
            help_btn = make_help_button(help_texts[name])
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

        # labels section -------------------------------------------------
        box = wx.StaticBox(self, label=_("Labels"))
        box_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)
        self.labels_panel = wx.Panel(box)
        self.labels_panel.SetSizer(wx.BoxSizer(wx.HORIZONTAL))
        self.labels_panel.Bind(wx.EVT_LEFT_DOWN, self._on_labels_click)
        box_sizer.Add(self.labels_panel, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(box_sizer, 0, wx.EXPAND | wx.ALL, 5)
        self._label_defs: list[Label] = []

        # derived from section -------------------------------------------
        df_box = wx.StaticBox(self, label=_("Derived from"))
        df_sizer = wx.StaticBoxSizer(df_box, wx.VERTICAL)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.derived_id = wx.TextCtrl(df_box)
        row.Add(self.derived_id, 1, wx.EXPAND | wx.RIGHT, 5)
        add_link_btn = wx.Button(df_box, label=_("Add"))
        add_link_btn.Bind(wx.EVT_BUTTON, self._on_add_link)
        row.Add(add_link_btn, 0)
        df_sizer.Add(row, 0, wx.EXPAND | wx.ALL, 5)
        self.derived_list = wx.CheckListBox(df_box, choices=[])
        self.derived_list.Bind(wx.EVT_CHECKLISTBOX, self._on_link_toggle)
        df_sizer.Add(self.derived_list, 1, wx.EXPAND | wx.ALL, 5)
        sizer.Add(df_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # derivation details ---------------------------------------------
        for name, multiline in [
            ("rationale", True),
            ("assumptions", True),
            ("method", False),
            ("margin", False),
        ]:
            label = wx.StaticText(self, label=labels[name])
            sizer.Add(label, 0, wx.ALL, 5)
            style = wx.TE_MULTILINE if multiline else 0
            ctrl = wx.TextCtrl(self, style=style)
            if multiline:
                self._bind_autosize(ctrl)
            self.derivation_fields[name] = ctrl
            # Здесь также используем пропорцию 0, чтобы изменение
            # одного поля не растягивало другие.
            sizer.Add(ctrl, 0, wx.EXPAND | wx.ALL, 5)

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
        self._app = wx.GetApp()
        self._refresh_labels_display()

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

    # basic operations -------------------------------------------------
    def set_directory(self, directory: str | Path | None) -> None:
        """Set working directory for ID validation."""
        self.directory = Path(directory) if directory else None
        self._on_id_change()

    def new_requirement(self) -> None:
        for ctrl in self.fields.values():
            ctrl.SetValue("")
        defaults = {
            "type": locale.code_to_label("type", "requirement"),
            "status": locale.code_to_label("status", "draft"),
            "priority": locale.code_to_label("priority", "medium"),
            "verification": locale.code_to_label("verification", "analysis"),
        }
        for name, choice in self.enums.items():
            choice.SetStringSelection(defaults[name])
        self.attachments = []
        self.derived_from = []
        self.current_path = None
        self.mtime = None
        self.original_id = None
        self.extra.update({
            "labels": [],
            "revision": 1,
            "approved_at": None,
            "notes": "",
        })
        self.derived_list.Set([])
        self.derived_id.SetValue("")
        for ctrl in self.derivation_fields.values():
            ctrl.SetValue("")
        self._auto_resize_all()
        self._refresh_labels_display()
        self._on_id_change()

    def load(
        self,
        data: Requirement | dict[str, Any],
        *,
        path: str | Path | None = None,
        mtime: float | None = None,
    ) -> None:
        if isinstance(data, Requirement):
            data = requirement_to_dict(data)
        for name, ctrl in self.fields.items():
            ctrl.SetValue(str(data.get(name, "")))
        self.attachments = list(data.get("attachments", []))
        self.derived_from = [dict(link) for link in data.get("derived_from", [])]
        items = [f"{d['source_id']} (r{d['source_revision']})" for d in self.derived_from]
        self.derived_list.Set(items)
        for i, link in enumerate(self.derived_from):
            self.derived_list.Check(i, link.get("suspect", False))
        self.derived_id.SetValue("")
        for name, choice in self.enums.items():
            mapping = getattr(locale, name.upper())
            code = data.get(name, next(iter(mapping)))
            choice.SetStringSelection(locale.code_to_label(name, code))
        for key in self.extra:
            if key in data:
                self.extra[key] = data[key]
        self.current_path = Path(path) if path else None
        self.mtime = mtime
        self.original_id = data.get("id")
        self._refresh_labels_display()
        derivation = data.get("derivation", {})
        for name, ctrl in self.derivation_fields.items():
            if name == "assumptions":
                ctrl.SetValue("\n".join(derivation.get(name, [])))
            else:
                ctrl.SetValue(derivation.get(name, ""))
        self._auto_resize_all()
        self._on_id_change()

    def clone(self, new_id: int) -> None:
        self.fields["id"].SetValue(str(new_id))
        self.current_path = None
        self.mtime = None
        self.original_id = None
        self.derived_from = []
        self.derived_list.Set([])
        for ctrl in self.derivation_fields.values():
            ctrl.SetValue("")
        self._auto_resize_all()
        self._refresh_labels_display()

    # data helpers -----------------------------------------------------
    def get_data(self) -> Requirement:
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
            "type": locale.label_to_code("type", self.enums["type"].GetStringSelection()),
            "status": locale.label_to_code("status", self.enums["status"].GetStringSelection()),
            "owner": self.fields["owner"].GetValue(),
            "priority": locale.label_to_code("priority", self.enums["priority"].GetStringSelection()),
            "source": self.fields["source"].GetValue(),
            "verification": locale.label_to_code(
                "verification", self.enums["verification"].GetStringSelection()
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
            "approved_at": self.extra.get("approved_at"),
            "notes": self.extra.get("notes", ""),
            "derived_from": list(self.derived_from),
        }
        self.extra["labels"] = data["labels"]
        if any(
            ctrl.GetValue().strip() for ctrl in self.derivation_fields.values()
        ):
            assumptions = [
                s.strip()
                for s in self.derivation_fields["assumptions"].GetValue().splitlines()
                if s.strip()
            ]
            data["derivation"] = {
                "rationale": self.derivation_fields["rationale"].GetValue(),
                "assumptions": assumptions,
                "method": self.derivation_fields["method"].GetValue(),
                "margin": self.derivation_fields["margin"].GetValue(),
            }
        return requirement_from_dict(data)

    # labels helpers ---------------------------------------------------
    def update_labels_list(self, labels: list[Label]) -> None:
        """Update available labels and reapply selection."""
        self._label_defs = list(labels)
        current = [
            lbl for lbl in self.extra.get("labels", []) if any(l.name == lbl for l in labels)
        ]
        self.extra["labels"] = current
        self._refresh_labels_display()

    def apply_label_selection(self, labels: list[str]) -> None:
        """Apply selected ``labels`` to requirement and refresh display."""
        available = {l.name for l in self._label_defs}
        self.extra["labels"] = [lbl for lbl in labels if lbl in available]
        self._refresh_labels_display()

    def _refresh_labels_display(self) -> None:
        if not wx.GetApp():
            return
        sizer = self.labels_panel.GetSizer()
        if sizer:
            sizer.Clear(False)
        labels = self.extra.get("labels", [])
        if not labels:
            placeholder = wx.StaticText(self.labels_panel, label=_("(none)"))
            placeholder.SetForegroundColour(wx.Colour("grey"))
            placeholder.Bind(wx.EVT_LEFT_DOWN, self._on_labels_click)
            sizer.Add(placeholder, 0)
        else:
            for i, name in enumerate(labels):
                lbl_def = next((l for l in self._label_defs if l.name == name), None)
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
        choices = [lbl.name for lbl in self._label_defs]
        if not choices:
            return
        preselect = [
            i for i, lbl in enumerate(self._label_defs) if lbl.name in self.extra.get("labels", [])
        ]
        dlg = wx.MultiChoiceDialog(self, _("Select labels"), _("Labels"), choices)
        dlg.SetSelections(preselect)
        if dlg.ShowModal() == wx.ID_OK:
            selected = [choices[i] for i in dlg.GetSelections()]
            self.apply_label_selection(selected)
        dlg.Destroy()

    def _on_add_link(self, _event: wx.CommandEvent) -> None:
        value = self.derived_id.GetValue().strip()
        if not value:
            return
        try:
            src_id = int(value)
        except ValueError:
            return
        revision = 1
        if self.directory:
            path = self.directory / f"{src_id}.json"
            try:
                data, _ = store.load(path)
                revision = data.get("revision", 1)
            except Exception:
                pass
        self.derived_from.append(
            {"source_id": src_id, "source_revision": revision, "suspect": False}
        )
        self.derived_list.Append(f"{src_id} (r{revision})")
        self.derived_id.SetValue("")

    def _on_link_toggle(self, _event: wx.CommandEvent) -> None:
        for i, link in enumerate(self.derived_from):
            link["suspect"] = self.derived_list.IsChecked(i)

    def _on_add_derived_button(self, _evt: wx.Event) -> None:
        if not self._on_add_derived_callback:
            return
        try:
            req = self.get_data()
        except Exception:
            return
        self._on_add_derived_callback(req)

    def _on_id_change(self, _event: wx.CommandEvent | None = None) -> None:
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
            if req_id <= 0:
                raise ValueError
        except Exception:
            ctrl.SetBackgroundColour(wx.Colour(255, 200, 200))
            ctrl.Refresh()
            return
        ids = set(store.load_index(self.directory))
        if self.original_id is not None:
            ids.discard(self.original_id)
        if req_id in ids:
            ctrl.SetBackgroundColour(wx.Colour(255, 200, 200))
        else:
            ctrl.SetBackgroundColour(wx.NullColour)
        ctrl.Refresh()

    def _on_save_button(self, _evt: wx.Event) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.fields["modified_at"].SetValue(now)
        if self._on_save_callback:
            self._on_save_callback()

    def save(self, directory: str | Path) -> Path:
        req = self.get_data()
        path = store.save(directory, req, mtime=self.mtime)
        self.current_path = path
        self.mtime = path.stat().st_mtime
        self.directory = Path(directory)
        self.original_id = req.id
        self._on_id_change()
        return path

    def delete(self) -> None:
        if self.current_path and self.current_path.exists():
            store.delete(self.current_path.parent, int(self.current_path.stem))
        self.current_path = None
        self.mtime = None
        self.original_id = None

    def add_attachment(self, path: str, note: str = "") -> None:
        self.attachments.append({"path": path, "note": note})

    # helpers ----------------------------------------------------------
    def _show_help(self, message: str) -> None:
        dlg = ScrolledMessageDialog(self, message, _("Hint"))
        dlg.ShowModal()
        dlg.Destroy()
