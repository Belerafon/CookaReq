"""Utilities to render markdown content inside chat bubbles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import markdown
import wx
import wx.html as html

from ..text import normalize_for_display


try:  # pragma: no cover - platform specific
    WX_ASSERTION_ERROR = wx.PyAssertionError
except AttributeError:  # pragma: no cover - fallback for older builds
    WX_ASSERTION_ERROR = getattr(wx, "wxAssertionError", RuntimeError)


def _colour_to_hex(colour: wx.Colour) -> str:
    return f"#{colour.Red():02x}{colour.Green():02x}{colour.Blue():02x}"


def _mix_colour(base: wx.Colour, other: wx.Colour, weight: float) -> wx.Colour:
    weight = max(0.0, min(weight, 1.0))
    return wx.Colour(
        int(base.Red() * (1.0 - weight) + other.Red() * weight),
        int(base.Green() * (1.0 - weight) + other.Green() * weight),
        int(base.Blue() * (1.0 - weight) + other.Blue() * weight),
    )


def _font_face(font: wx.Font) -> str:
    if not font.IsOk():
        return "sans-serif"
    face = font.GetFaceName()
    return face or "sans-serif"


def _font_size(font: wx.Font) -> int:
    if not font.IsOk():
        return 11
    return max(font.GetPointSize(), 8)


def _build_markdown_renderer() -> markdown.Markdown:
    renderer = markdown.Markdown(
        extensions=[
            "markdown.extensions.extra",
            "markdown.extensions.sane_lists",
        ],
        output_format="html5",
    )
    # Hide raw HTML returned by the LLM to avoid embedding arbitrary tags.
    renderer.preprocessors.deregister("html_block")
    renderer.inlinePatterns.deregister("html")
    renderer.reset()
    return renderer


_MARKDOWN = _build_markdown_renderer()


def _render_markdown(markdown_text: str) -> str:
    renderer = _MARKDOWN
    renderer.reset()
    return renderer.convert(markdown_text or "")


def _estimate_contrast(background: wx.Colour) -> str:
    if not background.IsOk():
        return "light"
    r, g, b = background.Red(), background.Green(), background.Blue()
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "dark" if luminance < 128 else "light"


@dataclass(slots=True)
class MarkdownTheme:
    """Container describing palette used to render markdown content."""

    foreground: wx.Colour
    background: wx.Colour

    def table_border(self) -> wx.Colour:
        return _mix_colour(self.foreground, self.background, 0.7)

    def subtle_background(self) -> wx.Colour:
        return _mix_colour(self.background, self.foreground, 0.08)


class MarkdownView(html.HtmlWindow):
    """Simple view displaying markdown converted to HTML."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        foreground_colour: wx.Colour,
        background_colour: wx.Colour,
    ) -> None:
        super().__init__(
            parent,
            style=html.HW_SCROLLBAR_AUTO,
        )
        self._theme = MarkdownTheme(foreground_colour, background_colour)
        self._markdown: str = ""
        self._pending_markup: str | None = None
        self._pending_render: bool = False
        self._destroyed = False
        self._render_listeners: list[Callable[[], None]] = []
        self.SetBackgroundColour(background_colour)
        self.SetForegroundColour(foreground_colour)
        self.SetBorders(0)
        # Allow the control to manage its own scrollbars; manual size callbacks
        # are not needed when horizontal overflow is enabled.
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

    def SetMarkdown(self, markdown_text: str) -> None:
        """Update control contents with *markdown_text*."""
        self._markdown = markdown_text
        markup = self._wrap_html(_render_markdown(markdown_text))
        self._pending_markup = normalize_for_display(markup)
        if self._try_render_pending_markup():
            return
        self._request_pending_render()

    def DoSetFont(self, font: wx.Font | None) -> bool:  # noqa: N802 - wx naming convention
        changed = super().DoSetFont(font)
        if changed:
            self.SetMarkdown(self._markdown)
        return changed

    def HasSelection(self) -> bool:  # noqa: N802 - wx naming convention
        return bool(self.SelectionToText())

    def GetSelectionText(self) -> str:
        return self.SelectionToText()

    def GetPlainText(self) -> str:
        return self.ToText()

    def _on_size(self, event: wx.SizeEvent) -> None:
        event.Skip()
        wx.CallAfter(self._refresh_best_size)

    def _refresh_best_size(self) -> None:
        try:
            internal = self.GetInternalRepresentation()
        except RuntimeError:
            return
        if internal is None:
            return
        height = internal.GetHeight()
        min_width = self.FromDIP(160)
        current = self.GetMinSize()
        if current.GetHeight() != height:
            self.SetMinSize(wx.Size(min_width, height))

    def _request_pending_render(self) -> None:
        if self._destroyed or self._pending_markup is None:
            return
        if self._pending_render:
            return

        self._pending_render = True

        def run() -> None:
            self._pending_render = False
            if self._destroyed:
                self._pending_markup = None
                return
            if not self._try_render_pending_markup():
                if self._pending_markup is not None:
                    self._request_pending_render()

        wx.CallAfter(run)

    def _try_render_pending_markup(self) -> bool:
        markup = self._pending_markup
        if markup is None or self._destroyed:
            return False
        if not self._is_window_ready():
            return False
        try:
            self.SetPage(markup)
        except (RuntimeError, WX_ASSERTION_ERROR, AttributeError):
            return False
        self._pending_markup = None
        self._refresh_best_size()
        self._notify_render_listeners()
        return True

    def add_render_listener(self, listener: Callable[[], None]) -> None:
        """Register *listener* to be notified after a render completes."""

        if callable(listener) and listener not in self._render_listeners:
            self._render_listeners.append(listener)

    def _notify_render_listeners(self) -> None:
        for listener in list(self._render_listeners):
            try:
                listener()
            except Exception:  # pragma: no cover - defensive
                continue

    def _is_window_ready(self) -> bool:
        try:
            if not self:
                return False
        except RuntimeError:
            return False

        handle_getter = getattr(self, "GetHandle", None)
        if callable(handle_getter):
            try:
                handle = handle_getter()
            except RuntimeError:
                return False
            if not handle:
                return False

        hwnd_getter = getattr(self, "GetHWND", None)
        if callable(hwnd_getter):
            try:
                hwnd = hwnd_getter()
            except RuntimeError:
                return False
            if not hwnd:
                return False

        return True

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            self._destroyed = True
            self._pending_markup = None
            self._pending_render = False
            self._render_listeners.clear()
        event.Skip()

    def _wrap_html(self, body_html: str) -> str:
        foreground_hex = _colour_to_hex(self._theme.foreground)
        background_hex = _colour_to_hex(self._theme.background)
        table_border_hex = _colour_to_hex(self._theme.table_border())
        subtle_hex = _colour_to_hex(self._theme.subtle_background())
        contrast = _estimate_contrast(self._theme.background)

        font = self.GetFont()
        mono_font = wx.SystemSettings.GetFont(wx.SYS_ANSI_FIXED_FONT)
        font_face = _font_face(font)
        font_size = _font_size(font)
        mono_face = _font_face(mono_font)

        body_attributes = (
            f" bgcolor=\"{background_hex}\""
            f" text=\"{foreground_hex}\""
            f" link=\"{foreground_hex}\""
            f" vlink=\"{foreground_hex}\""
            f" alink=\"{foreground_hex}\""
        )

        return (
            "<!DOCTYPE html>"
            "<html>"
            "<head>"
            "<meta charset='utf-8'>"
            "<style>"
            "body {"
            f" background-color: {background_hex};"
            f" color: {foreground_hex};"
            f" font-family: {font_face};"
            f" font-size: {font_size}pt;"
            " margin: 0;"
            " line-height: 1.4;"
            " word-break: break-word;"
            "}"
            "table {"
            " border-collapse: collapse;"
            " width: 100%;"
            " margin: 8px 0;"
            "}"
            "th, td {"
            f" border: 1px solid {table_border_hex};"
            " padding: 4px 6px;"
            " text-align: left;"
            " vertical-align: top;"
            "}"
            "thead tr {"
            f" background-color: {subtle_hex};"
            " font-weight: bold;"
            "}"
            "code {"
            f" font-family: {mono_face};"
            " font-size: 0.95em;"
            "}"
            "pre {"
            f" background-color: {subtle_hex};"
            " padding: 8px;"
            " border-radius: 4px;"
            " overflow-x: auto;"
            "}"
            "blockquote {"
            f" border-left: 3px solid {table_border_hex};"
            " margin: 4px 0;"
            " padding: 4px 8px;"
            f" background-color: {subtle_hex};"
            "}"
            "ul, ol {"
            " margin: 4px 0 4px 20px;"
            " padding: 0;"
            "}"
            "li + li {"
            " margin-top: 2px;"
            "}"
            "a {"
            f" color: {foreground_hex};"
            " text-decoration: underline;"
            "}"
            "hr {"
            f" border: 0; border-top: 1px solid {table_border_hex};"
            " margin: 8px 0;"
            "}"
            ":root {"
            f" color-scheme: {contrast};"
            "}"
            "</style>"
            "</head>"
            f"<body{body_attributes}>"
            f"{body_html}"
            "</body>"
            "</html>"
        )


