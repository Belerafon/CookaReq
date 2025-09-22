"""Application configuration manager."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import logging
from pathlib import Path
from typing import Any, Callable, Generic, Literal, Protocol, TypeVar

import wx

from .llm.constants import DEFAULT_MAX_CONTEXT_TOKENS
from .settings import (
    AppSettings,
    LLMSettings,
    MCPSettings,
    UISettings,
    default_requirements_path,
)


T = TypeVar("T")
DEFAULT_LIST_COLUMNS: list[str] = [
    "labels",
    "id",
    "derived_from",
    "status",
    "priority",
    "type",
    "owner",
]


@dataclass(frozen=True)
class FieldSpec(Generic[T]):
    """Describe a configuration entry stored in :class:`wx.Config`."""

    key: str
    value_type: Any
    default: T | None = None
    default_factory: Callable[[], T] | None = None
    reader: Callable[["ConfigManager", "FieldSpec[T]", T], T] | None = None
    writer: Callable[["ConfigManager", "FieldSpec[T]", T], None] | None = None

    def make_default(self) -> T:
        """Return a default value honouring ``default_factory``."""

        if self.default_factory is not None:
            return self.default_factory()
        return deepcopy(self.default)


def _list_reader(separator: str) -> Callable[["ConfigManager", FieldSpec[list[str]], list[str]], list[str]]:
    def reader(
        manager: "ConfigManager",
        spec: FieldSpec[list[str]],
        default: list[str],
    ) -> list[str]:
        fallback = separator.join(default)
        raw = manager._cfg.Read(spec.key, fallback)
        if not raw:
            return []
        return [item for item in raw.split(separator) if item]

    return reader


def _list_writer(separator: str) -> Callable[["ConfigManager", FieldSpec[list[str]], list[str]], None]:
    def writer(
        manager: "ConfigManager",
        spec: FieldSpec[list[str]],
        value: list[str],
    ) -> None:
        manager._cfg.Write(spec.key, separator.join(value))

    return writer


def _optional_string_reader(
    manager: "ConfigManager",
    spec: FieldSpec[str | None],
    default: str | None,
) -> str | None:
    fallback = "" if default is None else str(default)
    value = manager._cfg.Read(spec.key, fallback)
    return value or None


def _optional_string_writer(
    manager: "ConfigManager",
    spec: FieldSpec[str | None],
    value: str | None,
) -> None:
    manager._cfg.Write(spec.key, "" if value is None else str(value))


def _llm_base_url_reader(
    manager: "ConfigManager",
    spec: FieldSpec[str],
    default: str,
) -> str:
    legacy = manager._cfg.Read("llm_api_base", default)
    return manager._cfg.Read(spec.key, legacy)


ConfigFieldName = Literal[
    "list_columns",
    "recent_dirs",
    "auto_open_last",
    "remember_sort",
    "language",
    "mcp_auto_start",
    "mcp_host",
    "mcp_port",
    "mcp_base_path",
    "mcp_log_dir",
    "mcp_require_token",
    "mcp_token",
    "llm_base_url",
    "llm_model",
    "llm_api_key",
    "llm_max_retries",
    "llm_max_context_tokens",
    "llm_timeout_minutes",
    "llm_stream",
    "sort_column",
    "sort_ascending",
    "log_sash",
    "log_level",
    "log_shown",
    "agent_chat_sash",
    "agent_chat_shown",
    "agent_history_sash",
    "win_w",
    "win_h",
    "win_x",
    "win_y",
    "doc_tree_collapsed",
    "sash_pos",
    "editor_sash_pos",
]


CONFIG_FIELD_SPECS: dict[ConfigFieldName, FieldSpec[Any]] = {
    "list_columns": FieldSpec(
        key="list_columns",
        value_type=list[str],
        default_factory=lambda: list(DEFAULT_LIST_COLUMNS),
        reader=_list_reader(","),
        writer=_list_writer(","),
    ),
    "recent_dirs": FieldSpec(
        key="recent_dirs",
        value_type=list[str],
        default_factory=list,
        reader=_list_reader("|"),
        writer=_list_writer("|"),
    ),
    "auto_open_last": FieldSpec(
        key="auto_open_last",
        value_type=bool,
        default=False,
    ),
    "remember_sort": FieldSpec(
        key="remember_sort",
        value_type=bool,
        default=False,
    ),
    "language": FieldSpec(
        key="language",
        value_type=str | None,
        default=None,
        reader=_optional_string_reader,
        writer=_optional_string_writer,
    ),
    "mcp_auto_start": FieldSpec(
        key="mcp_auto_start",
        value_type=bool,
        default=True,
    ),
    "mcp_host": FieldSpec(
        key="mcp_host",
        value_type=str,
        default="127.0.0.1",
    ),
    "mcp_port": FieldSpec(
        key="mcp_port",
        value_type=int,
        default=59362,
    ),
    "mcp_base_path": FieldSpec(
        key="mcp_base_path",
        value_type=str,
        default_factory=default_requirements_path,
    ),
    "mcp_log_dir": FieldSpec(
        key="mcp_log_dir",
        value_type=str | None,
        default=None,
        reader=_optional_string_reader,
        writer=_optional_string_writer,
    ),
    "mcp_require_token": FieldSpec(
        key="mcp_require_token",
        value_type=bool,
        default=False,
    ),
    "mcp_token": FieldSpec(
        key="mcp_token",
        value_type=str,
        default="",
    ),
    "llm_base_url": FieldSpec(
        key="llm_base_url",
        value_type=str,
        default="",
        reader=_llm_base_url_reader,
    ),
    "llm_model": FieldSpec(
        key="llm_model",
        value_type=str,
        default="",
    ),
    "llm_api_key": FieldSpec(
        key="llm_api_key",
        value_type=str | None,
        default=None,
        reader=_optional_string_reader,
        writer=_optional_string_writer,
    ),
    "llm_max_retries": FieldSpec(
        key="llm_max_retries",
        value_type=int,
        default=3,
    ),
    "llm_max_context_tokens": FieldSpec(
        key="llm_max_context_tokens",
        value_type=int,
        default=DEFAULT_MAX_CONTEXT_TOKENS,
    ),
    "llm_timeout_minutes": FieldSpec(
        key="llm_timeout_minutes",
        value_type=int,
        default=60,
    ),
    "llm_stream": FieldSpec(
        key="llm_stream",
        value_type=bool,
        default=False,
    ),
    "sort_column": FieldSpec(
        key="sort_column",
        value_type=int,
        default=-1,
    ),
    "sort_ascending": FieldSpec(
        key="sort_ascending",
        value_type=bool,
        default=True,
    ),
    "log_sash": FieldSpec(
        key="log_sash",
        value_type=int,
        default=300,
    ),
    "log_level": FieldSpec(
        key="log_level",
        value_type=int,
        default=logging.INFO,
    ),
    "log_shown": FieldSpec(
        key="log_shown",
        value_type=bool,
        default=False,
    ),
    "agent_chat_sash": FieldSpec(
        key="agent_chat_sash",
        value_type=int,
        default=400,
    ),
    "agent_chat_shown": FieldSpec(
        key="agent_chat_shown",
        value_type=bool,
        default=False,
    ),
    "agent_history_sash": FieldSpec(
        key="agent_history_sash",
        value_type=int,
        default=320,
    ),
    "editor_shown": FieldSpec(
        key="editor_shown",
        value_type=bool,
        default=True,
    ),
    "win_w": FieldSpec(
        key="win_w",
        value_type=int,
        default=800,
    ),
    "win_h": FieldSpec(
        key="win_h",
        value_type=int,
        default=600,
    ),
    "win_x": FieldSpec(
        key="win_x",
        value_type=int,
        default=-1,
    ),
    "win_y": FieldSpec(
        key="win_y",
        value_type=int,
        default=-1,
    ),
    "doc_tree_collapsed": FieldSpec(
        key="doc_tree_collapsed",
        value_type=bool,
        default=False,
    ),
    "sash_pos": FieldSpec(
        key="sash_pos",
        value_type=int,
        default=300,
    ),
    "editor_sash_pos": FieldSpec(
        key="editor_sash_pos",
        value_type=int,
        default=600,
    ),
}


_MISSING = object()


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
    """Wrapper around :class:`wx.Config` with typed helpers."""

    FIELDS: dict[ConfigFieldName, FieldSpec[Any]] = CONFIG_FIELD_SPECS

    def __init__(
        self,
        app_name: str = "CookaReq",
        path: Path | str | None = None,
    ) -> None:
        """Initialize configuration storage.

        Parameters
        ----------
        app_name:
            Application name for config files.
        path:
            Optional explicit path for configuration file.
        """
        if path is None:
            self._cfg = wx.Config(appName=app_name)
        else:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._cfg = wx.FileConfig(appName=app_name, localFilename=str(p))

    # ------------------------------------------------------------------
    # schema access helpers
    @classmethod
    def get_field_spec(cls, name: ConfigFieldName) -> FieldSpec[Any]:
        """Return field specification for ``name``."""

        return cls.FIELDS[name]

    def get_value(self, name: ConfigFieldName, default: Any = _MISSING) -> Any:
        """Read value for ``name`` using :data:`CONFIG_FIELD_SPECS`."""

        spec = self.FIELDS[name]
        resolved_default = spec.make_default() if default is _MISSING else default
        if spec.reader is not None:
            return spec.reader(self, spec, resolved_default)
        return self._read_native(spec, resolved_default)

    def has_value(self, name: ConfigFieldName) -> bool:
        """Return ``True`` if ``name`` is explicitly stored in the config."""

        spec = self.FIELDS[name]
        try:
            return bool(self._cfg.HasEntry(spec.key))
        except Exception:  # pragma: no cover - defensive compatibility path
            return True

    def set_value(self, name: ConfigFieldName, value: Any) -> None:
        """Write ``value`` for ``name`` using :data:`CONFIG_FIELD_SPECS`."""

        spec = self.FIELDS[name]
        if spec.writer is not None:
            spec.writer(self, spec, value)
            return
        self._write_native(spec, value)

    def _read_native(self, spec: FieldSpec[Any], default: Any) -> Any:
        """Read primitive value based on ``value_type``."""

        if spec.value_type is bool:
            return self._cfg.ReadBool(spec.key, bool(default))
        if spec.value_type is int:
            return self._cfg.ReadInt(spec.key, int(default))
        if spec.value_type is str:
            fallback = "" if default is None else str(default)
            return self._cfg.Read(spec.key, fallback)
        raise TypeError(f"No native reader for field '{spec.key}'")

    def _write_native(self, spec: FieldSpec[Any], value: Any) -> None:
        """Write primitive value based on ``value_type``."""

        if spec.value_type is bool:
            self._cfg.WriteBool(spec.key, bool(value))
            return
        if spec.value_type is int:
            self._cfg.WriteInt(spec.key, int(value))
            return
        if spec.value_type is str:
            self._cfg.Write(spec.key, str(value))
            return
        raise TypeError(f"No native writer for field '{spec.key}'")

    # ------------------------------------------------------------------
    # basic ``wx.Config`` API
    def read(self, key: str, default: str = "") -> str:
        """Read string value for ``key``."""

        return self._cfg.Read(key, default)

    def read_int(self, key: str, default: int = 0) -> int:
        """Read integer value for ``key``."""

        return self._cfg.ReadInt(key, default)

    def read_bool(self, key: str, default: bool = False) -> bool:
        """Read boolean value for ``key``."""

        return self._cfg.ReadBool(key, default)

    def write(self, key: str, value: str) -> None:
        """Write string ``value`` under ``key``."""

        self._cfg.Write(key, value)

    def write_int(self, key: str, value: int) -> None:
        """Write integer ``value`` under ``key``."""

        self._cfg.WriteInt(key, value)

    def write_bool(self, key: str, value: bool) -> None:
        """Write boolean ``value`` under ``key``."""

        self._cfg.WriteBool(key, value)

    def flush(self) -> None:  # pragma: no cover - simple wrapper
        """Persist configuration to disk."""

        self._cfg.Flush()

    # ------------------------------------------------------------------
    # columns
    def get_columns(self) -> list[str]:
        """Return list of visible column identifiers."""

        return self.get_value("list_columns")

    def set_columns(self, fields: list[str]) -> None:
        """Persist selected column identifiers."""

        self.set_value("list_columns", fields)
        self.flush()

    # ------------------------------------------------------------------
    # recent directories
    def get_recent_dirs(self) -> list[str]:
        """Return list of recently opened directories."""

        return self.get_value("recent_dirs")

    def set_recent_dirs(self, dirs: list[str]) -> None:
        """Persist recently opened directories."""

        self.set_value("recent_dirs", dirs)
        self.flush()

    def add_recent_dir(self, path: Path) -> list[str]:
        """Insert ``path`` at the beginning of recent directories list."""

        dirs = self.get_value("recent_dirs")
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
        """Return whether last directory is opened on startup."""

        return self.get_value("auto_open_last")

    def set_auto_open_last(self, value: bool) -> None:
        """Persist option to open last directory on startup."""

        self.set_value("auto_open_last", value)
        self.flush()

    def get_remember_sort(self) -> bool:
        """Return whether list sorting is remembered."""

        return self.get_value("remember_sort")

    def set_remember_sort(self, value: bool) -> None:
        """Persist option to remember list sorting."""

        self.set_value("remember_sort", value)
        self.flush()

    def get_language(self) -> str | None:
        """Return stored UI language code or ``None``."""

        return self.get_value("language")

    def set_language(self, language: str) -> None:
        """Persist UI language code."""

        self.set_value("language", language)
        self.flush()

    # ------------------------------------------------------------------
    # MCP server settings
    def get_mcp_settings(self) -> MCPSettings:
        """Return stored MCP server settings."""

        return MCPSettings(
            auto_start=self.get_value("mcp_auto_start"),
            host=self.get_value("mcp_host"),
            port=self.get_value("mcp_port"),
            base_path=self.get_value("mcp_base_path"),
            log_dir=self.get_value("mcp_log_dir"),
            require_token=self.get_value("mcp_require_token"),
            token=self.get_value("mcp_token"),
        )

    def set_mcp_settings(self, settings: MCPSettings) -> None:
        """Persist MCP server settings."""

        self.set_value("mcp_auto_start", settings.auto_start)
        self.set_value("mcp_host", settings.host)
        self.set_value("mcp_port", settings.port)
        self.set_value("mcp_base_path", settings.base_path)
        self.set_value("mcp_log_dir", settings.log_dir)
        self.set_value("mcp_require_token", settings.require_token)
        self.set_value("mcp_token", settings.token)
        self.flush()

    # ------------------------------------------------------------------
    # LLM client settings
    def get_llm_settings(self) -> LLMSettings:
        """Return stored LLM client settings."""

        return LLMSettings(
            base_url=self.get_value("llm_base_url"),
            model=self.get_value("llm_model"),
            api_key=self.get_value("llm_api_key"),
            max_retries=self.get_value("llm_max_retries"),
            max_context_tokens=self.get_value("llm_max_context_tokens"),
            timeout_minutes=self.get_value("llm_timeout_minutes"),
            stream=self.get_value("llm_stream"),
        )

    def set_llm_settings(self, settings: LLMSettings) -> None:
        """Persist LLM client settings."""

        self.set_value("llm_base_url", settings.base_url)
        self.set_value("llm_model", settings.model)
        self.set_value("llm_api_key", settings.api_key)
        self.set_value("llm_max_retries", settings.max_retries)
        self.set_value("llm_max_context_tokens", settings.max_context_tokens)
        self.set_value("llm_timeout_minutes", settings.timeout_minutes)
        self.set_value("llm_stream", settings.stream)
        self.flush()

    # ------------------------------------------------------------------
    # composite dataclasses
    def get_ui_settings(self) -> UISettings:
        """Assemble and return composite UI settings."""

        sort_column, sort_ascending = self.get_sort_settings()
        return UISettings(
            columns=self.get_columns(),
            recent_dirs=self.get_recent_dirs(),
            auto_open_last=self.get_auto_open_last(),
            remember_sort=self.get_remember_sort(),
            language=self.get_language(),
            sort_column=sort_column,
            sort_ascending=sort_ascending,
            log_level=self.get_log_level(),
        )

    def set_ui_settings(self, settings: UISettings) -> None:
        """Persist composite UI settings."""

        self.set_columns(settings.columns)
        self.set_recent_dirs(settings.recent_dirs)
        self.set_auto_open_last(settings.auto_open_last)
        self.set_remember_sort(settings.remember_sort)
        if settings.language is not None:
            self.set_language(settings.language)
        sort_col = settings.sort_column
        sort_asc = settings.sort_ascending
        self.set_sort_settings(sort_col, sort_asc)
        self.set_log_level(settings.log_level)

    def get_app_settings(self) -> AppSettings:
        """Return all application settings."""

        return AppSettings(
            llm=self.get_llm_settings(),
            mcp=self.get_mcp_settings(),
            ui=self.get_ui_settings(),
        )

    def set_app_settings(self, settings: AppSettings) -> None:
        """Persist all application settings."""

        self.set_llm_settings(settings.llm)
        self.set_mcp_settings(settings.mcp)
        self.set_ui_settings(settings.ui)

    # ------------------------------------------------------------------
    # sort settings
    def get_sort_settings(self) -> tuple[int, bool]:
        """Return stored sort column and order."""

        return self.get_value("sort_column"), self.get_value("sort_ascending")

    def set_sort_settings(self, column: int, ascending: bool) -> None:
        """Persist sort column and order."""

        self.set_value("sort_column", column)
        self.set_value("sort_ascending", ascending)
        self.flush()

    # ------------------------------------------------------------------
    # log console
    def get_log_sash(self, default: int) -> int:
        """Return splitter position for log console."""

        return self.get_value("log_sash", default=default)

    def set_log_sash(self, pos: int) -> None:
        """Persist splitter position for log console."""

        self.set_value("log_sash", pos)
        self.flush()

    def set_log_shown(self, shown: bool) -> None:
        """Persist whether log console is visible."""

        self.set_value("log_shown", shown)
        self.flush()

    def get_log_level(self) -> int:
        """Return the minimum severity displayed in the log console."""

        level = int(self.get_value("log_level"))
        if level not in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR):
            return logging.INFO
        return level

    def set_log_level(self, level: int) -> None:
        """Persist minimum severity displayed in the log console."""

        self.set_value("log_level", int(level))
        self.flush()

    def get_agent_chat_shown(self) -> bool:
        """Check whether agent chat panel is visible."""

        return self.get_value("agent_chat_shown")

    def set_agent_chat_shown(self, shown: bool) -> None:
        """Persist visibility flag for agent chat panel."""

        self.set_value("agent_chat_shown", shown)
        self.flush()

    def get_agent_chat_sash(self, default: int) -> int:
        """Return stored splitter position for the agent chat pane."""

        return self.get_value("agent_chat_sash", default=default)

    def set_agent_chat_sash(self, pos: int) -> None:
        """Persist splitter position for the agent chat pane."""

        self.set_value("agent_chat_sash", pos)
        self.flush()

    def get_agent_history_sash(self, default: int) -> int:
        """Return stored width of the chat history list."""

        return self.get_value("agent_history_sash", default=default)

    def set_agent_history_sash(self, pos: int) -> None:
        """Persist width of the chat history list."""

        self.set_value("agent_history_sash", pos)
        self.flush()

    # ------------------------------------------------------------------
    # requirement editor panel
    def get_editor_sash(self, default: int) -> int:
        """Return stored splitter position for the requirement editor."""

        return self.get_value("editor_sash_pos", default=default)

    def set_editor_sash(self, pos: int) -> None:
        """Persist splitter position for the requirement editor."""

        self.set_value("editor_sash_pos", pos)
        self.flush()

    def get_editor_shown(self) -> bool:
        """Check whether the requirement editor is visible on the main form."""

        return self.get_value("editor_shown")

    def set_editor_shown(self, shown: bool) -> None:
        """Persist visibility flag for the requirement editor."""

        self.set_value("editor_shown", shown)
        self.flush()

    def get_doc_tree_collapsed(self) -> bool:
        """Return whether the hierarchy pane was collapsed."""

        return self.get_value("doc_tree_collapsed")

    def set_doc_tree_collapsed(self, collapsed: bool) -> None:
        """Persist collapsed state of the hierarchy pane."""

        self.set_value("doc_tree_collapsed", collapsed)
        self.flush()

    def get_doc_tree_shown(self) -> bool:
        """Return whether the hierarchy pane should be visible."""

        return not self.get_doc_tree_collapsed()

    def set_doc_tree_shown(self, shown: bool) -> None:
        """Persist hierarchy visibility flag."""

        self.set_doc_tree_collapsed(not shown)

    def get_doc_tree_sash(self, default: int) -> int:
        """Return stored width of the hierarchy splitter."""

        value = int(self.get_value("sash_pos", default=default))
        return max(value, 0)

    def set_doc_tree_sash(self, pos: int) -> None:
        """Persist width of the hierarchy splitter."""

        self.set_value("sash_pos", pos)
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
        """Restore window geometry and splitter positions."""
        w = self.get_value("win_w")
        h = self.get_value("win_h")
        w = max(400, min(w, 3000))
        h = max(300, min(h, 2000))
        frame.SetSize((w, h))
        x = self.get_value("win_x")
        y = self.get_value("win_y")
        if x != -1 and y != -1:
            frame.SetPosition((x, y))
        else:
            frame.Centre()
        # Ensure layout calculations are performed even if the frame is not shown yet.
        # ``wx.Yield`` has been observed to segfault when called in quick succession
        # during automated tests, so prefer processing the pending events directly.
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
        stored_doc_sash = self.get_value("sash_pos")
        doc_sash = max(doc_min, min(stored_doc_sash, doc_max))
        doc_splitter.SetSashPosition(doc_sash)
        if editor_splitter is not None and editor_splitter.IsSplit():
            editor_default = editor_splitter.GetSashPosition()
            editor_min = max(editor_splitter.GetMinimumPaneSize(), 100)
            available_width = max(client_size.width - doc_sash, editor_min * 2)
            editor_max = max(available_width - editor_min, editor_min)
            stored_editor_sash = self.get_value(
                "editor_sash_pos", default=editor_default
            )
            editor_sash = max(editor_min, min(stored_editor_sash, editor_max))
            editor_splitter.SetSize(wx.Size(available_width, client_size.height))
            editor_splitter.SetSashPosition(editor_sash)
        panel.load_column_widths(self)
        panel.load_column_order(self)
        log_shown = self.get_value("log_shown")
        log_sash = self.get_value("log_sash", default=client_size.height - 150)
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
        """Persist window geometry and splitter positions."""
        w, h = frame.GetSize()
        x, y = frame.GetPosition()
        self.set_value("win_w", w)
        self.set_value("win_h", h)
        self.set_value("win_x", x)
        self.set_value("win_y", y)
        sash_to_store = (
            doc_tree_sash
            if doc_tree_sash is not None
            else doc_splitter.GetSashPosition()
        )
        self.set_value("sash_pos", sash_to_store)
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
                self.set_value("agent_chat_sash", agent_chat_sash)
        if agent_history_sash is not None:
            self.set_value("agent_history_sash", agent_history_sash)
        panel.save_column_widths(self)
        panel.save_column_order(self)
        self.flush()
