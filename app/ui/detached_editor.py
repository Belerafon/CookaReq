"""Standalone window hosting the requirement editor outside the main frame."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import wx

from ..confirm import confirm
from ..services.requirements import LabelDef, RequirementsService
from ..core.model import Requirement
from ..i18n import _
from .editor_panel import EditorPanel
from .helpers import inherit_background


class DetachedEditorFrame(wx.Frame):
    """Floating frame containing :class:`EditorPanel` for detached editing."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        requirement: Requirement,
        service: RequirementsService | None = None,
        doc_prefix: str,
        directory: Path | str | None = None,
        labels: list[LabelDef],
        allow_freeform: bool,
        on_save: Callable[[DetachedEditorFrame], bool],
        on_close: Callable[[DetachedEditorFrame], None] | None = None,
    ) -> None:
        """Create frame initialized with ``requirement`` contents."""
        if service is None:
            if directory is None:
                raise ValueError(
                    "DetachedEditorFrame requires either a requirements service or a directory"
                )
            service = RequirementsService(directory)
        else:
            if directory is not None:
                resolved = Path(directory)
                try:
                    service_root = getattr(service, "root", None)
                except Exception:  # pragma: no cover - defensive guard
                    service_root = None
                if service_root is None or Path(service_root) != resolved:
                    service = RequirementsService(resolved)

        title = self._format_title(requirement, doc_prefix)
        super().__init__(parent, title=title)
        background_source = self._resolve_background_source(parent)
        self._apply_background(self, background_source)
        self._on_save = on_save
        self._on_close = on_close
        self._closing_via_cancel = False
        self._service = service
        self.doc_prefix = doc_prefix
        self.requirement_id = requirement.id
        self._allow_freeform = allow_freeform
        self._labels: list[LabelDef] = list(labels)

        container = wx.Panel(self)
        self._apply_background(container, background_source)

        self.editor = EditorPanel(
            container,
            on_save=self._handle_save,
            on_discard=self._handle_cancel,
        )
        self.editor.set_service(service)
        editor_sizer = wx.BoxSizer(wx.VERTICAL)
        editor_sizer.Add(self.editor, 1, wx.EXPAND)
        container.SetSizer(editor_sizer)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(container, 1, wx.EXPAND)
        self.SetSizer(sizer)

        self.editor.set_document(self.doc_prefix)
        self.editor.update_labels_list(self._labels, self._allow_freeform)
        self.editor.load(requirement)

        self.Bind(wx.EVT_CLOSE, self._on_close_window)
        self.SetSize((900, 700))
        self.CentreOnParent()

    # ------------------------------------------------------------------
    def _resolve_background_source(self, parent: wx.Window | None) -> wx.Window | None:
        """Return a widget whose colours should be mirrored by this frame."""
        if parent is None:
            return None
        try:
            candidate = getattr(parent, "editor", None)
        except Exception:  # pragma: no cover - defensive: attribute may raise
            candidate = None
        if isinstance(candidate, wx.Window):
            return candidate
        if isinstance(parent, wx.Window):
            return parent
        return None

    def _apply_background(
        self, target: wx.Window, source: wx.Window | None
    ) -> None:
        """Copy background colour to ``target`` falling back to system defaults."""
        if source is not None:
            inherit_background(target, source)
            return
        try:
            colour = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        except Exception:  # pragma: no cover - backend specific failure
            return
        if hasattr(colour, "IsOk") and not colour.IsOk():
            return
        try:
            target.SetBackgroundColour(colour)
        except Exception:  # pragma: no cover - backend quirk
            return

    # ------------------------------------------------------------------
    @property
    def key(self) -> tuple[str, int]:
        """Return dictionary key representing this editor instance."""
        return self.doc_prefix, self.requirement_id

    def reload(
        self,
        requirement: Requirement,
        doc_prefix: str,
        labels: list[LabelDef],
        allow_freeform: bool,
    ) -> None:
        """Load ``requirement`` replacing current contents."""
        self.doc_prefix = requirement.doc_prefix or doc_prefix or self.doc_prefix
        self.requirement_id = requirement.id
        self._labels = list(labels)
        self._allow_freeform = allow_freeform
        self.editor.set_service(self._service)
        self.editor.set_document(self.doc_prefix)
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

        if self.editor.is_dirty() and not confirm(_("Discard unsaved changes?")):
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

