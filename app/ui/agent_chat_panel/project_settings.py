"""Persistence helpers for project-scoped agent settings."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Mapping


logger = logging.getLogger(__name__)


def _normalize_documents_path(value: str) -> str:
    """Return normalised representation of *value* suitable for persistence."""

    text = value.strip()
    if not text:
        return ""
    try:
        normalized = Path(text).expanduser()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to normalise documents path %s: %s", value, exc)
        return text
    return str(normalized)


@dataclass(frozen=True, slots=True)
class AgentProjectSettings:
    """Immutable container with project-specific agent options."""

    custom_system_prompt: str = ""
    documents_path: str = ""

    def normalized(self) -> AgentProjectSettings:
        """Return settings with whitespace-normalised fields."""

        return AgentProjectSettings(
            custom_system_prompt=self.custom_system_prompt.strip(),
            documents_path=_normalize_documents_path(self.documents_path),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise settings into a JSON-compatible mapping."""

        normalized = self.normalized()
        return {
            "version": 2,
            "custom_system_prompt": normalized.custom_system_prompt,
            "documents_path": normalized.documents_path,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AgentProjectSettings:
        """Create :class:`AgentProjectSettings` from *payload* data."""

        prompt = payload.get("custom_system_prompt", "")
        if not isinstance(prompt, str):
            prompt = ""

        documents_path = payload.get("documents_path", "")
        if not isinstance(documents_path, str):
            documents_path = ""

        return cls(
            custom_system_prompt=prompt.strip(),
            documents_path=_normalize_documents_path(documents_path),
        )


def load_agent_project_settings(path: Path) -> AgentProjectSettings:
    """Load project settings from *path* returning defaults on failure."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return AgentProjectSettings()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to load agent settings %s: %s", path, exc)
        return AgentProjectSettings()

    if not isinstance(raw, Mapping):
        return AgentProjectSettings()

    return AgentProjectSettings.from_dict(raw)


def save_agent_project_settings(path: Path, settings: AgentProjectSettings) -> None:
    """Persist *settings* to *path* using a temporary file."""

    payload = settings.to_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


__all__ = [
    "AgentProjectSettings",
    "load_agent_project_settings",
    "save_agent_project_settings",
]

