"""Standalone window hosting the requirement editor outside the main frame."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import wx

from ..confirm import confirm
from ..core.document_store import LabelDef
from ..core.model import Requirement
from ..i18n import _
from .editor_panel import EditorPanel


class DetachedEditorFrame(wx.Frame):
    """Floating frame containing :class:`EditorPanel` for detached editing."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        requirement: Requirement,
        doc_prefix: str,
        directory: Path,
        labels: list[LabelDef],
        allow_freeform: bool,
        on_save: Callable[["DetachedEditorFrame"], bool],
        on_close: Callable[["DetachedEditorFrame"], None] | None = None,
    ) -> None:
        """Create frame initialized with ``requirement`` contents."""

        title = self._format_title(requirement, doc_prefix)
        super().__init__(parent, title=title)
        self._on_save = on_save
        self._on_close = on_close
        self._closing_via_cancel = False
        self.doc_prefix = doc_prefix
        self.requirement_id = requirement.id
        self.directory = Path(directory)
        self._allow_freeform = allow_freeform
        self._labels: list[LabelDef] = list(labels)

        self.editor = EditorPanel(
            self,
            on_save=self._handle_save,
            on_discard=self._handle_cancel,
        )
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.editor, 1, wx.EXPAND)
        self.SetSizer(sizer)

        self.editor.set_directory(self.directory)
        self.editor.update_labels_list(self._labels, self._allow_freeform)
        self.editor.load(requirement)

        self.Bind(wx.EVT_CLOSE, self._on_close_window)
        self.SetSize((900, 700))
        self.CentreOnParent()

    # ------------------------------------------------------------------
    @property
    def key(self) -> tuple[str, int]:
        """Return dictionary key representing this editor instance."""

        return self.doc_prefix, self.requirement_id

    def reload(
        self,
        requirement: Requirement,
        directory: Path,
        labels: list[LabelDef],
        allow_freeform: bool,
    ) -> None:
        """Load ``requirement`` replacing current contents."""

        self.directory = Path(directory)
        self.doc_prefix = requirement.doc_prefix or self.doc_prefix
        self.requirement_id = requirement.id
        self._labels = list(labels)
        self._allow_freeform = allow_freeform
        self.editor.set_directory(self.directory)
        self.editor.update_labels_list(self._labels, self._allow_freeform)
        self.editor.load(requirement)
        self._update_title(requirement)

    # ------------------------------------------------------------------
    def _handle_save(self) -> None:
        """Delegate saving to owning frame and keep focus on success."""

        if self._on_save(self):
            # Reload handled by callback; nothing else to do on success.
            return

    def _handle_cancel(self) -> bool:
        """Close the frame when the editor requests to discard changes."""

        self._closing_via_cancel = True
        closed = self.Close()
        if not closed:
            self._closing_via_cancel = False
            return False
        return True

    def _on_close_window(self, event: wx.CloseEvent) -> None:
        """Confirm closing when editor has unsaved changes."""

        if self._closing_via_cancel:
            self._closing_via_cancel = False
            if self._on_close:
                self._on_close(self)
            event.Skip()
            return

        if self.editor.is_dirty():
            if not confirm(_("Discard unsaved changes?")):
                event.Veto()
                return
        if self._on_close:
            self._on_close(self)
        event.Skip()

    def _update_title(self, requirement: Requirement) -> None:
        """Refresh window title based on ``requirement`` metadata."""

        self.SetTitle(self._format_title(requirement, self.doc_prefix))

    @staticmethod
    def _format_title(requirement: Requirement, doc_prefix: str) -> str:
        """Return localized title string for ``requirement``."""

        rid = getattr(requirement, "rid", "") or f"{doc_prefix}-{requirement.id:04d}".strip("-")
        base = requirement.title.strip() if getattr(requirement, "title", "") else ""
        if base:
            return _("Requirement {rid}: {title}").format(rid=rid, title=base)
        return _("Requirement {rid}").format(rid=rid)

