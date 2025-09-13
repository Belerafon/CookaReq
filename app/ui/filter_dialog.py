"""Dialog for configuring requirement filters."""
from __future__ import annotations

from ..i18n import _
from typing import Dict

import wx

from ..core import requirements as req_ops
from ..core.model import Status
from . import locale


class FilterDialog(wx.Dialog):
    """Dialog allowing to configure various filters."""

    def __init__(self, parent: wx.Window, *, labels: list[str], values: Dict | None = None) -> None:
        title = _("Filters")
        super().__init__(parent, title=title)
        self._labels = labels
        self._build_ui(values or {})

    def _build_ui(self, values: Dict) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Global query across all searchable fields
        sizer.Add(wx.StaticText(self, label=_("Any field contains")), 0, wx.ALL, 5)
        self.any_query = wx.TextCtrl(self)
        self.any_query.SetValue(values.get("query", ""))
        sizer.Add(self.any_query, 0, wx.EXPAND | wx.ALL, 5)

        # Per-field queries
        self.field_controls: Dict[str, wx.TextCtrl] = {}
        for field in sorted(req_ops.SEARCHABLE_FIELDS):
            sizer.Add(wx.StaticText(self, label=field.title()), 0, wx.ALL, 5)
            ctrl = wx.TextCtrl(self)
            ctrl.SetValue(values.get("field_queries", {}).get(field, ""))
            self.field_controls[field] = ctrl
            sizer.Add(ctrl, 0, wx.EXPAND | wx.ALL, 5)

        # Labels
        sizer.Add(wx.StaticText(self, label=_("Labels")), 0, wx.ALL, 5)
        self.labels_box = wx.CheckListBox(self, choices=self._labels)
        for lbl in values.get("labels", []):
            if lbl in self._labels:
                idx = self._labels.index(lbl)
                self.labels_box.Check(idx)
        sizer.Add(self.labels_box, 0, wx.EXPAND | wx.ALL, 5)

        self.match_any = wx.CheckBox(self, label=_("Match any labels"))
        self.match_any.SetValue(values.get("match_any", False))
        sizer.Add(self.match_any, 0, wx.ALL, 5)

        # Status filter
        sizer.Add(wx.StaticText(self, label=_("Status")), 0, wx.ALL, 5)
        self._status_values = [s.value for s in Status]
        status_choices = [_("(any)")] + [locale.STATUS[v] for v in self._status_values]
        self.status_choice = wx.Choice(self, choices=status_choices)
        selected = 0
        if values.get("status") in self._status_values:
            selected = self._status_values.index(values["status"]) + 1
        self.status_choice.SetSelection(selected)
        sizer.Add(self.status_choice, 0, wx.EXPAND | wx.ALL, 5)

        # Derived filters
        self.is_derived = wx.CheckBox(self, label=_("Derived only"))
        self.is_derived.SetValue(values.get("is_derived", False))
        sizer.Add(self.is_derived, 0, wx.ALL, 5)

        self.has_derived = wx.CheckBox(self, label=_("Has derived"))
        self.has_derived.SetValue(values.get("has_derived", False))
        sizer.Add(self.has_derived, 0, wx.ALL, 5)

        self.suspect_only = wx.CheckBox(self, label=_("Suspect only"))
        self.suspect_only.SetValue(values.get("suspect_only", False))
        sizer.Add(self.suspect_only, 0, wx.ALL, 5)

        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btns, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        self.SetSizerAndFit(sizer)

    def get_filters(self) -> Dict:
        """Return chosen filters as a dict."""
        labels = [self._labels[i] for i in range(self.labels_box.GetCount()) if self.labels_box.IsChecked(i)]
        field_queries = {field: ctrl.GetValue() for field, ctrl in self.field_controls.items() if ctrl.GetValue()}
        return {
            "query": self.any_query.GetValue(),
            "labels": labels,
            "match_any": self.match_any.GetValue(),
            "status": (self._status_values[self.status_choice.GetSelection() - 1]
                        if self.status_choice.GetSelection() > 0 else None),
            "is_derived": self.is_derived.GetValue(),
            "has_derived": self.has_derived.GetValue(),
            "suspect_only": self.suspect_only.GetValue(),
            "field_queries": field_queries,
        }
