"""Main application window."""

import re
import wx
from pathlib import Path
from dataclasses import fields
from typing import Dict

from app.core import store
from app.core.model import Requirement
from .list_panel import ListPanel
from .editor_panel import EditorPanel


class MainFrame(wx.Frame):
    """Top-level frame with basic menu and toolbar."""

    def __init__(self, parent: wx.Window | None):
        self._base_title = "CookaReq"
        self.config = wx.Config(appName="CookaReq")
        self.available_fields = [f.name for f in fields(Requirement) if f.name != "title"]
        self.selected_fields = self._load_columns()
        super().__init__(parent=parent, title=self._base_title)
        self._create_menu()
        self._create_toolbar()
        self.splitter = wx.SplitterWindow(self)
        self.panel = ListPanel(
            self.splitter,
            on_clone=self.on_clone_requirement,
            on_delete=self.on_delete_requirement,
        )
        self.panel.set_columns(self.selected_fields)
        self.editor = EditorPanel(self.splitter, on_save=self._on_editor_save)
        self.splitter.SplitVertically(self.panel, self.editor, 300)
        self.editor.Hide()
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.splitter, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self.SetSize((800, 600))
        self.Centre()
        self.requirements: list[dict] = []
        self.current_dir: Path | None = None
        self.panel.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_requirement_selected)

    def _create_menu(self) -> None:
        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        open_item = file_menu.Append(wx.ID_OPEN, "&Open Folder\tCtrl+O")
        exit_item = file_menu.Append(wx.ID_EXIT, "E&xit")
        self.Bind(wx.EVT_MENU, self.on_open_folder, open_item)
        self.Bind(wx.EVT_MENU, lambda evt: self.Close(), exit_item)
        menu_bar.Append(file_menu, "&File")

        view_menu = wx.Menu()
        self._column_items: Dict[int, str] = {}
        for field in self.available_fields:
            item = view_menu.AppendCheckItem(wx.ID_ANY, field)
            item.Check(field in self.selected_fields)
            self.Bind(wx.EVT_MENU, self.on_toggle_column, item)
            self._column_items[item.GetId()] = field
        menu_bar.Append(view_menu, "&View")
        self.SetMenuBar(menu_bar)

    def _create_toolbar(self) -> None:
        toolbar = self.CreateToolBar()
        open_tool = toolbar.AddTool(wx.ID_OPEN, "Open", wx.ArtProvider.GetBitmap(wx.ART_FOLDER_OPEN))
        new_tool = toolbar.AddTool(wx.ID_NEW, "New", wx.ArtProvider.GetBitmap(wx.ART_NEW))
        self.Bind(wx.EVT_TOOL, self.on_open_folder, open_tool)
        self.Bind(wx.EVT_TOOL, self.on_new_requirement, new_tool)
        toolbar.Realize()

    def on_open_folder(self, event: wx.Event) -> None:
        dlg = wx.DirDialog(self, "Select requirements folder")
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self.SetTitle(f"{self._base_title} - {path}")
            self.current_dir = Path(path)
            self.requirements = []
            for fp in self.current_dir.glob("*.json"):
                try:
                    data, _ = store.load(fp)
                    self.requirements.append(data)
                except Exception:
                    continue
            self.panel.set_requirements(self.requirements)
            self.editor.Hide()
        dlg.Destroy()

    def on_requirement_selected(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if 0 <= idx < len(self.requirements):
            self.editor.load(self.requirements[idx])
            self.editor.Show()
            self.splitter.UpdateSize()

    def _on_editor_save(self) -> None:
        if not self.current_dir:
            return
        path = self.editor.save(self.current_dir)
        data = self.editor.get_data()
        for i, req in enumerate(self.requirements):
            if req.get("id") == data.get("id"):
                self.requirements[i] = data
                break
        else:
            self.requirements.append(data)
        self.panel.set_requirements(self.requirements)

    def on_toggle_column(self, event: wx.CommandEvent) -> None:
        field = self._column_items.get(event.GetId())
        if not field:
            return
        if field in self.selected_fields:
            self.selected_fields.remove(field)
        else:
            self.selected_fields.append(field)
        self.panel.set_columns(self.selected_fields)
        self._save_columns()

    def _load_columns(self) -> list[str]:
        value = self.config.Read("list_columns", "")
        return [f for f in value.split(",") if f]

    def _save_columns(self) -> None:
        self.config.Write("list_columns", ",".join(self.selected_fields))
        self.config.Flush()

    # context menu actions -------------------------------------------
    def _generate_new_id(self, base: str | None = None) -> str:
        existing = {req["id"] for req in self.requirements}
        if base:
            match = re.match(r"^(.*?)(\d+)$", base)
            if match:
                prefix, num = match.groups()
                width = len(num)
                n = int(num)
                while True:
                    n += 1
                    candidate = f"{prefix}{n:0{width}d}"
                    if candidate not in existing:
                        return candidate
            base_candidate = f"{base}_copy"
            candidate = base_candidate
            counter = 1
            while candidate in existing:
                candidate = f"{base_candidate}{counter}"
                counter += 1
            return candidate
        prefix = "REQ-"
        n = 1
        candidate = f"{prefix}{n:03d}"
        while candidate in existing:
            n += 1
            candidate = f"{prefix}{n:03d}"
        return candidate

    def on_new_requirement(self, event: wx.Event) -> None:
        new_id = self._generate_new_id()
        self.editor.new_requirement()
        self.editor.fields["id"].SetValue(new_id)
        data = self.editor.get_data()
        self.requirements.append(data)
        self.panel.set_requirements(self.requirements)
        self.editor.Show()
        self.splitter.UpdateSize()

    def on_clone_requirement(self, index: int) -> None:
        if not (0 <= index < len(self.requirements)):
            return
        source = self.requirements[index]
        new_id = self._generate_new_id(source.get("id", ""))
        data = dict(source)
        data["id"] = new_id
        data["title"] = f"(Копия) {source.get('title', '')}".strip()
        data["modified_at"] = ""
        data["revision"] = 1
        self.requirements.append(data)
        self.panel.set_requirements(self.requirements)
        self.editor.load(data, path=None, mtime=None)
        self.editor.Show()
        self.splitter.UpdateSize()

    def on_delete_requirement(self, index: int) -> None:
        if not self.current_dir or not (0 <= index < len(self.requirements)):
            return
        req = self.requirements.pop(index)
        try:
            (self.current_dir / store.filename_for(req["id"])).unlink()
        except Exception:
            pass
        self.panel.set_requirements(self.requirements)
        self.editor.Hide()
        self.splitter.UpdateSize()
