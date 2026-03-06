"""Dialog for managing document-level shared artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import wx

from ..i18n import _
from .helpers import make_help_button


@dataclass(slots=True)
class _ArtifactFormResult:
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
        note: str,
        include_in_export: bool,
        tags: list[str],
    ) -> None:
        super().__init__(parent, title=_("Shared artifact"))
        main = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, hgap=8, vgap=8)
        grid.AddGrowableCol(1, 1)
        grid.AddGrowableRow(1, 1)

        title_label = wx.StaticText(self, label=_("Artifact title"))
        title_label.SetToolTip(_("Display name shown in shared artifacts list and exports."))
        grid.Add(title_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self._title_ctrl = wx.TextCtrl(self, value=title)
        self._title_ctrl.SetToolTip(_("Display name shown in shared artifacts list and exports."))
        grid.Add(self._title_ctrl, 1, wx.EXPAND)

        note_label = wx.StaticText(self, label=_("Optional note"))
        note_label.SetToolTip(_("Short comment about this artifact, for example status or owner."))
        grid.Add(note_label, 0, wx.ALIGN_TOP)
        self._note_ctrl = wx.TextCtrl(self, value=note, style=wx.TE_MULTILINE)
        self._note_ctrl.SetMinSize((-1, 140))
        self._note_ctrl.SetToolTip(_("Short comment about this artifact, for example status or owner."))
        grid.Add(self._note_ctrl, 1, wx.EXPAND)

        tags_label = wx.StaticText(self, label=_("Tags (comma-separated)"))
        tags_label.SetToolTip(_("Keywords to simplify searching and filtering in exports."))
        grid.Add(tags_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self._tags_ctrl = wx.TextCtrl(self, value=", ".join(tags))
        self._tags_ctrl.SetToolTip(_("Keywords to simplify searching and filtering in exports."))
        grid.Add(self._tags_ctrl, 1, wx.EXPAND)

        self._include_export = wx.CheckBox(self, label=_("Include in export introduction"))
        self._include_export.SetValue(include_in_export)
        self._include_export.SetToolTip(
            _("Adds artifact content to the generated export introduction section.")
        )

        main.Add(grid, 1, wx.ALL | wx.EXPAND, 10)
        main.Add(self._include_export, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        if buttons:
            main.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizer(main)
        self.SetMinSize((560, 420))
        self.SetSize((680, 520))

    def get_result(self) -> _ArtifactFormResult:
        title = self._title_ctrl.GetValue().strip()
        note = self._note_ctrl.GetValue()
        tags = [item.strip() for item in self._tags_ctrl.GetValue().split(",") if item.strip()]
        return _ArtifactFormResult(
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

        main = wx.BoxSizer(wx.VERTICAL)

        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        toolbar.AddStretchSpacer(1)
        self._open_file_btn = wx.Button(self, label=_("Open file"))
        self._open_file_btn.SetToolTip(_("Open selected file using the system default application."))
        toolbar.Add(self._open_file_btn, 0)
        main.Add(toolbar, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 10)

        list_row = wx.BoxSizer(wx.HORIZONTAL)
        self._list = wx.ListCtrl(
            self,
            style=wx.LC_REPORT | wx.BORDER_SUNKEN | wx.LC_SINGLE_SEL,
        )
        self._list.InsertColumn(0, _("Title"))
        self._list.InsertColumn(1, _("File"))
        self._list.InsertColumn(2, _("Export"))
        list_row.Add(self._list, 1, wx.EXPAND | wx.RIGHT, 10)

        actions = wx.BoxSizer(wx.VERTICAL)
        self._add_btn = wx.Button(self, label=_("Add"))
        self._edit_btn = wx.Button(self, label=_("Edit"))
        self._toggle_export_btn = wx.Button(self, label=_("Toggle export"))
        self._remove_btn = wx.Button(self, label=_("Remove"))
        self._close_btn = wx.Button(self, id=wx.ID_CLOSE, label=_("Close"))

        self._add_btn.SetToolTip(_("Select and register a new shared artifact file."))
        self._edit_btn.SetToolTip(_("Edit metadata of the selected shared artifact."))
        self._toggle_export_btn.SetToolTip(_("Enable or disable inclusion in export introduction."))
        self._remove_btn.SetToolTip(_("Remove metadata entry for the selected shared artifact."))
        self._close_btn.SetToolTip(_("Close this dialog."))

        actions.Add(self._add_btn, 0, wx.BOTTOM, 5)
        actions.Add(self._edit_btn, 0, wx.BOTTOM, 5)
        actions.Add(self._toggle_export_btn, 0, wx.BOTTOM, 5)
        actions.Add(self._remove_btn, 0, wx.BOTTOM, 5)
        actions.Add(self._close_btn, 0)
        list_row.Add(actions, 0, wx.ALIGN_TOP)

        main.Add(list_row, 1, wx.ALL | wx.EXPAND, 10)

        hint = _(
            "Shared artifacts are available to all requirements in this data module."
            " Attach key source files here so they can be reused in reviews and exports."
        )
        hint_row = wx.BoxSizer(wx.HORIZONTAL)
        hint_label = wx.StaticText(self, label=hint)
        hint_label.SetToolTip(hint)
        hint_row.Add(hint_label, 1, wx.ALIGN_CENTER_VERTICAL)
        hint_row.Add(
            make_help_button(self, hint, dialog_parent=self),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            6,
        )
        main.Add(hint_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        self.SetSizer(main)
        self.SetMinSize((980, 560))
        self.SetSize((1120, 680))

        self._add_btn.Bind(wx.EVT_BUTTON, self._on_add_click)
        self._edit_btn.Bind(wx.EVT_BUTTON, self._on_edit_click)
        self._toggle_export_btn.Bind(wx.EVT_BUTTON, self._on_toggle_export_click)
        self._remove_btn.Bind(wx.EVT_BUTTON, self._on_remove_click)
        self._open_file_btn.Bind(wx.EVT_BUTTON, self._on_open_file_click)
        self._close_btn.Bind(wx.EVT_BUTTON, lambda _evt: self.EndModal(wx.ID_CLOSE))
        self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_edit_click)
        self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda _evt: self._sync_buttons_state())
        self._list.Bind(wx.EVT_SIZE, lambda evt: (evt.Skip(), self._autosize_columns()))

        self._refresh()

    def _autosize_columns(self) -> None:
        width = max(420, self._list.GetClientSize().width)
        self._list.SetColumnWidth(0, max(220, int(width * 0.36)))
        self._list.SetColumnWidth(1, max(230, int(width * 0.52)))
        self._list.SetColumnWidth(2, max(90, int(width * 0.12)))

    def _refresh(self) -> None:
        self._list.Freeze()
        try:
            self._list.DeleteAllItems()
            for artifact_index, artifact in enumerate(self._artifacts):
                idx = self._list.InsertItem(self._list.GetItemCount(), getattr(artifact, "title", ""))
                self._list.SetItem(idx, 1, str(getattr(artifact, "path", "")))
                export_flag = "✓" if bool(getattr(artifact, "include_in_export", True)) else ""
                self._list.SetItem(idx, 2, export_flag)
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
        if selected < 0:
            return None
        artifact_index = self._list.GetItemData(selected)
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
