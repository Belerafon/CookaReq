"""Widgets used to render chat transcript entries."""

from __future__ import annotations

import json
from typing import Any, Callable

import wx

from ...i18n import _
from ..text import normalize_for_display


def _blend_colour(base: wx.Colour, other: wx.Colour, weight: float) -> wx.Colour:
    weight = max(0.0, min(weight, 1.0))
    return wx.Colour(
        int(base.Red() * (1.0 - weight) + other.Red() * weight),
        int(base.Green() * (1.0 - weight) + other.Green() * weight),
        int(base.Blue() * (1.0 - weight) + other.Blue() * weight),
    )


FooterFactory = Callable[[wx.Window], wx.Sizer | wx.Window | None]


class MessageBubble(wx.Panel):
    """Simple chat bubble with copy support and optional text selection."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        role_label: str,
        timestamp: str,
        text: str,
        align: str,
        allow_selection: bool = False,
        render_markdown: bool = False,
        footer_factory: FooterFactory | None = None,
    ) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(parent.GetBackgroundColour())
        self.SetDoubleBuffered(True)

        display_text = normalize_for_display(text)
        self._text_value = display_text
        self._wrap_width = 0
        self._content_padding = self.FromDIP(12)
        self._copy_menu_id = wx.Window.NewControlId()
        self.Bind(wx.EVT_MENU, self._on_copy, id=self._copy_menu_id)
        self._allow_selection = allow_selection
        self._copy_selection_menu_id: int | None = None
        self._selection_checker: Callable[[], bool] | None = None
        self._selection_getter: Callable[[], str] | None = None
        if allow_selection:
            self._copy_selection_menu_id = wx.Window.NewControlId()
            self.Bind(wx.EVT_MENU, self._on_copy_selection, id=self._copy_selection_menu_id)

        user_highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
        user_text = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHTTEXT)
        agent_bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        agent_text = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)

        if align == "right":
            bubble_bg = user_highlight
            bubble_fg = user_text
            meta_colour = _blend_colour(user_text, wx.Colour(255, 255, 255), 0.4)
        else:
            bubble_bg = agent_bg
            bubble_fg = agent_text
            meta_colour = wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT)

        outer = wx.BoxSizer(wx.VERTICAL)

        bubble = wx.Panel(self, style=wx.BORDER_NONE)
        bubble.SetBackgroundColour(bubble_bg)
        bubble.SetForegroundColour(bubble_fg)
        bubble.SetDoubleBuffered(True)
        bubble.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        bubble.Bind(wx.EVT_PAINT, self._on_bubble_paint)
        bubble.Bind(wx.EVT_ERASE_BACKGROUND, self._on_bubble_erase_background)
        self._bubble_corner_radius: float = max(float(self.FromDIP(8)), 2.0)
        bubble_sizer = wx.BoxSizer(wx.VERTICAL)
        bubble.SetSizer(bubble_sizer)

        header_text = role_label if not timestamp else f"{role_label} • {timestamp}"
        header_align_flag = wx.ALIGN_RIGHT if align == "right" else 0
        header = wx.StaticText(bubble, label=header_text, style=header_align_flag)
        header.SetBackgroundColour(bubble_bg)
        header.SetForegroundColour(meta_colour)
        header_font = header.GetFont()
        if header_font.IsOk():
            header_font.MakeSmaller()
            header.SetFont(header_font)

        header_row = wx.BoxSizer(wx.HORIZONTAL)
        header_row.Add(header, 1, wx.ALIGN_CENTER_VERTICAL)
        header_row.AddSpacer(self.FromDIP(4))
        header_row.Add(self._create_copy_button(bubble), 0, wx.ALIGN_CENTER_VERTICAL)
        bubble_sizer.Add(
            header_row,
            0,
            wx.TOP | wx.LEFT | wx.RIGHT,
            self._content_padding,
        )

        if allow_selection:
            if render_markdown:
                from .markdown_view import MarkdownContent

                markdown = MarkdownContent(
                    bubble,
                    markdown=text,
                    background_colour=bubble_bg,
                    foreground_colour=bubble_fg,
                )
                markdown.SetMinSize(wx.Size(self.FromDIP(160), -1))
                self._text = markdown

                self._selection_checker = markdown.HasSelection
                self._selection_getter = markdown.GetSelectionText
            else:
                style = (
                    wx.TE_MULTILINE
                    | wx.TE_READONLY
                    | wx.TE_WORDWRAP
                    | wx.TE_NO_VSCROLL
                    | wx.BORDER_NONE
                )
                text_ctrl = wx.TextCtrl(bubble, value=display_text, style=style)
                text_ctrl.SetBackgroundColour(bubble_bg)
                text_ctrl.SetForegroundColour(bubble_fg)
                text_ctrl.SetMinSize(wx.Size(self.FromDIP(160), -1))
                self._text = text_ctrl

                def has_selection(tc: wx.TextCtrl = text_ctrl) -> bool:
                    start, end = tc.GetSelection()
                    return end > start

                self._selection_checker = has_selection
                self._selection_getter = text_ctrl.GetStringSelection
        else:
            text_align_flag = wx.ALIGN_RIGHT if align == "right" else 0
            self._text = wx.StaticText(bubble, label=display_text, style=text_align_flag)
            self._text.SetForegroundColour(bubble_fg)
            self._text.SetBackgroundColour(bubble_bg)
            self._text.Wrap(self.FromDIP(320))
        bubble_sizer.Add(
            self._text,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            self._content_padding,
        )

        footer_targets: list[wx.Window] = []
        if footer_factory is not None:
            footer = footer_factory(bubble)
            if isinstance(footer, wx.Sizer):
                bubble_sizer.Add(
                    footer,
                    0,
                    wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                    self._content_padding,
                )
                for item in footer.GetChildren():
                    window = item.GetWindow()
                    if window is not None:
                        footer_targets.append(window)
            elif isinstance(footer, wx.Window):
                bubble_sizer.Add(
                    footer,
                    0,
                    wx.LEFT | wx.RIGHT | wx.BOTTOM,
                    self._content_padding,
                )
                footer_targets.append(footer)

        bubble.Bind(wx.EVT_SIZE, self._on_bubble_resize)
        self.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        bubble.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self._attach_context_menu_handlers(self._text)
        for target in footer_targets:
            self._attach_context_menu_handlers(target)

        outer.Add(bubble, 0, wx.EXPAND)

        self.SetSizer(outer)

    def _on_bubble_erase_background(self, event: wx.EraseEvent) -> None:
        event.Skip(False)

    def _on_bubble_paint(self, event: wx.PaintEvent) -> None:
        bubble = event.GetEventObject()
        if not isinstance(bubble, wx.Window):
            return
        size = bubble.GetClientSize()
        if size.width <= 0 or size.height <= 0:
            return

        parent_colour = self.GetBackgroundColour()
        bubble_colour = bubble.GetBackgroundColour()
        radius = min(self._bubble_corner_radius, min(size.width, size.height) / 2.0)

        dc = wx.AutoBufferedPaintDC(bubble)
        dc.SetBackground(wx.Brush(parent_colour))
        dc.Clear()

        gc = wx.GraphicsContext.Create(dc)
        rect_width = max(size.width - 1, 0)
        rect_height = max(size.height - 1, 0)
        if gc is not None:
            gc.SetPen(wx.Pen(bubble_colour))
            gc.SetBrush(wx.Brush(bubble_colour))
            gc.DrawRoundedRectangle(0, 0, rect_width, rect_height, radius)
        else:
            brush = wx.Brush(bubble_colour)
            pen = wx.Pen(bubble_colour)
            dc.SetBrush(brush)
            dc.SetPen(pen)
            dc.DrawRoundedRectangle(0, 0, rect_width, rect_height, radius)

    def _attach_context_menu_handlers(self, widget: wx.Window | None) -> None:
        if widget is None:
            return
        widget.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        for child in widget.GetChildren():
            self._attach_context_menu_handlers(child)

    def _on_bubble_resize(self, event: wx.SizeEvent) -> None:
        event.Skip()
        width = event.GetSize().width - 2 * self._content_padding
        width = max(width, self.FromDIP(120))
        if isinstance(self._text, wx.StaticText):
            if abs(width - self._wrap_width) > self.FromDIP(4):
                self._wrap_width = width
                self._text.Wrap(width)
        elif isinstance(self._text, wx.TextCtrl):
            self._text.SetMinSize(wx.Size(width, -1))
            self._text.Layout()

    def _create_copy_button(self, parent: wx.Window) -> wx.Window:
        icon_size = self.FromDIP(16)
        bitmap = wx.ArtProvider.GetBitmap(
            wx.ART_COPY,
            wx.ART_BUTTON,
            wx.Size(icon_size, icon_size),
        )
        if bitmap.IsOk():
            button = wx.BitmapButton(
                parent,
                bitmap=bitmap,
                style=wx.BU_EXACTFIT | wx.BORDER_NONE,
            )
            button.SetBackgroundColour(parent.GetBackgroundColour())
        else:
            button = wx.Button(parent, label=_("Copy"), style=wx.BU_EXACTFIT)
        button.SetToolTip(_("Copy message"))
        button.Bind(wx.EVT_BUTTON, self._on_copy)
        return button

    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
        menu = wx.Menu()
        if self._copy_selection_menu_id is not None:
            item = menu.Append(self._copy_selection_menu_id, _("Copy selection"))
            item.Enable(self._has_selection())
        menu.Append(self._copy_menu_id, _("Copy message"))
        self.PopupMenu(menu)
        menu.Destroy()
        event.Skip(False)

    def _on_copy(self, _event: wx.CommandEvent) -> None:
        if not self._text_value:
            return
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(self._text_value))
            finally:
                wx.TheClipboard.Close()

    def _on_copy_selection(self, _event: wx.CommandEvent) -> None:
        if not self._allow_selection:
            return
        selection = self._get_selection_text()
        if not selection:
            return
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(selection))
            finally:
                wx.TheClipboard.Close()

    def _has_selection(self) -> bool:
        if self._selection_checker is None:
            return False
        try:
            return bool(self._selection_checker())
        except Exception:  # pragma: no cover - defensive
            return False

    def _get_selection_text(self) -> str:
        if self._selection_getter is not None:
            try:
                return self._selection_getter()
            except Exception:  # pragma: no cover - defensive
                return ""
        return ""


class TranscriptMessagePanel(wx.Panel):
    """Compact chat entry view for a prompt/response pair."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        prompt: str,
        response: str,
        prompt_timestamp: str = "",
        response_timestamp: str = "",
        on_regenerate: Callable[[], None] | None = None,
        regenerate_enabled: bool = True,
    ) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(parent.GetBackgroundColour())
        self.SetDoubleBuffered(True)

        outer = wx.BoxSizer(wx.VERTICAL)
        padding = self.FromDIP(4)

        user_bubble = MessageBubble(
            self,
            role_label=_("You"),
            timestamp=prompt_timestamp,
            text=prompt,
            align="right",
        )
        outer.Add(user_bubble, 0, wx.EXPAND | wx.ALL, padding)

        agent_bubble = MessageBubble(
            self,
            role_label=_("Agent"),
            timestamp=response_timestamp,
            text=response,
            align="left",
            allow_selection=True,
            render_markdown=True,
            footer_factory=(
                lambda container: self._create_regenerate_footer(
                    container,
                    on_regenerate=on_regenerate,
                    enabled=regenerate_enabled,
                )
                if on_regenerate is not None
                else None
            ),
        )
        outer.Add(agent_bubble, 0, wx.EXPAND | wx.ALL, padding)

        self.SetSizer(outer)

    def _create_regenerate_footer(
        self,
        container: wx.Window,
        *,
        on_regenerate: Callable[[], None],
        enabled: bool,
    ) -> wx.Sizer:
        button = wx.Button(container, label=_("Перегенерить"), style=wx.BU_EXACTFIT)
        button.SetBackgroundColour(container.GetBackgroundColour())
        button.SetForegroundColour(container.GetForegroundColour())
        button.SetToolTip(_("Запустить генерацию ответа заново"))
        button.Bind(wx.EVT_BUTTON, lambda _event: on_regenerate())
        button.Enable(enabled)
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.AddStretchSpacer()
        sizer.Add(button, 0, wx.ALIGN_CENTER_VERTICAL)
        return sizer
