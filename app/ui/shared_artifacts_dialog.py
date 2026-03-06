"""Dialog for managing document-level shared artifacts."""

from __future__ import annotations

from pathlib import Path

import wx

from ..i18n import _
from .helpers import make_help_button

_ARTIFACT_KINDS: tuple[tuple[str, str], ...] = (
    ("general", _("General")),
    ("system_overview", _("System overview")),
    ("tz", _("Technical specification")),
    ("pssa", _("PSSA calculation")),
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
        on_add,
        on_remove,
    ) -> None:
        super().__init__(parent, title=_("Shared artifacts: {prefix}").format(prefix=prefix))
        self._prefix = prefix
        self._on_add = on_add
        self._on_remove = on_remove
        self._artifacts = artifacts

        main = wx.BoxSizer(wx.VERTICAL)
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
        self._remove_btn = wx.Button(self, label=_("Remove"))
        self._close_btn = wx.Button(self, id=wx.ID_CLOSE, label=_("Close"))
        actions.Add(self._add_btn, 0, wx.BOTTOM, 5)
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
        self.SetMinSize((780, 380))

        self._add_btn.Bind(wx.EVT_BUTTON, self._on_add_click)
        self._remove_btn.Bind(wx.EVT_BUTTON, self._on_remove_click)
        self._close_btn.Bind(wx.EVT_BUTTON, lambda _evt: self.EndModal(wx.ID_CLOSE))
        self._list.Bind(wx.EVT_SIZE, lambda evt: (evt.Skip(), self._autosize_columns()))

        self._refresh()

    def _autosize_columns(self) -> None:
        width = max(300, self._list.GetClientSize().width)
        self._list.SetColumnWidth(0, max(180, int(width * 0.30)))
        self._list.SetColumnWidth(1, max(120, int(width * 0.16)))
        self._list.SetColumnWidth(2, max(180, int(width * 0.38)))
        self._list.SetColumnWidth(3, max(80, int(width * 0.12)))

    def _kind_label(self, kind: str) -> str:
        for value, label in _ARTIFACT_KINDS:
            if value == kind:
                return label
        return kind

    def _refresh(self) -> None:
        self._list.Freeze()
        try:
            self._list.DeleteAllItems()
            for artifact in self._artifacts:
                idx = self._list.InsertItem(self._list.GetItemCount(), getattr(artifact, "title", ""))
                self._list.SetItem(idx, 1, self._kind_label(str(getattr(artifact, "kind", ""))))
                self._list.SetItem(idx, 2, str(getattr(artifact, "path", "")))
                export_flag = "✓" if bool(getattr(artifact, "include_in_export", True)) else ""
                self._list.SetItem(idx, 3, export_flag)
                self._list.SetItemData(idx, idx)
        finally:
            self._list.Thaw()
        self._remove_btn.Enable(bool(self._artifacts))
        self._autosize_columns()

    def _show_add_form(self) -> tuple[str, str, str, str, bool, list[str]] | None:
        with wx.FileDialog(
            self,
            _("Select shared artifact"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as file_dialog:
            if file_dialog.ShowModal() != wx.ID_OK:
                return None
            source_path = file_dialog.GetPath()

        default_title = Path(source_path).stem
        title = default_title
        with wx.TextEntryDialog(self, _("Artifact title"), _("Shared artifact"), value=default_title) as title_dialog:
            if title_dialog.ShowModal() == wx.ID_OK:
                title = title_dialog.GetValue().strip() or default_title

        kind_labels = [label for _, label in _ARTIFACT_KINDS]
        with wx.SingleChoiceDialog(self, _("Artifact type"), _("Shared artifact"), choices=kind_labels) as kind_dialog:
            if kind_dialog.ShowModal() != wx.ID_OK:
                return None
            selection = kind_dialog.GetSelection()
            kind = _ARTIFACT_KINDS[selection][0] if 0 <= selection < len(_ARTIFACT_KINDS) else "general"

        note = ""
        with wx.TextEntryDialog(self, _("Optional note"), _("Shared artifact")) as note_dialog:
            if note_dialog.ShowModal() == wx.ID_OK:
                note = note_dialog.GetValue()

        return source_path, kind, title, note, True, []

    def _on_add_click(self, _event: wx.CommandEvent) -> None:
        form = self._show_add_form()
        if form is None:
            return
        source_path, kind, title, note, include_in_export, tags = form
        try:
            artifact = self._on_add(
                self._prefix,
                source_path,
                kind=kind,
                title=title,
                note=note,
                include_in_export=include_in_export,
                tags=tags,
            )
        except Exception as exc:  # pragma: no cover - UI safeguard
            wx.MessageBox(str(exc), _("Error"), style=wx.OK | wx.ICON_ERROR)
            return
        self._artifacts.append(artifact)
        self._refresh()

    def _on_remove_click(self, _event: wx.CommandEvent) -> None:
        selected = self._list.GetFirstSelected()
        if selected < 0 or selected >= len(self._artifacts):
            return
        artifact = self._artifacts[selected]
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
            del self._artifacts[selected]
            self._refresh()


__all__ = ["SharedArtifactsDialog"]
