"""Dialog for managing document-level shared artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import wx

from ..i18n import _
from .helpers import make_help_button

_ARTIFACT_KINDS: tuple[tuple[str, str], ...] = (
    ("all", _("All types")),
    ("general", _("General")),
    ("system_overview", _("System overview")),
    ("tz", _("Technical specification")),
    ("pssa", _("PSSA calculation")),
)


@dataclass(slots=True)
class _ArtifactFormResult:
    kind: str
    title: str
    note: str
    include_in_export: bool
    tags: list[str]


class SharedArtifactEditDialog(wx.Dialog):
    """Edit metadata of a shared artifact (without changing file path)."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        title: str,
        kind: str,
        note: str,
        include_in_export: bool,
        tags: list[str],
    ) -> None:
        super().__init__(parent, title=_("Shared artifact"))
        main = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, hgap=8, vgap=8)
        grid.AddGrowableCol(1, 1)

        grid.Add(wx.StaticText(self, label=_("Artifact title")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._title_ctrl = wx.TextCtrl(self, value=title)
        grid.Add(self._title_ctrl, 1, wx.EXPAND)

        grid.Add(wx.StaticText(self, label=_("Artifact type")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._kind_values = [value for value, _ in _ARTIFACT_KINDS if value != "all"]
        kind_labels = [label for value, label in _ARTIFACT_KINDS if value != "all"]
        self._kind_choice = wx.Choice(self, choices=kind_labels)
        selection = 0
        if kind in self._kind_values:
            selection = self._kind_values.index(kind)
        self._kind_choice.SetSelection(selection)
        grid.Add(self._kind_choice, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label=_("Optional note")), 0, wx.ALIGN_TOP)
        self._note_ctrl = wx.TextCtrl(self, value=note, style=wx.TE_MULTILINE)
        grid.Add(self._note_ctrl, 1, wx.EXPAND)

        grid.Add(wx.StaticText(self, label=_("Tags (comma-separated)")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._tags_ctrl = wx.TextCtrl(self, value=", ".join(tags))
        grid.Add(self._tags_ctrl, 1, wx.EXPAND)

        self._include_export = wx.CheckBox(self, label=_("Include in export preface"))
        self._include_export.SetValue(include_in_export)

        main.Add(grid, 1, wx.ALL | wx.EXPAND, 10)
        main.Add(self._include_export, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        if buttons:
            main.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizer(main)
        self.SetMinSize((480, 320))

    def get_result(self) -> _ArtifactFormResult:
        kind_idx = self._kind_choice.GetSelection()
        kind = self._kind_values[kind_idx] if 0 <= kind_idx < len(self._kind_values) else "general"
        title = self._title_ctrl.GetValue().strip()
        note = self._note_ctrl.GetValue()
        tags = [item.strip() for item in self._tags_ctrl.GetValue().split(",") if item.strip()]
        return _ArtifactFormResult(
            kind=kind,
            title=title,
            note=note,
            include_in_export=self._include_export.GetValue(),
            tags=tags,
        )


class SharedArtifactsDialog(wx.Dialog):
    """Manage shared artifacts stored on document level."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        prefix: str,
        root: Path,
        artifacts: list[object],
        on_add: Any,
        on_remove: Any,
        on_update: Any,
    ) -> None:
        super().__init__(parent, title=_("Shared artifacts: {prefix}").format(prefix=prefix))
        self._prefix = prefix
        self._document_root = root / prefix
        self._on_add = on_add
        self._on_remove = on_remove
        self._on_update = on_update
        self._artifacts = artifacts
        self._filtered_indices: list[int] = []

        main = wx.BoxSizer(wx.VERTICAL)

        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        toolbar.Add(wx.StaticText(self, label=_("Filter by type")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._filter_choice = wx.Choice(self, choices=[label for _value, label in _ARTIFACT_KINDS])
        self._filter_choice.SetSelection(0)
        toolbar.Add(self._filter_choice, 0, wx.RIGHT, 10)
        toolbar.AddStretchSpacer(1)
        self._open_file_btn = wx.Button(self, label=_("Open file"))
        toolbar.Add(self._open_file_btn, 0)
        main.Add(toolbar, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 10)

        list_row = wx.BoxSizer(wx.HORIZONTAL)
        self._list = wx.ListCtrl(
            self,
            style=wx.LC_REPORT | wx.BORDER_SUNKEN | wx.LC_SINGLE_SEL,
        )
        self._list.InsertColumn(0, _("Title"))
        self._list.InsertColumn(1, _("Type"))
        self._list.InsertColumn(2, _("File"))
        self._list.InsertColumn(3, _("Export"))
        list_row.Add(self._list, 1, wx.EXPAND | wx.RIGHT, 10)

        actions = wx.BoxSizer(wx.VERTICAL)
        self._add_btn = wx.Button(self, label=_("Add"))
        self._edit_btn = wx.Button(self, label=_("Edit"))
        self._toggle_export_btn = wx.Button(self, label=_("Toggle export"))
        self._remove_btn = wx.Button(self, label=_("Remove"))
        self._close_btn = wx.Button(self, id=wx.ID_CLOSE, label=_("Close"))
        actions.Add(self._add_btn, 0, wx.BOTTOM, 5)
        actions.Add(self._edit_btn, 0, wx.BOTTOM, 5)
        actions.Add(self._toggle_export_btn, 0, wx.BOTTOM, 5)
        actions.Add(self._remove_btn, 0, wx.BOTTOM, 5)
        actions.Add(self._close_btn, 0)
        list_row.Add(actions, 0, wx.ALIGN_TOP)

        main.Add(list_row, 1, wx.ALL | wx.EXPAND, 10)

        hint = _(
            "Shared artifacts are available to all requirements in this data module."
            " Use types to classify documents such as system overview, TZ and PSSA."
        )
        hint_row = wx.BoxSizer(wx.HORIZONTAL)
        hint_row.Add(wx.StaticText(self, label=hint), 1, wx.ALIGN_CENTER_VERTICAL)
        hint_row.Add(
            make_help_button(self, hint, dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            6,
        )
        main.Add(hint_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        self.SetSizer(main)
        self.SetMinSize((860, 420))

        self._add_btn.Bind(wx.EVT_BUTTON, self._on_add_click)
        self._edit_btn.Bind(wx.EVT_BUTTON, self._on_edit_click)
        self._toggle_export_btn.Bind(wx.EVT_BUTTON, self._on_toggle_export_click)
        self._remove_btn.Bind(wx.EVT_BUTTON, self._on_remove_click)
        self._open_file_btn.Bind(wx.EVT_BUTTON, self._on_open_file_click)
        self._close_btn.Bind(wx.EVT_BUTTON, lambda _evt: self.EndModal(wx.ID_CLOSE))
        self._filter_choice.Bind(wx.EVT_CHOICE, lambda _evt: self._refresh())
        self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_edit_click)
        self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda _evt: self._sync_buttons_state())
        self._list.Bind(wx.EVT_SIZE, lambda evt: (evt.Skip(), self._autosize_columns()))

        self._refresh()

    def _autosize_columns(self) -> None:
        width = max(320, self._list.GetClientSize().width)
        self._list.SetColumnWidth(0, max(180, int(width * 0.28)))
        self._list.SetColumnWidth(1, max(130, int(width * 0.18)))
        self._list.SetColumnWidth(2, max(190, int(width * 0.38)))
        self._list.SetColumnWidth(3, max(85, int(width * 0.12)))

    def _kind_label(self, kind: str) -> str:
        for value, label in _ARTIFACT_KINDS:
            if value == kind:
                return label
        return kind

    def _current_filter(self) -> str:
        idx = self._filter_choice.GetSelection()
        if 0 <= idx < len(_ARTIFACT_KINDS):
            return _ARTIFACT_KINDS[idx][0]
        return "all"

    def _refresh(self) -> None:
        self._filtered_indices = []
        filter_kind = self._current_filter()
        self._list.Freeze()
        try:
            self._list.DeleteAllItems()
            for artifact_index, artifact in enumerate(self._artifacts):
                kind = str(getattr(artifact, "kind", "general"))
                if filter_kind != "all" and kind != filter_kind:
                    continue
                self._filtered_indices.append(artifact_index)
                idx = self._list.InsertItem(self._list.GetItemCount(), getattr(artifact, "title", ""))
                self._list.SetItem(idx, 1, self._kind_label(kind))
                self._list.SetItem(idx, 2, str(getattr(artifact, "path", "")))
                export_flag = "✓" if bool(getattr(artifact, "include_in_export", True)) else ""
                self._list.SetItem(idx, 3, export_flag)
                self._list.SetItemData(idx, artifact_index)
        finally:
            self._list.Thaw()
        self._autosize_columns()
        self._sync_buttons_state()

    def _sync_buttons_state(self) -> None:
        selected = self._selected_artifact()
        enabled = selected is not None
        self._remove_btn.Enable(enabled)
        self._edit_btn.Enable(enabled)
        self._toggle_export_btn.Enable(enabled)
        self._open_file_btn.Enable(enabled)

    def _selected_artifact(self) -> tuple[int, object] | None:
        selected = self._list.GetFirstSelected()
        if selected < 0 or selected >= len(self._filtered_indices):
            return None
        artifact_index = self._filtered_indices[selected]
        if artifact_index < 0 or artifact_index >= len(self._artifacts):
            return None
        return artifact_index, self._artifacts[artifact_index]

    def _show_add_form(self) -> tuple[str, _ArtifactFormResult] | None:
        with wx.FileDialog(
            self,
            _("Select shared artifact"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as file_dialog:
            if file_dialog.ShowModal() != wx.ID_OK:
                return None
            source_path = file_dialog.GetPath()

        default_title = Path(source_path).stem
        edit = SharedArtifactEditDialog(
            self,
            title=default_title,
            kind="general",
            note="",
            include_in_export=True,
            tags=[],
        )
        try:
            if edit.ShowModal() != wx.ID_OK:
                return None
            result = edit.get_result()
        finally:
            edit.Destroy()
        if not result.title:
            result.title = default_title
        return source_path, result

    def _on_add_click(self, _event: wx.CommandEvent) -> None:
        form = self._show_add_form()
        if form is None:
            return
        source_path, result = form
        try:
            artifact = self._on_add(
                self._prefix,
                source_path,
                kind=result.kind,
                title=result.title,
                note=result.note,
                include_in_export=result.include_in_export,
                tags=result.tags,
            )
        except Exception as exc:  # pragma: no cover - UI safeguard
            wx.MessageBox(str(exc), _("Error"), style=wx.OK | wx.ICON_ERROR)
            return
        self._artifacts.append(artifact)
        self._refresh()

    def _on_edit_click(self, _event: wx.Event) -> None:
        selected = self._selected_artifact()
        if selected is None:
            return
        artifact_index, artifact = selected
        edit = SharedArtifactEditDialog(
            self,
            title=str(getattr(artifact, "title", "")),
            kind=str(getattr(artifact, "kind", "general")),
            note=str(getattr(artifact, "note", "")),
            include_in_export=bool(getattr(artifact, "include_in_export", True)),
            tags=list(getattr(artifact, "tags", [])),
        )
        try:
            if edit.ShowModal() != wx.ID_OK:
                return
            result = edit.get_result()
        finally:
            edit.Destroy()
        if not result.title:
            result.title = str(getattr(artifact, "title", ""))
        updated = self._on_update(
            self._prefix,
            str(getattr(artifact, "id", "")),
            kind=result.kind,
            title=result.title,
            note=result.note,
            include_in_export=result.include_in_export,
            tags=result.tags,
        )
        self._artifacts[artifact_index] = updated
        self._refresh()

    def _on_toggle_export_click(self, _event: wx.CommandEvent) -> None:
        selected = self._selected_artifact()
        if selected is None:
            return
        artifact_index, artifact = selected
        updated = self._on_update(
            self._prefix,
            str(getattr(artifact, "id", "")),
            include_in_export=not bool(getattr(artifact, "include_in_export", True)),
        )
        self._artifacts[artifact_index] = updated
        self._refresh()

    def _on_open_file_click(self, _event: wx.CommandEvent) -> None:
        selected = self._selected_artifact()
        if selected is None:
            return
        _artifact_index, artifact = selected
        path = str(getattr(artifact, "path", "")).strip()
        if not path:
            return
        candidate = (self._document_root / path).resolve()
        launch_path = str(candidate if candidate.exists() else Path(path))
        if not wx.LaunchDefaultApplication(launch_path):
            wx.MessageBox(
                _("Unable to open file with the default application."),
                _("Error"),
                style=wx.OK | wx.ICON_ERROR,
            )

    def _on_remove_click(self, _event: wx.CommandEvent) -> None:
        selected = self._selected_artifact()
        if selected is None:
            return
        artifact_index, artifact = selected
        path = str(getattr(artifact, "path", ""))
        with wx.MessageDialog(
            self,
            _("Delete selected shared artifact metadata?"),
            _("Shared artifact"),
            style=wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        ) as confirm:
            if confirm.ShowModal() != wx.ID_YES:
                return
        remove_file = False
        with wx.MessageDialog(
            self,
            _("Also delete artifact file from disk?\n{path}").format(path=path),
            _("Shared artifact"),
            style=wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        ) as confirm_file:
            if confirm_file.ShowModal() == wx.ID_YES:
                remove_file = True
        removed = self._on_remove(
            self._prefix,
            str(getattr(artifact, "id", "")),
            delete_file=remove_file,
        )
        if removed:
            del self._artifacts[artifact_index]
            self._refresh()


__all__ = ["SharedArtifactsDialog", "SharedArtifactEditDialog"]
