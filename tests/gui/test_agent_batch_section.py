import pytest
import wx
import wx.dataview as dv

from app.ui.agent_chat_panel.batch_runner import (
    BatchItem,
    BatchItemStatus,
    BatchTarget,
)
from app.ui.agent_chat_panel.batch_ui import AgentBatchSection, BatchControls


pytestmark = pytest.mark.gui


class DummyPanel(wx.Panel):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent)
        self._is_running = False
        self.input = wx.TextCtrl(self)
        self.status_label = wx.StaticText(self)
        self._controller = type(
            "Controller",
            (),
            {"stop": lambda self: True},
        )()
        self.coordinator = self._controller
        self._batch_target_provider = lambda: [
            BatchTarget(requirement_id=1, rid="REQ-1", title="Sample"),
        ]
        self.layout_refreshes = 0
        self.cancelled_runs: int = 0
        self.batch_resets = 0

    def _refresh_bottom_panel_layout(self) -> None:
        self.layout_refreshes += 1

    def _reset_batch_conversation_tracking(self) -> None:
        self.batch_resets += 1

    def _prepare_batch_attachment(self) -> None:
        return None

    def _clear_batch_attachment(self) -> None:
        return None

    @property
    def is_running(self) -> bool:
        return self._is_running

    def cancel_agent_run(self):
        self.cancelled_runs += 1
        return None


def _make_controls(
    panel: DummyPanel,
    *,
    list_ctrl: dv.DataViewListCtrl | None = None,
) -> BatchControls:
    close_button = wx.Button(panel, label="Close")
    run_button = wx.Button(panel, label="Run")
    stop_button = wx.Button(panel, label="Stop")
    status_label = wx.StaticText(panel)
    progress = wx.Gauge(panel, range=1)
    if list_ctrl is None:
        list_ctrl = dv.DataViewListCtrl(panel)
    return BatchControls(
        panel=panel,
        close_button=close_button,
        run_button=run_button,
        stop_button=stop_button,
        status_label=status_label,
        progress=progress,
        list_ctrl=list_ctrl,
    )


class RunnerWithLifecycle:
    def __init__(self) -> None:
        self.started = None
        self.cancelled = False
        self.skipped = False
        self.reset_called = False
        self._items: list[BatchItem] = []
        self.is_running = False
        self.active_item: BatchItem | None = None

    @property
    def items(self):
        return tuple(self._items)

    def start(self, prompt, targets):
        self.started = (prompt, tuple(targets))
        self._items = [BatchItem(target=targets[0])]
        self.active_item = self._items[0]
        self.is_running = True
        return True

    def cancel_all(self):
        self.cancelled = True
        self.is_running = False

    def request_skip_current(self):
        self.skipped = True

    def handle_completion(self, *, conversation_id, success, error):
        self.is_running = False

    def handle_cancellation(self, *, conversation_id):
        self.is_running = False

    def reset(self):
        self.reset_called = True
        self._items = []
        self.is_running = False


def test_agent_batch_section_handles_start_and_stop(wx_app):
    frame = wx.Frame(None)
    try:
        panel = DummyPanel(frame)
        list_ctrl = dv.DataViewListCtrl(panel)
        list_ctrl.AppendTextColumn("RID")
        list_ctrl.AppendTextColumn("Title")
        list_ctrl.AppendTextColumn("Status")
        list_ctrl.AppendTextColumn("Tool calls")
        list_ctrl.AppendTextColumn("Requirement edits")
        list_ctrl.AppendTextColumn("Tokens")
        controls = _make_controls(panel, list_ctrl=list_ctrl)
        runner = RunnerWithLifecycle()
        section = AgentBatchSection(panel=panel, controls=controls, runner=runner)

        panel.input.SetValue("Plan release")
        section.start_batch()

        assert runner.started is not None
        assert runner.is_running
        assert "Batch started" in panel.status_label.GetLabel()
        assert panel.batch_resets == 1

        section.stop_batch()
        assert runner.cancelled
        assert "Batch cancellation requested" in panel.status_label.GetLabel()
        assert panel.cancelled_runs == 1

        section.close_panel()
        assert runner.reset_called
    finally:
        frame.Destroy()


class ListCtrlProbe:
    def __init__(self) -> None:
        self.rows: list[list[str]] = []
        self.ensure_visible_calls: list[tuple[int, object]] = []

    def Freeze(self) -> None:  # noqa: N802 - wx compatibility
        return None

    def Thaw(self) -> None:  # noqa: N802 - wx compatibility
        return None

    def DeleteAllItems(self) -> None:  # noqa: N802 - wx compatibility
        self.rows.clear()

    def AppendItem(self, values: list[str]) -> None:  # noqa: N802
        self.rows.append(values)

    def GetItemCount(self) -> int:  # noqa: N802
        return len(self.rows)

    def GetColumnCount(self) -> int:  # noqa: N802
        return 1

    def GetColumn(self, _index: int) -> object:  # noqa: N802
        return object()

    def EnsureVisible(self, row: int, column: object) -> None:  # noqa: N802
        self.ensure_visible_calls.append((row, column))


class RunnerWithActiveItem:
    def __init__(self) -> None:
        self.is_running = True
        self._items = [
            BatchItem(
                target=BatchTarget(requirement_id=1, rid="REQ-1", title="One"),
                status=BatchItemStatus.COMPLETED,
            ),
            BatchItem(
                target=BatchTarget(requirement_id=2, rid="REQ-2", title="Two"),
                status=BatchItemStatus.RUNNING,
            ),
            BatchItem(
                target=BatchTarget(requirement_id=3, rid="REQ-3", title="Three"),
                status=BatchItemStatus.PENDING,
            ),
        ]
        self.active_item = self._items[1]

    @property
    def items(self):
        return tuple(self._items)


def test_agent_batch_section_scrolls_to_active_item(wx_app):
    frame = wx.Frame(None)
    try:
        panel = DummyPanel(frame)
        list_ctrl = ListCtrlProbe()
        controls = _make_controls(panel, list_ctrl=list_ctrl)  # type: ignore[arg-type]
        runner = RunnerWithActiveItem()

        AgentBatchSection(panel=panel, controls=controls, runner=runner)

        assert list_ctrl.ensure_visible_calls
        row, _ = list_ctrl.ensure_visible_calls[-1]
        assert row == 1
    finally:
        frame.Destroy()
