"""Tests for OS file-opening command helpers."""

from pathlib import Path

from app.util import system_open


def test_reveal_in_file_manager_uses_explorer_select_on_windows(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    target = tmp_path / "file.txt"
    target.write_text("data", encoding="utf-8")
    monkeypatch.setattr(system_open.sys, "platform", "win32")
    monkeypatch.setattr(system_open.subprocess, "Popen", lambda args: calls.append(args))

    assert system_open.reveal_in_file_manager(target) is True

    assert calls == [["explorer", "/select,", str(target.resolve())]]


def test_reveal_in_file_manager_opens_parent_on_linux(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    target = tmp_path / "file.txt"
    target.write_text("data", encoding="utf-8")
    monkeypatch.setattr(system_open.sys, "platform", "linux")
    monkeypatch.setattr(system_open.subprocess, "call", lambda args: calls.append(args) or 0)

    assert system_open.reveal_in_file_manager(target) is True

    assert calls == [["xdg-open", str(tmp_path.resolve())]]
