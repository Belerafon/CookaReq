from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace

from app.llm.tokenizer import TokenCountResult

from app.ui.agent_chat_panel.controller import AgentRunCallbacks, AgentRunController
from app.ui.agent_chat_panel.panel import AgentChatPanel, _PendingAttachment


def _build_pending_attachment() -> _PendingAttachment:
    token_info = TokenCountResult.exact(12)
    return _PendingAttachment(
        filename="note.txt",
        content="hello",
        size_bytes=5,
        message_content="file: note.txt\nhello",
        token_info=token_info,
        preview_lines=("hello",),
    )


def test_prepare_context_messages_skips_duplicate_attachment_metadata():
    panel = AgentChatPanel.__new__(AgentChatPanel)
    panel._attachment_summary = None
    panel._refresh_bottom_panel_layout = lambda: None
    attachment = _build_pending_attachment()
    panel._pending_attachment = attachment

    existing_message = attachment.to_context_message()
    prepared = panel._prepare_context_messages([existing_message])

    assert prepared == (existing_message,)
    assert panel._pending_attachment is None


def test_prepare_context_messages_appends_pending_attachment_when_missing():
    panel = AgentChatPanel.__new__(AgentChatPanel)
    panel._attachment_summary = None
    panel._refresh_bottom_panel_layout = lambda: None
    attachment = _build_pending_attachment()
    panel._pending_attachment = attachment

    prepared = panel._prepare_context_messages([])

    assert len(prepared) == 1
    message = prepared[0]
    assert isinstance(message.get("metadata"), Mapping)
    assert message["metadata"]["attachment"]["filename"] == attachment.filename
    assert panel._pending_attachment is None


def test_submit_prompt_with_prepared_context_skips_extra_processing():
    conversation = SimpleNamespace(conversation_id="c1", entries=())
    prepared_messages = ({"role": "system", "content": "ready"},)
    calls: dict[str, int] = {"prepare": 0}

    def _prepare_context_messages(context: object) -> tuple[dict, ...]:
        calls["prepare"] += 1
        return tuple(dict(message) for message in context or ())

    callbacks = AgentRunCallbacks(
        ensure_active_conversation=lambda: conversation,
        get_conversation_by_id=lambda cid: conversation if cid == "c1" else None,
        conversation_messages=lambda: (),
        conversation_messages_for=lambda conv: (),
        prepare_context_messages=_prepare_context_messages,
        add_pending_entry=lambda *_args, **_kwargs: None,
        remove_entry=lambda *_args, **_kwargs: None,
        restore_entry=lambda *_args, **_kwargs: None,
        is_running=lambda: False,
        persist_history=lambda: None,
        refresh_history=lambda: None,
        render_transcript=lambda: None,
        set_wait_state=lambda *_args, **_kwargs: None,
        confirm_override_kwargs=lambda: {},
        finalize_prompt=lambda *_args, **_kwargs: None,
        handle_streamed_tool_results=lambda *_args, **_kwargs: None,
        handle_llm_step=lambda *_args, **_kwargs: None,
    )

    controller = AgentRunController(
        agent_supplier=lambda **_kwargs: None,
        command_executor=None,
        token_model_resolver=lambda: None,
        context_provider=None,
        callbacks=callbacks,
    )

    captured: dict[str, object | None] = {}

    def _capture_start_prompt(**kwargs: object) -> None:  # type: ignore[override]
        captured.update(kwargs)

    controller._start_prompt = _capture_start_prompt  # type: ignore[assignment]

    controller.submit_prompt_with_context(
        "hello",
        conversation_id="c1",
        context_messages=prepared_messages,
        prompt_at="t",
        prepared_context=True,
    )

    assert calls["prepare"] == 0
    assert captured["context_messages"] == tuple(dict(m) for m in prepared_messages)


def test_submit_prompt_with_context_runs_preparation_by_default():
    conversation = SimpleNamespace(conversation_id="c1", entries=())
    calls: dict[str, int] = {"prepare": 0}

    def _prepare_context_messages(context: object) -> tuple[dict, ...]:
        calls["prepare"] += 1
        return tuple(dict(message) for message in context or ())

    callbacks = AgentRunCallbacks(
        ensure_active_conversation=lambda: conversation,
        get_conversation_by_id=lambda cid: conversation if cid == "c1" else None,
        conversation_messages=lambda: (),
        conversation_messages_for=lambda conv: (),
        prepare_context_messages=_prepare_context_messages,
        add_pending_entry=lambda *_args, **_kwargs: None,
        remove_entry=lambda *_args, **_kwargs: None,
        restore_entry=lambda *_args, **_kwargs: None,
        is_running=lambda: False,
        persist_history=lambda: None,
        refresh_history=lambda: None,
        render_transcript=lambda: None,
        set_wait_state=lambda *_args, **_kwargs: None,
        confirm_override_kwargs=lambda: {},
        finalize_prompt=lambda *_args, **_kwargs: None,
        handle_streamed_tool_results=lambda *_args, **_kwargs: None,
        handle_llm_step=lambda *_args, **_kwargs: None,
    )

    controller = AgentRunController(
        agent_supplier=lambda **_kwargs: None,
        command_executor=None,
        token_model_resolver=lambda: None,
        context_provider=None,
        callbacks=callbacks,
    )

    controller._start_prompt = lambda **_kwargs: None  # type: ignore[assignment]

    controller.submit_prompt_with_context(
        "hello",
        conversation_id="c1",
        context_messages=({"role": "system", "content": "raw"},),
        prompt_at="t",
    )

    assert calls["prepare"] == 1
