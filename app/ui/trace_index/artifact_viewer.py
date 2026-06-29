"""Read-only source artifact viewer for trace-index GUI navigation."""
from __future__ import annotations

from pathlib import Path

import wx

from ...i18n import _


class TraceArtifactFrame(wx.Frame):
    """Read-only source artifact viewer focused on a trace location line."""

    def __init__(
        self,
        parent: wx.Window | None,
        *,
        path: Path,
        project_root: Path,
        line: int | None = None,
    ) -> None:
        self.path = path
        self.project_root = project_root
        self.line = line
        title = _("Trace Artifact: {path}").format(
            path=display_artifact_path(path, project_root)
        )
        super().__init__(parent, title=title, size=(900, 620))
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        header = wx.StaticText(panel, label=path.as_posix())
        self.text = wx.TextCtrl(
            panel,
            value=self._read_text(path),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
        )
        font = wx.Font(wx.FontInfo(10).Family(wx.FONTFAMILY_TELETYPE))
        self.text.SetFont(font)
        sizer.Add(header, 0, wx.EXPAND | wx.ALL, self.FromDIP(8))
        sizer.Add(
            self.text,
            1,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            self.FromDIP(8),
        )
        panel.SetSizer(sizer)
        self._focus_line(line)

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return _("Cannot read artifact file: {error}").format(error=exc)

    def _focus_line(self, line: int | None) -> None:
        if line is None or line < 1:
            return
        position = self.text.XYToPosition(0, line - 1)
        if position == -1:
            return
        self.text.SetInsertionPoint(position)
        self.text.ShowPosition(position)


def display_artifact_path(path: Path, project_root: Path) -> str:
    """Return a project-relative artifact path when possible."""
    try:
        return path.resolve(strict=False).relative_to(
            project_root.resolve(strict=False)
        ).as_posix()
    except (OSError, ValueError):
        return path.as_posix()
