"""Main application window."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import fields, replace
from importlib import resources
from pathlib import Path

import wx

from ..agent import LocalAgent
from ..config import ConfigManager
from ..confirm import confirm
from ..core.model import Requirement
from ..core.document_store import (
    Document,
    LabelDef,
    RequirementIDCollisionError,
    ValidationError,
    save_document,
)
from ..i18n import _
from ..log import logger
from ..mcp.controller import MCPController
from ..settings import AppSettings, LLMSettings, MCPSettings
from .agent_chat_panel import AgentChatPanel
from .controllers import DocumentsController
from .document_dialog import DocumentPropertiesDialog
from .document_tree import DocumentTree
from .detached_editor import DetachedEditorFrame
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
        if self.mcp_settings.auto_start:
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
            on_toggle_requirement_editor=self.on_toggle_requirement_editor,
            on_toggle_agent_chat=self.on_toggle_agent_chat,
            on_show_derivation_graph=self.on_show_derivation_graph,
            on_show_trace_matrix=self.on_show_trace_matrix,
            on_new_requirement=self.on_new_requirement,
            on_run_command=self.on_run_command,
        )
        self._recent_menu = self.navigation.recent_menu
        self._recent_menu_item = self.navigation.recent_menu_item
        self.log_menu_item = self.navigation.log_menu_item
        self.editor_menu_item = self.navigation.editor_menu_item
        self.agent_chat_menu_item = self.navigation.agent_chat_menu_item
        self.manage_labels_id = self.navigation.manage_labels_id
        self._detached_editors: dict[tuple[str, int], DetachedEditorFrame] = {}

        # split horizontally: top is main content, bottom is log console
        self.main_splitter = wx.SplitterWindow(self)
        self._disable_splitter_unsplit(self.main_splitter)
        self.doc_splitter = wx.SplitterWindow(self.main_splitter)
        self._disable_splitter_unsplit(self.doc_splitter)
        self._doc_tree_min_pane = 160
        self.doc_splitter.SetMinimumPaneSize(self._doc_tree_min_pane)
        self.doc_splitter.Bind(
            wx.EVT_SPLITTER_SASH_POS_CHANGED,
            self._on_doc_splitter_sash_changed,
        )
        self.agent_splitter = wx.SplitterWindow(self.doc_splitter)
        self._disable_splitter_unsplit(self.agent_splitter)
        self.agent_splitter.SetMinimumPaneSize(280)
        self.splitter = wx.SplitterWindow(self.agent_splitter)
        self._disable_splitter_unsplit(self.splitter)
        self.splitter.SetMinimumPaneSize(200)
        (
            self.doc_tree_container,
            self.doc_tree_label,
            self.doc_tree,
        ) = self._create_section(
            self.doc_splitter,
            label=_("Hierarchy"),
            factory=lambda parent: DocumentTree(
                parent,
                on_select=self.on_document_selected,
                on_new_document=self.on_new_document,
                on_rename_document=self.on_rename_document,
                on_delete_document=self.on_delete_document,
            ),
            header_factory=lambda parent: (
                self._create_doc_tree_toggle(parent),
            ),
        )
        self.doc_tree.tree.Bind(wx.EVT_TREE_SEL_CHANGING, self._on_doc_changing)
        (
            self.list_container,
            self.list_label,
            self.panel,
        ) = self._create_section(
            self.splitter,
            label=_("Requirements"),
            factory=lambda parent: ListPanel(
                parent,
                model=self.model,
                on_clone=self.on_clone_requirement,
                on_delete=self.on_delete_requirement,
                on_delete_many=self.on_delete_requirements,
                on_sort_changed=self._on_sort_changed,
                on_derive=self.on_derive_requirement,
            ),
        )
        self.panel.set_columns(self.selected_fields)
        self.panel.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_requirement_activated)
        (
            self.editor_container,
            self.editor_label,
            self.editor,
        ) = self._create_section(
            self.splitter,
            label=_("Editor"),
            factory=lambda parent: EditorPanel(
                parent,
                on_save=self._on_editor_save,
            ),
        )
        self.splitter.SplitVertically(self.list_container, self.editor_container, 300)
        (
            self.agent_container,
            self.agent_label,
            self.agent_panel,
        ) = self._create_section(
            self.agent_splitter,
            label=_("Agent Chat"),
            factory=lambda parent: AgentChatPanel(
                parent,
                agent_supplier=self._create_agent,
            ),
        )
        self._hide_agent_section()
        self.agent_splitter.Initialize(self.splitter)
        self.doc_splitter.SplitVertically(
            self.doc_tree_container,
            self.agent_splitter,
            200,
        )
        self._doc_tree_collapsed = False
        self._doc_tree_saved_sash = self.doc_splitter.GetSashPosition()
        self._hide_editor_panel()

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
        self._selected_requirement_id: int | None = None
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

    def _create_section(
        self,
        parent: wx.Window,
        *,
        label: str,
        factory: Callable[[wx.Window], wx.Window],
        header_factory: Callable[[wx.Window], Sequence[wx.Window]] | None = None,
    ) -> tuple[wx.Panel, wx.StaticText, wx.Window]:
        """Build a titled container holding the widget returned by ``factory``."""

        container = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)
        label_ctrl = wx.StaticText(container, label=label)
        if header_factory is not None:
            header = wx.BoxSizer(wx.HORIZONTAL)
            header.Add(label_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
            for ctrl in header_factory(container):
                header.Add(ctrl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
            sizer.Add(header, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)
        else:
            sizer.Add(label_ctrl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
        content = factory(container)
        sizer.Add(content, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 3)
        container.SetSizer(sizer)
        return container, label_ctrl, content

    def _create_doc_tree_toggle(self, parent: wx.Window) -> wx.Button:
        """Create collapse/expand toggle for the document tree pane."""

        self.doc_tree_toggle = wx.Button(
            parent,
            label="<<<",
            style=wx.BU_EXACTFIT,
        )
        self.doc_tree_toggle.SetMinSize(self.doc_tree_toggle.GetBestSize())
        self.doc_tree_toggle.SetToolTip(_("Hide hierarchy"))
        self.doc_tree_toggle.Bind(wx.EVT_BUTTON, self._on_toggle_doc_tree)
        return self.doc_tree_toggle

    def _on_toggle_doc_tree(self, _event: wx.Event) -> None:
        """Collapse or expand the document hierarchy panel."""

        if self._doc_tree_collapsed:
            self._expand_doc_tree(update_config=True)
        else:
            self._collapse_doc_tree(update_config=True)

    def _collapse_doc_tree(self, *, update_config: bool) -> None:
        """Hide the tree while keeping the toggle handle accessible."""

        if self._doc_tree_collapsed:
            return
        sash = self.doc_splitter.GetSashPosition()
        self._doc_tree_saved_sash = max(sash, self._doc_tree_min_pane)
        self.doc_tree.Hide()
        self.doc_tree_label.Hide()
        self.doc_splitter.SetMinimumPaneSize(0)
        handle = self._collapsed_doc_tree_width()
        self.doc_tree_container.SetMinSize(wx.Size(handle, -1))
        self.doc_tree_container.Layout()
        self._doc_tree_collapsed = True
        self.doc_splitter.SetSashPosition(handle, True)
        self.doc_tree_toggle.SetLabel(">>>")
        self.doc_tree_toggle.SetToolTip(_("Show hierarchy"))
        if update_config:
            self.config.set_doc_tree_saved_sash(self._doc_tree_saved_sash)
            self.config.set_doc_tree_collapsed(True)

    def _expand_doc_tree(self, *, update_config: bool) -> None:
        """Restore the tree pane to its saved width."""

        self.doc_tree_container.SetMinSize(wx.Size(-1, -1))
        self.doc_tree_label.Show()
        self.doc_tree.Show()
        self.doc_splitter.SetMinimumPaneSize(self._doc_tree_min_pane)
        width = self._desired_doc_tree_sash()
        self._doc_tree_collapsed = False
        self.doc_splitter.SetSashPosition(width, True)
        self.doc_tree_toggle.SetLabel("<<<")
        self.doc_tree_toggle.SetToolTip(_("Hide hierarchy"))
        self.doc_tree_container.Layout()
        if update_config:
            self._doc_tree_saved_sash = width
            self.config.set_doc_tree_saved_sash(self._doc_tree_saved_sash)
            self.config.set_doc_tree_collapsed(False)

    def _collapsed_doc_tree_width(self) -> int:
        """Return minimal width required to display the toggle handle."""

        margin = 8  # header padding (left/right = 4)
        return self.doc_tree_toggle.GetBestSize().width + margin

    def _desired_doc_tree_sash(self) -> int:
        """Clamp saved sash position to current splitter dimensions."""

        saved = max(self._doc_tree_saved_sash, self._doc_tree_min_pane)
        width = self.doc_splitter.GetClientSize().width
        if width <= 0:
            width = self.agent_splitter.GetClientSize().width
        if width <= 0:
            width = self.GetClientSize().width
        if width <= 0:
            width = saved
        max_left = max(width - self._doc_tree_min_pane, self._doc_tree_min_pane)
        return max(self._doc_tree_min_pane, min(saved, max_left))

    def _on_doc_splitter_sash_changed(self, event: wx.SplitterEvent) -> None:
        """Remember latest sash position when the tree pane is visible."""

        event.Skip()
        if self._doc_tree_collapsed:
            return
        pos = event.GetSashPosition()
        if pos > 0:
            self._doc_tree_saved_sash = pos

    def _show_editor_panel(self) -> None:
        """Display the editor section alongside its container."""

        if not self.splitter.IsSplit():
            sash = self.config.get_editor_sash(self._default_editor_sash())
            self.splitter.SplitVertically(
                self.list_container,
                self.editor_container,
                sash,
            )
        self.editor_container.Show()
        self.editor.Show()
        self.editor_container.Layout()
        self.editor.Layout()

    def _hide_editor_panel(self) -> None:
        """Hide the editor section and its container."""

        self.editor.Hide()
        self.editor_container.Hide()

    def _is_editor_visible(self) -> bool:
        """Return ``True`` when the main editor pane is enabled."""

        return bool(self.editor_menu_item and self.editor_menu_item.IsChecked())

    def _show_agent_section(self) -> None:
        """Display the agent chat section and ensure layout refresh."""

        self.agent_container.Show()
        self.agent_panel.Show()
        self.agent_container.Layout()
        self.agent_panel.Layout()

    def _hide_agent_section(self) -> None:
        """Hide the agent chat widgets to free screen space."""

        self.agent_panel.Hide()
        self.agent_container.Hide()

    def _update_section_labels(self) -> None:
        """Refresh captions for titled sections according to current locale."""

        self.doc_tree_label.SetLabel(_("Hierarchy"))
        self.list_label.SetLabel(_("Requirements"))
        self.editor_label.SetLabel(_("Editor"))
        self.agent_label.SetLabel(_("Agent Chat"))
        self.log_label.SetLabel(_("Error Console"))


    def _confirm_discard_changes(self) -> bool:
        """Ask user to discard unsaved edits if editor has pending changes."""

        if not getattr(self, "editor", None):
            return True
        if not self.editor.is_dirty():
            return True
        if confirm(_("Discard unsaved changes?")):
            self.editor.mark_clean()
            return True
        return False


    def on_open_folder(self, _event: wx.Event) -> None:
        """Handle "Open Folder" menu action."""

        dlg = wx.DirDialog(self, _("Select requirements folder"))
        if dlg.ShowModal() == wx.ID_OK:
            if not self._confirm_discard_changes():
                dlg.Destroy()
                return
            self._load_directory(Path(dlg.GetPath()))
        dlg.Destroy()

    def on_open_recent(self, event: wx.CommandEvent) -> None:
        """Open a directory selected from the "recent" menu."""

        path = self.navigation.get_recent_path(event.GetId())
        if path and self._confirm_discard_changes():
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
            max_output_tokens=self.llm_settings.max_output_tokens,
            timeout_minutes=self.llm_settings.timeout_minutes,
            stream=self.llm_settings.stream,
            auto_start=self.mcp_settings.auto_start,
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
                auto_start,
                host,
                port,
                base_path,
                require_token,
                token,
            ) = dlg.get_values()
            previous_mcp = self.mcp_settings
            self.llm_settings = LLMSettings(
                base_url=base_url,
                model=model,
                api_key=api_key or None,
                max_retries=max_retries,
                max_output_tokens=max_output_tokens,
                timeout_minutes=timeout_minutes,
                stream=stream,
            )
            self.mcp_settings = MCPSettings(
                auto_start=auto_start,
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
            auto_start_changed = (
                previous_mcp.auto_start != self.mcp_settings.auto_start
            )
            server_config_changed = (
                previous_mcp.model_dump(exclude={"auto_start"})
                != self.mcp_settings.model_dump(exclude={"auto_start"})
            )
            if auto_start_changed:
                if self.mcp_settings.auto_start:
                    self.mcp.start(self.mcp_settings)
                else:
                    self.mcp.stop()
            elif self.mcp_settings.auto_start and server_config_changed:
                self.mcp.stop()
                self.mcp.start(self.mcp_settings)
            self._apply_language()
        dlg.Destroy()

    def on_run_command(self, _event: wx.Event) -> None:
        """Ensure agent chat panel is visible and focused."""

        if not self.agent_chat_menu_item:
            return
        if not self.agent_chat_menu_item.IsChecked():
            self.agent_chat_menu_item.Check(True)
            self.on_toggle_agent_chat(None)
        else:
            self._ensure_agent_chat_visible()

    def _apply_language(self) -> None:
        """Reinitialize locale and rebuild UI after language change."""
        from ..main import init_locale

        app = wx.GetApp()
        app.locale = init_locale(self.language)

        editor_visible = self._is_editor_visible()
        agent_visible = bool(
            self.agent_chat_menu_item and self.agent_chat_menu_item.IsChecked()
        )

        # Rebuild menus with new translations
        self.navigation.rebuild(self.selected_fields)
        self._recent_menu = self.navigation.recent_menu
        self._recent_menu_item = self.navigation.recent_menu_item
        self.log_menu_item = self.navigation.log_menu_item
        self.editor_menu_item = self.navigation.editor_menu_item
        self.agent_chat_menu_item = self.navigation.agent_chat_menu_item
        self.manage_labels_id = self.navigation.manage_labels_id
        if self.editor_menu_item:
            self.editor_menu_item.Check(editor_visible)
        if self.agent_chat_menu_item:
            self.agent_chat_menu_item.Check(agent_visible)

        # Replace panels to update all labels
        old_panel = self.panel
        list_sizer = self.list_container.GetSizer()
        self.panel = ListPanel(
            self.list_container,
            model=self.model,
            on_clone=self.on_clone_requirement,
            on_delete=self.on_delete_requirement,
            on_delete_many=self.on_delete_requirements,
            on_sort_changed=self._on_sort_changed,
            on_derive=self.on_derive_requirement,
        )
        self.panel.set_columns(self.selected_fields)
        self.panel.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_requirement_selected)
        self.panel.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_requirement_activated)
        if list_sizer is not None:
            list_sizer.Replace(old_panel, self.panel)
        old_panel.Destroy()

        editor_was_visible = self.editor_container.IsShown()
        old_editor = self.editor
        self.editor = EditorPanel(
            self.editor_container,
            on_save=self._on_editor_save,
        )
        editor_sizer = self.editor_container.GetSizer()
        if editor_sizer is not None:
            editor_sizer.Replace(old_editor, self.editor)
        old_editor.Destroy()
        if editor_was_visible:
            self._show_editor_panel()
        else:
            self._hide_editor_panel()

        self._apply_editor_visibility(persist=False)

        if hasattr(self, "agent_panel"):
            old_agent_panel = self.agent_panel
            agent_was_split = self.agent_splitter.IsSplit()
            sash_pos = self.agent_splitter.GetSashPosition() if agent_was_split else None
            self.agent_panel = AgentChatPanel(
                self.agent_container,
                agent_supplier=self._create_agent,
            )
            agent_sizer = self.agent_container.GetSizer()
            if agent_sizer is not None:
                agent_sizer.Replace(old_agent_panel, self.agent_panel)
            old_agent_panel.Destroy()
            if agent_was_split:
                self._show_agent_section()
                if sash_pos is not None:
                    self.agent_splitter.SetSashPosition(sash_pos)
            else:
                self._hide_agent_section()

        self._update_section_labels()
        self.list_container.Layout()
        self.editor_container.Layout()
        self.agent_container.Layout()

        # Restore layout and reload data if any directory is open
        self._load_layout()
        if self.current_dir:
            self._load_directory(self.current_dir)
        else:
            self.panel.set_requirements(self.model.get_all(), {})

        self.Layout()

    def _create_agent(self) -> LocalAgent:
        """Construct ``LocalAgent`` using current settings."""

        settings = AppSettings(llm=self.llm_settings, mcp=self.mcp_settings)
        return LocalAgent(settings=settings, confirm=confirm)

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
        controller = DocumentsController(path, self.model)
        try:
            docs = controller.load_documents()
        except ValidationError as exc:
            logger.error(
                "validation error while loading requirements folder %s: %s", path, exc
            )
            self._show_directory_error(path, exc)
            return
        except Exception as exc:  # pragma: no cover - unexpected GUI failure
            logger.exception(
                "unexpected error while loading requirements folder %s", path
            )
            self._show_directory_error(path, exc)
            return

        self.docs_controller = controller
        self.panel.set_documents_controller(self.docs_controller)
        self.doc_tree.set_documents(docs)
        self.config.add_recent_dir(path)
        self.navigation.update_recent_menu()
        self.SetTitle(f"{self._base_title} - {path}")
        self.current_dir = path
        if docs:
            first = sorted(docs)[0]
            self.current_doc_prefix = first
            self.panel.set_active_document(first)
            self.editor.set_directory(self.current_dir / first)
            self._load_document_contents(first)
            self.doc_tree.select(first)
        else:
            self.current_doc_prefix = None
            self.panel.set_active_document(None)
            self.editor.set_directory(None)
            self.panel.set_requirements([], {})
            self.editor.update_labels_list([])
            self.panel.update_labels_list([])
        if self.remember_sort and self.sort_column != -1:
            self.panel.sort(self.sort_column, self.sort_ascending)
        self._selected_requirement_id = None
        self._hide_editor_panel()

    def _show_directory_error(self, path: Path, error: Exception) -> None:
        """Display error message for a failed directory load."""

        message = _(
            "Failed to load requirements folder \"{path}\": {error}"
        ).format(path=path, error=error)
        wx.MessageBox(message, _("Error"), wx.ICON_ERROR)

    def _refresh_documents(
        self,
        *,
        select: str | None = None,
        force_reload: bool = False,
    ) -> None:
        """Reload document tree and optionally change selection."""

        if not self.docs_controller:
            return
        docs = self.docs_controller.load_documents()
        self.doc_tree.set_documents(docs)
        target = select
        if target and target not in docs:
            target = None
        if target is None:
            if self.current_doc_prefix and self.current_doc_prefix in docs:
                target = self.current_doc_prefix
            elif docs:
                target = sorted(docs)[0]
        if target:
            if force_reload or target != self.current_doc_prefix:
                self.current_doc_prefix = None
            self.doc_tree.select(target)
        else:
            self.current_doc_prefix = None
            self.panel.set_active_document(None)
            self.editor.set_directory(None)
            self.panel.set_requirements([], {})
            self.editor.update_labels_list([])
            self.panel.update_labels_list([])
            self._selected_requirement_id = None
            self._hide_editor_panel()

    def _load_document_contents(self, prefix: str) -> bool:
        """Load items and labels for ``prefix`` and update the views."""

        if not self.docs_controller:
            return False
        try:
            derived_map = self.docs_controller.load_items(prefix)
        except Exception as exc:  # pragma: no cover - GUI side effect
            logger.exception("failed to load requirements for document %s", prefix)
            message = _(
                "Failed to load requirements for document \"{prefix}\": {error}"
            ).format(prefix=prefix, error=exc)
            wx.MessageBox(message, _("Error"), wx.ICON_ERROR)
            self.model.set_requirements([])
            self.panel.set_requirements([], {})
            self.editor.update_labels_list([], False)
            self.panel.update_labels_list([])
            self._selected_requirement_id = None
            self._hide_editor_panel()
            self.splitter.UpdateSize()
            return False
        labels, freeform = self.docs_controller.collect_labels(prefix)
        self.panel.set_requirements(self.model.get_all(), derived_map)
        self.editor.update_labels_list(labels, freeform)
        self.panel.update_labels_list(labels)
        self._selected_requirement_id = None
        self._hide_editor_panel()
        self.splitter.UpdateSize()
        return True

    # recent directories -------------------------------------------------

    def on_new_document(self, parent_prefix: str | None) -> None:
        """Create a new document under ``parent_prefix``."""

        if not (self.docs_controller and self.current_dir):
            wx.MessageBox(_("Select requirements folder first"), _("No Data"))
            return
        dlg = DocumentPropertiesDialog(
            self,
            mode="create",
            parent_prefix=parent_prefix,
        )
        props = None
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            props = dlg.get_properties()
        finally:
            dlg.Destroy()
        if props is None:
            return
        try:
            doc = self.docs_controller.create_document(
                props.prefix,
                props.title,
                digits=props.digits,
                parent=parent_prefix,
            )
        except ValueError as exc:
            wx.MessageBox(str(exc), _("Error"), wx.ICON_ERROR)
            return
        self._selected_requirement_id = None
        self._refresh_documents(select=doc.prefix, force_reload=True)

    def on_rename_document(self, prefix: str) -> None:
        """Rename or retitle document ``prefix``."""

        if not self.docs_controller:
            return
        doc = self.docs_controller.documents.get(prefix)
        if not doc:
            return
        dlg = DocumentPropertiesDialog(
            self,
            mode="rename",
            prefix=doc.prefix,
            title=doc.title,
            digits=doc.digits,
            parent_prefix=doc.parent,
        )
        props = None
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            props = dlg.get_properties()
        finally:
            dlg.Destroy()
        if props is None:
            return
        try:
            self.docs_controller.rename_document(
                prefix,
                title=props.title,
                digits=props.digits,
            )
        except ValueError as exc:
            wx.MessageBox(str(exc), _("Error"), wx.ICON_ERROR)
            return
        self._refresh_documents(select=prefix, force_reload=True)

    def on_delete_document(self, prefix: str) -> None:
        """Delete document ``prefix`` after confirmation."""

        if not self.docs_controller:
            return
        doc = self.docs_controller.documents.get(prefix)
        if not doc:
            return
        msg = _("Delete document {prefix} and its subtree?").format(prefix=prefix)
        if not confirm(msg):
            return
        parent_prefix = doc.parent
        removed = self.docs_controller.delete_document(prefix)
        if not removed:
            wx.MessageBox(_("Document not found"), _("Error"), wx.ICON_ERROR)
            return
        self._selected_requirement_id = None
        target = parent_prefix if parent_prefix in self.docs_controller.documents else None
        self._refresh_documents(select=target, force_reload=True)

    def _on_doc_changing(self, event: wx.TreeEvent) -> None:
        """Request confirmation before switching documents."""

        if event.GetItem() == event.GetOldItem():
            event.Skip()
            return
        if not self._confirm_discard_changes():
            if not hasattr(event, "CanVeto") or event.CanVeto():
                event.Veto()
            return
        event.Skip()

    def on_document_selected(self, prefix: str) -> None:
        """Load items and labels for selected document ``prefix``."""
        if prefix == self.current_doc_prefix:
            return
        if not self.docs_controller:
            return
        self.current_doc_prefix = prefix
        self.panel.set_active_document(prefix)
        if self.current_dir:
            self.editor.set_directory(self.current_dir / prefix)
        self._load_document_contents(prefix)

    def on_requirement_selected(self, event: wx.ListEvent) -> None:
        """Load requirement into editor when selected in list."""

        index = event.GetIndex()
        if index == wx.NOT_FOUND:
            return
        req_id = self.panel.list.GetItemData(index)
        if req_id == self._selected_requirement_id:
            return
        if not self._confirm_discard_changes():
            if hasattr(event, "Veto"):
                can_veto = getattr(event, "CanVeto", None)
                if can_veto is None or can_veto():
                    event.Veto()
            return
        req = self.model.get_by_id(req_id)
        if req:
            self._selected_requirement_id = req_id
            self.editor.load(req)
            if self._is_editor_visible():
                self._show_editor_panel()
                self.splitter.UpdateSize()

    def on_requirement_activated(self, event: wx.ListEvent) -> None:
        """Open requirement in a detached editor when activated."""

        if self._is_editor_visible():
            event.Skip()
            return
        index = event.GetIndex()
        if index == wx.NOT_FOUND:
            return
        try:
            req_id = self.panel.list.GetItemData(index)
        except Exception:
            return
        if req_id <= 0:
            return
        req = self.model.get_by_id(req_id)
        if not req:
            return
        self._open_detached_editor(req)

    def _save_editor_contents(
        self,
        editor_panel: EditorPanel,
        *,
        doc_prefix: str | None = None,
    ) -> Requirement | None:
        if not (self.current_dir and self.docs_controller):
            return None
        prefix = doc_prefix or str(editor_panel.extra.get("doc_prefix", ""))
        if not prefix:
            prefix = self.current_doc_prefix or ""
        if not prefix:
            return None
        doc = self.docs_controller.documents.get(prefix)
        if not doc:
            return None
        directory = self.current_dir / prefix
        try:
            editor_panel.save(directory, doc=doc)
        except RequirementIDCollisionError:
            return None
        except Exception as exc:  # pragma: no cover - GUI event
            wx.MessageBox(str(exc), _("Error"), wx.ICON_ERROR)
            return None
        requirement = editor_panel.get_data()
        requirement.doc_prefix = prefix or requirement.doc_prefix
        self.model.update(requirement)
        self.panel.recalc_derived_map(self.model.get_all())
        labels, freeform = self.docs_controller.collect_labels(prefix)
        editor_panel.update_labels_list(labels, freeform)
        self.panel.update_labels_list(labels)
        if editor_panel is not self.editor:
            self.editor.update_labels_list(labels, freeform)
            if (
                self._is_editor_visible()
                and self.current_doc_prefix == prefix
                and self._selected_requirement_id == requirement.id
            ):
                self.editor.load(requirement)
        self._selected_requirement_id = requirement.id
        return requirement

    def _on_editor_save(self) -> None:
        if not self.docs_controller:
            return
        self._save_editor_contents(self.editor, doc_prefix=self.current_doc_prefix)

    def _open_detached_editor(self, requirement: Requirement) -> None:
        if not (self.docs_controller and self.current_dir):
            return
        prefix = getattr(requirement, "doc_prefix", "") or self.current_doc_prefix
        if not prefix:
            return
        doc = self.docs_controller.documents.get(prefix)
        if not doc:
            return
        directory = self.current_dir / prefix
        labels, freeform = self.docs_controller.collect_labels(prefix)
        key = (prefix, getattr(requirement, "id", 0))
        existing = self._detached_editors.get(key)
        if existing:
            existing.reload(requirement, directory, labels, freeform)
            existing.Raise()
            existing.SetFocus()
            return
        frame = DetachedEditorFrame(
            self,
            requirement=requirement,
            doc_prefix=prefix,
            directory=directory,
            labels=labels,
            allow_freeform=freeform,
            on_save=self._on_detached_editor_save,
            on_close=self._on_detached_editor_closed,
        )
        self._detached_editors[frame.key] = frame
        frame.Show()

    def _on_detached_editor_save(self, frame: DetachedEditorFrame) -> bool:
        prefix = frame.doc_prefix
        if not prefix or not self.docs_controller or not self.current_dir:
            return False
        old_key = frame.key
        requirement = self._save_editor_contents(frame.editor, doc_prefix=prefix)
        if requirement is None:
            return False
        directory = self.current_dir / prefix
        labels, freeform = self.docs_controller.collect_labels(prefix)
        frame.reload(requirement, directory, labels, freeform)
        if old_key in self._detached_editors and self._detached_editors[old_key] is frame:
            del self._detached_editors[old_key]
        self._detached_editors[frame.key] = frame
        return True

    def _on_detached_editor_closed(self, frame: DetachedEditorFrame) -> None:
        for key, window in list(self._detached_editors.items()):
            if window is frame:
                del self._detached_editors[key]
                break

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

    def on_toggle_agent_chat(self, _event: wx.CommandEvent | None) -> None:
        """Toggle agent chat panel visibility."""

        if not self.agent_chat_menu_item:
            return
        if self.agent_chat_menu_item.IsChecked():
            self._ensure_agent_chat_visible()
        else:
            self._hide_agent_chat()

    def on_toggle_requirement_editor(self, _event: wx.CommandEvent) -> None:
        """Toggle visibility of the requirement editor pane."""

        if not self.editor_menu_item:
            return
        if not self.editor_menu_item.IsChecked():
            if not self._confirm_discard_changes():
                self.editor_menu_item.Check(True)
                return
        self._apply_editor_visibility(persist=True)

    def _default_editor_sash(self) -> int:
        width = self.splitter.GetClientSize().width
        if width <= 0:
            width = self.agent_splitter.GetClientSize().width
        if width <= 0:
            width = self.doc_splitter.GetClientSize().width
        if width <= 0:
            width = self.GetClientSize().width
        if width <= 0:
            width = 1000
        min_size = max(self.splitter.GetMinimumPaneSize(), 200)
        max_left = max(width - min_size, min_size)
        desired = width // 2 if width // 2 > 0 else min_size
        desired = max(min_size, desired)
        desired = min(desired, max_left)
        return desired

    def _default_agent_chat_sash(self) -> int:
        width = self.agent_splitter.GetClientSize().width
        if width <= 0:
            width = self.doc_splitter.GetClientSize().width
        if width <= 0:
            width = self.GetClientSize().width
        if width <= 0:
            width = 1000
        min_size = max(self.agent_splitter.GetMinimumPaneSize(), 200)
        max_left = max(width - min_size, min_size)
        desired = width - 320
        desired = max(min_size, desired)
        desired = min(desired, max_left)
        return desired

    def _ensure_agent_chat_visible(self) -> None:
        if not self.agent_splitter.IsSplit():
            default = self.config.get_agent_chat_sash(self._default_agent_chat_sash())
            self._show_agent_section()
            self.agent_splitter.SplitVertically(
                self.splitter,
                self.agent_container,
                default,
            )
        self.agent_panel.focus_input()
        self.config.set_agent_chat_shown(True)

    def _hide_agent_chat(self) -> None:
        if self.agent_splitter.IsSplit():
            self.config.set_agent_chat_sash(self.agent_splitter.GetSashPosition())
            self.agent_splitter.Unsplit(self.agent_container)
        self._hide_agent_section()
        self.config.set_agent_chat_shown(False)

    def _apply_editor_visibility(self, *, persist: bool) -> None:
        visible = self._is_editor_visible()
        if visible:
            if not self.splitter.IsSplit():
                sash = self.config.get_editor_sash(self._default_editor_sash())
                self.splitter.SplitVertically(
                    self.list_container,
                    self.editor_container,
                    sash,
                )
            else:
                sash = self.config.get_editor_sash(self.splitter.GetSashPosition())
                self.splitter.SetSashPosition(sash)
            self._show_editor_panel()
            if persist:
                self.config.set_editor_shown(True)
        else:
            if self.splitter.IsSplit():
                if persist:
                    self.config.set_editor_sash(self.splitter.GetSashPosition())
                self.splitter.Unsplit(self.editor_container)
            self._hide_editor_panel()
            if persist:
                self.config.set_editor_shown(False)
        self.splitter.UpdateSize()
        self.Layout()

    def _load_layout(self) -> None:
        """Restore window geometry, splitter, console, and column widths."""
        self.config.restore_layout(
            self,
            self.doc_splitter,
            self.main_splitter,
            self.panel,
            self.log_panel,
            self.log_menu_item,
            editor_splitter=self.splitter,
        )
        self._doc_tree_saved_sash = self.config.get_doc_tree_saved_sash(
            self.doc_splitter.GetSashPosition()
        )
        if self.config.get_doc_tree_collapsed():
            self._collapse_doc_tree(update_config=False)
        else:
            self._expand_doc_tree(update_config=False)
        if self.editor_menu_item:
            self.editor_menu_item.Check(self.config.get_editor_shown())
        self._apply_editor_visibility(persist=False)
        if self.agent_chat_menu_item:
            if self.config.get_agent_chat_shown():
                self.agent_chat_menu_item.Check(True)
                sash = self.config.get_agent_chat_sash(self._default_agent_chat_sash())
                self._show_agent_section()
                self.agent_splitter.SplitVertically(
                    self.splitter,
                    self.agent_container,
                    sash,
                )
            else:
                self.agent_chat_menu_item.Check(False)
                if self.agent_splitter.IsSplit():
                    self.agent_splitter.Unsplit(self.agent_container)
                self._hide_agent_section()

    def _save_layout(self) -> None:
        """Persist window geometry, splitter, console, and column widths."""
        self.config.save_layout(
            self,
            self.doc_splitter,
            self.main_splitter,
            self.panel,
            editor_splitter=self.splitter,
            agent_splitter=self.agent_splitter,
            doc_tree_collapsed=self._doc_tree_collapsed,
            doc_tree_expanded_sash=self._doc_tree_saved_sash,
        )

    def _disable_splitter_unsplit(self, splitter: wx.SplitterWindow) -> None:
        """Attach handlers preventing ``splitter`` from unsplitting on double click."""

        splitter.Bind(wx.EVT_SPLITTER_DOUBLECLICKED, self._prevent_splitter_unsplit)
        splitter.Bind(wx.EVT_SPLITTER_DCLICK, self._prevent_splitter_unsplit)

    def _prevent_splitter_unsplit(self, event: wx.SplitterEvent) -> None:
        """Block attempts to unsplit panes initiated by double clicks."""

        event.Veto()

    def _on_close(self, event: wx.Event) -> None:  # pragma: no cover - GUI event
        if not self._confirm_discard_changes():
            if hasattr(event, "Veto") and event.CanVeto():  # pragma: no cover - GUI event
                event.Veto()
            return
        self._save_layout()
        for frame in list(self._detached_editors.values()):
            try:
                frame.Destroy()
            except Exception:  # pragma: no cover - best effort cleanup
                pass
        self._detached_editors.clear()
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
        self._selected_requirement_id = new_id
        self.panel.refresh(select_id=new_id)
        self.editor.load(data, path=None, mtime=None)
        if self._is_editor_visible():
            self._show_editor_panel()
            self.splitter.UpdateSize()
        else:
            self._open_detached_editor(data)

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
        self._selected_requirement_id = new_id
        self.panel.refresh(select_id=new_id)
        self.editor.load(clone, path=None, mtime=None)
        if self._is_editor_visible():
            self._show_editor_panel()
            self.splitter.UpdateSize()
        else:
            self._open_detached_editor(clone)

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
        self._selected_requirement_id = clone.id
        self.panel.refresh(select_id=clone.id)
        self.editor.load(clone, path=None, mtime=None)
        if self._is_editor_visible():
            self._show_editor_panel()
            self.splitter.UpdateSize()
        else:
            self._open_detached_editor(clone)


    def _format_requirement_summary(
        self, requirement: Requirement | None
    ) -> str | None:
        if not requirement:
            return None
        summary_parts: list[str] = []
        if requirement.rid:
            summary_parts.append(requirement.rid)
        title = requirement.title.strip()
        if title:
            summary_parts.append(title)
        if summary_parts:
            return " — ".join(summary_parts)
        return None

    def on_delete_requirements(self, req_ids: Sequence[int]) -> None:
        """Delete multiple requirements referenced by ``req_ids``."""

        if not req_ids:
            return
        if not (self.docs_controller and self.current_doc_prefix):
            return

        unique_ids: list[int] = []
        seen: set[int] = set()
        for req_id in req_ids:
            try:
                numeric = int(req_id)
            except (TypeError, ValueError):
                continue
            if numeric in seen:
                continue
            seen.add(numeric)
            unique_ids.append(numeric)
        if not unique_ids:
            return

        summaries: list[str] = []
        if self.model:
            for req_id in unique_ids:
                summary = self._format_requirement_summary(
                    self.model.get_by_id(req_id)
                )
                if summary:
                    summaries.append(summary)

        if len(unique_ids) == 1:
            message = _("Delete requirement?")
            if summaries:
                message = _("Delete requirement {summary}?").format(
                    summary=summaries[0]
                )
        else:
            message = _("Delete {count} requirements?").format(
                count=len(unique_ids)
            )
            if summaries:
                preview_limit = 5
                preview = summaries[:preview_limit]
                bullet_lines = "\n".join(f"- {text}" for text in preview)
                message = message + "\n" + bullet_lines
                if len(summaries) > preview_limit:
                    remaining = len(summaries) - preview_limit
                    message += "\n" + _("...and {count} more.").format(
                        count=remaining
                    )

        if not confirm(message):
            return

        deleted_any = False
        for req_id in unique_ids:
            if not self.docs_controller.delete_requirement(
                self.current_doc_prefix, req_id
            ):
                continue
            deleted_any = True

        if not deleted_any:
            return

        self._selected_requirement_id = None
        self.panel.recalc_derived_map(self.model.get_all())
        self._hide_editor_panel()
        self.splitter.UpdateSize()
        labels, freeform = self.docs_controller.collect_labels(
            self.current_doc_prefix
        )
        self.editor.update_labels_list(labels, freeform)
        self.panel.update_labels_list(labels)

    def on_delete_requirement(self, req_id: int) -> None:
        """Delete requirement ``req_id`` and refresh views."""

        self.on_delete_requirements([req_id])
