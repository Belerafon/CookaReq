"""Tests for MCP tool summary rendering helpers."""

from __future__ import annotations

from app.llm.tokenizer import TokenCountResult
from app.ui.agent_chat_panel.tool_summaries import summarize_tool_payload


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
    payload = {
        "tool_name": "read_user_document",
        "tool_arguments": {"path": "docs/sample.txt"},
        "result": {
            "path": "docs/sample.txt",
            "start_line": 1,
            "end_line": 2,
            "bytes_consumed": len(content.encode("utf-8")),
            "content": content,
            "truncated": False,
        },
        "ok": True,
    }

    summary = summarize_tool_payload(1, payload)
    assert summary is not None
    preview_line = next(
        line for line in summary.bullet_lines if line.startswith("Content preview:")
    )
    assert "1: First line" in preview_line
    assert "2: Second line" in preview_line
    assert "lines: 2, tokens: 123, characters:" in preview_line
    assert preview_line.count("…") >= 2


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
    payload = {
        "tool_name": "create_user_document",
        "tool_arguments": {
            "path": "docs/new.txt",
            "content": content,
            "exist_ok": True,
        },
        "result": {"path": "docs/new.txt", "bytes_written": len(content.encode("utf-8"))},
        "ok": True,
    }

    summary = summarize_tool_payload(1, payload)
    assert summary is not None
    preview_line = next(
        line for line in summary.bullet_lines if line.startswith("Content preview:")
    )
    assert "Alpha" in preview_line and "Gamma" in preview_line
    assert "lines: 3, tokens: ≈9, characters: 16" in preview_line
    assert preview_line.endswith("Gamma`")
