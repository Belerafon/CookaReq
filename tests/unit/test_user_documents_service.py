from __future__ import annotations

from pathlib import Path

import pytest

from app.llm.tokenizer import count_text_tokens
from app.services.user_documents import (
    DEFAULT_MAX_READ_BYTES,
    LARGE_FILE_TOKEN_ESTIMATE_BYTES,
    MAX_ALLOWED_READ_BYTES,
    TOKEN_COUNT_SAMPLE_BYTES,
    UserDocumentsService,
)


def create_service(
    tmp_path: Path,
    *,
    model: str | None = None,
    max_read_bytes: int = DEFAULT_MAX_READ_BYTES,
) -> UserDocumentsService:
    root = tmp_path / "docs"
    root.mkdir()
    return UserDocumentsService(
        root,
        max_context_tokens=100,
        token_model=model,
        max_read_bytes=max_read_bytes,
    )


def test_list_tree_reports_tokens_and_percentages(tmp_path: Path) -> None:
    service = create_service(tmp_path)
    (service.root / "guide").mkdir()
    (service.root / "guide" / "intro.txt").write_text("hello world", encoding="utf-8")
    (service.root / "guide" / "details.md").write_text("line one\nline two\n", encoding="utf-8")
    (service.root / "notes.txt").write_text("alpha beta gamma", encoding="utf-8")

    payload = service.list_tree()

    assert payload["root"] == str(service.root)
    assert payload["max_context_tokens"] == 100
    assert payload["max_read_bytes"] == service.max_read_bytes
    assert payload["max_read_kib"] == service.max_read_bytes // 1024
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
        service.read_file(target.name, max_bytes=service.max_read_bytes + 1)


def test_custom_max_read_bytes_respected(tmp_path: Path) -> None:
    limit = 32 * 1024
    service = create_service(tmp_path, max_read_bytes=limit)
    payload = service.list_tree()
    assert payload["max_read_bytes"] == limit
    sample = service.create_file("info.txt", content="data")
    with pytest.raises(ValueError):
        service.read_file(sample.name, max_bytes=limit + 1)


def test_max_read_bytes_upper_bound_enforced(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    with pytest.raises(ValueError):
        UserDocumentsService(
            root,
            max_context_tokens=100,
            max_read_bytes=MAX_ALLOWED_READ_BYTES + 1,
        )


def test_handles_unicode_and_space_paths(tmp_path: Path) -> None:
    service = create_service(tmp_path)
    service.create_file("ТЗ/План работ.txt", content="первая строка\nвторая строка")
    service.create_file("аналитика/отчёт итоговый.md", content="# Раздел")

    payload = service.list_tree()
    tree_text = payload["tree_text"]
    assert "ТЗ" in tree_text
    assert "План работ.txt" in tree_text
    assert "аналитика" in tree_text
    assert "отчёт итоговый.md" in tree_text

    chunk = service.read_file("ТЗ/План работ.txt", max_bytes=128)
    assert "первая строка" in chunk["content"]
    assert chunk["path"] == "ТЗ/План работ.txt"


def test_large_files_use_sampling_heuristic(tmp_path: Path) -> None:
    service = create_service(tmp_path)
    block = ("sample text for estimation " * 16) + "\n"
    repeats = (LARGE_FILE_TOKEN_ESTIMATE_BYTES // len(block)) + 20
    content = block * repeats
    target = service.create_file("bulk/huge.txt", content=content)

    payload = service.list_tree()
    bulk_dir = next(item for item in payload["entries"] if item["name"] == "bulk")
    huge_entry = next(item for item in bulk_dir["children"] if item["name"] == "huge.txt")

    token_meta = huge_entry["token_count"]
    assert token_meta["approximate"] is True
    assert "sampled_heuristic" in token_meta["reason"]

    size = target.stat().st_size
    with target.open("rb") as stream:
        sample = stream.read(TOKEN_COUNT_SAMPLE_BYTES)
    sample_tokens = count_text_tokens(sample.decode("utf-8", errors="replace"))
    assert sample_tokens.tokens is not None
    expected = int(round(sample_tokens.tokens * (size / len(sample))))
    assert token_meta["tokens"] == expected

