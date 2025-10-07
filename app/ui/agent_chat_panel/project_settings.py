"""Persistence helpers for project-scoped agent settings."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Mapping


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentProjectSettings:
    """Immutable container with project-specific agent options."""

    custom_system_prompt: str = ""

    def normalized(self) -> AgentProjectSettings:
        """Return settings with whitespace-normalised fields."""

        return AgentProjectSettings(
            custom_system_prompt=self.custom_system_prompt.strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise settings into a JSON-compatible mapping."""

        normalized = self.normalized()
        return {
            "version": 3,
            "custom_system_prompt": normalized.custom_system_prompt,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AgentProjectSettings:
        """Create :class:`AgentProjectSettings` from *payload* data."""

        prompt = payload.get("custom_system_prompt", "")
        if not isinstance(prompt, str):
            prompt = ""
        return cls(custom_system_prompt=prompt.strip())


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

