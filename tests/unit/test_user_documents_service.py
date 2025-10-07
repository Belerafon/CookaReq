from __future__ import annotations

from pathlib import Path

import pytest

from app.services.user_documents import MAX_READ_BYTES, UserDocumentsService


def create_service(tmp_path: Path, *, model: str | None = None) -> UserDocumentsService:
    root = tmp_path / "docs"
    root.mkdir()
    return UserDocumentsService(root, max_context_tokens=100, token_model=model)


def test_list_tree_reports_tokens_and_percentages(tmp_path: Path) -> None:
    service = create_service(tmp_path)
    (service.root / "guide").mkdir()
    (service.root / "guide" / "intro.txt").write_text("hello world", encoding="utf-8")
    (service.root / "guide" / "details.md").write_text("line one\nline two\n", encoding="utf-8")
    (service.root / "notes.txt").write_text("alpha beta gamma", encoding="utf-8")

    payload = service.list_tree()

    assert payload["root"] == str(service.root)
    assert payload["max_context_tokens"] == 100
    root_entry = payload["root_entry"]
    assert root_entry["name"] == service.root.name
    entries = payload["entries"]
    assert len(entries) == 2
    notes = next(item for item in entries if item["name"] == "notes.txt")
    assert notes["type"] == "file"
    assert notes["token_count"]["tokens"] is not None
    assert notes["percent_of_context"] > 0
    guide = next(item for item in entries if item["name"] == "guide")
    assert guide["type"] == "directory"
    assert guide["token_count"]["tokens"] >= notes["token_count"]["tokens"]
    assert "guide" in payload["tree_text"]
    assert "tokens" in payload["tree_text"]


def test_read_file_applies_line_numbers_and_limits(tmp_path: Path) -> None:
    service = create_service(tmp_path)
    content = "\n".join(f"line {idx}" for idx in range(1, 21))
    target = service.create_file("chapter.txt", content=content)

    result = service.read_file(target.name, start_line=5, max_bytes=40)

    assert result["start_line"] == 5
    assert result["end_line"] >= 5
    assert result["bytes_consumed"] <= 40
    assert result["truncated"] is True
    assert "     5:" in result["content"]


def test_create_file_rejects_existing_paths_without_flag(tmp_path: Path) -> None:
    service = create_service(tmp_path)
    service.create_file("report.txt", content="initial")

    with pytest.raises(FileExistsError):
        service.create_file("report.txt", content="overwrite")


def test_delete_file_and_traversal_guard(tmp_path: Path) -> None:
    service = create_service(tmp_path)
    created = service.create_file("folder/data.txt", content="payload")
    assert created.exists()

    service.delete_file("folder/data.txt")
    assert not created.exists()

    outside = tmp_path / "other.txt"
    outside.write_text("danger", encoding="utf-8")
    with pytest.raises(PermissionError):
        service.delete_file(outside)


def test_read_file_rejects_invalid_arguments(tmp_path: Path) -> None:
    service = create_service(tmp_path)
    target = service.create_file("notes.txt", content="text")

    with pytest.raises(ValueError):
        service.read_file(target.name, start_line=0)
    with pytest.raises(ValueError):
        service.read_file(target.name, max_bytes=MAX_READ_BYTES + 1)

