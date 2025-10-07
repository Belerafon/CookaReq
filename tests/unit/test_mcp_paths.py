from pathlib import Path

from app.mcp.paths import (
    describe_documents_root,
    normalize_documents_path,
    resolve_documents_root,
)


def test_normalize_documents_path_handles_various_inputs(tmp_path):
    assert normalize_documents_path("  docs  ") == "docs"
    assert normalize_documents_path(None) == ""
    assert normalize_documents_path(tmp_path / "manuals") == str(tmp_path / "manuals")


def test_resolve_documents_root_with_relative_path(tmp_path):
    root = resolve_documents_root(tmp_path, "share")
    assert root == (Path(tmp_path) / "share").resolve()


def test_resolve_documents_root_with_absolute_path(tmp_path):
    absolute = (tmp_path / "manuals").resolve()
    result = resolve_documents_root(tmp_path / "ignored", absolute)
    assert result == absolute


def test_resolve_documents_root_without_base(tmp_path):
    assert resolve_documents_root(None, "docs") is None
    assert resolve_documents_root("", "docs") is None


def test_describe_documents_root_relative_and_absolute(tmp_path):
    relative = describe_documents_root(tmp_path, "./manuals")
    assert relative.status == "resolved"
    assert relative.is_relative
    assert relative.input_path == "./manuals"
    assert relative.resolved == (Path(tmp_path) / "manuals").resolve()

    absolute_target = (tmp_path / "absdocs").resolve()
    absolute = describe_documents_root(tmp_path / "ignored", absolute_target)
    assert absolute.status == "resolved"
    assert not absolute.is_relative
    assert absolute.input_path == str(absolute_target)
    assert absolute.resolved == absolute_target


def test_describe_documents_root_missing_base():
    info = describe_documents_root("", "./docs")
    assert info.status == "missing_base"
    assert info.is_relative
