"""Application configuration manager backed by JSON settings."""

from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal, Protocol

import wx

from .settings import (
    AppSettings,
    LLMSettings,
    MCPSettings,
    UISettings,
    DEFAULT_LIST_COLUMNS as SETTINGS_DEFAULT_LIST_COLUMNS,
)


logger = logging.getLogger(__name__)
_MISSING = object()


def _default_config_path(app_name: str) -> Path:
    """Return platform-appropriate config path for *app_name*."""

    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        root = Path(base)
    else:
        root = Path.home() / ".config"
    return root / app_name / "config.json"


@dataclass(frozen=True)
class FieldBinding:
    """Describe mapping between config field name and Pydantic settings."""

    section: Literal["llm", "mcp", "ui"]
    attribute: str


FIELD_BINDINGS: dict[str, FieldBinding] = {
    "list_columns": FieldBinding("ui", "columns"),
    "recent_dirs": FieldBinding("ui", "recent_dirs"),
    "auto_open_last": FieldBinding("ui", "auto_open_last"),
    "remember_sort": FieldBinding("ui", "remember_sort"),
    "language": FieldBinding("ui", "language"),
    "mcp_auto_start": FieldBinding("mcp", "auto_start"),
    "mcp_host": FieldBinding("mcp", "host"),
    "mcp_port": FieldBinding("mcp", "port"),
    "mcp_base_path": FieldBinding("mcp", "base_path"),
    "mcp_log_dir": FieldBinding("mcp", "log_dir"),
    "mcp_require_token": FieldBinding("mcp", "require_token"),
    "mcp_token": FieldBinding("mcp", "token"),
    "llm_base_url": FieldBinding("llm", "base_url"),
    "llm_model": FieldBinding("llm", "model"),
    "llm_api_key": FieldBinding("llm", "api_key"),
    "llm_max_retries": FieldBinding("llm", "max_retries"),
    "llm_max_context_tokens": FieldBinding("llm", "max_context_tokens"),
    "llm_timeout_minutes": FieldBinding("llm", "timeout_minutes"),
    "llm_stream": FieldBinding("llm", "stream"),
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
}


class ListPanelLike(Protocol):
    """Protocol for panels persisting column layout state."""

    def load_column_widths(self, cfg: "ConfigManager") -> None:
        """Restore column widths from *cfg*."""

    def load_column_order(self, cfg: "ConfigManager") -> None:
        """Restore column order from *cfg*."""

    def save_column_widths(self, cfg: "ConfigManager") -> None:
        """Persist current column widths to *cfg*."""

    def save_column_order(self, cfg: "ConfigManager") -> None:
        """Persist current column order to *cfg*."""


