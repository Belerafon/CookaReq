"""Agent chat helpers for the main frame."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

import wx

from ...confirm import ConfirmDecision, RequirementUpdatePrompt
from ...services.requirements import parse_rid
from ...core.model import Requirement, requirement_from_dict
from ...settings import AppSettings
from ...mcp.events import ToolResultEvent, add_tool_result_listener
from ..agent_chat_panel.batch_runner import BatchTarget

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from .frame import MainFrame


logger = logging.getLogger("cookareq.ui.main_frame.agent")


def _short_repr(value: Any, *, limit: int = 200) -> str:
    """Return shortened ``repr`` for logging purposes."""

    try:
        text = repr(value)
    except Exception:  # pragma: no cover - extremely defensive
        return f"<unrepresentable {type(value).__name__}>"
    if len(text) > limit:
        return text[: limit - 1] + "\u2026"
    return text


class MainFrameAgentMixin:
    """Provide agent chat integration and shortcuts."""

    _mcp_tool_listener_remove: Callable[[], None] | None = None
    _mcp_tool_listener_callback: Callable[[ToolResultEvent], None] | None = None

    def _create_agent(
        self: MainFrame,
        *,
        confirm_override: Callable[[str], bool] | None = None,
        confirm_requirement_update_override: Callable[
            [RequirementUpdatePrompt], ConfirmDecision
        ]
        | None = None,
    ):
        """Construct ``LocalAgent`` using current settings."""

        from . import confirm

        factory = getattr(self, "local_agent_factory", None)
        if factory is None:
            raise RuntimeError("Local agent factory not configured")

        settings = AppSettings(llm=self.llm_settings, mcp=self.mcp_settings)
        overrides: dict[str, object] = {
            "confirm_override": confirm_override or confirm,
        }
        if confirm_requirement_update_override is not None:
            overrides["confirm_requirement_update_override"] = (
                confirm_requirement_update_override
            )
        return factory(settings, **overrides)

    def _init_mcp_tool_listener(self: MainFrame) -> None:
        """Subscribe to MCP tool result notifications."""

        if getattr(self, "_mcp_tool_listener_remove", None):
            return

        def _deliver(event: ToolResultEvent) -> None:
            if not isinstance(event, ToolResultEvent):
                return
            if not event.payloads:
                return
            wx.CallAfter(self._handle_mcp_tool_event, event)

        self._mcp_tool_listener_callback = _deliver
        self._mcp_tool_listener_remove = add_tool_result_listener(_deliver)

    def _teardown_mcp_tool_listener(self: MainFrame) -> None:
        """Detach from MCP tool result notifications."""

        remover = getattr(self, "_mcp_tool_listener_remove", None)
        if remover is not None:
            try:
                remover()
            except Exception:  # pragma: no cover - defensive logging
                logger.exception("Failed to remove MCP tool listener")
            self._mcp_tool_listener_remove = None
        self._mcp_tool_listener_callback = None

    @staticmethod
    def _paths_match(current: Path | None, expected: Path | None) -> bool:
        if expected is None:
            return True
        if current is None:
            return False
        try:
            return current.resolve() == expected.resolve()
        except OSError:
            try:
                return Path(current) == Path(expected)
            except Exception:
                return False

    def _handle_mcp_tool_event(
        self: MainFrame, event: ToolResultEvent
    ) -> None:
        """Apply requirement changes described by *event*."""

        if not event.payloads:
            return
        if getattr(self, "_shutdown_in_progress", False):
            return
        if not hasattr(self, "model") or not hasattr(self, "panel"):
            return
        current_dir = getattr(self, "current_dir", None)
        if not self._paths_match(current_dir, event.base_path):
            return
        try:
            self._on_agent_tool_results(event.payloads)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Failed to apply MCP tool result event")

    def _on_window_destroy(self: MainFrame, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            self._teardown_mcp_tool_listener()
        event.Skip()

    def _selected_requirement_ids_for_agent(self: MainFrame) -> list[int]:
        ids: list[int] = []
        panel = getattr(self, "panel", None)
        if panel is not None and hasattr(panel, "get_selected_ids"):
            with suppress(Exception):  # pragma: no cover - defensive
                ids.extend(panel.get_selected_ids())
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

    def _agent_batch_targets(self: MainFrame) -> list[BatchTarget]:
        model = getattr(self, "model", None)
        if model is None:
            return []
        targets: list[BatchTarget] = []
        seen: set[str] = set()
        for req_id in self._selected_requirement_ids_for_agent():
            requirement = model.get_by_id(req_id)
            if requirement is None:
                continue
            rid = (requirement.rid or "").strip()
            if not rid:
                fallback = f"{requirement.doc_prefix}{requirement.id}".strip()
                rid = fallback if fallback else str(requirement.id)
            if rid in seen:
                continue
            seen.add(rid)
            title = (requirement.title or "").strip()
            targets.append(
                BatchTarget(
                    requirement_id=requirement.id,
                    rid=rid,
                    title=title,
                )
            )
        return targets

    def _agent_context_messages(self: MainFrame) -> list[dict[str, str]]:
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
        invalid_rids: dict[str, str] = {}

        resolved_any = False
        if selected_ids and model is not None:
            seen_rids: set[str] = set()
            for req_id in selected_ids:
                requirement = model.get_by_id(req_id)
                if requirement is None:
                    unresolved_ids.append(str(req_id))
                    continue

                rid_raw = getattr(requirement, "rid", "") or ""
                rid = rid_raw.strip()
                if not rid:
                    unresolved_ids.append(str(req_id))
                    continue

                resolved_any = True
                try:
                    canonical_prefix, canonical_id = parse_rid(rid)
                except ValueError:
                    if rid not in invalid_rids:
                        invalid_rids[rid] = (
                            "expected format <PREFIX><NUMBER> with a prefix that starts "
                            "with a letter and contains only ASCII letters, digits, or "
                            "underscores"
                        )
                    continue

                expected_prefix = getattr(requirement, "doc_prefix", None)
                if (
                    isinstance(expected_prefix, str)
                    and expected_prefix
                    and canonical_prefix != expected_prefix
                ):
                    if rid not in invalid_rids:
                        invalid_rids[rid] = (
                            "prefix must match the document prefix exactly "
                            f"(expected {expected_prefix})"
                        )
                    continue

                display_rid = f"{canonical_prefix}{canonical_id}"
                if display_rid not in seen_rids:
                    seen_rids.add(display_rid)
                    rid_summary.append(display_rid)
        elif selected_ids:
            unresolved_ids.extend(str(req_id) for req_id in selected_ids)

        if rid_summary:
            lines.append(
                "Selected requirement RIDs: " + ", ".join(rid_summary)
            )
        elif selected_ids:
            if resolved_any:
                lines.append("Selected requirement RIDs: (no unique identifiers)")
            else:
                lines.append("Selected requirement RIDs: (no valid identifiers)")
        else:
            lines.append("Selected requirement RIDs: (none)")

        if invalid_rids:
            formatted_invalids = "; ".join(
                f"{rid} — {reason}" for rid, reason in invalid_rids.items()
            )
            lines.append(
                "Invalid requirement identifiers detected: " + formatted_invalids
            )
            lines.append(
                "Requirement prefixes must start with a letter and may "
                "contain only ASCII letters, digits, or underscores. Adjust "
                "the directory structure or JSON files so each RID follows "
                "the <PREFIX><NUMBER> convention."
            )

        if unresolved_ids:
            lines.append(
                "Unresolved GUI selection ids: " + ", ".join(unresolved_ids)
            )

        return [{"role": "system", "content": "\n".join(lines)}]

    def _agent_context_for_requirement(
        self: MainFrame, requirement_id: int
    ) -> tuple[dict[str, str], ...]:
        model = getattr(self, "model", None)
        if model is None:
            return ()
        requirement = model.get_by_id(requirement_id)
        if requirement is None:
            return ()

        rid = (requirement.rid or "").strip()
        if not rid:
            rid = f"{requirement.doc_prefix}{requirement.id}".strip()
        if not rid:
            rid = str(requirement.id)

        lines: list[str] = ["[Requirement focus]"]
        lines.append(f"Target RID: {rid}")
        if requirement.title:
            lines.append(f"Title: {requirement.title.strip()}")
        statement = requirement.statement.strip()
        lines.append(f"Statement: {statement}" if statement else "Statement: (empty)")
        lines.append(f"Type: {requirement.type.value}")
        lines.append(f"Status: {requirement.status.value}")
        owner = requirement.owner.strip() if requirement.owner else ""
        lines.append(f"Owner: {owner}" if owner else "Owner: (not set)")
        priority = requirement.priority.value if requirement.priority else ""
        if priority:
            lines.append(f"Priority: {priority}")
        source = requirement.source.strip() if requirement.source else ""
        if source:
            lines.append(f"Source: {source}")
        conditions = requirement.conditions.strip()
        if conditions:
            lines.append(f"Conditions: {conditions}")
        rationale = requirement.rationale.strip()
        if rationale:
            lines.append(f"Rationale: {rationale}")
        assumptions = requirement.assumptions.strip()
        if assumptions:
            lines.append(f"Assumptions: {assumptions}")
        notes = requirement.notes.strip()
        if notes:
            lines.append(f"Notes: {notes}")
        if requirement.labels:
            labels_text = ", ".join(sorted(label.strip() for label in requirement.labels if label))
            if labels_text:
                lines.append(f"Labels: {labels_text}")
        if requirement.links:
            link_summaries: list[str] = []
            for link in requirement.links:
                label = link.rid
                if link.suspect:
                    label = f"{label} (suspect)"
                link_summaries.append(label)
            if link_summaries:
                lines.append("Trace links: " + ", ".join(link_summaries))
        if requirement.attachments:
            attachment_labels = [
                att.path for att in requirement.attachments if getattr(att, "path", "")
            ]
            if attachment_labels:
                lines.append("Attachments: " + ", ".join(attachment_labels))

        return (({"role": "system", "content": "\n".join(lines)}),)

    def _on_agent_tool_results(
        self: MainFrame, tool_results: Sequence[Mapping[str, Any]]
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
                logger.warning(
                    "Ignoring agent tool payload because it is not a mapping: %s",
                    _short_repr(payload),
                )
                continue
            if not payload.get("ok", False):
                logger.warning(
                    "Agent tool payload reported failure and was ignored: %s",
                    _short_repr(payload),
                )
                continue
            tool_name_raw = (
                payload.get("tool_name")
                or payload.get("name")
                or payload.get("tool")
            )
            tool_name = str(tool_name_raw) if tool_name_raw else ""
            if not tool_name:
                logger.warning(
                    "Agent tool payload missing tool name: %s",
                    _short_repr(payload),
                )
                continue
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
                    prefix_raw, req_id = parse_rid(rid)
                except ValueError:
                    logger.warning("Agent returned invalid requirement id %r", rid)
                    continue
                if prefix_raw == current_prefix:
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

    def _convert_tool_result_requirement(self: MainFrame, result_payload: Any) -> Requirement | None:
        if not isinstance(result_payload, Mapping):
            logger.warning(
                "Agent tool result has unexpected structure: %s",
                _short_repr(result_payload),
            )
            return None
        rid_raw = result_payload.get("rid")
        if not isinstance(rid_raw, str) or not rid_raw.strip():
            logger.warning(
                "Agent tool result missing requirement id: %s",
                _short_repr(result_payload),
            )
            return None
        rid = rid_raw.strip()
        try:
            prefix_raw, req_id = parse_rid(rid)
        except ValueError:
            logger.warning("Agent returned invalid requirement id %r", rid)
            return None
        prefix = prefix_raw
        canonical_rid = f"{prefix}{req_id}"
        try:
            requirement = requirement_from_dict(
                dict(result_payload),
                doc_prefix=prefix,
                rid=canonical_rid,
            )
        except Exception:
            logger.exception("Failed to parse requirement payload from agent tool")
            return None
        requirement.doc_prefix = prefix
        requirement.rid = canonical_rid
        return requirement

    def on_run_command(self: MainFrame, _event: wx.Event) -> None:
        """Ensure agent chat panel is visible and focused."""

        if not self.agent_chat_menu_item:
            return
        if not self.agent_chat_menu_item.IsChecked():
            self.agent_chat_menu_item.Check(True)
            self.on_toggle_agent_chat(None)
        else:
            self._apply_agent_chat_visibility(persist=False)

    def on_toggle_agent_chat(self: MainFrame, _event: wx.CommandEvent | None) -> None:
        """Toggle agent chat panel visibility."""

        if not self.agent_chat_menu_item:
            return
        self._apply_agent_chat_visibility(persist=True)
