"""Widgets used to render chat transcript entries."""
from __future__ import annotations

import hashlib
import math
from contextlib import suppress
from dataclasses import dataclass
from collections.abc import Callable

import wx

from ...i18n import _
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
    wx.Colour(235, 244, 215),
    wx.Colour(229, 241, 255),
    wx.Colour(224, 239, 246),
)


def tool_bubble_palette(
    parent_background: wx.Colour, tool_name: str
) -> MessageBubblePalette:
    """Compose colours for tool responses based on *parent_background*."""
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
        """Construct a chat bubble widget and prime rendering metadata."""
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
        self._max_visible_text_lines = 28
        self._text_vertical_padding = self.FromDIP(6)
        self._copy_menu_id = wx.Window.NewControlId()
        self.Bind(wx.EVT_MENU, self._on_copy, id=self._copy_menu_id)
        self._allow_selection = allow_selection
        self._copy_selection_menu_id: int | None = None
        self._selection_checker: Callable[[], bool] | None = None
        self._selection_getter: Callable[[], str] | None = None
        if allow_selection:
            self._copy_selection_menu_id = wx.Window.NewControlId()
            self.Bind(
                wx.EVT_MENU,
                self._on_copy_selection,
                id=self._copy_selection_menu_id,
            )

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

        self._text_base_style: int | None = None

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
                base_style = (
                    wx.TE_MULTILINE
                    | wx.TE_READONLY
                    | wx.TE_WORDWRAP
                    | wx.BORDER_NONE
                )
                style = base_style
                text_ctrl = wx.TextCtrl(bubble, value=display_text, style=style)
                text_ctrl.SetBackgroundColour(bubble_bg)
                text_ctrl.SetForegroundColour(bubble_fg)
                text_ctrl.SetMinSize(wx.Size(self.FromDIP(160), -1))
                if message_font is not None and message_font.IsOk():
                    text_ctrl.SetFont(message_font)
                self._text = text_ctrl
                self._text_base_style = base_style

                def has_selection(tc: wx.TextCtrl = text_ctrl) -> bool:
                    start, end = tc.GetSelection()
                    return end > start

                self._selection_checker = has_selection
                self._selection_getter = text_ctrl.GetStringSelection
                self._refresh_textctrl_height()
        else:
            text_align_flag = wx.ALIGN_LEFT
            self._text = wx.StaticText(
                bubble,
                label=display_text,
                style=text_align_flag,
            )
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
            self._refresh_textctrl_height()
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
            with suppress(RuntimeError):
                self._bubble_sizer.Detach(existing)
            existing.Destroy()
        elif isinstance(existing, wx.Sizer):
            with suppress(RuntimeError):
                self._bubble_sizer.Detach(existing)
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
        """Mark the bubble as destroyed before letting wx tear down state."""
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
            self._refresh_textctrl_height(width=width)
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
            available_width = max(
                parent_width,
                inner_parent_width,
                inner_viewport_width,
            )
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

    def _refresh_textctrl_height(self, width: int | None = None) -> None:
        text_ctrl = getattr(self, "_text", None)
        if not isinstance(text_ctrl, wx.TextCtrl):
            return
        if not _is_window_usable(text_ctrl):
            return

        try:
            current_min = text_ctrl.GetMinSize()
        except RuntimeError:
            current_min = wx.Size(0, 0)

        width_hint = width if width is not None and width > 0 else current_min.width
        if width_hint <= 0:
            width_hint = self.FromDIP(160)

        try:
            text_ctrl.SetMinSize(wx.Size(width_hint, current_min.height))
            text_ctrl.SetInitialSize(wx.Size(width_hint, current_min.height))
        except RuntimeError:
            return

        try:
            char_height = text_ctrl.GetCharHeight()
        except RuntimeError:
            char_height = 0
        if char_height <= 0:
            try:
                _, char_height = text_ctrl.GetTextExtent("Ag")
            except RuntimeError:
                char_height = 0
        if char_height <= 0:
            char_height = max(self.FromDIP(14), 1)

        try:
            line_count = text_ctrl.GetNumberOfLines()
        except RuntimeError:
            line_count = 1
        line_count = max(line_count, 1)

        max_lines = max(int(self._max_visible_text_lines), 1)
        padding = max(int(self._text_vertical_padding), 0)
        full_height = line_count * char_height + padding
        capped_height = max_lines * char_height + padding
        target_height = full_height if line_count <= max_lines else capped_height

        self._apply_textctrl_scrollbar_policy(
            text_ctrl,
            needs_scrollbar=line_count > max_lines,
        )

        try:
            text_ctrl.SetMinSize(wx.Size(width_hint, target_height))
            text_ctrl.SetInitialSize(wx.Size(width_hint, target_height))
            text_ctrl.SetMaxSize(wx.Size(-1, capped_height))
        except RuntimeError:
            return

        with suppress(RuntimeError):
            text_ctrl.Layout()
        parent = text_ctrl.GetParent()
        if parent is not None and _is_window_usable(parent):
            with suppress(RuntimeError):
                parent.Layout()

    def _apply_textctrl_scrollbar_policy(
        self, text_ctrl: wx.TextCtrl, *, needs_scrollbar: bool
    ) -> None:
        base_style = self._text_base_style
        if base_style is None:
            try:
                base_style = text_ctrl.GetWindowStyleFlag()
            except RuntimeError:
                return
            else:
                self._text_base_style = base_style
        try:
            current_style = text_ctrl.GetWindowStyleFlag()
        except RuntimeError:
            return

        desired_style = base_style | (wx.VSCROLL if needs_scrollbar else 0)
        if current_style == desired_style:
            return
        try:
            text_ctrl.SetWindowStyleFlag(desired_style)
        except RuntimeError:
            return
        with suppress(RuntimeError):
            text_ctrl.Refresh()
        with suppress(RuntimeError):
            text_ctrl.Update()

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

__all__ = ['MessageBubble', 'tool_bubble_palette']