class ConfigManager:
    """Wrapper around :class:`AppSettings` with helpers for wx widgets."""

    FIELD_BINDINGS: ClassVar[dict[str, FieldBinding]] = FIELD_BINDINGS

    def __init__(
        self,
        app_name: str = "CookaReq",
        path: Path | str | None = None,
    ) -> None:
        self._app_name = app_name
        self._path = Path(path) if path is not None else _default_config_path(app_name)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._settings = AppSettings()
        self._overrides: dict[str, dict[str, Any]] = {"llm": {}, "mcp": {}, "ui": {}}
        self._raw: dict[str, Any] = {}
        self._load()

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

    def has_value(self, name: str) -> bool:
        binding = self._binding_for(name)
        if binding is not None:
            return self._is_overridden(binding)
        return name in self._raw

    def set_value(self, name: str, value: Any) -> None:
        binding = self._binding_for(name)
        if binding is not None:
            self._set_override(binding, value)
            return
        self._raw[name] = deepcopy(value)

    # ------------------------------------------------------------------
    # basic key/value API compatible with wx.Config
    def read(self, key: str, default: str = "") -> str:
        binding = self._binding_for(key)
        if binding is not None:
            value = self.get_value(key, default=default)
            return "" if value is None else str(value)
        return str(self._raw.get(key, default))

    def read_int(self, key: str, default: int = 0) -> int:
        binding = self._binding_for(key)
        if binding is not None:
            try:
                return int(self.get_value(key, default=default))
            except (TypeError, ValueError):
                return int(default)
        value = self._raw.get(key, _MISSING)
        if value is _MISSING:
            return int(default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    def read_bool(self, key: str, default: bool = False) -> bool:
        binding = self._binding_for(key)
        if binding is not None:
            value = self.get_value(key, default=default)
            return bool(value)
        value = self._raw.get(key, _MISSING)
        if value is _MISSING:
            return bool(default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def write(self, key: str, value: str) -> None:
        binding = self._binding_for(key)
        if binding is not None:
            self.set_value(key, value)
        else:
            self._raw[key] = str(value)

    def write_int(self, key: str, value: int) -> None:
        binding = self._binding_for(key)
        if binding is not None:
            self.set_value(key, int(value))
        else:
            self._raw[key] = int(value)

    def write_bool(self, key: str, value: bool) -> None:
        binding = self._binding_for(key)
        if binding is not None:
            self.set_value(key, bool(value))
        else:
            self._raw[key] = bool(value)

    # ------------------------------------------------------------------
    # columns
    def get_columns(self) -> list[str]:
        return list(self.get_value("list_columns"))

    def set_columns(self, fields: list[str]) -> None:
        self.set_value("list_columns", list(fields))
        self.flush()

    # ------------------------------------------------------------------
    # recent directories
    def get_recent_dirs(self) -> list[str]:
        return list(self.get_value("recent_dirs"))

    def set_recent_dirs(self, dirs: list[str]) -> None:
        self.set_value("recent_dirs", list(dirs))
        self.flush()

    def add_recent_dir(self, path: Path) -> list[str]:
        dirs = self.get_recent_dirs()
        p = str(path)
        if p in dirs:
            dirs.remove(p)
        dirs.insert(0, p)
        del dirs[5:]
        self.set_recent_dirs(dirs)
        return dirs

    # ------------------------------------------------------------------
    # flags and language
    def get_auto_open_last(self) -> bool:
        return bool(self.get_value("auto_open_last"))

    def set_auto_open_last(self, value: bool) -> None:
        self.set_value("auto_open_last", bool(value))
        self.flush()

    def get_remember_sort(self) -> bool:
        return bool(self.get_value("remember_sort"))

    def set_remember_sort(self, value: bool) -> None:
        self.set_value("remember_sort", bool(value))
        self.flush()

    def get_language(self) -> str | None:
        return self.get_value("language")

    def set_language(self, language: str | None) -> None:
        self.set_value("language", language)
        self.flush()

    # ------------------------------------------------------------------
    # MCP server settings
    def get_mcp_settings(self) -> MCPSettings:
        return self._settings.mcp.model_copy(deep=True)

    def set_mcp_settings(self, settings: MCPSettings) -> None:
        self._overrides["mcp"] = settings.model_dump(mode="python")
        self._rebuild_settings()
        self.flush()

    # ------------------------------------------------------------------
    # LLM client settings
    def get_llm_settings(self) -> LLMSettings:
        return self._settings.llm.model_copy(deep=True)

    def set_llm_settings(self, settings: LLMSettings) -> None:
        self._overrides["llm"] = settings.model_dump(mode="python")
        self._rebuild_settings()
        self.flush()

    # ------------------------------------------------------------------
    # composite dataclasses
    def get_ui_settings(self) -> UISettings:
        return self._settings.ui.model_copy(deep=True)

    def set_ui_settings(self, settings: UISettings) -> None:
        self._overrides["ui"] = settings.model_dump(mode="python")
        self._rebuild_settings()
        self.flush()

    def get_app_settings(self) -> AppSettings:
        return self._settings.model_copy(deep=True)

    def set_app_settings(self, settings: AppSettings) -> None:
        self.set_llm_settings(settings.llm)
        self.set_mcp_settings(settings.mcp)
        self.set_ui_settings(settings.ui)

    # ------------------------------------------------------------------
    # sort settings
    def get_sort_settings(self) -> tuple[int, bool]:
        return int(self.get_value("sort_column")), bool(self.get_value("sort_ascending"))

    def set_sort_settings(self, column: int, ascending: bool) -> None:
        self.set_value("sort_column", int(column))
        self.set_value("sort_ascending", bool(ascending))
        self.flush()

    # ------------------------------------------------------------------
    # log console
    def get_log_sash(self, default: int) -> int:
        return int(self.get_value("log_sash", default=default))

    def set_log_sash(self, pos: int) -> None:
        self.set_value("log_sash", int(pos))
        self.flush()

    def set_log_shown(self, shown: bool) -> None:
        self.set_value("log_shown", bool(shown))
        self.flush()

    def get_log_level(self) -> int:
        level = int(self.get_value("log_level"))
        if level not in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR):
            return logging.INFO
        return level

    def set_log_level(self, level: int) -> None:
        self.set_value("log_level", int(level))
        self.flush()

    def get_agent_chat_shown(self) -> bool:
        return bool(self.get_value("agent_chat_shown"))

    def set_agent_chat_shown(self, shown: bool) -> None:
        self.set_value("agent_chat_shown", bool(shown))
        self.flush()

    def get_agent_chat_sash(self, default: int) -> int:
        return int(self.get_value("agent_chat_sash", default=default))

    def set_agent_chat_sash(self, pos: int) -> None:
        self.set_value("agent_chat_sash", int(pos))
        self.flush()

    def get_agent_history_sash(self, default: int) -> int:
        return int(self.get_value("agent_history_sash", default=default))

    def get_agent_confirm_mode(self) -> str:
        value = str(self.get_value("agent_confirm_mode", default="prompt"))
        if value not in {"prompt", "never"}:
            return "prompt"
        return value

    def set_agent_history_sash(self, pos: int) -> None:
        self.set_value("agent_history_sash", int(pos))
        self.flush()

    def set_agent_confirm_mode(self, mode: str) -> None:
        if mode not in {"prompt", "never"}:
            mode = "prompt"
        self.set_value("agent_confirm_mode", mode)
        self.flush()

    # ------------------------------------------------------------------
    # requirement editor panel
    def get_editor_sash(self, default: int) -> int:
        return int(self.get_value("editor_sash_pos", default=default))

    def set_editor_sash(self, pos: int) -> None:
        self.set_value("editor_sash_pos", int(pos))
        self.flush()

    def get_editor_shown(self) -> bool:
        return bool(self.get_value("editor_shown"))

    def set_editor_shown(self, shown: bool) -> None:
        self.set_value("editor_shown", bool(shown))
        self.flush()

    def get_doc_tree_collapsed(self) -> bool:
        return bool(self.get_value("doc_tree_collapsed"))

    def set_doc_tree_collapsed(self, collapsed: bool) -> None:
        self.set_value("doc_tree_collapsed", bool(collapsed))
        self.flush()

    def get_doc_tree_shown(self) -> bool:
        return not self.get_doc_tree_collapsed()

    def set_doc_tree_shown(self, shown: bool) -> None:
        self.set_doc_tree_collapsed(not shown)

    def get_doc_tree_sash(self, default: int) -> int:
        value = int(self.get_value("sash_pos", default=default))
        return max(value, 0)

    def set_doc_tree_sash(self, pos: int) -> None:
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
        w = max(400, min(int(self.get_value("win_w")), 3000))
        h = max(300, min(int(self.get_value("win_h")), 2000))
        frame.SetSize((w, h))
        x = int(self.get_value("win_x"))
        y = int(self.get_value("win_y"))
        if x != -1 and y != -1:
            frame.SetPosition((x, y))
        else:
            frame.Centre()
        frame.SendSizeEvent()
        app = wx.GetApp()
        if app is not None:
            app.ProcessPendingEvents()
        client_size = frame.GetClientSize()
        if client_size.width <= 1 or client_size.height <= 1:
            client_size = wx.Size(w, h)
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
        w, h = frame.GetSize()
        x, y = frame.GetPosition()
        self.set_value("win_w", int(w))
        self.set_value("win_h", int(h))
        self.set_value("win_x", int(x))
        self.set_value("win_y", int(y))
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


DEFAULT_LIST_COLUMNS = list(SETTINGS_DEFAULT_LIST_COLUMNS)
"""Re-exported for compatibility with legacy tests."""
