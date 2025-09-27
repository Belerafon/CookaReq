"""User-interface helpers for managing batch agent runs."""

from __future__ import annotations

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
        self.update_ui()

    # ------------------------------------------------------------------
    @property
    def runner(self) -> AgentBatchRunner:
        return self._runner

    # ------------------------------------------------------------------
    def start_batch(self) -> None:
        if self._panel._is_running:
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
        if not runner.start(prompt_text, targets):
            self._panel.status_label.SetLabel(_("Unable to start batch queue"))
            return
        self._panel.status_label.SetLabel(
            _("Batch started: {count} requirements").format(count=len(targets))
        )
        self.update_ui()

    # ------------------------------------------------------------------
    def stop_batch(self) -> None:
        runner = self._runner
        if not runner.items:
            return
        runner.cancel_all()
        controller = self._panel._controller
        if controller is not None:
            controller.stop()
        self._panel.status_label.SetLabel(_("Batch cancellation requested"))
        self.update_ui()

    # ------------------------------------------------------------------
    def request_skip_current(self) -> None:
        self._runner.request_skip_current()

    # ------------------------------------------------------------------
    def notify_completion(
        self,
        *,
        conversation_id: str,
        success: bool,
        error: str | None,
    ) -> None:
        self._runner.handle_completion(
            conversation_id=conversation_id,
            success=success,
            error=error,
        )
        self.update_ui()

    # ------------------------------------------------------------------
    def notify_cancellation(self, *, conversation_id: str) -> None:
        self._runner.handle_cancellation(conversation_id=conversation_id)
        self.update_ui()

    # ------------------------------------------------------------------
    def update_ui(self) -> None:
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
            run_button.Enable(not self._panel._is_running)
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
        run_button.Enable(not runner.is_running and not self._panel._is_running)
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
            control.AppendItem([rid, title, status_text])

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
    def _handle_run_request(self, _event: wx.Event) -> None:
        self.start_batch()

    # ------------------------------------------------------------------
    def _handle_stop_request(self, _event: wx.Event) -> None:
        self.stop_batch()


__all__ = ["AgentBatchSection", "BatchControls"]

