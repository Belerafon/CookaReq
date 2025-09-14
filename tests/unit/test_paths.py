"""Tests for paths."""

from pathlib import Path

import pytest

from app.util.paths import ensure_relative

pytestmark = pytest.mark.unit


def test_ensure_relative_returns_relative(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    file_path = base / "file.txt"
    file_path.write_text("data")

    rel = ensure_relative(file_path, base)
    assert rel == Path("file.txt")


def test_ensure_relative_raises_outside(tmp_path):
    base = tmp_path / "base"
    other = tmp_path / "other"
    base.mkdir()
    other.mkdir()
    outside_file = other / "file.txt"
    outside_file.write_text("data")

    with pytest.raises(ValueError):
        ensure_relative(outside_file, base)
