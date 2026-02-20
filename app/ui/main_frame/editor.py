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

    def _has_multiple_selected_requirements(self: MainFrame) -> bool:
        """Return ``True`` when requirements list currently contains multi-selection."""
        panel = getattr(self, "panel", None)
        if panel is None or not hasattr(panel, "get_selected_ids"):
            return False
        try:
            return len(panel.get_selected_ids()) > 2
        except Exception:
            return False

    def _is_requirement_index_selected(self: MainFrame, index: int) -> bool:
        """Return ``True`` if list row ``index`` remains selected."""
        if index < 0:
            return False
        list_ctrl = getattr(getattr(self, "panel", None), "list", None)
        if list_ctrl is None or not hasattr(list_ctrl, "GetItemState"):
            return False
        selected_flag = getattr(wx, "LIST_STATE_SELECTED", 0x0002)
        try:
            state = list_ctrl.GetItemState(index, selected_flag)
        except Exception:
            return False
        return bool(state & selected_flag)

    def _load_requirement_from_list_index(self: MainFrame, index: int) -> None:
        """Load requirement for list row ``index`` into the editor."""
        if index == wx.NOT_FOUND:
            return
        req_id = self.panel.list.GetItemData(index)
        if req_id == self._selected_requirement_id:
            return
        req = self.model.get_by_id(req_id, doc_prefix=self.current_doc_prefix)
        if req:
            self._selected_requirement_id = req_id
            self.editor.load(req)
            if self._is_editor_visible():
                self._show_editor_panel()
                self.splitter.UpdateSize()

    def _apply_deferred_requirement_selection(self: MainFrame, index: int) -> None:
        """Re-check selection state after UI events settle."""
        if not self._is_requirement_index_selected(index):
            return
        if self._is_editor_visible() and self._has_multiple_selected_requirements():
            return
        if not self._confirm_discard_changes():
            return
        self._load_requirement_from_list_index(index)

    def on_requirement_selected(self: MainFrame, event: wx.ListEvent) -> None:
        """Load requirement into editor when selected in list."""
        index = event.GetIndex()
        if index == wx.NOT_FOUND:
            return
        if self._is_editor_visible() and self._has_multiple_selected_requirements():
            wx.CallAfter(self._apply_deferred_requirement_selection, index)
            return
        if not self._confirm_discard_changes():
            if hasattr(event, "Veto"):
                can_veto = getattr(event, "CanVeto", None)
                if can_veto is None or can_veto():
                    event.Veto()
            return
        self._load_requirement_from_list_index(index)

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
        req = self.model.get_by_id(req_id, doc_prefix=self.current_doc_prefix)
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
            requirement = editor_panel.save(prefix)
        except RequirementIDCollisionError:
            return None
        except Exception as exc:  # pragma: no cover - GUI event
            from . import show_error_dialog

            show_error_dialog(self, str(exc), title=_("Error"))
            return None
        requirement.doc_prefix = prefix or requirement.doc_prefix
        self.model.update(requirement)
        if hasattr(self.model, "clear_unsaved"):
            self.model.clear_unsaved(requirement)
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
        if hasattr(self, "panel") and hasattr(self.panel, "refresh"):
            select_id = (
                self._selected_requirement_id
                if self.current_doc_prefix == prefix
                else None
            )
            self.panel.refresh(select_id=select_id)
        if self.current_doc_prefix == prefix:
            self.docs_controller.refresh_document(prefix)
            self._update_requirements_label()
        return requirement

    def _on_editor_save(self: MainFrame) -> None:
        if not self.docs_controller:
            return
        self._save_editor_contents(self.editor, doc_prefix=self.current_doc_prefix)

    def _handle_editor_discard(self: MainFrame) -> bool:
        """Reload currently selected requirement into the editor."""
        if self._selected_requirement_id is None:
            return False
        requirement = self.model.get_by_id(
            self._selected_requirement_id, doc_prefix=self.current_doc_prefix
        )
        if not requirement:
            return False
        if hasattr(self.model, "clear_unsaved"):
            self.model.clear_unsaved(requirement)
        self.editor.load(requirement)
        return True

    def _stash_unsaved_edits(
        self: MainFrame,
        editor_panel: EditorPanel,
        *,
        doc_prefix: str | None = None,
    ) -> bool:
        prefix = doc_prefix or str(editor_panel.extra.get("doc_prefix", ""))
        if not prefix:
            prefix = self.current_doc_prefix or ""
        if not prefix:
            return False
        try:
            requirement = editor_panel.get_data()
        except Exception as exc:  # pragma: no cover - GUI validation
            from . import show_error_dialog

            show_error_dialog(self, str(exc), title=_("Error"))
            return False
        requirement.doc_prefix = prefix or requirement.doc_prefix
        self.model.update(requirement)
        if hasattr(self.model, "mark_unsaved"):
            self.model.mark_unsaved(requirement)
        self.panel.recalc_derived_map(self.model.get_all())
        self.panel.refresh()
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
            config=self.config,
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
