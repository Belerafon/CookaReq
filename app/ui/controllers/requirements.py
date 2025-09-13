from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Dict

from app.i18n import _

from app.config import ConfigManager
from app.core import requirements as req_ops
from app.core.model import Requirement
from app.log import logger


class RequirementsController:
    """Handle loading and basic CRUD operations for requirements."""

    def __init__(self, config: ConfigManager, model, directory: Path) -> None:
        self.config = config
        self.model = model
        self.directory = directory

    # loading ---------------------------------------------------------
    def load_directory(self) -> Dict[int, list[int]]:
        """Load requirements from ``directory`` and return derivation map."""
        self.config.add_recent_dir(self.directory)
        try:
            items = req_ops.load_all(self.directory)
        except Exception as exc:
            logger.warning("Failed to load directory %s: %s", self.directory, exc)
            items = []
        derived_map: Dict[int, list[int]] = {}
        for req in items:
            for link in getattr(req, "derived_from", []):
                derived_map.setdefault(link.source_id, []).append(req.id)
        self.model.set_requirements(items)
        return derived_map

    # requirement creation -------------------------------------------
    def generate_new_id(self) -> int:
        existing = {req.id for req in self.model.get_all()}
        return max(existing, default=0) + 1

    def add_requirement(self, requirement: Requirement) -> None:
        self.model.add(requirement)

    def clone_requirement(self, req_id: int) -> Requirement | None:
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
        req = self.model.get_by_id(req_id)
        if not req:
            return False
        self.model.delete(req_id)
        try:
            req_ops.delete_requirement(self.directory, req.id)
        except Exception:
            pass
        return True
