"""Dialog for managing document-level shared artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import wx

from ..config import ConfigManager
from ..i18n import _
from .helpers import make_help_button


TEXT_EXPORT_SUFFIXES = frozenset({".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".log", ".ini"})


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
        config: ConfigManager | None = None,
    ) -> None:
        super().__init__(
            parent,
            title=_("Shared artifacts: {prefix}").format(prefix=prefix),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX,
        )
        self._prefix = prefix
        self._document_root = root / prefix
        self._on_add = on_add
        self._on_remove = on_remove
        self._on_update = on_update
        self._artifacts = artifacts
        self._config = config
        self._column_widths_loaded = False

        main = wx.BoxSizer(wx.VERTICAL)

        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        self._add_btn = wx.Button(self, label=_("Add file"))
        self._add_btn.SetToolTip(_("Select and register a new shared artifact file."))
        toolbar.Add(self._add_btn, 0)
        toolbar.AddStretchSpacer(1)
        main.Add(toolbar, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 10)

        self._list = wx.ListCtrl(
            self,
            style=wx.LC_REPORT | wx.BORDER_SUNKEN | wx.LC_SINGLE_SEL,
        )
        self._list.InsertColumn(0, _("Title"))
        self._list.InsertColumn(1, _("File"))
        self._list.InsertColumn(2, _("File size"))
        self._list.InsertColumn(3, _("Tags"))
        self._list.InsertColumn(4, _("Export"))

        main.Add(self._list, 1, wx.ALL | wx.EXPAND, 10)

        close_row = wx.BoxSizer(wx.HORIZONTAL)
        close_row.AddStretchSpacer(1)
        self._close_btn = wx.Button(self, id=wx.ID_CLOSE, label=_("Close"))
        self._close_btn.SetToolTip(_("Close this dialog."))
        close_row.Add(self._close_btn, 0)
        main.Add(close_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        hint = _(
            "Shared artifacts are available to all requirements in this document."
            " Attach key source files here so they can be reused in reviews and exports."
            " For export preface inclusion use UTF-8 text files (.txt, .md, .csv, .json, .yaml, .yml, .log, .ini)."
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
        if self._config is not None:
            self._config.restore_shared_artifacts_dialog_geometry(self)
        else:
            self.SetSize((1120, 680))

        self._add_btn.Bind(wx.EVT_BUTTON, self._on_add_click)
        self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_edit_click)
        self._list.Bind(wx.EVT_SIZE, self._on_list_resized)
        self._list.Bind(wx.EVT_LIST_COL_END_DRAG, self._on_column_resized)
        self._list.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self._close_btn.Bind(wx.EVT_BUTTON, lambda _evt: self.EndModal(wx.ID_CLOSE))
        self.Bind(wx.EVT_CLOSE, self._on_close)

        self._refresh()

    def _load_persisted_column_widths(self) -> bool:
        if self._config is None:
            return False
        loaded_any = False
        for index in range(5):
            width = self._config.get_shared_artifacts_column_width(index, default=-1)
            if width > 0:
                self._list.SetColumnWidth(index, width)
                loaded_any = True
        self._column_widths_loaded = loaded_any
        return loaded_any

    def _persist_geometry_and_columns(self) -> None:
        if self._config is None:
            return
        self._config.save_shared_artifacts_dialog_geometry(self)
        for index in range(5):
            width = self._list.GetColumnWidth(index)
            if width > 0:
                self._config.set_shared_artifacts_column_width(index, width)
        self._config.flush()

    def _on_list_resized(self, event: wx.SizeEvent) -> None:
        event.Skip()
        if not self._column_widths_loaded:
            if not self._load_persisted_column_widths():
                self._autosize_columns()

    def _on_column_resized(self, event: wx.ListEvent) -> None:
        event.Skip()
        self._column_widths_loaded = True

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._persist_geometry_and_columns()
        event.Skip()

    def _autosize_columns(self) -> None:
        width = max(420, self._list.GetClientSize().width)
        self._list.SetColumnWidth(0, max(190, int(width * 0.23)))
        self._list.SetColumnWidth(1, max(250, int(width * 0.35)))
        self._list.SetColumnWidth(2, max(110, int(width * 0.12)))
        self._list.SetColumnWidth(3, max(180, int(width * 0.20)))
        self._list.SetColumnWidth(4, max(90, int(width * 0.10)))

    def _resolve_artifact_file(self, artifact: object) -> Path | None:
        path = str(getattr(artifact, "path", "")).strip()
        if not path:
            return None
        return (self._document_root / path).resolve()

    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(max(0, size_bytes))
        for idx, unit in enumerate(units):
            is_last = idx == len(units) - 1
            if size < 1024 or is_last:
                if unit == "B":
                    return f"{int(size)} {unit}"
                return f"{size:.1f} {unit}"
            size /= 1024

    def _refresh(self) -> None:
        self._list.Freeze()
        try:
            self._list.DeleteAllItems()
            for artifact_index, artifact in enumerate(self._artifacts):
                idx = self._list.InsertItem(self._list.GetItemCount(), getattr(artifact, "title", ""))
                self._list.SetItem(idx, 1, str(getattr(artifact, "path", "")))
                candidate = self._resolve_artifact_file(artifact)
                size_label = _("Missing")
                if candidate is not None and candidate.exists() and candidate.is_file():
                    size_label = self._format_file_size(candidate.stat().st_size)
                self._list.SetItem(idx, 2, size_label)
                tags = getattr(artifact, "tags", [])
                tags_label = ", ".join(str(tag).strip() for tag in tags if str(tag).strip())
                self._list.SetItem(idx, 3, tags_label)
                export_flag = "✓" if bool(getattr(artifact, "include_in_export", True)) else ""
                self._list.SetItem(idx, 4, export_flag)
                self._list.SetItemData(idx, artifact_index)
        finally:
            self._list.Thaw()
        self._autosize_columns()

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
            wildcard=_("Text files (*.txt;*.md;*.csv;*.json;*.yaml;*.yml;*.log;*.ini)|*.txt;*.md;*.csv;*.json;*.yaml;*.yml;*.log;*.ini|All files (*.*)|*.*"),
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
        source = Path(source_path)
        if result.include_in_export and source.suffix.lower() not in TEXT_EXPORT_SUFFIXES:
            wx.MessageBox(
                _(
                    "This file type cannot be added to export introduction. "
                    "Allowed text formats: .txt, .md, .csv, .json, .yaml, .yml, .log, .ini"
                ),
                _("Shared artifact"),
                style=wx.OK | wx.ICON_WARNING,
            )
            return
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
        will_include = not bool(getattr(artifact, "include_in_export", True))
        if will_include:
            candidate = self._resolve_artifact_file(artifact)
            suffix = candidate.suffix.lower() if candidate is not None else ""
            if suffix not in TEXT_EXPORT_SUFFIXES:
                wx.MessageBox(
                    _(
                        "Only text artifacts can be included in export introduction. "
                        "Allowed formats: .txt, .md, .csv, .json, .yaml, .yml, .log, .ini"
                    ),
                    _("Shared artifact"),
                    style=wx.OK | wx.ICON_WARNING,
                )
                return
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
        candidate = self._resolve_artifact_file(artifact)
        if candidate is None:
            return
        if not candidate.exists() or not candidate.is_file():
            wx.MessageBox(
                _("File is missing on disk."),
                _("Shared artifact"),
                style=wx.OK | wx.ICON_WARNING,
            )
            return
        if not wx.LaunchDefaultApplication(str(candidate)):
            wx.MessageBox(
                _("Unable to open file with the default application."),
                _("Error"),
                style=wx.OK | wx.ICON_ERROR,
            )

    def _on_open_directory_click(self, _event: wx.CommandEvent) -> None:
        selected = self._selected_artifact()
        if selected is None:
            return
        _artifact_index, artifact = selected
        candidate = self._resolve_artifact_file(artifact)
        if candidate is None:
            return
        directory = candidate.parent
        if not directory.exists() or not directory.is_dir():
            wx.MessageBox(
                _("Containing directory is missing on disk."),
                _("Shared artifact"),
                style=wx.OK | wx.ICON_WARNING,
            )
            return
        if not wx.LaunchDefaultApplication(str(directory)):
            wx.MessageBox(
                _("Unable to open containing directory with the default application."),
                _("Error"),
                style=wx.OK | wx.ICON_ERROR,
            )

    def _context_menu_position_to_item_index(self, event: wx.ContextMenuEvent) -> int:
        pos = event.GetPosition()
        if pos.x == -1 and pos.y == -1:
            return self._list.GetFirstSelected()
        local_pos = self._list.ScreenToClient(pos)
        item_index, _flags = self._list.HitTest(local_pos)
        return item_index

    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
        item_index = self._context_menu_position_to_item_index(event)
        if item_index >= 0:
            self._list.Select(item_index)
            self._list.Focus(item_index)
        selected = self._selected_artifact()

        menu = wx.Menu()
        open_item = menu.Append(wx.ID_ANY, _("Open file"))
        open_dir_item = menu.Append(wx.ID_ANY, _("Open containing directory"))
        edit_item = menu.Append(wx.ID_ANY, _("Edit"))
        toggle_export_item = menu.Append(
            wx.ID_ANY,
            _("Remove from export")
            if selected is not None and bool(getattr(selected[1], "include_in_export", True))
            else _("Include in export"),
        )
        remove_item = menu.Append(wx.ID_ANY, _("Remove"))

        if selected is None:
            open_item.Enable(False)
            open_dir_item.Enable(False)
            edit_item.Enable(False)
            toggle_export_item.Enable(False)
            remove_item.Enable(False)
        else:
            _artifact_index, artifact = selected
            candidate = self._resolve_artifact_file(artifact)
            if candidate is None or not candidate.exists() or not candidate.is_file():
                open_item.Enable(False)
            if candidate is None or not candidate.parent.exists() or not candidate.parent.is_dir():
                open_dir_item.Enable(False)

        menu.Bind(wx.EVT_MENU, self._on_open_file_click, open_item)
        menu.Bind(wx.EVT_MENU, self._on_open_directory_click, open_dir_item)
        menu.Bind(wx.EVT_MENU, self._on_edit_click, edit_item)
        menu.Bind(wx.EVT_MENU, self._on_toggle_export_click, toggle_export_item)
        menu.Bind(wx.EVT_MENU, self._on_remove_click, remove_item)

        self._list.PopupMenu(menu)
        menu.Destroy()

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
