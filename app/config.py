"""Application configuration manager backed by JSON settings."""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence
from typing import Any, ClassVar, Literal, Protocol
import re

import wx

from .columns import default_column_width, sanitize_columns
from .settings import AppSettings, LLMSettings, MCPSettings, UISettings


_FIRST_RUN_COLUMN_PRIORITY: tuple[str, ...] = (
    "id",
    "title",
    "source",
    "status",
    "labels",
)


logger = logging.getLogger(__name__)
_MISSING = object()


_CONFIG_DIRECTORY = Path.home() / ".cookareq"


def _slugify_app_name(app_name: str) -> str:
    """Return filesystem-friendly slug derived from *app_name*."""

    text = app_name.strip().lower()
    if not text:
        return "default"
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return slug or "default"


def _default_config_path(app_name: str) -> Path:
    """Return preferred config path under ~/.cookareq per application name."""

    if app_name == "CookaReq":
        filename = "config.json"
    else:
        filename = f"config-{_slugify_app_name(app_name)}.json"
    return _CONFIG_DIRECTORY / filename



@dataclass(frozen=True)
class FieldBinding:
    """Describe mapping between config field name and Pydantic settings."""

    section: Literal["llm", "mcp", "ui"]
    attribute: str


@dataclass(frozen=True)
class ExportDialogState:
    """Persisted export dialog state for a requirements directory."""

    path: str | None
    format: str | None
    columns: list[str]
    order: list[str]
    empty_fields_placeholder: bool
    docx_formula_renderer: str | None


FIELD_BINDINGS: dict[str, FieldBinding] = {
    "list_columns": FieldBinding("ui", "columns"),
    "recent_dirs": FieldBinding("ui", "recent_dirs"),
    "last_documents": FieldBinding("ui", "last_documents"),
    "auto_open_last": FieldBinding("ui", "auto_open_last"),
    "remember_sort": FieldBinding("ui", "remember_sort"),
    "language": FieldBinding("ui", "language"),
    "mcp_auto_start": FieldBinding("mcp", "auto_start"),
    "mcp_host": FieldBinding("mcp", "host"),
    "mcp_port": FieldBinding("mcp", "port"),
    "mcp_base_path": FieldBinding("mcp", "base_path"),
    "mcp_documents_path": FieldBinding("mcp", "documents_path"),
    "mcp_documents_max_read_kb": FieldBinding("mcp", "documents_max_read_kb"),
    "mcp_log_dir": FieldBinding("mcp", "log_dir"),
    "mcp_require_token": FieldBinding("mcp", "require_token"),
    "mcp_token": FieldBinding("mcp", "token"),
    "llm_base_url": FieldBinding("llm", "base_url"),
    "llm_model": FieldBinding("llm", "model"),
    "llm_format": FieldBinding("llm", "message_format"),
    "llm_api_key": FieldBinding("llm", "api_key"),
    "llm_max_retries": FieldBinding("llm", "max_retries"),
    "llm_max_context_tokens": FieldBinding("llm", "max_context_tokens"),
    "llm_timeout_minutes": FieldBinding("llm", "timeout_minutes"),
    "llm_stream": FieldBinding("llm", "stream"),
    "llm_use_custom_temperature": FieldBinding("llm", "use_custom_temperature"),
    "llm_temperature": FieldBinding("llm", "temperature"),
    "sort_column": FieldBinding("ui", "sort_column"),
    "sort_ascending": FieldBinding("ui", "sort_ascending"),
    "log_level": FieldBinding("ui", "log_level"),
    "log_sash": FieldBinding("ui", "log_sash"),
    "log_shown": FieldBinding("ui", "log_shown"),
    "agent_chat_sash": FieldBinding("ui", "agent_chat_sash"),
    "agent_chat_shown": FieldBinding("ui", "agent_chat_shown"),
    "agent_history_sash": FieldBinding("ui", "agent_history_sash"),
    "agent_confirm_mode": FieldBinding("ui", "agent_confirm_mode"),
    "editor_shown": FieldBinding("ui", "editor_shown"),
    "editor_sash_pos": FieldBinding("ui", "editor_sash_pos"),
    "doc_tree_collapsed": FieldBinding("ui", "doc_tree_collapsed"),
    "sash_pos": FieldBinding("ui", "doc_tree_sash"),
    "win_w": FieldBinding("ui", "window_width"),
    "win_h": FieldBinding("ui", "window_height"),
    "win_x": FieldBinding("ui", "window_x"),
    "win_y": FieldBinding("ui", "window_y"),
    "win_max": FieldBinding("ui", "window_maximized"),
    "det_editor_w": FieldBinding("ui", "detached_editor_width"),
    "det_editor_h": FieldBinding("ui", "detached_editor_height"),
    "det_editor_x": FieldBinding("ui", "detached_editor_x"),
    "det_editor_y": FieldBinding("ui", "detached_editor_y"),
    "det_editor_max": FieldBinding("ui", "detached_editor_maximized"),
}


