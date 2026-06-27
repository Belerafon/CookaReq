"""Shared helpers for trace-index source parsers."""
from __future__ import annotations

import re
from pathlib import Path

RID_RE = re.compile(r"\b[A-Z]+-?0*[0-9]+\b")


def display_path(path: Path, project_root: str | Path | None) -> str:
    """Return ``path`` as project-relative POSIX text when possible."""
    if project_root is None:
        return path.as_posix()
    try:
        return path.resolve().relative_to(Path(project_root).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def iter_block_comments(text: str) -> list[tuple[str, int, int]]:
    """Yield C block comments while skipping string and character literals."""
    comments: list[tuple[str, int, int]] = []
    i = 0
    line = 1
    while i < len(text):
        char = text[i]
        next_char = text[i + 1] if i + 1 < len(text) else ""
        if char in {'"', "'"}:
            i, line = skip_string_or_char(text, i, line)
            continue
        if char == "/" and next_char == "*":
            start_line = line
            start = i
            i += 2
            while i < len(text) - 1 and not (text[i] == "*" and text[i + 1] == "/"):
                if text[i] == "\n":
                    line += 1
                i += 1
            if i < len(text) - 1:
                i += 2
            comments.append((text[start:i], start_line, line))
            continue
        if char == "\n":
            line += 1
        i += 1
    return comments


def skip_string_or_char(text: str, start: int, line: int) -> tuple[int, int]:
    """Skip a C-like string or character literal starting at ``start``."""
    quote = text[start]
    i = start + 1
    while i < len(text):
        if text[i] == "\n":
            line += 1
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == quote:
            return i + 1, line
        i += 1
    return i, line


def rid_list_candidate(raw: str) -> str:
    """Return the RID-list portion before an optional marker note."""
    return raw.split(":", 1)[0].strip().rstrip("*/ ").strip()


def rid_list_is_valid(text: str, rids: tuple[str, ...]) -> bool:
    """Validate that ``text`` contains only the comma-separated RID list."""
    normalized = re.sub(r"\s+", "", text)
    return normalized == ",".join(rids)


def line_for_offset(text: str, offset: int) -> int:
    """Return a 1-based line number for a character offset."""
    return text.count("\n", 0, offset) + 1
