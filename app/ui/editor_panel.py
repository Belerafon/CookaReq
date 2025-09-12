"""Requirement editor panel."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from gettext import gettext as _

import wx
from wx.lib.dialogs import ScrolledMessageDialog

from app.core import store
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


class EditorPanel(wx.Panel):
    """Panel for creating and editing requirements."""

    def __init__(self, parent: wx.Window, on_save: Callable[[], None] | None = None):
        super().__init__(parent)
        self.fields: dict[str, wx.TextCtrl] = {}
        self.enums: dict[str, wx.Choice] = {}
        self._on_save_callback = on_save
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
            if name == "source":
                ctrl.SetMinSize((-1, 60))
            self.fields[name] = ctrl
            proportion = 1 if multiline and name != "source" else 0
            sizer.Add(ctrl, proportion, wx.EXPAND | wx.ALL, 5)
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
        self.labels_list = wx.CheckListBox(box, choices=[])
        self.labels_list.Bind(wx.EVT_CHECKLISTBOX, self._on_label_toggle)
        box_sizer.Add(self.labels_list, 1, wx.EXPAND | wx.ALL, 5)
        sizer.Add(box_sizer, 0, wx.EXPAND | wx.ALL, 5)

        self.save_btn = wx.Button(self, label=_("Save"))
        self.save_btn.Bind(wx.EVT_BUTTON, self._on_save_button)
        sizer.Add(self.save_btn, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        self.SetSizer(sizer)

        self.attachments: list[dict[str, str]] = []
        self.extra: dict[str, Any] = {
            "labels": [],
            "revision": 1,
            "approved_at": None,
            "notes": "",
        }
        self.current_path: Path | None = None
        self.mtime: float | None = None

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
        self.current_path = None
        self.mtime = None
        self.original_id = None
        self.extra.update({
            "labels": [],
            "revision": 1,
            "approved_at": None,
            "notes": "",
        })
        for i in range(self.labels_list.GetCount()):
            self.labels_list.Check(i, False)
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
        for i in range(self.labels_list.GetCount()):
            name = self.labels_list.GetString(i)
            self.labels_list.Check(i, name in self.extra["labels"])
        self._on_id_change()

    def clone(self, new_id: int) -> None:
        self.fields["id"].SetValue(str(new_id))
        self.current_path = None
        self.mtime = None
        self.original_id = None

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
            "labels": [
                self.labels_list.GetString(i)
                for i in range(self.labels_list.GetCount())
                if self.labels_list.IsChecked(i)
            ],
            "attachments": list(self.attachments),
            "revision": self.extra.get("revision", 1),
            "approved_at": self.extra.get("approved_at"),
            "notes": self.extra.get("notes", ""),
        }
        self.extra["labels"] = data["labels"]
        return requirement_from_dict(data)

    # labels helpers ---------------------------------------------------
    def update_labels_list(self, labels: list[str]) -> None:
        """Update available labels and reapply selection."""
        self.labels_list.Set(labels)
        current = [lbl for lbl in self.extra.get("labels", []) if lbl in labels]
        self.extra["labels"] = current
        for i, name in enumerate(labels):
            self.labels_list.Check(i, name in current)

    def _on_label_toggle(self, _event: wx.CommandEvent) -> None:
        self.extra["labels"] = [
            self.labels_list.GetString(i)
            for i in range(self.labels_list.GetCount())
            if self.labels_list.IsChecked(i)
        ]

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
