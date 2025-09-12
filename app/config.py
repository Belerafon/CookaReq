"""Application configuration manager."""

from __future__ import annotations

from pathlib import Path
import wx

from app.ui.list_panel import ListPanel


class ConfigManager:
    """Wrapper around :class:`wx.Config` with typed helpers."""

    def __init__(self, app_name: str = "CookaReq") -> None:
        self._cfg = wx.Config(appName=app_name)

    @property
    def wx(self) -> wx.Config:  # pragma: no cover - simple property
        """Expose underlying ``wx.Config`` for low-level operations."""
        return self._cfg

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
    def get_mcp_settings(self) -> tuple[str, int, str, str]:
        host = self._cfg.Read("mcp_host", "127.0.0.1")
        port = self._cfg.ReadInt("mcp_port", 8000)
        base_path = self._cfg.Read("mcp_base_path", "")
        token = self._cfg.Read("mcp_token", "")
        return host, port, base_path, token

    def set_mcp_settings(self, host: str, port: int, base_path: str, token: str) -> None:
        self._cfg.Write("mcp_host", host)
        self._cfg.WriteInt("mcp_port", port)
        self._cfg.Write("mcp_base_path", base_path)
        self._cfg.Write("mcp_token", token)
        self._cfg.Flush()

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
        panel: ListPanel,
        log_console: wx.TextCtrl,
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
        sash = self._cfg.ReadInt("sash_pos", 300)
        client_w = frame.GetClientSize().width
        sash = max(100, min(sash, max(client_w - 100, 100)))
        splitter.SetSashPosition(sash)
        panel.load_column_widths(self._cfg)
        panel.load_column_order(self._cfg)
        log_shown = self._cfg.ReadBool("log_shown", False)
        log_sash = self._cfg.ReadInt("log_sash", frame.GetClientSize().height - 150)
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
        panel: ListPanel,
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
        panel.save_column_widths(self._cfg)
        panel.save_column_order(self._cfg)
        self._cfg.Flush()