class MarkdownContent(wx.Panel):
    """Container embedding :class:`MarkdownView` in bubble layouts."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        markdown: str,
        foreground_colour: wx.Colour,
        background_colour: wx.Colour,
    ) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(background_colour)
        scroller = wx.ScrolledWindow(
            self,
            style=wx.HSCROLL | wx.VSCROLL | wx.BORDER_NONE,
        )
        scroller.SetBackgroundColour(background_colour)
        scroller.SetForegroundColour(foreground_colour)
        dip_24 = max(int(self.FromDIP(24)), 1)
        scroller.SetScrollRate(dip_24, dip_24)
        scroller.SetMinSize(wx.Size(self.FromDIP(160), -1))
        self._scroller: wx.ScrolledWindow | None = scroller
        self._destroyed = False
        self._pending_layout_sync = False
        self._max_visible_height = max(int(self.FromDIP(640)), 0)

        self._view = MarkdownView(
            scroller,
            foreground_colour=foreground_colour,
            background_colour=background_colour,
        )
        self._view.SetMinSize(wx.Size(self.FromDIP(160), -1))
        self._view.add_render_listener(self._on_view_rendered)

        scroller_sizer = wx.BoxSizer(wx.VERTICAL)
        scroller_sizer.Add(self._view, 1, wx.EXPAND)
        scroller.SetSizer(scroller_sizer)

        scroller.Bind(wx.EVT_WINDOW_DESTROY, self._on_scroller_destroy)
        scroller.Bind(wx.EVT_SIZE, self._on_scroller_size)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_container_destroy)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(scroller, 1, wx.EXPAND)
        self.SetSizer(outer)

        self._view.SetMarkdown(markdown)

    def DoSetFont(self, font: wx.Font | None) -> bool:  # noqa: N802 - wx naming convention
        changed = super().DoSetFont(font)
        if changed:
            effective = font if font is not None else self.GetFont()
            if effective.IsOk():
                self._view.SetFont(effective)
            else:
                self._view.SetFont(wx.NullFont)
            self._on_view_rendered()
        return changed

    def HasSelection(self) -> bool:  # noqa: N802 - wx naming convention
        return self._view.HasSelection()

    def GetSelectionText(self) -> str:
        return self._view.GetSelectionText()

    def SetMarkdown(self, markdown: str) -> None:
        """Forward updated markdown to the underlying view."""
        self._view.SetMarkdown(markdown)

    def SelectAll(self) -> None:  # noqa: N802 - wx naming convention
        self._view.SelectAll()

    def GetPlainText(self) -> str:
        return self._view.GetPlainText()

    def GetMarkdownView(self) -> MarkdownView:
        """Expose the underlying :class:`MarkdownView` for tests and tooling."""

        return self._view

    def GetScrollerWindow(self) -> wx.ScrolledWindow | None:
        """Return the scroller hosting the markdown view."""

        return self._scroller

    def _on_scroller_size(self, event: wx.SizeEvent) -> None:
        event.Skip()
        self._request_layout_sync()

    def _on_view_rendered(self) -> None:
        self._request_layout_sync()

    def _request_layout_sync(self) -> None:
        if self._destroyed:
            return
        if self._pending_layout_sync:
            return

        self._pending_layout_sync = True

        def run() -> None:
            self._pending_layout_sync = False
            if self._destroyed:
                return
            self._sync_view_layout()

        wx.CallAfter(run)

    def _sync_view_layout(self) -> None:
        if self._destroyed:
            return
        scroller = getattr(self, "_scroller", None)
        if scroller is None:
            return
        try:
            internal = self._view.GetInternalRepresentation()
        except RuntimeError:
            internal = None
        min_width = max(int(self.FromDIP(160)), 0)
        min_height = max(int(self.FromDIP(40)), 0)
        content_width = min_width
        content_height = min_height
        if internal is not None:
            content_width = max(content_width, int(internal.GetWidth()))
            content_height = max(content_height, int(internal.GetHeight()))

        available_width = 0
        try:
            available_width = scroller.GetClientSize().width
        except RuntimeError:
            available_width = 0
        if available_width <= 0:
            parent: wx.Window | None
            try:
                parent = self.GetParent()
            except RuntimeError:
                parent = None
            if parent is not None:
                try:
                    available_width = parent.GetClientSize().width
                except RuntimeError:
                    available_width = 0

        view_width = min_width
        if available_width > 0:
            view_width = max(min_width, min(available_width, content_width))
        else:
            view_width = min_width

        max_visible = self._max_visible_height
        if max_visible <= 0:
            max_visible = content_height
        visible_height = max(min_height, min(content_height, max_visible))

        try:
            self._view.SetMinSize(wx.Size(min_width, min_height))
            self._view.SetInitialSize(wx.Size(view_width, visible_height))
        except RuntimeError:
            return

        try:
            scroller.SetMinSize(wx.Size(min_width, visible_height))
            scroller.SetInitialSize(wx.Size(view_width, visible_height))
            scroller.SetVirtualSize(wx.Size(content_width, content_height))
            scroller.Scroll(0, 0)
        except RuntimeError:
            return

    def _on_scroller_destroy(self, _event: wx.WindowDestroyEvent) -> None:
        self._scroller = None

    def _on_container_destroy(self, _event: wx.WindowDestroyEvent) -> None:
        self._destroyed = True
        self._scroller = None

