"""Tests for MCP tool summary rendering helpers."""

from __future__ import annotations

from app.agent.run_contract import ToolResultSnapshot
from app.llm.tokenizer import TokenCountResult
from app.ui.agent_chat_panel.tool_summaries import summarize_tool_results


def test_read_user_document_summary_uses_compact_preview(monkeypatch) -> None:
    """Ensure that read_user_document results present a truncated preview."""

    def fake_count(text: object, *, model: str | None = None) -> TokenCountResult:
        assert isinstance(text, str)
        assert "First line" in text
        return TokenCountResult.exact(123)

    monkeypatch.setattr(
        "app.ui.agent_chat_panel.tool_summaries.count_text_tokens",
        fake_count,
    )

    content = "     1: First line\n     2: Second line\n"
    snapshot = ToolResultSnapshot(
        call_id="call-1",
        tool_name="read_user_document",
        status="succeeded",
        arguments={"path": "docs/sample.txt"},
        result={
            "path": "docs/sample.txt",
            "encoding": "utf-8",
            "encoding_source": "detected",
            "encoding_confidence": 1.0,
            "start_line": 1,
            "end_line": 2,
            "bytes_consumed": len(content.encode("utf-8")),
            "content": content,
            "truncated": False,
        },
    )

    summary_tuple = summarize_tool_results([snapshot])
    assert len(summary_tuple) == 1
    summary = summary_tuple[0]
    encoding_line = next(
        line for line in summary.bullet_lines if line.startswith("Encoding:")
    )
    assert "utf-8" in encoding_line
    preview_line = next(
        line for line in summary.bullet_lines if line.startswith("Content preview:")
    )
    assert "1: First line" in preview_line
    assert "2: Second line" in preview_line
    assert "lines: 2, tokens: 123, characters:" in preview_line
    assert preview_line.count("…") >= 2


def test_read_user_document_summary_includes_continuation_hint(monkeypatch) -> None:
    """Ensure that read_user_document results surface continuation details."""

    def fake_count(text: object, *, model: str | None = None) -> TokenCountResult:
        assert isinstance(text, str)
        return TokenCountResult.exact(42)

    monkeypatch.setattr(
        "app.ui.agent_chat_panel.tool_summaries.count_text_tokens",
        fake_count,
    )

    content = "     1: First line\n     2: Second line\n"
    snapshot = ToolResultSnapshot(
        call_id="call-1",
        tool_name="read_user_document",
        status="succeeded",
        arguments={"path": "docs/sample.txt"},
        result={
            "path": "docs/sample.txt",
            "encoding": "utf-8",
            "encoding_source": "detected",
            "encoding_confidence": 1.0,
            "start_line": 1,
            "end_line": 2,
            "bytes_consumed": len(content.encode("utf-8")),
            "content": content,
            "truncated": True,
            "continuation_hint": {
                "next_start_line": 101,
                "max_chunk_bytes": 4096,
                "bytes_remaining": 2048,
                "truncated_mid_line": True,
                "line_exceeded_chunk_limit": True,
            },
        },
    )

    summary = summarize_tool_results([snapshot])[0]
    hint_line = next(
        line for line in summary.bullet_lines if line.startswith("Hint:")
    )
    assert "read_user_document" in hint_line
    assert "start_line=101" in hint_line
    assert "max_bytes≤4096" in hint_line
    assert "bytes remain" in hint_line
    assert "Increase `max_bytes`" in hint_line


def test_create_user_document_arguments_use_preview(monkeypatch) -> None:
    """Ensure that create_user_document arguments include a compact preview."""

    def fake_count(text: object, *, model: str | None = None) -> TokenCountResult:
        assert isinstance(text, str)
        assert "Alpha" in text
        return TokenCountResult.approximate_result(9)

    monkeypatch.setattr(
        "app.ui.agent_chat_panel.tool_summaries.count_text_tokens",
        fake_count,
    )

    content = "Alpha\nBeta\nGamma"
    snapshot = ToolResultSnapshot(
        call_id="call-1",
        tool_name="create_user_document",
        status="succeeded",
        arguments={
            "path": "docs/new.txt",
            "content": content,
            "exist_ok": True,
        },
        result={
            "path": "docs/new.txt",
            "bytes_written": len(content.encode("utf-8")),
            "encoding": "utf-8",
        },
    )

    summary_tuple = summarize_tool_results([snapshot])
    assert len(summary_tuple) == 1
    summary = summary_tuple[0]
    preview_line = next(
        line for line in summary.bullet_lines if line.startswith("Content preview:")
    )
    assert "Alpha" in preview_line and "Gamma" in preview_line
    assert "lines: 3, tokens: ≈9, characters: 16" in preview_line
    assert preview_line.endswith("Gamma`")
