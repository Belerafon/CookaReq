import pytest


pytestmark = pytest.mark.gui


def test_agent_batch_section_handles_start_and_stop(wx_app):
    import wx
    import wx.dataview as dv

    from app.ui.agent_chat_panel.batch_runner import BatchItem, BatchTarget
    from app.ui.agent_chat_panel.batch_ui import AgentBatchSection, BatchControls

    frame = wx.Frame(None)

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

        @property
        def is_running(self) -> bool:
            return self._is_running

        def cancel_agent_run(self):
            self.cancelled_runs += 1
            return None

    panel = DummyPanel(frame)

    close_button = wx.Button(panel, label="Close")
    run_button = wx.Button(panel, label="Run")
    stop_button = wx.Button(panel, label="Stop")
    status_label = wx.StaticText(panel)
    progress = wx.Gauge(panel, range=1)
    list_ctrl = dv.DataViewListCtrl(panel)

    controls = BatchControls(
        panel=panel,
        close_button=close_button,
        run_button=run_button,
        stop_button=stop_button,
        status_label=status_label,
        progress=progress,
        list_ctrl=list_ctrl,
    )

    class StubRunner:
        def __init__(self) -> None:
            self.started = None
            self.cancelled = False
            self.skipped = False
            self.reset_called = False
            self._items: list[BatchItem] = []
            self.is_running = False
            self.active_item = None

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

    runner = StubRunner()
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

    frame.Destroy()
