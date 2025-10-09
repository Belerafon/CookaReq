"""Implementation of the :class:`MainFrame` application window."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

import wx

from ...application import (
    ApplicationContext,
    LocalAgentFactory,
    MCPControllerFactory,
    RequirementsServiceFactory,
)
from ...columns import available_columns
from ...config import ConfigManager
from ...i18n import _
from ..requirement_model import RequirementModel
from ..splitter_utils import refresh_splitter_highlight
from .agent import MainFrameAgentMixin
from .documents import MainFrameDocumentsMixin
from .editor import MainFrameEditorMixin
from .logging import MainFrameLoggingMixin
from .requirements import MainFrameRequirementsMixin
from .sections import MainFrameSectionsMixin
from .settings import MainFrameSettingsMixin
from .shutdown import MainFrameShutdownMixin
from ..agent_chat_panel import AgentChatPanel
from ..document_tree import DocumentTree
from ..editor_panel import EditorPanel
from ..list_panel import ListPanel
from ..navigation import Navigation

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from .controllers import DocumentsController

class MainFrame(
    MainFrameRequirementsMixin,
    MainFrameEditorMixin,
    MainFrameDocumentsMixin,
    MainFrameAgentMixin,
    MainFrameSettingsMixin,
    MainFrameSectionsMixin,
    MainFrameLoggingMixin,
    MainFrameShutdownMixin,
    wx.Frame,
):
    """Top-level frame coordinating UI subsystems."""

    def __init__(
        self,
        parent: wx.Window | None,
        *,
        context: ApplicationContext,
        config: ConfigManager | None = None,
        model: RequirementModel | None = None,
        requirements_service_factory: RequirementsServiceFactory | None = None,
        local_agent_factory: LocalAgentFactory | None = None,
        mcp_factory: MCPControllerFactory | None = None,
    ) -> None:
        """Set up main application window and controllers."""
        self._base_title = "CookaReq"
        if context is None:
            raise ValueError("MainFrame requires an ApplicationContext instance")
        self.context = context
        self.config = config if config is not None else self.context.config
        self.model = model if model is not None else self.context.requirement_model
        self.requirements_service_factory = (
            requirements_service_factory
            or self.context.requirements_service_factory
        )
        self.local_agent_factory = (
            local_agent_factory or self.context.local_agent_factory
        )
        self._mcp_factory = mcp_factory or self.context.mcp_controller_factory
        self.available_fields = available_columns()
        self.selected_fields = self.config.get_columns()
        self.auto_open_last = self.config.get_auto_open_last()
        self.remember_sort = self.config.get_remember_sort()
        self.language = self.config.get_language()
        self.sort_column, self.sort_ascending = self.config.get_sort_settings()
        self.llm_settings = self.config.get_llm_settings()
        self.mcp_settings = self.config.get_mcp_settings()
        self.mcp = self._mcp_factory()
        if self.mcp_settings.auto_start:
            self.mcp.start(
                self.mcp_settings,
                max_context_tokens=self.llm_settings.max_context_tokens,
                token_model=self.llm_settings.model,
            )
        self.docs_controller: DocumentsController | None = None
        self._detached_editors: dict[tuple[str, int], wx.Frame] = {}
        self._shutdown_in_progress = False

        super().__init__(parent=parent, title=self._base_title)

        self._init_icons()
        self.navigation = self._create_navigation()
        self._assign_navigation_references()

        self.main_splitter = self._create_splitter(self)
        self.doc_splitter = self._create_splitter(self.main_splitter)
        self._doc_tree_min_pane = max(self.FromDIP(20), 1)
        self.doc_splitter.SetMinimumPaneSize(self._doc_tree_min_pane)
        self._doc_tree_last_sash = self.doc_splitter.GetSashPosition()
        self.agent_splitter = self._create_splitter(self.doc_splitter)
        self.agent_splitter.SetMinimumPaneSize(280)
        self._agent_last_sash = self.config.get_agent_chat_sash(
            self._default_agent_chat_sash()
        )
        self.splitter = self._create_splitter(self.agent_splitter)
        self.splitter.SetMinimumPaneSize(200)

        self._init_sections()
        self._init_log_console()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.main_splitter, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self._load_layout()
        for splitter in (
            self.main_splitter,
            self.doc_splitter,
            self.agent_splitter,
            self.splitter,
        ):
            refresh_splitter_highlight(splitter)
        self.current_dir: Path | None = None
        self.current_doc_prefix: str | None = None
        self._selected_requirement_id: int | None = None
        self.panel.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_requirement_selected)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_window_destroy)
        if self.auto_open_last and self.recent_dirs:
            path = Path(self.recent_dirs[0])
            if path.exists():
                self._load_directory(path)

    # ------------------------------------------------------------------
    # initialization helpers
    def _init_icons(self) -> None:
        """Load platform icons into the frame."""
        with resources.as_file(
            resources.files("app.resources") / "app.ico",
        ) as icon_path:
            icons = wx.IconBundle(str(icon_path), wx.BITMAP_TYPE_ANY)
            self.SetIcons(icons)

    def _create_navigation(self) -> Navigation:
        """Build the navigation menus and toolbars."""
        return Navigation(
            self,
            self.config,
            available_fields=self.available_fields,
            selected_fields=self.selected_fields,
            on_open_folder=self.on_open_folder,
            on_import_requirements=self.on_import_requirements,
            on_open_settings=self.on_open_settings,
            on_manage_labels=self.on_manage_labels,
            on_open_recent=self.on_open_recent,
            on_toggle_column=self.on_toggle_column,
            on_toggle_log_console=self.on_toggle_log_console,
            on_toggle_hierarchy=self.on_toggle_hierarchy,
            on_toggle_requirement_editor=self.on_toggle_requirement_editor,
            on_toggle_agent_chat=self.on_toggle_agent_chat,
            on_show_derivation_graph=self.on_show_derivation_graph,
            on_show_trace_matrix=self.on_show_trace_matrix,
            on_new_requirement=self.on_new_requirement,
            on_run_command=self.on_run_command,
            on_open_logs=self.on_open_logs,
        )

    def _assign_navigation_references(self) -> None:
        """Expose frequently used menu items as attributes."""
        self._recent_menu = self.navigation.recent_menu
        self.log_menu_item = self.navigation.log_menu_item
        self.hierarchy_menu_item = self.navigation.hierarchy_menu_item
        self.editor_menu_item = self.navigation.editor_menu_item
        self.agent_chat_menu_item = self.navigation.agent_chat_menu_item
        self.manage_labels_id = self.navigation.manage_labels_id
        self.navigation.set_manage_labels_enabled(False)

    def _init_sections(self) -> None:
        """Construct hierarchy, list, editor and agent panels."""
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
            allow_label_shrink=True,
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
                on_discard=self._handle_editor_discard,
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
                token_model_resolver=lambda: self.llm_settings.model,
                context_provider=self._agent_context_messages,
                context_window_resolver=lambda: self.llm_settings.max_context_tokens,
                confirm_preference=self.config.get_agent_confirm_mode(),
                persist_confirm_preference=self.config.set_agent_confirm_mode,
                batch_target_provider=self._agent_batch_targets,
                batch_context_provider=self._agent_context_for_requirement,
                documents_subdirectory=self.mcp_settings.documents_path,
            ),
        )
        self._setup_agent_documents_hooks()
        self._init_mcp_tool_listener()
        self._hide_agent_section()
        history_sash = self.config.get_agent_history_sash(
            self.agent_panel.default_history_sash()
        )
        self.agent_panel.apply_history_sash(history_sash)
        self.agent_splitter.Initialize(self.splitter)
        self.doc_splitter.SplitVertically(
            self.doc_tree_container,
            self.agent_splitter,
            200,
        )
        self._doc_tree_last_sash = self.doc_splitter.GetSashPosition()
        self._clear_editor_panel()

    # ------------------------------------------------------------------
    # hooks for localisation and dynamic rebuilding
    def _apply_language(self) -> None:
        from ...main import init_locale

        app = wx.GetApp()
        app.locale = init_locale(self.language)

        editor_visible = self._is_editor_visible()
        agent_visible = bool(
            self.agent_chat_menu_item and self.agent_chat_menu_item.IsChecked()
        )

        self.navigation.rebuild(self.selected_fields)
        self._assign_navigation_references()
        if self.editor_menu_item:
            self.editor_menu_item.Check(editor_visible)
        if self.agent_chat_menu_item:
            self.agent_chat_menu_item.Check(agent_visible)

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
            on_discard=self._handle_editor_discard,
        )
        if getattr(self, "docs_controller", None):
            self.editor.set_service(self.docs_controller.service)
            if self.current_doc_prefix:
                self.editor.set_document(self.current_doc_prefix)
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
            vertical_sash: int | None = None
            if hasattr(old_agent_panel, "vertical_sash"):
                vertical_value = old_agent_panel.vertical_sash  # type: ignore[attr-defined]
                if isinstance(vertical_value, int) and vertical_value > 0:
                    vertical_sash = vertical_value
            self.agent_panel = AgentChatPanel(
                self.agent_container,
                agent_supplier=self._create_agent,
                token_model_resolver=lambda: self.llm_settings.model,
                context_provider=self._agent_context_messages,
                context_window_resolver=lambda: self.llm_settings.max_context_tokens,
                confirm_preference=self.config.get_agent_confirm_mode(),
                persist_confirm_preference=self.config.set_agent_confirm_mode,
                batch_target_provider=self._agent_batch_targets,
                batch_context_provider=self._agent_context_for_requirement,
                documents_subdirectory=self.mcp_settings.documents_path,
            )
            self._init_mcp_tool_listener()
            self._setup_agent_documents_hooks()
            history_sash = self.config.get_agent_history_sash(
                self.agent_panel.default_history_sash()
            )
            self.agent_panel.apply_history_sash(history_sash)
            if vertical_sash is not None:
                self.agent_panel.apply_vertical_sash(vertical_sash)
            agent_sizer = self.agent_container.GetSizer()
            if agent_sizer is not None:
                agent_sizer.Replace(old_agent_panel, self.agent_panel)
            old_agent_panel.Destroy()
            if agent_was_split:
                self._show_agent_section()
                if sash_pos is not None:
                    self._agent_last_sash = sash_pos
                    self.agent_splitter.SetSashPosition(sash_pos)
            else:
                self._hide_agent_section()
        self._update_section_labels()
        self.list_container.Layout()
        self.editor_container.Layout()
        self.agent_container.Layout()

        self._load_layout()
        if self.current_dir:
            self._load_directory(self.current_dir)
        else:
            self.panel.set_requirements(self.model.get_all(), {})

        self.Layout()
