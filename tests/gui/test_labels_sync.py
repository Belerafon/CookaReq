"""Tests for labels sync."""

import pytest
from app.core import store, label_store
from app.core.labels import PRESET_SETS

pytestmark = pytest.mark.gui


def _create_requirement(directory):
    data = {
        "id": 1,
        "title": "Title",
        "statement": "Statement",
        "type": "requirement",
        "status": "draft",
        "owner": "user",
        "priority": "medium",
        "source": "spec",
        "verification": "analysis",
        "labels": ["ui"],
        "revision": 1,
    }
    store.save(directory, data)


def test_sync_labels_preserves_unused(monkeypatch, tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    label_store.save_labels(tmp_path, PRESET_SETS["basic"])
    _create_requirement(tmp_path)
    from app.ui.main_frame import MainFrame
    frame = MainFrame(None)
    frame._load_directory(tmp_path)
    assert {l.name for l in frame.labels} == {l.name for l in PRESET_SETS["basic"]}
    frame.Destroy()
