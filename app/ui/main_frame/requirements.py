"""Requirement list actions for the main frame."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from collections.abc import Sequence

import wx

from ...services.requirements import rid_for
from ...core.model import Link, Requirement, requirement_fingerprint
from ...i18n import _
from ...log import logger

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from .frame import MainFrame


class MainFrameRequirementsMixin:
    """Implement actions triggered from the requirements list."""

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

    def on_new_requirement(self: MainFrame, _event: wx.Event) -> None:
        """Create and persist a new requirement."""

        if not (self.docs_controller and self.current_doc_prefix):
            return
        new_id = self.docs_controller.next_item_id(self.current_doc_prefix)
        self.editor.new_requirement()
        self.editor.fields["id"].SetValue(str(new_id))
        data = self.editor.get_data()
        self.docs_controller.add_requirement(self.current_doc_prefix, data)
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
        source = self.model.get_by_id(req_id)
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
        self.docs_controller.add_requirement(self.current_doc_prefix, clone)
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
        source = self.model.get_by_id(req_id)
        if not source:
            return
        clone, parent_rid = self._create_linked_copy(source)
        self.docs_controller.add_requirement(self.current_doc_prefix, clone)
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
                    self.model.get_by_id(req_id)
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
        for req_id in unique_ids:
            if not self.docs_controller.delete_requirement(
                self.current_doc_prefix, req_id
            ):
                continue
            deleted_any = True

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
        self.panel.update_labels_list(labels)

    def on_delete_requirement(self: MainFrame, req_id: int) -> None:
        """Delete requirement ``req_id`` and refresh views."""

        self.on_delete_requirements([req_id])

    def _on_sort_changed(self: MainFrame, column: int, ascending: bool) -> None:
        if not self.remember_sort:
            return
        self.sort_column = column
        self.sort_ascending = ascending
        self.config.set_sort_settings(column, ascending)
