from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from app.config import ConfigManager
from app.core import store
from app.core.labels import Label
from app.log import logger


class LabelsController:
    """Manage label persistence and synchronization."""

    def __init__(self, config: ConfigManager, model, directory: Path) -> None:
        self.config = config
        self.model = model
        self.directory = directory
        self.labels: List[Label] = []

    def load_labels(self) -> List[Label]:
        self.labels = store.load_labels(self.directory)
        return self.labels

    def sync_labels(self) -> List[str]:
        """Synchronize labels file with labels used by requirements."""
        if not self.directory:
            return []
        existing_colors = {lbl.name: lbl.color for lbl in self.labels}
        used_names = {l for req in self.model.get_all() for l in req.labels}
        all_names = sorted(existing_colors.keys() | used_names)
        self.labels = [Label(name=n, color=existing_colors.get(n, "#ffffff")) for n in all_names]
        try:
            store.save_labels(self.directory, self.labels)
        except Exception as exc:
            logger.warning("Failed to save labels: %s", exc)
        return [lbl.name for lbl in self.labels]

    def update_labels(
        self, new_labels: List[Label], remove_from_requirements: bool
    ) -> Dict[str, List[int]]:
        """Update labels and optionally strip removed ones from requirements.

        Returns a mapping of removed label name -> requirement ids using it.
        When ``remove_from_requirements`` is ``True``, labels are removed from
        requirements and data is saved to disk, and an empty mapping is
        returned.
        """
        old_names = {lbl.name for lbl in self.labels}
        new_names = {lbl.name for lbl in new_labels}
        removed = old_names - new_names
        used: Dict[str, List[int]] = {}
        if removed:
            for lbl in removed:
                ids = [req.id for req in self.model.get_all() if lbl in req.labels]
                if ids:
                    used[lbl] = ids
        if used and not remove_from_requirements:
            return used
        removed_set = set(used) if remove_from_requirements else set()
        if remove_from_requirements:
            for req in self.model.get_all():
                before = list(req.labels)
                req.labels = [l for l in req.labels if l not in removed_set]
                if before != req.labels:
                    try:
                        store.save(self.directory, req)
                    except Exception as exc:
                        logger.warning("Failed to save %s: %s", req.id, exc)
        self.labels = new_labels
        try:
            store.save_labels(self.directory, self.labels)
        except Exception as exc:
            logger.warning("Failed to save labels: %s", exc)
        return {}

    def get_label_names(self) -> List[str]:
        return [lbl.name for lbl in self.labels]
