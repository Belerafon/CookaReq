"""Main application window."""

from ..i18n import _

import logging
from importlib import resources
from pathlib import Path
from dataclasses import fields, replace

import wx

from ..log import logger

from ..config import ConfigManager
from ..core import requirements as req_ops
from ..core.model import Requirement, DerivationLink
from ..core.labels import Label
from ..mcp.controller import MCPController
from ..settings import AppSettings, LLMSettings, MCPSettings
from ..agent import LocalAgent
from ..confirm import confirm
from .list_panel import ListPanel
from .editor_panel import EditorPanel
from .settings_dialog import SettingsDialog
from .requirement_model import RequirementModel
from .labels_dialog import LabelsDialog
from .navigation import Navigation
from .command_dialog import CommandDialog
from .controllers import RequirementsController, LabelsController
from ..core.repository import FileRequirementRepository


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
    """Top-level frame coordinating UI subsystems."""

    def __init__(
        self,
        parent: wx.Window | None,
        *,
        config: ConfigManager | None = None,
        model: RequirementModel | None = None,
    ) -> None:
        self._base_title = "CookaReq"
        self.config = config if config is not None else ConfigManager()
        self.model = model if model is not None else RequirementModel()
        # ``Requirement`` содержит множество полей, но в списке колонок
        # нам нужны только скалярные значения. Метки отображаются особым
        # образом, поэтому добавим их вручную в конец списка.
        self.available_fields = [
            f.name for f in fields(Requirement) if f.name not in {"title", "labels"}
        ]
        self.available_fields.append("labels")
        self.available_fields.append("derived_count")
        self.selected_fields = self.config.get_columns()
        self.auto_open_last = self.config.get_auto_open_last()
        self.remember_sort = self.config.get_remember_sort()
        self.language = self.config.get_language()
        self.sort_column, self.sort_ascending = self.config.get_sort_settings()
        self.llm_settings = self.config.get_llm_settings()
        self.mcp_settings = self.config.get_mcp_settings()
        self.mcp = MCPController()
        self.mcp.start(self.mcp_settings)
        self.req_controller: RequirementsController | None = None
        self.labels_controller: LabelsController | None = None
        super().__init__(parent=parent, title=self._base_title)
        # Load all available icon sizes so that Windows taskbar and other
        # platforms can pick the most appropriate resolution. Using
        # ``SetIcons`` with an ``IconBundle`` ensures both the title bar and
        # the taskbar use the custom application icon.
        with resources.as_file(resources.files("app.resources") / "app.ico") as icon_path:
            icons = wx.IconBundle(str(icon_path), wx.BITMAP_TYPE_ANY)
            self.SetIcons(icons)
        self.navigation = Navigation(
            self,
            self.config,
            available_fields=self.available_fields,
            selected_fields=self.selected_fields,
            on_open_folder=self.on_open_folder,
            on_open_settings=self.on_open_settings,
            on_manage_labels=self.on_manage_labels,
            on_open_recent=self.on_open_recent,
            on_toggle_column=self.on_toggle_column,
            on_toggle_log_console=self.on_toggle_log_console,
            on_show_derivation_graph=self.on_show_derivation_graph,
            on_new_requirement=self.on_new_requirement,
            on_run_command=self.on_run_command,
        )
        self._recent_menu = self.navigation.recent_menu
        self._recent_menu_item = self.navigation.recent_menu_item
        self.log_menu_item = self.navigation.log_menu_item
        self.manage_labels_id = self.navigation.manage_labels_id

        # split horizontally: top is main content, bottom is log console
        self.main_splitter = wx.SplitterWindow(self)
        self.splitter = wx.SplitterWindow(self.main_splitter)
        self.panel = ListPanel(
            self.splitter,
            model=self.model,
            on_clone=self.on_clone_requirement,
            on_delete=self.on_delete_requirement,
            on_sort_changed=self._on_sort_changed,
            on_derive=self.on_derive_requirement,
        )
        self.panel.set_columns(self.selected_fields)
        self.editor = EditorPanel(
            self.splitter,
            on_save=self._on_editor_save,
            on_add_derived=self.on_add_derived_requirement,
        )
        self.splitter.SplitVertically(self.panel, self.editor, 300)
        self.editor.Hide()

        self.log_console = wx.TextCtrl(
            self.main_splitter,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        existing = next((h for h in logger.handlers if isinstance(h, WxLogHandler)), None)
        if existing:
            self.log_handler = existing
            self.log_handler._target = self.log_console
        else:
            self.log_handler = WxLogHandler(self.log_console)
            self.log_handler.setLevel(logging.WARNING)
            logger.addHandler(self.log_handler)

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

    @property
    def recent_dirs(self) -> list[str]:
        return self.config.get_recent_dirs()

    @property
    def labels(self) -> list[Label]:
        return self.labels_controller.labels if self.labels_controller else []

    def on_open_folder(self, event: wx.Event) -> None:
        dlg = wx.DirDialog(self, _("Select requirements folder"))
        if dlg.ShowModal() == wx.ID_OK:
            self._load_directory(Path(dlg.GetPath()))
        dlg.Destroy()

    def on_open_recent(self, event: wx.CommandEvent) -> None:
        path = self.navigation.get_recent_path(event.GetId())
        if path:
            self._load_directory(path)

    def on_open_settings(self, event: wx.Event) -> None:  # pragma: no cover - GUI event
        dlg = SettingsDialog(
            self,
            open_last=self.auto_open_last,
            remember_sort=self.remember_sort,
            language=self.language,
            api_base=self.llm_settings.api_base,
            model=self.llm_settings.model,
            api_key=self.llm_settings.api_key,
            timeout=self.llm_settings.timeout,
            host=self.mcp_settings.host,
            port=self.mcp_settings.port,
            base_path=self.mcp_settings.base_path,
            require_token=self.mcp_settings.require_token,
            token=self.mcp_settings.token,
        )
        if dlg.ShowModal() == wx.ID_OK:
            (
                self.auto_open_last,
                self.remember_sort,
                self.language,
                api_base,
                model,
                api_key,
                timeout,
                host,
                port,
                base_path,
                require_token,
                token,
            ) = dlg.get_values()
            changed = (
                host != self.mcp_settings.host
                or port != self.mcp_settings.port
                or base_path != self.mcp_settings.base_path
                or require_token != self.mcp_settings.require_token
                or token != self.mcp_settings.token
            )
            self.llm_settings = LLMSettings(
                api_base=api_base,
                model=model,
                api_key=api_key,
                timeout=timeout,
            )
            self.mcp_settings = MCPSettings(
                host=host,
                port=port,
                base_path=base_path,
                require_token=require_token,
                token=token,
            )
            self.config.set_auto_open_last(self.auto_open_last)
            self.config.set_remember_sort(self.remember_sort)
            self.config.set_language(self.language)
            self.config.set_llm_settings(self.llm_settings)
            self.config.set_mcp_settings(self.mcp_settings)
            if changed:
                self.mcp.stop()
                self.mcp.start(self.mcp_settings)
            self._apply_language()
        dlg.Destroy()

    def on_run_command(self, event: wx.Event) -> None:
        settings = AppSettings(llm=self.llm_settings, mcp=self.mcp_settings)
        agent = LocalAgent(settings=settings, confirm=confirm)
        dlg = CommandDialog(self, agent=agent)
        dlg.ShowModal()
        dlg.Destroy()

    def _apply_language(self) -> None:
        """Reinitialize locale and rebuild UI after language change."""
        from ..main import init_locale

        app = wx.GetApp()
        app.locale = init_locale(self.language)

        # Rebuild menus and toolbar with new translations
        self.navigation.rebuild(self.selected_fields)
        self._recent_menu = self.navigation.recent_menu
        self._recent_menu_item = self.navigation.recent_menu_item
        self.log_menu_item = self.navigation.log_menu_item
        self.manage_labels_id = self.navigation.manage_labels_id

        # Replace panels to update all labels
        old_panel, old_editor = self.panel, self.editor
        self.panel = ListPanel(
            self.splitter,
            model=self.model,
            on_clone=self.on_clone_requirement,
            on_delete=self.on_delete_requirement,
            on_sort_changed=self._on_sort_changed,
            on_derive=self.on_derive_requirement,
        )
        self.panel.set_columns(self.selected_fields)
        self.panel.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_requirement_selected)

        self.editor = EditorPanel(
            self.splitter,
            on_save=self._on_editor_save,
            on_add_derived=self.on_add_derived_requirement,
        )
        self.editor.Hide()

        self.splitter.ReplaceWindow(old_panel, self.panel)
        self.splitter.ReplaceWindow(old_editor, self.editor)
        old_panel.Destroy()
        old_editor.Destroy()

        # Restore layout and reload data if any directory is open
        self._load_layout()
        if self.current_dir:
            self._load_directory(self.current_dir)
        else:
            self.panel.set_requirements(self.model.get_all(), {})

        self.Layout()

    def on_manage_labels(self, _event: wx.Event) -> None:  # pragma: no cover - GUI event
        if not self.labels_controller:
            return
        dlg = LabelsDialog(self, self.labels_controller.labels)
        if dlg.ShowModal() == wx.ID_OK:
            new_labels = dlg.get_labels()
            used = self.labels_controller.update_labels(
                new_labels, remove_from_requirements=False
            )
            if used:
                lines = [f"{k}: {', '.join(map(str, v))}" for k, v in used.items()]
                msg = _(
                    "Labels in use will be removed from requirements:\n%s\nContinue?"
                ) % "\n".join(lines)
                if not confirm(msg):
                    dlg.Destroy()
                    return
                self.labels_controller.update_labels(
                    new_labels, remove_from_requirements=True
                )
                self.panel.refresh()
            self.editor.update_labels_list(self.labels_controller.labels)
            self.panel.update_labels_list(self.labels_controller.labels)
        dlg.Destroy()

    def on_show_derivation_graph(self, _event: wx.Event) -> None:  # pragma: no cover - GUI event
        """Open window displaying requirement derivation graph."""
        if not self.current_dir:
            wx.MessageBox(_("Select requirements folder first"), _("No Data"))
            return
        try:
            from .derivation_graph import DerivationGraphFrame
        except Exception as exc:
            wx.MessageBox(str(exc), _("Error"))
            return
        reqs = self.model.get_all()
        if not reqs:
            wx.MessageBox(_("No requirements loaded"), _("No Data"))
            return
        frame = DerivationGraphFrame(self, reqs)
        frame.Show()

    def _load_directory(self, path: Path) -> None:
        """Load requirements from ``path`` and update recent list."""
        repo = FileRequirementRepository()
        self.req_controller = RequirementsController(
            self.config, self.model, path, repo
        )
        self.labels_controller = LabelsController(self.config, self.model, path)
        self.labels_controller.load_labels()
        derived_map = self.req_controller.load_directory()
        self.navigation.update_recent_menu()
        self.SetTitle(f"{self._base_title} - {path}")
        self.current_dir = path
        self.editor.set_directory(self.current_dir)
        self.panel.set_requirements(self.model.get_all(), derived_map)
        if self.remember_sort and self.sort_column != -1:
            self.panel.sort(self.sort_column, self.sort_ascending)
        self.editor.Hide()
        self.labels_controller.sync_labels()
        self.editor.update_labels_list(self.labels_controller.labels)
        self.panel.update_labels_list(self.labels_controller.labels)

    # recent directories -------------------------------------------------

    def on_requirement_selected(self, event: wx.ListEvent) -> None:
        index = event.GetIndex()
        if index == wx.NOT_FOUND:
            return
        req_id = self.panel.list.GetItemData(index)
        req = self.model.get_by_id(req_id)
        if req:
            self.editor.load(req)
            self.editor.Show()
            self.editor.Layout()
            self.splitter.UpdateSize()

    def _on_editor_save(self) -> None:
        if not self.current_dir:
            return
        try:
            self.editor.save(self.current_dir)
        except req_ops.ConflictError:  # pragma: no cover - GUI event
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
        self.panel.recalc_derived_map(self.model.get_all())
        if self.labels_controller:
            self.labels_controller.sync_labels()
            self.editor.update_labels_list(self.labels_controller.labels)
            self.panel.update_labels_list(self.labels_controller.labels)

    def on_toggle_column(self, event: wx.CommandEvent) -> None:
        field = self.navigation.get_field_for_id(event.GetId())
        if not field:
            return
        if field in self.selected_fields:
            self.selected_fields.remove(field)
        else:
            self.selected_fields.append(field)
        self.panel.set_columns(self.selected_fields)
        self.panel.load_column_widths(self.config)
        self.panel.load_column_order(self.config)
        self.config.set_columns(self.selected_fields)

    def on_toggle_log_console(self, event: wx.CommandEvent) -> None:
        if self.navigation.log_menu_item.IsChecked():
            sash = self.config.get_log_sash(self.GetClientSize().height - 150)
            self.log_console.Show()
            self.main_splitter.SplitHorizontally(self.splitter, self.log_console, sash)
        else:
            if self.main_splitter.IsSplit():
                self.config.set_log_sash(self.main_splitter.GetSashPosition())
            self.main_splitter.Unsplit(self.log_console)
            self.log_console.Hide()
        self.config.set_log_shown(self.navigation.log_menu_item.IsChecked())

    def _load_layout(self) -> None:
        """Restore window geometry, splitter, console, and column widths."""
        self.config.restore_layout(
            self,
            self.splitter,
            self.main_splitter,
            self.panel,
            self.log_console,
            self.log_menu_item,
        )

    def _save_layout(self) -> None:
        """Persist window geometry, splitter, console, and column widths."""
        self.config.save_layout(self, self.splitter, self.main_splitter, self.panel)

    def _on_close(self, event: wx.Event) -> None:  # pragma: no cover - GUI event
        self._save_layout()
        if self.log_handler in logger.handlers:
            logger.removeHandler(self.log_handler)
        self.mcp.stop()
        event.Skip()

    def _on_sort_changed(self, column: int, ascending: bool) -> None:
        if not self.remember_sort:
            return
        self.sort_column = column
        self.sort_ascending = ascending
        self.config.set_sort_settings(column, ascending)

    # context menu actions -------------------------------------------
    def on_new_requirement(self, event: wx.Event) -> None:
        if not self.req_controller:
            return
        new_id = self.req_controller.generate_new_id()
        self.editor.new_requirement()
        self.editor.fields["id"].SetValue(str(new_id))
        data = self.editor.get_data()
        self.req_controller.add_requirement(data)
        self.panel.refresh()
        self.editor.Show()
        self.splitter.UpdateSize()

    def on_clone_requirement(self, req_id: int) -> None:
        if not self.req_controller:
            return
        clone = self.req_controller.clone_requirement(req_id)
        if not clone:
            return
        self.panel.refresh()
        self.editor.load(clone, path=None, mtime=None)
        self.editor.Show()
        self.splitter.UpdateSize()

    def _create_derived_from(self, source: Requirement) -> Requirement:
        if not self.req_controller:
            raise RuntimeError("Requirements controller not initialized")
        new_id = self.req_controller.generate_new_id()
        clone = replace(
            source,
            id=new_id,
            title=f"{_('(Derived)')} {source.title}".strip(),
            modified_at="",
            revision=1,
        )
        link = DerivationLink(
            source_id=source.id, source_revision=source.revision, suspect=False
        )
        clone.derived_from = list(source.derived_from) + [link]
        clone.derivation = None
        return clone

    def on_derive_requirement(self, req_id: int) -> None:
        source = self.model.get_by_id(req_id)
        if not source:
            return
        clone = self._create_derived_from(source)
        self.model.add(clone)
        self.panel.add_derived_link(source.id, clone.id)
        self.panel.refresh()
        self.editor.load(clone, path=None, mtime=None)
        self.editor.Show()
        self.splitter.UpdateSize()

    def on_add_derived_requirement(self, source: Requirement) -> None:
        clone = self._create_derived_from(source)
        self.model.add(clone)
        self.panel.add_derived_link(source.id, clone.id)
        self.panel.refresh()
        self.editor.load(clone, path=None, mtime=None)
        self.editor.Show()
        self.splitter.UpdateSize()

    def on_delete_requirement(self, req_id: int) -> None:
        if not self.req_controller or not self.labels_controller:
            return
        if not self.req_controller.delete_requirement(req_id):
            return
        self.panel.refresh()
        self.editor.Hide()
        self.splitter.UpdateSize()
        self.labels_controller.sync_labels()
        self.editor.update_labels_list(self.labels_controller.labels)
        self.panel.update_labels_list(self.labels_controller.labels)
