import json
import sqlite3
from pathlib import Path
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, TYPE_CHECKING
from collections.abc import Callable, Mapping, Sequence

from app.confirm import ConfirmDecision, reset_requirement_update_preference, set_confirm, set_requirement_update_confirm
from app.llm.spec import SYSTEM_PROMPT
from app.llm.tokenizer import TokenCountResult
from app.ui.agent_chat_panel.token_usage import format_token_quantity
from app.agent.run_contract import AgentEvent, AgentEventLog, AgentRunPayload, LlmStep, LlmTrace, ToolResultSnapshot
from app.ui.agent_chat_panel import AgentProjectSettings, RequirementConfirmPreference
from app.ui.agent_chat_panel.panel import AttachmentValidationError, MAX_ATTACHMENT_BYTES
from app.ui.agent_chat_panel.components.segments import (
    MessageSegmentPanel,
    TurnCard,
)
from app.ui.agent_chat_panel.execution import _AgentRunHandle
from app.ui.agent_chat_panel.batch_runner import BatchItemStatus, BatchTarget
from app.ui.agent_chat_panel.view_model import (
    TranscriptEntry,
    build_conversation_timeline,
    build_transcript_segments,
)
from app.ui.agent_chat_panel.log_export import compose_transcript_text
from app.ui.agent_chat_panel.time_formatting import format_entry_timestamp
from app.ui.agent_chat_panel.layout import PRIMARY_ACTION_IDLE_LABEL
from app.ui.chat_entry import ChatConversation, ChatEntry
from app.ui.agent_chat_panel.history_store import HistoryStore
from app.ui.widgets.chat_message import MessageBubble
from app.util.cancellation import CancellationEvent
from app import i18n

import pytest

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    import wx
else:  # pragma: no cover - runtime stub to satisfy static analysis
    wx = None  # type: ignore[assignment]


pytestmark = [pytest.mark.gui, pytest.mark.integration]


HISTORY_FILENAME = "agent_chats.sqlite"

_ = i18n._


def history_db_path(tmp_path: Path) -> Path:
    return tmp_path / HISTORY_FILENAME


def read_history_database(path: Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        metadata = {
            row["key"]: row["value"]
            for row in conn.execute("SELECT key, value FROM metadata")
        }
        conversations: list[dict[str, Any]] = []
        for row in conn.execute(
            """
            SELECT id, position, title, created_at, updated_at, preview
            FROM conversations
            ORDER BY position
            """
        ):
            conversation = dict(row)
            conversation["entries"] = [
                json.loads(entry_row["payload"])
                for entry_row in conn.execute(
                    """
                    SELECT payload
                    FROM entries
                    WHERE conversation_id = ?
                    ORDER BY position
                    """,
                    (row["id"],),
                )
            ]
            conversations.append(conversation)
        return metadata, conversations
    finally:
        conn.close()


VALIDATION_ERROR_MESSAGE = (
    "Invalid arguments for update_requirement_field: value: 'in_last_review' "
    "is not one of ['draft', 'in_review', 'approved', 'baselined', 'retired']"
)


class SynchronousAgentCommandExecutor:
    """Executor that runs submitted functions immediately on the caller thread."""

    def submit(self, func):
        future: Future = Future()
        if not future.set_running_or_notify_cancel():
            return future
        try:
            result = func()
        except BaseException as exc:  # pragma: no cover - defensive
            future.set_exception(exc)
        else:
            future.set_result(result)
        return future


def flush_wx_events(wx, count: int = 3) -> None:
    app = wx.GetApp()
    for _ in range(count):
        if not app:
            break
        for _ in range(50):
            if not app.HasPendingEvents():
                break
            app.ProcessPendingEvents()


class FakeKeyEvent:
    """Minimal stand-in for :class:`wx.KeyEvent` used in key handling tests."""

    def __init__(
        self,
        key_code: int,
        *,
        control: bool = False,
        command: bool = False,
    ) -> None:
        self._key_code = key_code
        self._control = control
        self._command = command
        self.skipped = False

    def GetKeyCode(self) -> int:
        return self._key_code

    def ControlDown(self) -> bool:
        return self._control

    def CmdDown(self) -> bool:
        return self._command

    def Skip(self) -> None:
        self.skipped = True


def build_entry_timeline(
    *,
    prompt: str = "user",
    response: str = "assistant",
    prompt_at: str = "2025-01-01T10:00:00+00:00",
    response_at: str = "2025-01-01T10:01:00+00:00",
    context_messages: Sequence[dict[str, Any]] | None = None,
    reasoning_segments: Sequence[dict[str, Any]] | None = None,
    tool_results: Sequence[dict[str, Any]] | None = None,
    raw_payload: Any | None = None,
    regenerated: bool = False,
) -> tuple[ChatConversation, TranscriptEntry]:
    tool_payloads = list(tool_results or ())
    if tool_payloads:
        if isinstance(raw_payload, Mapping):
            raw_payload = {**raw_payload, "tool_results": tool_payloads}
        else:
            raw_payload = {"tool_results": tool_payloads}

    entry = ChatEntry(
        prompt=prompt,
        response=response,
        tokens=0,
        display_response=response,
        prompt_at=prompt_at,
        response_at=response_at,
        context_messages=tuple(context_messages or ()),
        reasoning=tuple(reasoning_segments or ()),
        raw_result=raw_payload,
        regenerated=regenerated,
    )
    conversation = ChatConversation(
        conversation_id="test-conversation",
        title=None,
        created_at=prompt_at,
        updated_at=response_at or prompt_at,
    )
    conversation.replace_entries([entry])
    timeline = build_conversation_timeline(conversation)
    return conversation, timeline.entries[0]


def get_entry_segments(
    conversation: ChatConversation, entry: TranscriptEntry
) -> list:
    segments = build_transcript_segments(conversation)
    return [
        segment for segment in segments.segments if segment.entry_id == entry.entry_id
    ]


def render_turn_card(
    parent,
    *,
    conversation: ChatConversation,
    entry: TranscriptEntry,
    layout_hints: Mapping[str, int] | None = None,
    on_layout_hint: Callable[[str, int], None] | None = None,
    on_regenerate: Callable[[], None] | None = None,
    regenerate_enabled: bool = True,
) -> TurnCard:
    if layout_hints is not None:
        conversation.entries[entry.entry_index].layout_hints = dict(layout_hints)
    entry_segments = get_entry_segments(conversation, entry)
    card = TurnCard(
        parent,
        entry_id=entry.entry_id,
        entry_index=entry.entry_index,
        on_layout_hint=on_layout_hint,
    )
    card.update(
        segments=entry_segments,
        on_regenerate=on_regenerate,
        regenerate_enabled=regenerate_enabled,
    )
    return card


def bubble_header_text(bubble: MessageBubble) -> str:
    import wx  # noqa: PLC0415 - imported for GUI helper

    for child in bubble.GetChildren():
        if not isinstance(child, wx.Panel):
            continue
        for grand_child in child.GetChildren():
            if isinstance(grand_child, wx.StaticText):
                return grand_child.GetLabel()
    return ""


def bubble_body_text(bubble: MessageBubble) -> str:
    return getattr(bubble, "_text_value", "")


def collapsible_label(pane) -> str:
    import wx  # noqa: PLC0415 - GUI helper

    if not isinstance(pane, wx.CollapsiblePane):
        return ""
    label = pane.GetLabel()
    if label:
        return label
    name = pane.GetName()
    if name:
        return name
    button = pane.GetButton() if hasattr(pane, "GetButton") else None
    if button is not None:
        try:
            return button.GetLabel()
        except Exception:  # pragma: no cover - defensive
            return ""
    return ""


def collect_message_bubbles(window: "wx.Window") -> list[MessageBubble]:
    bubbles: list[MessageBubble] = []
    for child in window.GetChildren():
        if isinstance(child, MessageBubble):
            bubbles.append(child)
        bubbles.extend(collect_message_bubbles(child))
    return bubbles


def collect_collapsible_panes(window: "wx.Window") -> list["wx.CollapsiblePane"]:
    import wx  # noqa: PLC0415 - GUI helper

    panes: list[wx.CollapsiblePane] = []
    for child in window.GetChildren():
        if isinstance(child, wx.CollapsiblePane):
            panes.append(child)
        panes.extend(collect_collapsible_panes(child))
    return panes


def write_transcript_artifacts(panel, artifact_dir: Path, request) -> tuple[Path, Path]:
    conversation_text = panel.get_transcript_text()
    log_text = panel.get_transcript_log_text()

    conversation_path = artifact_dir / "copied_conversation.txt"
    log_path = artifact_dir / "copied_technical_log.txt"

    conversation_path.write_text(conversation_text, encoding="utf-8")
    log_path.write_text(log_text, encoding="utf-8")

    request.node.add_report_section("call", "copied_conversation", conversation_text)
    request.node.add_report_section("call", "copied_technical_log", log_text)

    return conversation_path, log_path


def test_user_attachment_metadata_display(wx_app):
    wx = pytest.importorskip("wx")

    frame = wx.Frame(None)
    panel = None
    try:
        token_info = TokenCountResult.exact(120, model="test-model").to_dict()
        conversation, entry_timeline = build_entry_timeline(
            prompt="Hello",  # ensure prompt bubble renders
            context_messages=[
                {
                    "role": "user",
                    "content": "[Attachment: report.txt]\nfirst line\nsecond line",
                    "metadata": {
                        "attachment": {
                            "filename": "report.txt",
                            "size_bytes": 2048,
                            "token_info": token_info,
                            "preview_lines": ["first line", "second line"],
                        }
                    },
                }
            ],
        )
        panel = render_turn_card(
            frame,
            conversation=conversation,
            entry=entry_timeline,
            layout_hints=entry_timeline.layout_hints,
        )
        bubbles = collect_message_bubbles(panel)
        attachment_bubble = next(
            b for b in bubbles if "Attachment:" in bubble_body_text(b)
        )
        text = bubble_body_text(attachment_bubble)
        assert "report.txt" in text
        assert "2.00 KB" in text
        assert "Tokens: 0.12 k tokens" in text
        assert "Preview:" in text
        assert "first line" in text
        assert "second line" in text
    finally:
        if panel is not None:
            panel.Destroy()
        frame.Destroy()


def find_collapsible_by_name(
    window: "wx.Window", name: str
) -> "wx.CollapsiblePane | None":
    for pane in collect_collapsible_panes(window):
        if pane.GetName() == name:
            return pane
    return None


def install_monotonic_stub(monkeypatch, *, elapsed_seconds: int = 5) -> str:
    state = {"calls": 0, "value": 0.0}

    def fake_monotonic() -> float:
        calls = state["calls"]
        state["calls"] += 1
        if calls == 0:
            state["value"] = 0.0
        elif calls == 1:
            state["value"] = float(elapsed_seconds)
        else:
            state["value"] += float(elapsed_seconds)
        return state["value"]

    monkeypatch.setattr(
        "app.ui.agent_chat_panel.panel.time.monotonic",
        fake_monotonic,
    )
    minutes, seconds = divmod(int(elapsed_seconds), 60)
    return f"{minutes:02d}:{seconds:02d}"


def create_panel(
    tmp_path,
    wx_app,
    agent,
    executor=None,
    context_provider=None,
    context_window=4096,
    confirm_preference=None,
    persist_confirm_preference=None,
    use_default_executor: bool = False,
):
    wx = pytest.importorskip("wx")
    from app.ui.agent_chat_panel import AgentChatPanel
    import app.confirm as confirm_mod

    frame = wx.Frame(None)
    command_executor = None if use_default_executor else executor or SynchronousAgentCommandExecutor()
    panel = AgentChatPanel(
        frame,
        agent_supplier=lambda **_overrides: agent,
        history_path=history_db_path(tmp_path),
        command_executor=command_executor,
        context_provider=context_provider,
        context_window_resolver=lambda: context_window,
        confirm_preference=confirm_preference,
        persist_confirm_preference=persist_confirm_preference,
    )
    panel.set_project_settings_path(tmp_path / "agent_settings.json")

    previous_confirm = confirm_mod._callback
    previous_update = confirm_mod._requirement_update_callback
    reset_requirement_update_preference()
    set_confirm(lambda _message: True)
    set_requirement_update_confirm(lambda _prompt: ConfirmDecision.YES)

    # The frame remains hidden during tests; controls are created off-screen.

    def _restore_confirm() -> None:
        confirm_mod._callback = previous_confirm
        confirm_mod._requirement_update_callback = previous_update
        reset_requirement_update_preference()

    panel._restore_confirm = _restore_confirm
    return wx, frame, panel


def destroy_panel(frame, panel):
    restore = getattr(panel, "_restore_confirm", None)
    if callable(restore):
        restore()
    panel.Destroy()
    frame.Destroy()


def test_history_list_remains_interactive_during_agent_run(
    tmp_path, wx_app, monkeypatch
):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):
            return {"ok": True, "error": None, "result": {}}

    wx, frame, panel = create_panel(tmp_path, wx_app, agent=DummyAgent())

    try:
        flush_wx_events(wx)
        panel._create_conversation(persist=False)
        flush_wx_events(wx)
        assert panel.history_list.GetItemCount() >= 2

        panel._session.begin_run(tokens=TokenCountResult.exact(0))
        assert panel._session.is_running
        assert panel.history_list.IsEnabled()

        target_row = 0
        target_id = panel.conversations[target_row].conversation_id
        panel.history_list.SelectRow(target_row)
        item = panel.history_list.RowToItem(target_row)

        class _FakeSelectionEvent:
            def __init__(self, data_view_item):
                self._item = data_view_item
                self.skipped = False

            def GetItem(self):
                return self._item

            def Skip(self):
                self.skipped = True

        panel._history_view._on_select_history(_FakeSelectionEvent(item))
        assert panel.active_conversation_id == target_id

        popup_labels: list[list[str]] = []
        delete_enabled: list[bool] = []

        def fake_popup(menu):
            items = list(menu.GetMenuItems())
            popup_labels.append([item.GetItemLabelText() for item in items])
            delete_items = [
                item
                for item in items
                if "Delete" in item.GetItemLabelText()
            ]
            assert delete_items, "expected delete option in context menu"
            delete_enabled.append(all(item.IsEnabled() for item in delete_items))

        monkeypatch.setattr(panel.history_list, "PopupMenu", fake_popup)
        panel._history_view._show_context_menu(target_row)
        assert popup_labels != []
        assert delete_enabled == [False]
    finally:
        panel._session.finalize_run()
        destroy_panel(frame, panel)


def test_agent_run_updates_original_conversation_after_switch(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):
            return {"ok": True, "result": {}}

    wx, frame, panel = create_panel(tmp_path, wx_app, agent=DummyAgent())

    try:
        conversation_a = panel._ensure_active_conversation()
        prompt_at = "2025-01-01T00:00:00+00:00"
        pending_entry = panel._add_pending_entry(
            conversation_a,
            "hello",
            prompt_at=prompt_at,
            context_messages=None,
        )

        handle = _AgentRunHandle(
            run_id=1,
            prompt="hello",
            prompt_tokens=TokenCountResult.exact(1),
            cancel_event=CancellationEvent(),
            prompt_at=prompt_at,
        )
        handle.conversation_id = conversation_a.conversation_id
        handle.pending_entry = pending_entry

        class _CoordinatorStub:
            def __init__(self):
                self.reset_calls: list[_AgentRunHandle] = []

            def reset_active_handle(self, handle):
                self.reset_calls.append(handle)

        panel._coordinator = _CoordinatorStub()

        panel._session.begin_run(tokens=TokenCountResult.exact(0))
        panel._on_new_chat(None)

        conversation_b = panel._get_active_conversation()
        assert conversation_b is not None
        assert conversation_b.conversation_id != conversation_a.conversation_id

        panel._finalize_prompt("hello", {"ok": True, "result": {}}, handle)

        assert not panel._session.is_running
        assert panel.active_conversation_id == conversation_b.conversation_id

        updated = panel._get_conversation_by_id(conversation_a.conversation_id)
        assert updated is not None
        assert updated.entries
        entry = updated.entries[-1]
        assert entry.response
        assert entry.response_at is not None
    finally:
        destroy_panel(frame, panel)


def test_batch_runner_stops_after_consecutive_tool_errors(tmp_path, wx_app):
    class ExplodingMessage:
        def __str__(self) -> str:  # pragma: no cover - exercised indirectly
            raise RuntimeError("boom")

        __repr__ = __str__

    class FaultyAgent:
        def __init__(self) -> None:
            self.calls = 0

        def run_command(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"ok": True, "result": "done"}
            return {
                "ok": False,
                "status": "failed",
                "result": "",
                "diagnostic": {"error": {"message": ExplodingMessage()}},
                "agent_stop_reason": {
                    "type": "consecutive_tool_errors",
                    "count": 3,
                    "max_consecutive_tool_errors": 3,
                },
            }

    agent = FaultyAgent()

    wx, frame, panel = create_panel(
        tmp_path,
        wx_app,
        agent=agent,
        use_default_executor=True,
    )

    try:
        flush_wx_events(wx)
        panel._batch_section._target_provider = lambda: [
            BatchTarget(requirement_id=1, rid="REQ-1", title="First"),
            BatchTarget(requirement_id=2, rid="REQ-2", title="Second"),
        ]
        panel.input.SetValue("Fix the issue")
        flush_wx_events(wx, count=5)
        panel._batch_section.start_batch()
        flush_wx_events(wx, count=30)
        runner = panel._batch_section.runner
        assert not runner.is_running
        assert len(runner.items) == 2
        first, second = runner.items
        assert first.status is BatchItemStatus.COMPLETED
        assert second.status is BatchItemStatus.FAILED
        assert second.error
        assert not panel._session.is_running

        failure_conversation = None
        for conversation in panel.conversations:
            if conversation.title and conversation.title.endswith("REQ-2"):
                failure_conversation = conversation
                break
        assert failure_conversation is not None
        assert failure_conversation.entries, "expected entries recorded for failed batch item"
        failure_entry = failure_conversation.entries[-1]
        assert failure_entry.display_response != _("Working")
    finally:
        destroy_panel(frame, panel)


def test_batch_context_reuses_attachment_for_entire_queue(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):  # pragma: no cover - simple stub
            return {"ok": True, "result": {}}

    wx, frame, panel = create_panel(tmp_path, wx_app, agent=DummyAgent())

    try:
        flush_wx_events(wx)
        panel._batch_context_provider = lambda _rid: ()
        attachment_path = tmp_path / "batch_attachment.txt"
        attachment_path.write_text("Line one\nLine two")

        attachment = panel._load_attachment(attachment_path)
        panel._pending_attachment = attachment
        panel._prepare_batch_attachment()

        first_context = panel._build_batch_context(
            BatchTarget(requirement_id=1, rid="REQ-1", title="First"),
        )
        assert first_context is not None
        first_attachment = first_context[0]["metadata"]["attachment"]
        assert first_attachment["filename"] == "batch_attachment.txt"

        second_context = panel._build_batch_context(
            BatchTarget(requirement_id=2, rid="REQ-2", title="Second"),
        )
        assert second_context is not None
        second_attachment = second_context[0]["metadata"]["attachment"]
        assert second_attachment["filename"] == "batch_attachment.txt"

        assert panel._pending_attachment is attachment
        panel._clear_batch_attachment()
        assert panel._pending_attachment is None
    finally:
        destroy_panel(frame, panel)


def test_batch_conversation_creation_respects_manual_selection(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):
            return {"ok": True, "error": None, "result": {}}

    wx, frame, panel = create_panel(tmp_path, wx_app, agent=DummyAgent())

    try:
        flush_wx_events(wx)
        panel._reset_batch_conversation_tracking()
        first_batch = panel._create_batch_conversation()
        flush_wx_events(wx)
        assert panel.active_conversation_id == first_batch.conversation_id

        panel._activate_conversation_by_index(
            0, refresh_history=False, _source="history_row"
        )
        flush_wx_events(wx)
        selected_id = panel.active_conversation_id
        assert selected_id == panel.conversations[0].conversation_id

        second_batch = panel._create_batch_conversation()
        flush_wx_events(wx)
        assert panel.active_conversation_id == selected_id
        assert second_batch.conversation_id != selected_id

        previous_batch_index = panel.conversations.index(first_batch)
        panel._activate_conversation_by_index(
            previous_batch_index, refresh_history=False, _source="history_row"
        )
        flush_wx_events(wx)
        assert panel.active_conversation_id == first_batch.conversation_id

        third_batch = panel._create_batch_conversation()
        flush_wx_events(wx)
        assert panel.active_conversation_id == third_batch.conversation_id
    finally:
        destroy_panel(frame, panel)


def test_agent_chat_panel_initial_run_updates_primary_button(
    tmp_path, wx_app, monkeypatch
):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):
            return {"ok": True, "error": None, "result": {}}

    wx = pytest.importorskip("wx")
    from app.ui.agent_chat_panel.components.view import AgentChatView

    triggered = {"armed": False}
    original_build = AgentChatView.build

    def build_with_pending(self, *args, **kwargs):
        if not triggered["armed"]:
            triggered["armed"] = True
            wx.CallAfter(
                self._panel._session.begin_run, tokens=TokenCountResult.exact(0)
            )
            flush_wx_events(wx)
        return original_build(self, *args, **kwargs)

    monkeypatch.setattr(AgentChatView, "build", build_with_pending)

    wx_module, frame, panel = create_panel(tmp_path, wx_app, agent=DummyAgent())

    try:
        assert wx_module is wx
        flush_wx_events(wx)
        assert panel._session.is_running
        assert panel._primary_action_btn is not None
        layout = getattr(panel, "_layout", None)
        assert layout is not None
        stop_label = panel._primary_action_btn.GetLabel()
        if layout.primary_action_stop_uses_bitmap:
            assert stop_label == ""
            getter = getattr(panel._primary_action_btn, "GetBitmap", None)
            if callable(getter):
                bitmap = getter()
                assert bitmap is not None
                assert bitmap.IsOk()
        else:
            assert stop_label == layout.primary_action_stop_label
        tooltip = panel._primary_action_btn.GetToolTip()
        if tooltip is not None:
            assert tooltip.GetTip() == _("Stop")
    finally:
        panel._session.finalize_run()
        destroy_panel(frame, panel)


