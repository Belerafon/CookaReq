"""Tests for labels."""

from app.core.labels import Label, add_label, get_label, update_label, delete_label
from app.core import label_store
from app.core.label_repository import FileLabelRepository
from pathlib import Path
import pytest

pytestmark = pytest.mark.unit


def test_label_crud_operations(tmp_path: Path) -> None:
    labels: list[Label] = []
    lbl = Label("ui", "#ff0000")
    add_label(labels, lbl)
    assert get_label(labels, "ui") == lbl
    update_label(labels, Label("ui", "#00ff00"))
    assert get_label(labels, "ui").color == "#00ff00"
    delete_label(labels, "ui")
    assert get_label(labels, "ui") is None


def test_store_load_save_labels(tmp_path: Path) -> None:
    labels = [Label("ui", "#ff0000"), Label("backend", "#00ff00")]
    label_store.save_labels(tmp_path, labels)
    loaded = label_store.load_labels(tmp_path)
    assert loaded == labels


def test_file_label_repository_roundtrip(tmp_path: Path) -> None:
    repo = FileLabelRepository()
    labels = [Label("ui", "#ff0000"), Label("backend", "#00ff00")]
    repo.save(tmp_path, labels)
    loaded = repo.load(tmp_path)
    assert loaded == labels
