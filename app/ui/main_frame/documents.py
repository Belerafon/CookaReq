"""Document tree management for the main frame."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import wx

from ...services.requirements import (
    LabelDef,
    RequirementIDCollisionError,
    ValidationError,
)
from ...core.requirement_import import SequentialIDAllocator, build_requirements
from ...i18n import _
from ...log import logger
from ..controllers import DocumentsController
from ..import_dialog import RequirementImportDialog
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
    def recent_dirs(self: MainFrame) -> list[str]:
        """Return directories recently opened by the user."""
        return self.config.get_recent_dirs()

    def _current_document_summary(self: MainFrame) -> str | None:
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

    def _update_requirements_label(self: MainFrame) -> None:
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

    def on_open_folder(self: MainFrame, _event: wx.Event) -> None:
        """Handle "Open Folder" menu action."""
        dlg = wx.DirDialog(self, _("Select requirements folder"))
        if dlg.ShowModal() == wx.ID_OK:
            if not self._confirm_discard_changes():
                dlg.Destroy()
                return
            self._load_directory(Path(dlg.GetPath()))
        dlg.Destroy()

    def on_open_recent(self: MainFrame, event: wx.CommandEvent) -> None:
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

    def _sync_mcp_base_path(self: MainFrame, path: Path) -> None:
        """Persist MCP base path and keep the running server in sync."""
        new_base_path = self._normalise_directory_path(path)
        if self.mcp_settings.base_path == new_base_path:
            return

        was_running = False
        try:
            was_running = bool(self.mcp.is_running())
        except Exception:  # pragma: no cover - controller must not crash UI
            logger.exception("Failed to query MCP server status before restart")

        auto_start = self.mcp_settings.auto_start
        self.mcp_settings = self.mcp_settings.model_copy(
            update={"base_path": new_base_path}
        )
        self.config.set_mcp_settings(self.mcp_settings)

        if not (auto_start or was_running):
            return

        try:
            self.mcp.stop()
        except Exception:  # pragma: no cover - controller must not crash UI
            logger.exception(
                "Failed to stop MCP server before applying new base path"
            )

        try:
            self.mcp.start(
                self.mcp_settings,
                max_context_tokens=self.llm_settings.max_context_tokens,
                token_model=self.llm_settings.model,
            )
        except Exception:  # pragma: no cover - controller must not crash UI
            logger.exception(
                "Failed to start MCP server after applying new base path"
            )

    def _load_directory(self: MainFrame, path: Path) -> None:
        """Load requirements from ``path`` and update recent list."""
        factory = getattr(self, "requirements_service_factory", None)
        if factory is None:
            raise RuntimeError("Requirements service factory not configured")
        service = factory(path)
        controller = DocumentsController(service, self.model)
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
        self.editor.set_service(service)
        self.panel.set_documents_controller(self.docs_controller)
        self.doc_tree.set_documents(docs)
        self.config.add_recent_dir(path)
        self.navigation.update_recent_menu()
        self.SetTitle(f"{self._base_title} - {path}")
        self.current_dir = path
        if hasattr(self, "agent_panel"):
            self.agent_panel.set_history_directory(path)
        self._sync_mcp_base_path(path)
        has_docs = bool(docs)
        if docs:
            first = sorted(docs)[0]
            self.current_doc_prefix = first
            self.panel.set_active_document(first)
            self.editor.set_document(first)
            self._load_document_contents(first)
            self.doc_tree.select(first)
        else:
            self.current_doc_prefix = None
            self.panel.set_active_document(None)
            self.editor.set_document(None)
            self.panel.set_requirements([], {})
            self.editor.update_labels_list([])
            self.panel.update_labels_list([], False)
        if hasattr(self, "navigation"):
            self.navigation.set_manage_labels_enabled(has_docs)
        self._update_requirements_label()
        if self.remember_sort and self.sort_column != -1:
            self.panel.sort(self.sort_column, self.sort_ascending)
        self._selected_requirement_id = None
        self._clear_editor_panel()

    def _show_directory_error(self: MainFrame, path: Path, error: Exception) -> None:
        """Display error message for a failed directory load."""
        message = _(
            "Failed to load requirements folder \"{path}\": {error}"
        ).format(path=path, error=error)
        wx.MessageBox(message, _("Error"), wx.ICON_ERROR)

    def _refresh_documents(
        self: MainFrame,
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
            self.editor.set_document(None)
            self.panel.set_requirements([], {})
            self.editor.update_labels_list([])
            self.panel.update_labels_list([], False)
            self._selected_requirement_id = None
            self._clear_editor_panel()
            self._update_requirements_label()
        if hasattr(self, "navigation"):
            self.navigation.set_manage_labels_enabled(bool(docs))

    def _load_document_contents(self: MainFrame, prefix: str) -> bool:
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
            self.panel.update_labels_list([], False)
            self._selected_requirement_id = None
            self._clear_editor_panel()
            self.splitter.UpdateSize()
            return False
        labels, freeform = self.docs_controller.collect_labels(prefix)
        self.panel.set_requirements(self.model.get_all(), derived_map)
        self.editor.update_labels_list(labels, freeform)
        self.panel.update_labels_list(labels, freeform)
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
        location = f" from {doc_path}" if doc_path else ""
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

    def on_new_document(self: MainFrame, parent_prefix: str | None) -> None:
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

    def on_rename_document(self: MainFrame, prefix: str) -> None:
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

    def on_delete_document(self: MainFrame, prefix: str) -> None:
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

    def _on_doc_changing(self: MainFrame, event: wx.TreeEvent) -> None:
        """Request confirmation before switching documents."""
        if event.GetItem() == event.GetOldItem():
            event.Skip()
            return
        if not self._confirm_discard_changes():
            if not hasattr(event, "CanVeto") or event.CanVeto():
                event.Veto()
            return
        event.Skip()

    def on_document_selected(self: MainFrame, prefix: str) -> None:
        """Load items and labels for selected document ``prefix``."""
        if prefix == self.current_doc_prefix:
            return
        if not self.docs_controller:
            if hasattr(self, "navigation"):
                self.navigation.set_manage_labels_enabled(False)
            return
        self.current_doc_prefix = prefix
        if hasattr(self, "navigation"):
            self.navigation.set_manage_labels_enabled(True)
        self.panel.set_active_document(prefix)
        self.editor.set_document(prefix)
        self._load_document_contents(prefix)

    def on_import_requirements(self: MainFrame, _event: wx.Event) -> None:
        """Open the import dialog and persist selected requirements."""
        if not (self.docs_controller and self.current_doc_prefix and self.current_dir):
            wx.MessageBox(_("Select requirements folder first"), _("No Data"))
            return
        doc = self.docs_controller.documents.get(self.current_doc_prefix)
        if doc is None:
            wx.MessageBox(_("Document not found"), _("Error"), wx.ICON_ERROR)
            return

        existing_ids = [req.id for req in self.model.get_all()]
        try:
            next_id = self.docs_controller.next_item_id(self.current_doc_prefix)
        except Exception as exc:  # pragma: no cover - document access failure
            logger.exception("Failed to determine next requirement id for %s", self.current_doc_prefix)
            wx.MessageBox(str(exc), _("Error"), wx.ICON_ERROR)
            return

        summary_parts = [doc.prefix]
        if doc.title.strip():
            summary_parts.append(doc.title.strip())
        document_label = " — ".join(summary_parts)
        dlg = RequirementImportDialog(
            self,
            existing_ids=existing_ids,
            next_id=next_id,
            document_label=document_label,
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            plan = dlg.get_plan()
        finally:
            dlg.Destroy()
        if plan is None:
            return

        allocator = SequentialIDAllocator(start=next_id, existing=existing_ids)
        result = build_requirements(plan.dataset, plan.configuration, allocator=allocator)
        if result.issues:
            messages = []
            for issue in result.issues[:5]:
                if issue.field:
                    messages.append(
                        _("Row {row}, field {field}: {message}").format(
                            row=issue.row, field=issue.field, message=issue.message
                        )
                    )
                else:
                    messages.append(
                        _("Row {row}: {message}").format(
                            row=issue.row, message=issue.message
                        )
                    )
            if len(result.issues) > 5:
                messages.append(
                    _("{count} more issue(s) not shown").format(
                        count=len(result.issues) - 5
                    )
                )
            wx.MessageBox(
                "\n".join(messages),
                _("Import blocked"),
                wx.ICON_ERROR,
            )
            return
        if not result.requirements:
            wx.MessageBox(_("No requirements to import."), _("Import"))
            return

        failures: list[str] = []
        imported = 0
        for requirement in result.requirements:
            try:
                self.docs_controller.add_requirement(self.current_doc_prefix, requirement)
                self.docs_controller.save_requirement(self.current_doc_prefix, requirement)
                imported += 1
            except RequirementIDCollisionError as exc:
                failures.append(str(exc))
            except ValidationError as exc:
                failures.append(str(exc))
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.exception("Failed to import requirement %s", getattr(requirement, "rid", requirement.id))
                failures.append(str(exc))

        if imported:
            last_id = result.requirements[-1].id
            self.panel.recalc_derived_map(self.model.get_all())
            self.panel.focus_requirement(last_id)
            self._selected_requirement_id = last_id
            logger.info(
                "Imported %s requirement(s) into %s", imported, self.current_doc_prefix
            )
            wx.MessageBox(
                _("Imported {count} requirement(s).").format(count=imported),
                _("Import completed"),
            )
        if failures:
            wx.MessageBox(
                "\n".join(failures),
                _("Some requirements failed"),
                wx.ICON_WARNING,
            )

    def on_manage_labels(self: MainFrame, _event: wx.Event) -> None:
        """Open dialog to manage defined labels."""
        if not (self.docs_controller and self.current_dir):
            wx.MessageBox(_("Select requirements folder first"), _("No Data"))
            return
        prefix = self.current_doc_prefix
        if not prefix:
            wx.MessageBox(_("Select a document first"), _("No Data"))
            return
        doc = self.docs_controller.documents.get(prefix)
        if doc is None:
            wx.MessageBox(_("Document not found"), _("Error"), wx.ICON_ERROR)
            return
        labels = [LabelDef(ld.key, ld.title, ld.color) for ld in doc.labels.defs]
        dlg = LabelsDialog(self, labels)
        if dlg.ShowModal() == wx.ID_OK:
            doc.labels.defs = dlg.get_labels()
            self.docs_controller.service.save_document(doc)
            labels_all, freeform = self.docs_controller.collect_labels(
                prefix
            )
            self.panel.update_labels_list(labels_all, freeform)
            self.editor.update_labels_list(labels_all, freeform)
        dlg.Destroy()

    def on_show_derivation_graph(self: MainFrame, _event: wx.Event) -> None:
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

    def on_show_trace_matrix(self: MainFrame, _event: wx.Event) -> None:
        """Open window displaying requirement trace links."""
        if not (self.current_dir and self.docs_controller):
            wx.MessageBox(_("Select requirements folder first"), _("No Data"))
            return
        try:
            from ..trace_matrix import TraceMatrixConfigDialog, TraceMatrixFrame
        except Exception as exc:  # pragma: no cover - missing wx
            wx.MessageBox(str(exc), _("Error"))
            return
        controller = self.docs_controller
        try:
            documents = controller.load_documents()
        except Exception as exc:  # pragma: no cover - defensive guard
            wx.MessageBox(str(exc), _("Error"))
            return
        if not documents:
            wx.MessageBox(_("No documents found"), _("No Data"))
            return

        default_row = self.current_doc_prefix or next(iter(documents), "")
        default_column: str | None = None
        if default_row and default_row in documents:
            default_column = documents[default_row].parent

        dialog = TraceMatrixConfigDialog(
            self,
            documents,
            default_rows=default_row,
            default_columns=default_column,
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            config = dialog.get_config()
        finally:
            dialog.Destroy()

        try:
            matrix = controller.build_trace_matrix(config)
        except Exception as exc:  # pragma: no cover - report via UI
            wx.MessageBox(str(exc), _("Error"))
            return
        if not matrix.rows or not matrix.columns:
            wx.MessageBox(
                _("Selected documents do not contain requirements"),
                _("No Data"),
            )
            return

        frame = TraceMatrixFrame(self, controller, config, matrix)
        self.register_auxiliary_frame(frame)
        frame.Show()