def test_agent_chat_panel_header_shows_conversation_tokens(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):
            return {"ok": True, "error": None, "result": {}}

    wx, frame, panel = create_panel(tmp_path, wx_app, agent=DummyAgent())

    try:
        breakdown = panel._compute_context_token_breakdown()
        label = panel._conversation_label.GetLabel()

        total_tokens = breakdown.total
        context_limit = panel._context_token_limit()
        tokens_text = panel._format_tokens_for_status(
            total_tokens, limit=context_limit
        )
        assert tokens_text in label

        system_tokens = format_token_quantity(breakdown.system)
        assert system_tokens in label
    finally:
        destroy_panel(frame, panel)


def test_bottom_controls_wrap_when_width_shrinks(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):
            return {"ok": True, "error": None, "result": {}}

    wx, frame, panel = create_panel(tmp_path, wx_app, agent=DummyAgent())

    try:
        flush_wx_events(wx)
        assert panel._bottom_controls_panel is not None
        target_width = panel.FromDIP(340)
        target_height = panel.FromDIP(520)
        frame.SetClientSize((target_width, target_height))
        frame.SendSizeEvent()
        flush_wx_events(wx, count=5)
        panel.activity.Show()
        panel._refresh_bottom_panel_layout()
        flush_wx_events(wx, count=5)
        bottom_panel = panel._bottom_controls_panel
        client_width = bottom_panel.GetClientSize().GetWidth()
        assert client_width <= target_width
        controls = [
            panel.activity,
            panel.status_label,
            panel._confirm_label,
            panel._confirm_choice,
            panel._run_batch_button,
            panel._stop_batch_button,
            panel._attachment_button,
            panel._attachment_summary,
            panel._clear_input_button,
            panel._project_settings_button,
            panel._primary_action_btn,
        ]
        y_positions: set[int] = set()
        for control in controls:
            assert control is not None
            assert control.IsShown()
            rect = control.GetRect()
            y_positions.add(rect.y)
            assert rect.GetRight() <= client_width
        # At least one control should wrap to a new row when the width is constrained.
        assert len(y_positions) > 1
    finally:
        destroy_panel(frame, panel)


def test_attachment_summary_visible_even_when_space_is_tight(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):
            return {"ok": True, "error": None, "result": {}}

    wx, frame, panel = create_panel(tmp_path, wx_app, agent=DummyAgent())

    try:
        flush_wx_events(wx)
        assert panel._attachment_summary is not None

        target_width = panel.FromDIP(420)
        target_height = panel.FromDIP(520)
        frame.SetClientSize((target_width, target_height))
        frame.SendSizeEvent()
        flush_wx_events(wx, count=8)

        summary_width = panel._attachment_summary.GetSize().GetWidth()
        assert summary_width >= panel.FromDIP(120)
        assert panel._attachment_summary.GetLabel()
    finally:
        destroy_panel(frame, panel)


def test_attachment_rejects_files_over_limit(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):
            return {"ok": True, "error": None, "result": {}}

    _wx, frame, panel = create_panel(tmp_path, wx_app, agent=DummyAgent())

    try:
        oversize = tmp_path / "oversize.txt"
        oversize.write_bytes(b"a" * (MAX_ATTACHMENT_BYTES + 1))

        with pytest.raises(AttachmentValidationError) as exc:
            panel._read_attachment_text(oversize)

        assert "1 MB" in str(exc.value)
    finally:
        destroy_panel(frame, panel)


def test_attachment_accepts_files_up_to_limit(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):
            return {"ok": True, "error": None, "result": {}}

    _wx, frame, panel = create_panel(tmp_path, wx_app, agent=DummyAgent())

    try:
        boundary = tmp_path / "boundary.txt"
        boundary.write_bytes(b"b" * MAX_ATTACHMENT_BYTES)

        text, size = panel._read_attachment_text(boundary)

        assert len(text) == MAX_ATTACHMENT_BYTES
        assert size == MAX_ATTACHMENT_BYTES
    finally:
        destroy_panel(frame, panel)


def test_input_enter_does_not_submit_without_modifier(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):
            return {"ok": True, "error": None, "result": {}}

    wx, frame, panel = create_panel(tmp_path, wx_app, agent=DummyAgent())

    try:
        sent_prompts: list[str] = []

        def fake_submit(prompt: str, *, prompt_at: str | None = None) -> None:
            sent_prompts.append(prompt)

        panel._submit_prompt = fake_submit  # type: ignore[assignment]
        panel.input.SetValue("hello agent")

        event = FakeKeyEvent(wx.WXK_RETURN)
        panel._on_input_key_down(event)

        assert event.skipped is True
        assert sent_prompts == []
        assert panel.input.GetValue() == "hello agent"
    finally:
        destroy_panel(frame, panel)


@pytest.mark.parametrize("modifier", ["control", "command"])
def test_input_modifier_enter_submits_prompt(tmp_path, wx_app, modifier):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):
            return {"ok": True, "error": None, "result": {}}

    wx, frame, panel = create_panel(tmp_path, wx_app, agent=DummyAgent())

    try:
        sent_prompts: list[str] = []

        def fake_submit(prompt: str, *, prompt_at: str | None = None) -> None:
            sent_prompts.append(prompt)

        panel._submit_prompt = fake_submit  # type: ignore[assignment]
        panel.input.SetValue("send me")

        kwargs = {"control": False, "command": False}
        kwargs[modifier] = True
        event = FakeKeyEvent(wx.WXK_RETURN, **kwargs)
        panel._on_input_key_down(event)

        assert event.skipped is False
        assert sent_prompts == ["send me"]
        assert panel.input.GetValue() == ""
    finally:
        destroy_panel(frame, panel)


def test_send_during_active_run_queues_prompt(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):
            return {"ok": True, "error": None, "result": {}}

    wx, frame, panel = create_panel(tmp_path, wx_app, agent=DummyAgent())

    try:
        flush_wx_events(wx)
        panel._ensure_active_conversation()
        panel._session.begin_run(tokens=TokenCountResult.exact(0))

        sent_prompts: list[str] = []

        def fake_submit(prompt: str, *, prompt_at: str | None = None) -> None:
            sent_prompts.append(prompt)

        panel._submit_prompt = fake_submit  # type: ignore[assignment]
        panel.input.SetValue("queued follow-up")
        panel._on_send(None)
        flush_wx_events(wx)

        assert sent_prompts == []
        assert len(panel._prompt_queue) == 1
        banner = panel._queued_prompt_panel
        assert banner is not None and banner.IsShown()
        summary = panel._queued_prompt_label
        assert summary is not None
        tooltip = summary.GetToolTip()
        assert tooltip is not None
        assert "queued follow-up" in tooltip.GetTip()
    finally:
        if panel._session.is_running:
            panel._session.finalize_run()
        destroy_panel(frame, panel)


def test_cancel_queued_prompt_hides_banner(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):
            return {"ok": True, "error": None, "result": {}}

    wx, frame, panel = create_panel(tmp_path, wx_app, agent=DummyAgent())

    try:
        flush_wx_events(wx)
        panel._ensure_active_conversation()
        panel._session.begin_run(tokens=TokenCountResult.exact(0))
        panel.input.SetValue("queued follow-up")
        panel._on_send(None)
        flush_wx_events(wx)

        panel._on_cancel_queued_prompt(None)
        flush_wx_events(wx)

        assert len(panel._prompt_queue) == 0
        banner = panel._queued_prompt_panel
        assert banner is not None and not banner.IsShown()
        summary = panel._queued_prompt_label
        assert summary is not None and summary.GetLabel() == ""
    finally:
        if panel._session.is_running:
            panel._session.finalize_run()
        destroy_panel(frame, panel)


def test_queued_prompt_submits_after_completion(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):
            return {"ok": True, "error": None, "result": {}}

    class StubCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def submit_prompt(self, prompt: str, *, prompt_at: str | None = None) -> None:
            self.calls.append((prompt, prompt_at))

    wx, frame, panel = create_panel(tmp_path, wx_app, agent=DummyAgent())

    try:
        flush_wx_events(wx)
        panel._ensure_active_conversation()
        panel._session.begin_run(tokens=TokenCountResult.exact(0))
        coordinator = StubCoordinator()
        panel._coordinator = coordinator  # type: ignore[assignment]

        panel.input.SetValue("follow-up")
        panel._on_send(None)
        flush_wx_events(wx)

        panel._session.finalize_run()
        panel._process_next_queued_prompt()

        assert coordinator.calls and coordinator.calls[0][0] == "follow-up"
        assert len(panel._prompt_queue) == 0
        banner = panel._queued_prompt_panel
        assert banner is not None and not banner.IsShown()
    finally:
        destroy_panel(frame, panel)


def test_attachment_summary_compact_format(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):
            return {"ok": True, "error": None, "result": {}}

    wx, frame, panel = create_panel(tmp_path, wx_app, agent=DummyAgent())

    try:
        sample = tmp_path / (
            "sample_attachment_with_a_pretty_long_name_to_trigger_ellipsis.txt"
        )
        sample.write_text("hello world\n")

        attachment = panel._load_attachment(sample)
        panel._pending_attachment = attachment
        panel._update_attachment_summary()
        flush_wx_events(wx)

        label = panel._attachment_summary
        assert label is not None
        text = label.GetLabel()
        # Compact stats should show file name and three segments joined with slashes.
        assert "•" in text
        assert text.count("/") == 2
        assert text.endswith(("%", i18n._("n/a")))

        tooltip_obj = label.GetToolTip()
        assert tooltip_obj is not None
        tooltip = tooltip_obj.GetTip()
        assert "Attachment:" in tooltip
        assert sample.name in tooltip
        assert "Tokens:" in tooltip

        panel._clear_pending_attachment()
        flush_wx_events(wx)
        assert label.GetToolTip() is None
    finally:
        destroy_panel(frame, panel)


def test_switching_to_previous_chat_after_starting_new_one(tmp_path, wx_app):
    class DummyAgent:
        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
            on_llm_step=None,
        ):
            return {"ok": True, "error": None, "result": {"echo": text}}

    wx, frame, panel = create_panel(tmp_path, wx_app, DummyAgent())

    try:
        panel.input.SetValue("first message")
        panel._on_send(None)
        flush_wx_events(wx)

        assert panel.history_list.GetItemCount() == 1
        assert "first message" in panel.get_transcript_text()

        panel._on_new_chat(None)
        flush_wx_events(wx)

        assert panel.history_list.GetItemCount() == 2
        assert panel._active_index() == 1

        panel._on_history_row_activated(0)
        flush_wx_events(wx)

        assert panel._active_index() == 0
        transcript = panel.get_transcript_text()
        assert "first message" in transcript
    finally:
        destroy_panel(frame, panel)


def test_streaming_steps_persist_across_history_switch(tmp_path, wx_app):
    class StreamingAgent:
        def __init__(self) -> None:
            self.first_chunk = threading.Event()
            self.allow_finish = threading.Event()

        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
            on_llm_step=None,
        ):
            if on_llm_step is not None:
                on_llm_step(
                    {
                        "step": 1,
                        "response": {"content": "first stream chunk"},
                    }
                )
            self.first_chunk.set()
            self.allow_finish.wait(timeout=5)
            if on_llm_step is not None:
                on_llm_step(
                    {
                        "step": 2,
                        "response": {"content": "second stream chunk"},
                    }
                )
            return {"ok": True, "result": {"echo": text}}

    agent = StreamingAgent()
    wx, frame, panel = create_panel(
        tmp_path, wx_app, agent, use_default_executor=True
    )

    try:
        panel.input.SetValue("stream this")
        panel._on_send(None)

        assert agent.first_chunk.wait(timeout=5), "streaming did not start"
        flush_wx_events(wx, count=4)
        transcript = panel.get_transcript_text()
        assert "first stream chunk" in transcript

        panel._on_new_chat(None)
        flush_wx_events(wx, count=2)
        assert panel._active_index() == 1

        panel._on_history_row_activated(0)
        flush_wx_events(wx, count=2)
        assert panel._active_index() == 0
        transcript_after_switch = panel.get_transcript_text()
        assert "first stream chunk" in transcript_after_switch

        agent.allow_finish.set()
        start = time.time()
        while panel._session.is_running and time.time() - start < 6:
            flush_wx_events(wx)
            time.sleep(0.05)
        flush_wx_events(wx, count=3)

        conversation = panel._get_active_conversation()
        assert conversation is not None
        assert conversation.entries
        entry = conversation.entries[0]
        diagnostic = entry.diagnostic
        assert isinstance(diagnostic, dict)
        steps = diagnostic.get("llm_steps")
        assert isinstance(steps, list)
        assert len(steps) == 2

        timeline = panel._latest_timeline
        if timeline is None or timeline.conversation_id != conversation.conversation_id:
            timeline = build_conversation_timeline(conversation)
        assert timeline.entries
        agent_turn = timeline.entries[0].agent_turn
        assert agent_turn is not None
        assert len(agent_turn.streamed_responses) == 2

        final_transcript = panel.get_transcript_text()
        assert "first stream chunk" in final_transcript
        assert "second stream chunk" in final_transcript

        cache = panel._transcript_view._conversation_cache[conversation.conversation_id]
        entry_key = f"{conversation.conversation_id}:0"
        assert entry_key in cache.cards_by_entry
    finally:
        agent.allow_finish.set()
        destroy_panel(frame, panel)
def test_agent_custom_system_prompt_appended(tmp_path, wx_app):
    class CaptureAgent:
        def __init__(self) -> None:
            self.last_history: list[dict[str, str]] | None = None

        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
            on_llm_step=None,
        ):
            self.last_history = list(history or [])
            return {"ok": True, "result": {"echo": text}}

    agent = CaptureAgent()
    wx, frame, panel = create_panel(tmp_path, wx_app, agent)

    try:
        custom_prompt = "Follow project conventions"
        panel._apply_project_settings(
            AgentProjectSettings(custom_system_prompt=custom_prompt)
        )
        panel.input.SetValue("Plan release")
        panel._on_send(None)
        flush_wx_events(wx)

        history = agent.last_history
        assert history is not None
        assert history[0]["role"] == "system"
        assert history[0]["content"] == custom_prompt

        assert panel.history
        entry = panel.history[0]
        assert entry.diagnostic
        assert entry.diagnostic.get("custom_system_prompt") == custom_prompt
        assert entry.diagnostic["history_messages"][0]["role"] == "system"
        assert entry.diagnostic["history_messages"][0]["content"] == custom_prompt
    finally:
        destroy_panel(frame, panel)


