"""Dialogs for moving or copying requirements between documents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

import wx

from ..i18n import _
from ..services.requirements import Document


class TransferMode(str, Enum):
    """Supported transfer operations."""

    COPY = "copy"
    MOVE = "move"


@dataclass(slots=True)
class RequirementTransferPlan:
    """Result describing how to transfer requirements."""

    target_prefix: str
    mode: TransferMode
    reset_revision: bool = True
    switch_to_target: bool = False


class RequirementTransferDialog(wx.Dialog):
    """Prompt the user for transfer mode and destination document."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        documents: Mapping[str, Document] | Sequence[Document],
        current_prefix: str | None,
        selection_count: int,
    ) -> None:
        title = _("Move or copy requirements")
        super().__init__(parent, title=title)
        self._plan: RequirementTransferPlan | None = None
        self._documents = self._normalize_documents(documents)
        self._prefixes = [doc.prefix for doc in self._documents]

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        count_label = wx.StaticText(
            self,
            label=_("Selected requirements: {count}").format(count=selection_count),
        )
        main_sizer.Add(count_label, 0, wx.ALL, 10)

        form = wx.FlexGridSizer(0, 2, 6, 8)
        form.AddGrowableCol(1, 1)

        target_label = wx.StaticText(self, label=_("Target document"))
        form.Add(target_label, 0, wx.ALIGN_CENTER_VERTICAL)

        target_choices = [self._format_document(doc) for doc in self._documents]
        self._target_choice = wx.Choice(self, choices=target_choices)
        default_index = self._default_target_index(current_prefix)
        if default_index >= 0:
            self._target_choice.SetSelection(default_index)
        form.Add(self._target_choice, 1, wx.EXPAND)

        mode_label = wx.StaticText(self, label=_("Operation"))
        form.Add(mode_label, 0, wx.ALIGN_CENTER_VERTICAL)

        mode_box = wx.BoxSizer(wx.HORIZONTAL)
        self._copy_radio = wx.RadioButton(self, label=_("Copy"), style=wx.RB_GROUP)
        self._move_radio = wx.RadioButton(self, label=_("Move"))
        self._copy_radio.SetValue(True)
        mode_box.Add(self._copy_radio, 0, wx.RIGHT, 10)
        mode_box.Add(self._move_radio)
        form.Add(mode_box, 0, wx.ALIGN_LEFT)

        form.AddSpacer(0)
        self._reset_revision = wx.CheckBox(
            self, label=_("Reset revision to 1 in copies")
        )
        self._reset_revision.SetValue(True)
        form.Add(self._reset_revision, 0, wx.ALIGN_LEFT)

        form.AddSpacer(0)
        self._switch_checkbox = wx.CheckBox(
            self, label=_("Switch to target document after completion")
        )
        form.Add(self._switch_checkbox, 0, wx.ALIGN_LEFT)

        main_sizer.Add(form, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 10)

        btn_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        if btn_sizer is not None:
            main_sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
            ok_btn = btn_sizer.GetAffirmativeButton()
        else:  # pragma: no cover - minimal wx builds
            ok_btn = None

        self.SetSizer(main_sizer)
        self.SetMinSize((360, 240))
        self._copy_radio.Bind(wx.EVT_RADIOBUTTON, self._on_mode_changed)
        self._move_radio.Bind(wx.EVT_RADIOBUTTON, self._on_mode_changed)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

        if ok_btn is not None and not self._prefixes:
            ok_btn.Enable(False)

        self._on_mode_changed(None)

    @staticmethod
    def _normalize_documents(
        documents: Mapping[str, Document] | Sequence[Document]
    ) -> list[Document]:
        if isinstance(documents, Mapping):
            items: Iterable[Document] = documents.values()
        else:
            items = documents
        normalized = [doc for doc in items if isinstance(doc, Document)]
        normalized.sort(key=lambda doc: doc.prefix)
        return normalized

    @staticmethod
    def _format_document(document: Document) -> str:
        if document.title:
            return f"{document.prefix}: {document.title}"
        return document.prefix

    def _default_target_index(self, current_prefix: str | None) -> int:
        if not self._prefixes:
            return -1
        if current_prefix is None:
            return 0
        for idx, prefix in enumerate(self._prefixes):
            if prefix != current_prefix:
                return idx
        return 0

    def _on_mode_changed(self, _event: wx.Event | None) -> None:
        is_copy = self._copy_radio.GetValue()
        self._reset_revision.Enable(is_copy)
        if not is_copy:
            self._reset_revision.SetValue(False)

    def _on_ok(self, _event: wx.CommandEvent) -> None:
        if not self._prefixes:
            self.EndModal(wx.ID_CANCEL)
            return
        selection = self._target_choice.GetSelection()
        if selection < 0 or selection >= len(self._prefixes):
            wx.MessageBox(_("Select a target document."), _("Error"), wx.ICON_ERROR)
            return
        mode = TransferMode.COPY if self._copy_radio.GetValue() else TransferMode.MOVE
        plan = RequirementTransferPlan(
            target_prefix=self._prefixes[selection],
            mode=mode,
            reset_revision=self._reset_revision.GetValue() if mode is TransferMode.COPY else False,
            switch_to_target=self._switch_checkbox.GetValue(),
        )
        self._plan = plan
        self.EndModal(wx.ID_OK)

    def get_plan(self) -> RequirementTransferPlan | None:
        """Return the selected transfer plan when accepted."""

        return self._plan
