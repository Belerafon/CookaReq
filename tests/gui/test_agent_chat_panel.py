import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any
from collections.abc import Mapping, Sequence

from app.confirm import ConfirmDecision, reset_requirement_update_preference, set_confirm, set_requirement_update_confirm
from app.llm.tokenizer import TokenCountResult
from app.ui.agent_chat_panel.token_usage import summarize_token_usage
from app.ui.agent_chat_panel import AgentProjectSettings, RequirementConfirmPreference
from app.ui.widgets.chat_message import MessageBubble, TranscriptMessagePanel
from app import i18n

import pytest


pytestmark = [pytest.mark.gui, pytest.mark.integration, pytest.mark.gui_smoke]


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
    for _ in range(count):
        wx.Yield()


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
        history_path=tmp_path / "history.json",
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
def test_agent_chat_panel_sends_and_saves_history(tmp_path, wx_app):
    class DummyAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {"ok": True, "error": None, "result": {"echo": text}}

    wx, frame, panel = create_panel(tmp_path, wx_app, DummyAgent())

    baseline_total = panel._compute_context_token_breakdown().total
    baseline_label = panel._conversation_label.GetLabel()

    panel.input.SetValue("run")
    panel._on_send(None)
    flush_wx_events(wx)

    updated_total = panel._compute_context_token_breakdown().total
    updated_label = panel._conversation_label.GetLabel()
    assert updated_label != baseline_label
    assert (updated_total.tokens or 0) >= (baseline_total.tokens or 0)
    expected_tokens = panel._format_tokens_for_status(updated_total)
    assert expected_tokens in updated_label
    expected_percent = panel._format_context_percentage(
        updated_total, panel._context_token_limit()
    )
    assert expected_percent in updated_label

    transcript = panel.get_transcript_text()
    assert "run" in transcript
    assert "\"echo\": \"run\"" in transcript
    assert panel.history_list.GetItemCount() == 1
    assert panel.input.GetValue() == ""
    assert len(panel.history) == 1

    saved = json.loads((tmp_path / "history.json").read_text())
    assert saved["version"] == 2
    assert isinstance(saved.get("active_id"), str)
    conversations = saved["conversations"]
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

    context_payload = {"role": "system", "content": "Active requirements list: SYS"}

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
            {"role": "system", "content": "Active requirements list: SYS"},
        )
        assert panel.history
        stored_entry = panel.history[0]
        assert stored_entry.context_messages == (
            {"role": "system", "content": "Active requirements list: SYS"},
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
            panel._append_history(prompt, base_response, base_response, None, None, None)
            panel._render_transcript()
        flush_wx_events(wx, count=5)

        transcript_panel = panel.transcript_panel
        assert transcript_panel.GetVirtualSize().GetHeight() > transcript_panel.GetClientSize().GetHeight()

        transcript_panel.Scroll(0, 0)
        flush_wx_events(wx, count=2)
        view_x, view_y = transcript_panel.GetViewStart()
        assert view_y == 0

        long_response = "\n".join(f"final line {line}" for line in range(40))
        panel._append_history("final prompt", long_response, long_response, None, None, None)
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
        def collect_collapsible(window):
            panes: list[wx.CollapsiblePane] = []
            for child in window.GetChildren():
                if isinstance(child, wx.CollapsiblePane):
                    panes.append(child)
                panes.extend(collect_collapsible(child))
            return panes

        assert not collect_collapsible(panel.transcript_panel)

        transcript_text = panel.get_transcript_text()
        assert "demo_tool" in transcript_text
        assert "Agent: tool call" in transcript_text
        assert "tool_results" not in transcript_text
        assert "Query: `inspect`" in transcript_text

        log_text = panel.get_transcript_log_text()
        assert "demo_tool" in log_text
        assert "Agent → MCP call 1" in log_text
        assert "MCP → Agent response 1" in log_text
        assert "query" in log_text
        assert "LLM system prompt" in log_text
        assert "LLM tool specification" in log_text
        assert "Agent → LLM request" in log_text
        assert "LLM → Agent message" in log_text
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
                "Active requirements list: sys: System req.\n"
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

        context_pane = panes[0]
        label_value = context_pane.GetLabel()
        expected_labels = {"", "Context", i18n.gettext("Context")}
        assert label_value in expected_labels
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
        assert "Active requirements list: sys: System req." in value
        assert "Selected requirement RIDs: sys48, sys49, sys50" in value

        # Context pane should live inside the user message bubble so that it scrolls together with the prompt
        bubble_ancestor = context_pane.GetParent()
        while bubble_ancestor is not None and not isinstance(bubble_ancestor, MessageBubble):
            bubble_ancestor = bubble_ancestor.GetParent()
        assert isinstance(
            bubble_ancestor, MessageBubble
        ), "context pane expected inside the user bubble"
    finally:
        destroy_panel(frame, panel)


def test_agent_chat_panel_orders_tool_bubbles_before_agent_reply(tmp_path, wx_app):
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
        entry_panels = [
            child
            for child in panel.transcript_panel.GetChildren()
            if isinstance(child, TranscriptMessagePanel)
        ]
        assert entry_panels, "expected transcript entry"
        entry = entry_panels[0]

        def bubble_headers(message_panel):
            headers: list[str] = []
            for child in message_panel.GetChildren():
                if not isinstance(child, MessageBubble):
                    continue
                bubble_panel = None
                for candidate in child.GetChildren():
                    if isinstance(candidate, wx.Panel):
                        bubble_panel = candidate
                        break
                if bubble_panel is None:
                    continue
                header_label = None
                for candidate in bubble_panel.GetChildren():
                    if isinstance(candidate, wx.StaticText):
                        header_label = candidate.GetLabel()
                        break
                if header_label is not None:
                    headers.append(header_label)
            return headers

        headers = bubble_headers(entry)
        assert headers, "expected at least one bubble"

        agent_indexes = [idx for idx, label in enumerate(headers) if "Agent" in label]
        assert agent_indexes, "agent bubble missing"
        agent_index = agent_indexes[-1]
        tool_indexes = [idx for idx, label in enumerate(headers) if "demo_tool" in label]
        assert tool_indexes, "tool bubble missing"
        assert tool_indexes[0] < agent_index
        assert agent_index == len(headers) - 1
    finally:
        destroy_panel(frame, panel)


def test_transcript_message_panel_shows_reasoning(wx_app):
    wx = pytest.importorskip("wx")
    from app.i18n import _

    frame = wx.Frame(None)
    try:
        panel = TranscriptMessagePanel(
            frame,
            prompt="user",
            response="assistant",
            reasoning_segments=[
                {"type": "analysis", "text": "first step"},
                {"type": "", "text": "second step"},
            ],
        )
        reasoning_label = _("Model reasoning")
        panes = [
            child
            for child in panel.GetChildren()
            if isinstance(child, wx.CollapsiblePane)
        ]
        assert panes, "reasoning pane should be created"
        reasoning_pane = panes[0]
        label_value = reasoning_pane.GetLabel()
        if label_value:
            assert label_value == reasoning_label
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


def test_transcript_message_panel_orders_supplements_after_messages(wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.widgets.chat_message import MessageBubble

    frame = wx.Frame(None)
    try:
        prompt_ts = "2024-06-11 18:41:03"
        response_ts = "2024-06-11 18:42:07"
        panel = TranscriptMessagePanel(
            frame,
            prompt="user",
            response="assistant",
            prompt_timestamp=prompt_ts,
            response_timestamp=response_ts,
            context_messages=[{"role": "system", "content": "ctx"}],
            reasoning_segments=[{"type": "analysis", "text": "think"}],
        )
        wx.GetApp().Yield()

        child_windows = [
            item.GetWindow()
            for item in panel.GetSizer().GetChildren()
            if item.IsWindow()
        ]
        assert child_windows, "expected child windows"

        # Reasoning pane is still rendered after the agent bubble on the top level
        top_level_collapsible = [
            window
            for window in child_windows
            if isinstance(window, wx.CollapsiblePane)
        ]
        assert len(top_level_collapsible) == 1, "expected only reasoning pane on top level"

        def collect_all_panes(window):
            panes: list[wx.CollapsiblePane] = []
            for child in window.GetChildren():
                if isinstance(child, wx.CollapsiblePane):
                    panes.append(child)
                panes.extend(collect_all_panes(child))
            return panes

        all_panes = collect_all_panes(panel)
        assert len(all_panes) == 2, "expected reasoning and context panes in total"

        context_panes = [
            pane
            for pane in all_panes
            if pane.GetLabel() in {"", "Context", i18n.gettext("Context")}
        ]
        assert context_panes, "missing context pane"

        context_parent = context_panes[0].GetParent()
        while context_parent is not None and not isinstance(context_parent, MessageBubble):
            context_parent = context_parent.GetParent()
        assert isinstance(
            context_parent, MessageBubble
        ), "context pane should be nested under the user message bubble"

        reasoning_pane = top_level_collapsible[0]

        def collect_labels(window: wx.Window) -> list[str]:
            labels: list[str] = []
            stack = [window]
            while stack:
                current = stack.pop()
                if isinstance(current, wx.StaticText):
                    labels.append(current.GetLabel())
                stack.extend(current.GetChildren())
            return labels

        user_bubble = None
        agent_bubble = None
        for window in child_windows:
            if not isinstance(window, MessageBubble):
                continue
            labels = collect_labels(window)
            if any("Agent" in label for label in labels):
                agent_bubble = window
            elif any("You" in label for label in labels):
                user_bubble = window

        assert user_bubble is not None, "user bubble missing"
        assert agent_bubble is not None, "agent bubble missing"

        assert prompt_ts in "\n".join(collect_labels(user_bubble))
        assert response_ts in "\n".join(collect_labels(agent_bubble))

        assert child_windows.index(agent_bubble) < child_windows.index(reasoning_pane)
    finally:
        panel.Destroy()
        frame.Destroy()


def test_transcript_message_panel_reuses_layout_hints(wx_app):
    wx = pytest.importorskip("wx")

    frame = wx.Frame(None)
    first_panel = None
    second_panel = None
    try:
        recorded_hints: dict[str, int] = {}

        def store_hint(key: str, width: int) -> None:
            recorded_hints[key] = int(width)

        first_panel = TranscriptMessagePanel(
            frame,
            prompt="hello",
            response="this is a fairly long answer " * 8,
            on_layout_hint=store_hint,
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

        second_panel = TranscriptMessagePanel(
            frame,
            prompt="hello",
            response="short",
            layout_hints={"agent": agent_hint},
        )
        sizer.Add(second_panel, 1, wx.EXPAND)
        wx.GetApp().Yield()

        def has_agent_header(window: MessageBubble) -> bool:
            stack = list(window.GetChildren())
            while stack:
                child = stack.pop()
                if isinstance(child, wx.StaticText) and "Agent" in child.GetLabel():
                    return True
                stack.extend(child.GetChildren())
            return False

        child_windows = [
            item.GetWindow()
            for item in second_panel.GetSizer().GetChildren()
            if item.IsWindow()
        ]

        agent_bubbles = [
            window
            for window in child_windows
            if isinstance(window, MessageBubble) and has_agent_header(window)
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


def test_agent_transcript_log_orders_sections_for_errors(tmp_path, wx_app):
    class ErrorAgent:
        def run_command(self, text, *, history=None, context=None, cancellation=None, on_tool_result=None, on_llm_step=None):
            return {
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid arguments",
                },
            }

    wx, frame, panel = create_panel(tmp_path, wx_app, ErrorAgent())

    panel.input.SetValue("trigger error")
    panel._on_send(None)
    flush_wx_events(wx)

    try:
        log_text = panel.get_transcript_log_text()
        assert "VALIDATION_ERROR" in log_text

        order = {
            "agent_llm": log_text.index("Agent → LLM request"),
            "llm_agent": log_text.index("LLM → Agent message"),
            "agent_mcp": log_text.index("Agent → MCP calls: (none)"),
            "mcp_agent": log_text.index("MCP → Agent responses: (none)"),
            "agent_user": log_text.index("Agent → User response"),
        }

        assert order["agent_llm"] < order["llm_agent"] < order["agent_mcp"]
        assert order["agent_mcp"] < order["mcp_agent"] < order["agent_user"]
        assert "Agent reported error payload" in log_text
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
        assert "LLM → Agent planned tool calls:" in log_text
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


def test_message_bubble_respects_scrolled_viewport_width(wx_app):
    wx = pytest.importorskip("wx")
    from wx.lib.scrolledpanel import ScrolledPanel

    frame = wx.Frame(None, size=wx.Size(1024, 768))
    scrolled = ScrolledPanel(frame, style=wx.TAB_TRAVERSAL)
    scrolled_sizer = wx.BoxSizer(wx.VERTICAL)
    scrolled.SetSizer(scrolled_sizer)

    entry = TranscriptMessagePanel(
        scrolled,
        prompt="user prompt " * 40,
        response="agent response " * 200,
    )
    padding = entry.FromDIP(4)
    scrolled_sizer.Add(entry, 0, wx.EXPAND | wx.ALL, padding)

    frame_sizer = wx.BoxSizer(wx.VERTICAL)
    frame_sizer.Add(scrolled, 1, wx.EXPAND)
    frame.SetSizer(frame_sizer)
    frame.Layout()
    scrolled.SetupScrolling(scroll_x=False, scroll_y=True)
    frame.Show()
    flush_wx_events(wx, count=10)

    def _agent_bubble() -> tuple[MessageBubble, wx.Panel]:
        bubbles = [
            child
            for child in entry.GetChildren()
            if isinstance(child, MessageBubble)
        ]
        assert bubbles, "expected transcript bubbles"
        bubble = bubbles[-1]
        panels = [
            child for child in bubble.GetChildren() if isinstance(child, wx.Panel)
        ]
        assert panels, "bubble should host an inner panel"
        return bubble, panels[0]

    try:
        bubble, inner_panel = _agent_bubble()
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

        _, resized_panel = _agent_bubble()
        resized_width = resized_panel.GetSize().width
        shrunk_viewport = scrolled.GetClientSize().width
        assert shrunk_viewport < viewport_width
        assert resized_width <= shrunk_viewport
        assert resized_width >= int(shrunk_viewport * 0.65)

        assert _agent_bubble()[0] is bubble
    finally:
        frame.Destroy()


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


def test_agent_chat_panel_stop_cancels_generation(tmp_path, wx_app):
    from app.i18n import _
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
        assert panel._stop_btn is not None and panel._stop_btn.IsEnabled()

        panel._on_stop(None)

        assert panel.input.GetValue() == "stop me"
        assert panel.status_label.GetLabel() == _("Generation cancelled")
        assert panel._stop_btn is not None and not panel._stop_btn.IsEnabled()

        assert agent.cancel_seen.wait(1.0)
        assert agent.completed.wait(1.0)
        wx.Yield()

        history = panel.history
        assert len(history) == 1
        entry = history[0]
        assert entry.prompt == "stop me"
        assert entry.display_response == _("Generation cancelled")
        assert entry.response == ""
        assert entry.response_at is not None
    finally:
        if frame is not None and panel is not None:
            destroy_panel(frame, panel)
        pool.shutdown(wait=True, cancel_futures=True)


def test_agent_chat_panel_cancellation_preserves_llm_step(tmp_path, wx_app):
    from app.i18n import _
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
                                        "field": "title",
                                        "value": "Настройки агента",
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


def test_agent_chat_panel_streams_tool_results(tmp_path, wx_app):
    from app.i18n import _

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
        assert panel._is_running

        agent.release.set()
        deadline = time.time() + 2.0
        while panel._is_running and time.time() < deadline:
            wx_app.Yield()
            time.sleep(0.05)
        flush_wx_events(wx, count=4)

        assert not panel._is_running
    finally:
        agent.release.set()
        destroy_panel(frame, panel)


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

    from app.i18n import _

    try:
        prompt_tokens = TokenCountResult.exact(1000)
        panel._set_wait_state(True, prompt_tokens)
        flush_wx_events(wx)

        final_tokens = TokenCountResult.exact(2000)
        panel._set_wait_state(False, final_tokens)
        flush_wx_events(wx)

        limit = panel._context_token_limit()
        expected_details = summarize_token_usage(final_tokens, limit)
        expected_label = _("{base} — {details}").format(
            base=_("Ready"),
            details=expected_details,
        )

        assert panel.status_label.GetLabel() == expected_label
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
    assert len(panel2.history) == 1
    assert panel2.history[0].prompt == "hello"
    destroy_panel(frame2, panel2)


def test_agent_chat_panel_handles_invalid_history(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.agent_chat_panel import AgentChatPanel

    bad_file = tmp_path / "history.json"
    bad_file.write_text("{not json}")

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
    destroy_panel(frame, panel)


def test_agent_chat_panel_rejects_unknown_history_version(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.agent_chat_panel import AgentChatPanel

    legacy_file = tmp_path / "history.json"
    legacy_file.write_text(json.dumps({"version": 1, "conversations": []}))

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
    assert panel.history_list.GetItemCount() == 0
    assert "Start chatting" in panel.get_transcript_text()

    destroy_panel(frame, panel)


def test_agent_chat_panel_rejects_entries_without_token_info(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    from app.ui.agent_chat_panel import AgentChatPanel

    legacy_file = tmp_path / "history.json"
    legacy_file.write_text(
        json.dumps(
            {
                "version": 2,
                "active_id": "conv-1",
                "conversations": [
                    {
                        "id": "conv-1",
                        "title": "Legacy conversation",
                        "created_at": "2024-01-01T00:00:00Z",
                        "updated_at": "2024-01-01T00:00:00Z",
                        "entries": [
                            {
                                "prompt": "old request",
                                "response": "old response",
                                "tokens": 2,
                            }
                        ],
                    }
                ],
            }
        )
    )

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
    assert panel.history_list.GetItemCount() == 0
    assert "Start chatting" in panel.get_transcript_text()

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
                None,
                None,
                TokenCountResult.exact(1),
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

    saved = json.loads((tmp_path / "history.json").read_text())
    prompts = [conv["entries"][0]["prompt"] for conv in saved["conversations"]]
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

    from app.i18n import _

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
        tokens = panel._current_tokens
        assert tokens.tokens is not None and 990 <= tokens.tokens <= 1010
        assert tokens.approximate
    finally:
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
