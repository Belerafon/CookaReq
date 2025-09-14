"""Requirement repository interface and implementations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from . import requirements as req_ops
from .model import Requirement


class RequirementRepository(Protocol):
    """Abstract persistence operations for requirements."""

    def load_all(self, directory: str | Path) -> list[Requirement]:
        """Load all requirements from *directory*."""

    def search(
        self,
        directory: str | Path,
        *,
        query: str | None = None,
        labels: Sequence[str] | None = None,
        fields: Sequence[str] | None = None,
        status: str | None = None,
    ) -> list[Requirement]:
        """Search requirements in *directory* using optional filters."""

    def load(self, directory: str | Path, req_id: int) -> tuple[dict, float]:
        """Return raw requirement data and modification time."""

    def get(self, directory: str | Path, req_id: int) -> Requirement:
        """Return :class:`Requirement` by ``req_id``."""

    def save(
        self,
        directory: str | Path,
        data: Mapping | Requirement,
        *,
        mtime: float | None = None,
        modified_at: str | None = None,
    ) -> Path:
        """Persist requirement data in *directory* and return resulting path."""

    def delete(self, directory: str | Path, req_id: int) -> None:
        """Remove requirement ``req_id`` from *directory*."""


class FileRequirementRepository(RequirementRepository):
    """Filesystem-backed requirement repository."""

    def load_all(self, directory: str | Path) -> list[Requirement]:  # type: ignore[override]
        """Load all requirements from ``directory``."""

        return req_ops.load_all(directory)

    def search(
        self,
        directory: str | Path,
        *,
        query: str | None = None,
        labels: Sequence[str] | None = None,
        fields: Sequence[str] | None = None,
        status: str | None = None,
    ) -> list[Requirement]:  # type: ignore[override]
        """Search requirements in ``directory`` with optional filters."""

        return req_ops.search_requirements(
            directory, query=query, labels=labels, fields=fields, status=status
        )

    def load(self, directory: str | Path, req_id: int) -> tuple[dict, float]:  # type: ignore[override]
        """Load raw requirement data and mtime for ``req_id``."""

        return req_ops.load_requirement(directory, req_id)

    def get(self, directory: str | Path, req_id: int) -> Requirement:  # type: ignore[override]
        """Return :class:`Requirement` identified by ``req_id``."""

        return req_ops.get_requirement(directory, req_id)

    def save(
        self,
        directory: str | Path,
        data: Mapping | Requirement,
        *,
        mtime: float | None = None,
        modified_at: str | None = None,
    ) -> Path:  # type: ignore[override]
        """Persist requirement ``data`` to ``directory`` and return path."""

        return req_ops.save_requirement(
            directory, data, mtime=mtime, modified_at=modified_at
        )

    def delete(self, directory: str | Path, req_id: int) -> None:  # type: ignore[override]
        """Remove requirement ``req_id`` from ``directory``."""

        req_ops.delete_requirement(directory, req_id)
