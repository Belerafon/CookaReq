"""Main application window."""

import logging
from dataclasses import fields, replace
from importlib import resources
from pathlib import Path

import wx

from ..agent import LocalAgent
from ..config import ConfigManager
from ..confirm import confirm
from ..core.model import Requirement
from ..core.doc_store import Document, LabelDef, save_document
from ..i18n import _
from ..log import logger
from ..mcp.controller import MCPController
from ..settings import AppSettings, LLMSettings, MCPSettings
from .command_dialog import CommandDialog
from .controllers import DocumentsController
from .document_tree import DocumentTree
from .editor_panel import EditorPanel
from .labels_dialog import LabelsDialog
from .list_panel import ListPanel
from .navigation import Navigation
from .requirement_model import RequirementModel
from .settings_dialog import SettingsDialog


class WxLogHandler(logging.Handler):
    """Forward log records to a ``wx.TextCtrl``."""

    def __init__(self, target: wx.TextCtrl) -> None:
        """Initialize handler redirecting log output to ``target``."""
        super().__init__()
        self._target = target
        self.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    @property
    def target(self) -> wx.TextCtrl:
        """Current ``wx.TextCtrl`` receiving log output."""
        return self._target

    @target.setter
    def target(self, new_target: wx.TextCtrl) -> None:
        """Redirect log output to ``new_target``."""
        self._target = new_target

    def emit(
        self,
        record: logging.LogRecord,
    ) -> None:  # pragma: no cover - GUI side effect
        """Append formatted ``record`` text to the log console."""

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
        """Set up main application window and controllers."""
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
        self.docs_controller: DocumentsController | None = None
        super().__init__(parent=parent, title=self._base_title)
        # Load all available icon sizes so that Windows taskbar and other
        # platforms can pick the most appropriate resolution. Using
        # ``SetIcons`` with an ``IconBundle`` ensures both the title bar and
        # the taskbar use the custom application icon.
        with resources.as_file(
            resources.files("app.resources") / "app.ico",
        ) as icon_path:
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
            on_show_trace_matrix=self.on_show_trace_matrix,
            on_new_requirement=self.on_new_requirement,
            on_run_command=self.on_run_command,
        )
        self._recent_menu = self.navigation.recent_menu
        self._recent_menu_item = self.navigation.recent_menu_item
        self.log_menu_item = self.navigation.log_menu_item
        self.manage_labels_id = self.navigation.manage_labels_id

        # split horizontally: top is main content, bottom is log console
        self.main_splitter = wx.SplitterWindow(self)
        self.doc_splitter = wx.SplitterWindow(self.main_splitter)
        self.splitter = wx.SplitterWindow(self.doc_splitter)
        self.doc_tree = DocumentTree(self.doc_splitter, on_select=self.on_document_selected)
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
        )
        self.splitter.SplitVertically(self.panel, self.editor, 300)
        self.doc_splitter.SplitVertically(self.doc_tree, self.splitter, 200)
        self.editor.Hide()

        self.log_panel = wx.Panel(self.main_splitter)
        log_sizer = wx.BoxSizer(wx.VERTICAL)
        self.log_label = wx.StaticText(self.log_panel, label=_("Error Console"))
        self.log_console = wx.TextCtrl(
            self.log_panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        log_sizer.Add(self.log_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)
        log_sizer.Add(self.log_console, 1, wx.EXPAND | wx.ALL, 5)
        self.log_panel.SetSizer(log_sizer)

        existing = next(
            (h for h in logger.handlers if isinstance(h, WxLogHandler)),
            None,
        )
        if existing:
            self.log_handler = existing
            self.log_handler.target = self.log_console
        else:
            self.log_handler = WxLogHandler(self.log_console)
            self.log_handler.setLevel(logging.WARNING)
            logger.addHandler(self.log_handler)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.main_splitter, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self._load_layout()
        self.current_dir: Path | None = None
        self.current_doc_prefix: str | None = None
        self.panel.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_requirement_selected)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        if self.auto_open_last and self.recent_dirs:
            path = Path(self.recent_dirs[0])
            if path.exists():
                self._load_directory(path)

    @property
    def recent_dirs(self) -> list[str]:
        """Return directories recently opened by the user."""

        return self.config.get_recent_dirs()


    def on_open_folder(self, _event: wx.Event) -> None:
        """Handle "Open Folder" menu action."""

        dlg = wx.DirDialog(self, _("Select requirements folder"))
        if dlg.ShowModal() == wx.ID_OK:
            self._load_directory(Path(dlg.GetPath()))
        dlg.Destroy()

    def on_open_recent(self, event: wx.CommandEvent) -> None:
        """Open a directory selected from the "recent" menu."""

        path = self.navigation.get_recent_path(event.GetId())
        if path:
            self._load_directory(path)

    def on_open_settings(
        self,
        _event: wx.Event,
    ) -> None:  # pragma: no cover - GUI event
        """Display settings dialog and apply changes."""

        dlg = SettingsDialog(
            self,
            open_last=self.auto_open_last,
            remember_sort=self.remember_sort,
            language=self.language,
            base_url=self.llm_settings.base_url,
            model=self.llm_settings.model,
            api_key=self.llm_settings.api_key or "",
            max_retries=self.llm_settings.max_retries,
            max_output_tokens=self.llm_settings.max_output_tokens or 0,
            timeout_minutes=self.llm_settings.timeout_minutes,
            stream=self.llm_settings.stream,
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
                base_url,
                model,
                api_key,
                max_retries,
                max_output_tokens,
                timeout_minutes,
                stream,
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
                base_url=base_url,
                model=model,
                api_key=api_key or None,
                max_retries=max_retries,
                max_output_tokens=max_output_tokens or None,
                timeout_minutes=timeout_minutes,
                stream=stream,
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

    def on_run_command(self, _event: wx.Event) -> None:
        """Invoke agent command dialog."""

        settings = AppSettings(llm=self.llm_settings, mcp=self.mcp_settings)
        try:
            agent = LocalAgent(settings=settings, confirm=confirm)
        except ValueError as exc:
            wx.MessageBox(str(exc), _("Warning"), style=wx.ICON_WARNING)
            return
        except Exception as exc:
            wx.MessageBox(str(exc), _("Error"), style=wx.ICON_ERROR)
            return
        dlg = CommandDialog(self, agent=agent)
        dlg.ShowModal()
        dlg.Destroy()

    def _apply_language(self) -> None:
        """Reinitialize locale and rebuild UI after language change."""
        from ..main import init_locale

        app = wx.GetApp()
        app.locale = init_locale(self.language)

        # Rebuild menus with new translations
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

    def on_manage_labels(
        self,
        _event: wx.Event,
    ) -> None:  # pragma: no cover - GUI event
        """Open dialog to manage defined labels."""

        if not (self.docs_controller and self.current_doc_prefix and self.current_dir):
            return
        doc = self.docs_controller.documents[self.current_doc_prefix]
        labels = [LabelDef(ld.key, ld.title, ld.color) for ld in doc.labels.defs]
        dlg = LabelsDialog(self, labels)
        if dlg.ShowModal() == wx.ID_OK:
            doc.labels.defs = dlg.get_labels()
            save_document(self.current_dir / self.current_doc_prefix, doc)
            labels_all, freeform = self.docs_controller.collect_labels(
                self.current_doc_prefix
            )
            self.panel.update_labels_list(labels_all)
            self.editor.update_labels_list(labels_all, freeform)
        dlg.Destroy()

    def on_show_derivation_graph(
        self,
        _event: wx.Event,
    ) -> None:  # pragma: no cover - GUI event
        """Open window displaying requirement derivation graph."""
        if not (self.current_dir and self.docs_controller):
            wx.MessageBox(_("Select requirements folder first"), _("No Data"))
            return
        links = list(self.docs_controller.iter_links())
        if not links:
            wx.MessageBox(_("No links found"), _("No Data"))
            return
        try:
            from .derivation_graph import DerivationGraphFrame
        except Exception as exc:
            wx.MessageBox(str(exc), _("Error"))
            return
        frame = DerivationGraphFrame(self, links)
        frame.Show()

    def on_show_trace_matrix(
        self,
        _event: wx.Event,
    ) -> None:  # pragma: no cover - GUI event
        """Open window displaying requirement trace links."""
        if not (self.current_dir and self.docs_controller):
            wx.MessageBox(_("Select requirements folder first"), _("No Data"))
            return
        links = list(self.docs_controller.iter_links())
        if not links:
            wx.MessageBox(_("No links found"), _("No Data"))
            return
        try:
            from .trace_matrix import TraceMatrixFrame
        except Exception as exc:  # pragma: no cover - missing wx
            wx.MessageBox(str(exc), _("Error"))
            return
        frame = TraceMatrixFrame(self, links)
        frame.Show()

    def _load_directory(self, path: Path) -> None:
        """Load requirements from ``path`` and update recent list."""
        self.docs_controller = DocumentsController(path, self.model)
        docs = self.docs_controller.load_documents()
        self.doc_tree.set_documents(docs)
        self.config.add_recent_dir(path)
        self.navigation.update_recent_menu()
        self.SetTitle(f"{self._base_title} - {path}")
        self.current_dir = path
        if docs:
            first = sorted(docs)[0]
            self.current_doc_prefix = first
            self.editor.set_directory(self.current_dir / first)
            derived_map = self.docs_controller.load_items(first)
            labels, freeform = self.docs_controller.collect_labels(first)
            self.panel.set_requirements(self.model.get_all(), derived_map)
            self.editor.update_labels_list(labels, freeform)
            self.panel.update_labels_list(labels)
        else:
            self.current_doc_prefix = None
            self.editor.set_directory(None)
            self.panel.set_requirements([], {})
            self.editor.update_labels_list([])
            self.panel.update_labels_list([])
        if self.remember_sort and self.sort_column != -1:
            self.panel.sort(self.sort_column, self.sort_ascending)
        self.editor.Hide()

    # recent directories -------------------------------------------------

    def on_document_selected(self, prefix: str) -> None:
        """Load items and labels for selected document ``prefix``."""
        if not self.docs_controller:
            return
        self.current_doc_prefix = prefix
        if self.current_dir:
            self.editor.set_directory(self.current_dir / prefix)
        derived_map = self.docs_controller.load_items(prefix)
        labels, freeform = self.docs_controller.collect_labels(prefix)
        self.panel.set_requirements(self.model.get_all(), derived_map)
        self.editor.update_labels_list(labels, freeform)
        self.panel.update_labels_list(labels)
        self.editor.Hide()
        self.splitter.UpdateSize()

    def on_requirement_selected(self, event: wx.ListEvent) -> None:
        """Load requirement into editor when selected in list."""

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
        if not (
            self.current_dir
            and self.docs_controller
            and self.current_doc_prefix
        ):
            return
        try:
            doc = self.docs_controller.documents[self.current_doc_prefix]
            self.editor.save(
                self.current_dir / self.current_doc_prefix, doc=doc
            )
        except Exception as exc:  # pragma: no cover - GUI event
            wx.MessageBox(str(exc), _("Error"), wx.ICON_ERROR)
            return
        data = self.editor.get_data()
        self.model.update(data)
        self.panel.recalc_derived_map(self.model.get_all())
        labels, freeform = self.docs_controller.collect_labels(self.current_doc_prefix)
        self.editor.update_labels_list(labels, freeform)
        self.panel.update_labels_list(labels)

    def on_toggle_column(self, event: wx.CommandEvent) -> None:
        """Show or hide column associated with menu item."""

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

    def on_toggle_log_console(self, _event: wx.CommandEvent) -> None:
        """Toggle visibility of log console panel."""

        if self.navigation.log_menu_item.IsChecked():
            sash = self.config.get_log_sash(self.GetClientSize().height - 150)
            self.log_panel.Show()
            self.main_splitter.SplitHorizontally(self.doc_splitter, self.log_panel, sash)
        else:
            if self.main_splitter.IsSplit():
                self.config.set_log_sash(self.main_splitter.GetSashPosition())
            self.main_splitter.Unsplit(self.log_panel)
            self.log_panel.Hide()
        self.config.set_log_shown(self.navigation.log_menu_item.IsChecked())

    def _load_layout(self) -> None:
        """Restore window geometry, splitter, console, and column widths."""
        self.config.restore_layout(
            self,
            self.doc_splitter,
            self.main_splitter,
            self.panel,
            self.log_panel,
            self.log_menu_item,
        )
        self.splitter.SetSashPosition(300)

    def _save_layout(self) -> None:
        """Persist window geometry, splitter, console, and column widths."""
        self.config.save_layout(self, self.doc_splitter, self.main_splitter, self.panel)

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
    def on_new_requirement(self, _event: wx.Event) -> None:
        """Create and persist a new requirement."""
        if not (self.docs_controller and self.current_doc_prefix):
            return
        new_id = self.docs_controller.next_item_id(self.current_doc_prefix)
        self.editor.new_requirement()
        self.editor.fields["id"].SetValue(str(new_id))
        data = self.editor.get_data()
        self.docs_controller.add_requirement(self.current_doc_prefix, data)
        self.panel.refresh()
        self.editor.load(data, path=None, mtime=None)
        self.editor.Show()
        self.splitter.UpdateSize()

    def on_clone_requirement(self, req_id: int) -> None:
        """Clone requirement ``req_id`` and open in editor."""
        if not (self.docs_controller and self.current_doc_prefix):
            return
        source = self.model.get_by_id(req_id)
        if not source:
            return
        new_id = self.docs_controller.next_item_id(self.current_doc_prefix)
        clone = replace(
            source,
            id=new_id,
            title=f"{_('(Copy)')} {source.title}".strip(),
            modified_at="",
            revision=1,
        )
        self.docs_controller.add_requirement(self.current_doc_prefix, clone)
        self.panel.refresh()
        self.editor.load(clone, path=None, mtime=None)
        self.editor.Show()
        self.splitter.UpdateSize()

    def _create_linked_copy(self, source: Requirement) -> Requirement:
        if not (self.docs_controller and self.current_doc_prefix):
            raise RuntimeError("Documents controller not initialized")
        new_id = self.docs_controller.next_item_id(self.current_doc_prefix)
        parent_rid = source.rid or str(source.id)
        clone = replace(
            source,
            id=new_id,
            title=f"{_('(Derived)')} {source.title}".strip(),
            modified_at="",
            revision=1,
            links=[*getattr(source, "links", []), parent_rid],
        )
        return clone

    def on_derive_requirement(self, req_id: int) -> None:
        """Create a requirement derived from ``req_id`` and open it."""

        if not (self.docs_controller and self.current_doc_prefix):
            return
        source = self.model.get_by_id(req_id)
        if not source:
            return
        clone = self._create_linked_copy(source)
        self.docs_controller.add_requirement(self.current_doc_prefix, clone)
        self.panel.record_link(source.rid or str(source.id), clone.id)
        self.panel.refresh()
        self.editor.load(clone, path=None, mtime=None)
        self.editor.Show()
        self.splitter.UpdateSize()


    def on_delete_requirement(self, req_id: int) -> None:
        """Delete requirement ``req_id`` and refresh views."""
        if not (self.docs_controller and self.current_doc_prefix):
            return
        if not self.docs_controller.delete_requirement(self.current_doc_prefix, req_id):
            return
        self.panel.refresh()
        self.editor.Hide()
        self.splitter.UpdateSize()
        labels, freeform = self.docs_controller.collect_labels(
            self.current_doc_prefix
        )
        self.editor.update_labels_list(labels, freeform)
        self.panel.update_labels_list(labels)