def test_agent_project_settings_dialog_handles_custom_prompt(wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.agent_chat_panel.settings_dialog import AgentProjectSettingsDialog

    frame = wx.Frame(None)
    settings = AgentProjectSettings(
        custom_system_prompt="Existing",
        documents_path="docs",
    )

    try:
        dialog = AgentProjectSettingsDialog(frame, settings=settings)
        try:
            assert dialog.get_custom_system_prompt() == "Existing"
            assert dialog.get_documents_path() == "docs"
            dialog._prompt.SetValue("   updated instructions   ")
            assert dialog.get_custom_system_prompt() == "updated instructions"
            dialog._documents_path.SetValue("  материалы ")
            assert dialog.get_documents_path() == "материалы"
        finally:
            dialog.Destroy()
    finally:
        frame.Destroy()


def test_project_settings_override_documents_path(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):
            return {"ok": True, "result": {}}

    wx, frame, panel = create_panel(tmp_path, wx_app, DummyAgent())

    try:
        base_dir = tmp_path / "repo"
        base_dir.mkdir()
        (base_dir / "share").mkdir()
        override = base_dir / "Документы" / "рабочие материалы"
        override.mkdir(parents=True)

        panel.set_history_directory(base_dir)
        panel._apply_project_settings(
            AgentProjectSettings(documents_path="Документы/рабочие материалы")
        )

        assert panel.documents_subdirectory == "Документы/рабочие материалы"
        assert panel.project_settings.documents_path == "Документы/рабочие материалы"
        resolved = panel.documents_root
        assert resolved is not None
        assert resolved == override.resolve()

        panel.set_documents_subdirectory("другое")
        assert panel.documents_subdirectory == "Документы/рабочие материалы"
        assert panel.documents_root == resolved
    finally:
        destroy_panel(frame, panel)


@pytest.mark.gui_smoke
def test_agent_chat_panel_sends_and_saves_history(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {"ok": True, "error": None, "result": {"echo": text}}

    wx, frame, panel = create_panel(tmp_path, wx_app, DummyAgent())

    baseline_breakdown = panel._compute_context_token_breakdown()
    baseline_conversation = baseline_breakdown.total
    baseline_label = panel._conversation_label.GetLabel()

    panel.input.SetValue("run")
    panel._on_send(None)
    flush_wx_events(wx)

    updated_breakdown = panel._compute_context_token_breakdown()
    updated_conversation = updated_breakdown.total
    updated_label = panel._conversation_label.GetLabel()
    assert (
        updated_label != baseline_label
        or (updated_conversation.tokens or 0)
        != (baseline_conversation.tokens or 0)
    ), "conversation header should reflect updated token usage"
    assert (updated_conversation.tokens or 0) >= (
        baseline_conversation.tokens or 0
    )
    context_limit = panel._context_token_limit()
    expected_tokens = panel._format_tokens_for_status(
        updated_conversation,
        limit=context_limit,
    )
    assert expected_tokens in updated_label
    expected_percent = panel._format_context_percentage(
        updated_conversation,
        context_limit,
    )
    assert expected_percent in updated_label

    transcript = panel.get_transcript_text()
    assert "run" in transcript
    assert "\"echo\": \"run\"" in transcript
    assert panel.history_list.GetItemCount() == 1
    assert panel.input.GetValue() == ""
    assert len(panel.history) == 1

    metadata, conversations = read_history_database(history_db_path(tmp_path))
    assert metadata.get("schema_version") == "1"
    assert isinstance(metadata.get("active_id"), str)
    assert len(conversations) == 1
    entry_payload = conversations[0]["entries"][0]
    assert entry_payload["prompt"] == "run"
    assert entry_payload["response"].strip().startswith("{")
    assert entry_payload.get("token_info") is not None
    assert entry_payload["token_info"]["tokens"] == entry_payload["tokens"]
    assert "context_messages" in entry_payload
    assert entry_payload["context_messages"] is None
    assert entry_payload.get("regenerated") is False

    history_entry = panel.history[0]
    assert history_entry.context_messages is None

    panel._on_clear_input(None)
    assert panel.input.GetValue() == ""

    panel.input.SetValue("draft")

    panel._activate_conversation_by_index(0)
    assert panel.input.GetValue() == "draft"

    destroy_panel(frame, panel)


def test_agent_chat_panel_regenerates_last_response(tmp_path, wx_app):
    class CountingAgent:
        def __init__(self) -> None:
            self.calls: int = 0
            self.history_snapshots: list[Sequence[Mapping[str, Any]] | None] = []

        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            self.calls += 1
            if history is None:
                self.history_snapshots.append(None)
            else:
                try:
                    cloned = [dict(message) for message in history]
                except Exception:
                    cloned = list(history)
                self.history_snapshots.append(cloned)
            return f"answer {self.calls}"

    agent = CountingAgent()
    wx, frame, panel = create_panel(tmp_path, wx_app, agent)

    try:
        panel.input.SetValue("regen")
        panel._on_send(None)
        flush_wx_events(wx, count=5)

        assert panel.history
        assert len(panel.history) == 1
        first_entry = panel.history[0]
        assert first_entry.response.endswith("1")
        assert not getattr(first_entry, "regenerated", False)

        target_labels = {"Regenerate", i18n.gettext("Regenerate")}

        def find_regenerate_button(window):
            for child in window.GetChildren():
                if isinstance(child, wx.Button) and child.GetLabel() in target_labels:
                    return child
                found = find_regenerate_button(child)
                if found is not None:
                    return found
            return None

        transcript_children = panel.transcript_panel.GetChildren()
        assert transcript_children
        regen_button = None
        for candidate in reversed(transcript_children):
            regen_button = find_regenerate_button(candidate)
            if regen_button is not None:
                break
        assert regen_button is not None
        assert regen_button.IsEnabled()

        evt = wx.CommandEvent(wx.EVT_BUTTON.typeId, regen_button.GetId())
        evt.SetEventObject(regen_button)
        regen_button.GetEventHandler().ProcessEvent(evt)
        flush_wx_events(wx, count=6)

        assert panel.history
        assert len(panel.history) == 1
        regenerated_entry = panel.history[0]
        assert regenerated_entry.response.endswith("2")
        assert not getattr(regenerated_entry, "regenerated", False)
        transcript = panel.get_transcript_text()
        assert "answer 1" not in transcript
        assert "answer 2" in transcript
        assert agent.history_snapshots[1] in (None, [])
    finally:
        destroy_panel(frame, panel)


def test_agent_response_normalizes_dash_characters(tmp_path, wx_app):
    class HyphenAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return "single\u2010folder"

    wx, frame, panel = create_panel(tmp_path, wx_app, HyphenAgent())

    panel.input.SetValue("dash")
    panel._on_send(None)
    flush_wx_events(wx)

    transcript = panel.get_transcript_text()
    assert "single-folder" in transcript

    assert panel.history
    entry = panel.history[0]
    assert entry.response == "single-folder"
    assert entry.display_response == "single-folder"

    destroy_panel(frame, panel)


@pytest.mark.gui_smoke
def test_agent_chat_panel_handles_error(tmp_path, wx_app):
    class FailingAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {"ok": False, "error": {"code": "FAIL", "message": "bad"}}

    wx, frame, panel = create_panel(tmp_path, wx_app, FailingAgent())

    panel.input.SetValue("go")
    panel._on_send(None)
    flush_wx_events(wx)

    transcript = panel.get_transcript_text()
    assert "FAIL" in transcript
    entry = panel.history[0]
    assert entry.token_info is not None
    assert entry.token_info.tokens is not None
    assert entry.token_info.tokens >= 1

    destroy_panel(frame, panel)


def test_confirmation_preference_resets_on_chat_switch(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {"ok": True, "result": text, "error": None}

    persisted: list[str] = []

    wx, frame, panel = create_panel(
        tmp_path,
        wx_app,
        DummyAgent(),
        confirm_preference="prompt",
        persist_confirm_preference=persisted.append,
    )

    try:
        panel._ensure_active_conversation()
        choice = panel._confirm_choice
        assert choice is not None
        index_map = panel._confirm_choice_index
        chat_only_index = index_map[RequirementConfirmPreference.CHAT_ONLY]
        never_index = index_map[RequirementConfirmPreference.NEVER]

        def select_preference(index: int) -> None:
            choice.SetSelection(index)
            evt = wx.CommandEvent(wx.EVT_CHOICE.typeId, choice.GetId())
            evt.SetEventObject(choice)
            evt.SetInt(index)
            choice.GetEventHandler().ProcessEvent(evt)
            flush_wx_events(wx)

        select_preference(chat_only_index)

        assert (
            panel.confirmation_preference
            == RequirementConfirmPreference.CHAT_ONLY.value
        )
        assert persisted == []

        panel._create_conversation(persist=False)
        flush_wx_events(wx)
        assert (
            panel.confirmation_preference
            == RequirementConfirmPreference.PROMPT.value
        )

        select_preference(chat_only_index)

        assert (
            panel.confirmation_preference
            == RequirementConfirmPreference.CHAT_ONLY.value
        )

        panel._activate_conversation_by_index(0)
        flush_wx_events(wx)
        assert (
            panel.confirmation_preference
            == RequirementConfirmPreference.PROMPT.value
        )

        select_preference(never_index)

        assert (
            panel.confirmation_preference
            == RequirementConfirmPreference.NEVER.value
        )
        assert persisted and persisted[-1] == RequirementConfirmPreference.NEVER.value
    finally:
        destroy_panel(frame, panel)


def test_agent_chat_panel_applies_vertical_sash(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {"ok": True, "result": text, "error": None}

    wx, frame, panel = create_panel(tmp_path, wx_app, DummyAgent())

    try:
        frame.SetSize((900, 700))
        frame.Show()
        frame.SendSizeEvent()
        flush_wx_events(wx, count=5)

        splitter = panel._vertical_splitter
        minimum = splitter.GetMinimumPaneSize()
        total = splitter.GetClientSize().GetHeight()
        if total <= 0:
            frame.SendSizeEvent()
            flush_wx_events(wx, count=5)
            total = splitter.GetClientSize().GetHeight()
        assert total > 0

        max_top = max(minimum, total - minimum)
        target = max(minimum, min(max_top, minimum + 120))

        panel.apply_vertical_sash(target)
        flush_wx_events(wx, count=5)
        assert abs(panel.vertical_sash - target) <= 2

        panel._adjust_vertical_splitter()
        assert abs(panel.vertical_sash - target) <= 2
    finally:
        destroy_panel(frame, panel)


def test_agent_chat_panel_passes_context(tmp_path, wx_app):
    captured: list[dict[str, Any]] = []

    class RecordingAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            captured.append({"text": text, "context": context})
            return {"ok": True, "error": None, "result": "ok"}

    context_payload = {"role": "system", "content": "Active requirements document: SYS"}

    wx, frame, panel = create_panel(
        tmp_path,
        wx_app,
        RecordingAgent(),
        context_provider=lambda: context_payload,
    )

    panel.input.SetValue("context run")
    panel._on_send(None)
    flush_wx_events(wx)

    try:
        assert captured
        first_call = captured[0]
        assert first_call["text"] == "context run"
        assert first_call["context"] == (
            {"role": "system", "content": "Active requirements document: SYS"},
        )
        assert panel.history
        stored_entry = panel.history[0]
        assert stored_entry.context_messages == (
            {"role": "system", "content": "Active requirements document: SYS"},
        )
    finally:
        destroy_panel(frame, panel)


def test_agent_response_allows_text_selection(tmp_path, wx_app):
    class EchoAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return f"agent: {text}"

    wx, frame, panel = create_panel(tmp_path, wx_app, EchoAgent())

    panel.input.SetValue("hello world")
    panel._on_send(None)
    flush_wx_events(wx)

    transcript_children = panel.transcript_panel.GetChildren()
    assert transcript_children
    entry_panel = transcript_children[0]

    from app.ui.widgets.markdown_view import MarkdownContent

    text_controls: list[wx.TextCtrl] = []
    markdown_controls: list[MarkdownContent] = []

    def collect_text_controls(window) -> None:
        for child in window.GetChildren():
            if isinstance(child, wx.TextCtrl):
                text_controls.append(child)
            if isinstance(child, MarkdownContent):
                markdown_controls.append(child)
            collect_text_controls(child)

    collect_text_controls(entry_panel)
    if markdown_controls:
        agent_markdown = markdown_controls[0]
        assert agent_markdown.GetPlainText().strip() == "agent: hello world"
        agent_markdown.SelectAll()
        assert agent_markdown.HasSelection()
        assert agent_markdown.GetSelectionText().strip().startswith("agent: hello world")
    else:
        assert text_controls, "Expected agent message to expose a selectable control"
        agent_text = text_controls[0]
        assert agent_text.GetValue() == "agent: hello world"
        assert not agent_text.IsEditable()

    destroy_panel(frame, panel)


def test_transcript_scrolls_to_bottom_on_new_messages(tmp_path, wx_app):
    class EchoAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return text

    wx, frame, panel = create_panel(tmp_path, wx_app, EchoAgent())

    try:
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(panel, 1, wx.EXPAND)
        frame.SetSizer(sizer)
        frame.SetClientSize((panel.FromDIP(320), panel.FromDIP(220)))
        frame.Layout()
        frame.SendSizeEvent()
        flush_wx_events(wx, count=3)

        base_response = "\n".join(f"entry line {line}" for line in range(30))
        for idx in range(4):
            prompt = f"prompt {idx}"
            panel._append_history(
                prompt,
                base_response,
                base_response,
                raw_result=None,
                token_info=None,
            )
            panel._render_transcript()
        flush_wx_events(wx, count=5)

        transcript_panel = panel.transcript_panel
        assert transcript_panel.GetVirtualSize().GetHeight() > transcript_panel.GetClientSize().GetHeight()

        transcript_panel.Scroll(0, 0)
        flush_wx_events(wx, count=2)
        view_x, view_y = transcript_panel.GetViewStart()
        assert view_y == 0

        long_response = "\n".join(f"final line {line}" for line in range(40))
        panel._append_history(
            "final prompt",
            long_response,
            long_response,
            raw_result=None,
            token_info=None,
        )
        panel._render_transcript()
        flush_wx_events(wx, count=6)

        view_x, view_y = transcript_panel.GetViewStart()
        assert view_y > 0

        children = transcript_panel.GetChildren()
        assert children, "expected transcript to contain message panels"
        last_panel = children[-1]
        last_top = last_panel.GetPosition().y
        last_bottom = last_top + last_panel.GetSize().GetHeight()
        client_height = transcript_panel.GetClientSize().GetHeight()
        assert last_bottom <= client_height
        tolerance = max(panel.FromDIP(64), last_panel.GetSize().GetHeight() // 4)
        assert client_height - last_bottom <= tolerance
    finally:
        destroy_panel(frame, panel)


def test_copy_conversation_button_copies_transcript(monkeypatch, tmp_path, wx_app):
    clipboard: dict[str, str] = {}

    class DummyClipboard:
        def __init__(self) -> None:
            self.opened = False

        def Open(self) -> bool:  # noqa: N802 - wx naming convention
            self.opened = True
            return True

        def Close(self) -> None:  # noqa: N802 - wx naming convention
            self.opened = False

        def SetData(self, data) -> None:  # noqa: N802 - wx naming convention
            clipboard["text"] = data.GetText()

    class SimpleAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return f"response to {text}"

    wx, frame, panel = create_panel(tmp_path, wx_app, SimpleAgent())
    monkeypatch.setattr(wx, "TheClipboard", DummyClipboard())

    assert panel._copy_conversation_btn is not None
    assert not panel._copy_conversation_btn.IsEnabled()

    panel.input.SetValue("copy me")
    panel._on_send(None)
    flush_wx_events(wx)

    assert panel._copy_conversation_btn.IsEnabled()

    panel._on_copy_conversation(None)

    assert "response to copy me" in clipboard["text"]

    destroy_panel(frame, panel)


def test_agent_chat_panel_hides_tool_results_and_exposes_log(tmp_path, wx_app):
    class ToolAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {
                "ok": True,
                "error": None,
                "result": "done",
                "tool_results": [
                    {
                        "tool_name": "demo_tool",
                        "ok": True,
                        "tool_arguments": {"query": text},
                        "result": {"status": "ok"},
                    }
                ],
            }

    wx, frame, panel = create_panel(tmp_path, wx_app, ToolAgent())

    panel.input.SetValue("inspect")
    panel._on_send(None)
    flush_wx_events(wx)

    try:
        panes = collect_collapsible_panes(panel.transcript_panel)
        assert panes, "expected collapsible transcript panes"

        raw_panes = [
            pane
            for pane in panes
            if pane.GetName().startswith(("raw:", "tool:raw:"))
        ]
        assert len(raw_panes) >= 2, "expected raw data panes for agent and tool"

        for pane in raw_panes:
            if pane.IsCollapsed():
                pane.Collapse(False)
        flush_wx_events(wx)

        def collect_text_controls(window):
            controls: list[wx.TextCtrl] = []
            for child in window.GetChildren():
                if isinstance(child, wx.TextCtrl):
                    controls.append(child)
                controls.extend(collect_text_controls(child))
            return controls

        raw_texts = []
        for pane in raw_panes:
            raw_controls = collect_text_controls(pane.GetPane())
            assert raw_controls, "expected raw data text control"
            raw_texts.append("\n".join(ctrl.GetValue() for ctrl in raw_controls))

        assert any("tool_results" in text for text in raw_texts)
        assert any("tool_arguments" in text for text in raw_texts)

        assert any(name == "raw:agent" for name in (pane.GetName() for pane in raw_panes)), "expected agent raw pane"
        assert any(
            name.startswith("tool:raw:") for name in (pane.GetName() for pane in raw_panes)
        ), "expected tool raw pane"

        transcript_text = panel.get_transcript_text()
        assert "demo_tool" in transcript_text
        assert "Agent: tool call" in transcript_text
        assert "tool_results" not in transcript_text
        assert "Query: `inspect`" in transcript_text

        log_text = panel.get_transcript_log_text()
        assert "demo_tool" in log_text
        assert "Tool call 1: demo_tool" in log_text
        assert "\"tool_arguments\"" in log_text
        assert "query" in log_text
        assert "LLM request:" in log_text
        assert "Raw LLM payload:" in log_text
    finally:
        destroy_panel(frame, panel)


def test_copy_buttons_emit_inspection_artifacts(tmp_path, wx_app, request):
    class ArtifactAgent:
        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
            on_llm_step=None,
        ):
            diagnostic = {
                "llm_steps": [
                    {
                        "response": {
                            "content": "Reasoning chunk",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "demo_tool",
                                        "arguments": json.dumps({"query": text}),
                                    },
                                }
                            ],
                        },
                    }
                ],
                "system_prompt": SYSTEM_PROMPT,
            }

            if on_tool_result is not None:
                on_tool_result(
                    {
                        "tool_name": "demo_tool",
                        "tool_arguments": {"query": text},
                        "result": {"status": "ok"},
                        "tool_call_id": "call-1",
                        "started_at": "2025-01-01T10:00:00+00:00",
                        "completed_at": "2025-01-01T10:00:05+00:00",
                        "ok": True,
                    }
                )

            if on_llm_step is not None:
                on_llm_step(
                    {
                        "step": 2,
                        "response": {
                            "content": "Final reasoning",
                        },
                    }
                )

            return {
                "ok": True,
                "error": None,
                "result": "Agent reply",
                "diagnostic": diagnostic,
                "tool_results": [
                    {
                        "tool_name": "demo_tool",
                        "tool_call_id": "call-1",
                        "tool_arguments": {"query": text},
                        "result": {"status": "ok"},
                        "started_at": "2025-01-01T10:00:00+00:00",
                        "completed_at": "2025-01-01T10:00:05+00:00",
                        "ok": True,
                    }
                ],
            }

    wx, frame, panel = create_panel(tmp_path, wx_app, agent=ArtifactAgent())

    try:
        panel.input.SetValue("collect artifacts")
        panel._on_send(None)
        flush_wx_events(wx, count=6)

        assert panel.history
        panel._render_transcript()
        flush_wx_events(wx, count=3)

        conversation_path, log_path = write_transcript_artifacts(
            panel, tmp_path, request
        )

        assert conversation_path.read_text(encoding="utf-8").strip()
        assert log_path.read_text(encoding="utf-8").strip()
    finally:
        destroy_panel(frame, panel)


def test_agent_chat_panel_preserves_tool_messages_in_history(tmp_path, wx_app):
    class ToolRecordingAgent:
        def __init__(self) -> None:
            self.history_snapshots: list[tuple[dict[str, Any], ...] | None] = []
            self.calls = 0

        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
            on_llm_step=None,
        ):
            self.calls += 1
            if history is None:
                self.history_snapshots.append(None)
            else:
                try:
                    snapshot = tuple(dict(message) for message in history)
                except Exception:
                    snapshot = tuple(history)
                self.history_snapshots.append(snapshot)

            tool_payload = {
                "tool_call_id": "call-1",
                "call_id": "call-1",
                "tool_name": "demo_tool",
                "tool_arguments": {"query": text},
                "result": {"ok": True},
            }

            if self.calls == 1:
                if on_llm_step is not None:
                    on_llm_step(
                        {
                            "step": 1,
                            "response": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {
                                            "name": "demo_tool",
                                            "arguments": json.dumps({"query": text}),
                                        },
                                    }
                                ],
                            },
                        }
                    )
                if on_tool_result is not None:
                    on_tool_result(dict(tool_payload))
                if on_llm_step is not None:
                    on_llm_step(
                        {
                            "step": 2,
                            "response": {"content": "Final answer"},
                        }
                    )
                return {
                    "ok": True,
                    "result": "Final answer",
                    "tool_results": [dict(tool_payload)],
                }

            return "Second response"

    agent = ToolRecordingAgent()
    wx, frame, panel = create_panel(tmp_path, wx_app, agent)

    try:
        panel.input.SetValue("first")
        panel._on_send(None)
        flush_wx_events(wx, count=6)

        assert panel.history
        entry = panel.history[0]
        assert entry.tool_messages
        first_tool_message = entry.tool_messages[0]
        assert first_tool_message["tool_call_id"] == "call-1"
        payload = json.loads(first_tool_message["content"])
        assert payload["tool_call_id"] == "call-1"
        assert payload["tool_name"] == "demo_tool"

        panel.input.SetValue("second")
        panel._on_send(None)
        flush_wx_events(wx, count=4)

        assert len(agent.history_snapshots) >= 2
        second_history = agent.history_snapshots[1]
        assert second_history is not None
        history_messages = list(second_history)
        assert history_messages[0]["role"] == "user"
        assert history_messages[1]["role"] == "assistant"
        tool_message = history_messages[2]
        assert tool_message["role"] == "tool"
        assert tool_message["tool_call_id"] == "call-1"
        history_payload = json.loads(tool_message["content"])
        assert history_payload["tool_call_id"] == "call-1"
        assert history_payload["tool_name"] == "demo_tool"
    finally:
        destroy_panel(frame, panel)


def test_agent_chat_panel_renders_context_collapsible(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {"ok": True, "result": text, "error": None}

    context_payload = [
        {
            "role": "system",
            "content": (
                "[Workspace context]\n"
                "Active requirements document: sys: System req.\n"
                "Selected requirement RIDs: sys48, sys49, sys50"
            ),
        }
    ]

    wx, frame, panel = create_panel(
        tmp_path,
        wx_app,
        DummyAgent(),
        context_provider=lambda: context_payload,
    )

    panel.input.SetValue("inspect")
    panel._on_send(None)
    flush_wx_events(wx)

    try:
        def collect_collapsible(window):
            panes: list[wx.CollapsiblePane] = []
            for child in window.GetChildren():
                if isinstance(child, wx.CollapsiblePane):
                    panes.append(child)
                panes.extend(collect_collapsible(child))
            return panes

        panes = collect_collapsible(panel.transcript_panel)
        assert panes, "expected collapsible context pane"

        context_panes = [
            pane
            for pane in panes
            if pane.GetName() == "context" or collapsible_label(pane) == i18n.gettext("Context")
        ]
        assert context_panes, "context pane should be present"
        context_pane = context_panes[0]
        assert context_pane.IsCollapsed()

        context_pane.Collapse(False)
        flush_wx_events(wx)

        def collect_text_controls(window):
            controls: list[wx.TextCtrl] = []
            for child in window.GetChildren():
                if isinstance(child, wx.TextCtrl):
                    controls.append(child)
                controls.extend(collect_text_controls(child))
            return controls

        text_controls = collect_text_controls(context_pane.GetPane())
        assert text_controls, "expected context text control"

        value = text_controls[0].GetValue()
        assert "[Workspace context]" in value
        assert "Active requirements document: sys: System req." in value
        assert "Selected requirement RIDs: sys48, sys49, sys50" in value
    finally:
        destroy_panel(frame, panel)


def test_agent_chat_panel_sorts_tool_results_chronologically(tmp_path, wx_app):
    class ChronoAgent:
        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
            on_llm_step=None,
        ):
            return {
                "ok": True,
                "result": text,
                "tool_results": [
                    {
                        "tool_name": "later_tool",
                        "ok": True,
                        "tool_arguments": {"query": "later"},
                        "result": {"status": "ok"},
                        "started_at": "2025-09-30T10:00:00+00:00",
                        "completed_at": "2025-09-30T10:00:30+00:00",
                    },
                    {
                        "tool_name": "earlier_tool",
                        "ok": True,
                        "tool_arguments": {"query": "earlier"},
                        "result": {"status": "ok"},
                        "started_at": "2025-09-30T09:00:00+00:00",
                        "completed_at": "2025-09-30T09:00:20+00:00",
                    },
                ],
            }

    wx, frame, panel = create_panel(tmp_path, wx_app, ChronoAgent())

    panel.input.SetValue("inspect")
    panel._on_send(None)
    flush_wx_events(wx)

    try:
        transcript_text = panel.get_transcript_text()
        earlier_index = transcript_text.index("earlier_tool")
        later_index = transcript_text.index("later_tool")
        assert earlier_index < later_index, transcript_text

        log_text = panel.get_transcript_log_text()
        first_timestamp = log_text.index("2025-09-30T09:00:00+00:00")
        second_timestamp = log_text.index("2025-09-30T10:00:00+00:00")
        assert first_timestamp < second_timestamp, log_text
    finally:
        destroy_panel(frame, panel)


def test_agent_events_should_follow_timestamp_order():
    conversation, _ = build_entry_timeline(
        prompt="Inspect request",
        response="Final agent message",
        prompt_at="2025-09-30T09:00:00+00:00",
        response_at="2025-09-30T10:00:30+00:00",
        tool_results=[
            {
                "tool_name": "later_tool",
                "ok": True,
                "tool_arguments": {"query": "later"},
                "result": {"status": "ok"},
                "started_at": "2025-09-30T10:00:00+00:00",
                "completed_at": "2025-09-30T10:00:30+00:00",
            },
            {
                "tool_name": "earlier_tool",
                "ok": True,
                "tool_arguments": {"query": "earlier"},
                "result": {"status": "ok"},
                "started_at": "2025-09-30T09:00:10+00:00",
                "completed_at": "2025-09-30T09:00:20+00:00",
            },
        ],
    )

    transcript_text = compose_transcript_text(conversation)

    tool_index = transcript_text.index("earlier_tool")
    agent_index = transcript_text.index("Final agent message")

    assert tool_index < agent_index, transcript_text


def test_agent_turn_timestamp_tracks_latest_event(tmp_path, wx_app):
    wx = pytest.importorskip("wx")

    latest_ts = "2025-09-30T10:00:30+00:00"
    conversation, entry_timeline = build_entry_timeline(
        prompt_at="2025-09-30T09:59:00+00:00",
        response="Final content",
        response_at="2025-09-30T09:59:30+00:00",
        tool_results=[
            {
                "tool_name": "demo_tool",
                "ok": True,
                "tool_arguments": {"query": "late"},
                "result": {"status": "ok"},
                "started_at": "2025-09-30T10:00:00+00:00",
                "completed_at": latest_ts,
            }
        ],
    )

    frame = wx.Frame(None)
    panel = None
    try:
        panel = render_turn_card(
            frame,
            conversation=conversation,
            entry=entry_timeline,
            layout_hints=entry_timeline.layout_hints,
        )
        wx.GetApp().Yield()

        agent_bubble = next(
            bubble
            for bubble in collect_message_bubbles(panel)
            if "Agent" in bubble_header_text(bubble)
        )
        header = bubble_header_text(agent_bubble)
        assert format_entry_timestamp(latest_ts) in header
    finally:
        if panel is not None:
            panel.Destroy()
        frame.Destroy()


