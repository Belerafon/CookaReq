"""Helpers for managing sections and layout within the main frame."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

import wx

from ...i18n import _
from ..splitter_utils import refresh_splitter_highlight, style_splitter
from ..widgets import SectionContainer

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from .frame import MainFrame


class MainFrameSectionsMixin:
    """Provide high level helpers for the hierarchical UI layout."""

    doc_splitter: wx.SplitterWindow
    agent_splitter: wx.SplitterWindow
    splitters_initialized: bool

    def _create_splitter(self, parent: wx.Window) -> wx.SplitterWindow:
        """Create a splitter with consistent styling and behaviour."""

        splitter = wx.SplitterWindow(parent)
        style_splitter(splitter)
        self._disable_splitter_unsplit(splitter)
        return splitter

    def _create_section(
        self: "MainFrame",
        parent: wx.Window,
        *,
        label: str,
        factory: Callable[[wx.Window], wx.Window],
        header_factory: Callable[[wx.Window], Sequence[wx.Window]] | None = None,
        allow_label_shrink: bool = False,
        padding: int = 0,
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

    # ------------------------------------------------------------------
    # visibility and localisation helpers
    def _apply_doc_tree_visibility(self: "MainFrame", *, persist: bool) -> None:
        """Update hierarchy pane visibility based on the menu state."""

        if not getattr(self, "doc_splitter", None) or not getattr(self, "doc_tree_container", None):
            return
        if not self.hierarchy_menu_item:
            return
        shown = self.hierarchy_menu_item.IsChecked()
        minimum = max(self._doc_tree_min_pane, 1)
        target = max(self._doc_tree_last_sash, minimum)
        if shown:
            self.doc_tree_container.Show()
            if not self.doc_splitter.IsSplit():
                self.doc_splitter.SplitVertically(
                    self.doc_tree_container,
                    self.agent_splitter,
                    target,
                )
            else:
                self.doc_splitter.SetSashPosition(target)
            refresh_splitter_highlight(self.doc_splitter)
            self._doc_tree_last_sash = self.doc_splitter.GetSashPosition()
            if persist:
                self.config.set_doc_tree_shown(True)
                self.config.set_doc_tree_sash(self._doc_tree_last_sash)
        else:
            if self.doc_splitter.IsSplit():
                self._doc_tree_last_sash = self.doc_splitter.GetSashPosition()
                self.doc_splitter.Unsplit(self.doc_tree_container)
            self.doc_tree_container.Hide()
            refresh_splitter_highlight(self.doc_splitter)
            if persist:
                self.config.set_doc_tree_shown(False)
                self.config.set_doc_tree_sash(self._doc_tree_last_sash)
        self.doc_splitter.UpdateSize()
        self.Layout()

    def _is_doc_tree_visible(self: "MainFrame") -> bool:
        """Return whether the hierarchy pane is currently shown."""

        return bool(self.hierarchy_menu_item and self.hierarchy_menu_item.IsChecked())

    def on_toggle_hierarchy(self: "MainFrame", _event: wx.CommandEvent | None) -> None:
        """Handle hierarchy visibility toggles from the menu."""

        if not self.hierarchy_menu_item:
            return
        self._apply_doc_tree_visibility(persist=True)

    def _apply_agent_chat_visibility(self: "MainFrame", *, persist: bool) -> None:
        """Update agent chat pane visibility based on the menu state."""

        if not self.agent_chat_menu_item:
            return
        shown = self.agent_chat_menu_item.IsChecked()
        minimum = max(self.agent_splitter.GetMinimumPaneSize(), 1)
        target = max(self._agent_last_sash, minimum)
        if shown:
            self._show_agent_section()
            if not self.agent_splitter.IsSplit():
                self.agent_splitter.SplitVertically(
                    self.splitter,
                    self.agent_container,
                    target,
                )
            else:
                self.agent_splitter.SetSashPosition(target)
            refresh_splitter_highlight(self.agent_splitter)
            self._agent_last_sash = self.agent_splitter.GetSashPosition()
            if persist:
                self.config.set_agent_chat_shown(True)
                self.config.set_agent_chat_sash(self._agent_last_sash)
            self.agent_panel.focus_input()
        else:
            if self.agent_splitter.IsSplit():
                self._agent_last_sash = self.agent_splitter.GetSashPosition()
                self.agent_splitter.Unsplit(self.agent_container)
            self._hide_agent_section()
            refresh_splitter_highlight(self.agent_splitter)
            if persist:
                self.config.set_agent_chat_shown(False)
                self.config.set_agent_chat_sash(self._agent_last_sash)
                self.config.set_agent_history_sash(self.agent_panel.history_sash)
        self.agent_splitter.UpdateSize()
        self.Layout()

    def _is_agent_chat_visible(self: "MainFrame") -> bool:
        """Return whether the agent chat pane is currently shown."""

        return bool(self.agent_chat_menu_item and self.agent_chat_menu_item.IsChecked())

    def _show_editor_panel(self: "MainFrame") -> None:
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
        refresh_splitter_highlight(self.splitter)

    def _hide_editor_panel(self: "MainFrame") -> None:
        """Hide the editor section and its container."""

        self.editor.Hide()
        self.editor_container.Hide()
        refresh_splitter_highlight(self.splitter)

    def _clear_editor_panel(self: "MainFrame") -> None:
        """Reset editor contents and reflect current visibility setting."""

        if not getattr(self, "editor", None):
            return
        self.editor.new_requirement()
        if self._is_editor_visible():
            self._show_editor_panel()
        else:
            self._hide_editor_panel()

    def _is_editor_visible(self: "MainFrame") -> bool:
        """Return ``True`` when the main editor pane is enabled."""

        return bool(self.editor_menu_item and self.editor_menu_item.IsChecked())

    def _show_agent_section(self: "MainFrame") -> None:
        """Display the agent chat section and ensure layout refresh."""

        self.agent_container.Show()
        self.agent_panel.Show()
        self.agent_container.Layout()
        self.agent_panel.Layout()
        refresh_splitter_highlight(self.agent_splitter)

    def _hide_agent_section(self: "MainFrame") -> None:
        """Hide the agent chat widgets to free screen space."""

        self.agent_panel.Hide()
        self.agent_container.Hide()
        refresh_splitter_highlight(self.agent_splitter)

    def _update_section_labels(self: "MainFrame") -> None:
        """Refresh captions for titled sections according to current locale."""

        self.doc_tree_label.SetLabel(_("Hierarchy"))
        self.editor_label.SetLabel(_("Editor"))
        self.agent_label.SetLabel(_("Agent Chat"))
        if hasattr(self, "_update_requirements_label"):
            self._update_requirements_label()
        else:  # pragma: no cover - defensive fallback if mixin missing
            self.list_label.SetLabel(_("Requirements"))
        self.update_log_console_labels()

    def _confirm_discard_changes(self: "MainFrame") -> bool:
        """Ask user to discard unsaved edits if editor has pending changes."""

        from . import confirm

        if not getattr(self, "editor", None):
            return True
        if not self.editor.is_dirty():
            return True
        if confirm(_("Discard unsaved changes?")):
            self.editor.discard_changes()
            return True
        return False

    def _default_editor_sash(self: "MainFrame") -> int:
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

    def _default_agent_chat_sash(self: "MainFrame") -> int:
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

    def _apply_editor_visibility(self: "MainFrame", *, persist: bool) -> None:
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

    def on_toggle_requirement_editor(self: "MainFrame", _event: wx.CommandEvent) -> None:
        """Toggle visibility of the requirement editor pane."""

        if not self.editor_menu_item:
            return
        if not self.editor_menu_item.IsChecked():
            if not self._confirm_discard_changes():
                self.editor_menu_item.Check(True)
                return
        self._apply_editor_visibility(persist=True)

    # ------------------------------------------------------------------
    # persistence helpers
    def _load_layout(self: "MainFrame") -> None:
        """Restore window geometry, splitter, console, and column widths."""

        self.config.restore_layout(
            self,
            self.doc_splitter,
            self.main_splitter,
            self.panel,
            self.log_panel,
            self.navigation.log_menu_item,
            editor_splitter=self.splitter,
        )
        self._doc_tree_last_sash = self.config.get_doc_tree_sash(
            self.doc_splitter.GetSashPosition()
        )
        self._agent_last_sash = self.config.get_agent_chat_sash(
            self._default_agent_chat_sash()
        )
        history_sash = self.config.get_agent_history_sash(
            self.agent_panel.default_history_sash()
        )
        self.agent_panel.apply_history_sash(history_sash)
        if self.hierarchy_menu_item:
            self.hierarchy_menu_item.Check(self.config.get_doc_tree_shown())
            self._apply_doc_tree_visibility(persist=False)
        if self.editor_menu_item:
            self.editor_menu_item.Check(self.config.get_editor_shown())
        self._apply_editor_visibility(persist=False)
        if self.agent_chat_menu_item:
            self.agent_chat_menu_item.Check(self.config.get_agent_chat_shown())
            self._apply_agent_chat_visibility(persist=False)

    def _save_layout(self: "MainFrame") -> None:
        """Persist window geometry, splitter, console, and column widths."""

        doc_tree_sash = (
            self.doc_splitter.GetSashPosition()
            if self.doc_splitter.IsSplit()
            else self._doc_tree_last_sash
        )
        agent_sash = (
            self.agent_splitter.GetSashPosition()
            if self.agent_splitter.IsSplit()
            else self._agent_last_sash
        )
        self.config.save_layout(
            self,
            self.doc_splitter,
            self.main_splitter,
            self.panel,
            editor_splitter=self.splitter,
            agent_splitter=self.agent_splitter,
            doc_tree_shown=self._is_doc_tree_visible(),
            doc_tree_sash=doc_tree_sash,
            agent_chat_shown=self._is_agent_chat_visible(),
            agent_chat_sash=agent_sash,
            agent_history_sash=self.agent_panel.history_sash,
        )

    # ------------------------------------------------------------------
    # splitter behaviour
    def _disable_splitter_unsplit(self: "MainFrame", splitter: wx.SplitterWindow) -> None:
        """Attach handlers preventing ``splitter`` from unsplitting on double click."""

        splitter.Bind(wx.EVT_SPLITTER_DOUBLECLICKED, self._prevent_splitter_unsplit)
        splitter.Bind(wx.EVT_SPLITTER_DCLICK, self._prevent_splitter_unsplit)

    def _prevent_splitter_unsplit(self: "MainFrame", event: wx.SplitterEvent) -> None:
        """Block attempts to unsplit panes initiated by double clicks."""

        event.Veto()
