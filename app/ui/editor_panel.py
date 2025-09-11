"""Requirement editor panel."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import wx

from app.core import store


class EditorPanel(wx.Panel):
    """Panel for creating and editing requirements."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent)
        self.fields: dict[str, wx.TextCtrl] = {}
        sizer = wx.BoxSizer(wx.VERTICAL)
        for name, multiline in [
            ("id", False),
            ("title", False),
            ("statement", True),
            ("acceptance", True),
            ("owner", False),
            ("source", False),
        ]:
            style = wx.TE_MULTILINE if multiline else 0
            ctrl = wx.TextCtrl(self, style=style)
            self.fields[name] = ctrl
            sizer.Add(ctrl, 1 if multiline else 0, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(sizer)

        self.attachments: list[dict[str, str]] = []
        self.extra: dict[str, Any] = {
            "type": "requirement",
            "status": "draft",
            "priority": "medium",
            "verification": "analysis",
            "labels": [],
            "revision": 1,
            "approved_at": None,
            "notes": "",
        }
        self.current_path: Path | None = None
        self.mtime: float | None = None

    # basic operations -------------------------------------------------
    def new_requirement(self) -> None:
        for ctrl in self.fields.values():
            ctrl.SetValue("")
        self.attachments = []
        self.current_path = None
        self.mtime = None
        self.extra.update({
            "labels": [],
            "revision": 1,
            "approved_at": None,
            "notes": "",
        })

    def load(self, data: dict[str, Any], *, path: str | Path | None = None, mtime: float | None = None) -> None:
        for name, ctrl in self.fields.items():
            ctrl.SetValue(str(data.get(name, "")))
        self.attachments = list(data.get("attachments", []))
        for key in self.extra:
            if key in data:
                self.extra[key] = data[key]
        self.current_path = Path(path) if path else None
        self.mtime = mtime

    def clone(self, new_id: str) -> None:
        self.fields["id"].SetValue(new_id)
        self.current_path = None
        self.mtime = None

    # data helpers -----------------------------------------------------
    def get_data(self) -> dict[str, Any]:
        return {
            "id": self.fields["id"].GetValue(),
            "title": self.fields["title"].GetValue(),
            "statement": self.fields["statement"].GetValue(),
            "type": self.extra.get("type", "requirement"),
            "status": self.extra.get("status", "draft"),
            "owner": self.fields["owner"].GetValue(),
            "priority": self.extra.get("priority", "medium"),
            "source": self.fields["source"].GetValue(),
            "verification": self.extra.get("verification", "analysis"),
            "acceptance": self.fields["acceptance"].GetValue() or None,
            "units": None,
            "labels": self.extra.get("labels", []),
            "attachments": list(self.attachments),
            "revision": self.extra.get("revision", 1),
            "approved_at": self.extra.get("approved_at"),
            "notes": self.extra.get("notes", ""),
        }

    def save(self, directory: str | Path) -> Path:
        data = self.get_data()
        path = store.save(directory, data, mtime=self.mtime)
        self.current_path = path
        self.mtime = path.stat().st_mtime
        return path

    def delete(self) -> None:
        if self.current_path and self.current_path.exists():
            self.current_path.unlink()
        self.current_path = None
        self.mtime = None

    def add_attachment(self, path: str, note: str = "") -> None:
        self.attachments.append({"path": path, "note": note})