def test_agent_chat_panel_embeds_tool_sections_inside_agent_bubble(tmp_path, wx_app):
    class ToolAgent:
        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
        ):
            return {
                "ok": True,
                "error": None,
                "result": "done",
                "tool_results": [
                    {
                        "tool_name": "demo_tool",
                        "ok": True,
                        "tool_arguments": {"query": text},
                        "result": {"status": "ok"},
                    }
                ],
            }

    wx, frame, panel = create_panel(tmp_path, wx_app, ToolAgent())

    panel.input.SetValue("inspect")
    panel._on_send(None)
    flush_wx_events(wx)

    try:
        cards = [
            child
            for child in panel.transcript_panel.GetChildren()
            if isinstance(child, TurnCard)
        ]
        assert cards, "expected transcript entry"
        card = cards[0]

        bubbles = collect_message_bubbles(card)
        assert any(
            "You" in bubble_header_text(bubble) for bubble in bubbles
        ), "user bubble missing"

        agent_bubbles = [
            bubble
            for bubble in bubbles
            if "Agent" in bubble_header_text(bubble)
        ]
        assert len(agent_bubbles) == 1, "agent bubble missing"

        agent_panels = [
            child
            for child in card.GetChildren()
            if isinstance(child, MessageSegmentPanel)
            and any(
                "Agent" in bubble_header_text(bubble)
                for bubble in collect_message_bubbles(child)
            )
        ]
        assert agent_panels, "agent segment missing"
        agent_panel = agent_panels[0]

        panel_bubbles = collect_message_bubbles(agent_panel)
        headers = [bubble_header_text(bubble) for bubble in panel_bubbles]
        agent_indices = [
            index for index, header in enumerate(headers) if "Agent" in header
        ]
        tool_indices = [
            index for index, header in enumerate(headers) if "Tool" in header
        ]
        assert tool_indices, "tool summary bubble missing"
        assert agent_indices, "agent bubble missing inside panel"
        assert agent_indices[0] < tool_indices[0], "tool bubble should follow the agent response"

        conversation = panel._get_active_conversation()
        assert conversation is not None
        timeline = build_conversation_timeline(conversation)
        tool_events = timeline.entries[-1].agent_turn.tool_calls
        assert tool_events, "tool events missing from timeline"
        event = tool_events[0]
        entry_id = timeline.entries[-1].entry_id
        identifier = (
            f"tool:{entry_id}:{event.summary.index}"
            if event.summary.index
            else f"tool:{entry_id}:1"
        )

        pane_names = {pane.GetName() for pane in collect_collapsible_panes(agent_panel)}
        assert f"tool:raw:{identifier}" in pane_names, "raw payload pane missing"
    finally:
        destroy_panel(frame, panel)


def test_turn_card_renders_tool_only_entries(wx_app):
    wx = pytest.importorskip("wx")

    frame = wx.Frame(None)
    try:
        conversation, entry_timeline = build_entry_timeline(
            response="",
            response_at=None,
            tool_results=[
                {
                    "tool_name": "demo_tool",
                    "status": "completed",
                    "arguments": {"field": "value"},
                    "result": {"ok": True},
                }
            ],
        )
        panel = render_turn_card(
            frame,
            conversation=conversation,
            entry=entry_timeline,
            layout_hints=entry_timeline.layout_hints,
            on_layout_hint=None,
            on_regenerate=None,
            regenerate_enabled=True,
        )
        wx.GetApp().Yield()

        agent_bubbles = [
            bubble
            for bubble in collect_message_bubbles(panel)
            if "Agent" in bubble_header_text(bubble)
        ]
        assert not agent_bubbles, "tool-only turn should not render agent text"

        agent_panels = [
            child
            for child in panel.GetChildren()
            if isinstance(child, MessageSegmentPanel)
            and any(
                "Tool" in bubble_header_text(bubble)
                for bubble in collect_message_bubbles(child)
            )
        ]
        assert agent_panels, "agent panel with tool bubble missing"
        agent_panel = agent_panels[0]

        tool_bubbles = [
            bubble
            for bubble in collect_message_bubbles(agent_panel)
            if "Tool" in bubble_header_text(bubble)
        ]
        assert tool_bubbles, "tool summary bubble missing"
        assert any(
            "demo_tool" in bubble_body_text(bubble)
            or "Ran" in bubble_body_text(bubble)
            for bubble in tool_bubbles
        )

        timeline = build_conversation_timeline(conversation)
        tool_events = timeline.entries[0].agent_turn.tool_calls
        assert tool_events, "tool events missing"
        identifier = (
            f"tool:{entry_timeline.entry_id}:{tool_events[0].summary.index}"
            if tool_events[0].summary.index
            else f"tool:{entry_timeline.entry_id}:1"
        )
        pane_names = {pane.GetName() for pane in collect_collapsible_panes(agent_panel)}
        assert f"tool:raw:{identifier}" in pane_names
        assert all(
            name != f"tool:summary:{identifier}" for name in pane_names
        ), "unexpected summary collapsible present"
    finally:
        panel.Destroy()
        frame.Destroy()


@pytest.mark.gui_smoke
def test_agent_message_bubble_converts_html_breaks(wx_app):
    wx = pytest.importorskip("wx")

    frame = wx.Frame(None)
    bubble: MessageBubble | None = None
    try:
        conversation, entry_timeline = build_entry_timeline(
            response="First line<br>Second line",
        )
        agent_turn = entry_timeline.agent_turn
        assert agent_turn is not None, "agent turn missing"
        final_response = agent_turn.final_response
        assert final_response is not None, "final response missing"

        display_text = final_response.display_text or final_response.text or ""
        bubble = MessageBubble(
            frame,
            role_label=_("Agent"),
            timestamp="",
            text=display_text,
            align="left",
            allow_selection=True,
            render_markdown=True,
        )
        bubble_text = bubble_body_text(bubble)
        assert "\n" in bubble_text, "expected newline after HTML break conversion"

        lines = bubble_text.splitlines()
        assert len(lines) >= 2, "expected at least two lines in bubble body"
        assert lines[0].rstrip() == "First line"
        assert lines[1].rstrip() == "Second line"
        assert "<br" not in bubble_text.lower()

    finally:
        if bubble is not None:
            bubble.Destroy()
        frame.Destroy()


def test_turn_card_attaches_tools_to_stream_only_response(wx_app):
    wx = pytest.importorskip("wx")

    frame = wx.Frame(None)
    try:
        response_ts = "2025-01-01T10:01:00+00:00"
        conversation, entry_timeline = build_entry_timeline(
            response="",
            response_at=None,
            tool_results=[
                {
                    "tool_name": "demo_tool",
                    "status": "completed",
                    "completed_at": "2025-01-01T10:01:05+00:00",
                    "result": {"ok": True},
                }
            ],
            raw_payload={
                "diagnostic": {
                    "llm_steps": [
                        {
                            "step": 1,
                            "response": {
                                "content": "Streamed answer",
                                "timestamp": response_ts,
                            },
                        }
                    ]
                }
            },
        )
        panel = render_turn_card(
            frame,
            conversation=conversation,
            entry=entry_timeline,
            layout_hints=entry_timeline.layout_hints,
            on_layout_hint=None,
            on_regenerate=None,
            regenerate_enabled=True,
        )
        wx.GetApp().Yield()

        agent_bubbles = [
            bubble
            for bubble in collect_message_bubbles(panel)
            if "Agent" in bubble_header_text(bubble)
        ]
        assert len(agent_bubbles) == 1, "expected a single agent bubble"
        agent_bubble = agent_bubbles[0]

        header = bubble_header_text(agent_bubble)
        expected_timestamp = format_entry_timestamp(response_ts)
        assert expected_timestamp in header
        body = bubble_body_text(agent_bubble)
        assert "Streamed answer" in body

        agent_panels = [
            child
            for child in panel.GetChildren()
            if isinstance(child, MessageSegmentPanel)
            and any(
                "Tool" in bubble_header_text(bubble)
                for bubble in collect_message_bubbles(child)
            )
        ]
        assert agent_panels, "tool bubble should be embedded in agent panel"
        agent_panel = agent_panels[0]
        pane_names = {pane.GetName() for pane in collect_collapsible_panes(agent_panel)}
        identifier = f"tool:{entry_timeline.entry_id}:1"
        assert f"tool:raw:{identifier}" in pane_names
        assert all(
            name != f"tool:summary:{identifier}" for name in pane_names
        ), "unexpected summary collapsible present"
    finally:
        panel.Destroy()
        frame.Destroy()


def test_turn_card_shows_reasoning(wx_app):
    wx = pytest.importorskip("wx")

    frame = wx.Frame(None)
    try:
        conversation, entry_timeline = build_entry_timeline(
            reasoning_segments=[
                {"type": "analysis", "text": "first step"},
                {"type": "", "text": "second step"},
            ]
        )
        panel = render_turn_card(
            frame,
            conversation=conversation,
            entry=entry_timeline,
            layout_hints=entry_timeline.layout_hints,
            on_layout_hint=None,
            on_regenerate=None,
            regenerate_enabled=True,
        )
        reasoning_pane = find_collapsible_by_name(
            panel, f"reasoning:{entry_timeline.entry_id}"
        )
        assert reasoning_pane is not None, "reasoning pane should be created"
        label_value = collapsible_label(reasoning_pane)
        if label_value:
            assert "reason" in label_value.lower()
        reasoning_pane.Expand()
        wx.GetApp().Yield()
        text_controls = [
            child
            for child in reasoning_pane.GetPane().GetChildren()
            if isinstance(child, wx.TextCtrl)
        ]
        assert text_controls, "reasoning pane should contain text control"
        value = text_controls[0].GetValue()
        assert "first step" in value
        assert "second step" in value
    finally:
        panel.Destroy()
        frame.Destroy()


def test_turn_card_shows_reasoning_for_each_step(wx_app):
    wx = pytest.importorskip("wx")

    frame = wx.Frame(None)
    try:
        raw_payload = {
            "ok": True,
            "status": "succeeded",
            "result": "done",
            "llm_trace": {
                "steps": [
                    {
                        "index": 1,
                        "occurred_at": "2025-01-01T10:00:00+00:00",
                        "request": [{"role": "user", "content": "hi"}],
                        "response": {
                            "content": "first chunk",
                            "reasoning": [
                                {"type": "analysis", "text": "plan tool one"}
                            ],
                        },
                    },
                    {
                        "index": 2,
                        "occurred_at": "2025-01-01T10:00:05+00:00",
                        "request": [{"role": "assistant", "content": "call tool"}],
                        "response": {
                            "content": "second chunk",
                            "reasoning": [
                                {"type": "analysis", "text": "plan tool two"}
                            ],
                        },
                    },
                ]
            },
            "tool_results": [
                {
                    "call_id": "call-1",
                    "tool_name": "alpha",
                    "status": "succeeded",
                    "started_at": "2025-01-01T10:00:10+00:00",
                    "completed_at": "2025-01-01T10:00:15+00:00",
                },
                {
                    "call_id": "call-2",
                    "tool_name": "beta",
                    "status": "succeeded",
                    "started_at": "2025-01-01T10:00:20+00:00",
                    "completed_at": "2025-01-01T10:00:25+00:00",
                },
            ],
        }
        conversation, entry_timeline = build_entry_timeline(
            prompt="user",
            response="assistant",
            prompt_at="2025-01-01T10:00:00+00:00",
            response_at="2025-01-01T10:00:30+00:00",
            raw_payload=raw_payload,
        )

        panel = render_turn_card(
            frame,
            conversation=conversation,
            entry=entry_timeline,
            layout_hints=entry_timeline.layout_hints,
            on_layout_hint=None,
            on_regenerate=None,
            regenerate_enabled=True,
        )
        wx.GetApp().Yield()

        agent_panels = [
            child
            for child in panel.GetChildren()
            if isinstance(child, MessageSegmentPanel)
        ]
        assert agent_panels, "agent panel missing"
        agent_panel = next(
            (
                candidate
                for candidate in agent_panels
                if any(
                    "reasoning" in pane.GetName()
                    for pane in collect_collapsible_panes(candidate)
                )
            ),
            agent_panels[0],
        )
        reasoning_panes = collect_collapsible_panes(agent_panel)
        reasoning_names = {
            pane.GetName() for pane in reasoning_panes if "reasoning" in pane.GetName()
        }
        base_key = f"reasoning:{entry_timeline.entry_id}"
        assert f"{base_key}:step-1" in reasoning_names
        assert f"{base_key}:step-2" in reasoning_names

        container = reasoning_panes[0].GetParent()
        ordered_widgets: list[wx.Window] = []
        for item in container.GetSizer().GetChildren():
            widget = item.GetWindow()
            if widget is not None:
                ordered_widgets.append(widget)

        def _index_of(fragment: str) -> int:
            for idx, widget in enumerate(ordered_widgets):
                if isinstance(widget, wx.CollapsiblePane) and fragment in widget.GetName():
                    return idx
                if isinstance(widget, MessageBubble):
                    header = bubble_header_text(widget)
                    if fragment in header:
                        return idx
            return -1

        first_reasoning_index = _index_of("step-1")
        first_tool_index = next(
            (
                idx
                for idx, widget in enumerate(ordered_widgets)
                if isinstance(widget, MessageBubble)
                and "Tool" in bubble_header_text(widget)
            ),
            -1,
        )
        assert 0 <= first_reasoning_index < first_tool_index

        second_reasoning_index = _index_of("step-2")
        second_tool_index = next(
            (
                idx
                for idx, widget in enumerate(ordered_widgets)
                if isinstance(widget, MessageBubble)
                and "Tool" in bubble_header_text(widget)
                and "beta" in bubble_body_text(widget)
            ),
            -1,
        )
        assert 0 <= second_reasoning_index < second_tool_index
    finally:
        panel.Destroy()
        frame.Destroy()


def test_turn_card_orders_tools_by_timestamp_without_event_log(wx_app):
    wx = pytest.importorskip("wx")

    frame = wx.Frame(None)
    try:
        raw_payload = {
            "ok": True,
            "status": "succeeded",
            "result": "done",
            "llm_trace": {
                "steps": [
                    {
                        "index": 1,
                        "occurred_at": "2025-01-01T10:00:00+00:00",
                        "request": [{"role": "user", "content": "hi"}],
                        "response": {
                            "content": "first chunk",
                            "reasoning": [
                                {"type": "analysis", "text": "plan tool one"}
                            ],
                        },
                    },
                    {
                        "index": 2,
                        "occurred_at": "2025-01-01T10:00:25+00:00",
                        "request": [{"role": "assistant", "content": "call tool"}],
                        "response": {
                            "content": "second chunk",
                            "reasoning": [
                                {"type": "analysis", "text": "plan tool two"}
                            ],
                        },
                    },
                ]
            },
            "tool_results": [
                {
                    "call_id": "call-1",
                    "tool_name": "alpha",
                    "status": "succeeded",
                    "started_at": "2025-01-01T10:00:10+00:00",
                    "completed_at": "2025-01-01T10:00:12+00:00",
                },
                {
                    "call_id": "call-2",
                    "tool_name": "beta",
                    "status": "succeeded",
                    "started_at": "2025-01-01T10:00:30+00:00",
                    "completed_at": "2025-01-01T10:00:35+00:00",
                },
            ],
        }

        conversation, entry_timeline = build_entry_timeline(
            prompt="user",
            response="assistant",
            prompt_at="2025-01-01T10:00:00+00:00",
            response_at="2025-01-01T10:00:40+00:00",
            raw_payload=raw_payload,
        )

        panel = render_turn_card(
            frame,
            conversation=conversation,
            entry=entry_timeline,
            layout_hints=entry_timeline.layout_hints,
            on_layout_hint=None,
            on_regenerate=None,
            regenerate_enabled=True,
        )
        wx.GetApp().Yield()

        agent_panels = [
            child
            for child in panel.GetChildren()
            if isinstance(child, MessageSegmentPanel)
        ]
        assert agent_panels, "agent panel missing"
        agent_panel = next(
            (
                candidate
                for candidate in agent_panels
                if any(
                    "Tool" in bubble_header_text(bubble)
                    for bubble in collect_message_bubbles(candidate)
                )
            ),
            agent_panels[0],
        )
        reasoning_panes = collect_collapsible_panes(agent_panel)
        assert reasoning_panes, "reasoning pane missing"
        container = reasoning_panes[0].GetParent()
        ordered_widgets: list[wx.Window] = []
        for item in container.GetSizer().GetChildren():
            widget = item.GetWindow()
            if widget is not None:
                ordered_widgets.append(widget)

        def _index_of(fragment: str) -> int:
            for idx, widget in enumerate(ordered_widgets):
                if isinstance(widget, wx.CollapsiblePane) and fragment in widget.GetName():
                    return idx
                if isinstance(widget, MessageBubble):
                    header = bubble_header_text(widget)
                    body = bubble_body_text(widget)
                    if fragment in header or fragment in body:
                        return idx
            return -1

        first_reasoning_index = _index_of("step-1")
        second_reasoning_index = _index_of("step-2")
        first_tool_index = _index_of("alpha")

        assert first_reasoning_index != -1, "step-1 reasoning missing"
        assert second_reasoning_index != -1, "step-2 reasoning missing"
        assert first_tool_index != -1, "first tool bubble missing"

        assert first_reasoning_index < first_tool_index < second_reasoning_index
    finally:
        panel.Destroy()
        frame.Destroy()


def test_turn_card_shows_step_reasoning_when_entry_has_aggregate_reasoning(wx_app):
    wx = pytest.importorskip("wx")

    frame = wx.Frame(None)
    try:
        reasoning_segments = [
            {"type": "analysis", "text": "plan tool one"},
            {"type": "analysis", "text": "plan tool two"},
        ]
        raw_payload = {
            "ok": True,
            "status": "succeeded",
            "result": "done",
            "llm_trace": {
                "steps": [
                    {
                        "index": 1,
                        "occurred_at": "2025-01-01T10:00:00+00:00",
                        "request": [{"role": "user", "content": "hi"}],
                        "response": {
                            "content": "first chunk",
                            "reasoning": [dict(reasoning_segments[0])],
                        },
                    },
                    {
                        "index": 2,
                        "occurred_at": "2025-01-01T10:00:05+00:00",
                        "request": [{"role": "assistant", "content": "call tool"}],
                        "response": {
                            "content": "second chunk",
                            "reasoning": [dict(reasoning_segments[1])],
                        },
                    },
                ]
            },
            "tool_results": [
                {
                    "call_id": "call-1",
                    "tool_name": "alpha",
                    "status": "succeeded",
                    "started_at": "2025-01-01T10:00:10+00:00",
                    "completed_at": "2025-01-01T10:00:15+00:00",
                },
                {
                    "call_id": "call-2",
                    "tool_name": "beta",
                    "status": "succeeded",
                    "started_at": "2025-01-01T10:00:20+00:00",
                    "completed_at": "2025-01-01T10:00:25+00:00",
                },
            ],
        }

        conversation, entry_timeline = build_entry_timeline(
            prompt="user",
            response="assistant",
            prompt_at="2025-01-01T10:00:00+00:00",
            response_at="2025-01-01T10:00:30+00:00",
            reasoning_segments=reasoning_segments,
            raw_payload=raw_payload,
        )

        panel = render_turn_card(
            frame,
            conversation=conversation,
            entry=entry_timeline,
            layout_hints=entry_timeline.layout_hints,
            on_layout_hint=None,
            on_regenerate=None,
            regenerate_enabled=True,
        )
        wx.GetApp().Yield()

        agent_panels = [
            child
            for child in panel.GetChildren()
            if isinstance(child, MessageSegmentPanel)
        ]
        assert agent_panels, "agent panel missing"
        agent_panel = next(
            (
                candidate
                for candidate in agent_panels
                if any(
                    "reasoning" in pane.GetName()
                    for pane in collect_collapsible_panes(candidate)
                )
                or any(
                    "Tool" in bubble_header_text(bubble)
                    for bubble in collect_message_bubbles(candidate)
                )
            ),
            agent_panels[0],
        )
        reasoning_panes = collect_collapsible_panes(agent_panel)
        reasoning_names = {
            pane.GetName() for pane in reasoning_panes if "reasoning" in pane.GetName()
        }
        base_key = f"reasoning:{entry_timeline.entry_id}"
        assert f"{base_key}:step-1" in reasoning_names
        assert f"{base_key}:step-2" in reasoning_names
        assert base_key not in reasoning_names, "aggregate reasoning should not replace steps"

        container = reasoning_panes[0].GetParent()
        ordered_widgets: list[wx.Window] = []
        for item in container.GetSizer().GetChildren():
            widget = item.GetWindow()
            if widget is not None:
                ordered_widgets.append(widget)

        def _index_of(fragment: str) -> int:
            for idx, widget in enumerate(ordered_widgets):
                if isinstance(widget, wx.CollapsiblePane) and fragment in widget.GetName():
                    return idx
                if isinstance(widget, MessageBubble):
                    header = bubble_header_text(widget)
                    if fragment in header:
                        return idx
            return -1

        first_reasoning_index = _index_of("step-1")
        first_tool_index = next(
            (
                idx
                for idx, widget in enumerate(ordered_widgets)
                if isinstance(widget, MessageBubble)
                and "Tool" in bubble_header_text(widget)
                and "alpha" in bubble_body_text(widget)
            ),
            -1,
        )
        assert 0 <= first_reasoning_index < first_tool_index

        second_reasoning_index = _index_of("step-2")
        second_tool_index = next(
            (
                idx
                for idx, widget in enumerate(ordered_widgets)
                if isinstance(widget, MessageBubble)
                and "Tool" in bubble_header_text(widget)
                and "beta" in bubble_body_text(widget)
            ),
            -1,
        )
        assert 0 <= second_reasoning_index < second_tool_index
    finally:
        panel.Destroy()
        frame.Destroy()


