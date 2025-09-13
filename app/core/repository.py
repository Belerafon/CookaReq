from __future__ import annotations

"""Requirement repository interface and implementations."""

from pathlib import Path
from typing import Mapping, Protocol, Sequence

from .model import Requirement
from . import requirements as req_ops


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
    ) -> Path:
        """Persist requirement data in *directory* and return resulting path."""

    def delete(self, directory: str | Path, req_id: int) -> None:
        """Remove requirement ``req_id`` from *directory*."""


class FileRequirementRepository(RequirementRepository):
    """Filesystem-backed requirement repository."""

    def load_all(self, directory: str | Path) -> list[Requirement]:  # type: ignore[override]
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
        return req_ops.search_requirements(
            directory, query=query, labels=labels, fields=fields, status=status
        )

    def load(self, directory: str | Path, req_id: int) -> tuple[dict, float]:  # type: ignore[override]
        return req_ops.load_requirement(directory, req_id)

    def get(self, directory: str | Path, req_id: int) -> Requirement:  # type: ignore[override]
        return req_ops.get_requirement(directory, req_id)

    def save(
        self,
        directory: str | Path,
        data: Mapping | Requirement,
        *,
        mtime: float | None = None,
    ) -> Path:  # type: ignore[override]
        return req_ops.save_requirement(directory, data, mtime=mtime)

    def delete(self, directory: str | Path, req_id: int) -> None:  # type: ignore[override]
        req_ops.delete_requirement(directory, req_id)
