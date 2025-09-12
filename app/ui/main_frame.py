"""Main application window."""

from gettext import gettext as _

import logging
from importlib import resources
import wx
from pathlib import Path
from dataclasses import fields
from typing import Dict

from app.core import store
from app.core.model import Requirement
from app.core.labels import Label
from .list_panel import ListPanel
from .editor_panel import EditorPanel
from .settings_dialog import SettingsDialog
from .requirement_model import RequirementModel
from .labels_dialog import LabelsDialog


class WxLogHandler(logging.Handler):
    """Forward log records to a ``wx.TextCtrl``."""

    def __init__(self, target: wx.TextCtrl) -> None:
        super().__init__()
        self._target = target
        self.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - GUI side effect
        if not wx.GetApp():
            return
        msg = self.format(record)
        wx.CallAfter(self._target.AppendText, msg + "\n")


class MainFrame(wx.Frame):
    """Top-level frame with basic menu and toolbar."""

    def __init__(self, parent: wx.Window | None):
        self._base_title = "CookaReq"
        self.config = wx.Config(appName="CookaReq")
        # ``Requirement`` содержит множество полей, но в списке колонок
        # нам нужны только скалярные значения. Метки отображаются особым
        # образом, поэтому добавим их вручную в конец списка.
        self.available_fields = [
            f.name for f in fields(Requirement) if f.name not in {"title", "labels"}
        ]
        self.available_fields.append("labels")
        self.selected_fields = self._load_columns()
        self.recent_dirs = self._load_recent_dirs()
        self._recent_items: Dict[int, Path] = {}
        self.auto_open_last = self.config.ReadBool("auto_open_last", False)
        self.remember_sort = self.config.ReadBool("remember_sort", False)
        self.sort_column = self.config.ReadInt("sort_column", -1)
        self.sort_ascending = self.config.ReadBool("sort_ascending", True)
        self.labels: list[Label] = []
        super().__init__(parent=parent, title=self._base_title)
        with resources.as_file(resources.files("app.resources") / "app.ico") as icon_path:
            self.SetIcon(wx.Icon(str(icon_path)))
        self.model = RequirementModel()
        self._create_menu()
        self._create_toolbar()

        # split horizontally: top is main content, bottom is log console
        self.main_splitter = wx.SplitterWindow(self)
        self.splitter = wx.SplitterWindow(self.main_splitter)
        self.panel = ListPanel(
            self.splitter,
            model=self.model,
            on_clone=self.on_clone_requirement,
            on_delete=self.on_delete_requirement,
            on_sort_changed=self._on_sort_changed,
        )
        self.panel.set_columns(self.selected_fields)
        self.editor = EditorPanel(self.splitter, on_save=self._on_editor_save)
        self.splitter.SplitVertically(self.panel, self.editor, 300)
        self.editor.Hide()

        self.log_console = wx.TextCtrl(
            self.main_splitter,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        self.log_handler = WxLogHandler(self.log_console)
        self.log_handler.setLevel(logging.WARNING)
        root_logger = logging.getLogger()
        for h in list(root_logger.handlers):
            if isinstance(h, WxLogHandler):
                root_logger.removeHandler(h)
        root_logger.addHandler(self.log_handler)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.main_splitter, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self._load_layout()
        self.current_dir: Path | None = None
        self.panel.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_requirement_selected)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        if self.auto_open_last and self.recent_dirs:
            path = Path(self.recent_dirs[0])
            if path.exists():
                self._load_directory(path)

    def _create_menu(self) -> None:
        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        open_item = file_menu.Append(wx.ID_OPEN, _("&Open Folder\tCtrl+O"))
        self._recent_menu = wx.Menu()
        self._recent_menu_item = file_menu.AppendSubMenu(self._recent_menu, _("Open &Recent"))
        settings_item = file_menu.Append(wx.ID_PREFERENCES, _("Settings"))
        labels_item = file_menu.Append(wx.ID_ANY, _("Manage Labels"))
        exit_item = file_menu.Append(wx.ID_EXIT, _("E&xit"))
        self.Bind(wx.EVT_MENU, self.on_open_folder, open_item)
        self.Bind(wx.EVT_MENU, self.on_open_settings, settings_item)
        self.Bind(wx.EVT_MENU, self.on_manage_labels, labels_item)
        self.Bind(wx.EVT_MENU, lambda evt: self.Close(), exit_item)
        self._rebuild_recent_menu()
        self.manage_labels_id = labels_item.GetId()
        menu_bar.Append(file_menu, _("&File"))

        view_menu = wx.Menu()
        self._column_items: Dict[int, str] = {}
        for field in self.available_fields:
            item = view_menu.AppendCheckItem(wx.ID_ANY, field)
            item.Check(field in self.selected_fields)
            self.Bind(wx.EVT_MENU, self.on_toggle_column, item)
            self._column_items[item.GetId()] = field
        self.log_menu_item = view_menu.AppendCheckItem(wx.ID_ANY, _("Show Error Console"))
        self.Bind(wx.EVT_MENU, self.on_toggle_log_console, self.log_menu_item)
        menu_bar.Append(view_menu, _("&View"))
        self.SetMenuBar(menu_bar)

    def _create_toolbar(self) -> None:
        toolbar = self.CreateToolBar()
        open_tool = toolbar.AddTool(wx.ID_OPEN, _("Open"), wx.ArtProvider.GetBitmap(wx.ART_FOLDER_OPEN))
        new_tool = toolbar.AddTool(wx.ID_NEW, _("New"), wx.ArtProvider.GetBitmap(wx.ART_NEW))
        self.Bind(wx.EVT_TOOL, self.on_open_folder, open_tool)
        self.Bind(wx.EVT_TOOL, self.on_new_requirement, new_tool)
        toolbar.Realize()

    def on_open_folder(self, event: wx.Event) -> None:
        dlg = wx.DirDialog(self, _("Select requirements folder"))
        if dlg.ShowModal() == wx.ID_OK:
            self._load_directory(Path(dlg.GetPath()))
        dlg.Destroy()

    def on_open_recent(self, event: wx.CommandEvent) -> None:
        path = self._recent_items.get(event.GetId())
        if path:
            self._load_directory(path)

    def on_open_settings(self, event: wx.Event) -> None:  # pragma: no cover - GUI event
        dlg = SettingsDialog(
            self,
            open_last=self.auto_open_last,
            remember_sort=self.remember_sort,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self.auto_open_last, self.remember_sort = dlg.get_values()
            self.config.WriteBool("auto_open_last", self.auto_open_last)
            self.config.WriteBool("remember_sort", self.remember_sort)
            self.config.Flush()
        dlg.Destroy()

    def on_manage_labels(self, _event: wx.Event) -> None:  # pragma: no cover - GUI event
        if not self.current_dir:
            return
        dlg = LabelsDialog(self, self.labels)
        if dlg.ShowModal() == wx.ID_OK:
            self.labels = dlg.get_labels()
            try:
                store.save_labels(self.current_dir, self.labels)
            except Exception as exc:  # pragma: no cover - disk errors
                logging.warning("Failed to save labels: %s", exc)
            self.panel.refresh()
            names = [lbl.name for lbl in self.labels]
            self.editor.update_labels_list(names)
            self.panel.update_labels_list(names)
        dlg.Destroy()

    def _load_directory(self, path: Path) -> None:
        """Load requirements from ``path`` and update recent list."""
        self._add_recent_dir(path)
        self.SetTitle(f"{self._base_title} - {path}")
        self.current_dir = path
        self.labels = store.load_labels(self.current_dir)
        items: list[dict] = []
        for fp in self.current_dir.glob("*.json"):
            if fp.name == store.LABELS_FILENAME:
                continue
            try:
                data, _ = store.load(fp)
                items.append(data)
            except Exception as exc:
                logging.warning("Failed to load %s: %s", fp, exc)
                continue
        self.panel.set_requirements(items)
        if self.remember_sort and self.sort_column != -1:
            self.panel.sort(self.sort_column, self.sort_ascending)
        self.editor.Hide()
        self._sync_labels()

    def _sync_labels(self) -> None:
        """Synchronize ``labels.json`` with labels used by requirements."""
        if not self.current_dir:
            return
        existing_colors = {lbl.name: lbl.color for lbl in self.labels}
        names = sorted({l for req in self.model.get_all() for l in req.get("labels", [])})
        self.labels = [Label(name=n, color=existing_colors.get(n, "#ffffff")) for n in names]
        try:
            store.save_labels(self.current_dir, self.labels)
        except Exception as exc:
            logging.warning("Failed to save labels: %s", exc)
        names = [lbl.name for lbl in self.labels]
        self.editor.update_labels_list(names)
        self.panel.update_labels_list(names)

    # recent directories -------------------------------------------------
    def _load_recent_dirs(self) -> list[str]:
        value = self.config.Read("recent_dirs", "")
        return [p for p in value.split("|") if p]

    def _save_recent_dirs(self) -> None:
        self.config.Write("recent_dirs", "|".join(self.recent_dirs))
        self.config.Flush()

    def _add_recent_dir(self, path: Path) -> None:
        p = str(path)
        if p in self.recent_dirs:
            self.recent_dirs.remove(p)
        self.recent_dirs.insert(0, p)
        del self.recent_dirs[5:]
        self._save_recent_dirs()
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        for item in list(self._recent_menu.GetMenuItems()):
            self._recent_menu.Delete(item)
        self._recent_items.clear()
        for p in self.recent_dirs:
            item = self._recent_menu.Append(wx.ID_ANY, p)
            self.Bind(wx.EVT_MENU, self.on_open_recent, item)
            self._recent_items[item.GetId()] = Path(p)
        self._recent_menu_item.Enable(bool(self.recent_dirs))

    def on_requirement_selected(self, event: wx.ListEvent) -> None:
        req_id = event.GetData()
        req = self.model.get_by_id(req_id)
        if req:
            self.editor.load(req)
            self.editor.Show()
            self.splitter.UpdateSize()

    def _on_editor_save(self) -> None:
        if not self.current_dir:
            return
        try:
            self.editor.save(self.current_dir)
        except store.ConflictError:  # pragma: no cover - GUI event
            wx.MessageBox(
                _("File was modified on disk. Save cancelled."),
                _("Error"),
                wx.ICON_ERROR,
            )
            return
        except Exception as exc:  # pragma: no cover - GUI event
            wx.MessageBox(str(exc), _("Error"), wx.ICON_ERROR)
            return
        data = self.editor.get_data()
        self.model.update(data)
        self.panel.refresh()
        self._sync_labels()

    def on_toggle_column(self, event: wx.CommandEvent) -> None:
        field = self._column_items.get(event.GetId())
        if not field:
            return
        if field in self.selected_fields:
            self.selected_fields.remove(field)
        else:
            self.selected_fields.append(field)
        self.panel.set_columns(self.selected_fields)
        self.panel.load_column_widths(self.config)
        self.panel.load_column_order(self.config)
        self._save_columns()

    def on_toggle_log_console(self, event: wx.CommandEvent) -> None:
        if self.log_menu_item.IsChecked():
            sash = self.config.ReadInt("log_sash", self.GetClientSize().height - 150)
            self.main_splitter.SplitHorizontally(self.splitter, self.log_console, sash)
        else:
            if self.main_splitter.IsSplit():
                self.config.WriteInt("log_sash", self.main_splitter.GetSashPosition())
            self.main_splitter.Unsplit(self.log_console)
        self.config.WriteBool("log_shown", self.log_menu_item.IsChecked())
        self.config.Flush()

    def _load_columns(self) -> list[str]:
        value = self.config.Read("list_columns", "")
        return [f for f in value.split(",") if f]

    def _save_columns(self) -> None:
        self.config.Write("list_columns", ",".join(self.selected_fields))
        self.config.Flush()

    def _load_layout(self) -> None:
        """Restore window geometry, splitter, console, and column widths."""
        w = self.config.ReadInt("win_w", 800)
        h = self.config.ReadInt("win_h", 600)
        w = max(400, min(w, 3000))
        h = max(300, min(h, 2000))
        self.SetSize((w, h))
        x = self.config.ReadInt("win_x", -1)
        y = self.config.ReadInt("win_y", -1)
        if x != -1 and y != -1:
            self.SetPosition((x, y))
        else:
            self.Centre()
        sash = self.config.ReadInt("sash_pos", 300)
        client_w = self.GetClientSize().width
        sash = max(100, min(sash, max(client_w - 100, 100)))
        self.splitter.SetSashPosition(sash)
        self.panel.load_column_widths(self.config)
        self.panel.load_column_order(self.config)

        log_shown = self.config.ReadBool("log_shown", False)
        log_sash = self.config.ReadInt("log_sash", self.GetClientSize().height - 150)
        if log_shown:
            self.main_splitter.SplitHorizontally(self.splitter, self.log_console, log_sash)
            if hasattr(self, "log_menu_item"):
                self.log_menu_item.Check(True)
        else:
            self.main_splitter.Initialize(self.splitter)
            if hasattr(self, "log_menu_item"):
                self.log_menu_item.Check(False)

    def _save_layout(self) -> None:
        """Persist window geometry, splitter, console, and column widths."""
        w, h = self.GetSize()
        x, y = self.GetPosition()
        self.config.WriteInt("win_w", w)
        self.config.WriteInt("win_h", h)
        self.config.WriteInt("win_x", x)
        self.config.WriteInt("win_y", y)
        self.config.WriteInt("sash_pos", self.splitter.GetSashPosition())
        if self.main_splitter.IsSplit():
            self.config.WriteBool("log_shown", True)
            self.config.WriteInt("log_sash", self.main_splitter.GetSashPosition())
        else:
            self.config.WriteBool("log_shown", False)
        self.panel.save_column_widths(self.config)
        self.panel.save_column_order(self.config)
        self.config.Flush()

    def _on_close(self, event: wx.Event) -> None:  # pragma: no cover - GUI event
        self._save_layout()
        logging.getLogger().removeHandler(self.log_handler)
        event.Skip()

    def _on_sort_changed(self, column: int, ascending: bool) -> None:
        if not self.remember_sort:
            return
        self.sort_column = column
        self.sort_ascending = ascending
        self.config.WriteInt("sort_column", column)
        self.config.WriteBool("sort_ascending", ascending)
        self.config.Flush()

    # context menu actions -------------------------------------------
    def _generate_new_id(self) -> int:
        existing = {req["id"] for req in self.model.get_all()}
        return max(existing, default=0) + 1

    def on_new_requirement(self, event: wx.Event) -> None:
        new_id = self._generate_new_id()
        self.editor.new_requirement()
        self.editor.fields["id"].SetValue(str(new_id))
        data = self.editor.get_data()
        self.model.add(data)
        self.panel.refresh()
        self.editor.Show()
        self.splitter.UpdateSize()

    def on_clone_requirement(self, req_id: int) -> None:
        source = self.model.get_by_id(req_id)
        if not source:
            return
        new_id = self._generate_new_id()
        data = dict(source)
        data["id"] = new_id
        data["title"] = f"{_('(Copy)')} {source.get('title', '')}".strip()
        data["modified_at"] = ""
        data["revision"] = 1
        self.model.add(data)
        self.panel.refresh()
        self.editor.load(data, path=None, mtime=None)
        self.editor.Show()
        self.splitter.UpdateSize()

    def on_delete_requirement(self, req_id: int) -> None:
        if not self.current_dir:
            return
        req = self.model.get_by_id(req_id)
        if not req:
            return
        self.model.delete(req_id)
        try:
            (self.current_dir / store.filename_for(req["id"])).unlink()
        except Exception:
            pass
        self.panel.refresh()
        self.editor.Hide()
        self.splitter.UpdateSize()
        self._sync_labels()
