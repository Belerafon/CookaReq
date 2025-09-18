"""Main application window."""

import json
import logging
import weakref
from collections.abc import Callable, Sequence
from dataclasses import fields, replace
from importlib import resources
from pathlib import Path

import wx

_COLLAPSE_ARROW = "\N{BLACK LEFT-POINTING TRIANGLE}"
_EXPAND_ARROW = "\N{BLACK RIGHT-POINTING TRIANGLE}"

from ..agent import LocalAgent
from ..config import ConfigManager
from ..confirm import confirm
from ..core.model import Link, Requirement, requirement_fingerprint
from ..core.document_store import (
    Document,
    LabelDef,
    RequirementIDCollisionError,
    ValidationError,
    rid_for,
    save_document,
)
from ..i18n import _
from ..log import get_log_directory, logger, open_log_directory
from ..mcp.controller import MCPController
from ..settings import AppSettings, LLMSettings, MCPSettings
from .agent_chat_panel import AgentChatPanel
from .controllers import DocumentsController
from .document_dialog import DocumentPropertiesDialog
from .document_tree import DocumentTree
from .detached_editor import DetachedEditorFrame
from .error_dialog import show_error_dialog
from .editor_panel import EditorPanel
from .labels_dialog import LabelsDialog
from .list_panel import ListPanel
from .navigation import Navigation
from .requirement_model import RequirementModel
from .settings_dialog import SettingsDialog
from .widgets import SectionContainer


_SECTION_DEFAULT_PADDING = 0

