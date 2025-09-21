"""Document tree management for the main frame."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import wx

from ...core.document_store import (
    LabelDef,
    ValidationError,
    save_document,
)
from ...i18n import _
from ...log import logger
from ..controllers import DocumentsController
from ..labels_dialog import LabelsDialog

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from .frame import MainFrame


class MainFrameDocumentsMixin:
    """Encapsulate document-related handlers and helpers."""

    docs_controller: DocumentsController | None
    current_dir: Path | None
    current_doc_prefix: str | None
    _doc_tree_last_sash: int
    _doc_tree_min_pane: int

    @property
    def recent_dirs(self: "MainFrame") -> list[str]:
        """Return directories recently opened by the user."""

        return self.config.get_recent_dirs()

    def _current_document_summary(self: "MainFrame") -> str | None:
        """Return prefix and title of the active document for the header."""

        prefix = self.current_doc_prefix
        if not prefix:
            return None
        controller = getattr(self, "docs_controller", None)
        if not controller:
            return None
        document = controller.documents.get(prefix)
        if document is None:
            return prefix
        prefix_text = document.prefix.strip()
        title_text = document.title.strip()
        if prefix_text and title_text:
            return f"{prefix_text}: {title_text}"
        if title_text:
            return title_text
        if prefix_text:
            return prefix_text
        return prefix

    def _update_requirements_label(self: "MainFrame") -> None:
        """Adjust requirements pane title to reflect active document."""

        label_ctrl = getattr(self, "list_label", None)
        if not label_ctrl:
            return
        base_label = _("Requirements")
        summary = self._current_document_summary()
        if summary:
            text = _("Requirements - {document}").format(document=summary)
        else:
            text = base_label
        label_ctrl.SetLabel(text)
        parent = getattr(label_ctrl, "GetParent", None)
        if callable(parent):
            container = parent()
            if container and hasattr(container, "Layout"):
                container.Layout()

    def on_open_folder(self: "MainFrame", _event: wx.Event) -> None:
        """Handle "Open Folder" menu action."""

        dlg = wx.DirDialog(self, _("Select requirements folder"))
        if dlg.ShowModal() == wx.ID_OK:
            if not self._confirm_discard_changes():
                dlg.Destroy()
                return
            self._load_directory(Path(dlg.GetPath()))
        dlg.Destroy()

    def on_open_recent(self: "MainFrame", event: wx.CommandEvent) -> None:
        """Open a directory selected from the "recent" menu."""

        path = self.navigation.get_recent_path(event.GetId())
        if path and self._confirm_discard_changes():
            self._load_directory(path)

    def _normalise_directory_path(self, path: Path) -> str:
        """Return canonical string representation for ``path``."""

        try:
            return str(path.resolve())
        except OSError:
            return str(path)

    def _sync_mcp_base_path(self: "MainFrame", path: Path) -> None:
        """Persist MCP base path and restart server when needed."""

        new_base_path = self._normalise_directory_path(path)
        if self.mcp_settings.base_path == new_base_path:
            return
        auto_start = self.mcp_settings.auto_start
        self.mcp_settings = self.mcp_settings.model_copy(
            update={"base_path": new_base_path}
        )
        self.config.set_mcp_settings(self.mcp_settings)
        if auto_start:
            try:
                self.mcp.stop()
            except Exception:  # pragma: no cover - controller must not crash UI
                logger.exception(
                    "Failed to stop MCP server before applying new base path"
                )
            try:
                self.mcp.start(self.mcp_settings)
            except Exception:  # pragma: no cover - controller must not crash UI
                logger.exception(
                    "Failed to start MCP server after applying new base path"
                )

    def _load_directory(self: "MainFrame", path: Path) -> None:
        """Load requirements from ``path`` and update recent list."""

        controller = DocumentsController(path, self.model)
        try:
            docs = controller.load_documents()
        except ValidationError as exc:
            logger.error(
                "validation error while loading requirements folder %s: %s", path, exc
            )
            self._show_directory_error(path, exc)
            return
        except Exception as exc:  # pragma: no cover - unexpected GUI failure
            logger.exception(
                "unexpected error while loading requirements folder %s", path
            )
            self._show_directory_error(path, exc)
            return

        self.docs_controller = controller
        self.panel.set_documents_controller(self.docs_controller)
        self.doc_tree.set_documents(docs)
        self.config.add_recent_dir(path)
        self.navigation.update_recent_menu()
        self.SetTitle(f"{self._base_title} - {path}")
        self.current_dir = path
        self._sync_mcp_base_path(path)
        if docs:
            first = sorted(docs)[0]
            self.current_doc_prefix = first
            self.panel.set_active_document(first)
            self.editor.set_directory(self.current_dir / first)
            self._load_document_contents(first)
            self.doc_tree.select(first)
        else:
            self.current_doc_prefix = None
            self.panel.set_active_document(None)
            self.editor.set_directory(None)
            self.panel.set_requirements([], {})
            self.editor.update_labels_list([])
            self.panel.update_labels_list([])
        self._update_requirements_label()
        if self.remember_sort and self.sort_column != -1:
            self.panel.sort(self.sort_column, self.sort_ascending)
        self._selected_requirement_id = None
        self._clear_editor_panel()

    def _show_directory_error(self: "MainFrame", path: Path, error: Exception) -> None:
        """Display error message for a failed directory load."""

        message = _(
            "Failed to load requirements folder \"{path}\": {error}"
        ).format(path=path, error=error)
        wx.MessageBox(message, _("Error"), wx.ICON_ERROR)

    def _refresh_documents(
        self: "MainFrame",
        *,
        select: str | None = None,
        force_reload: bool = False,
    ) -> None:
        """Reload document tree and optionally change selection."""

        if not self.docs_controller:
            return
        docs = self.docs_controller.load_documents()
        self.doc_tree.set_documents(docs)
        target = select
        if target and target not in docs:
            target = None
        if target is None:
            if self.current_doc_prefix and self.current_doc_prefix in docs:
                target = self.current_doc_prefix
            elif docs:
                target = sorted(docs)[0]
        if target:
            if force_reload or target != self.current_doc_prefix:
                self.current_doc_prefix = None
            self.doc_tree.select(target)
        else:
            self.current_doc_prefix = None
            self.panel.set_active_document(None)
            self.editor.set_directory(None)
            self.panel.set_requirements([], {})
            self.editor.update_labels_list([])
            self.panel.update_labels_list([])
            self._selected_requirement_id = None
            self._clear_editor_panel()
            self._update_requirements_label()

    def _load_document_contents(self: "MainFrame", prefix: str) -> bool:
        """Load items and labels for ``prefix`` and update the views."""

        if not self.docs_controller:
            return False
        self._update_requirements_label()
        try:
            derived_map = self.docs_controller.load_items(prefix)
        except Exception as exc:  # pragma: no cover - GUI side effect
            logger.exception("failed to load requirements for document %s", prefix)
            message = _(
                "Failed to load requirements for document \"{prefix}\": {error}"
            ).format(prefix=prefix, error=exc)
            wx.MessageBox(message, _("Error"), wx.ICON_ERROR)
            self.model.set_requirements([])
            self.panel.set_requirements([], {})
            self.editor.update_labels_list([], False)
            self.panel.update_labels_list([])
            self._selected_requirement_id = None
            self._clear_editor_panel()
            self.splitter.UpdateSize()
            return False
        labels, freeform = self.docs_controller.collect_labels(prefix)
        self.panel.set_requirements(self.model.get_all(), derived_map)
        self.editor.update_labels_list(labels, freeform)
        self.panel.update_labels_list(labels)
        self._selected_requirement_id = None
        self._clear_editor_panel()
        total = len(self.model.get_all())
        visible = len(self.model.get_visible())
        derived_parent_count = len(derived_map) if derived_map else 0
        derived_child_count = (
            sum(len(ids) for ids in derived_map.values()) if derived_map else 0
        )
        filters_snapshot: dict[str, object] = {}
        filter_summary = ""
        if hasattr(self.panel, "current_filters"):
            raw_filters = getattr(self.panel, "current_filters", {})
            for key, value in raw_filters.items():
                if isinstance(value, dict):
                    trimmed = {k: v for k, v in value.items() if v}
                    if trimmed:
                        filters_snapshot[key] = trimmed
                elif isinstance(value, (list, tuple, set)):
                    if value:
                        filters_snapshot[key] = list(value)
                elif isinstance(value, bool):
                    if value:
                        filters_snapshot[key] = value
                elif value not in (None, ""):
                    filters_snapshot[key] = value
        if getattr(self.panel, "filter_summary", None):
            try:
                filter_summary = self.panel.filter_summary.GetLabel().strip()
            except Exception:  # pragma: no cover - defensive UI access
                filter_summary = ""
        doc_path = ""
        if self.current_dir:
            doc_path = str(self.current_dir / prefix)
        filter_details = ""
        if filters_snapshot:
            try:
                serialized = json.dumps(
                    filters_snapshot, ensure_ascii=False, sort_keys=True
                )
            except Exception:  # pragma: no cover - logging fallback
                serialized = str(filters_snapshot)
            filter_details = f"; active filters={serialized}"
            if filter_summary:
                filter_details += f" ({filter_summary})"
        elif filter_summary:
            filter_details = f"; filter summary={filter_summary}"
        if doc_path:
            location = f" from {doc_path}"
        else:
            location = ""
        logger.info(
            "Document %s loaded%s: %s requirement(s), %s visible after filters%s; %s parent(s) with %s derived child link(s)",
            prefix,
            location,
            total,
            visible,
            filter_details,
            derived_parent_count,
            derived_child_count,
        )
        if total and visible == 0 and filters_snapshot:
            logger.warning(
                "All %s requirement(s) for %s are hidden by the current filters",
                total,
                prefix,
            )
        self.splitter.UpdateSize()
        return True

    def on_new_document(self: "MainFrame", parent_prefix: str | None) -> None:
        """Create a new document under ``parent_prefix``."""

        if not (self.docs_controller and self.current_dir):
            wx.MessageBox(_("Select requirements folder first"), _("No Data"))
            return
        from . import DocumentPropertiesDialog

        dlg = DocumentPropertiesDialog(
            self,
            mode="create",
            parent_prefix=parent_prefix,
        )
        props = None
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            props = dlg.get_properties()
        finally:
            dlg.Destroy()
        if props is None:
            return
        try:
            doc = self.docs_controller.create_document(
                props.prefix,
                props.title,
                parent=parent_prefix,
            )
        except ValueError as exc:
            wx.MessageBox(str(exc), _("Error"), wx.ICON_ERROR)
            return
        self._selected_requirement_id = None
        self._refresh_documents(select=doc.prefix, force_reload=True)

    def on_rename_document(self: "MainFrame", prefix: str) -> None:
        """Rename or retitle document ``prefix``."""

        if not self.docs_controller:
            return
        doc = self.docs_controller.documents.get(prefix)
        if not doc:
            return
        from . import DocumentPropertiesDialog

        dlg = DocumentPropertiesDialog(
            self,
            mode="rename",
            prefix=doc.prefix,
            title=doc.title,
            parent_prefix=doc.parent,
        )
        props = None
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            props = dlg.get_properties()
        finally:
            dlg.Destroy()
        if props is None:
            return
        try:
            self.docs_controller.rename_document(
                prefix,
                title=props.title,
            )
        except ValueError as exc:
            wx.MessageBox(str(exc), _("Error"), wx.ICON_ERROR)
            return
        self._refresh_documents(select=prefix, force_reload=True)

    def on_delete_document(self: "MainFrame", prefix: str) -> None:
        """Delete document ``prefix`` after confirmation."""

        if not self.docs_controller:
            return
        doc = self.docs_controller.documents.get(prefix)
        if not doc:
            return
        from . import confirm

        msg = _("Delete document {prefix} and its subtree?").format(prefix=prefix)
        if not confirm(msg):
            return
        parent_prefix = doc.parent
        removed = self.docs_controller.delete_document(prefix)
        if not removed:
            wx.MessageBox(_("Document not found"), _("Error"), wx.ICON_ERROR)
            return
        self._selected_requirement_id = None
        target = parent_prefix if parent_prefix in self.docs_controller.documents else None
        self._refresh_documents(select=target, force_reload=True)

    def _on_doc_changing(self: "MainFrame", event: wx.TreeEvent) -> None:
        """Request confirmation before switching documents."""

        if event.GetItem() == event.GetOldItem():
            event.Skip()
            return
        if not self._confirm_discard_changes():
            if not hasattr(event, "CanVeto") or event.CanVeto():
                event.Veto()
            return
        event.Skip()

    def on_document_selected(self: "MainFrame", prefix: str) -> None:
        """Load items and labels for selected document ``prefix``."""

        if prefix == self.current_doc_prefix:
            return
        if not self.docs_controller:
            return
        self.current_doc_prefix = prefix
        self.panel.set_active_document(prefix)
        if self.current_dir:
            self.editor.set_directory(self.current_dir / prefix)
        self._load_document_contents(prefix)

    def on_manage_labels(self: "MainFrame", _event: wx.Event) -> None:
        """Open dialog to manage defined labels."""

        if not (self.docs_controller and self.current_doc_prefix and self.current_dir):
            return
        doc = self.docs_controller.documents[self.current_doc_prefix]
        labels = [LabelDef(ld.key, ld.title, ld.color) for ld in doc.labels.defs]
        dlg = LabelsDialog(self, labels)
        if dlg.ShowModal() == wx.ID_OK:
            doc.labels.defs = dlg.get_labels()
            save_document(self.current_dir / self.current_doc_prefix, doc)
            labels_all, freeform = self.docs_controller.collect_labels(
                self.current_doc_prefix
            )
            self.panel.update_labels_list(labels_all)
            self.editor.update_labels_list(labels_all, freeform)
        dlg.Destroy()

    def on_show_derivation_graph(self: "MainFrame", _event: wx.Event) -> None:
        """Open window displaying requirement derivation graph."""

        if not (self.current_dir and self.docs_controller):
            wx.MessageBox(_("Select requirements folder first"), _("No Data"))
            return
        links = list(self.docs_controller.iter_links())
        if not links:
            wx.MessageBox(_("No links found"), _("No Data"))
            return
        try:
            from ..derivation_graph import DerivationGraphFrame
        except Exception as exc:
            wx.MessageBox(str(exc), _("Error"))
            return
        frame = DerivationGraphFrame(self, links)
        self.register_auxiliary_frame(frame)
        frame.Show()

    def on_show_trace_matrix(self: "MainFrame", _event: wx.Event) -> None:
        """Open window displaying requirement trace links."""

        if not (self.current_dir and self.docs_controller):
            wx.MessageBox(_("Select requirements folder first"), _("No Data"))
            return
        links = list(self.docs_controller.iter_links())
        if not links:
            wx.MessageBox(_("No links found"), _("No Data"))
            return
        try:
            from ..trace_matrix import TraceMatrixFrame
        except Exception as exc:  # pragma: no cover - missing wx
            wx.MessageBox(str(exc), _("Error"))
            return
        frame = TraceMatrixFrame(self, links)
        self.register_auxiliary_frame(frame)
        frame.Show()
