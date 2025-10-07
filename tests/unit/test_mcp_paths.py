from pathlib import Path

from app.mcp.paths import normalize_documents_path, resolve_documents_root


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
