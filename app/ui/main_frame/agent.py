"""Agent chat helpers for the main frame."""

from __future__ import annotations

from typing import TYPE_CHECKING

import wx

from ...agent import LocalAgent
from ...settings import AppSettings

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from .frame import MainFrame


class MainFrameAgentMixin:
    """Provide agent chat integration and shortcuts."""

    def _create_agent(self: "MainFrame") -> LocalAgent:
        """Construct ``LocalAgent`` using current settings."""

        from . import confirm

        settings = AppSettings(llm=self.llm_settings, mcp=self.mcp_settings)
        return LocalAgent(settings=settings, confirm=confirm)

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
        if selected_ids and model is not None:
            lines.append(f"Selected requirements ({len(selected_ids)}):")
            for req_id in selected_ids:
                requirement = model.get_by_id(req_id)
                if requirement is None:
                    lines.append(f"- id={req_id}")
                    continue
                rid = getattr(requirement, "rid", "") or ""
                rid = rid.strip()
                req_prefix = (
                    getattr(requirement, "doc_prefix", None)
                    or prefix
                    or ""
                )
                if not rid:
                    rid = f"{req_prefix}{requirement.id}" if req_prefix else str(
                        requirement.id
                    )
                title = getattr(requirement, "title", "") or ""
                title = title.strip()
                header = f"- {rid} (id={requirement.id}"
                if req_prefix:
                    header += f", prefix={req_prefix}"
                header += ")"
                if title:
                    header += f" — {title}"
                lines.append(header)
        else:
            lines.append("Selected requirements: (none)")

        return [{"role": "system", "content": "\n".join(lines)}]

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
