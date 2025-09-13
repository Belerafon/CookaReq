"""Application configuration manager."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import wx

from .settings import LLMSettings, MCPSettings, AppSettings, UISettings


class ListPanelLike(Protocol):
    def load_column_widths(self, cfg: "ConfigManager") -> None: ...
    def load_column_order(self, cfg: "ConfigManager") -> None: ...
    def save_column_widths(self, cfg: "ConfigManager") -> None: ...
    def save_column_order(self, cfg: "ConfigManager") -> None: ...


class ConfigManager:
    """Wrapper around :class:`wx.Config` with typed helpers."""

    def __init__(self, app_name: str = "CookaReq", path: Path | str | None = None) -> None:
        if path is None:
            self._cfg = wx.Config(appName=app_name)
        else:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._cfg = wx.FileConfig(appName=app_name, localFilename=str(p))

    # ------------------------------------------------------------------
    # basic ``wx.Config`` API
    def Read(self, key: str, default: str = "") -> str:
        return self._cfg.Read(key, default)

    def ReadInt(self, key: str, default: int = 0) -> int:
        return self._cfg.ReadInt(key, default)

    def ReadBool(self, key: str, default: bool = False) -> bool:
        return self._cfg.ReadBool(key, default)

    def Write(self, key: str, value: str) -> None:
        self._cfg.Write(key, value)

    def WriteInt(self, key: str, value: int) -> None:
        self._cfg.WriteInt(key, value)

    def WriteBool(self, key: str, value: bool) -> None:
        self._cfg.WriteBool(key, value)

    def Flush(self) -> None:  # pragma: no cover - simple wrapper
        self._cfg.Flush()

    # ------------------------------------------------------------------
    # columns
    def get_columns(self) -> list[str]:
        value = self._cfg.Read("list_columns", "")
        return [f for f in value.split(",") if f]

    def set_columns(self, fields: list[str]) -> None:
        self._cfg.Write("list_columns", ",".join(fields))
        self._cfg.Flush()

    # ------------------------------------------------------------------
    # recent directories
    def get_recent_dirs(self) -> list[str]:
        value = self._cfg.Read("recent_dirs", "")
        return [p for p in value.split("|") if p]

    def set_recent_dirs(self, dirs: list[str]) -> None:
        self._cfg.Write("recent_dirs", "|".join(dirs))
        self._cfg.Flush()

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
        return self._cfg.ReadBool("auto_open_last", False)

    def set_auto_open_last(self, value: bool) -> None:
        self._cfg.WriteBool("auto_open_last", value)
        self._cfg.Flush()

    def get_remember_sort(self) -> bool:
        return self._cfg.ReadBool("remember_sort", False)

    def set_remember_sort(self, value: bool) -> None:
        self._cfg.WriteBool("remember_sort", value)
        self._cfg.Flush()

    def get_language(self) -> str | None:
        return self._cfg.Read("language") or None

    def set_language(self, language: str) -> None:
        self._cfg.Write("language", language)
        self._cfg.Flush()

    # ------------------------------------------------------------------
    # MCP server settings
    def get_mcp_settings(self) -> MCPSettings:
        return MCPSettings(
            host=self._cfg.Read("mcp_host", "127.0.0.1"),
            port=self._cfg.ReadInt("mcp_port", 59362),
            base_path=self._cfg.Read("mcp_base_path", ""),
            require_token=self._cfg.ReadBool("mcp_require_token", False),
            token=self._cfg.Read("mcp_token", ""),
        )

    def set_mcp_settings(self, settings: MCPSettings) -> None:
        self._cfg.Write("mcp_host", settings.host)
        self._cfg.WriteInt("mcp_port", settings.port)
        self._cfg.Write("mcp_base_path", settings.base_path)
        self._cfg.WriteBool("mcp_require_token", settings.require_token)
        self._cfg.Write("mcp_token", settings.token)
        self._cfg.Flush()

    # ------------------------------------------------------------------
    # LLM client settings
    def get_llm_settings(self) -> LLMSettings:
        return LLMSettings(
            api_base=self._cfg.Read("llm_api_base", ""),
            model=self._cfg.Read("llm_model", ""),
            api_key=self._cfg.Read("llm_api_key", ""),
            timeout=self._cfg.ReadInt("llm_timeout", 60),
        )

    def set_llm_settings(self, settings: LLMSettings) -> None:
        self._cfg.Write("llm_api_base", settings.api_base)
        self._cfg.Write("llm_model", settings.model)
        self._cfg.Write("llm_api_key", settings.api_key)
        self._cfg.WriteInt("llm_timeout", settings.timeout)
        self._cfg.Flush()

    # ------------------------------------------------------------------
    # composite dataclasses
    def get_ui_settings(self) -> UISettings:
        sort_column, sort_ascending = self.get_sort_settings()
        return UISettings(
            columns=self.get_columns(),
            recent_dirs=self.get_recent_dirs(),
            auto_open_last=self.get_auto_open_last(),
            remember_sort=self.get_remember_sort(),
            language=self.get_language(),
            sort_column=sort_column,
            sort_ascending=sort_ascending,
        )

    def set_ui_settings(self, settings: UISettings) -> None:
        self.set_columns(settings.columns)
        self.set_recent_dirs(settings.recent_dirs)
        self.set_auto_open_last(settings.auto_open_last)
        self.set_remember_sort(settings.remember_sort)
        if settings.language is not None:
            self.set_language(settings.language)
        sort_col = settings.sort_column
        sort_asc = settings.sort_ascending
        self.set_sort_settings(sort_col, sort_asc)

    def get_app_settings(self) -> AppSettings:
        return AppSettings(
            llm=self.get_llm_settings(),
            mcp=self.get_mcp_settings(),
            ui=self.get_ui_settings(),
        )

    def set_app_settings(self, settings: AppSettings) -> None:
        self.set_llm_settings(settings.llm)
        self.set_mcp_settings(settings.mcp)
        self.set_ui_settings(settings.ui)

    # ------------------------------------------------------------------
    # sort settings
    def get_sort_settings(self) -> tuple[int, bool]:
        column = self._cfg.ReadInt("sort_column", -1)
        ascending = self._cfg.ReadBool("sort_ascending", True)
        return column, ascending

    def set_sort_settings(self, column: int, ascending: bool) -> None:
        self._cfg.WriteInt("sort_column", column)
        self._cfg.WriteBool("sort_ascending", ascending)
        self._cfg.Flush()

    # ------------------------------------------------------------------
    # log console
    def get_log_sash(self, default: int) -> int:
        return self._cfg.ReadInt("log_sash", default)

    def set_log_sash(self, pos: int) -> None:
        self._cfg.WriteInt("log_sash", pos)
        self._cfg.Flush()

    def set_log_shown(self, shown: bool) -> None:
        self._cfg.WriteBool("log_shown", shown)
        self._cfg.Flush()

    # ------------------------------------------------------------------
    # layout helpers
    def restore_layout(
        self,
        frame: wx.Frame,
        splitter: wx.SplitterWindow,
        main_splitter: wx.SplitterWindow,
        panel: ListPanelLike,
        log_console: wx.Window,
        log_menu_item: wx.MenuItem | None = None,
    ) -> None:
        """Restore window geometry and splitter positions."""
        w = self._cfg.ReadInt("win_w", 800)
        h = self._cfg.ReadInt("win_h", 600)
        w = max(400, min(w, 3000))
        h = max(300, min(h, 2000))
        frame.SetSize((w, h))
        x = self._cfg.ReadInt("win_x", -1)
        y = self._cfg.ReadInt("win_y", -1)
        if x != -1 and y != -1:
            frame.SetPosition((x, y))
        else:
            frame.Centre()
        # Ensure layout calculations are performed even if the frame is not shown yet
        frame.SendSizeEvent()
        wx.Yield()
        client_size = frame.GetClientSize()
        if client_size.width <= 1 or client_size.height <= 1:
            client_size = wx.Size(w, h)
        main_splitter.SetSize(client_size)
        splitter.SetSize(client_size)
        sash = self._cfg.ReadInt("sash_pos", 300)
        sash = max(100, min(sash, max(client_size.width - 100, 100)))
        splitter.SetSashPosition(sash)
        panel.load_column_widths(self)
        panel.load_column_order(self)
        log_shown = self._cfg.ReadBool("log_shown", False)
        log_sash = self._cfg.ReadInt("log_sash", client_size.height - 150)
        if log_shown:
            log_console.Show()
            main_splitter.SplitHorizontally(splitter, log_console, log_sash)
            if log_menu_item:
                log_menu_item.Check(True)
        else:
            main_splitter.Initialize(splitter)
            log_console.Hide()
            if log_menu_item:
                log_menu_item.Check(False)

    def save_layout(
        self,
        frame: wx.Frame,
        splitter: wx.SplitterWindow,
        main_splitter: wx.SplitterWindow,
        panel: ListPanelLike,
    ) -> None:
        """Persist window geometry and splitter positions."""
        w, h = frame.GetSize()
        x, y = frame.GetPosition()
        self._cfg.WriteInt("win_w", w)
        self._cfg.WriteInt("win_h", h)
        self._cfg.WriteInt("win_x", x)
        self._cfg.WriteInt("win_y", y)
        self._cfg.WriteInt("sash_pos", splitter.GetSashPosition())
        if main_splitter.IsSplit():
            self._cfg.WriteBool("log_shown", True)
            self._cfg.WriteInt("log_sash", main_splitter.GetSashPosition())
        else:
            self._cfg.WriteBool("log_shown", False)
        panel.save_column_widths(self)
        panel.save_column_order(self)
        self.Flush()
