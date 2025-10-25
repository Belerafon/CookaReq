"""User-interface helpers for managing batch agent runs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from collections.abc import Callable, Sequence

import logging
import textwrap

import wx
import wx.dataview as dv

from ...i18n import _
from .batch_runner import AgentBatchRunner, BatchItem, BatchItemStatus, BatchTarget

if TYPE_CHECKING:  # pragma: no cover - help type checkers
    from .panel import AgentChatPanel


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BatchControls:
    """Widgets composing the batch queue section."""

    panel: wx.Panel
    close_button: wx.Button
    run_button: wx.Button
    stop_button: wx.Button
    status_label: wx.StaticText
    progress: wx.Gauge
    list_ctrl: dv.DataViewListCtrl


class AgentBatchSection:
    """Coordinator for batch queue lifecycle and related UI."""

    def __init__(
        self,
        *,
        panel: AgentChatPanel,
        controls: BatchControls,
        runner: AgentBatchRunner | None = None,
        target_provider: Callable[[], Sequence[BatchTarget]] | None = None,
    ) -> None:
        """Bind batch controls to the panel, creating a runner when needed."""
        self._panel = panel
        self._controls = controls
        self._target_provider = target_provider
        self._runner = runner or AgentBatchRunner(
            submit_prompt=panel._submit_batch_prompt,
            create_conversation=panel._create_batch_conversation,
            ensure_conversation_id=lambda conv: conv.conversation_id,
            on_state_changed=self.update_ui,
            context_factory=panel._build_batch_context,
            prepare_conversation=panel._prepare_batch_conversation,
        )
        controls.run_button.Bind(wx.EVT_BUTTON, self._handle_run_request)
        controls.stop_button.Bind(wx.EVT_BUTTON, self._handle_stop_request)
        controls.close_button.Bind(wx.EVT_BUTTON, self._handle_close_request)
        self.update_ui()

    # ------------------------------------------------------------------
    @property
    def runner(self) -> AgentBatchRunner:
        """Expose the batch runner handling work execution."""
        return self._runner

    # ------------------------------------------------------------------
    def start_batch(self) -> None:
        """Start processing the configured batch queue if idle."""
        if self._panel.is_running:
            return
        runner = self._runner
        if runner.is_running:
            return
        prompt_text = self._panel.input.GetValue().strip()
        if not prompt_text:
            self._panel.status_label.SetLabel(
                _("Enter a prompt before starting a batch")
            )
            self._panel.input.SetFocus()
            return
        targets = self._collect_targets()
        if not targets:
            self._panel.status_label.SetLabel(
                _("Select at least one requirement in the list to run a batch")
            )
            return
        self._panel._reset_batch_conversation_tracking()
        if not runner.start(prompt_text, targets):
            self._panel.status_label.SetLabel(_("Unable to start batch queue"))
            return
        self._panel.status_label.SetLabel(
            _("Batch started: {count} requirements").format(count=len(targets))
        )
        self.update_ui()

    # ------------------------------------------------------------------
    def stop_batch(self) -> None:
        """Cancel all pending work and stop any active agent run."""
        runner = self._runner
        if not runner.items:
            return
        runner.cancel_all()
        self._panel.cancel_agent_run()
        self._panel.status_label.SetLabel(_("Batch cancellation requested"))
        self.update_ui()

    # ------------------------------------------------------------------
    def request_skip_current(self) -> None:
        """Skip the currently running batch item if possible."""
        self._runner.request_skip_current()

    # ------------------------------------------------------------------
    def close_panel(self) -> None:
        """Reset the batch queue and hide the panel."""
        runner = self._runner
        if runner.is_running:
            dialog = wx.MessageDialog(
                self._controls.panel,
                _("Batch processing is still running. Stop and close the queue?"),
                _("Stop batch processing?"),
                style=wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
            )
            try:
                if dialog.ShowModal() != wx.ID_YES:
                    return
            finally:
                dialog.Destroy()
            self.stop_batch()
        runner.reset()

    # ------------------------------------------------------------------
    def notify_completion(
        self,
        *,
        conversation_id: str,
        success: bool,
        error: str | None,
        tool_call_count: int | None = None,
        requirement_edit_count: int | None = None,
        token_count: int | None = None,
        tokens_approximate: bool = False,
    ) -> None:
        """Record completion state for ``conversation_id`` and refresh controls."""
        self._runner.handle_completion(
            conversation_id=conversation_id,
            success=success,
            error=error,
            tool_call_count=tool_call_count,
            requirement_edit_count=requirement_edit_count,
            token_count=token_count,
            tokens_approximate=tokens_approximate,
        )
        self.update_ui()

    # ------------------------------------------------------------------
    def notify_cancellation(self, *, conversation_id: str) -> None:
        """Record cancellation for ``conversation_id`` and refresh controls."""
        self._runner.handle_cancellation(conversation_id=conversation_id)
        self.update_ui()

    # ------------------------------------------------------------------
    def update_ui(self) -> None:
        """Synchronize button state, status text, and progress indicators."""
        panel = self._controls.panel
        runner = self._runner
        status_label = self._controls.status_label
        progress = self._controls.progress
        run_button = self._controls.run_button
        stop_button = self._controls.stop_button

        if not runner.items:
            panel.Hide()
            status_label.SetLabel(_("Select requirements and run a batch"))
            progress.SetRange(1)
            progress.SetValue(0)
            run_button.Enable(not self._panel.is_running)
            stop_button.Enable(False)
            self._panel._refresh_bottom_panel_layout()
            return

        panel.Show()
        self._refresh_table(runner.items)

        total = len(runner.items)
        completed_count = sum(1 for item in runner.items if item.status is BatchItemStatus.COMPLETED)
        failed_count = sum(1 for item in runner.items if item.status is BatchItemStatus.FAILED)
        cancelled_count = sum(1 for item in runner.items if item.status is BatchItemStatus.CANCELLED)
        pending_count = sum(1 for item in runner.items if item.status is BatchItemStatus.PENDING)

        if total <= 0:
            progress.SetRange(1)
            progress.SetValue(0)
        else:
            completed_steps = completed_count + failed_count + cancelled_count
            progress.SetRange(total)
            progress.SetValue(min(completed_steps, total))

        if runner.is_running and runner.active_item is not None:
            try:
                active_index = runner.items.index(runner.active_item)
            except ValueError:
                active_index = None
            current = active_index + 1 if active_index is not None else completed_count + 1
            summary = _(
                "Running {current} of {total} requirements (done: {done}, failed: {failed}, cancelled: {cancelled})"
            ).format(
                current=current,
                total=total,
                done=completed_count,
                failed=failed_count,
                cancelled=cancelled_count,
            )
        elif pending_count:
            summary = _(
                "Batch ready: {total} requirements queued ({pending} pending)"
            ).format(total=total, pending=pending_count)
        else:
            summary = _(
                "Batch finished: {done} completed, {failed} failed, {cancelled} cancelled"
            ).format(
                done=completed_count,
                failed=failed_count,
                cancelled=cancelled_count,
            )

        status_label.SetLabel(summary)
        run_button.Enable(not runner.is_running and not self._panel.is_running)
        stop_button.Enable(runner.is_running)
        self._panel._refresh_bottom_panel_layout()

    # ------------------------------------------------------------------
    def _collect_targets(self) -> list[BatchTarget]:
        provider = self._target_provider or self._panel._batch_target_provider
        if provider is None:
            return []
        try:
            candidates = list(provider())
        except Exception:
            logger.exception("Failed to collect batch targets")
            return []
        unique: list[BatchTarget] = []
        seen: set[str] = set()
        for item in candidates:
            if not isinstance(item, BatchTarget):
                continue
            rid = item.rid.strip() if item.rid else ""
            key = rid or str(item.requirement_id)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    # ------------------------------------------------------------------
    def _refresh_table(self, items: Sequence[BatchItem]) -> None:
        control = self._controls.list_ctrl
        control.DeleteAllItems()
        for item in items:
            rid = item.target.rid.strip() if item.target.rid else ""
            if not rid:
                rid = str(item.target.requirement_id)
            title = item.target.title.strip() if item.target.title else ""
            if not title:
                title = rid
            status_text = self._format_status(item)
            if item.status in {
                BatchItemStatus.COMPLETED,
                BatchItemStatus.FAILED,
                BatchItemStatus.CANCELLED,
            }:
                tool_calls_text = str(item.tool_call_count)
                edits_text = str(item.requirement_edit_count)
                tokens_text = self._format_token_usage(
                    item.token_count, item.tokens_approximate
                )
            else:
                tool_calls_text = ""
                edits_text = ""
                tokens_text = ""
            control.AppendItem(
                [rid, title, status_text, tool_calls_text, edits_text, tokens_text]
            )

    # ------------------------------------------------------------------
    def _format_status(self, item: BatchItem) -> str:
        labels = {
            BatchItemStatus.PENDING: _("Pending"),
            BatchItemStatus.RUNNING: _("Running"),
            BatchItemStatus.COMPLETED: _("Completed"),
            BatchItemStatus.FAILED: _("Failed"),
            BatchItemStatus.CANCELLED: _("Cancelled"),
        }
        label = labels.get(item.status, item.status.name.title())
        if item.error:
            snippet = textwrap.shorten(str(item.error), width=80, placeholder="…")
            label = f"{label} — {snippet}"
        return label

    # ------------------------------------------------------------------
    @staticmethod
    def _format_token_usage(token_count: int | None, approximate: bool) -> str:
        if token_count is None:
            return ""
        value = f"{token_count}"
        return f"~{value}" if approximate else value

    # ------------------------------------------------------------------
    def _handle_run_request(self, _event: wx.Event) -> None:
        self.start_batch()

    # ------------------------------------------------------------------
    def _handle_stop_request(self, _event: wx.Event) -> None:
        self.stop_batch()

    # ------------------------------------------------------------------
    def _handle_close_request(self, _event: wx.Event) -> None:
        self.close_panel()


__all__ = ["AgentBatchSection", "BatchControls"]

