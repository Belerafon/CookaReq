"""Agent chat helpers for the main frame."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

import wx

from ...confirm import ConfirmDecision, RequirementUpdatePrompt
from ...services.requirements import parse_rid
from ...services.user_documents import (
    DEFAULT_MAX_READ_BYTES,
    MAX_ALLOWED_READ_BYTES,
    UserDocumentsService,
)
from ...core.model import Requirement
from ...settings import AppSettings
from ...mcp.events import ToolResultEvent, add_tool_result_listener
from ..agent_chat_panel.batch_runner import BatchTarget

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from .frame import MainFrame


logger = logging.getLogger("cookareq.ui.main_frame.agent")


@dataclass(frozen=True, slots=True)
class _DocumentsTreeRequest:
    """Describe a snapshot request for the documentation tree."""

    documents_root: Path
    max_context_tokens: int
    token_model: str | None
    max_read_bytes: int


@dataclass(slots=True)
class _DocumentsTreeCacheEntry:
    """Store the latest documentation tree snapshot and its timestamp."""

    request: _DocumentsTreeRequest
    snapshot: dict[str, object]
    built_at: datetime


@dataclass(slots=True)
class _DocumentsTreeErrorEntry:
    """Capture the most recent failure while building the documentation tree."""

    request: _DocumentsTreeRequest
    message: str
    occurred_at: datetime


@dataclass(slots=True)
class _DocumentsTreeWorkerResult:
    """Result payload returned by the background worker."""

    job_id: int
    request: _DocumentsTreeRequest
    snapshot: dict[str, object] | None
    error: str | None
    built_at: datetime


def _run_documents_tree_job(
    job_id: int, request: _DocumentsTreeRequest
) -> _DocumentsTreeWorkerResult:
    """Build the documentation tree snapshot for *request*."""

    try:
        service = UserDocumentsService(
            request.documents_root,
            max_context_tokens=request.max_context_tokens,
            token_model=request.token_model,
            max_read_bytes=request.max_read_bytes,
        )
        snapshot = service.list_tree()
        return _DocumentsTreeWorkerResult(
            job_id=job_id,
            request=request,
            snapshot=snapshot,
            error=None,
            built_at=datetime.now(timezone.utc),
        )
    except Exception as exc:  # pragma: no cover - defensive worker catch
        message = getattr(exc, "message", None) or str(exc)
        return _DocumentsTreeWorkerResult(
            job_id=job_id,
            request=request,
            snapshot=None,
            error=message,
            built_at=datetime.now(timezone.utc),
        )


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
    _documents_tree_executor: ThreadPoolExecutor | None = None
    _documents_tree_future: Future[_DocumentsTreeWorkerResult] | None = None
    _documents_tree_cache: _DocumentsTreeCacheEntry | None = None
    _documents_tree_error: _DocumentsTreeErrorEntry | None = None
    _documents_tree_job_id: int = 0
    _documents_tree_pending_job_id: int | None = None
    _documents_tree_current_request: _DocumentsTreeRequest | None = None
    _documents_tree_listener_panel: wx.Window | None = None

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
            self._shutdown_user_documents_cache()
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

        documents_context = self._compose_user_documents_context()
        if documents_context:
            lines.append("")
            lines.extend(documents_context)

        return [{"role": "system", "content": "\n".join(lines)}]

    def _compose_user_documents_context(self: MainFrame) -> list[str]:
        panel = getattr(self, "agent_panel", None)
        if panel is None:
            return []

        self._setup_agent_documents_hooks()
        subdirectory = getattr(panel, "documents_subdirectory", "") or ""
        lines: list[str] = ["[User documentation]"]
        if not subdirectory:
            lines.append("Documentation folder access disabled (no path configured).")
            return lines

        documents_root = getattr(panel, "documents_root", None)
        if documents_root is None:
            lines.append(
                "Documentation folder pending: "
                f"{subdirectory} (open a requirements folder to resolve)."
            )
            return lines

        llm_settings = getattr(self, "llm_settings", None)
        try:
            max_context_tokens = int(
                getattr(llm_settings, "max_context_tokens", 0) or 0
            )
        except Exception:
            max_context_tokens = 0
        if max_context_tokens <= 0:
            max_context_tokens = 1
        token_model = getattr(llm_settings, "model", None)

        mcp_settings = getattr(self, "mcp_settings", None)
        try:
            documents_max_read_kb = int(
                getattr(mcp_settings, "documents_max_read_kb", 0) or 0
            )
        except Exception:
            documents_max_read_kb = 0
        if documents_max_read_kb <= 0:
            max_read_bytes = DEFAULT_MAX_READ_BYTES
        else:
            max_read_bytes = documents_max_read_kb * 1024
        max_read_bytes = max(1, min(MAX_ALLOWED_READ_BYTES, max_read_bytes))

        request = _DocumentsTreeRequest(
            documents_root=Path(documents_root),
            max_context_tokens=max_context_tokens,
            token_model=token_model,
            max_read_bytes=max_read_bytes,
        )

        cache_entry = getattr(self, "_documents_tree_cache", None)
        if cache_entry is not None and cache_entry.request == request:
            lines.extend(self._format_documents_snapshot(cache_entry))
            return lines

        error_entry = getattr(self, "_documents_tree_error", None)
        if error_entry is not None and error_entry.request == request:
            lines.append(
                "Failed to enumerate documentation folder: "
                f"{error_entry.message}"
            )
            return lines

        self._invalidate_documents_cache_if_mismatch(request)
        self._ensure_documents_tree_refresh(request)
        lines.append("Documentation folder is loading…")
        return lines

    # ------------------------------------------------------------------
    def _format_documents_snapshot(
        self: MainFrame, entry: _DocumentsTreeCacheEntry
    ) -> list[str]:
        lines: list[str] = []
        snapshot = entry.snapshot
        request = entry.request
        documents_root = request.documents_root
        lines.append(f"Resolved documentation root: {documents_root}")
        read_limit = snapshot.get("max_read_bytes", request.max_read_bytes)
        read_kib = snapshot.get("max_read_kib")
        if read_kib is None:
            read_kib = read_limit // 1024
        lines.append(
            f"Read chunk limit: {read_limit} bytes (~{read_kib} KiB)"
        )
        tree_model = snapshot.get("token_model")
        if tree_model:
            lines.append(f"Token model for analysis: {tree_model}")
        lines.append(f"Context window tokens: {snapshot.get('max_context_tokens')}")

        tree_text = str(snapshot.get("tree_text", "")).strip()
        if tree_text:
            lines.append("Directory tree:")
            lines.append(tree_text)
        else:
            lines.append("Directory tree: (empty)")
        built_at = entry.built_at.astimezone(timezone.utc)
        lines.append(f"Snapshot generated at: {built_at.isoformat()}")
        return lines

    # ------------------------------------------------------------------
    def _invalidate_documents_cache_if_mismatch(
        self: MainFrame, request: _DocumentsTreeRequest
    ) -> None:
        cache_entry = getattr(self, "_documents_tree_cache", None)
        if cache_entry is not None and cache_entry.request != request:
            self._documents_tree_cache = None
        error_entry = getattr(self, "_documents_tree_error", None)
        if error_entry is not None and error_entry.request != request:
            self._documents_tree_error = None
        current_request = getattr(self, "_documents_tree_current_request", None)
        if current_request is not None and current_request != request:
            self._documents_tree_current_request = None

    # ------------------------------------------------------------------
    def _ensure_documents_tree_refresh(
        self: MainFrame, request: _DocumentsTreeRequest
    ) -> None:
        current_request = getattr(self, "_documents_tree_current_request", None)
        pending_job = getattr(self, "_documents_tree_pending_job_id", None)
        if current_request == request and pending_job is not None:
            return

        future = getattr(self, "_documents_tree_future", None)
        if future is not None and not future.done():
            future.cancel()

        executor = getattr(self, "_documents_tree_executor", None)
        if executor is None:
            executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="CookaReqDocs"
            )
            self._documents_tree_executor = executor

        job_id = getattr(self, "_documents_tree_job_id", 0) + 1
        self._documents_tree_job_id = job_id
        self._documents_tree_pending_job_id = job_id
        self._documents_tree_current_request = request

        worker_future: Future[_DocumentsTreeWorkerResult] = executor.submit(
            _run_documents_tree_job, job_id, request
        )
        self._documents_tree_future = worker_future

        def _deliver(fut: Future[_DocumentsTreeWorkerResult]) -> None:
            try:
                result = fut.result()
            except Exception as exc:  # pragma: no cover - defensive
                message = getattr(exc, "message", None) or str(exc)
                result = _DocumentsTreeWorkerResult(
                    job_id=job_id,
                    request=request,
                    snapshot=None,
                    error=message,
                    built_at=datetime.now(timezone.utc),
                )
            wx.CallAfter(self._handle_documents_tree_result, result)

        worker_future.add_done_callback(_deliver)

    # ------------------------------------------------------------------
    def _handle_documents_tree_result(
        self: MainFrame, result: _DocumentsTreeWorkerResult
    ) -> None:
        if getattr(self, "_shutdown_in_progress", False):
            return
        pending_job_id = getattr(self, "_documents_tree_pending_job_id", None)
        if pending_job_id != result.job_id:
            return
        current_request = getattr(self, "_documents_tree_current_request", None)
        if current_request != result.request:
            return

        self._documents_tree_pending_job_id = None
        self._documents_tree_future = None

        if result.error is None and result.snapshot is not None:
            self._documents_tree_cache = _DocumentsTreeCacheEntry(
                request=result.request,
                snapshot=result.snapshot,
                built_at=result.built_at,
            )
            self._documents_tree_error = None
        else:
            message = result.error or "Unknown error"
            self._documents_tree_cache = None
            self._documents_tree_error = _DocumentsTreeErrorEntry(
                request=result.request,
                message=message,
                occurred_at=result.built_at,
            )

        panel = getattr(self, "agent_panel", None)
        if panel is not None and hasattr(panel, "on_documents_context_changed"):
            with suppress(Exception):
                panel.on_documents_context_changed()

    # ------------------------------------------------------------------
    def _shutdown_user_documents_cache(self: MainFrame) -> None:
        future = getattr(self, "_documents_tree_future", None)
        if future is not None:
            future.cancel()
        self._documents_tree_future = None
        executor = getattr(self, "_documents_tree_executor", None)
        if executor is not None:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:  # pragma: no cover - compatibility guard
                executor.shutdown(wait=False)
        self._documents_tree_executor = None
        self._documents_tree_cache = None
        self._documents_tree_error = None
        self._documents_tree_pending_job_id = None
        self._documents_tree_current_request = None

    # ------------------------------------------------------------------
    def _setup_agent_documents_hooks(self: MainFrame) -> None:
        panel = getattr(self, "agent_panel", None)
        if panel is None:
            return
        if getattr(self, "_documents_tree_listener_panel", None) is panel:
            return
        listener = getattr(panel, "set_documents_root_listener", None)
        if callable(listener):
            listener(self._on_agent_documents_root_changed)
            self._documents_tree_listener_panel = panel

    # ------------------------------------------------------------------
    def _on_agent_documents_root_changed(
        self: MainFrame, documents_root: Path | None
    ) -> None:
        self._invalidate_user_documents_cache()
        if documents_root is None:
            return
        self._documents_tree_current_request = None

    # ------------------------------------------------------------------
    def _invalidate_user_documents_cache(self: MainFrame) -> None:
        future = getattr(self, "_documents_tree_future", None)
        if future is not None:
            future.cancel()
        self._documents_tree_future = None
        self._documents_tree_cache = None
        self._documents_tree_error = None
        self._documents_tree_pending_job_id = None
        self._documents_tree_current_request = None

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
            requirement = Requirement.from_mapping(
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
