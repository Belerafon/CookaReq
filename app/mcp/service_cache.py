"""Service cache primitives for MCP requirement storage access."""

from __future__ import annotations

import threading
from pathlib import Path

from ..services.requirements import RequirementsService


class RequirementsServiceCache:
    """Thread-safe cache of :class:`RequirementsService` per base directory."""

    def __init__(self) -> None:
        """Initialize empty cache and lock protecting service instances."""
        self._lock = threading.RLock()
        self._services: dict[Path, RequirementsService] = {}
        self._active_base: Path | None = None

    @staticmethod
    def _normalize(base_path: str | Path) -> Path:
        path = Path(base_path or ".").expanduser()
        return path.resolve()

    def activate(self, base_path: str | Path) -> None:
        """Switch the cache to *base_path* dropping stale entries when needed."""
        target = self._normalize(base_path)
        with self._lock:
            if self._active_base != target:
                self._services.clear()
                self._active_base = target

    def deactivate(self) -> None:
        """Clear all cached services and forget the active base path."""
        with self._lock:
            self._services.clear()
            self._active_base = None

    def get(self, base_path: str | Path) -> RequirementsService:
        """Return a cached service for *base_path* creating it on demand."""
        target = self._normalize(base_path)
        with self._lock:
            service = self._services.get(target)
            if service is None:
                service = RequirementsService(target)
                self._services[target] = service
            return service