def test_turn_card_orders_sections(wx_app):
    wx = pytest.importorskip("wx")

    frame = wx.Frame(None)
    try:
        prompt_ts = "2024-06-11 18:41:03"
        response_ts = "2024-06-11 18:42:07"
        raw_payload = {
            "llm_message": {
                "id": "msg-1",
                "content": "assistant reply",
                "role": "assistant",
            },
            "reasoning": [{"type": "analysis", "text": "think"}],
            "llm_trace": {
                "steps": [
                    {
                        "index": 1,
                        "occurred_at": "2024-06-11T18:41:03+00:00",
                        "request": [
                            {"role": "system", "content": "ctx"},
                            {"role": "user", "content": "demo"},
                        ],
                        "response": {},
                    }
                ]
            },
        }
        tool_payload = {
            "tool_name": "demo_tool",
            "ok": True,
            "bullet_lines": ["processed input"],
            "started_at": "2025-09-30T20:50:10+00:00",
            "completed_at": "2025-09-30T20:50:11+00:00",
            "result": {"status": "ok"},
        }
        conversation, entry_timeline = build_entry_timeline(
            prompt="user",
            response="assistant",
            prompt_at=prompt_ts,
            response_at=response_ts,
            context_messages=[{"role": "system", "content": "ctx"}],
            reasoning_segments=[{"type": "analysis", "text": "think"}],
            tool_results=[tool_payload],
            raw_payload=raw_payload,
        )
        panel = render_turn_card(
            frame,
            conversation=conversation,
            entry=entry_timeline,
            layout_hints=entry_timeline.layout_hints,
            on_layout_hint=None,
            on_regenerate=None,
            regenerate_enabled=True,
        )
        wx.GetApp().Yield()

        bubbles = collect_message_bubbles(panel)
        assert len(bubbles) == 3

        user_bubble = next(b for b in bubbles if "You" in bubble_header_text(b))
        assert "You" in bubble_header_text(user_bubble)
        agent_bubble = next(
            b for b in bubbles if "Agent" in bubble_header_text(b)
        )
        assert bubble_body_text(agent_bubble)
        tool_bubble = next(
            b for b in bubbles if "Tool" in bubble_header_text(b)
        )
        tool_text = bubble_body_text(tool_bubble)
        assert "demo_tool" in tool_text
        assert "•" in tool_text

        context_pane = find_collapsible_by_name(
            panel, f"context:{entry_timeline.entry_id}"
        )
        assert context_pane is not None
        reasoning_pane = find_collapsible_by_name(
            panel, f"reasoning:{entry_timeline.entry_id}"
        )
        assert reasoning_pane is not None
        llm_request_pane = find_collapsible_by_name(
            panel, f"llm:{entry_timeline.entry_id}"
        )
        assert llm_request_pane is not None
        agent_raw_pane = find_collapsible_by_name(
            panel, f"raw:{entry_timeline.entry_id}"
        )
        assert agent_raw_pane is not None
        agent_panels = [
            child
            for child in panel.GetChildren()
            if isinstance(child, MessageSegmentPanel)
            and any(
                "Tool" in bubble_header_text(bubble)
                for bubble in collect_message_bubbles(child)
            )
        ]
        assert agent_panels, "tool bubble missing"
        agent_panel = agent_panels[0]
        tool_panes = collect_collapsible_panes(agent_panel)
        names = {pane.GetName() for pane in tool_panes}
        identifier = f"tool:{entry_timeline.entry_id}:1"
        assert f"tool:summary:{identifier}" not in names
        assert f"tool:raw:{identifier}" in names

        context_label = collapsible_label(context_pane)
        assert context_label.lower() in {"", _("Context").lower()}
        assert "reason" in collapsible_label(reasoning_pane).lower()
        assert "request" in collapsible_label(llm_request_pane).lower()
        assert "raw" in collapsible_label(agent_raw_pane).lower()

        frame.SendSizeEvent()
        panel.Layout()
        wx.GetApp().Yield()

        for pane in (
            context_pane,
            reasoning_pane,
            llm_request_pane,
            agent_raw_pane,
        ):
            sizer = pane.GetContainingSizer()
            assert sizer is not None and sizer.IsShown(pane)
            pane.Layout()
            measured_height = max(
                pane.GetSize().GetHeight(), pane.GetBestSize().GetHeight()
            )
            assert measured_height > 0
            header_getter = getattr(pane, "GetButton", None)
            if callable(header_getter):
                header = header_getter()
                if header is not None:
                    assert header.IsShown()
                    assert header.GetSize().GetHeight() > 0
    finally:
        panel.Destroy()
        frame.Destroy()


def test_turn_card_reuses_layout_hints(wx_app):
    wx = pytest.importorskip("wx")

    frame = wx.Frame(None)
    first_panel = None
    second_panel = None
    try:
        recorded_hints: dict[str, int] = {}

        def store_hint(key: str, width: int) -> None:
            recorded_hints[key] = int(width)

        long_conversation, long_entry = build_entry_timeline(
            prompt="hello",
            response="this is a fairly long answer " * 8,
        )
        first_panel = render_turn_card(
            frame,
            conversation=long_conversation,
            entry=long_entry,
            layout_hints=long_entry.layout_hints,
            on_layout_hint=store_hint,
            on_regenerate=None,
            regenerate_enabled=True,
        )
        if frame.GetSizer() is None:
            frame.SetSizer(wx.BoxSizer(wx.VERTICAL))
        sizer = frame.GetSizer()
        sizer.Add(first_panel, 1, wx.EXPAND)
        wx.GetApp().Yield()

        agent_hint = recorded_hints.get("agent")
        assert agent_hint is not None and agent_hint > 0, "agent width hint should be recorded"

        sizer.Detach(first_panel)
        first_panel.Destroy()
        first_panel = None
        recorded_hints.clear()

        short_conversation, short_entry = build_entry_timeline(
            prompt="hello", response="short"
        )
        second_panel = render_turn_card(
            frame,
            conversation=short_conversation,
            entry=short_entry,
            layout_hints={"agent": agent_hint},
            on_layout_hint=None,
            on_regenerate=None,
            regenerate_enabled=True,
        )
        sizer.Add(second_panel, 1, wx.EXPAND)
        wx.GetApp().Yield()

        agent_bubbles = [
            bubble
            for bubble in collect_message_bubbles(second_panel)
            if "Agent" in bubble_header_text(bubble)
        ]
        assert agent_bubbles, "expected agent bubble"
        bubble = agent_bubbles[0]
        bubble_width = bubble.GetSize().width
        if bubble_width <= 0:
            bubble_width = bubble.GetBestSize().width
        tolerance = second_panel.FromDIP(8)
        assert bubble_width >= agent_hint - tolerance
    finally:
        if second_panel is not None:
            second_panel.Destroy()
        if first_panel is not None:
            first_panel.Destroy()
        frame.Destroy()