class ListPanelLike(Protocol):
    """Protocol for panels persisting column layout state."""

    def load_column_widths(self, cfg: ConfigManager) -> None:
        """Restore column widths from *cfg*."""

    def load_column_order(self, cfg: ConfigManager) -> None:
        """Restore column order from *cfg*."""

    def save_column_widths(self, cfg: ConfigManager) -> None:
        """Persist current column widths to *cfg*."""

    def save_column_order(self, cfg: ConfigManager) -> None:
        """Persist current column order to *cfg*."""


class ConfigManager:
    """Wrapper around :class:`AppSettings` with helpers for wx widgets."""

    FIELD_BINDINGS: ClassVar[dict[str, FieldBinding]] = FIELD_BINDINGS

    def __init__(
        self,
        app_name: str = "CookaReq",
        path: Path | str | None = None,
    ) -> None:
        """Initialise configuration manager and load persisted state."""
        if path is not None:
            self._path = Path(path)
        else:
            self._path = _default_config_path(app_name)
        apply_first_run_defaults = not self._path.exists()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._settings = AppSettings()
        self._overrides: dict[str, dict[str, Any]] = {"llm": {}, "mcp": {}, "ui": {}}
        self._raw: dict[str, Any] = {}
        self._load()
        if apply_first_run_defaults:
            self._apply_first_run_defaults()

    # ------------------------------------------------------------------
    # internal helpers
    def _load(self) -> None:
        if self._path.exists():
            try:
                with self._path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - defensive
                logger.warning("Failed to load config %s: %s", self._path, exc)
            else:
                overrides = data.get("settings", {})
                if isinstance(overrides, dict):
                    for section in self._overrides:
                        section_data = overrides.get(section, {})
                        if isinstance(section_data, dict):
                            self._overrides[section] = {
                                key: deepcopy(value)
                                for key, value in section_data.items()
                            }
                raw = data.get("raw", {})
                if isinstance(raw, dict):
                    self._raw = {key: deepcopy(value) for key, value in raw.items()}
        self._rebuild_settings()

    def _apply_first_run_defaults(self) -> None:
        """Populate sensible defaults for a brand new configuration file."""

        columns = self.get_columns()
        order = self._initial_column_order(columns)
        if order:
            self._raw["col_order"] = order
        for index, field in enumerate(self._initial_physical_fields(columns)):
            width = default_column_width(field)
            self._raw[f"col_width_{index}"] = int(width)

        ui_defaults: dict[str, Any] = {
            "agent_chat_shown": False,
            "doc_tree_collapsed": False,
            "sash_pos": 117,
            "editor_sash_pos": 932,
            "editor_shown": True,
            "win_w": 1500,
            "win_h": 1000,
            "win_x": 100,
            "win_y": 50,
            "win_max": False,
            "det_editor_w": 900,
            "det_editor_h": 700,
            "det_editor_x": -1,
            "det_editor_y": -1,
            "det_editor_max": False,
        }
        for key, value in ui_defaults.items():
            self.set_value(key, value)

        self.flush()

    @staticmethod
    def _initial_column_order(columns: Sequence[str]) -> list[str]:
        """Return logical column order for freshly initialised configs."""

        order: list[str] = []
        seen: set[str] = set()
        for field in _FIRST_RUN_COLUMN_PRIORITY:
            if field == "title":
                if field not in seen:
                    order.append(field)
                    seen.add(field)
                continue
            if field in columns and field not in seen:
                order.append(field)
                seen.add(field)
        for field in columns:
            if field not in seen:
                order.append(field)
                seen.add(field)
        return order

    @staticmethod
    def _initial_physical_fields(columns: Sequence[str]) -> list[str]:
        """Return column sequence as instantiated by :class:`RequirementsListCtrl`."""

        fields: list[str] = []
        if "labels" in columns:
            fields.append("labels")
        fields.append("title")
        fields.extend(field for field in columns if field != "labels")
        return fields

    def _rebuild_settings(self) -> None:
        base = AppSettings()
        merged = {
            "llm": base.llm.model_dump(mode="python"),
            "mcp": base.mcp.model_dump(mode="python"),
            "ui": base.ui.model_dump(mode="python"),
        }
        for section, overrides in self._overrides.items():
            merged[section].update(overrides)
        self._settings = AppSettings.model_validate(merged)
        # normalise overrides to validated values
        for section, overrides in self._overrides.items():
            model_section = getattr(self._settings, section)
            self._overrides[section] = {
                key: deepcopy(getattr(model_section, key)) for key in overrides
            }

    def _binding_for(self, name: str) -> FieldBinding | None:
        return self.FIELD_BINDINGS.get(name)

    def _is_overridden(self, binding: FieldBinding) -> bool:
        return binding.attribute in self._overrides[binding.section]

    def _set_override(self, binding: FieldBinding, value: Any) -> None:
        section_overrides = dict(self._overrides[binding.section])
        section_overrides[binding.attribute] = deepcopy(value)
        self._overrides[binding.section] = section_overrides
        self._rebuild_settings()

    def _serialize_overrides(self) -> dict[str, dict[str, Any]]:
        return {
            section: {key: deepcopy(value) for key, value in overrides.items()}
            for section, overrides in self._overrides.items()
        }

    # ------------------------------------------------------------------
    # persistence
    def flush(self) -> None:
        """Persist configuration to disk."""
        payload = {
            "settings": self._serialize_overrides(),
            "raw": {key: deepcopy(value) for key, value in self._raw.items()},
        }
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
        tmp_path.replace(self._path)

    # ------------------------------------------------------------------
    # schema access helpers
    def get_value(self, name: str, default: Any = _MISSING) -> Any:
        """Return configuration value by *name* honouring overrides."""
        binding = self._binding_for(name)
        if binding is not None:
            value = deepcopy(
                getattr(getattr(self._settings, binding.section), binding.attribute)
            )
            if default is not _MISSING and not self._is_overridden(binding):
                return deepcopy(default)
            return value
        if name in self._raw:
            return deepcopy(self._raw[name])
        if default is not _MISSING:
            return deepcopy(default)
        raise KeyError(name)

    def set_value(self, name: str, value: Any) -> None:
        """Set configuration entry *name* to *value*."""
        binding = self._binding_for(name)
        if binding is not None:
            self._set_override(binding, value)
            return
        self._raw[name] = deepcopy(value)

    # ------------------------------------------------------------------
    # columns
    def get_column_width(self, index: int, default: int = -1) -> int:
        """Return persisted width for column *index* or *default* when unset."""
        key = f"col_width_{index}"
        value = self._raw.get(key, _MISSING)
        if value is _MISSING:
            return int(default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    def set_column_width(self, index: int, width: int) -> None:
        """Persist width *width* for column *index*."""
        self._raw[f"col_width_{index}"] = int(width)

    def get_column_order(self) -> list[str]:
        """Return configured ordering of visible columns."""
        raw = self._raw.get("col_order")
        if isinstance(raw, str):
            candidates = raw.split(",")
        elif isinstance(raw, Sequence):
            candidates = list(raw)
        else:
            return []

        columns = self.get_columns()
        allowed_fields = set(columns)
        allowed_fields.add("title")

        normalised: list[str] = []
        seen: set[str] = set()
        for entry in candidates:
            name = str(entry)
            if not name:
                continue
            if name not in allowed_fields:
                continue
            if name in seen:
                continue
            normalised.append(name)
            seen.add(name)

        if "title" not in seen:
            insert_at = 1 if normalised else 0
            normalised.insert(insert_at, "title")
            seen.add("title")
        if "source" in columns and "source" not in seen:
            if "title" in normalised:
                insert_at = normalised.index("title") + 1
            elif "id" in normalised:
                insert_at = normalised.index("id") + 1
            else:
                insert_at = 0
            normalised.insert(insert_at, "source")
            seen.add("source")

        pending_labels = False
        for field in columns:
            if field in seen:
                continue
            if field == "labels":
                pending_labels = True
                continue
            normalised.append(field)
            seen.add(field)

        if pending_labels and "labels" not in seen:
            if "status" in normalised:
                insert_at = normalised.index("status") + 1
            else:
                insert_at = len(normalised)
            normalised.insert(insert_at, "labels")
            seen.add("labels")

        return normalised

    def set_column_order(self, fields: Sequence[str]) -> None:
        """Persist ordering for visible *fields*."""
        self._raw["col_order"] = [str(field) for field in fields]

    def get_columns(self) -> list[str]:
        """Return sanitised list of configured columns."""
        return sanitize_columns(self.get_value("list_columns"))

    def set_columns(self, fields: list[str]) -> None:
        """Persist sanitized *fields* as visible columns and flush to disk."""
        self.set_value("list_columns", sanitize_columns(fields))
        self.flush()

    # ------------------------------------------------------------------
    # recent directories
    def get_recent_dirs(self) -> list[str]:
        """Return history of recently opened directories."""
        return list(self.get_value("recent_dirs"))

    def set_recent_dirs(self, dirs: list[str]) -> None:
        """Persist list of recent directories and flush to disk."""
        self.set_value("recent_dirs", list(dirs))
        self.flush()

    def add_recent_dir(self, path: Path) -> list[str]:
        """Add *path* to the MRU directory list returning the updated value."""
        dirs = self.get_recent_dirs()
        p = str(path)
        if p in dirs:
            dirs.remove(p)
        dirs.insert(0, p)
        del dirs[5:]
        self.set_recent_dirs(dirs)
        return dirs

    def _normalise_directory_key(self, path: Path | str) -> str:
        """Return canonical key for persisting directory-specific state."""
        candidate = Path(path)
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        return str(resolved)

    # ------------------------------------------------------------------
    # export dialog state
    def get_export_dialog_state(self, path: Path | str) -> ExportDialogState | None:
        """Return saved export dialog state for directory *path* if available."""
        raw = self._raw.get("export_dialog_state")
        if not isinstance(raw, dict):
            return None
        key = self._normalise_directory_key(path)
        payload = raw.get(key)
        if not isinstance(payload, dict):
            return None
        path_value = payload.get("path")
        fmt_value = payload.get("format")
        if not isinstance(path_value, str):
            path_value = None
        if not isinstance(fmt_value, str):
            fmt_value = None
        columns = payload.get("columns")
        if not isinstance(columns, list):
            columns_list: list[str] = []
        else:
            columns_list = [str(item) for item in columns if item]
        order = payload.get("order")
        if not isinstance(order, list):
            order_list: list[str] = []
        else:
            order_list = [str(item) for item in order if item]
        empty_fields_placeholder = payload.get("empty_fields_placeholder")
        if not isinstance(empty_fields_placeholder, bool):
            empty_fields_placeholder = False
        docx_formula_renderer = payload.get("docx_formula_renderer")
        if not isinstance(docx_formula_renderer, str):
            docx_formula_renderer = None
        return ExportDialogState(
            path=path_value,
            format=fmt_value,
            columns=columns_list,
            order=order_list,
            empty_fields_placeholder=empty_fields_placeholder,
            docx_formula_renderer=docx_formula_renderer,
        )

    def set_export_dialog_state(self, path: Path | str, state: ExportDialogState) -> None:
        """Persist export dialog state for directory *path* and flush."""
        raw = self._raw.get("export_dialog_state")
        if isinstance(raw, dict):
            export_state = dict(raw)
        else:
            export_state = {}
        key = self._normalise_directory_key(path)
        export_state[key] = {
            "path": state.path,
            "format": state.format,
            "columns": list(state.columns),
            "order": list(state.order),
            "empty_fields_placeholder": state.empty_fields_placeholder,
            "docx_formula_renderer": state.docx_formula_renderer,
        }
        self._raw["export_dialog_state"] = export_state
        self.flush()

    # ------------------------------------------------------------------
    # document persistence
    def get_last_documents(self) -> dict[str, str]:
        """Return mapping of directories to last opened document prefixes."""
        raw = self.get_value("last_documents")
        if not isinstance(raw, dict):
            return {}
        result: dict[str, str] = {}
        for directory, prefix in raw.items():
            if not directory or not prefix:
                continue
            if not isinstance(directory, str) or not isinstance(prefix, str):
                continue
            result[directory] = prefix
        return result

    def get_last_document(self, path: Path | str) -> str | None:
        """Return remembered document prefix for *path* if available."""
        key = self._normalise_directory_key(path)
        return self.get_last_documents().get(key)

    def set_last_document(self, path: Path | str, prefix: str | None) -> None:
        """Persist last opened document *prefix* for directory *path*."""
        key = self._normalise_directory_key(path)
        documents = self.get_last_documents()
        if prefix:
            if documents.get(key) == prefix:
                return
            documents[key] = prefix
        else:
            if key not in documents:
                return
            documents.pop(key, None)
        self.set_value("last_documents", documents)
        self.flush()

    def clear_last_document(self, path: Path | str) -> None:
        """Forget remembered document for directory *path*."""
        self.set_last_document(path, None)

    # ------------------------------------------------------------------
    # flags and language
    def get_auto_open_last(self) -> bool:
        """Return whether the last document should open automatically."""
        return bool(self.get_value("auto_open_last"))

    def set_auto_open_last(self, value: bool) -> None:
        """Persist auto-open preference and flush."""
        self.set_value("auto_open_last", bool(value))
        self.flush()

    def get_remember_sort(self) -> bool:
        """Return whether table sorting should be remembered."""
        return bool(self.get_value("remember_sort"))

    def set_remember_sort(self, value: bool) -> None:
        """Persist remember-sort preference and flush."""
        self.set_value("remember_sort", bool(value))
        self.flush()

    def get_language(self) -> str | None:
        """Return configured UI language code."""
        return self.get_value("language")

    def set_language(self, language: str | None) -> None:
        """Persist UI *language* preference and flush."""
        self.set_value("language", language)
        self.flush()

    # ------------------------------------------------------------------
    # MCP server settings
    def get_mcp_settings(self) -> MCPSettings:
        """Return deep copy of stored MCP configuration."""
        return self._settings.mcp.model_copy(deep=True)

    def set_mcp_settings(self, settings: MCPSettings) -> None:
        """Persist MCP *settings* and rebuild derived state."""
        self._overrides["mcp"] = settings.model_dump(mode="python")
        self._rebuild_settings()
        self.flush()

    # ------------------------------------------------------------------
    # LLM client settings
    def get_llm_settings(self) -> LLMSettings:
        """Return deep copy of stored LLM configuration."""
        return self._settings.llm.model_copy(deep=True)

    def set_llm_settings(self, settings: LLMSettings) -> None:
        """Persist LLM *settings* and rebuild derived state."""
        self._overrides["llm"] = settings.model_dump(mode="python")
        self._rebuild_settings()
        self.flush()

    # ------------------------------------------------------------------
    # composite dataclasses
    def get_ui_settings(self) -> UISettings:
        """Return deep copy of UI settings payload."""
        return self._settings.ui.model_copy(deep=True)

    def set_ui_settings(self, settings: UISettings) -> None:
        """Persist UI *settings* and rebuild derived state."""
        self._overrides["ui"] = settings.model_dump(mode="python")
        self._rebuild_settings()
        self.flush()

    def get_app_settings(self) -> AppSettings:
        """Return deep copy of the composite application settings."""
        return self._settings.model_copy(deep=True)

    def set_app_settings(self, settings: AppSettings) -> None:
        """Persist full *settings* payload splitting it into sub-sections."""
        self.set_llm_settings(settings.llm)
        self.set_mcp_settings(settings.mcp)
        self.set_ui_settings(settings.ui)

    # ------------------------------------------------------------------
    # sort settings
    def get_sort_settings(self) -> tuple[int, bool]:
        """Return stored sort column index and ascending flag."""
        return int(self.get_value("sort_column")), bool(self.get_value("sort_ascending"))

    def set_sort_settings(self, column: int, ascending: bool) -> None:
        """Persist sort configuration for list presentations."""
        self.set_value("sort_column", int(column))
        self.set_value("sort_ascending", bool(ascending))
        self.flush()

    # ------------------------------------------------------------------
    # log console
    def get_log_sash(self, default: int) -> int:
        """Return stored log console sash position with *default* fallback."""
        return int(self.get_value("log_sash", default=default))

    def set_log_sash(self, pos: int) -> None:
        """Persist log console sash position and flush."""
        self.set_value("log_sash", int(pos))
        self.flush()

    def set_log_shown(self, shown: bool) -> None:
        """Persist log console visibility flag."""
        self.set_value("log_shown", bool(shown))
        self.flush()

    def get_log_level(self) -> int:
        """Return configured log level with INFO fallback."""
        level = int(self.get_value("log_level"))
        if level not in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR):
            return logging.INFO
        return level

    def set_log_level(self, level: int) -> None:
        """Persist chosen log *level* and flush."""
        self.set_value("log_level", int(level))
        self.flush()

    def get_agent_chat_shown(self) -> bool:
        """Return whether the agent chat panel is visible."""
        return bool(self.get_value("agent_chat_shown"))

    def set_agent_chat_shown(self, shown: bool) -> None:
        """Persist agent chat visibility flag and flush."""
        self.set_value("agent_chat_shown", bool(shown))
        self.flush()

    def get_agent_chat_sash(self, default: int) -> int:
        """Return stored agent chat sash position with *default* fallback."""
        return int(self.get_value("agent_chat_sash", default=default))

    def set_agent_chat_sash(self, pos: int) -> None:
        """Persist agent chat sash position and flush."""
        self.set_value("agent_chat_sash", int(pos))
        self.flush()

    def get_agent_history_sash(self, default: int) -> int:
        """Return stored agent history sash position with *default* fallback."""
        return int(self.get_value("agent_history_sash", default=default))

    def get_agent_confirm_mode(self) -> str:
        """Return mode controlling confirmation prompts."""
        value = str(self.get_value("agent_confirm_mode", default="prompt"))
        if value not in {"prompt", "never"}:
            return "prompt"
        return value

    def set_agent_history_sash(self, pos: int) -> None:
        """Persist agent history sash position and flush."""
        self.set_value("agent_history_sash", int(pos))
        self.flush()

    def set_agent_confirm_mode(self, mode: str) -> None:
        """Persist confirmation *mode* coercing invalid values to ``"prompt"``."""
        if mode not in {"prompt", "never"}:
            mode = "prompt"
        self.set_value("agent_confirm_mode", mode)
        self.flush()

    # ------------------------------------------------------------------
    # display helpers
    @staticmethod
    def _client_display_areas() -> list[wx.Rect]:
        """Return client rectangles for all detected monitors."""

        areas: list[wx.Rect] = []
        try:
            display_count = wx.Display.GetCount()
        except Exception:  # pragma: no cover - backend quirk
            display_count = 0
        for index in range(display_count):
            try:
                rect = wx.Display(index).GetClientArea()
            except Exception:  # pragma: no cover - backend failure
                continue
            if isinstance(rect, wx.Rect):
                areas.append(rect)
        if not areas:
            x, y, width, height = wx.ClientDisplayRect()
            areas.append(wx.Rect(x, y, width, height))
        return areas

    @staticmethod
    def _normalise_window_geometry(
        width: int,
        height: int,
        x: int,
        y: int,
        *,
        min_size: tuple[int, int],
        max_size: tuple[int, int],
    ) -> tuple[wx.Size, tuple[int, int] | None]:
        """Clamp window rectangle to keep it visible on available displays."""

        min_width, min_height = min_size
        max_width, max_height = max_size
        try:
            numeric_width = int(width)
        except (TypeError, ValueError):
            numeric_width = min_width
        try:
            numeric_height = int(height)
        except (TypeError, ValueError):
            numeric_height = min_height
        clamped_width = max(min_width, min(numeric_width, max_width))
        clamped_height = max(min_height, min(numeric_height, max_height))
        if x == -1 or y == -1:
            return wx.Size(clamped_width, clamped_height), None
        try:
            numeric_x = int(x)
            numeric_y = int(y)
        except (TypeError, ValueError):
            return wx.Size(clamped_width, clamped_height), None
        stored_rect = wx.Rect(numeric_x, numeric_y, clamped_width, clamped_height)
        areas = ConfigManager._client_display_areas()
        target: wx.Rect | None = None
        for area in areas:
            try:
                intersects = stored_rect.Intersects(area)
            except Exception:  # pragma: no cover - wx backend issue
                intersects = False
            if intersects:
                target = area
                break
        if target is None:
            center = wx.Point(
                stored_rect.x + stored_rect.width // 2,
                stored_rect.y + stored_rect.height // 2,
            )
            try:
                display_index = wx.Display.GetFromPoint(center)
            except Exception:  # pragma: no cover - backend quirk
                display_index = wx.NOT_FOUND
            if display_index != wx.NOT_FOUND:
                try:
                    target = wx.Display(display_index).GetClientArea()
                except Exception:  # pragma: no cover - backend quirk
                    target = None
        if target is None:
            target = areas[0]
        usable_width = max(target.width, 1)
        usable_height = max(target.height, 1)
        adjusted_width = min(clamped_width, usable_width)
        adjusted_height = min(clamped_height, usable_height)
        max_x = target.x + max(usable_width - adjusted_width, 0)
        max_y = target.y + max(usable_height - adjusted_height, 0)
        adjusted_x = max(target.x, min(stored_rect.x, max_x))
        adjusted_y = max(target.y, min(stored_rect.y, max_y))
        return wx.Size(adjusted_width, adjusted_height), (adjusted_x, adjusted_y)

    # ------------------------------------------------------------------
    # requirement editor panel
    def get_editor_sash(self, default: int) -> int:
        """Return stored editor sash position with *default* fallback."""
        return int(self.get_value("editor_sash_pos", default=default))

    def set_editor_sash(self, pos: int) -> None:
        """Persist editor sash position and flush."""
        self.set_value("editor_sash_pos", int(pos))
        self.flush()

    def get_editor_shown(self) -> bool:
        """Return whether the editor panel is visible."""
        return bool(self.get_value("editor_shown"))

    def set_editor_shown(self, shown: bool) -> None:
        """Persist editor visibility flag and flush."""
        self.set_value("editor_shown", bool(shown))
        self.flush()

    def get_doc_tree_collapsed(self) -> bool:
        """Return whether the document tree is collapsed."""
        return bool(self.get_value("doc_tree_collapsed"))

    def set_doc_tree_collapsed(self, collapsed: bool) -> None:
        """Persist collapsed state for the document tree and flush."""
        self.set_value("doc_tree_collapsed", bool(collapsed))
        self.flush()

    def get_doc_tree_shown(self) -> bool:
        """Return whether the document tree is currently shown."""
        return not self.get_doc_tree_collapsed()

    def set_doc_tree_shown(self, shown: bool) -> None:
        """Toggle document tree collapsed flag based on *shown*."""
        self.set_doc_tree_collapsed(not shown)

    def get_doc_tree_sash(self, default: int) -> int:
        """Return clamped sash position for the document tree."""
        value = int(self.get_value("sash_pos", default=default))
        return max(value, 0)

    def set_doc_tree_sash(self, pos: int) -> None:
        """Persist document tree sash position and flush."""
        self.set_value("sash_pos", int(pos))
        self.flush()

    # ------------------------------------------------------------------
    # layout helpers
    def restore_layout(
        self,
        frame: wx.Frame,
        doc_splitter: wx.SplitterWindow,
        main_splitter: wx.SplitterWindow,
        panel: ListPanelLike,
        log_console: wx.Window,
        log_menu_item: wx.MenuItem | None = None,
        *,
        editor_splitter: wx.SplitterWindow | None = None,
    ) -> None:
        """Restore persisted window geometry and splitter positions."""
        size, position = self._normalise_window_geometry(
            self.get_value("win_w"),
            self.get_value("win_h"),
            self.get_value("win_x"),
            self.get_value("win_y"),
            min_size=(400, 300),
            max_size=(3000, 2000),
        )
        frame.SetSize(size)
        if position is not None:
            frame.SetPosition(position)
        else:
            frame.Centre()
        frame.SendSizeEvent()
        app = wx.GetApp()
        if app is not None:
            app.ProcessPendingEvents()
        client_size = frame.GetClientSize()
        if client_size.width <= 1 or client_size.height <= 1:
            client_size = wx.Size(size.width, size.height)
        main_splitter.SetSize(client_size)
        doc_splitter.SetSize(client_size)
        doc_min = max(doc_splitter.GetMinimumPaneSize(), 100)
        doc_max = max(client_size.width - doc_min, doc_min)
        stored_doc_sash = int(self.get_value("sash_pos"))
        doc_sash = max(doc_min, min(stored_doc_sash, doc_max))
        doc_splitter.SetSashPosition(doc_sash)
        if editor_splitter is not None and editor_splitter.IsSplit():
            editor_default = editor_splitter.GetSashPosition()
            editor_min = max(editor_splitter.GetMinimumPaneSize(), 100)
            available_width = max(client_size.width - doc_sash, editor_min * 2)
            editor_max = max(available_width - editor_min, editor_min)
            stored_editor_sash = int(
                self.get_value("editor_sash_pos", default=editor_default)
            )
            editor_sash = max(editor_min, min(stored_editor_sash, editor_max))
            editor_splitter.SetSize(wx.Size(available_width, client_size.height))
            editor_splitter.SetSashPosition(editor_sash)
        panel.load_column_widths(self)
        panel.load_column_order(self)
        log_shown = bool(self.get_value("log_shown"))
        log_sash = int(
            self.get_value("log_sash", default=client_size.height - 150)
        )
        if log_shown:
            log_console.Show()
            main_splitter.SplitHorizontally(doc_splitter, log_console, log_sash)
            if log_menu_item:
                log_menu_item.Check(True)
        else:
            main_splitter.Initialize(doc_splitter)
            log_console.Hide()
            if log_menu_item:
                log_menu_item.Check(False)
        if bool(self.get_value("win_max")):
            frame.Maximize(True)

    def save_layout(
        self,
        frame: wx.Frame,
        doc_splitter: wx.SplitterWindow,
        main_splitter: wx.SplitterWindow,
        panel: ListPanelLike,
        *,
        editor_splitter: wx.SplitterWindow | None = None,
        agent_splitter: wx.SplitterWindow | None = None,
        doc_tree_shown: bool | None = None,
        doc_tree_sash: int | None = None,
        agent_chat_shown: bool | None = None,
        agent_chat_sash: int | None = None,
        agent_history_sash: int | None = None,
    ) -> None:
        """Persist current window geometry, splitter positions and column layout."""
        w, h = frame.GetSize()
        x, y = frame.GetPosition()
        self.set_value("win_w", int(w))
        self.set_value("win_h", int(h))
        self.set_value("win_x", int(x))
        self.set_value("win_y", int(y))
        self.set_value("win_max", bool(frame.IsMaximized()))
        sash_to_store = (
            doc_tree_sash
            if doc_tree_sash is not None
            else doc_splitter.GetSashPosition()
        )
        self.set_value("sash_pos", int(sash_to_store))
        if doc_tree_shown is None:
            doc_tree_shown = doc_splitter.IsSplit()
        self.set_doc_tree_shown(bool(doc_tree_shown))
        if editor_splitter is not None:
            if editor_splitter.IsSplit():
                self.set_value("editor_shown", True)
                self.set_value("editor_sash_pos", editor_splitter.GetSashPosition())
            else:
                self.set_value("editor_shown", False)
        if main_splitter.IsSplit():
            self.set_value("log_shown", True)
            self.set_value("log_sash", main_splitter.GetSashPosition())
        else:
            self.set_value("log_shown", False)
        if agent_splitter is not None:
            if agent_chat_shown is None:
                agent_chat_shown = agent_splitter.IsSplit()
            self.set_value("agent_chat_shown", bool(agent_chat_shown))
            if agent_chat_sash is None:
                if agent_chat_shown:
                    agent_chat_sash = agent_splitter.GetSashPosition()
                else:
                    agent_chat_sash = self.get_value("agent_chat_sash")
            if agent_chat_sash is not None:
                self.set_value("agent_chat_sash", int(agent_chat_sash))
        if agent_history_sash is not None:
            self.set_value("agent_history_sash", int(agent_history_sash))
        panel.save_column_widths(self)
        panel.save_column_order(self)
        self.flush()

    def restore_detached_editor_geometry(self, frame: wx.Frame) -> None:
        """Restore persisted geometry for the detached requirement editor."""

        size, position = self._normalise_window_geometry(
            self.get_value("det_editor_w"),
            self.get_value("det_editor_h"),
            self.get_value("det_editor_x"),
            self.get_value("det_editor_y"),
            min_size=(500, 320),
            max_size=(3200, 2400),
        )
        frame.SetSize(size)
        if position is not None:
            frame.SetPosition(position)
        else:
            frame.CentreOnParent()
        if bool(self.get_value("det_editor_max")):
            frame.Maximize(True)

    def save_detached_editor_geometry(self, frame: wx.Frame) -> None:
        """Persist geometry for the detached requirement editor."""

        w, h = frame.GetSize()
        x, y = frame.GetPosition()
        self.set_value("det_editor_w", int(w))
        self.set_value("det_editor_h", int(h))
        self.set_value("det_editor_x", int(x))
        self.set_value("det_editor_y", int(y))
        self.set_value("det_editor_max", bool(frame.IsMaximized()))
