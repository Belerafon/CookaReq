"""Utilities to render markdown content inside chat bubbles."""

from __future__ import annotations

from dataclasses import dataclass

import markdown
import wx
import wx.html as html

from ..text import normalize_for_display


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
    # Сырый HTML от LLM не отображаем, чтобы не встраивать произвольные теги.
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
            style=html.HW_SCROLLBAR_NEVER,
        )
        self._theme = MarkdownTheme(foreground_colour, background_colour)
        self._markdown: str = ""
        self.SetBackgroundColour(background_colour)
        self.SetForegroundColour(foreground_colour)
        self.SetBorders(0)
        self.Bind(wx.EVT_SIZE, self._on_size)

    def SetMarkdown(self, markdown_text: str) -> None:
        """Update control contents with *markdown_text*."""

        self._markdown = markdown_text
        html_markup = self._wrap_html(_render_markdown(markdown_text))
        html_markup = normalize_for_display(html_markup)
        self.SetPage(html_markup)
        self._refresh_best_size()

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
        self._view = MarkdownView(
            self,
            foreground_colour=foreground_colour,
            background_colour=background_colour,
        )
        self._view.SetMinSize(wx.Size(self.FromDIP(160), -1))
        self._view.SetMarkdown(markdown)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._view, 1, wx.EXPAND)
        self.SetSizer(sizer)

    def DoSetFont(self, font: wx.Font | None) -> bool:  # noqa: N802 - wx naming convention
        changed = super().DoSetFont(font)
        if changed:
            effective = font if font is not None else self.GetFont()
            if effective.IsOk():
                self._view.SetFont(effective)
            else:
                self._view.SetFont(wx.NullFont)
        return changed

    def HasSelection(self) -> bool:  # noqa: N802 - wx naming convention
        return self._view.HasSelection()

    def GetSelectionText(self) -> str:
        return self._view.GetSelectionText()

    def SelectAll(self) -> None:  # noqa: N802 - wx naming convention
        self._view.SelectAll()

    def GetPlainText(self) -> str:
        return self._view.GetPlainText()

