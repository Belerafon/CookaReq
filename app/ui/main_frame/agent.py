"""Agent chat helpers for the main frame."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Callable

import wx

from ...agent import LocalAgent
from ...confirm import ConfirmDecision, RequirementUpdatePrompt
from ...core.document_store import parse_rid
from ...core.model import Requirement, requirement_from_dict
from ...settings import AppSettings

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from .frame import MainFrame


logger = logging.getLogger("cookareq.ui.main_frame.agent")


class MainFrameAgentMixin:
    """Provide agent chat integration and shortcuts."""

    def _create_agent(
        self: "MainFrame",
        *,
        confirm_override: Callable[[str], bool] | None = None,
        confirm_requirement_update_override: Callable[
            [RequirementUpdatePrompt], ConfirmDecision
        ]
        | None = None,
    ) -> LocalAgent:
        """Construct ``LocalAgent`` using current settings."""

        from . import confirm

        settings = AppSettings(llm=self.llm_settings, mcp=self.mcp_settings)
        confirm_callback = confirm_override or confirm
        return LocalAgent(
            settings=settings,
            confirm=confirm_callback,
            confirm_requirement_update=confirm_requirement_update_override,
        )

    def _selected_requirement_ids_for_agent(self: "MainFrame") -> list[int]:
        ids: list[int] = []
        panel = getattr(self, "panel", None)
        if panel is not None and hasattr(panel, "get_selected_ids"):
            try:
                ids.extend(panel.get_selected_ids())
            except Exception:  # pragma: no cover - defensive
                pass
        current = getattr(self, "_selected_requirement_id", None)
        if isinstance(current, int) and current not in ids:
            ids.append(current)
        filtered: list[int] = []
        for value in ids:
            try:
                numeric = int(value)
            except (TypeError, ValueError):
                continue
            if numeric not in filtered:
                filtered.append(numeric)
        return filtered

    def _agent_context_messages(self: "MainFrame") -> list[dict[str, str]]:
        lines: list[str] = ["[Workspace context]"]
        summary = self._current_document_summary()
        prefix = getattr(self, "current_doc_prefix", None)
        if summary:
            lines.append(f"Active requirements list: {summary}")
        elif prefix:
            lines.append(f"Active requirements list: {prefix}")
        else:
            lines.append("Active requirements list: (none)")

        selected_ids = self._selected_requirement_ids_for_agent()
        model = getattr(self, "model", None)
        rid_summary: list[str] = []
        unresolved_ids: list[str] = []
        if selected_ids and model is not None:
            for req_id in selected_ids:
                requirement = model.get_by_id(req_id)
                if requirement is None:
                    unresolved_ids.append(str(req_id))
                    continue
                rid = getattr(requirement, "rid", "") or ""
                rid = rid.strip()
                if not rid:
                    continue
                if rid not in rid_summary:
                    rid_summary.append(rid)
        elif selected_ids:
            unresolved_ids.extend(str(req_id) for req_id in selected_ids)

        if rid_summary:
            lines.append(f"Selected requirement RIDs: {', '.join(rid_summary)}")
        else:
            lines.append("Selected requirement RIDs: (none)")
        if unresolved_ids:
            lines.append(
                "Unresolved GUI selection ids: " + ", ".join(unresolved_ids)
            )

        return [{"role": "system", "content": "\n".join(lines)}]

    def _on_agent_tool_results(
        self: "MainFrame", tool_results: Sequence[Mapping[str, Any]]
    ) -> None:
        """Apply requirement updates returned by the agent."""

        if not tool_results:
            return
        current_prefix = getattr(self, "current_doc_prefix", None)
        if not current_prefix:
            return
        if not hasattr(self, "model") or not hasattr(self, "panel"):
            return

        updated: list[Requirement] = []
        removed_ids: list[int] = []
        for payload in tool_results:
            if not isinstance(payload, Mapping):
                continue
            if not payload.get("ok", False):
                continue
            tool_name_raw = (
                payload.get("tool_name")
                or payload.get("name")
                or payload.get("tool")
            )
            tool_name = str(tool_name_raw) if tool_name_raw else ""
            result_payload = payload.get("result")
            if tool_name in {
                "update_requirement_field",
                "set_requirement_labels",
                "set_requirement_attachments",
                "set_requirement_links",
                "link_requirements",
                "create_requirement",
            }:
                requirement = self._convert_tool_result_requirement(result_payload)
                if requirement is None:
                    continue
                if requirement.doc_prefix == current_prefix:
                    updated.append(requirement)
            elif tool_name == "delete_requirement":
                rid = self._extract_result_rid(result_payload)
                if not rid:
                    continue
                try:
                    prefix, req_id = parse_rid(rid)
                except ValueError:
                    logger.warning("Agent returned invalid requirement id %r", rid)
                    continue
                if prefix == current_prefix:
                    removed_ids.append(req_id)

        changes_applied = False
        selected_updated: Requirement | None = None
        for requirement in updated:
            try:
                self.model.update(requirement)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to update requirement %s", requirement.rid)
                continue
            changes_applied = True
            if getattr(self, "_selected_requirement_id", None) == requirement.id:
                selected_updated = requirement

        removed_selection = False
        for req_id in removed_ids:
            try:
                self.model.delete(req_id)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to remove requirement id %s", req_id)
                continue
            changes_applied = True
            if getattr(self, "_selected_requirement_id", None) == req_id:
                removed_selection = True

        if not changes_applied:
            return

        try:
            self.panel.recalc_derived_map(self.model.get_all())
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to refresh requirement list after agent update")
            return

        selected_id = getattr(self, "_selected_requirement_id", None)
        if removed_selection:
            self._selected_requirement_id = None
            try:
                self._clear_editor_panel()
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to clear editor after agent removal")
        elif selected_updated is not None:
            try:
                self.editor.load(selected_updated)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to refresh editor after agent update")
        if selected_id is not None and not removed_selection:
            try:
                self.panel.focus_requirement(selected_id)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to restore selection after agent update")

    @staticmethod
    def _extract_result_rid(result_payload: Any) -> str | None:
        if isinstance(result_payload, Mapping):
            rid_raw = result_payload.get("rid")
            return str(rid_raw) if isinstance(rid_raw, str) and rid_raw.strip() else None
        return None

    @staticmethod
    def _convert_tool_result_requirement(result_payload: Any) -> Requirement | None:
        if not isinstance(result_payload, Mapping):
            return None
        rid_raw = result_payload.get("rid")
        if not isinstance(rid_raw, str) or not rid_raw.strip():
            return None
        rid = rid_raw.strip()
        try:
            prefix, _ = parse_rid(rid)
        except ValueError:
            logger.warning("Agent returned invalid requirement id %r", rid)
            return None
        try:
            requirement = requirement_from_dict(dict(result_payload), doc_prefix=prefix, rid=rid)
        except Exception:
            logger.exception("Failed to parse requirement payload from agent tool")
            return None
        requirement.doc_prefix = prefix
        requirement.rid = rid
        return requirement

    def on_run_command(self: "MainFrame", _event: wx.Event) -> None:
        """Ensure agent chat panel is visible and focused."""

        if not self.agent_chat_menu_item:
            return
        if not self.agent_chat_menu_item.IsChecked():
            self.agent_chat_menu_item.Check(True)
            self.on_toggle_agent_chat(None)
        else:
            self._apply_agent_chat_visibility(persist=False)

    def on_toggle_agent_chat(self: "MainFrame", _event: wx.CommandEvent | None) -> None:
        """Toggle agent chat panel visibility."""

        if not self.agent_chat_menu_item:
            return
        self._apply_agent_chat_visibility(persist=True)
