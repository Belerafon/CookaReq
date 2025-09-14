"""Tests for RequirementsController."""

from pathlib import Path

import pytest

from app.core.model import (
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
)
from app.ui.controllers.requirements import RequirementsController

pytestmark = pytest.mark.unit


def _req(req_id: int, title: str = "T") -> Requirement:
    """Create a minimal requirement for tests."""
    return Requirement(
        id=req_id,
        title=title,
        statement="S",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="o",
        priority=Priority.MEDIUM,
        source="s",
        verification=Verification.ANALYSIS,
    )


class DummyConfig:
    def __init__(self) -> None:
        self.directories: list[Path] = []

    def add_recent_dir(self, path: Path) -> None:
        self.directories.append(path)


class DummyModel:
    def __init__(self) -> None:
        self.requirements: list[Requirement] = []
        self.added: list[Requirement] = []

    def get_all(self) -> list[Requirement]:
        return self.requirements

    def set_requirements(self, items: list[Requirement]) -> None:
        self.requirements = items

    def get_by_id(self, req_id: int) -> Requirement | None:
        for req in self.requirements:
            if req.id == req_id:
                return req
        return None

    def add(self, req: Requirement) -> None:
        self.added.append(req)
        self.requirements.append(req)


def test_generate_new_id_multiple():
    config = DummyConfig()
    model = DummyModel()
    model.requirements = [_req(1), _req(5), _req(3)]
    controller = RequirementsController(config, model, Path("/tmp"))

    assert controller.generate_new_id() == 6


def test_clone_requirement_missing_source():
    config = DummyConfig()

    class NoAddModel:
        def get_by_id(self, req_id: int):
            return None

        def add(self, req: Requirement) -> None:  # pragma: no cover - should not be called
            raise AssertionError("add should not be called")

    controller = RequirementsController(config, NoAddModel(), Path("/tmp"))

    assert controller.clone_requirement(99) is None


def test_load_directory_repo_exception(monkeypatch):
    config = DummyConfig()
    model = DummyModel()
    model.requirements = [_req(1)]
    controller = RequirementsController(config, model, Path("/tmp"))

    def boom(path: Path):
        raise RuntimeError("boom")

    monkeypatch.setattr(controller.repo, "load_all", boom)

    derived = controller.load_directory()

    assert derived == {}
    assert model.requirements == []
    assert config.directories == [Path("/tmp")]
