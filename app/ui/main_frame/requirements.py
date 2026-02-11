"""Requirement list actions for the main frame."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from collections.abc import Sequence

import wx

from ...services.requirements import (
    DocumentNotFoundError,
    RequirementIDCollisionError,
    RequirementNotFoundError,
    ValidationError,
    rid_for,
)
from ...core.model import Link, Requirement, requirement_fingerprint
from ...i18n import _
from ...log import logger
from ..transfer_dialog import (
    RequirementTransferDialog,
    TransferMode,
)

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from .frame import MainFrame


class MainFrameRequirementsMixin:
    """Implement actions triggered from the requirements list."""

    def _persist_new_requirement(
        self: MainFrame,
        requirement: Requirement,
        *,
        action_label: str,
    ) -> bool:
        if not (self.docs_controller and self.current_doc_prefix):
            return False
        prefix = self.current_doc_prefix
        try:
            self.docs_controller.add_requirement(prefix, requirement)
            self.docs_controller.save_requirement(prefix, requirement)
        except (
            DocumentNotFoundError,
            RequirementIDCollisionError,
            ValidationError,
        ) as exc:
            self.model.delete(requirement.id, doc_prefix=prefix)
            message = _("{action} failed for {rid}: {error}").format(
                action=action_label,
                rid=requirement.rid or f"{prefix}{requirement.id}",
                error=str(exc),
            )
            logger.warning("%s", message)
            wx.MessageBox(message, _("Error"), wx.ICON_ERROR)
            return False
        except Exception as exc:  # pragma: no cover - defensive guard
            self.model.delete(requirement.id, doc_prefix=prefix)
            logger.exception(
                "%s failed for %s",
                action_label,
                requirement.rid or f"{prefix}{requirement.id}",
            )
            wx.MessageBox(
                _("{action} failed: {error}").format(
                    action=action_label,
                    error=str(exc),
                ),
                _("Error"),
                wx.ICON_ERROR,
            )
            return False
        return True

    def on_toggle_column(self: MainFrame, event: wx.CommandEvent) -> None:
        """Show or hide column associated with menu item."""
        field = self.navigation.get_field_for_id(event.GetId())
        if not field:
            return
        if field in self.selected_fields:
            self.selected_fields.remove(field)
        else:
            self.selected_fields.append(field)
        self.panel.set_columns(self.selected_fields)
        self.panel.load_column_widths(self.config)
        self.panel.load_column_order(self.config)
        self.config.set_columns(self.selected_fields)

    def on_new_requirement(self: MainFrame, _event: wx.Event | None = None) -> None:
        """Create and persist a new requirement."""
        if not (self.docs_controller and self.current_doc_prefix):
            return
        new_id = self.docs_controller.next_item_id(self.current_doc_prefix)
        self.editor.new_requirement()
        self.editor.fields["id"].SetValue(str(new_id))
        data = self.editor.get_data()
        self.docs_controller.add_requirement(self.current_doc_prefix, data)
        if hasattr(self.model, "mark_unsaved"):
            self.model.mark_unsaved(data)
        self._selected_requirement_id = new_id
        self.panel.refresh(select_id=new_id)
        self.editor.load(data, path=None, mtime=None)
        if self._is_editor_visible():
            self._show_editor_panel()
            self.splitter.UpdateSize()
        else:
            self._open_detached_editor(data)

    def on_clone_requirement(self: MainFrame, req_id: int) -> None:
        """Clone requirement ``req_id`` and open in editor."""
        if not (self.docs_controller and self.current_doc_prefix):
            return
        source = self.model.get_by_id(req_id, doc_prefix=self.current_doc_prefix)
        if not source:
            return
        new_id = self.docs_controller.next_item_id(self.current_doc_prefix)
        clone = replace(
            source,
            id=new_id,
            title=f"{_('(Copy)')} {source.title}".strip(),
            modified_at="",
            revision=1,
        )
        if not self._persist_new_requirement(clone, action_label=_("Clone")):
            return
        self._selected_requirement_id = new_id
        self.panel.refresh(select_id=new_id)
        self.editor.load(clone, path=None, mtime=None)
        if self._is_editor_visible():
            self._show_editor_panel()
            self.splitter.UpdateSize()
        else:
            self._open_detached_editor(clone)

    def _create_linked_copy(self: MainFrame, source: Requirement) -> tuple[Requirement, str]:
        if not (self.docs_controller and self.current_doc_prefix):
            raise RuntimeError("Documents controller not initialized")
        doc = self.docs_controller.documents.get(self.current_doc_prefix)
        if doc is None:
            raise RuntimeError("Document not loaded")

        new_id = self.docs_controller.next_item_id(self.current_doc_prefix)
        parent_rid = (getattr(source, "rid", "") or "").strip()
        if not parent_rid:
            parent_rid = rid_for(doc, source.id)

        existing_links: list[Link] = []
        for entry in getattr(source, "links", []):
            if isinstance(entry, Link):
                existing_links.append(
                    Link(rid=entry.rid, fingerprint=entry.fingerprint, suspect=entry.suspect)
                )
                continue
            try:
                existing_links.append(Link.from_raw(entry))
            except (TypeError, ValueError):
                logger.warning(
                    "Ignoring invalid link %r while deriving requirement %s",
                    entry,
                    getattr(source, "rid", source.id),
                )

        parent_link = Link(
            rid=parent_rid,
            fingerprint=requirement_fingerprint(source),
            suspect=False,
        )
        new_links = [*existing_links, parent_link]

        clone = replace(
            source,
            id=new_id,
            title=f"{_('(Derived)')} {source.title}".strip(),
            modified_at="",
            revision=1,
            links=new_links,
        )
        return clone, parent_rid

    def on_derive_requirement(self: MainFrame, req_id: int) -> None:
        """Create a requirement derived from ``req_id`` and open it."""
        if not (self.docs_controller and self.current_doc_prefix):
            return
        source = self.model.get_by_id(req_id, doc_prefix=self.current_doc_prefix)
        if not source:
            return
        clone, parent_rid = self._create_linked_copy(source)
        if not self._persist_new_requirement(clone, action_label=_("Derive")):
            return
        self.panel.record_link(parent_rid, clone.id)
        self._selected_requirement_id = clone.id
        self.panel.refresh(select_id=clone.id)
        self.editor.load(clone, path=None, mtime=None)
        if self._is_editor_visible():
            self._show_editor_panel()
            self.splitter.UpdateSize()
        else:
            self._open_detached_editor(clone)

    def _format_requirement_summary(
        self: MainFrame, requirement: Requirement | None
    ) -> str | None:
        if not requirement:
            return None
        summary_parts: list[str] = []
        if requirement.rid:
            summary_parts.append(requirement.rid)
        title = requirement.title.strip()
        if title:
            summary_parts.append(title)
        if summary_parts:
            return " — ".join(summary_parts)
        return None

    def on_delete_requirements(self: MainFrame, req_ids: Sequence[int]) -> None:
        """Delete multiple requirements referenced by ``req_ids``."""
        if not req_ids:
            return
        if not (self.docs_controller and self.current_doc_prefix):
            return

        unique_ids: list[int] = []
        seen: set[int] = set()
        for req_id in req_ids:
            try:
                numeric = int(req_id)
            except (TypeError, ValueError):
                continue
            if numeric in seen:
                continue
            seen.add(numeric)
            unique_ids.append(numeric)
        if not unique_ids:
            return

        summaries: list[str] = []
        if self.model:
            for req_id in unique_ids:
                summary = self._format_requirement_summary(
                    self.model.get_by_id(
                        req_id, doc_prefix=self.current_doc_prefix
                    )
                )
                if summary:
                    summaries.append(summary)

        if len(unique_ids) == 1:
            message = _("Delete requirement?")
            if summaries:
                message = _("Delete requirement {summary}?").format(
                    summary=summaries[0]
                )
        else:
            message = _("Delete {count} requirements?").format(
                count=len(unique_ids)
            )
            if summaries:
                preview_limit = 5
                preview = summaries[:preview_limit]
                bullet_lines = "\n".join(f"- {text}" for text in preview)
                message = message + "\n" + bullet_lines
                if len(summaries) > preview_limit:
                    remaining = len(summaries) - preview_limit
                    message += "\n" + _("...and {count} more.").format(
                        count=remaining
                    )

        from . import confirm

        if not confirm(message):
            return

        deleted_any = False
        revision_errors: list[str] = []
        for req_id in unique_ids:
            requirement = self.model.get_by_id(
                req_id, doc_prefix=self.current_doc_prefix
            )
            unsaved_only = bool(
                requirement is not None
                and hasattr(self.model, "is_unsaved")
                and self.model.is_unsaved(requirement)
            )
            try:
                self.docs_controller.delete_requirement(
                    self.current_doc_prefix, req_id
                )
            except RequirementNotFoundError:
                if unsaved_only:
                    self.model.delete(req_id, doc_prefix=self.current_doc_prefix)
                    deleted_any = True
                continue
            except ValidationError as exc:
                doc = self.docs_controller.documents.get(self.current_doc_prefix)
                rid = (
                    rid_for(doc, req_id)
                    if doc is not None
                    else f"{self.current_doc_prefix}{req_id}"
                )
                revision_errors.append(
                    _("{rid}: {message}").format(rid=rid, message=str(exc))
                )
                continue
            deleted_any = True

        if revision_errors:
            unique_errors = list(dict.fromkeys(revision_errors))
            wx.MessageBox(
                "\n".join(unique_errors),
                _("Delete requirement failed"),
                wx.ICON_WARNING,
            )

        if not deleted_any:
            return

        self._selected_requirement_id = None
        self.panel.recalc_derived_map(self.model.get_all())
        self._clear_editor_panel()
        self.splitter.UpdateSize()
        labels, freeform = self.docs_controller.collect_labels(
            self.current_doc_prefix
        )
        self.editor.update_labels_list(labels, freeform)
        self.panel.update_labels_list(labels, freeform)

    def on_delete_requirement(self: MainFrame, req_id: int) -> None:
        """Delete requirement ``req_id`` and refresh views."""
        self.on_delete_requirements([req_id])

    def on_transfer_requirements(self: MainFrame, req_ids: Sequence[int]) -> None:
        """Move or copy selected requirements to another document."""

        if not req_ids:
            return
        if not (self.docs_controller and self.current_doc_prefix):
            return

        unique_ids: list[int] = []
        seen: set[int] = set()
        for req_id in req_ids:
            try:
                numeric = int(req_id)
            except (TypeError, ValueError):
                continue
            if numeric in seen:
                continue
            seen.add(numeric)
            unique_ids.append(numeric)
        if not unique_ids:
            return

        requirements: list[Requirement] = []
        for req_id in unique_ids:
            requirement = self.model.get_by_id(
                req_id, doc_prefix=self.current_doc_prefix
            )
            if requirement is not None:
                requirements.append(requirement)
        if not requirements:
            return

        documents = self.docs_controller.documents
        if not documents:
            documents = self.docs_controller.load_documents()
        dialog = RequirementTransferDialog(
            self,
            documents=documents,
            current_prefix=self.current_doc_prefix,
            selection_count=len(requirements),
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            plan = dialog.get_plan()
        finally:
            dialog.Destroy()

        if plan is None:
            return

        target_prefix = plan.target_prefix.strip()
        if not target_prefix:
            wx.MessageBox(_("Select a target document."), _("Error"), wx.ICON_ERROR)
            return
        current_prefix = self.current_doc_prefix
        if plan.mode is TransferMode.MOVE and target_prefix == current_prefix:
            wx.MessageBox(
                _("Select a different document when moving requirements."),
                _("Error"),
                wx.ICON_ERROR,
            )
            return

        successes: list[Requirement] = []
        errors: list[str] = []
        doc = self.docs_controller.documents.get(current_prefix)
        if doc is None:
            doc = self.docs_controller.load_documents().get(current_prefix)
        for requirement in requirements:
            rid = getattr(requirement, "rid", "")
            if not rid:
                if doc is not None:
                    rid = rid_for(doc, requirement.id)
                else:
                    rid = f"{current_prefix}{requirement.id}"
            try:
                if plan.mode is TransferMode.COPY:
                    copied = self.docs_controller.copy_requirement_to(
                        current_prefix,
                        requirement,
                        target_prefix=target_prefix,
                        reset_revision=plan.reset_revision,
                    )
                    successes.append(copied)
                    logger.info(
                        "Copied requirement %s to %s as %s",
                        rid,
                        target_prefix,
                        copied.rid,
                    )
                else:
                    moved = self.docs_controller.move_requirement_to(
                        current_prefix,
                        requirement,
                        target_prefix=target_prefix,
                    )
                    successes.append(moved)
                    logger.info(
                        "Moved requirement %s to %s as %s",
                        rid,
                        target_prefix,
                        moved.rid,
                    )
            except (
                DocumentNotFoundError,
                RequirementIDCollisionError,
                RequirementNotFoundError,
                ValidationError,
            ) as exc:
                message = _("{rid}: {error}").format(rid=rid, error=str(exc))
                errors.append(message)
                logger.warning("Failed to transfer requirement %s: %s", rid, exc)

        if errors:
            unique_errors = list(dict.fromkeys(errors))
            wx.MessageBox(
                "\n".join(unique_errors),
                _("Transfer failed"),
                wx.ICON_WARNING,
            )

        if not successes:
            return

        selection_prefix = current_prefix
        if plan.switch_to_target:
            selection_prefix = target_prefix

        focus_prefix: str | None = None
        focus_id: int | None = None
        if plan.mode is TransferMode.COPY and target_prefix == current_prefix:
            focus_prefix = current_prefix
            focus_id = successes[-1].id
        elif plan.switch_to_target:
            focus_prefix = target_prefix
            focus_id = successes[-1].id

        self._refresh_documents(select=selection_prefix, force_reload=True)

        if focus_prefix and focus_id is not None:
            self._selected_requirement_id = focus_id
            wx.CallAfter(self.panel.focus_requirement, focus_id)
        else:
            self._selected_requirement_id = None

        rid_list = ", ".join(req.rid for req in successes if getattr(req, "rid", ""))
        action_label = _("Copied") if plan.mode is TransferMode.COPY else _("Moved")
        message = _("{action} {count} requirement(s) to {prefix}.").format(
            action=action_label,
            count=len(successes),
            prefix=target_prefix,
        )
        if rid_list:
            message += "\n" + rid_list
        wx.MessageBox(message, _("Transfer completed"))

    def _on_sort_changed(self: MainFrame, column: int, ascending: bool) -> None:
        if not self.remember_sort:
            return
        self.sort_column = column
        self.sort_ascending = ascending
        self.config.set_sort_settings(column, ascending)