def test_tool_sections_follow_agent_response(wx_app):
    wx = pytest.importorskip("wx")

    frame = wx.Frame(None)
    panel = None
    try:
            conversation, entry_timeline = build_entry_timeline(
                response="Agent answer",
                response_at="2025-01-01T10:01:00+00:00",
                tool_results=[
                    {
                        "tool_name": "update_requirement_field",
                        "tool_call_id": "call-1",
                        "started_at": "2025-01-01T09:59:30+00:00",
                        "completed_at": "2025-01-01T09:59:45+00:00",
                        "ok": False,
                        "error": {
                            "code": "VALIDATION_ERROR",
                            "message": "Missing rid",
                        },
                    }
                ],
                raw_payload={
                    "diagnostic": {
                        "llm_steps": [
                            {
                                "response": {
                                    "content": "Applying updates",
                                    "tool_calls": [
                                        {
                                            "id": "call-1",
                                            "name": "update_requirement_field",
                                            "arguments": {
                                                "rid": "REQ-1",
                                                "field": "title",
                                                "value": "Новое имя",
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                },
            )
            panel = render_turn_card(
                frame,
                conversation=conversation,
                entry=entry_timeline,
                layout_hints={},
                on_layout_hint=None,
                on_regenerate=None,
                regenerate_enabled=True,
            )
            if frame.GetSizer() is None:
                frame.SetSizer(wx.BoxSizer(wx.VERTICAL))
            frame.GetSizer().Add(panel, 1, wx.EXPAND)
            wx.GetApp().Yield()

            agent_bubble = next(
                (
                    bubble
                    for bubble in collect_message_bubbles(panel)
                    if "Agent" in bubble_header_text(bubble)
                ),
                None,
            )
            assert agent_bubble is not None, "agent bubble should be present"

            agent_panel = next(
                (
                    child
                    for child in panel.GetChildren()
                    if isinstance(child, MessageSegmentPanel)
                    and agent_bubble in collect_message_bubbles(child)
                ),
                None,
            )
            assert agent_panel is not None, "agent segment missing"
            panel_bubbles = collect_message_bubbles(agent_panel)
            timeline_order = [
                "tool" if evt.kind == "tool" else "response"
                for evt in entry_timeline.agent_turn.events
                if evt.kind in {"tool", "response"}
            ]
            bubble_order = [
                "tool" if "Tool" in bubble_header_text(bubble) else "response"
                for bubble in panel_bubbles
                if "Tool" in bubble_header_text(bubble)
                or "Agent" in bubble_header_text(bubble)
            ]
            assert bubble_order[: len(timeline_order)] == timeline_order
    finally:
        if panel is not None:
            panel.Destroy()
        frame.Destroy()


def test_agent_bubbles_follow_event_log_sequence(wx_app):
    wx = pytest.importorskip("wx")

    frame = wx.Frame(None)
    panel = None
    try:
        payload = AgentRunPayload(
            ok=True,
            status="succeeded",
            result_text="final",
            events=AgentEventLog(
                events=[
                    AgentEvent(
                        kind="llm_step",
                        occurred_at="2025-01-01T12:00:05+00:00",
                        payload={
                            "index": 0,
                            "request": (),
                            "response": {"content": "Working"},
                        },
                    ),
                    AgentEvent(
                        kind="tool_completed",
                        occurred_at="2025-01-01T12:00:02+00:00",
                        payload={"call_id": "call-1", "status": "succeeded"},
                    ),
                    AgentEvent(
                        kind="agent_finished",
                        occurred_at="2025-01-01T12:00:06+00:00",
                        payload={"ok": True, "status": "succeeded", "result": "final"},
                    ),
                ]
            ),
            tool_results=[
                ToolResultSnapshot(
                    call_id="call-1",
                    tool_name="update_requirement_field",
                    status="succeeded",
                    sequence=1,
                    started_at="2025-01-01T12:00:01+00:00",
                    completed_at="2025-01-01T12:00:02+00:00",
                )
            ],
            llm_trace=LlmTrace(
                steps=[
                    LlmStep(
                        index=0,
                        occurred_at="2025-01-01T12:00:05+00:00",
                        request=(),
                        response={"content": "Working"},
                    )
                ]
            ),
            reasoning=(),
        ).to_dict()

        conversation, entry_timeline = build_entry_timeline(
            prompt="Do the thing",
            response="final",
            response_at="2025-01-01T12:00:06+00:00",
            prompt_at="2025-01-01T12:00:00+00:00",
            raw_payload=payload,
        )
        panel = render_turn_card(
            frame,
            conversation=conversation,
            entry=entry_timeline,
            layout_hints={},
            on_layout_hint=None,
            on_regenerate=None,
            regenerate_enabled=True,
        )
        if frame.GetSizer() is None:
            frame.SetSizer(wx.BoxSizer(wx.VERTICAL))
        frame.GetSizer().Add(panel, 1, wx.EXPAND)
        wx.GetApp().Yield()

        agent_bubble = next(
            (
                bubble
                for bubble in collect_message_bubbles(panel)
                if "Agent" in bubble_header_text(bubble)
            ),
            None,
        )
        assert agent_bubble is not None, "agent bubble should be present"

        agent_panel = next(
            (
                child
                for child in panel.GetChildren()
                if isinstance(child, MessageSegmentPanel)
                and agent_bubble in collect_message_bubbles(child)
            ),
            None,
        )
        assert agent_panel is not None, "agent segment missing"

        panel_bubbles = collect_message_bubbles(agent_panel)
        timeline_order = [
            "tool" if evt.kind == "tool" else "response"
            for evt in entry_timeline.agent_turn.events
            if evt.kind in {"tool", "response"}
        ]
        assert timeline_order == ["response", "tool", "response"]
        bubble_order = [
            "tool" if "Tool" in bubble_header_text(bubble) else "response"
            for bubble in panel_bubbles
            if "Tool" in bubble_header_text(bubble)
            or "Agent" in bubble_header_text(bubble)
        ]

        assert bubble_order[: len(timeline_order)] == timeline_order
    finally:
        if panel is not None:
            panel.Destroy()
        frame.Destroy()


def test_tool_summary_includes_llm_exchange(wx_app):
    wx = pytest.importorskip("wx")

    frame = wx.Frame(None)
    panel = None
    try:
        conversation, entry_timeline = build_entry_timeline(
            response="Agent answer",
            response_at="2025-01-01T10:01:00+00:00",
            tool_results=[
                {
                    "tool_name": "update_requirement_field",
                    "tool_call_id": "call-1",
                    "started_at": "2025-01-01T09:59:30+00:00",
                    "completed_at": "2025-01-01T09:59:45+00:00",
                    "ok": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Missing rid",
                    },
                }
            ],
            raw_payload={
                "diagnostic": {
                    "llm_steps": [
                        {
                            "response": {
                                "content": "Applying updates",
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "name": "update_requirement_field",
                                        "arguments": {
                                            "rid": "REQ-1",
                                            "field": "title",
                                            "value": "Новое имя",
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            },
        )

        panel = render_turn_card(
            frame,
            conversation=conversation,
            entry=entry_timeline,
            layout_hints={},
            on_layout_hint=None,
            on_regenerate=None,
            regenerate_enabled=True,
        )
        if frame.GetSizer() is None:
            frame.SetSizer(wx.BoxSizer(wx.VERTICAL))
        frame.GetSizer().Add(panel, 1, wx.EXPAND)
        wx.GetApp().Yield()

        agent_panels = [
            child
            for child in panel.GetChildren()
            if isinstance(child, MessageSegmentPanel)
            and any(
                "Tool" in bubble_header_text(bubble)
                for bubble in collect_message_bubbles(child)
            )
        ]
        assert agent_panels, "tool panel missing"
        agent_panel = agent_panels[0]

        entry_key = f"tool:{entry_timeline.entry_id}:1"
        panes_by_name = {
            pane.GetName(): pane for pane in collect_collapsible_panes(agent_panel)
        }
        tool_bubbles = [
            bubble
            for bubble in collect_message_bubbles(agent_panel)
            if "Tool" in bubble_header_text(bubble)
        ]
        assert tool_bubbles, "tool summary bubble missing"
        bubble_text = "\n".join(bubble_body_text(bubble) for bubble in tool_bubbles)
        assert "update_requirement_field" in bubble_text
        assert "VALIDATION_ERROR" in bubble_text

        raw_pane = panes_by_name.get(f"tool:raw:{entry_key}")
        assert raw_pane is not None
        raw_texts = [
            child.GetValue()
            for child in raw_pane.GetPane().GetChildren()
            if isinstance(child, wx.TextCtrl)
        ]
        raw_text = "\n".join(raw_texts)
        assert "llm_request" in raw_text
        assert "llm_response" in raw_text
        assert "update_requirement_field" in raw_text

        agent_bubbles = [
            bubble
            for bubble in collect_message_bubbles(panel)
            if "Agent" in bubble_header_text(bubble)
        ]
        assert len(agent_bubbles) == 2
        step_bubble, final_bubble = agent_bubbles
        step_index = entry_timeline.agent_turn.streamed_responses[0].step_index
        expected_label = i18n.gettext("Step {index}").format(index=step_index)
        assert expected_label in bubble_header_text(step_bubble)
        assert "Applying updates" in bubble_body_text(step_bubble)
        assert "Agent answer" in bubble_body_text(final_bubble)

        step_y = step_bubble.GetScreenPosition()[1]
        final_y = final_bubble.GetScreenPosition()[1]
        assert step_y <= final_y

    finally:
        if panel is not None:
            panel.Destroy()
        frame.Destroy()


def test_agent_transcript_log_orders_sections_for_errors(tmp_path, wx_app):
    class ErrorAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid arguments",
                },
                "raw": {
                    "llm_trace": {
                        "steps": [
                            {
                                "index": 1,
                                "occurred_at": "2024-06-11T18:41:03+00:00",
                                "request": [
                                    {"role": "system", "content": "ctx"},
                                    {"role": "user", "content": text},
                                ],
                                "response": {},
                            }
                        ]
                    },
                    "llm_message": {"id": "error-1", "content": "", "role": "assistant"},
                },
            }

    wx, frame, panel = create_panel(tmp_path, wx_app, ErrorAgent())

    panel.input.SetValue("trigger error")
    panel._on_send(None)
    flush_wx_events(wx)

    try:
        log_text = panel.get_transcript_log_text()
        assert "VALIDATION_ERROR" in log_text

        agent_index = log_text.index("Agent:")
        llm_prefix = "LLM request:"
        raw_prefix = "Raw LLM payload:"
        has_llm = llm_prefix in log_text
        has_raw = raw_prefix in log_text
        if has_llm:
            llm_index = log_text.index(llm_prefix)
            if has_raw:
                raw_index = log_text.index(raw_prefix)
                assert agent_index < llm_index < raw_index
            else:
                assert agent_index < llm_index
        elif has_raw:
            raw_index = log_text.index(raw_prefix)
            assert agent_index < raw_index
        assert "\"error\"" in log_text
    finally:
        destroy_panel(frame, panel)


def test_agent_transcript_log_includes_planned_tool_calls(tmp_path, wx_app):
    class ToolErrorAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid arguments",
                    "details": {
                        "type": "ToolValidationError",
                        "llm_message": "Preparing the request",
                        "llm_tool_calls": [
                            {
                                "id": "call-0",
                                "type": "function",
                                "function": {
                                    "name": "create_requirement",
                                    "arguments": "{\"prefix\": \"SYS\", \"data\": {\"title\": \"Req\"}}",
                                },
                            }
                        ],
                    },
                },
            }

    wx, frame, panel = create_panel(tmp_path, wx_app, ToolErrorAgent())

    panel.input.SetValue("draft requirement")
    panel._on_send(None)
    flush_wx_events(wx)

    try:
        log_text = panel.get_transcript_log_text()
        assert "\"llm_tool_calls\"" in log_text
        assert "create_requirement" in log_text
        assert "\"prefix\": \"SYS\"" in log_text
    finally:
        destroy_panel(frame, panel)


def test_agent_message_copy_selection(monkeypatch, wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.widgets.chat_message import MessageBubble

    clipboard: dict[str, str] = {}

    class DummyClipboard:
        def Open(self) -> bool:  # noqa: N802 - wx naming convention
            return True

        def Close(self) -> None:  # noqa: N802 - wx naming convention
            pass

        def SetData(self, data) -> None:  # noqa: N802 - wx naming convention
            clipboard["text"] = data.GetText()

    monkeypatch.setattr(wx, "TheClipboard", DummyClipboard())

    frame = wx.Frame(None)
    bubble = MessageBubble(
        frame,
        role_label="Agent",
        timestamp="",
        text="selectable text",
        align="left",
        allow_selection=True,
        render_markdown=True,
    )

    from app.ui.widgets.markdown_view import MarkdownContent

    assert isinstance(bubble._text, MarkdownContent)
    bubble._text.SelectAll()

    bubble._on_copy_selection(None)

    assert clipboard.get("text", "").strip().startswith("selectable text")

    bubble.Destroy()
    frame.Destroy()


def test_message_bubble_keyboard_copy_selection(monkeypatch, wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.widgets.chat_message import MessageBubble

    clipboard: dict[str, str] = {}

    class DummyClipboard:
        def Open(self) -> bool:  # noqa: N802 - wx naming convention
            return True

        def Close(self) -> None:  # noqa: N802 - wx naming convention
            pass

        def SetData(self, data) -> None:  # noqa: N802 - wx naming convention
            clipboard["text"] = data.GetText()

    class FakeKeyEvent:
        def __init__(self, key_code: int, *, cmd: bool = False, control: bool = False) -> None:
            self._key_code = key_code
            self._cmd = cmd
            self._control = control
            self._skipped: bool | None = None

        def GetKeyCode(self) -> int:
            return self._key_code

        def CmdDown(self) -> bool:
            return self._cmd

        def ControlDown(self) -> bool:
            return self._control

        def Skip(self, value: bool = True) -> None:
            self._skipped = value

    monkeypatch.setattr(wx, "TheClipboard", DummyClipboard())

    frame = wx.Frame(None)
    bubble = MessageBubble(
        frame,
        role_label="Agent",
        timestamp="",
        text="selectable text",
        align="left",
        allow_selection=True,
        render_markdown=True,
    )

    from app.ui.widgets.markdown_view import MarkdownContent

    assert isinstance(bubble._text, MarkdownContent)
    bubble._text.SelectAll()

    event = FakeKeyEvent(ord("C"), cmd=True, control=True)
    handled = bubble._process_copy_shortcut(event)

    assert handled
    assert event._skipped is False
    assert clipboard.get("text", "").strip().startswith("selectable text")

    event_insert = FakeKeyEvent(wx.WXK_INSERT, control=True)
    handled_insert = bubble._process_copy_shortcut(event_insert)

    assert handled_insert
    assert event_insert._skipped is False

    bubble.Destroy()
    frame.Destroy()


def test_message_bubble_keyboard_copy_message(monkeypatch, wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.widgets.chat_message import MessageBubble

    clipboard: dict[str, str] = {}

    class DummyClipboard:
        def Open(self) -> bool:  # noqa: N802 - wx naming convention
            return True

        def Close(self) -> None:  # noqa: N802 - wx naming convention
            pass

        def SetData(self, data) -> None:  # noqa: N802 - wx naming convention
            clipboard["text"] = data.GetText()

    class FakeKeyEvent:
        def __init__(self, key_code: int, *, cmd: bool = False, control: bool = False) -> None:
            self._key_code = key_code
            self._cmd = cmd
            self._control = control
            self._skipped: bool | None = None

        def GetKeyCode(self) -> int:
            return self._key_code

        def CmdDown(self) -> bool:
            return self._cmd

        def ControlDown(self) -> bool:
            return self._control

        def Skip(self, value: bool = True) -> None:
            self._skipped = value

    monkeypatch.setattr(wx, "TheClipboard", DummyClipboard())

    frame = wx.Frame(None)
    bubble = MessageBubble(
        frame,
        role_label="Agent",
        timestamp="",
        text="plain text message",
        align="left",
        allow_selection=False,
        render_markdown=False,
    )

    event = FakeKeyEvent(ord("C"), cmd=True, control=True)
    handled = bubble._process_copy_shortcut(event)

    assert handled
    assert event._skipped is False
    assert clipboard.get("text", "") == "plain text message"

    event_insert = FakeKeyEvent(wx.WXK_INSERT, control=True)
    handled_insert = bubble._process_copy_shortcut(event_insert)

    assert handled_insert
    assert event_insert._skipped is False
    assert clipboard.get("text", "") == "plain text message"

    bubble.Destroy()
    frame.Destroy()


def test_message_bubble_respects_scrolled_viewport_width(wx_app):
    wx = pytest.importorskip("wx")
    from wx.lib.scrolledpanel import ScrolledPanel

    frame = wx.Frame(None, size=wx.Size(1024, 768))
    scrolled = ScrolledPanel(frame, style=wx.TAB_TRAVERSAL)
    scrolled_sizer = wx.BoxSizer(wx.VERTICAL)
    scrolled.SetSizer(scrolled_sizer)

    bubble = MessageBubble(
        scrolled,
        role_label="Agent",
        timestamp="",
        text="agent response " * 200,
        align="left",
        allow_selection=True,
        render_markdown=True,
    )
    padding = bubble.FromDIP(4)
    scrolled_sizer.Add(bubble, 0, wx.EXPAND | wx.ALL, padding)

    frame_sizer = wx.BoxSizer(wx.VERTICAL)
    frame_sizer.Add(scrolled, 1, wx.EXPAND)
    frame.SetSizer(frame_sizer)
    frame.Layout()
    scrolled.SetupScrolling(scroll_x=False, scroll_y=True)
    frame.Show()
    flush_wx_events(wx, count=10)

    def _inner_panel(target: MessageBubble) -> wx.Panel:
        panels = [
            child for child in target.GetChildren() if isinstance(child, wx.Panel)
        ]
        assert panels, "bubble should host an inner panel"
        return panels[0]

    try:
        inner_panel = _inner_panel(bubble)
        viewport_width = scrolled.GetClientSize().width
        assert viewport_width > 0
        flush_wx_events(wx, count=2)

        inner_width = inner_panel.GetSize().width
        assert inner_width <= viewport_width
        assert inner_width >= int(viewport_width * 0.65)

        frame.SetClientSize(wx.Size(640, frame.GetClientSize().height))
        frame.Layout()
        scrolled.Layout()
        scrolled.SetupScrolling(scroll_x=False, scroll_y=True)
        flush_wx_events(wx, count=10)

        resized_panel = _inner_panel(bubble)
        resized_width = resized_panel.GetSize().width
        shrunk_viewport = scrolled.GetClientSize().width
        assert shrunk_viewport < viewport_width
        assert resized_width <= shrunk_viewport
        assert resized_width >= int(shrunk_viewport * 0.65)
    finally:
        frame.Destroy()


@pytest.mark.gui_smoke
def test_agent_markdown_table_enables_horizontal_scroll(wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.widgets.chat_message import MessageBubble
    from app.ui.widgets.markdown_view import MarkdownContent

    frame = wx.Frame(None, size=wx.Size(720, 560))
    table_header = "| Column A | Column B | Column C |"
    table_rule = "|----------|----------|----------|"
    wide_cell = "LONGVALUE" * 64
    table_row = f"| {wide_cell} | {wide_cell} | {wide_cell} |"
    markdown = "\n".join((table_header, table_rule, table_row))

    bubble = MessageBubble(
        frame,
        role_label="Agent",
        timestamp="",
        text=markdown,
        align="left",
        allow_selection=True,
        render_markdown=True,
    )

    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(bubble, 0, wx.EXPAND | wx.ALL, bubble.FromDIP(12))
    frame.SetSizer(sizer)
    frame.Layout()
    frame.Show()
    flush_wx_events(wx, count=12)

    try:
        assert isinstance(bubble._text, MarkdownContent)
        scroller = bubble._text.GetScrollerWindow()
        assert scroller is not None
        client_width = scroller.GetClientSize().width
        virtual_width = scroller.GetVirtualSize().width
        assert virtual_width > client_width, (
            "expected markdown scroller to provide horizontal overflow"
        )
        assert scroller.HasScrollbar(wx.HORIZONTAL)
    finally:
        frame.Destroy()


@pytest.mark.gui_smoke
def test_agent_markdown_compact_content_hides_horizontal_scroll(wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.widgets.chat_message import MessageBubble
    from app.ui.widgets.markdown_view import MarkdownContent

    frame = wx.Frame(None, size=wx.Size(720, 560))
    markdown = "\n".join(
        (
            "| Key | Value |",
            "|-----|-------|",
            "| foo | bar   |",
        )
    )

    bubble = MessageBubble(
        frame,
        role_label="Agent",
        timestamp="",
        text=markdown,
        align="left",
        allow_selection=True,
        render_markdown=True,
    )

    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(bubble, 0, wx.EXPAND | wx.ALL, bubble.FromDIP(12))
    frame.SetSizer(sizer)
    frame.Layout()
    frame.Show()
    flush_wx_events(wx, count=8)

    try:
        assert isinstance(bubble._text, MarkdownContent)
        scroller = bubble._text.GetScrollerWindow()
        assert scroller is not None
        client_width = scroller.GetClientSize().width
        virtual_width = scroller.GetVirtualSize().width
        assert virtual_width <= client_width + bubble.FromDIP(4)
        assert not scroller.HasScrollbar(wx.HORIZONTAL)
    finally:
        frame.Destroy()


@pytest.mark.gui_smoke
def test_agent_bubble_shrinks_after_wide_markdown(wx_app):
    wx = pytest.importorskip("wx")
    from wx.lib.scrolledpanel import ScrolledPanel

    frame = wx.Frame(None, size=wx.Size(720, 560))
    scrolled = ScrolledPanel(frame, style=wx.TAB_TRAVERSAL)
    scrolled_sizer = wx.BoxSizer(wx.VERTICAL)
    scrolled.SetSizer(scrolled_sizer)

    wide_cell = "LONGVALUE" * 48
    markdown = "\n".join(
        (
            "| Column A | Column B | Column C |",
            "|----------|----------|----------|",
            f"| {wide_cell} | {wide_cell} | {wide_cell} |",
        )
    )

    conversation, timeline_entry = build_entry_timeline(response=markdown)
    entry_index = timeline_entry.entry_index

    def record_hint(key: str, width: int) -> None:
        try:
            numeric = int(width)
        except (TypeError, ValueError):
            return
        if numeric <= 0:
            return
        entry = conversation.entries[entry_index]
        entry.layout_hints[key] = numeric

    card = render_turn_card(
        scrolled,
        conversation=conversation,
        entry=timeline_entry,
        on_layout_hint=record_hint,
    )
    scrolled_sizer.Add(card, 0, wx.EXPAND | wx.ALL, card.FromDIP(8))

    frame_sizer = wx.BoxSizer(wx.VERTICAL)
    frame_sizer.Add(scrolled, 1, wx.EXPAND)
    frame.SetSizer(frame_sizer)
    frame.Layout()
    scrolled.SetupScrolling(scroll_x=False, scroll_y=True)
    frame.Show()
    flush_wx_events(wx, count=15)

    def collect_bubbles(window) -> list[MessageBubble]:
        bubbles: list[MessageBubble] = []
        for child in window.GetChildren():
            if isinstance(child, MessageBubble):
                bubbles.append(child)
            else:
                bubbles.extend(collect_bubbles(child))
        return bubbles

    try:
        bubbles = collect_bubbles(card)
        agent_bubbles = [
            bubble
            for bubble in bubbles
            if getattr(bubble, "_role_label", "") == "Agent"
        ]
        assert agent_bubbles, "expected agent bubble to be rendered"
        agent_bubble = agent_bubbles[0]
        initial_width = agent_bubble._bubble.GetSize().width
        assert initial_width >= agent_bubble.FromDIP(320)

        short_response = "Short answer"
        entry = conversation.entries[entry_index]
        entry.response = short_response
        entry.display_response = short_response
        updated_entry = build_conversation_timeline(conversation).entries[entry_index]
        updated_segments = get_entry_segments(conversation, updated_entry)
        card.update(
            segments=updated_segments,
            on_regenerate=None,
            regenerate_enabled=True,
        )

        flush_wx_events(wx, count=15)

        refreshed_bubbles = collect_bubbles(card)
        agent_bubbles = [
            bubble
            for bubble in refreshed_bubbles
            if getattr(bubble, "_role_label", "") == "Agent"
        ]
        assert agent_bubbles, "agent bubble should persist after update"
        agent_bubble = agent_bubbles[0]
        updated_width = agent_bubble._bubble.GetSize().width
        assert updated_width < initial_width
        assert updated_width <= max(initial_width * 0.8, agent_bubble.FromDIP(200))
    finally:
        frame.Destroy()


def test_message_bubble_user_textctrl_enables_vertical_scroll(wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.widgets.chat_message import MessageBubble

    frame = wx.Frame(None, size=wx.Size(800, 600))
    long_text = "\n".join(
        f"строка {index}: {('длинное сообщение ' * 4).strip()}"
        for index in range(120)
    )
    bubble = MessageBubble(
        frame,
        role_label="User",
        timestamp="",
        text=long_text,
        align="right",
        allow_selection=True,
        render_markdown=False,
    )

    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(bubble, 1, wx.EXPAND | wx.ALL, bubble.FromDIP(8))
    frame.SetSizer(sizer)
    frame.Layout()
    frame.Show()
    flush_wx_events(wx, count=15)

    try:
        assert isinstance(bubble._text, wx.TextCtrl)
        assert bubble._text.HasFlag(wx.VSCROLL)

        char_height = max(bubble._text.GetCharHeight(), 1)
        visible_height = bubble._text.GetSize().height
        total_lines = bubble._text.GetNumberOfLines()

        assert total_lines > visible_height // char_height
        assert visible_height >= char_height * 3
    finally:
        frame.Destroy()


def test_message_bubble_user_textctrl_hides_vertical_scroll_for_short_text(wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.widgets.chat_message import MessageBubble

    frame = wx.Frame(None, size=wx.Size(800, 600))
    bubble = MessageBubble(
        frame,
        role_label="User",
        timestamp="",
        text="короткий текст",
        align="right",
        allow_selection=True,
        render_markdown=False,
    )

    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(bubble, 1, wx.EXPAND | wx.ALL, bubble.FromDIP(8))
    frame.SetSizer(sizer)
    frame.Layout()
    frame.Show()
    flush_wx_events(wx, count=10)

    try:
        assert isinstance(bubble._text, wx.TextCtrl)
        assert not bubble._text.HasFlag(wx.VSCROLL)
        assert bubble._text.HasFlag(wx.TE_NO_VSCROLL)
        assert not bubble._text.HasScrollbar(wx.VERTICAL)
    finally:
        frame.Destroy()

@pytest.mark.gui_smoke
def test_markdown_content_keeps_height_reasonable(wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.widgets.markdown_view import MarkdownContent

    frame = wx.Frame(None)

    try:
        long_response = "\n".join(
            f"agent response line {index}: " + ("long text " * 6).strip()
            for index in range(80)
        )

        content = MarkdownContent(
            frame,
            markdown=long_response,
            foreground_colour=wx.Colour(10, 10, 10),
            background_colour=wx.Colour(240, 240, 240),
        )

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(content, 1, wx.EXPAND)
        frame.SetSizer(sizer)
        frame.SetClientSize((content.FromDIP(420), content.FromDIP(520)))
        frame.Show()
        frame.Layout()
        frame.SendSizeEvent()

        flush_wx_events(wx, count=10)

        size = content.GetSize()
        if size.height <= 0:
            size = content.GetBestSize()

        max_reasonable = content.FromDIP(800)
        assert size.height <= max_reasonable

        scroller = content.GetScrollerWindow()
        assert scroller is not None

        markdown_view = content.GetMarkdownView()
        flush_wx_events(wx, count=5)

        assert scroller.HasScrollbar(wx.VERTICAL)

        visible_height = scroller.GetClientSize().height
        if visible_height <= 0:
            visible_height = scroller.GetBestSize().height
        assert 0 < visible_height <= max_reasonable

        virtual_height = scroller.GetVirtualSize().height
        assert virtual_height >= visible_height

        internal = markdown_view.GetInternalRepresentation()
        assert internal is not None
        assert internal.GetHeight() >= visible_height
    finally:
        frame.Destroy()


def test_agent_markdown_bubble_keeps_height_reasonable(tmp_path, wx_app):
    wx = pytest.importorskip("wx")

    class QuietAgent:
        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
            on_llm_step=None,
        ):
            return {"ok": True, "error": None, "result": text}

    wx, frame, panel = create_panel(tmp_path, wx_app, QuietAgent())

    try:
        long_response = "\n".join(
            f"agent response line {index}: " + ("long text " * 6).strip()
            for index in range(80)
        )

        panel._append_history(
            "long prompt",
            long_response,
            long_response,
            raw_result=None,
            token_info=None,
        )
        panel._render_transcript()
        flush_wx_events(wx, count=20)

        transcript_panel = panel.transcript_panel
        bubbles = collect_message_bubbles(transcript_panel)
        agent_bubbles = [
            bubble
            for bubble in bubbles
            if "Agent" in bubble_header_text(bubble)
            and "agent response" in bubble_body_text(bubble)
        ]
        assert agent_bubbles, "expected agent response bubble to be rendered"

        agent_bubble = agent_bubbles[0]
        height = agent_bubble.GetSize().height
        if height <= 0:
            height = agent_bubble.GetBestSize().height

        max_reasonable = agent_bubble.FromDIP(800)
        assert height <= max_reasonable
    finally:
        destroy_panel(frame, panel)


def test_message_bubble_destroy_ignores_pending_width_update(monkeypatch, wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.widgets.chat_message import MessageBubble

    scheduled: list[tuple[Any, tuple[Any, ...], dict[str, Any]]] = []

    def fake_call_after(func, *args, **kwargs):  # noqa: ANN001 - wx public API uses *args/**kwargs
        scheduled.append((func, args, kwargs))

    monkeypatch.setattr(wx, "CallAfter", fake_call_after)

    frame = wx.Frame(None)
    bubble = MessageBubble(
        frame,
        role_label="Agent",
        timestamp="",
        text="resize after destroy",
        align="left",
        allow_selection=False,
        render_markdown=False,
    )

    assert scheduled, "MessageBubble should request a deferred layout update"

    bubble.Destroy()

    # Execute the deferred callbacks after the bubble has been torn down. The
    # handlers must return quietly without resurrecting the widget or throwing.
    for func, args, kwargs in list(scheduled):
        func(*args, **kwargs)

    frame.Destroy()


@pytest.mark.gui_smoke
def test_agent_chat_panel_stop_cancels_generation(tmp_path, wx_app):
    from app.ui.agent_chat_panel import ThreadedAgentCommandExecutor

    class BlockingAgent:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.completed = threading.Event()
            self.release = threading.Event()
            self.cancel_seen = threading.Event()

        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            self.started.set()
            try:
                while True:
                    if cancellation is not None and cancellation.wait(0.05):
                        self.cancel_seen.set()
                        cancellation.raise_if_cancelled()
                    if self.release.wait(0.05):
                        break
                return {"ok": True, "error": None, "result": text.upper()}
            finally:
                self.completed.set()

    agent = BlockingAgent()
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="TestAgentChat")
    frame = panel = None
    try:
        wx, frame, panel = create_panel(
            tmp_path,
            wx_app,
            agent,
            executor=ThreadedAgentCommandExecutor(pool),
        )

        panel.input.SetValue("stop me")
        panel._on_send(None)

        assert agent.started.wait(1.0)
        assert panel._primary_action_btn is not None
        assert panel._primary_action_btn.IsEnabled()
        layout = getattr(panel, "_layout", None)
        assert layout is not None
        stop_label = panel._primary_action_btn.GetLabel()
        if layout.primary_action_stop_uses_bitmap:
            assert stop_label == ""
            getter = getattr(panel._primary_action_btn, "GetBitmap", None)
            if callable(getter):
                bitmap = getter()
                assert bitmap is not None
                assert bitmap.IsOk()
        else:
            assert stop_label == _("Stop")

        panel._on_stop(None)

        assert panel.input.GetValue() == "stop me"
        assert panel.status_label.GetLabel() == _("Generation cancelled")
        assert panel._primary_action_btn is not None
        assert panel._primary_action_btn.IsEnabled()
        idle_label = panel._primary_action_btn.GetLabel()
        if layout.primary_action_idle_uses_bitmap:
            assert idle_label == ""
            getter = getattr(panel._primary_action_btn, "GetBitmap", None)
            if callable(getter):
                bitmap = getter()
                assert bitmap is not None
                assert bitmap.IsOk()
        else:
            assert idle_label == PRIMARY_ACTION_IDLE_LABEL

        assert agent.cancel_seen.wait(1.0)
        assert agent.completed.wait(1.0)
        flush_wx_events(wx, count=6)

        history = panel.history
        assert len(history) == 1
        entry = history[0]
        assert entry.prompt == "stop me"
        assert entry.display_response == _("Generation cancelled")
        assert entry.response == ""
        assert entry.response_at is not None

        target_labels = {"Regenerate", i18n.gettext("Regenerate")}

        def find_regenerate_button(window):
            for child in window.GetChildren():
                if isinstance(child, wx.Button) and child.GetLabel() in target_labels:
                    return child
                found = find_regenerate_button(child)
                if found is not None:
                    return found
            return None

        transcript_children = panel.transcript_panel.GetChildren()
        assert transcript_children
        regen_button = None
        for candidate in reversed(transcript_children):
            regen_button = find_regenerate_button(candidate)
            if regen_button is not None:
                break

        assert regen_button is not None
        assert regen_button.IsEnabled()
    finally:
        if frame is not None and panel is not None:
            destroy_panel(frame, panel)
        pool.shutdown(wait=True, cancel_futures=True)


def test_agent_chat_panel_cancellation_preserves_llm_step(tmp_path, wx_app):
    from app.ui.agent_chat_panel import ThreadedAgentCommandExecutor

    class StepAgent:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.cancel_seen = threading.Event()

        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
            on_llm_step=None,
        ):
            self.started.set()
            if on_llm_step is not None:
                on_llm_step(
                    {
                        "step": 1,
                        "response": {
                            "content": "Initial translation plan",
                            "tool_calls": [
                                {
                                    "id": "tool_call_0",
                                    "name": "update_requirement_field",
                                    "arguments": {
                                        "rid": "DEMO14",
                                        "field": "status",
                                        "value": "in_last_review",
                                    },
                                }
                            ],
                            "reasoning": [
                                {"type": "thought", "text": "Перевести требование"}
                            ],
                        },
                        "request_messages": [
                            {"role": "user", "content": text},
                        ],
                    }
                )
            while cancellation is not None and not cancellation.wait(0.05):
                pass
            if cancellation is not None:
                self.cancel_seen.set()
                cancellation.raise_if_cancelled()
            return {"ok": True, "error": None, "result": text.upper()}

    agent = StepAgent()
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="TestAgentChat")
    frame = panel = None
    try:
        wx, frame, panel = create_panel(
            tmp_path,
            wx_app,
            agent,
            executor=ThreadedAgentCommandExecutor(pool),
        )

        panel.input.SetValue("translate requirements")
        panel._on_send(None)
        assert agent.started.wait(1.0)
        wx.Yield()

        panel._on_stop(None)
        assert agent.cancel_seen.wait(1.0)
        wx.Yield()

        history = panel.history
        assert len(history) == 1
        entry = history[0]
        display_text = entry.display_response
        assert "Initial translation plan" in display_text
        assert _("Generation cancelled") in display_text
        assert entry.reasoning
        assert entry.reasoning[0]["text"] == "Перевести требование"
        diagnostic = entry.raw_result["diagnostic"]
        assert "llm_steps" in diagnostic
        steps = diagnostic["llm_steps"]
        assert isinstance(steps, list) and steps
        assert steps[0]["response"]["content"] == "Initial translation plan"
    finally:
        if frame is not None and panel is not None:
            destroy_panel(frame, panel)
        pool.shutdown(wait=True, cancel_futures=True)


@pytest.mark.gui_smoke
def test_agent_chat_panel_cancellation_persists_tool_history(tmp_path, wx_app):
    from app.ui.agent_chat_panel import ThreadedAgentCommandExecutor

    class StreamingAgent:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.streamed = threading.Event()
            self.cancel_seen = threading.Event()

        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
            on_llm_step=None,
        ):
            self.started.set()
            payloads = [
                {
                    "call_id": "call-stop-0",
                    "tool_name": "update_requirement_field",
                    "status": "running",
                    "arguments": {
                        "rid": "SYS-0002",
                        "field": "title",
                        "value": "Cancelled",
                    },
                    "events": [
                        {
                            "kind": "started",
                            "occurred_at": "2025-09-30T20:50:10+00:00",
                        }
                    ],
                },
                {
                    "call_id": "call-stop-1",
                    "tool_name": "list_requirements",
                    "status": "running",
                    "arguments": {
                        "label": "security",
                    },
                    "events": [
                        {
                            "kind": "started",
                            "occurred_at": "2025-09-30T20:50:12+00:00",
                            "message": "Filtering requirements",
                        }
                    ],
                },
            ]
            if callable(on_tool_result):
                for payload in payloads:
                    on_tool_result(payload)
            self.streamed.set()
            while cancellation is not None and not cancellation.wait(0.05):
                pass
            if cancellation is not None:
                self.cancel_seen.set()
                cancellation.raise_if_cancelled()
            return {"ok": True, "error": None, "result": text.upper()}

    agent = StreamingAgent()
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="TestAgentChat")
    wx, frame, panel = create_panel(
        tmp_path,
        wx_app,
        agent,
        executor=ThreadedAgentCommandExecutor(pool),
    )

    try:
        panel.input.SetValue("cancel tool stream")
        panel._on_send(None)

        assert agent.started.wait(1.0)
        assert agent.streamed.wait(1.0)
        flush_wx_events(wx, count=6)

        panel._on_stop(None)

        assert agent.cancel_seen.wait(1.0)
        flush_wx_events(wx, count=6)

        history = panel.history
        assert len(history) == 1
        entry = history[0]
        tool_results = entry.raw_result.get("tool_results")
        assert tool_results, "expected tool results in raw payload"
        assert len(tool_results) == 2
        tool_ids = {
            payload.get("call_id") or payload.get("tool_call_id")
            for payload in tool_results
        }
        assert "call-stop-0" in tool_ids
        expected_stream_ids = {"call-stop-1"}
        stream_ids = {identifier for identifier in tool_ids if identifier != "call-stop-0"}
        assert stream_ids == expected_stream_ids
        persisted_results = entry.tool_results
        assert persisted_results
        persisted_ids = {
            payload.get("call_id") or payload.get("tool_call_id")
            for payload in persisted_results
        }
        assert persisted_ids == {"call-stop-0", "call-stop-1"}
        assert "call-stop-0" in persisted_ids
        persisted_stream_ids = {
            identifier for identifier in persisted_ids if identifier != "call-stop-0"
        }
        assert persisted_stream_ids == expected_stream_ids
        assert entry.tool_messages
        message_ids = {
            message.get("tool_call_id") or message.get("call_id")
            for message in entry.tool_messages
        }
        assert message_ids == {"call-stop-0", *expected_stream_ids}

        metadata, conversations = read_history_database(history_db_path(tmp_path))
        assert metadata.get("active_id") == conversations[0]["id"]
        stored_entries = conversations[0]["entries"]
        assert stored_entries and stored_entries[0]["raw_result"]["tool_results"]
    finally:
        destroy_panel(frame, panel)
        pool.shutdown(wait=True, cancel_futures=True)

    class PassiveAgent:
        def run_command(self, *args, **kwargs):  # pragma: no cover - not used
            return {"ok": True, "result": "noop"}

    wx2, frame2, panel2 = create_panel(
        tmp_path,
        wx_app,
        PassiveAgent(),
        use_default_executor=True,
    )

    try:
        conversations = panel2.conversations
        saved = next((conv for conv in conversations if conv.entries), None)
        assert saved is not None, "expected saved conversation in history"
        panel2._session.history.ensure_conversation_entries(saved)
        assert len(saved.entries) == 1
        reloaded_entry = saved.entries[0]
        reloaded_results = reloaded_entry.raw_result.get("tool_results")
        assert reloaded_results
        reloaded_ids = {
            payload.get("call_id") or payload.get("tool_call_id")
            for payload in reloaded_results
        }
        assert reloaded_ids == {"call-stop-0", *expected_stream_ids}
        assert reloaded_entry.tool_results
        persisted_reloaded_ids = {
            payload.get("call_id") or payload.get("tool_call_id")
            for payload in reloaded_entry.tool_results
        }
        assert persisted_reloaded_ids == {"call-stop-0", *expected_stream_ids}
        assert reloaded_entry.tool_messages
        reloaded_message_ids = {
            message.get("tool_call_id") or message.get("call_id")
            for message in reloaded_entry.tool_messages
        }
        assert reloaded_message_ids == {"call-stop-0", *expected_stream_ids}
    finally:
        destroy_panel(frame2, panel2)


def test_agent_chat_panel_streams_tool_results(tmp_path, wx_app):

    class StreamingAgent:
        def __init__(self) -> None:
            self.streamed = threading.Event()
            self.release = threading.Event()

        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
        ):
            running_payload = {
                "tool_name": "update_requirement_field",
                "tool_call_id": "call-stream-0",
                "call_id": "call-stream-0",
                "tool_arguments": {
                    "rid": "SYS-0001",
                    "field": "title",
                    "value": "Updated",
                },
                "agent_status": "running",
            }
            completed_payload = {
                "ok": True,
                "tool_name": "update_requirement_field",
                "tool_call_id": "call-stream-0",
                "call_id": "call-stream-0",
                "tool_arguments": {
                    "rid": "SYS-0001",
                    "field": "title",
                    "value": "Updated",
                },
                "result": {"rid": "SYS-0001", "title": "Updated"},
                "agent_status": "completed",
            }
            if callable(on_tool_result):
                on_tool_result(running_payload)
                self.streamed.set()
                self.release.wait(0.5)
                on_tool_result(completed_payload)
            return {"ok": True, "error": None, "result": "done"}

    agent = StreamingAgent()
    wx, frame, panel = create_panel(
        tmp_path,
        wx_app,
        agent,
        use_default_executor=True,
    )

    try:
        panel.input.SetValue("stream")
        panel._on_send(None)

        assert agent.streamed.wait(1.0)
        flush_wx_events(wx, count=6)

        transcript = panel.get_transcript_text()
        assert "Agent: tool call" in transcript
        assert "update_requirement_field" in transcript
        assert _("in progress…") in transcript
        assert panel.is_running

        agent.release.set()
        deadline = time.time() + 2.0
        while panel.is_running and time.time() < deadline:
            wx_app.Yield()
            time.sleep(0.05)
        flush_wx_events(wx, count=4)

        assert not panel.is_running
    finally:
        agent.release.set()
        destroy_panel(frame, panel)


def test_agent_chat_panel_preserves_llm_output_and_tool_timeline(
    tmp_path, wx_app, monkeypatch
):
    wx = pytest.importorskip("wx")

    class TimelineAgent:
        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
            on_llm_step=None,
        ):
            if callable(on_llm_step):
                on_llm_step(
                    {
                        "step": 1,
                        "response": {
                            "content": (
                                "Now I will translate the selected requirements into Russian."
                            ),
                            "reasoning": [
                                {"type": "thinking", "text": "Fetch requirement data"}
                            ],
                            "tool_calls": [
                                {
                                    "id": "call-123",
                                    "name": "update_requirement_field",
                                    "arguments": {
                                        "rid": "DEMO14",
                                        "field": "status",
                                        "value": "in_last_review",
                                    },
                                }
                            ],
                        },
                        "request_messages": [
                            {"role": "user", "content": text},
                        ],
                    }
                )
            if callable(on_tool_result):
                on_tool_result(
                    {
                        "tool_name": "update_requirement_field",
                        "tool_call_id": "call-123",
                        "call_id": "call-123",
                        "tool_arguments": {
                            "rid": "DEMO14",
                            "field": "status",
                            "value": "in_last_review",
                        },
                        "agent_status": "running",
                    }
                )
                on_tool_result(
                    {
                        "ok": False,
                        "tool_name": "update_requirement_field",
                        "tool_call_id": "call-123",
                        "call_id": "call-123",
                        "tool_arguments": {
                            "rid": "DEMO14",
                            "field": "status",
                            "value": "in_last_review",
                        },
                        "error": {
                            "code": "VALIDATION_ERROR",
                            "message": VALIDATION_ERROR_MESSAGE,
                        },
                        "agent_status": "failed",
                    }
                )
            return {
                "ok": False,
                "error": {
                    "type": "ToolValidationError",
                    "message": VALIDATION_ERROR_MESSAGE,
                },
                "tool_results": [
                    {
                        "tool_name": "update_requirement_field",
                        "tool_call_id": "call-123",
                        "call_id": "call-123",
                        "tool_arguments": {
                            "rid": "DEMO14",
                            "field": "status",
                            "value": "in_last_review",
                        },
                        "ok": False,
                        "error": {
                            "code": "VALIDATION_ERROR",
                            "message": VALIDATION_ERROR_MESSAGE,
                        },
                    }
                ],
                "diagnostic": {
                    "llm_steps": [
                        {
                            "step": 1,
                            "response": {
                                "content": (
                                    "Now I will translate the selected requirements into Russian."
                                ),
                                "reasoning": [
                                    {
                                        "type": "thinking",
                                        "text": "Fetch requirement data",
                                    }
                                ],
                            },
                        }
                    ]
                },
            }

    times = iter(
        [
            "2025-01-01T12:00:00Z",
            "2025-01-01T12:00:02Z",
            "2025-01-01T12:00:04Z",
            "2025-01-01T12:00:06Z",
            "2025-01-01T12:00:08Z",
        ]
    )

    def fake_utc_now_iso() -> str:
        try:
            return next(times)
        except StopIteration:
            return "2025-01-01T12:59:59Z"

    monkeypatch.setattr("app.ui.agent_chat_panel.panel.utc_now_iso", fake_utc_now_iso)
    monkeypatch.setattr("app.ui.agent_chat_panel.controller.utc_now_iso", fake_utc_now_iso)

    agent = TimelineAgent()
    wx, frame, panel = create_panel(tmp_path, wx_app, agent)

    try:
        panel.input.SetValue("translate selected requirements")
        panel._on_send(None)
        flush_wx_events(wx, count=6)

        history = panel.history
        assert len(history) == 1
        entry = history[0]
        assert "Now I will translate the selected requirements into Russian." in entry.display_response
        assert VALIDATION_ERROR_MESSAGE in entry.display_response
        assert entry.reasoning
        assert entry.reasoning[0]["text"] == "Fetch requirement data"
        assert entry.tool_results and entry.tool_results[0]["started_at"] == "2025-01-01T12:00:02Z"
        assert entry.tool_results[0]["completed_at"] == "2025-01-01T12:00:04Z"

        raw_tool = entry.raw_result["tool_results"][0]
        assert raw_tool["started_at"] == "2025-01-01T12:00:02Z"
        assert raw_tool["completed_at"] == "2025-01-01T12:00:04Z"

        diagnostic = entry.diagnostic
        tool_exchange = diagnostic["tool_exchanges"][0]
        assert tool_exchange["started_at"] == "2025-01-01T12:00:02Z"
        assert tool_exchange["completed_at"] == "2025-01-01T12:00:04Z"

        conversation = panel._get_active_conversation()
        assert conversation is not None
        cache = panel._transcript_view._conversation_cache[conversation.conversation_id]
        entry_index = conversation.entries.index(entry)
        entry_key = f"{conversation.conversation_id}:{entry_index}"
        assert entry_key in cache
        timeline = build_conversation_timeline(conversation)
        tool_events = timeline.entries[entry_index].agent_turn.tool_calls
        assert any(event.llm_request for event in tool_events), "expected llm request payload"
        bubbles = collect_message_bubbles(panel)
        assert len(bubbles) == 4

        agent_bubbles = [
            bubble
            for bubble in bubbles
            if "Agent" in bubble_header_text(bubble)
        ]
        assert len(agent_bubbles) == 2
        step_bubble, agent_bubble = agent_bubbles
        step_index = (
            timeline.entries[entry_index].agent_turn.streamed_responses[0].step_index
        )
        expected_step = i18n.gettext("Step {index}").format(index=step_index)
        assert expected_step in bubble_header_text(step_bubble)
        assert "Now I will translate the selected requirements" in bubble_body_text(
            step_bubble
        )
        assert bubble_body_text(agent_bubble)
        user_bubble = next(
            bubble for bubble in bubbles if "You" in bubble_header_text(bubble)
        )
        assert bubble_body_text(user_bubble)



        context_pane = find_collapsible_by_name(
            panel, f"context:{entry_key}"
        )
        reasoning_pane = find_collapsible_by_name(
            panel, f"reasoning:{entry_key}"
        )
        if reasoning_pane is None:
            prefix = f"reasoning:{entry_key}:"
            reasoning_pane = next(
                (
                    pane
                    for pane in collect_collapsible_panes(panel)
                    if pane.GetName().startswith(prefix)
                ),
                None,
            )
        agent_raw_pane = find_collapsible_by_name(panel, f"raw:{entry_key}")
        llm_request_pane = find_collapsible_by_name(panel, f"llm:{entry_key}")
        tool_bubble = next(
            (
                bubble
                for bubble in bubbles
                if "Tool" in bubble_header_text(bubble)
            ),
            None,
        )
        assert tool_bubble is not None, "expected tool bubble"
        agent_panel = tool_bubble.GetParent()
        while agent_panel is not None and not isinstance(agent_panel, MessageSegmentPanel):
            agent_panel = agent_panel.GetParent()
        assert isinstance(agent_panel, MessageSegmentPanel)
        tool_panes = collect_collapsible_panes(agent_panel)
        panes_by_name = {pane.GetName(): pane for pane in tool_panes}
        tool_entry_key = (
            f"tool:{entry_key}:{tool_events[0].summary.index}"
            if tool_events[0].summary.index
            else f"tool:{entry_key}:1"
        )
        tool_raw_pane = panes_by_name.get(f"tool:raw:{tool_entry_key}")

        assert context_pane is not None
        assert reasoning_pane is not None
        assert agent_raw_pane is not None
        assert llm_request_pane is not None
        assert tool_raw_pane is not None
        assert panes_by_name.get(f"tool:summary:{tool_entry_key}") is None

        context_label = collapsible_label(context_pane)
        assert context_label.lower() in {"", i18n._("Context").lower()}
        assert "reason" in collapsible_label(reasoning_pane).lower()
        assert "raw" in collapsible_label(agent_raw_pane).lower()
        assert "raw" in collapsible_label(tool_raw_pane).lower()

        tool_raw_pane.Collapse(False)
        flush_wx_events(wx)

        def pane_text(pane: "wx.CollapsiblePane") -> str:
            lines: list[str] = []
            for child in pane.GetPane().GetChildren():
                if isinstance(child, wx.TextCtrl):
                    lines.append(child.GetValue())
            return "\n".join(lines)

        tool_summary_bubbles = [
            bubble
            for bubble in collect_message_bubbles(agent_panel)
            if "Tool" in bubble_header_text(bubble)
        ]
        summary_text = "\n".join(bubble_body_text(b) for b in tool_summary_bubbles)
        raw_text = pane_text(tool_raw_pane)
        assert "update_requirement_field" in summary_text
        assert "[VALIDATION_ERROR]" in summary_text
        assert "Started at" not in summary_text
        assert "llm_request" in raw_text
        assert "llm_response" in raw_text
        assert "rid" in raw_text
        assert "update_requirement_field" in raw_text
        assert "Applying updates" in raw_text

        log_text = panel._compose_transcript_log_text()
        started_line = next(
            (line for line in log_text.splitlines() if line.strip().startswith("Started at ")), 
            "",
        )
        completed_line = next(
            (line for line in log_text.splitlines() if line.strip().startswith("Completed at ")),
            "",
        )
        assert started_line
        assert completed_line
        assert "T" not in started_line.strip()
        assert "T" not in completed_line.strip()
        assert "12:00:02" in started_line
        assert "12:00:04" in completed_line
        assert "Now I will translate the selected requirements into Russian." in log_text
    finally:
        destroy_panel(frame, panel)


def test_agent_chat_panel_preserves_multistep_timeline(tmp_path, wx_app, monkeypatch):
    wx = pytest.importorskip("wx")

    from app.agent.local_agent import LocalAgent
    from app.llm.types import LLMReasoningSegment, LLMResponse, LLMToolCall

    timeline = iter([f"2025-01-01T12:00:{index:02d}Z" for index in range(60)])

    def fake_utc_now_iso() -> str:
        return next(timeline, "2025-01-01T13:00:00Z")

    monkeypatch.setattr("app.ui.agent_chat_panel.panel.utc_now_iso", fake_utc_now_iso)
    monkeypatch.setattr("app.ui.agent_chat_panel.controller.utc_now_iso", fake_utc_now_iso)
    monkeypatch.setattr("app.agent.local_agent.utc_now_iso", fake_utc_now_iso)
    monkeypatch.setattr("app.agent.run_contract.utc_now_iso", fake_utc_now_iso)

    scripted_steps = [
        {
            "content": "First streamed response",
            "reasoning": "Collect user inputs",
            "tool": {
                "id": "call-1",
                "name": "alpha_tool",
                "arguments": {"rid": "R-1", "field": "status", "value": "draft"},
            },
        },
        {
            "content": "Second step with notes",
            "reasoning": "Validate current data",
            "tool": {
                "id": "call-2",
                "name": "beta_tool",
                "arguments": {"rid": "R-2", "field": "owner", "value": "QA"},
            },
        },
        {
            "content": "Third iteration before synthesis",
            "reasoning": "Refine summary",
            "tool": {
                "id": "call-3",
                "name": "gamma_tool",
                "arguments": {"rid": "R-3", "field": "priority", "value": "high"},
            },
        },
        {
            "content": "Fourth response mixing tool output",
            "reasoning": "Consolidate feedback",
            "tool": {
                "id": "call-4",
                "name": "delta_tool",
                "arguments": {"rid": "R-4", "field": "title", "value": "Rephrase"},
            },
        },
        {
            "content": "Final combined answer",
            "reasoning": "Deliver final summary",
            "tool": None,
        },
    ]

    class ScriptedLLM:
        def __init__(self, steps):
            self._steps = list(steps)

        async def check_llm_async(self):
            return {"ok": True}

        async def respond_async(self, conversation, *, cancellation=None):
            if not self._steps:
                raise AssertionError("LLM received more respond_async calls than scripted")

            payload = self._steps.pop(0)
            tool_calls: tuple[LLMToolCall, ...]
            tool_call_payload = payload.get("tool")
            if tool_call_payload:
                tool_calls = (
                    LLMToolCall(
                        id=tool_call_payload["id"],
                        name=tool_call_payload["name"],
                        arguments=tool_call_payload["arguments"],
                    ),
                )
            else:
                tool_calls = ()

            return LLMResponse(
                content=payload["content"],
                tool_calls=tool_calls,
                reasoning=(
                    LLMReasoningSegment(
                        type="thinking",
                        text=payload["reasoning"],
                    ),
                ),
                request_messages=tuple(conversation or ()),
            )

    class ScriptedMCP:
        def __init__(self, steps):
            self.calls: list[tuple[str, Mapping[str, Any]]] = []
            self._steps = [step for step in steps if step.get("tool")]

        async def check_tools_async(self):
            return {"ok": True, "tools": [step["tool"]["name"] for step in self._steps]}

        async def ensure_ready_async(self):
            return None

        async def call_tool_async(self, name: str, arguments: Mapping[str, Any]):
            self.calls.append((name, arguments))
            return {
                "ok": True,
                "result": {
                    "rid": arguments.get("rid"),
                    "field": arguments.get("field"),
                    "updated": True,
                },
            }

        async def get_tool_schemas_async(self):
            return {
                step["tool"]["name"]: {
                    "name": step["tool"]["name"],
                    "parameters": step["tool"]["arguments"],
                }
                for step in self._steps
            }

    agent = LocalAgent(
        llm=ScriptedLLM(scripted_steps),
        mcp=ScriptedMCP(scripted_steps),
        max_thought_steps=None,
    )
    wx, frame, panel = create_panel(tmp_path, wx_app, agent)

    try:
        panel.input.SetValue("orchestrate multi-step update")
        panel._on_send(None)
        flush_wx_events(wx, count=20)

        history = panel.history
        assert len(history) == 1
        entry = history[0]

        conversation = panel._get_active_conversation()
        assert conversation is not None
        entry_index = conversation.entries.index(entry)
        timeline = build_conversation_timeline(conversation)
        turn = timeline.entries[entry_index].agent_turn
        assert turn is not None
        event_labels = [
            (
                event.kind,
                event.response.display_text if event.response else event.tool_call.summary.tool_name,
            )
            for event in turn.events
        ]
        expected_events = [
            ("response", "First streamed response"),
            ("tool", "alpha_tool"),
            ("response", "Second step with notes"),
            ("tool", "beta_tool"),
            ("response", "Third iteration before synthesis"),
            ("tool", "gamma_tool"),
            ("response", "Fourth response mixing tool output"),
            ("tool", "delta_tool"),
            ("response", "Final combined answer"),
        ]
        assert event_labels[: len(expected_events)] == expected_events

        bubbles = [
            (bubble_header_text(bubble), bubble_body_text(bubble))
            for bubble in collect_message_bubbles(panel)
            if "Agent" in bubble_header_text(bubble)
            or "Tool" in bubble_header_text(bubble)
        ]
        bubble_texts = [text for _header, text in bubbles]
        expected_sequence = [
            "First streamed response",
            "Tool call alpha_tool",
            "Second step with notes",
            "Tool call beta_tool",
            "Third iteration before synthesis",
            "Tool call gamma_tool",
            "Fourth response mixing tool output",
            "Tool call delta_tool",
            "Final combined answer",
        ]
        assert len(bubble_texts) >= len(expected_sequence)
        for expected, actual in zip(expected_sequence, bubble_texts):
            assert expected in actual

        reasoning_texts = [
            segment.get("text") for segment in (turn.reasoning or ()) if isinstance(segment, Mapping)
        ]
        assert reasoning_texts == [step["reasoning"] for step in scripted_steps]

        entry_key = timeline.entries[entry_index].entry_id
        reasoning_pane = find_collapsible_by_name(panel, f"reasoning:{entry_key}")
        if reasoning_pane is None:
            prefix = f"reasoning:{entry_key}:"
            reasoning_pane = next(
                (
                    pane
                    for pane in collect_collapsible_panes(panel)
                    if pane.GetName().startswith(prefix)
                ),
                None,
            )
        assert reasoning_pane is not None
        reasoning_pane.Expand()
        flush_wx_events(wx)
        text_controls = [
            child
            for child in reasoning_pane.GetPane().GetChildren()
            if isinstance(child, wx.TextCtrl)
        ]
        assert text_controls, "reasoning pane should render text control"
        combined_text = "\n".join(child.GetValue() for child in text_controls)
        for expected in reasoning_texts:
            assert expected in combined_text
    finally:
        destroy_panel(frame, panel)


@pytest.mark.gui_smoke
def test_agent_chat_panel_activity_indicator_layout(tmp_path, wx_app):
    class IdleAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):  # pragma: no cover - defensive
            return {"ok": True, "error": None, "result": text}

    wx, frame, panel = create_panel(tmp_path, wx_app, IdleAgent())

    try:
        panel._set_wait_state(True)
        flush_wx_events(wx)

        activity_pos = panel.activity.GetPosition()
        status_pos = panel.status_label.GetPosition()
        indicator_height = max(1, panel.activity.GetSize().GetHeight())

        assert abs(activity_pos.y - status_pos.y) <= indicator_height
    finally:
        panel._set_wait_state(False)
        destroy_panel(frame, panel)


def test_agent_chat_panel_ready_status_reflects_tokens(tmp_path, wx_app):
    class IdleAgent:
        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
        ):  # pragma: no cover - defensive
            return {"ok": True, "error": None, "result": text}

    wx, frame, panel = create_panel(
        tmp_path,
        wx_app,
        IdleAgent(),
        context_window=4000,
    )


    try:
        prompt_tokens = TokenCountResult.exact(1000)
        panel._set_wait_state(True, prompt_tokens)
        flush_wx_events(wx)

        final_tokens = TokenCountResult.exact(2000)
        panel._set_wait_state(False, final_tokens)
        flush_wx_events(wx)

        assert panel.status_label.GetLabel() == _("Ready")
    finally:
        panel._set_wait_state(False)
        destroy_panel(frame, panel)


def test_agent_chat_panel_shuts_down_executor_pool_on_destroy(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):  # pragma: no cover - defensive
            raise AssertionError("Should not be called")

    class DummyPool:
        def __init__(self) -> None:
            self.shutdown_called = False

        def submit(self, func):
            future = Future()
            future.set_result(None)
            return future

        def shutdown(self, wait=True, cancel_futures=False):
            self.shutdown_called = True

    from app.ui.agent_chat_panel import ThreadedAgentCommandExecutor

    pool = DummyPool()
    wx, frame, panel = create_panel(
        tmp_path,
        wx_app,
        DummyAgent(),
        executor=ThreadedAgentCommandExecutor(pool),
    )

    destroy_panel(frame, panel)

    assert pool.shutdown_called


def test_agent_chat_panel_persists_between_instances(tmp_path, wx_app):
    class EchoAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {"ok": True, "error": None, "result": text}

    wx, frame1, panel1 = create_panel(tmp_path, wx_app, EchoAgent())
    panel1.input.SetValue("hello")
    panel1._on_send(None)
    flush_wx_events(wx)
    destroy_panel(frame1, panel1)

    wx, frame2, panel2 = create_panel(tmp_path, wx_app, EchoAgent())
    assert panel2.history == []
    assert panel2.history_list.GetItemCount() == 2
    assert panel2._active_index() == 1

    panel2._on_history_row_activated(0)
    flush_wx_events(wx)

    assert len(panel2.history) == 1
    assert panel2.history[0].prompt == "hello"
    destroy_panel(frame2, panel2)


def test_agent_chat_panel_handles_invalid_history(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.agent_chat_panel import AgentChatPanel

    bad_file = history_db_path(tmp_path)
    bad_file.write_text("{not sqlite}")

    class DummyAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {"ok": True, "error": None, "result": {}}

    frame = wx.Frame(None)
    panel = AgentChatPanel(
        frame,
        agent_supplier=lambda **_overrides: DummyAgent(),
        history_path=bad_file,
    )
    assert panel.history == []
    assert panel.history_list.GetItemCount() == 1
    assert (
        panel.get_transcript_text()
        == _("This chat does not have any messages yet. Send one to get started.")
    )
    destroy_panel(frame, panel)


def test_primary_action_button_visible_without_bitmaps(
    tmp_path, wx_app, monkeypatch
):
    wx = pytest.importorskip("wx")
    from app.ui.agent_chat_panel.layout import AgentChatLayoutBuilder

    class DummyAgent:
        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
            on_llm_step=None,
        ):
            return {"ok": True, "error": None, "result": {}}

    monkeypatch.setattr(
        AgentChatLayoutBuilder,
        "_render_primary_action_bitmaps",
        lambda self, parent, icon_size, svg_builder: None,
    )

    wx, frame, panel = create_panel(tmp_path, wx_app, DummyAgent())
    try:
        layout = panel._layout
        assert layout is not None
        button = layout.primary_action_button
        frame.SetClientSize((800, 600))
        frame.Show()
        frame.SendSizeEvent()
        flush_wx_events(wx)

        assert button.IsShown()
        min_size = button.GetMinSize()
        assert min_size.GetWidth() > 0
        assert min_size.GetHeight() > 0

        button.InvalidateBestSize()
        best_size = button.GetBestSize()
        assert best_size.GetWidth() > 0
        assert best_size.GetHeight() > 0
    finally:
        destroy_panel(frame, panel)


def test_agent_chat_panel_rejects_unknown_history_version(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.agent_chat_panel import AgentChatPanel

    legacy_file = history_db_path(tmp_path)
    conn = sqlite3.connect(str(legacy_file))
    try:
        conn.execute(
            "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO metadata (key, value) VALUES ('schema_version', '999')"
        )
        conn.commit()
    finally:
        conn.close()

    class DummyAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {"ok": True, "error": None, "result": {}}

    frame = wx.Frame(None)
    panel = AgentChatPanel(
        frame,
        agent_supplier=lambda **_overrides: DummyAgent(),
        history_path=legacy_file,
    )

    assert panel.history == []
    assert panel.history_list.GetItemCount() == 1
    assert (
        panel.get_transcript_text()
        == _("This chat does not have any messages yet. Send one to get started.")
    )

    destroy_panel(frame, panel)


def test_handle_streamed_tool_results_coalesces_renders(
    tmp_path, wx_app, monkeypatch
):
    from app.llm.tokenizer import TokenCountResult
    from app.ui.agent_chat_panel.execution import _AgentRunHandle
    from app.util.cancellation import CancellationEvent

    class DummyAgent:
        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
            on_llm_step=None,
        ):
            return {"ok": True, "error": None, "result": {}}

    wx, frame, panel = create_panel(tmp_path, wx_app, DummyAgent())
    conversation = panel._ensure_active_conversation()
    entry = panel._add_pending_entry(
        conversation,
        "hello",
        prompt_at="2025-01-01T00:00:00+00:00",
        context_messages=None,
    )
    handle = _AgentRunHandle(
        run_id=1,
        prompt="hello",
        prompt_tokens=TokenCountResult.exact(1),
        cancel_event=CancellationEvent(),
        prompt_at="2025-01-01T00:00:00+00:00",
    )
    handle.conversation_id = conversation.conversation_id
    handle.pending_entry = entry
    panel._active_handle = lambda: handle

    calls: list[tuple[Any, Any, list[str] | None, bool]] = []

    def record_schedule_render(
        *,
        conversation,
        timeline,
        updated_entries,
        force,
    ) -> None:
        calls.append((conversation, timeline, updated_entries, force))

    monkeypatch.setattr(panel._transcript_view, "schedule_render", record_schedule_render)

    payloads = [
        [{"call_id": "tool-1", "status": "running"}],
        [{"call_id": "tool-1", "status": "running", "agent_status": "running"}],
        [{"call_id": "tool-1", "status": "completed", "agent_status": "completed"}],
    ]

    for payload in payloads:
        panel._handle_streamed_tool_results(handle, payload)

    flush_wx_events(wx)

    assert len(calls) == 1
    scheduled_conversation, scheduled_timeline, updated_entries, force = calls[0]
    assert scheduled_conversation.conversation_id == conversation.conversation_id
    assert hasattr(scheduled_timeline, "entries")
    assert not force
    expected_entry = panel._entry_identifier(conversation, entry)
    assert updated_entries == [expected_entry]

    destroy_panel(frame, panel)


def test_agent_chat_panel_rejects_entries_without_token_info(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.agent_chat_panel import AgentChatPanel

    legacy_file = history_db_path(tmp_path)
    store = HistoryStore(legacy_file)
    conversation = ChatConversation.new()
    conversation.title = "Legacy conversation"
    entry = ChatEntry(prompt="old request", response="old response", tokens=2)
    conversation.replace_entries([entry])
    store.save([conversation], conversation.conversation_id)

    conn = sqlite3.connect(str(legacy_file))
    conn.row_factory = sqlite3.Row
    try:
        payload_row = conn.execute(
            "SELECT payload FROM entries WHERE conversation_id = ?",
            (conversation.conversation_id,),
        ).fetchone()
        assert payload_row is not None
        payload = json.loads(payload_row["payload"])
        payload.pop("token_info", None)
        conn.execute(
            "UPDATE entries SET payload = ? WHERE conversation_id = ?",
            (json.dumps(payload), conversation.conversation_id),
        )
        conn.commit()
    finally:
        conn.close()

    class DummyAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {"ok": True, "error": None, "result": {}}

    frame = wx.Frame(None)
    panel = AgentChatPanel(
        frame,
        agent_supplier=lambda **_overrides: DummyAgent(),
        history_path=legacy_file,
    )

    assert panel.history == []
    assert panel.history_list.GetItemCount() == 1
    assert (
        panel.get_transcript_text()
        == _("This chat does not have any messages yet. Send one to get started.")
    )

    destroy_panel(frame, panel)


def test_agent_chat_panel_provides_history_context(tmp_path, wx_app):
    class RecordingAgent:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            recorded_history = list(history or [])
            self.calls.append({"text": text, "history": recorded_history})
            return {"ok": True, "error": None, "result": f"answer {len(self.calls)}"}

    agent = RecordingAgent()
    wx, frame, panel = create_panel(tmp_path, wx_app, agent)

    panel.input.SetValue("first question")
    panel._on_send(None)
    flush_wx_events(wx)
    assert agent.calls[0]["history"] == []
    first_response = panel.history[0].response

    panel.input.SetValue("second question")
    panel._on_send(None)
    flush_wx_events(wx)

    expected_history = [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": first_response},
    ]
    assert agent.calls[1]["history"] == expected_history

    destroy_panel(frame, panel)


def test_agent_chat_panel_clear_history_resets_context(tmp_path, wx_app):
    class RecordingAgent:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            recorded_history = list(history or [])
            self.calls.append({"text": text, "history": recorded_history})
            return {"ok": True, "error": None, "result": f"answer {len(self.calls)}"}

    agent = RecordingAgent()
    wx, frame, panel = create_panel(tmp_path, wx_app, agent)

    panel.input.SetValue("keep this")
    panel._on_send(None)
    flush_wx_events(wx)
    assert agent.calls[0]["history"] == []

    panel.history_list.SelectRow(0)
    panel._on_clear_history(None)
    assert panel.history == []
    assert panel.history_list.GetItemCount() == 0
    assert "Start chatting" in panel.get_transcript_text()

    panel.input.SetValue("after clear")
    panel._on_send(None)
    flush_wx_events(wx)
    assert agent.calls[-1]["history"] == []

    destroy_panel(frame, panel)


def test_agent_chat_panel_delete_multiple_chats(tmp_path, wx_app):
    class RecordingAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {"ok": True, "error": None, "result": f"answer {text}"}

    wx, frame, panel = create_panel(tmp_path, wx_app, RecordingAgent())

    panel.input.SetValue("first request")
    panel._on_send(None)
    flush_wx_events(wx)

    panel._on_new_chat(None)
    panel.input.SetValue("second request")
    panel._on_send(None)
    flush_wx_events(wx)

    panel._on_new_chat(None)
    panel.input.SetValue("third request")
    panel._on_send(None)
    flush_wx_events(wx)

    assert len(panel.conversations) == 3
    to_remove = list(panel.conversations[:2])
    last_id = panel.conversations[-1].conversation_id
    panel.input.SetValue("draft text")

    panel._remove_conversations(to_remove)

    assert len(panel.conversations) == 1
    assert panel.history_list.GetItemCount() == 1
    assert panel.conversations[0].conversation_id == last_id
    assert panel.active_conversation_id == last_id
    assert panel.input.GetValue() == "draft text"

    destroy_panel(frame, panel)


def test_agent_chat_panel_history_context_menu_handles_multiselect(
    monkeypatch, tmp_path, wx_app
):
    class QuietAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {"ok": True, "error": None, "result": text}

    wx, frame, panel = create_panel(tmp_path, wx_app, QuietAgent())

    try:
        for idx in range(3):
            panel._append_history(
                f"prompt {idx}",
                f"response {idx}",
                f"response {idx}",
                raw_result=None,
                token_info=TokenCountResult.exact(1),
            )
            flush_wx_events(wx)
            if idx < 2:
                panel._create_conversation(persist=True)
                flush_wx_events(wx)

        assert panel.history_list.GetItemCount() == 3

        panel.history_list.UnselectAll()
        first_item = panel.history_list.RowToItem(0)
        second_item = panel.history_list.RowToItem(1)
        panel.history_list.Select(first_item)
        panel._activate_conversation_by_index(0, refresh_history=False)
        flush_wx_events(wx)
        panel.history_list.Select(second_item)
        panel._activate_conversation_by_index(1, refresh_history=False)
        flush_wx_events(wx)

        assert panel._history_view.selected_rows() == [0, 1]
        assert panel._active_index() == 1

        captured_labels: list[list[str]] = []

        def fake_popup(menu, pos=wx.DefaultPosition):
            labels = [item.GetItemLabelText() for item in menu.GetMenuItems()]
            captured_labels.append(labels)
            return True

        monkeypatch.setattr(panel.history_list, "PopupMenu", fake_popup)

        panel._history_view._show_context_menu(1)
        flush_wx_events(wx)
        assert captured_labels and captured_labels[0][0] == "Delete selected chats"
        assert panel._history_view.selected_rows() == [0, 1]

        panel._history_view._show_context_menu(2)
        flush_wx_events(wx)
        assert len(captured_labels) >= 2 and captured_labels[1][0] == "Delete chat"
        assert panel._history_view.selected_rows() == [2]
    finally:
        destroy_panel(frame, panel)


def test_agent_chat_panel_new_chat_creates_separate_conversation(tmp_path, wx_app):
    class RecordingAgent:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            recorded_history = list(history or [])
            self.calls.append({"text": text, "history": recorded_history})
            return {"ok": True, "error": None, "result": f"echo {len(self.calls)}"}

    agent = RecordingAgent()
    wx, frame, panel = create_panel(tmp_path, wx_app, agent)

    panel.input.SetValue("first request")
    panel._on_send(None)
    flush_wx_events(wx)
    assert agent.calls[0]["history"] == []
    assert len(panel.history) == 1

    panel._on_new_chat(None)
    assert panel.history == []
    assert panel.history_list.GetItemCount() == 2
    assert "does not have any messages yet" in panel.get_transcript_text()

    panel.input.SetValue("second request")
    panel._on_send(None)
    flush_wx_events(wx)
    assert agent.calls[-1]["history"] == []
    assert len(panel.history) == 1

    panel._activate_conversation_by_index(0)
    assert "first request" in panel.get_transcript_text()

    panel._activate_conversation_by_index(1)
    assert "second request" in panel.get_transcript_text()

    _, conversations = read_history_database(history_db_path(tmp_path))
    prompts = [conv["entries"][0]["prompt"] for conv in conversations]
    assert prompts == ["first request", "second request"]

    destroy_panel(frame, panel)


def test_agent_chat_panel_history_columns_show_metadata(tmp_path, wx_app):
    class EchoAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {"ok": True, "error": None, "result": text.upper()}

    wx, frame, panel = create_panel(tmp_path, wx_app, EchoAgent())

    panel.input.SetValue("check metadata")
    panel._on_send(None)
    flush_wx_events(wx)

    assert panel.history_list.GetItemCount() == 1
    assert panel.history_list.GetColumnCount() == 2
    title = panel.history_list.GetTextValue(0, 0)
    last_activity = panel.history_list.GetTextValue(0, 1)

    assert "check metadata" in title
    assert last_activity != ""

    destroy_panel(frame, panel)


def test_agent_chat_panel_history_resize_repaints_rows(
    tmp_path, wx_app, monkeypatch
):
    class EchoAgent:
        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
            on_llm_step=None,
        ):
            return {"ok": True, "error": None, "result": text.upper()}

    wx, frame, panel = create_panel(tmp_path, wx_app, EchoAgent())

    try:
        flush_wx_events(wx)
        panel._history_column_widths = (100, 120)
        refresh_calls: list[bool] = []
        original_refresh = panel.history_list.__class__.Refresh

        def record_refresh(self, *args, **kwargs):  # pragma: no cover - exercised
            refresh_calls.append(True)
            return original_refresh(self, *args, **kwargs)

        monkeypatch.setattr(
            panel.history_list.__class__, "Refresh", record_refresh, raising=False
        )

        monkeypatch.setattr(
            panel,
            "_current_history_column_widths",
            lambda history_list=None: (140, 120),
        )

        idle_event = wx.IdleEvent()
        idle_event.SetEventObject(panel.history_list)
        panel._on_history_list_idle(idle_event)

        flush_wx_events(wx, count=6)

        assert refresh_calls
        assert not panel._history_column_refresh_scheduled
    finally:
        destroy_panel(frame, panel)


def test_agent_chat_panel_handles_tokenizer_failure(tmp_path, wx_app, monkeypatch):
    class EchoAgent:
        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
        ):
            return {"ok": True, "error": None, "result": text}


    elapsed_text = install_monotonic_stub(monkeypatch, elapsed_seconds=5)

    def failing_counter(*_args, **_kwargs) -> TokenCountResult:
        return TokenCountResult.unavailable(reason="boom")

    monkeypatch.setattr(
        "app.ui.agent_chat_panel.panel.count_text_tokens",
        failing_counter,
    )

    wx, frame, panel = create_panel(tmp_path, wx_app, EchoAgent())

    panel.input.SetValue("token failure")
    panel._on_send(None)
    flush_wx_events(wx)

    try:
        label = panel.status_label.GetLabel()
        expected = _("Received response in {time} • {tokens}").format(
            time=elapsed_text,
            tokens="n/a",
        )
        assert label == expected
        entry = panel.history[0]
        assert entry.token_info is not None
        assert entry.token_info.tokens is None
    finally:
        destroy_panel(frame, panel)


def test_agent_chat_panel_updates_status_with_token_count(
    tmp_path, wx_app, monkeypatch
):
    class EchoAgent:
        def run_command(
            self,
            text,
            *,
            history=None,
            context=None,
            cancellation=None,
            on_tool_result=None,
        ):
            return {"ok": True, "error": None, "result": text}

    from app.i18n import _

    elapsed_text = install_monotonic_stub(monkeypatch, elapsed_seconds=5)

    def fixed_counter(*_args, **_kwargs) -> TokenCountResult:
        return TokenCountResult.exact(1000)

    monkeypatch.setattr(
        "app.ui.agent_chat_panel.panel.count_text_tokens",
        fixed_counter,
    )

    wx, frame, panel = create_panel(tmp_path, wx_app, EchoAgent())

    panel.input.SetValue("token success")
    panel._on_send(None)
    flush_wx_events(wx)

    try:
        label = panel.status_label.GetLabel()
        tokens_text = "~1.00 k tokens"
        expected = _("Received response in {time} • {tokens}").format(
            time=elapsed_text,
            tokens=tokens_text,
        )
        assert label == expected
        tokens = panel.tokens
        assert tokens.tokens is not None and 990 <= tokens.tokens <= 1010
        assert tokens.approximate
    finally:
        destroy_panel(frame, panel)


def test_wait_status_reports_full_prompt_tokens(tmp_path, wx_app, monkeypatch):
    class DummyAgent:
        def run_command(self, *_args, **_kwargs):
            return {"ok": True, "error": None, "result": {}}

    model_name = "fake-model"
    system_text = str(SYSTEM_PROMPT)
    token_map = {
        system_text: 100,
        "history prompt": 10,
        "history response": 20,
        "tool": 8,
        "history tool": 6,
        "tool payload": 24,
        "context-role": 5,
        "context message": 15,
        "user prompt": 30,
    }

    def fake_count(text, *, model=None):
        value = token_map.get(str(text), 0)
        return TokenCountResult.exact(value, model=model or model_name)

    monkeypatch.setattr("app.ui.agent_chat_panel.panel.count_text_tokens", fake_count)
    monkeypatch.setattr("app.ui.chat_entry.count_text_tokens", fake_count)

    wx, frame, panel = create_panel(tmp_path, wx_app, DummyAgent())

    try:
        panel._token_model = lambda: model_name
        conversation = panel._ensure_active_conversation()
        conversation.append_entry(
            ChatEntry(
                prompt="history prompt",
                response="history response",
                tokens=0,
                token_info=TokenCountResult.exact(0, model=model_name),
                prompt_at="2024-01-01T00:00:00Z",
                response_at="2024-01-01T00:01:00Z",
                tool_messages=(
                    {
                        "role": "tool",
                        "name": "history tool",
                        "content": "tool payload",
                    },
                ),
            )
        )

        context_messages = ({"role": "context-role", "content": "context message"},)

        handle = _AgentRunHandle(
            run_id=1,
            prompt="user prompt",
            prompt_tokens=TokenCountResult.exact(token_map["user prompt"], model=model_name),
            cancel_event=CancellationEvent(),
            prompt_at="2024-01-01T00:02:00Z",
        )
        handle.context_messages = context_messages

        pending_entry = panel._add_pending_entry(
            conversation,
            "user prompt",
            prompt_at="2024-01-01T00:02:00Z",
            context_messages=context_messages,
        )
        handle.pending_entry = pending_entry

        class _CoordinatorStub:
            def __init__(self, active_handle):
                self.active_handle = active_handle

            def stop(self) -> None:  # pragma: no cover - cleanup helper
                return None

        panel._coordinator = _CoordinatorStub(handle)

        breakdown = panel._compute_context_token_breakdown()
        expected_total = sum(
            token_map[key]
            for key in (
                system_text,
                "history prompt",
                "history response",
                "tool",
                "history tool",
                "tool payload",
                "context-role",
                "context message",
                "user prompt",
            )
        )
        assert breakdown.total.tokens == expected_total

        panel._set_wait_state(True, handle.prompt_tokens)

        total_tokens = panel.tokens
        assert total_tokens.tokens == expected_total
        assert total_tokens.model == model_name


        assert panel.status_label.GetLabel() == _("Working {time}").format(
            time="00:00"
        )
    finally:
        if panel._session.is_running:
            panel._set_wait_state(False, TokenCountResult.exact(0, model=model_name))
        destroy_panel(frame, panel)


def test_agent_history_sash_waits_for_ready_size(tmp_path, wx_app, monkeypatch):
    class DummyAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {"ok": True, "error": None, "result": text}

    wx, frame, panel = create_panel(tmp_path, wx_app, DummyAgent())

    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(panel, 1, wx.EXPAND)
    frame.SetSizer(sizer)

    splitter = panel._horizontal_splitter
    view = panel._history_view
    minimum = splitter.GetMinimumPaneSize()
    desired = minimum + panel.FromDIP(180)
    attempts: list[int] = []
    original_attempt = view._attempt_set_sash

    def tracking_attempt(target: int) -> bool:
        attempts.append(target)
        if len(attempts) == 1:
            return False
        return original_attempt(target)

    monkeypatch.setattr(view, "_attempt_set_sash", tracking_attempt)

    panel.apply_history_sash(desired)

    assert attempts[0] == desired
    assert len(attempts) == 1
    assert view._sash_goal == desired
    assert view._sash_dirty

    wx_app.Yield()
    assert attempts == [desired]

    frame.Show()
    large_width = desired + panel.FromDIP(320)
    frame.SetClientSize((int(large_width), int(panel.FromDIP(400))))
    frame.Layout()
    frame.SendSizeEvent()
    wx_app.Yield()
    wx_app.Yield()

    assert attempts[0] == desired
    assert attempts[-1] == desired
    assert len(attempts) >= 2
    assert view._sash_goal == desired
    assert not view._sash_dirty
    assert panel.history_sash == splitter.GetSashPosition()
    assert splitter.GetSashPosition() >= minimum

    wx_app.Yield()
    assert attempts[-1] == desired
    assert not view._sash_dirty

    destroy_panel(frame, panel)
    wx_app.Yield()
