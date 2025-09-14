"""Controller for label persistence and synchronization."""

from __future__ import annotations

from pathlib import Path

from ...config import ConfigManager
from ...core import requirements as req_ops
from ...core.label_repository import FileLabelRepository, LabelRepository
from ...core.labels import Label
from ...log import logger


class LabelsController:
    """Manage label persistence and synchronization."""

    def __init__(
        self,
        config: ConfigManager,
        model,
        directory: Path,
        repository: LabelRepository | None = None,
    ) -> None:
        """Initialize controller with storage ``directory`` and model."""
        self.config = config
        self.model = model
        self.directory = directory
        self.repo = repository or FileLabelRepository()
        self.labels: list[Label] = []

    def load_labels(self) -> list[Label]:
        """Load labels from configured repository."""

        self.labels = req_ops.load_labels(self.directory, repo=self.repo)
        return self.labels

    def sync_labels(self) -> list[str]:
        """Synchronize labels file with labels used by requirements."""
        if not self.directory:
            return []
        existing_colors = {lbl.name: lbl.color for lbl in self.labels}
        used_names = {label for req in self.model.get_all() for label in req.labels}
        all_names = sorted(existing_colors.keys() | used_names)
        self.labels = [
            Label(name=name, color=existing_colors.get(name, "#ffffff"))
            for name in all_names
        ]
        try:
            req_ops.save_labels(self.directory, self.labels, repo=self.repo)
        except Exception as exc:
            logger.warning("Failed to save labels: %s", exc)
        return [lbl.name for lbl in self.labels]

    def update_labels(
        self,
        new_labels: list[Label],
        remove_from_requirements: bool,
    ) -> dict[str, list[int]]:
        """Update labels and optionally strip removed ones from requirements.

        Returns a mapping of removed label name -> requirement ids using it.
        When ``remove_from_requirements`` is ``True``, labels are removed from
        requirements and data is saved to disk, and an empty mapping is
        returned.
        """
        old_names = {lbl.name for lbl in self.labels}
        new_names = {lbl.name for lbl in new_labels}
        removed = old_names - new_names
        used: dict[str, list[int]] = {}
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
                req.labels = [label for label in req.labels if label not in removed_set]
                if before != req.labels:
                    try:
                        req_ops.save_requirement(self.directory, req)
                    except Exception as exc:
                        logger.warning("Failed to save %s: %s", req.id, exc)
        self.labels = new_labels
        try:
            req_ops.save_labels(self.directory, self.labels, repo=self.repo)
        except Exception as exc:
            logger.warning("Failed to save labels: %s", exc)
        return {}

    def get_label_names(self) -> list[str]:
        """Return list of current label names."""

        return [lbl.name for lbl in self.labels]
