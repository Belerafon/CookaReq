"""Widgets used to render chat transcript entries."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from collections.abc import Callable

import wx

from ...i18n import _
from ..agent_chat_panel.tool_summaries import (
    ToolCallSummary,
    render_tool_summary_markdown,
)
from ..text import normalize_for_display


def _is_window_usable(window: wx.Window | None) -> bool:
    """Return True when the wx window can be safely accessed."""

    if window is None:
        return False
    try:
        # ``bool(window)`` delegates to ``IsOk`` without raising on GTK.
        if not window:
            return False
    except RuntimeError:
        return False

    is_being_deleted = getattr(window, "IsBeingDeleted", None)
    if callable(is_being_deleted):
        try:
            if is_being_deleted():
                return False
        except RuntimeError:
            return False
    return True


def _blend_colour(base: wx.Colour, other: wx.Colour, weight: float) -> wx.Colour:
    weight = max(0.0, min(weight, 1.0))
    return wx.Colour(
        int(base.Red() * (1.0 - weight) + other.Red() * weight),
        int(base.Green() * (1.0 - weight) + other.Green() * weight),
        int(base.Blue() * (1.0 - weight) + other.Blue() * weight),
    )


def _relative_luminance(colour: wx.Colour) -> float:
    if not colour.IsOk():
        return 255.0
    return 0.2126 * colour.Red() + 0.7152 * colour.Green() + 0.0722 * colour.Blue()


def _is_dark_colour(colour: wx.Colour) -> bool:
    return _relative_luminance(colour) < 128.0


def _contrast_ratio(colour_a: wx.Colour, colour_b: wx.Colour) -> float:
    lum_a = _relative_luminance(colour_a) / 255.0
    lum_b = _relative_luminance(colour_b) / 255.0
    lighter = max(lum_a, lum_b)
    darker = min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def _pick_best_contrast(background: wx.Colour, *candidates: wx.Colour) -> wx.Colour:
    if not candidates:
        return wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
    best = candidates[0]
    best_ratio = _contrast_ratio(best, background)
    for candidate in candidates[1:]:
        ratio = _contrast_ratio(candidate, background)
        if ratio > best_ratio:
            best_ratio = ratio
            best = candidate
    return best


def _soften_user_highlight(
    highlight: wx.Colour, *, background: wx.Colour
) -> wx.Colour:
    """Return pastel variant of the system highlight colour."""

    if not background.IsOk():
        background = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
    weight = 0.7 if not _is_dark_colour(background) else 0.45
    return _blend_colour(highlight, background, weight)


def _agent_tint(base: wx.Colour) -> wx.Colour:
    """Add a soft green tint to the agent message background."""

    if not base.IsOk():
        base = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
    if _is_dark_colour(base):
        accent = wx.Colour(58, 96, 70)
        return _blend_colour(base, accent, 0.22)
    accent = wx.Colour(207, 233, 214)
    return _blend_colour(base, accent, 0.3)


@dataclass(frozen=True)
class MessageBubblePalette:
    """Colour palette applied to message bubbles."""

    background: wx.Colour
    foreground: wx.Colour
    meta: wx.Colour


_TOOL_ACCENT_COLOURS: tuple[wx.Colour, ...] = (
    wx.Colour(196, 221, 255),
    wx.Colour(202, 242, 255),
    wx.Colour(210, 245, 221),
    wx.Colour(255, 232, 206),
    wx.Colour(244, 224, 255),
    wx.Colour(255, 226, 235),
)


def _tool_bubble_palette(
    parent_background: wx.Colour, tool_name: str
) -> MessageBubblePalette:
    base = (
        parent_background
        if parent_background.IsOk()
        else wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
    )
    normalized = tool_name.strip().lower() or "tool"
    digest = hashlib.sha1(normalized.encode("utf-8")).digest()
    accent = _TOOL_ACCENT_COLOURS[digest[0] % len(_TOOL_ACCENT_COLOURS)]
    weight = 0.55 if not _is_dark_colour(base) else 0.35
    background = _blend_colour(base, accent, weight)
    foreground = _pick_best_contrast(
        background,
        wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT),
        wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNTEXT),
        wx.Colour(20, 20, 20),
        wx.Colour(70, 70, 70),
    )
    meta = _blend_colour(foreground, background, 0.4)
    return MessageBubblePalette(background, foreground, meta)


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
        palette: MessageBubblePalette | None = None,
        width_hint: int | None = None,
        on_width_change: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(parent.GetBackgroundColour())
        self.SetDoubleBuffered(True)
        self._destroyed = False
        self._pending_width_update = False
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

        self._on_width_change = on_width_change
        try:
            hint_value = int(width_hint) if width_hint is not None else None
        except (TypeError, ValueError):
            hint_value = None
        if hint_value is not None and hint_value <= 0:
            hint_value = None
        self._explicit_width_hint = hint_value
        self._initial_width_hint = hint_value

        display_text = normalize_for_display(text)
        self._text_value = display_text
        self._wrap_width = 0
        self._bubble_max_width_ratio = 0.85
        self._bubble_margin = self.FromDIP(48)
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

        palette = (
            palette
            if palette is not None
            else self._build_default_palette(
                align=align,
                parent_background=self.GetBackgroundColour(),
            )
        )
        bubble_bg = palette.background
        bubble_fg = palette.foreground
        meta_colour = palette.meta

        is_user_message = align == "right"

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
        self._bubble = bubble
        self._bubble_sizer = bubble_sizer
        self._min_bubble_width = (
            self.FromDIP(160)
            if allow_selection or render_markdown
            else self.FromDIP(120)
        )
        self._cached_width_constraints: tuple[int, int] | None = None

        header_text = role_label if not timestamp else f"{role_label} • {timestamp}"
        header_align_flag = wx.ALIGN_RIGHT if align == "right" else 0
        header = wx.StaticText(bubble, label=header_text, style=header_align_flag)
        header.SetBackgroundColour(bubble_bg)
        header.SetForegroundColour(meta_colour)
        header_font = header.GetFont()
        if header_font.IsOk():
            header_font.MakeSmaller()
            header.SetFont(header_font)
        self._header = header
        self._role_label = role_label
        self._timestamp = timestamp
        self._align = align
        self._render_markdown = render_markdown

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

        base_font = self.GetFont()
        message_font: wx.Font | None = None
        if base_font.IsOk():
            if is_user_message:
                try:
                    user_font = wx.Font(base_font)
                except Exception:
                    message_font = base_font
                else:
                    try:
                        user_font.MakeLarger()
                    except Exception:
                        message_font = base_font
                    else:
                        message_font = user_font if user_font.IsOk() else base_font
            else:
                message_font = base_font

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
                if message_font is not None and message_font.IsOk():
                    markdown.SetFont(message_font)
                self._text = markdown

                hidden_text = wx.TextCtrl(
                    bubble,
                    value=display_text,
                    style=(
                        wx.TE_MULTILINE
                        | wx.TE_READONLY
                        | wx.TE_WORDWRAP
                        | wx.TE_NO_VSCROLL
                        | wx.BORDER_NONE
                    ),
                )
                hidden_text.SetBackgroundColour(bubble_bg)
                hidden_text.SetForegroundColour(bubble_fg)
                hidden_text.Hide()
                bubble_sizer.Add(hidden_text, 0, wx.EXPAND)
                self._hidden_text_copy = hidden_text

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
                if message_font is not None and message_font.IsOk():
                    text_ctrl.SetFont(message_font)
                self._text = text_ctrl

                def has_selection(tc: wx.TextCtrl = text_ctrl) -> bool:
                    start, end = tc.GetSelection()
                    return end > start

                self._selection_checker = has_selection
                self._selection_getter = text_ctrl.GetStringSelection
        else:
            text_align_flag = wx.ALIGN_LEFT
            self._text = wx.StaticText(bubble, label=display_text, style=text_align_flag)
            self._text.SetForegroundColour(bubble_fg)
            self._text.SetBackgroundColour(bubble_bg)
            if message_font is not None and message_font.IsOk():
                self._text.SetFont(message_font)
            self._text.Wrap(self.FromDIP(320))
        bubble_sizer.Add(
            self._text,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            self._content_padding,
        )

        footer_targets: list[wx.Window] = []
        footer_object: wx.Sizer | wx.Window | None = None
        if footer_factory is not None:
            footer = footer_factory(bubble)
            if isinstance(footer, wx.Sizer):
                bubble_sizer.Add(
                    footer,
                    0,
                    wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                    self._content_padding,
                )
                footer_object = footer
                for item in footer.GetChildren():
                    window = item.GetWindow()
                    if window is not None:
                        footer_targets.append(window)
            elif isinstance(footer, wx.Window):
                bubble_sizer.Add(
                    footer,
                    0,
                    wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                    self._content_padding,
                )
                footer_object = footer
                footer_targets.append(footer)
        self._footer = footer_object

        bubble.Bind(wx.EVT_SIZE, self._on_bubble_resize)
        self.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        bubble.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self._attach_context_menu_handlers(self._text)
        for target in footer_targets:
            self._attach_context_menu_handlers(target)

        alignment_row = wx.BoxSizer(wx.HORIZONTAL)
        if align == "right":
            alignment_row.AddStretchSpacer()
            alignment_row.Add(bubble, 0)
        else:
            alignment_row.Add(bubble, 0)
            alignment_row.AddStretchSpacer()
        outer.Add(alignment_row, 1, wx.EXPAND)

        self.SetSizer(outer)
        self.Bind(wx.EVT_SIZE, self._on_panel_resize)

        if self._initial_width_hint is not None:
            initial_width = self._initial_width_hint
            size = wx.Size(initial_width, -1)
            try:
                bubble.SetMinSize(size)
                bubble.SetMaxSize(size)
                bubble.SetInitialSize(size)
            except RuntimeError:
                pass
            else:
                self._cached_width_constraints = (initial_width, initial_width)

        self._schedule_width_update()

    # ------------------------------------------------------------------
    def update_header(self, role_label: str, timestamp: str) -> None:
        """Update the header label and timestamp."""

        header = self._header
        if not _is_window_usable(header):
            return
        self._role_label = role_label
        self._timestamp = timestamp
        header_text = role_label if not timestamp else f"{role_label} • {timestamp}"
        if header.GetLabel() != header_text:
            header.SetLabel(header_text)

    # ------------------------------------------------------------------
    def update_text(self, text: str) -> None:
        """Refresh main message text without rebuilding the widget."""

        display_text = normalize_for_display(text)
        if display_text == self._text_value:
            return
        self._text_value = display_text
        control = self._text
        if isinstance(control, wx.StaticText):
            control.SetLabel(display_text)
            control.Wrap(self.FromDIP(320))
        elif isinstance(control, wx.TextCtrl):
            control.ChangeValue(display_text)
        else:
            from .markdown_view import MarkdownContent

            if isinstance(control, MarkdownContent):
                control.SetMarkdown(text)

    # ------------------------------------------------------------------
    def set_footer(self, footer_factory: FooterFactory | None) -> None:
        """Replace the optional footer contents."""

        bubble = self._bubble
        if not _is_window_usable(bubble):
            return
        existing = self._footer
        if isinstance(existing, wx.Window) and _is_window_usable(existing):
            try:
                self._bubble_sizer.Detach(existing)
            except RuntimeError:
                pass
            existing.Destroy()
        elif isinstance(existing, wx.Sizer):
            try:
                self._bubble_sizer.Detach(existing)
            except RuntimeError:
                pass
            existing.Clear(delete_windows=True)
        self._footer = None
        if footer_factory is None:
            return
        footer = footer_factory(bubble)
        footer_targets: list[wx.Window] = []
        if isinstance(footer, wx.Sizer):
            self._bubble_sizer.Add(
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
            self._bubble_sizer.Add(
                footer,
                0,
                wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                self._content_padding,
            )
            footer_targets.append(footer)
        self._footer = footer
        for target in footer_targets:
            self._attach_context_menu_handlers(target)

    # ------------------------------------------------------------------
    def set_explicit_width_hint(self, width_hint: int | None) -> None:
        """Apply explicit width hint without recreating the bubble."""

        if width_hint is not None:
            try:
                hint = int(width_hint)
            except (TypeError, ValueError):
                hint = None
            else:
                if hint <= 0:
                    hint = None
        else:
            hint = None
        if hint == self._explicit_width_hint:
            return
        self._explicit_width_hint = hint
        bubble = self._bubble
        if not _is_window_usable(bubble):
            return
        try:
            if hint is None:
                bubble.SetMinSize(wx.DefaultSize)
                bubble.SetMaxSize(wx.DefaultSize)
            else:
                size = wx.Size(hint, -1)
                bubble.SetMinSize(size)
                bubble.SetMaxSize(size)
        except RuntimeError:
            return
        self._cached_width_constraints = None
        self._schedule_width_update()

    def _build_default_palette(
        self, *, align: str, parent_background: wx.Colour
    ) -> MessageBubblePalette:
        user_highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
        user_text = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHTTEXT)
        agent_bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        agent_text = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)

        background = parent_background
        if not background.IsOk():
            background = agent_bg

        if align == "right":
            bubble_bg = _soften_user_highlight(
                user_highlight,
                background=background,
            )
            bubble_fg = _pick_best_contrast(bubble_bg, user_text, agent_text)
            meta_colour = _blend_colour(bubble_fg, bubble_bg, 0.35)
        else:
            bubble_bg = _agent_tint(agent_bg)
            bubble_fg = agent_text
            meta_colour = _blend_colour(agent_text, bubble_bg, 0.45)
        return MessageBubblePalette(bubble_bg, bubble_fg, meta_colour)

    def Destroy(self) -> bool:  # type: ignore[override]
        self._destroyed = True
        return super().Destroy()

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            self._destroyed = True
        event.Skip()

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
        self._cached_width_constraints = None

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

    def _on_panel_resize(self, event: wx.SizeEvent) -> None:
        event.Skip()
        self._schedule_width_update()

    def _schedule_width_update(self) -> None:
        if self._destroyed or self._pending_width_update:
            return

        self._pending_width_update = True

        def run() -> None:
            # ``CallAfter`` executes once the main loop becomes idle; the
            # MessageBubble can already be destroyed by then.
            self._pending_width_update = False
            if self._destroyed:
                return
            with suppress(RuntimeError):
                # ``wx`` raises ``RuntimeError`` when invoking methods on a
                # window whose native counterpart has already been torn down.
                # The flag above prevents re-entry, so we can silently ignore
                # the callback.
                self._update_width_constraints()

        wx.CallAfter(run)

    def _update_width_constraints(self) -> None:
        if self._destroyed:
            return

        try:
            parent = self.GetParent()
        except RuntimeError:
            return
        if not _is_window_usable(parent):
            return

        try:
            parent_width = parent.GetClientSize().width
        except RuntimeError:
            return

        border = self._resolve_parent_border(parent)
        inner_parent_width = parent_width
        if border > 0 and parent_width > 0:
            inner_parent_width = max(parent_width - 2 * border, 0)

        viewport_width = self._resolve_viewport_width(parent)
        inner_viewport_width = 0
        if viewport_width > 0:
            inner_viewport_width = viewport_width
            if border > 0:
                inner_viewport_width = max(inner_viewport_width - 2 * border, 0)

        available_width = inner_viewport_width or inner_parent_width
        if available_width <= 0:
            available_width = max(parent_width, inner_parent_width, inner_viewport_width)
        if available_width <= 0:
            return

        hard_cap_candidates = [available_width]
        if inner_parent_width > 0:
            hard_cap_candidates.append(inner_parent_width)
        if parent_width > 0:
            hard_cap_candidates.append(parent_width)
        hard_cap = min(hard_cap_candidates) if hard_cap_candidates else 0
        if hard_cap <= 0:
            hard_cap = available_width

        max_width = int(available_width * self._bubble_max_width_ratio)
        max_width = min(max_width, available_width)
        if hard_cap > 0:
            max_width = min(max_width, hard_cap)
            margin_cap = hard_cap - self._bubble_margin
            if margin_cap > 0:
                max_width = min(max_width, margin_cap)

        min_width_cap = self._min_bubble_width
        if hard_cap > 0:
            min_width_cap = min(min_width_cap, hard_cap)
        min_width_cap = max(min_width_cap, 0)

        if max_width < min_width_cap:
            max_width = min_width_cap
        if max_width <= 0:
            return

        hint_floor = self._initial_width_hint
        if hint_floor is not None and hint_floor > 0:
            capped_hint = hint_floor
            if hard_cap > 0:
                capped_hint = min(capped_hint, hard_cap)
            if max_width < capped_hint:
                max_width = capped_hint
            target_floor = capped_hint
        else:
            target_floor = 0

        content_width = self._estimate_content_width()
        padded_content = content_width + 2 * self._content_padding
        char_count = len(self._text_value)
        growth_threshold = 360
        ratio = math.sqrt(char_count / growth_threshold) if growth_threshold else 1.0
        ratio = max(0.0, min(ratio, 1.0))
        target_from_chars = min_width_cap + int((max_width - min_width_cap) * ratio)
        target_width = max(min_width_cap, padded_content, target_from_chars)
        target_width = min(target_width, max_width)
        if target_floor:
            target_width = max(target_width, target_floor)

        cached = self._cached_width_constraints
        if cached is not None and cached == (target_width, max_width):
            return

        bubble = getattr(self, "_bubble", None)
        if not _is_window_usable(bubble):
            return

        self._cached_width_constraints = (target_width, max_width)

        try:
            bubble.SetMinSize(wx.Size(target_width, -1))
            bubble.SetMaxSize(wx.Size(max_width, -1))
            bubble.SetInitialSize(wx.Size(target_width, -1))
        except RuntimeError:
            self._cached_width_constraints = None
            return

        try:
            bubble_sizer = bubble.GetSizer()
        except RuntimeError:
            return
        if bubble_sizer is not None:
            bubble_sizer.Layout()

        try:
            container_sizer = self.GetSizer()
        except RuntimeError:
            container_sizer = None
        if container_sizer is not None:
            with suppress(RuntimeError):
                container_sizer.Layout()
        with suppress(RuntimeError):
            self.Layout()

        self._initial_width_hint = target_width

        if self._on_width_change is not None and target_width > 0:
            with suppress(Exception):
                self._on_width_change(target_width)

    def _resolve_parent_border(self, parent: wx.Window) -> int:
        try:
            sizer = parent.GetSizer()
        except RuntimeError:
            return 0
        if sizer is None:
            return 0
        try:
            item = sizer.GetItem(self)
        except Exception:
            item = None
        if item is None:
            return 0
        try:
            border = int(item.GetBorder())
        except Exception:
            return 0
        return max(border, 0)

    def _resolve_viewport_width(self, parent: wx.Window) -> int:
        ancestor = parent
        while _is_window_usable(ancestor):
            if isinstance(ancestor, wx.ScrolledWindow):
                try:
                    width = ancestor.GetClientSize().width
                except RuntimeError:
                    return 0
                if width > 0:
                    return width
            try:
                ancestor = ancestor.GetParent()
            except RuntimeError:
                return 0
            if not _is_window_usable(ancestor):
                return 0
        return 0

    def _estimate_content_width(self) -> int:
        if not self._text_value:
            return 0

        font: wx.Font | None = None
        if isinstance(self._text, wx.Window):
            candidate = self._text.GetFont()
            if candidate.IsOk():
                font = candidate
        if font is None or not font.IsOk():
            font = self.GetFont()
        if font is None or not font.IsOk():
            font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)

        text = self._text_value
        lines = text.splitlines() or [text]

        bitmap = wx.Bitmap(1, 1)
        dc = wx.MemoryDC()
        dc.SelectObject(bitmap)
        dc.SetFont(font)

        max_width = 0
        for line in lines:
            width, _ = dc.GetTextExtent(line or " ")
            if width > max_width:
                max_width = width
        dc.SelectObject(wx.NullBitmap)
        return max_width


@dataclass(slots=True)
class _TranscriptPanelState:
    prompt: str
    prompt_timestamp: str
    response: str
    response_timestamp: str
    regenerate_enabled: bool
    regenerate_available: bool
    tool_summaries: tuple[ToolCallSummary, ...]
    context_signature: str
    reasoning_signature: str
    regenerated: bool
    layout_hints: tuple[tuple[str, int], ...]


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
        tool_summaries: Sequence[ToolCallSummary] | None = None,
        context_messages: Sequence[Mapping[str, Any]] | None = None,
        reasoning_segments: Sequence[Mapping[str, Any]] | None = None,
        regenerated: bool = False,
        layout_hints: Mapping[str, int] | None = None,
        on_layout_hint: Callable[[str, int], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(parent.GetBackgroundColour())
        self.SetDoubleBuffered(True)

        self._padding = self.FromDIP(4)
        self._on_layout_hint = on_layout_hint
        self._regenerate_handler = on_regenerate
        self._regenerate_button: wx.Button | None = None
        self._user_bubble: MessageBubble | None = None
        self._agent_bubble: MessageBubble | None = None
        self._tool_bubbles: list[tuple[ToolCallSummary, MessageBubble]] = []
        self._tool_section = wx.BoxSizer(wx.VERTICAL)
        self._reasoning_pane: wx.CollapsiblePane | None = None
        self._context_signature = ""
        self._reasoning_signature = ""
        self._layout_hints = self._sanitize_layout_hints(layout_hints)
        self._state = _TranscriptPanelState(
            prompt="",
            prompt_timestamp="",
            response="",
            response_timestamp="",
            regenerate_enabled=regenerate_enabled,
            regenerate_available=on_regenerate is not None,
            tool_summaries=(),
            context_signature="",
            reasoning_signature="",
            regenerated=False,
            layout_hints=tuple(sorted(self._layout_hints.items())),
        )

        outer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(outer)

        self._regenerated_notice: wx.StaticText | None = None
        if regenerated:
            self._regenerated_notice = self._create_regenerated_notice(outer)

        user_bubble = MessageBubble(
            self,
            role_label=_("You"),
            timestamp=prompt_timestamp,
            text=prompt,
            align="right",
            footer_factory=self._context_footer_factory(context_messages),
            width_hint=self._resolve_hint("user"),
            on_width_change=lambda width: self._emit_layout_hint("user", width),
        )
        outer.Add(user_bubble, 0, wx.EXPAND | wx.ALL, self._padding)
        self._user_bubble = user_bubble
        self._context_signature = self._context_messages_signature(context_messages)

        agent_bubble = MessageBubble(
            self,
            role_label=_("Agent"),
            timestamp=response_timestamp,
            text=response,
            align="left",
            allow_selection=True,
            render_markdown=True,
            footer_factory=self._regenerate_footer_factory(
                on_regenerate, regenerate_enabled
            ),
            width_hint=self._resolve_hint("agent"),
            on_width_change=lambda width: self._emit_layout_hint("agent", width),
        )
        outer.Add(agent_bubble, 0, wx.EXPAND | wx.ALL, self._padding)
        self._agent_bubble = agent_bubble

        self._selection_probe = wx.TextCtrl(
            self,
            value=response,
            style=(
                wx.TE_MULTILINE
                | wx.TE_READONLY
                | wx.TE_WORDWRAP
                | wx.TE_NO_VSCROLL
                | wx.BORDER_NONE
            ),
        )
        self._selection_probe.Hide()

        outer.Add(self._tool_section, 0, wx.EXPAND)
        self._build_tool_bubbles(tool_summaries)

        self._update_reasoning(reasoning_segments)

        self._state = _TranscriptPanelState(
            prompt=prompt,
            prompt_timestamp=prompt_timestamp,
            response=response,
            response_timestamp=response_timestamp,
            regenerate_enabled=regenerate_enabled,
            regenerate_available=on_regenerate is not None,
            tool_summaries=tuple(tool_summaries or ()),
            context_signature=self._context_signature,
            reasoning_signature=self._reasoning_signature,
            regenerated=regenerated,
            layout_hints=tuple(sorted(self._layout_hints.items())),
        )

    @staticmethod
    def tool_layout_hint_key(summary: ToolCallSummary) -> str:
        return f"tool:{summary.tool_name.strip().lower()}:{summary.index}"

    def update_from_entry(
        self,
        *,
        prompt: str,
        response: str,
        prompt_timestamp: str = "",
        response_timestamp: str = "",
        on_regenerate: Callable[[], None] | None = None,
        regenerate_enabled: bool = True,
        tool_summaries: Sequence[ToolCallSummary] | None = None,
        context_messages: Sequence[Mapping[str, Any]] | None = None,
        reasoning_segments: Sequence[Mapping[str, Any]] | None = None,
        regenerated: bool = False,
        layout_hints: Mapping[str, int] | None = None,
    ) -> None:
        self._layout_hints = self._sanitize_layout_hints(layout_hints)
        layout_hint_state = tuple(sorted(self._layout_hints.items()))

        if self._regenerated_notice is None and regenerated:
            self._regenerated_notice = self._create_regenerated_notice(self.GetSizer())
        elif self._regenerated_notice is not None and not regenerated:
            notice = self._regenerated_notice
            if _is_window_usable(notice):
                try:
                    self.GetSizer().Detach(notice)
                except Exception:
                    pass
                notice.Destroy()
            self._regenerated_notice = None

        user_bubble = self._user_bubble
        if user_bubble is not None:
            if prompt != self._state.prompt:
                user_bubble.update_text(prompt)
            if prompt_timestamp != self._state.prompt_timestamp:
                user_bubble.update_header(_("You"), prompt_timestamp)
            user_bubble.set_explicit_width_hint(self._resolve_hint("user"))
            context_signature = self._context_messages_signature(context_messages)
            if context_signature != self._context_signature:
                user_bubble.set_footer(
                    self._context_footer_factory(context_messages)
                )
                self._context_signature = context_signature

        self._update_tool_bubbles(tool_summaries)

        agent_bubble = self._agent_bubble
        if agent_bubble is not None:
            if response != self._state.response:
                agent_bubble.update_text(response)
            if response_timestamp != self._state.response_timestamp:
                agent_bubble.update_header(_("Agent"), response_timestamp)
            agent_bubble.set_explicit_width_hint(self._resolve_hint("agent"))
            self._update_regenerate_footer(on_regenerate, regenerate_enabled)
        probe = getattr(self, "_selection_probe", None)
        if isinstance(probe, wx.TextCtrl):
            probe.SetValue(normalize_for_display(response))

        self._update_reasoning(reasoning_segments)

        self._state = _TranscriptPanelState(
            prompt=prompt,
            prompt_timestamp=prompt_timestamp,
            response=response,
            response_timestamp=response_timestamp,
            regenerate_enabled=regenerate_enabled,
            regenerate_available=on_regenerate is not None,
            tool_summaries=tuple(tool_summaries or ()),
            context_signature=self._context_signature,
            reasoning_signature=self._reasoning_signature,
            regenerated=regenerated,
            layout_hints=layout_hint_state,
        )

    def _sanitize_layout_hints(
        self, layout_hints: Mapping[str, int] | None
    ) -> dict[str, int]:
        sanitized: dict[str, int] = {}
        if not layout_hints:
            return sanitized
        for key, value in layout_hints.items():
            try:
                width = int(value)
            except (TypeError, ValueError):
                continue
            if width <= 0:
                continue
            sanitized[str(key)] = width
        return sanitized

    def _emit_layout_hint(self, key: str, width: int) -> None:
        if self._on_layout_hint is None or width <= 0:
            return
        try:
            self._on_layout_hint(key, int(width))
        except Exception:
            return

    def _resolve_hint(self, key: str) -> int | None:
        return self._layout_hints.get(key)

    def _context_footer_factory(
        self, context_messages: Sequence[Mapping[str, Any]] | None
    ) -> FooterFactory | None:
        if not context_messages:
            return None

        def factory(container: wx.Window) -> wx.Window | None:
            return self._create_context_panel(container, context_messages)

        return factory

    def _context_messages_signature(
        self, context_messages: Sequence[Mapping[str, Any]] | None
    ) -> str:
        return self._format_context_messages(context_messages).strip()

    def _build_tool_bubbles(
        self, tool_summaries: Sequence[ToolCallSummary] | None
    ) -> None:
        self._clear_tool_bubbles()
        summaries = list(tool_summaries or [])
        if not summaries:
            return
        parent_background = self.GetBackgroundColour()
        for summary in summaries:
            markdown = render_tool_summary_markdown(summary).strip()
            if not markdown:
                continue
            hint_key = self.tool_layout_hint_key(summary)
            timestamp = (
                summary.completed_at
                or summary.last_observed_at
                or summary.started_at
                or ""
            )
            bubble = MessageBubble(
                self,
                role_label=summary.tool_name,
                timestamp=timestamp,
                text=markdown,
                align="left",
                allow_selection=True,
                render_markdown=True,
                palette=_tool_bubble_palette(parent_background, summary.tool_name),
                width_hint=self._resolve_hint(hint_key),
                on_width_change=lambda width, key=hint_key: self._emit_layout_hint(
                    key, width
                ),
            )
            self._tool_section.Add(
                bubble,
                0,
                wx.EXPAND | wx.ALL,
                self._padding,
            )
            self._tool_bubbles.append((summary, bubble))

    def _clear_tool_bubbles(self) -> None:
        if not self._tool_bubbles:
            return
        for _, bubble in self._tool_bubbles:
            if not _is_window_usable(bubble):
                continue
            try:
                self._tool_section.Detach(bubble)
            except Exception:
                pass
            bubble.Destroy()
        self._tool_bubbles.clear()

    def _update_tool_bubbles(
        self, tool_summaries: Sequence[ToolCallSummary] | None
    ) -> None:
        current = tuple(summary for summary, _ in self._tool_bubbles)
        desired = tuple(tool_summaries or ())
        if current == desired:
            for summary, bubble in self._tool_bubbles:
                bubble.set_explicit_width_hint(
                    self._resolve_hint(self.tool_layout_hint_key(summary))
                )
            return
        self._build_tool_bubbles(tool_summaries)

    def _create_regenerate_footer(
        self,
        container: wx.Window,
        *,
        on_regenerate: Callable[[], None],
        enabled: bool,
    ) -> wx.Sizer:
        button = wx.Button(container, label=_("Regenerate"), style=wx.BU_EXACTFIT)
        button.SetBackgroundColour(container.GetBackgroundColour())
        button.SetForegroundColour(container.GetForegroundColour())
        button.SetToolTip(_("Restart response generation"))
        button.Bind(wx.EVT_BUTTON, self._on_regenerate_clicked)
        button.Enable(enabled)
        self._regenerate_button = button
        self._regenerate_handler = on_regenerate
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.AddStretchSpacer()
        sizer.Add(button, 0, wx.ALIGN_CENTER_VERTICAL)
        return sizer

    def _on_regenerate_clicked(self, _event: wx.CommandEvent) -> None:
        handler = self._regenerate_handler
        if handler is None:
            return
        try:
            handler()
        except Exception:  # pragma: no cover - defensive
            pass

    def _create_context_panel(
        self,
        container: wx.Window,
        context_messages: Sequence[Mapping[str, Any]] | None,
    ) -> wx.CollapsiblePane | None:
        if not context_messages:
            return None

        context_text = self._format_context_messages(context_messages).strip()
        if not context_text:
            return None

        pane = wx.CollapsiblePane(
            container,
            label=_("Context"),
            style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE,
        )
        pane.Collapse(True)

        pane_background = container.GetBackgroundColour()
        if not pane_background.IsOk():
            pane_background = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        pane.SetBackgroundColour(pane_background)
        pane_foreground = container.GetForegroundColour()
        if pane_foreground.IsOk():
            pane.SetForegroundColour(pane_foreground)
            try:
                toggle = pane.GetButton()
            except AttributeError:
                toggle = None
            if toggle is not None and _is_window_usable(toggle):
                toggle.SetForegroundColour(pane_foreground)
                toggle.SetBackgroundColour(pane_background)
        inner = pane.GetPane()
        inner.SetBackgroundColour(pane_background)
        if pane_foreground.IsOk():
            inner.SetForegroundColour(pane_foreground)

        content_sizer = wx.BoxSizer(wx.VERTICAL)
        text_ctrl = wx.TextCtrl(
            inner,
            value=normalize_for_display(context_text),
            style=(
                wx.TE_MULTILINE
                | wx.TE_READONLY
                | wx.TE_BESTWRAP
                | wx.BORDER_NONE
            ),
        )
        text_ctrl.SetBackgroundColour(pane_background)
        text_ctrl.SetForegroundColour(
            _pick_best_contrast(
                pane_background,
                wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT),
                wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNTEXT),
            )
        )
        text_ctrl.SetMinSize((-1, self.FromDIP(120)))
        content_sizer.Add(text_ctrl, 1, wx.EXPAND | wx.TOP, self.FromDIP(4))
        inner.SetSizer(content_sizer)
        return pane

    @staticmethod
    def _format_context_messages(
        context_messages: Sequence[Mapping[str, Any]] | None,
    ) -> str:
        if not context_messages:
            return ""

        blocks: list[str] = []
        for message in context_messages:
            if not isinstance(message, Mapping):
                continue
            role_raw = message.get("role")
            role = str(role_raw).strip() if isinstance(role_raw, str) else ""
            content_value = message.get("content")
            fragments: list[str] = []
            if isinstance(content_value, str):
                fragments.append(content_value)
            elif isinstance(content_value, Sequence):
                for fragment in content_value:
                    if isinstance(fragment, Mapping):
                        fragment_text = fragment.get("text")
                        if isinstance(fragment_text, str):
                            fragments.append(fragment_text)
                        continue
                    if isinstance(fragment, str):
                        fragments.append(fragment)
                    else:
                        fragments.append(str(fragment))
            elif content_value is not None:
                fragments.append(str(content_value))

            text = "\n".join(part for part in fragments if part)
            if not text and not role:
                continue

            parts: list[str] = []
            if role:
                parts.append(f"{role}:")
            if text:
                parts.append(text)
            blocks.append("\n".join(parts).strip())

        return "\n\n".join(block for block in blocks if block)

    def _regenerate_footer_factory(
        self,
        on_regenerate: Callable[[], None] | None,
        enabled: bool,
    ) -> FooterFactory | None:
        if on_regenerate is None:
            self._regenerate_button = None
            self._regenerate_handler = None
            return None
        self._regenerate_handler = on_regenerate

        def factory(container: wx.Window) -> wx.Sizer:
            return self._create_regenerate_footer(
                container,
                on_regenerate=on_regenerate,
                enabled=enabled,
            )

        return factory

    def _update_regenerate_footer(
        self,
        on_regenerate: Callable[[], None] | None,
        enabled: bool,
    ) -> None:
        if on_regenerate is None:
            if self._regenerate_button is not None:
                self._agent_bubble.set_footer(None)
                self._regenerate_button = None
            self._regenerate_handler = None
            return
        if self._regenerate_button is None or not _is_window_usable(
            self._regenerate_button
        ):
            self._agent_bubble.set_footer(
                self._regenerate_footer_factory(on_regenerate, enabled)
            )
        else:
            self._regenerate_handler = on_regenerate
            self._regenerate_button.Enable(enabled)

    def _create_regenerated_notice(self, outer: wx.Sizer) -> wx.StaticText:
        notice = wx.StaticText(
            self,
            label=_("Previous attempt (kept after regeneration)"),
        )
        notice_font = notice.GetFont()
        if notice_font.IsOk():
            notice_font.MakeItalic()
            notice.SetFont(notice_font)
        notice.SetForegroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT)
        )
        outer.Insert(0, notice, 0, wx.LEFT | wx.RIGHT | wx.TOP, self._padding)
        return notice

    def _create_reasoning_panel(
        self, reasoning_segments: Sequence[Mapping[str, Any]] | None
    ) -> wx.CollapsiblePane | None:
        if not reasoning_segments:
            return None

        reasoning_text = self._format_reasoning_segments(reasoning_segments).strip()
        if not reasoning_text:
            return None

        pane = wx.CollapsiblePane(
            self,
            label=_("Model reasoning"),
            style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE,
        )
        pane.Collapse(True)

        pane_background = self.GetBackgroundColour()
        if not pane_background.IsOk():
            pane_background = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        pane.SetBackgroundColour(pane_background)
        inner = pane.GetPane()
        inner.SetBackgroundColour(pane_background)

        content_sizer = wx.BoxSizer(wx.VERTICAL)
        text_ctrl = wx.TextCtrl(
            inner,
            value=normalize_for_display(reasoning_text),
            style=(
                wx.TE_MULTILINE
                | wx.TE_READONLY
                | wx.TE_BESTWRAP
                | wx.BORDER_NONE
            ),
        )
        text_ctrl.SetBackgroundColour(pane_background)
        text_ctrl.SetForegroundColour(
            _pick_best_contrast(
                pane_background,
                wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT),
                wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNTEXT),
            )
        )
        text_ctrl.SetMinSize((-1, self.FromDIP(100)))
        content_sizer.Add(text_ctrl, 1, wx.EXPAND | wx.TOP, self.FromDIP(4))
        inner.SetSizer(content_sizer)
        setattr(pane, "_transcript_reasoning_text_ctrl", text_ctrl)
        return pane

    def _update_reasoning(
        self, reasoning_segments: Sequence[Mapping[str, Any]] | None
    ) -> None:
        container = self.GetSizer()
        signature = self._format_reasoning_segments(reasoning_segments).strip()
        if signature == self._reasoning_signature:
            if self._reasoning_pane is not None and _is_window_usable(
                self._reasoning_pane
            ):
                text_ctrl = getattr(
                    self._reasoning_pane,
                    "_transcript_reasoning_text_ctrl",
                    None,
                )
                if isinstance(text_ctrl, wx.TextCtrl):
                    text_ctrl.ChangeValue(normalize_for_display(signature))
            return
        if self._reasoning_pane is not None and _is_window_usable(
            self._reasoning_pane
        ):
            try:
                if isinstance(container, wx.Sizer):
                    container.Detach(self._reasoning_pane)
            except Exception:
                pass
            self._reasoning_pane.Destroy()
            self._reasoning_pane = None
        if not signature:
            self._reasoning_signature = ""
            if isinstance(container, wx.Sizer):
                container.Layout()
            return
        pane = self._create_reasoning_panel(reasoning_segments)
        if pane is not None and isinstance(container, wx.Sizer):
            container.Add(
                pane,
                0,
                wx.EXPAND | wx.ALL,
                self._padding,
            )
            self._reasoning_pane = pane
            self._reasoning_signature = signature
            container.Layout()


    @staticmethod
    def _format_reasoning_segments(
        reasoning_segments: Sequence[Mapping[str, Any]] | None,
    ) -> str:
        if not reasoning_segments:
            return ""

        blocks: list[str] = []
        for index, segment in enumerate(reasoning_segments, start=1):
            if isinstance(segment, Mapping):
                type_value = segment.get("type")
                text_value = segment.get("text")
            else:
                type_value = getattr(segment, "type", None)
                text_value = getattr(segment, "text", None)
            if text_value is None:
                continue
            text = str(text_value).strip()
            if not text:
                continue
            type_label = str(type_value).strip() if type_value is not None else ""
            heading = type_label or _("Thought {index}").format(index=index)
            blocks.append(f"{heading}\n{text}")
        return "\n\n".join(blocks)
