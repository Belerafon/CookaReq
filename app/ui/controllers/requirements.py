"""Controller handling requirement CRUD operations."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from ...config import ConfigManager
from ...core.model import Requirement
from ...core.repository import FileRequirementRepository, RequirementRepository
from ...i18n import _
from ...log import logger


class RequirementsController:
    """Handle loading and basic CRUD operations for requirements."""

    def __init__(
        self,
        config: ConfigManager,
        model,
        directory: Path,
        repository: RequirementRepository | None = None,
    ) -> None:
        """Initialize controller for given storage ``directory``."""
        self.config = config
        self.model = model
        self.directory = directory
        self.repo = repository or FileRequirementRepository()

    # loading ---------------------------------------------------------
    def load_directory(self) -> dict[int, list[int]]:
        """Load requirements from ``directory`` and return derivation map."""
        self.config.add_recent_dir(self.directory)
        try:
            items = self.repo.load_all(self.directory)
        except Exception as exc:
            logger.warning("Failed to load directory %s: %s", self.directory, exc)
            items = []
        derived_map: dict[str, list[int]] = {}
        for req in items:
            for link in getattr(req, "derived_from", []):
                derived_map.setdefault(link.rid, []).append(req.id)
        self.model.set_requirements(items)
        return derived_map

    # requirement creation -------------------------------------------
    def generate_new_id(self) -> int:
        """Return a free requirement identifier."""

        existing = {req.id for req in self.model.get_all()}
        return max(existing, default=0) + 1

    def add_requirement(self, requirement: Requirement) -> None:
        """Add ``requirement`` to the model."""

        self.model.add(requirement)

    def clone_requirement(self, req_id: int) -> Requirement | None:
        """Return a copy of requirement ``req_id`` with a new id."""

        source = self.model.get_by_id(req_id)
        if not source:
            return None
        new_id = self.generate_new_id()
        clone = replace(
            source,
            id=new_id,
            title=f"{_('(Copy)')} {source.title}".strip(),
            modified_at="",
            revision=1,
        )
        self.model.add(clone)
        return clone

    def delete_requirement(self, req_id: int) -> bool:
        """Delete requirement ``req_id`` from model and storage."""

        req = self.model.get_by_id(req_id)
        if not req:
            return False
        self.model.delete(req_id)
        with suppress(Exception):
            self.repo.delete(self.directory, req.id)
        return True
