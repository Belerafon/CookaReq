"""Editor management for the main frame."""

from __future__ import annotations

from typing import TYPE_CHECKING

import wx

from ...services.requirements import RequirementIDCollisionError
from ...core.model import Requirement
from ...i18n import _
from ..detached_editor import DetachedEditorFrame
from ..editor_panel import EditorPanel

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from .frame import MainFrame


class MainFrameEditorMixin:
    """Handlers dealing with the main and detached requirement editors."""

    editor: EditorPanel

    def on_requirement_selected(self: MainFrame, event: wx.ListEvent) -> None:
        """Load requirement into editor when selected in list."""
        index = event.GetIndex()
        if index == wx.NOT_FOUND:
            return
        req_id = self.panel.list.GetItemData(index)
        if req_id == self._selected_requirement_id:
            return
        if not self._confirm_discard_changes():
            if hasattr(event, "Veto"):
                can_veto = getattr(event, "CanVeto", None)
                if can_veto is None or can_veto():
                    event.Veto()
            return
        req = self.model.get_by_id(req_id)
        if req:
            self._selected_requirement_id = req_id
            self.editor.load(req)
            if self._is_editor_visible():
                self._show_editor_panel()
                self.splitter.UpdateSize()

    def on_requirement_activated(self: MainFrame, event: wx.ListEvent) -> None:
        """Open requirement in a detached editor when activated."""
        if self._is_editor_visible():
            event.Skip()
            return
        index = event.GetIndex()
        if index == wx.NOT_FOUND:
            return
        try:
            req_id = self.panel.list.GetItemData(index)
        except Exception:
            return
        if req_id <= 0:
            return
        req = self.model.get_by_id(req_id)
        if not req:
            return
        self._open_detached_editor(req)

    def _save_editor_contents(
        self: MainFrame,
        editor_panel: EditorPanel,
        *,
        doc_prefix: str | None = None,
    ) -> Requirement | None:
        if not (self.current_dir and self.docs_controller):
            return None
        prefix = doc_prefix or str(editor_panel.extra.get("doc_prefix", ""))
        if not prefix:
            prefix = self.current_doc_prefix or ""
        if not prefix:
            return None
        try:
            editor_panel.save(prefix)
        except RequirementIDCollisionError:
            return None
        except Exception as exc:  # pragma: no cover - GUI event
            from . import show_error_dialog

            show_error_dialog(self, str(exc), title=_("Error"))
            return None
        requirement = editor_panel.get_data()
        requirement.doc_prefix = prefix or requirement.doc_prefix
        self.model.update(requirement)
        self.panel.recalc_derived_map(self.model.get_all())
        labels, freeform = self.docs_controller.collect_labels(prefix)
        editor_panel.update_labels_list(labels, freeform)
        self.panel.update_labels_list(labels, freeform)
        if editor_panel is not self.editor:
            self.editor.update_labels_list(labels, freeform)
            if (
                self._is_editor_visible()
                and self.current_doc_prefix == prefix
                and self._selected_requirement_id == requirement.id
            ):
                self.editor.load(requirement)
        self._selected_requirement_id = requirement.id
        return requirement

    def _on_editor_save(self: MainFrame) -> None:
        if not self.docs_controller:
            return
        self._save_editor_contents(self.editor, doc_prefix=self.current_doc_prefix)

    def _handle_editor_discard(self: MainFrame) -> bool:
        """Reload currently selected requirement into the editor."""
        if self._selected_requirement_id is None:
            return False
        requirement = self.model.get_by_id(self._selected_requirement_id)
        if not requirement:
            return False
        self.editor.load(requirement)
        return True

    def _open_detached_editor(self: MainFrame, requirement: Requirement) -> None:
        if not self.docs_controller:
            return
        prefix = getattr(requirement, "doc_prefix", "") or self.current_doc_prefix
        if not prefix:
            return
        labels, freeform = self.docs_controller.collect_labels(prefix)
        key = (prefix, getattr(requirement, "id", 0))
        existing = self._detached_editors.get(key)
        if existing:
            existing.reload(requirement, prefix, labels, freeform)
            existing.Raise()
            existing.SetFocus()
            return
        frame = DetachedEditorFrame(
            self,
            requirement=requirement,
            service=self.docs_controller.service,
            doc_prefix=prefix,
            labels=labels,
            allow_freeform=freeform,
            on_save=self._on_detached_editor_save,
            on_close=self._on_detached_editor_closed,
        )
        self._detached_editors[frame.key] = frame
        frame.Show()

    def _on_detached_editor_save(self: MainFrame, frame: DetachedEditorFrame) -> bool:
        prefix = frame.doc_prefix
        if not prefix or not self.docs_controller:
            return False
        old_key = frame.key
        requirement = self._save_editor_contents(frame.editor, doc_prefix=prefix)
        if requirement is None:
            return False
        labels, freeform = self.docs_controller.collect_labels(prefix)
        frame.reload(requirement, prefix, labels, freeform)
        if old_key in self._detached_editors and self._detached_editors[old_key] is frame:
            del self._detached_editors[old_key]
        self._detached_editors[frame.key] = frame
        return True

    def _on_detached_editor_closed(self: MainFrame, frame: DetachedEditorFrame) -> None:
        for key, window in list(self._detached_editors.items()):
            if window is frame:
                del self._detached_editors[key]
                break