class WxLogHandler(logging.Handler):
    """Forward log records to a ``wx.TextCtrl``."""

    def __init__(self, target: wx.TextCtrl, *, max_chars: int = 500_000) -> None:
        """Initialize handler redirecting log output to ``target``."""
        super().__init__()
        self._target = target
        self._max_chars = max_chars
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

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
        wx.CallAfter(self._append_message, msg)

    def _append_message(self, message: str) -> None:
        """Render ``message`` in the target control respecting the size limit."""

        target = self._target
        if not target or target.IsBeingDeleted():
            return
        target.AppendText(message + "\n")
        if self._max_chars and self._max_chars > 0:
            excess = target.GetLastPosition() - self._max_chars
            if excess > 0:
                target.Remove(0, excess)


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
            on_open_logs=self.on_open_logs,
        )
        self._recent_menu = self.navigation.recent_menu
        self._recent_menu_item = self.navigation.recent_menu_item
        self.log_menu_item = self.navigation.log_menu_item
        self.editor_menu_item = self.navigation.editor_menu_item
        self.agent_chat_menu_item = self.navigation.agent_chat_menu_item
        self.manage_labels_id = self.navigation.manage_labels_id
        self._detached_editors: dict[tuple[str, int], DetachedEditorFrame] = {}
        self._auxiliary_frames: set[wx.Frame] = set()
        self._shutdown_in_progress = False

        # split horizontally: top is main content, bottom is log console
        self.main_splitter = wx.SplitterWindow(self)
        self.doc_splitter = wx.SplitterWindow(self.main_splitter)
        self._doc_tree_min_pane = max(self.FromDIP(20), 1)
        self.doc_splitter.SetMinimumPaneSize(self._doc_tree_min_pane)
        self._doc_tree_toggle_size: wx.Size | None = None
        self._doc_tree_collapsed = False
        self._doc_tree_last_width = max(200, self._doc_tree_min_pane)
        self.agent_splitter = wx.SplitterWindow(self.doc_splitter)
        self.agent_splitter.SetMinimumPaneSize(280)
        self._agent_last_width = max(self.agent_splitter.GetMinimumPaneSize(), 320)
        self.splitter = wx.SplitterWindow(self.agent_splitter)
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
            allow_label_shrink=True,
        )
        self._configure_doc_tree_section()
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
            ),
        )
        self._hide_agent_section()
        self.agent_splitter.Initialize(self.splitter)
        self.doc_splitter.SplitVertically(
            self.doc_tree_container,
            self.agent_splitter,
            200,
        )
        self._doc_tree_last_width = self._current_doc_tree_width()
        self._clear_editor_panel()

        self.log_panel = wx.Panel(self.main_splitter)
        log_sizer = wx.BoxSizer(wx.VERTICAL)
        header = wx.BoxSizer(wx.HORIZONTAL)
        self.log_label = wx.StaticText(self.log_panel, label=_("Log Console"))
        header.Add(self.log_label, 1, wx.ALIGN_CENTER_VERTICAL)
        self.log_level_label = wx.StaticText(self.log_panel, label=_("Log Level"))
        header.Add(self.log_level_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        self._log_level_values: list[int] = []
        self.log_level_choice = wx.Choice(self.log_panel, choices=[])
        header.Add(self.log_level_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 2)
        self.open_logs_button = wx.Button(
            self.log_panel,
            label=_("Open Log Folder"),
            style=wx.BU_EXACTFIT,
        )
        self.open_logs_button.Bind(wx.EVT_BUTTON, self.on_open_logs)
        header.Add(self.open_logs_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        log_sizer.Add(header, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.log_console = wx.TextCtrl(
            self.log_panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        log_sizer.Add(self.log_console, 1, wx.EXPAND | wx.ALL, 5)
        self.log_panel.SetSizer(log_sizer)

        existing = next(
            (h for h in logger.handlers if isinstance(h, WxLogHandler)),
            None,
        )
        saved_log_level = self.config.get_log_level()
        if existing:
            self.log_handler = existing
            self.log_handler.target = self.log_console
        else:
            self.log_handler = WxLogHandler(self.log_console)
            logger.addHandler(self.log_handler)
        self.log_handler.setLevel(saved_log_level)
        self._populate_log_level_choice(saved_log_level)
        self.log_level_choice.Bind(wx.EVT_CHOICE, self.on_change_log_level)

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

    def _log_level_options(self) -> list[tuple[str, int]]:
        """Return ordered pairs of localized labels and log levels."""

        return [
            (_("Debug"), logging.DEBUG),
            (_("Info"), logging.INFO),
            (_("Warning"), logging.WARNING),
            (_("Error"), logging.ERROR),
        ]

    def _populate_log_level_choice(self, selected_level: int | None = None) -> None:
        """Fill the level selector preserving the current ``selected_level``."""

        if not getattr(self, "log_level_choice", None):
            return

        target_level = selected_level if selected_level is not None else self.log_handler.level
        if target_level == logging.NOTSET:
            target_level = logging.INFO

        options = self._log_level_options()
        self.log_level_choice.Freeze()
        try:
            self.log_level_choice.Clear()
            self._log_level_values = []
            for label, level in options:
                self.log_level_choice.Append(label)
                self._log_level_values.append(level)
        finally:
            self.log_level_choice.Thaw()

        index = self._find_choice_index_for_level(target_level)
        if index >= 0:
            self.log_level_choice.SetSelection(index)

    def _find_choice_index_for_level(self, level: int) -> int:
        """Return the closest matching index for ``level`` in the selector."""

        if not self._log_level_values:
            return -1
        if level in self._log_level_values:
            return self._log_level_values.index(level)
        for idx, candidate in enumerate(self._log_level_values):
            if level <= candidate:
                return idx
        return len(self._log_level_values) - 1

    def _create_section(
        self,
        parent: wx.Window,
        *,
        label: str,
        factory: Callable[[wx.Window], wx.Window],
        header_factory: Callable[[wx.Window], Sequence[wx.Window]] | None = None,
        allow_label_shrink: bool = False,
        padding: int = _SECTION_DEFAULT_PADDING,
    ) -> tuple[wx.Panel, wx.StaticText, wx.Window]:
        """Build a titled container holding the widget returned by ``factory``."""

        container = SectionContainer(parent)
        background = container.GetBackgroundColour()
        sizer = wx.BoxSizer(wx.VERTICAL)
        border = max(container.FromDIP(padding), 0)
        label_style = 0
        if allow_label_shrink and hasattr(wx, "ST_NO_AUTORESIZE"):
            label_style |= wx.ST_NO_AUTORESIZE
        label_ctrl = wx.StaticText(container, label=label, style=label_style)
        if background.IsOk():
            label_ctrl.SetBackgroundColour(background)
        if allow_label_shrink:
            best = label_ctrl.GetBestSize()
            min_height = best.height if best.height > 0 else -1
            label_ctrl.SetMinSize(wx.Size(0, min_height))
        if header_factory is not None:
            header = wx.BoxSizer(wx.HORIZONTAL)
            header.Add(label_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
            for ctrl in header_factory(container):
                if background.IsOk():
                    ctrl.SetBackgroundColour(background)
                header.Add(ctrl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
            sizer.Add(header, 0, wx.EXPAND | wx.TOP, border)
        else:
            sizer.Add(label_ctrl, 0, wx.TOP, border)
        content = factory(container)
        if border:
            sizer.Add(content, 1, wx.EXPAND | wx.BOTTOM, border)
        else:
            sizer.Add(content, 1, wx.EXPAND)
        container.SetSizer(sizer)
        return container, label_ctrl, content

    def _configure_doc_tree_section(self) -> None:
        """Allow the hierarchy pane header to collapse to a narrow width."""

        if not getattr(self, "doc_tree_container", None):
            return
        label = getattr(self, "doc_tree_label", None)
        container = self.doc_tree_container
        if label:
            best = label.GetBestSize()
            min_height = best.height if best.height > 0 else -1
            label.SetMinSize(wx.Size(0, min_height))
            label.InvalidateBestSize()
        sizer = container.GetSizer()
        if sizer:
            children = sizer.GetChildren()
            if not children:
                return
            current_border = children[0].GetBorder()
            if current_border <= 0:
                return
            border = max(container.FromDIP(2), 1)
            children[0].SetBorder(border)
            if len(children) > 1:
                children[1].SetBorder(border)
            sizer.Layout()
        header_sizer = label.GetContainingSizer() if label else None
        if header_sizer:
            header_children = list(header_sizer.GetChildren())
            if header_children:
                border = header_children[0].GetBorder()
                if border > 0:
                    for item in header_children[1:]:
                        item.SetBorder(border)
            header_sizer.Layout()
        container.Layout()

    def _create_doc_tree_toggle(self, parent: wx.Window) -> wx.ToggleButton:
        """Create a minimalist text toggle for the document tree pane."""

        collapse_label = _COLLAPSE_ARROW
        expand_label = _EXPAND_ARROW
        self.doc_tree_toggle = wx.ToggleButton(
            parent,
            label=collapse_label,
            style=wx.BU_EXACTFIT | wx.BORDER_NONE,
        )
        self.doc_tree_toggle.SetWindowVariant(wx.WINDOW_VARIANT_MINI)
        background = parent.GetBackgroundColour()
        if background.IsOk():
            self.doc_tree_toggle.SetBackgroundColour(background)
        foreground = parent.GetForegroundColour()
        if foreground.IsOk():
            self.doc_tree_toggle.SetForegroundColour(foreground)
        best = self.doc_tree_toggle.GetBestSize()
        if expand_label != collapse_label:
            self.doc_tree_toggle.SetLabel(expand_label)
            alt_best = self.doc_tree_toggle.GetBestSize()
            best = wx.Size(
                max(best.width, alt_best.width),
                max(best.height, alt_best.height),
            )
            self.doc_tree_toggle.SetLabel(collapse_label)
        self.doc_tree_toggle.SetMinSize(best)
        self.doc_tree_toggle.SetMaxSize(best)
        self._doc_tree_toggle_size = best
        self.doc_tree_toggle.SetValue(True)
        self.doc_tree_toggle.SetToolTip(_("Hide hierarchy"))
        self.doc_tree_toggle.Bind(wx.EVT_TOGGLEBUTTON, self._on_toggle_doc_tree)
        return self.doc_tree_toggle

    def _on_toggle_doc_tree(self, _event: wx.Event) -> None:
        """Collapse or expand the document hierarchy panel."""

        if self.doc_tree_toggle and self.doc_tree_toggle.GetValue():
            self._expand_doc_tree()
        else:
            self._collapse_doc_tree()

    def _collapsed_doc_tree_width(self) -> int:
        """Return minimal width required to display the toggle handle."""

        if getattr(self, "doc_tree_toggle", None):
            margin = self.doc_tree_toggle.FromDIP(8)
            best = self.doc_tree_toggle.GetBestSize()
            width = best.width + margin
        else:
            width = self.FromDIP(24)
        return max(width, self._doc_tree_min_pane)

    def _default_doc_tree_width(self) -> int:
        """Heuristic width used when the saved value is not usable."""

        width = self.doc_splitter.GetClientSize().width
        if width <= 0:
            width = self.GetClientSize().width
        if width <= 0:
            width = 800
        return max(width // 4, self._doc_tree_min_pane)

    def _current_doc_tree_width(self) -> int:
        """Return the rendered width of the hierarchy pane."""

        width = 0
        if self.doc_splitter.IsSplit():
            tree_container = self.doc_splitter.GetWindow1()
            if tree_container is not None:
                width = tree_container.GetSize().width
                if width <= 0:
                    width = tree_container.GetClientSize().width
        if width <= 0:
            width = self.doc_splitter.GetSashPosition()
        if width <= 0:
            width = self._default_doc_tree_width()
        return max(width, self._doc_tree_min_pane)

    def _current_agent_splitter_width(self) -> int:
        """Return the width of the primary pane in the agent splitter."""

        width = 0
        if self.agent_splitter.IsSplit():
            primary = self.agent_splitter.GetWindow1()
            if primary is not None:
                width = primary.GetSize().width
                if width <= 0:
                    width = primary.GetClientSize().width
        if width <= 0:
            width = self.agent_splitter.GetMinimumPaneSize()
        return width

    def _collapse_doc_tree(self) -> None:
        """Hide the tree while keeping the toggle handle accessible."""

        if self._doc_tree_collapsed:
            return
        if self.doc_splitter.IsSplit():
            width = self._current_doc_tree_width()
            if width > self._doc_tree_min_pane:
                self._doc_tree_last_width = width
        if self.doc_tree_label:
            self.doc_tree_label.Hide()
        self.doc_tree.Hide()
        collapsed = self._collapsed_doc_tree_width()
        self.doc_tree_container.SetMinSize(wx.Size(collapsed, -1))
        self.doc_splitter.SetSashPosition(collapsed)
        self.doc_tree_container.Show()
        self.doc_tree_container.Layout()
        self._doc_tree_collapsed = True
        self._update_doc_tree_toggle_state()

    def _expand_doc_tree(self) -> None:
        """Restore the tree pane to its saved width."""

        if not self._doc_tree_collapsed:
            return
        self.doc_tree_container.SetMinSize(wx.Size(-1, -1))
        if self.doc_tree_label:
            self.doc_tree_label.Show()
        self.doc_tree.Show()
        target = self._doc_tree_last_width
        collapsed = self._collapsed_doc_tree_width()
        if target <= collapsed:
            target = self._default_doc_tree_width()
        self.doc_splitter.SetSashPosition(max(target, self._doc_tree_min_pane))
        self.doc_tree_container.Layout()
        self.doc_splitter.Layout()
        self._doc_tree_collapsed = False
        self._update_doc_tree_toggle_state()

    def _update_doc_tree_toggle_state(self) -> None:
        """Synchronize toggle labels, tooltips, and state."""

        if not getattr(self, "doc_tree_toggle", None):
            return
        collapse_label = _COLLAPSE_ARROW
        expand_label = _EXPAND_ARROW
        if self._doc_tree_collapsed:
            self.doc_tree_toggle.SetValue(False)
            self.doc_tree_toggle.SetLabel(expand_label)
            self.doc_tree_toggle.SetToolTip(_("Show hierarchy"))
        else:
            self.doc_tree_toggle.SetValue(True)
            self.doc_tree_toggle.SetLabel(collapse_label)
            self.doc_tree_toggle.SetToolTip(_("Hide hierarchy"))
        self.doc_tree_toggle.Refresh()

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

    def _clear_editor_panel(self) -> None:
        """Reset editor contents and reflect current visibility setting."""

        if not getattr(self, "editor", None):
            return
        self.editor.new_requirement()
        if self._is_editor_visible():
            self._show_editor_panel()
        else:
            self._hide_editor_panel()

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
        self.log_label.SetLabel(_("Log Console"))
        self.log_level_label.SetLabel(_("Log Level"))
        self._populate_log_level_choice(self.log_handler.level)
        self.open_logs_button.SetLabel(_("Open Log Folder"))


    def _confirm_discard_changes(self) -> bool:
        """Ask user to discard unsaved edits if editor has pending changes."""

        if not getattr(self, "editor", None):
            return True
        if not self.editor.is_dirty():
            return True
        if confirm(_("Discard unsaved changes?")):
            self.editor.discard_changes()
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

    def on_open_logs(self, _event: wx.CommandEvent) -> None:
        """Show the log directory in the system file browser."""

        from ..telemetry import log_event

        directory = get_log_directory()
        success = open_log_directory()
        log_event(
            "OPEN_LOG_FOLDER",
            {"directory": str(directory), "success": success},
        )
        if not success:
            message = _("Could not open log folder:\n%s") % directory
            show_error_dialog(self, message, title=_("Error"))

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
            token_limit_parameter=self.llm_settings.token_limit_parameter,
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
                token_limit_parameter,
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
                token_limit_parameter=token_limit_parameter or None,
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
            on_discard=self._handle_editor_discard,
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
            sash_width = self._current_agent_splitter_width() if agent_was_split else None
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
                if sash_width is not None:
                    self._agent_last_width = sash_width
                    self.agent_splitter.SetSashPosition(sash_width)
                    self._agent_last_width = self._current_agent_splitter_width()
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
        self.register_auxiliary_frame(frame)
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
        self.register_auxiliary_frame(frame)
        frame.Show()

    @staticmethod
    def _normalise_directory_path(path: Path) -> str:
        """Return canonical string representation for ``path``."""

        try:
            return str(path.resolve())
        except OSError:
            return str(path)

    def _sync_mcp_base_path(self, path: Path) -> None:
        """Persist MCP base path and restart server when needed."""

        new_base_path = self._normalise_directory_path(path)
        if self.mcp_settings.base_path == new_base_path:
            return
        auto_start = self.mcp_settings.auto_start
        self.mcp_settings = self.mcp_settings.model_copy(
            update={"base_path": new_base_path}
        )
        self.config.set_mcp_settings(self.mcp_settings)
        if auto_start:
            try:
                self.mcp.stop()
            except Exception:  # pragma: no cover - controller must not crash UI
                logger.exception(
                    "Failed to stop MCP server before applying new base path"
                )
            try:
                self.mcp.start(self.mcp_settings)
            except Exception:  # pragma: no cover - controller must not crash UI
                logger.exception(
                    "Failed to start MCP server after applying new base path"
                )

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
        self._sync_mcp_base_path(path)
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
        self._clear_editor_panel()

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
            self._clear_editor_panel()

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
            self._clear_editor_panel()
            self.splitter.UpdateSize()
            return False
        labels, freeform = self.docs_controller.collect_labels(prefix)
        self.panel.set_requirements(self.model.get_all(), derived_map)
        self.editor.update_labels_list(labels, freeform)
        self.panel.update_labels_list(labels)
        self._selected_requirement_id = None
        self._clear_editor_panel()
        total = len(self.model.get_all())
        visible = len(self.model.get_visible())
        derived_parent_count = len(derived_map) if derived_map else 0
        derived_child_count = (
            sum(len(ids) for ids in derived_map.values()) if derived_map else 0
        )
        filters_snapshot: dict[str, object] = {}
        filter_summary = ""
        if hasattr(self.panel, "current_filters"):
            raw_filters = getattr(self.panel, "current_filters", {})
            for key, value in raw_filters.items():
                if isinstance(value, dict):
                    trimmed = {k: v for k, v in value.items() if v}
                    if trimmed:
                        filters_snapshot[key] = trimmed
                elif isinstance(value, (list, tuple, set)):
                    if value:
                        filters_snapshot[key] = list(value)
                elif isinstance(value, bool):
                    if value:
                        filters_snapshot[key] = value
                elif value not in (None, ""):
                    filters_snapshot[key] = value
        if getattr(self.panel, "filter_summary", None):
            try:
                filter_summary = self.panel.filter_summary.GetLabel().strip()
            except Exception:  # pragma: no cover - defensive UI access
                filter_summary = ""
        doc_path = ""
        if self.current_dir:
            doc_path = str(self.current_dir / prefix)
        filter_details = ""
        if filters_snapshot:
            try:
                serialized = json.dumps(
                    filters_snapshot, ensure_ascii=False, sort_keys=True
                )
            except Exception:  # pragma: no cover - logging fallback
                serialized = str(filters_snapshot)
            filter_details = f"; active filters={serialized}"
            if filter_summary:
                filter_details += f" ({filter_summary})"
        elif filter_summary:
            filter_details = f"; filter summary={filter_summary}"
        if doc_path:
            location = f" from {doc_path}"
        else:
            location = ""
        logger.info(
            "Document %s loaded%s: %s requirement(s), %s visible after filters%s; %s parent(s) with %s derived child link(s)",
            prefix,
            location,
            total,
            visible,
            filter_details,
            derived_parent_count,
            derived_child_count,
        )
        if total and visible == 0 and filters_snapshot:
            logger.warning(
                "All %s requirement(s) for %s are hidden by the current filters",
                total,
                prefix,
            )
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
            show_error_dialog(self, str(exc), title=_("Error"))
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

    def _handle_editor_discard(self) -> bool:
        """Reload currently selected requirement into the editor."""

        if self._selected_requirement_id is None:
            return False
        requirement = self.model.get_by_id(self._selected_requirement_id)
        if not requirement:
            return False
        self.editor.load(requirement)
        return True

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

    def on_change_log_level(self, event: wx.CommandEvent) -> None:
        """Adjust the wx log handler level according to user selection."""

        if not getattr(self, "log_handler", None):
            return
        selection = event.GetSelection()
        if selection < 0 or selection >= len(self._log_level_values):
            return
        level = self._log_level_values[selection]
        self.log_handler.setLevel(level)
        self.config.set_log_level(level)

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
        desired = self._agent_last_width
        if desired <= 0:
            desired = self._default_agent_chat_sash()
        desired = max(desired, self.agent_splitter.GetMinimumPaneSize())
        self._show_agent_section()
        if not self.agent_splitter.IsSplit():
            self.agent_splitter.SplitVertically(
                self.splitter,
                self.agent_container,
                desired,
            )
        else:
            self.agent_splitter.SetSashPosition(desired)
        self._agent_last_width = self._current_agent_splitter_width()
        self.agent_panel.focus_input()
        self.config.set_agent_chat_shown(True)

    def _hide_agent_chat(self) -> None:
        if self.agent_splitter.IsSplit():
            self._agent_last_width = self._current_agent_splitter_width()
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
        self._doc_tree_last_width = self._current_doc_tree_width()
        self._doc_tree_collapsed = False
        self._update_doc_tree_toggle_state()
        if self.editor_menu_item:
            self.editor_menu_item.Check(self.config.get_editor_shown())
        self._apply_editor_visibility(persist=False)
        if self.agent_chat_menu_item:
            shown = self.config.get_agent_chat_shown()
            self.agent_chat_menu_item.Check(shown)
            if shown:
                desired = max(
                    self._agent_last_width,
                    self.agent_splitter.GetMinimumPaneSize(),
                )
                self._show_agent_section()
                if not self.agent_splitter.IsSplit():
                    self.agent_splitter.SplitVertically(
                        self.splitter,
                        self.agent_container,
                        desired,
                    )
                else:
                    self.agent_splitter.SetSashPosition(desired)
                self._agent_last_width = self._current_agent_splitter_width()
            else:
                if self.agent_splitter.IsSplit():
                    self._agent_last_width = self._current_agent_splitter_width()
                    self.agent_splitter.Unsplit(self.agent_container)
                self._hide_agent_section()

    def _save_layout(self) -> None:
        """Persist window geometry, splitter, console, and column widths."""
        if not self._doc_tree_collapsed and self.doc_splitter.IsSplit():
            current = self._current_doc_tree_width()
            if current > 0:
                self._doc_tree_last_width = current
        if self.agent_splitter.IsSplit():
            current = self._current_agent_splitter_width()
            if current > 0:
                self._agent_last_width = current
        self.config.save_layout(
            self,
            self.doc_splitter,
            self.main_splitter,
            self.panel,
            editor_splitter=self.splitter,
        )

    def register_auxiliary_frame(self, frame: wx.Frame) -> None:
        """Track ``frame`` so it is destroyed during main window shutdown."""

        if frame is None:
            return
        if frame in self._auxiliary_frames:
            return

        owner_ref = weakref.ref(self)
        frame_ref = weakref.ref(frame)

        def _on_aux_close(event: wx.Event) -> None:  # pragma: no cover - GUI event
            owner = owner_ref()
            target = frame_ref()
            if owner is not None and target is not None:
                owner._auxiliary_frames.discard(target)
            event.Skip()

        frame.Bind(wx.EVT_CLOSE, _on_aux_close)
        self._auxiliary_frames.add(frame)

    def _close_auxiliary_frames(self) -> None:
        """Destroy all registered auxiliary frames, ignoring errors."""

        remaining = len(self._auxiliary_frames)
        logger.info(
            "Shutdown step: closing %s auxiliary window(s)",
            remaining,
        )
        for aux in list(self._auxiliary_frames):
            if aux is None:
                continue
            try:
                if aux.IsBeingDeleted():
                    continue
                try:
                    if aux.IsShownOnScreen():
                        aux.Show(False)
                except Exception:  # pragma: no cover - defensive guard
                    logger.exception("Failed to hide auxiliary window during shutdown")
                closed = False
                try:
                    close = getattr(aux, "Close", None)
                    if callable(close):
                        try:
                            closed = bool(close(force=True))
                        except TypeError:
                            closed = bool(close(True))
                except Exception:  # pragma: no cover - close handlers must not abort shutdown
                    logger.exception("Failed to close auxiliary window during shutdown")
                if not closed and not aux.IsBeingDeleted():
                    aux.Destroy()
            except Exception:  # pragma: no cover - best effort cleanup
                logger.exception("Failed to destroy auxiliary window during shutdown")
        self._auxiliary_frames.clear()
        logger.info("Shutdown step completed: auxiliary windows closed")

    def _on_close(self, event: wx.Event) -> None:  # pragma: no cover - GUI event
        if self._shutdown_in_progress:
            if event is not None:
                event.Skip()
            return

        event_type = type(event).__name__ if event is not None else "<none>"
        can_veto = False
        if event is not None and hasattr(event, "CanVeto"):
            try:  # pragma: no cover - defensive guard around wx API
                can_veto = bool(event.CanVeto())
            except Exception:  # pragma: no cover - wx implementations may vary
                can_veto = False
        editor_dirty = bool(getattr(self, "editor", None) and self.editor.is_dirty())
        logger.info(
            "Close requested: event=%s, can_veto=%s, editor_dirty=%s",
            event_type,
            can_veto,
            editor_dirty,
        )
        if not self._confirm_discard_changes():
            logger.warning(
                "Close vetoed: pending edits remain and user declined to discard",
            )
            if event is not None and hasattr(event, "Veto") and can_veto:
                event.Veto()
            return
        self._shutdown_in_progress = True
        logger.info("Proceeding with shutdown sequence")
        logger.info("Shutdown step: saving layout")
        try:
            self._save_layout()
        except Exception:  # pragma: no cover - best effort cleanup
            logger.exception("Shutdown step failed: error while saving layout")
        else:
            logger.info("Shutdown step completed: layout persisted")

        remaining_editors = len(self._detached_editors)
        logger.info(
            "Shutdown step: closing %s detached editor window(s)",
            remaining_editors,
        )
        for frame in list(self._detached_editors.values()):
            try:
                frame.Destroy()
            except Exception:  # pragma: no cover - best effort cleanup
                logger.exception("Failed to destroy detached editor during shutdown")
        self._detached_editors.clear()
        logger.info("Shutdown step completed: detached editors closed")

        self._close_auxiliary_frames()

        if self.log_handler in logger.handlers:
            logger.info("Shutdown step: detaching wx log handler")
            logger.removeHandler(self.log_handler)

        mcp_running = False
        try:
            mcp_running = self.mcp.is_running()
        except Exception:  # pragma: no cover - defensive guard around controller
            logger.exception("Failed to query MCP controller state before shutdown")
        logger.info("Shutdown step: stopping MCP controller (running=%s)", mcp_running)
        try:
            self.mcp.stop()
        except Exception:  # pragma: no cover - controller stop must not block close
            logger.exception("Shutdown step failed: MCP controller stop raised an error")
        else:
            logger.info("Shutdown step completed: MCP controller stopped")

        if event is not None:
            event.Skip()
            logger.info("Shutdown sequence handed off to wx for finalization")

            def _finalize_close() -> None:
                if not self.IsBeingDeleted():
                    self.Destroy()
                self._request_exit_main_loop()

            wx.CallAfter(_finalize_close)
        else:
            logger.info("Shutdown sequence completed without wx event object")
            if not self.IsBeingDeleted():
                self.Destroy()
            self._request_exit_main_loop()

    def _request_exit_main_loop(self) -> None:
        """Ask wx to terminate the main loop if it is still running."""

        app = wx.GetApp()
        if not app:
            return

        exit_main_loop = getattr(app, "ExitMainLoop", None)
        if not callable(exit_main_loop):
            return

        is_running = getattr(app, "IsMainLoopRunning", None)
        try:
            if callable(is_running) and not is_running():
                return
        except Exception:  # pragma: no cover - defensive guard around wx API
            logger.exception("Failed to query wx main loop state before shutdown")

        try:
            exit_main_loop()
        except Exception:  # pragma: no cover - wx implementations may vary
            logger.exception("Failed to request wx main loop exit during shutdown")

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

    def _create_linked_copy(self, source: Requirement) -> tuple[Requirement, str]:
        if not (self.docs_controller and self.current_doc_prefix):
            raise RuntimeError("Documents controller not initialized")
        doc = self.docs_controller.documents.get(self.current_doc_prefix)
        if doc is None:
            raise RuntimeError("Document not loaded")

        new_id = self.docs_controller.next_item_id(self.current_doc_prefix)
        parent_rid = (getattr(source, "rid", "") or "").strip()
        if not parent_rid:
            parent_rid = rid_for(doc, source.id)

        existing_links: list[Link] = []
        for entry in getattr(source, "links", []):
            if isinstance(entry, Link):
                existing_links.append(
                    Link(rid=entry.rid, fingerprint=entry.fingerprint, suspect=entry.suspect)
                )
                continue
            try:
                existing_links.append(Link.from_raw(entry))
            except (TypeError, ValueError):
                logger.warning(
                    "Ignoring invalid link %r while deriving requirement %s",
                    entry,
                    getattr(source, "rid", source.id),
                )

        parent_link = Link(
            rid=parent_rid,
            fingerprint=requirement_fingerprint(source),
            suspect=False,
        )
        new_links = [*existing_links, parent_link]

        clone = replace(
            source,
            id=new_id,
            title=f"{_('(Derived)')} {source.title}".strip(),
            modified_at="",
            revision=1,
            links=new_links,
        )
        return clone, parent_rid

    def on_derive_requirement(self, req_id: int) -> None:
        """Create a requirement derived from ``req_id`` and open it."""

        if not (self.docs_controller and self.current_doc_prefix):
            return
        source = self.model.get_by_id(req_id)
        if not source:
            return
        clone, parent_rid = self._create_linked_copy(source)
        self.docs_controller.add_requirement(self.current_doc_prefix, clone)
        self.panel.record_link(parent_rid, clone.id)
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
        self._clear_editor_panel()
        self.splitter.UpdateSize()
        labels, freeform = self.docs_controller.collect_labels(
            self.current_doc_prefix
        )
        self.editor.update_labels_list(labels, freeform)
        self.panel.update_labels_list(labels)

    def on_delete_requirement(self, req_id: int) -> None:
        """Delete requirement ``req_id`` and refresh views."""

        self.on_delete_requirements([req_id])
