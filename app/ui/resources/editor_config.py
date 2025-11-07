"""Load requirement editor resources from JSON."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any
from collections.abc import Iterable

from ...i18n import translate_resource


def _ensure_segments(value: Any) -> tuple[str, ...]:
    """Normalize help text segments from resource data."""
    if isinstance(value, str):
        segments = (value,)
    elif isinstance(value, Iterable):
        segments = tuple(str(part) for part in value)
    else:
        raise TypeError("Help text must be a string or an iterable of strings")
    if not segments or any(part == "" for part in segments):
        raise ValueError("Help text entries must contain non-empty strings")
    return segments


@dataclass(frozen=True)
class EditorFieldSpec:
    """Description of a single field in the requirement editor."""

    name: str
    help: tuple[str, ...]
    control: str = "text"
    multiline: bool = False
    hint: str | None = None

    def __post_init__(self) -> None:
        if self.control not in {"text", "enum"}:
            raise ValueError(f"Unsupported control type '{self.control}' for field '{self.name}'")
        if not self.help:
            raise ValueError(f"Field '{self.name}' must define help text")

    def localized_help(self) -> str:
        """Return localized help text for this field."""
        return translate_resource(self.help)


@dataclass(frozen=True)
class EditorResource:
    """Collection of editor field specifications and auxiliary help strings."""

    text_fields: tuple[EditorFieldSpec, ...]
    grid_fields: tuple[EditorFieldSpec, ...]
    extra_help: dict[str, tuple[str, ...]]
    _help_map: dict[str, tuple[str, ...]] = field(init=False, repr=False)
    _field_names: tuple[str, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        help_map: dict[str, tuple[str, ...]] = {}
        for spec in (*self.text_fields, *self.grid_fields):
            if spec.name in help_map:
                raise ValueError(f"Duplicate field entry '{spec.name}' in editor resource")
            help_map[spec.name] = spec.help
        for key, value in self.extra_help.items():
            if key in help_map:
                raise ValueError(f"Duplicate help entry '{key}' in editor resource")
            help_map[key] = value
        object.__setattr__(self, "_help_map", help_map)
        object.__setattr__(
            self,
            "_field_names",
            tuple(spec.name for spec in (*self.text_fields, *self.grid_fields)),
        )

    @property
    def field_names(self) -> tuple[str, ...]:
        """Return the ordered list of field names used in the editor."""
        return self._field_names

    def help_text(self, name: str) -> str:
        """Return localized help text for ``name``."""
        try:
            segments = self._help_map[name]
        except KeyError as exc:  # pragma: no cover - defensive branch
            raise KeyError(f"Unknown help entry '{name}'") from exc
        return translate_resource(segments)

    def localized_help(self) -> dict[str, str]:
        """Return localized help texts for all known entries."""
        return {name: translate_resource(segments) for name, segments in self._help_map.items()}


def _load_field_spec(data: dict[str, Any]) -> EditorFieldSpec:
    if not isinstance(data, dict):
        raise TypeError("Field specification must be a mapping")
    try:
        name = data["name"]
        help_value = data["help"]
    except KeyError as exc:  # pragma: no cover - configuration errors are fatal
        raise KeyError(f"Missing required key {exc!s} in field specification") from exc
    hint = data.get("hint")
    if hint is not None and not isinstance(hint, str):
        raise TypeError(f"Hint for field '{name}' must be a string if provided")
    control = data.get("control", "text")
    multiline = bool(data.get("multiline", False))
    return EditorFieldSpec(
        name=name,
        help=_ensure_segments(help_value),
        control=control,
        multiline=multiline,
        hint=hint,
    )


def _load_extra_help(data: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(data, dict):
        raise TypeError("Extra help section must be a mapping")
    extra: dict[str, tuple[str, ...]] = {}
    for key, value in data.items():
        extra[key] = _ensure_segments(value)
    return extra


@cache
def load_editor_config() -> EditorResource:
    """Load requirement editor configuration from the JSON resource."""
    # First try to load from the regular location
    path = Path(__file__).with_name("editor_fields.json")
    
    # If not found and we're in a PyInstaller bundle, try the _MEIPASS directory
    if not path.exists() and getattr(sys, 'frozen', False):
        # When running in a PyInstaller bundle
        bundle_dir = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        path = bundle_dir / "app" / "ui" / "resources" / "editor_fields.json"
        
        # If still not found, try the parent directory of the executable
        if not path.exists():
            exe_dir = Path(sys.executable).parent
            path = exe_dir / "app" / "ui" / "resources" / "editor_fields.json"
    
    try:
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Could not find editor_fields.json in any of the expected locations. Tried: {path}") from e
        
    if not isinstance(payload, dict):
        raise TypeError("Editor resource must be a mapping")
        
    text_fields = tuple(_load_field_spec(entry) for entry in payload.get("text_fields", []))
    grid_fields = tuple(_load_field_spec(entry) for entry in payload.get("grid_fields", []))
    extra_help = _load_extra_help(payload.get("extra_help", {}))
    return EditorResource(text_fields=text_fields, grid_fields=grid_fields, extra_help=extra_help)
