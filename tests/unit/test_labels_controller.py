"""Tests for LabelsController."""

from dataclasses import dataclass
from pathlib import Path

import pytest

import app.ui.controllers.labels as labels_mod
from app.core.labels import Label
from app.ui.controllers.labels import LabelsController

pytestmark = pytest.mark.unit


@dataclass
class DummyReq:
    id: int
    labels: list[str]


class DummyModel:
    def __init__(self) -> None:
        self.items: list[DummyReq] = []

    def get_all(self) -> list[DummyReq]:
        return self.items


class DummyConfig:
    pass


class SpyRepo:
    """Simple label repository for tests."""

    def __init__(self) -> None:
        self.loaded_path: Path | None = None
        self.saved_labels: list[Label] | None = None

    def load(self, directory: Path) -> list[Label]:
        self.loaded_path = directory
        return [Label("x", "#111111")]

    def save(self, directory: Path, labels: list[Label]) -> Path:
        self.saved_labels = labels
        return directory / "labels.json"


class FailingRepo(SpyRepo):
    def save(self, directory: Path, labels: list[Label]) -> Path:  # type: ignore[override]
        raise RuntimeError("fail")


# ---------------------------------------------------------------------------
# load_labels
# ---------------------------------------------------------------------------

def test_load_labels_with_repo(tmp_path: Path) -> None:
    repo = SpyRepo()
    controller = LabelsController(DummyConfig(), DummyModel(), tmp_path, repo)

    labels = controller.load_labels()

    assert labels == [Label("x", "#111111")]
    assert controller.labels == labels
    assert repo.loaded_path == tmp_path


# ---------------------------------------------------------------------------
# sync_labels
# ---------------------------------------------------------------------------

def test_sync_labels_save_failure_logs(monkeypatch, tmp_path: Path) -> None:
    model = DummyModel()
    model.items = [DummyReq(1, ["foo"]), DummyReq(2, ["bar"])]
    repo = FailingRepo()
    controller = LabelsController(DummyConfig(), model, tmp_path, repo)
    controller.labels = [Label("foo", "#aaaaaa")]

    calls: list[str] = []

    def fake_warning(msg, *args):
        calls.append(msg % args)

    monkeypatch.setattr(labels_mod.logger, "warning", fake_warning)

    names = controller.sync_labels()

    assert names == ["bar", "foo"]
    assert calls and "Failed to save labels" in calls[0]


# ---------------------------------------------------------------------------
# update_labels
# ---------------------------------------------------------------------------

def test_update_labels_without_removal(tmp_path: Path) -> None:
    model = DummyModel()
    model.items = [DummyReq(1, ["a"]), DummyReq(2, ["a", "b"])]
    repo = SpyRepo()
    controller = LabelsController(DummyConfig(), model, tmp_path, repo)
    controller.labels = [Label("a", "#1"), Label("b", "#2")]

    result = controller.update_labels([Label("b", "#2")], remove_from_requirements=False)

    assert result == {"a": [1, 2]}
    assert controller.labels[0].name == "a"  # unchanged
    assert repo.saved_labels is None
    assert model.items[0].labels == ["a"]
    assert model.items[1].labels == ["a", "b"]


def test_update_labels_with_removal(monkeypatch, tmp_path: Path) -> None:
    model = DummyModel()
    model.items = [DummyReq(1, ["a", "b"]), DummyReq(2, ["b"]), DummyReq(3, ["a"])]
    repo = SpyRepo()
    controller = LabelsController(DummyConfig(), model, tmp_path, repo)
    controller.labels = [Label("a", "#1"), Label("b", "#2")]

    saved: list[int] = []

    def fake_save_requirement(directory: Path, req: DummyReq, **_: object):
        saved.append(req.id)
        return directory / f"{req.id}.json"

    monkeypatch.setattr(labels_mod.req_ops, "save_requirement", fake_save_requirement)

    result = controller.update_labels([Label("b", "#2")], remove_from_requirements=True)

    assert result == {}
    assert repo.saved_labels == [Label("b", "#2")]
    assert model.items[0].labels == ["b"]
    assert model.items[1].labels == ["b"]
    assert model.items[2].labels == []
    assert saved == [1, 3]
