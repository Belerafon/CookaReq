"""Utilities to render markdown content inside chat bubbles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import html as html_lib
import logging
from pathlib import Path
import re
import tempfile
from urllib.parse import quote

import markdown
import wx
import wx.html as wx_html

from ...core.markdown_utils import (
    convert_markdown_math,
    normalize_escaped_newlines,
    sanitize_html,
    strip_markdown,
)
from ..text import normalize_for_display
import contextlib


_FORMULA_LOG = logging.getLogger(__name__)


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


def _build_markdown_renderer(*, allow_html: bool) -> markdown.Markdown:
    renderer = markdown.Markdown(
        extensions=[
            "markdown.extensions.extra",
            "markdown.extensions.sane_lists",
        ],
        output_format="html5",
    )
    if not allow_html:
        # Hide raw HTML returned by the LLM to avoid embedding arbitrary tags.
        renderer.preprocessors.deregister("html_block")
        renderer.inlinePatterns.deregister("html")
    renderer.reset()
    return renderer


_MARKDOWN = _build_markdown_renderer(allow_html=False)
_MARKDOWN_WITH_HTML = _build_markdown_renderer(allow_html=True)


def _render_markdown(markdown_text: str, *, allow_html: bool, render_math: bool) -> str:
    renderer = _MARKDOWN_WITH_HTML if allow_html else _MARKDOWN
    renderer.reset()
    prepared = normalize_escaped_newlines(markdown_text or "")
    if render_math:
        prepared = _replace_markdown_formulas_with_images(prepared)
        prepared = convert_markdown_math(prepared)
    markup = renderer.convert(prepared)
    return sanitize_html(markup)


_INLINE_FORMULA_RE = re.compile(r"\\\((.+?)\\\)")
_INLINE_DOLLAR_FORMULA_RE = re.compile(r"(?<!\\)\$(?!\$)(.+?)(?<!\\)\$")
_CODE_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _looks_like_formula(candidate: str) -> bool:
    stripped = candidate.strip()
    if not stripped:
        return False
    return any(ch.isalpha() for ch in stripped) or any(
        token in stripped for token in ("\\", "^", "_", "{", "}", "=", "+", "-", "*", "/")
    )


def _latex_to_png_bytes(latex: str) -> bytes | None:
    try:
        import matplotlib
        from matplotlib import pyplot as plt
    except ImportError:  # pragma: no cover - optional runtime dependency
        _FORMULA_LOG.warning(
            "Formula preview PNG renderer is unavailable: matplotlib is not installed."
        )
        return None

    matplotlib.use("Agg", force=True)
    figure = None
    try:
        figure = plt.figure(figsize=(0.01, 0.01))
        figure.text(0.0, 0.0, f"${latex}$", fontsize=12)
        with tempfile.SpooledTemporaryFile() as buffer:
            figure.savefig(
                buffer,
                format="png",
                bbox_inches="tight",
                pad_inches=0.1,
                transparent=True,
            )
            buffer.seek(0)
            return buffer.read()
    except Exception:  # pragma: no cover - rendering failures
        _FORMULA_LOG.exception("Failed to render formula preview image for LaTeX expression.")
        return None
    finally:
        if figure is not None:
            plt.close(figure)


def _formula_image_uri(latex: str) -> str | None:
    png_bytes = _latex_to_png_bytes(latex)
    if not png_bytes:
        return None
    cache_dir = Path(tempfile.gettempdir()) / "cookareq-formula-preview"
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(latex.encode("utf-8")).hexdigest()
    target = cache_dir / f"{digest}.png"
    if not target.exists():
        target.write_bytes(png_bytes)
    return target.as_uri()


def _formula_img_tag(latex: str, *, display: str) -> str:
    uri = _formula_image_uri(latex)
    if not uri:
        escaped = latex.replace("\\", "\\\\")
        return f"$${escaped}$$" if display == "block" else f"\\({escaped}\\)"
    escaped_latex = html_lib.escape(latex, quote=True)
    class_name = "math-formula-block" if display == "block" else "math-formula-inline"
    return (
        f'<img src="{quote(uri, safe=":/%")}" alt="{escaped_latex}" '
        f'title="{escaped_latex}" class="{class_name}" />'
    )


def _replace_inline_formulas(text: str) -> str:
    parts = text.split("`")
    for idx, part in enumerate(parts):
        if idx % 2:
            continue

        def _inline_repl(match: re.Match[str]) -> str:
            latex = match.group(1).strip()
            if not latex:
                return match.group(0)
            return _formula_img_tag(latex, display="inline")

        def _inline_dollar_repl(match: re.Match[str]) -> str:
            latex = match.group(1).strip()
            if not _looks_like_formula(latex):
                return match.group(0)
            return _formula_img_tag(latex, display="inline")

        converted = _INLINE_FORMULA_RE.sub(_inline_repl, part)
        parts[idx] = _INLINE_DOLLAR_FORMULA_RE.sub(_inline_dollar_repl, converted)
    return "`".join(parts)


def _replace_markdown_formulas_with_images(value: str) -> str:
    if not value or ("\\(" not in value and "$$" not in value and "$" not in value):
        return value

    lines = value.splitlines()
    output: list[str] = []
    in_fence = False
    fence_marker = ""
    in_block = False
    block_lines: list[str] = []

    for line in lines:
        match = _CODE_FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            output.append(line)
            continue
        if in_fence:
            output.append(line)
            continue
        if in_block:
            if "$$" in line:
                before, _sep, after = line.partition("$$")
                block_lines.append(before)
                latex = "\n".join(block_lines).strip()
                rendered = _formula_img_tag(latex, display="block") if latex else ""
                tail = _replace_inline_formulas(after) if after else ""
                output.append(f"{rendered}{tail}")
                block_lines = []
                in_block = False
            else:
                block_lines.append(line)
            continue
        if "$$" in line:
            before, _sep, after = line.partition("$$")
            if "$$" in after:
                latex, _sep2, rest = after.partition("$$")
                replacement = _formula_img_tag(latex.strip(), display="block")
                output.append(
                    f"{_replace_inline_formulas(before)}{replacement}{_replace_inline_formulas(rest)}"
                )
            else:
                if before:
                    output.append(_replace_inline_formulas(before))
                block_lines = [after]
                in_block = True
            continue
        output.append(_replace_inline_formulas(line))

    if in_block:
        output.append("$$" + "\n".join(block_lines))
    return "\n".join(output)


def _wx_html_table_compatibility_markup(
    body_html: str,
    *,
    border_hex: str,
    header_hex: str,
) -> str:
    """Inject legacy table attributes for wx HTML compatibility."""

    if "<table" not in body_html:
        return body_html

    table_pattern = re.compile(r"<table(\s[^>]*)?>", re.IGNORECASE)
    th_pattern = re.compile(r"<th(\s[^>]*)?>", re.IGNORECASE)
    td_pattern = re.compile(r"<td(\s[^>]*)?>", re.IGNORECASE)

    def _has_attribute(attributes: str, name: str) -> bool:
        return re.search(rf"(?:^|\s){re.escape(name)}\s*=", attributes, re.IGNORECASE) is not None

    def _table_repl(match: re.Match[str]) -> str:
        attributes = (match.group(1) or "").strip()
        additions: list[str] = []
        if not _has_attribute(attributes, "border"):
            additions.append('border="1"')
        if not _has_attribute(attributes, "cellspacing"):
            additions.append('cellspacing="0"')
        if not _has_attribute(attributes, "cellpadding"):
            additions.append('cellpadding="6"')
        if not _has_attribute(attributes, "bordercolor"):
            additions.append(f'bordercolor="{border_hex}"')
        if not additions:
            return match.group(0)
        suffix = f" {attributes}" if attributes else ""
        return "<table " + " ".join(additions) + f"{suffix}>"

    def _th_repl(match: re.Match[str]) -> str:
        attributes = (match.group(1) or "").strip()
        additions: list[str] = []
        if not _has_attribute(attributes, "bgcolor"):
            additions.append(f'bgcolor="{header_hex}"')
        if not _has_attribute(attributes, "valign"):
            additions.append('valign="middle"')
        if not _has_attribute(attributes, "align"):
            additions.append('align="left"')
        if not additions:
            return match.group(0)
        suffix = f" {attributes}" if attributes else ""
        return "<th " + " ".join(additions) + f"{suffix}>"

    def _td_repl(match: re.Match[str]) -> str:
        attributes = (match.group(1) or "").strip()
        additions: list[str] = []
        if not _has_attribute(attributes, "valign"):
            additions.append('valign="middle"')
        if not _has_attribute(attributes, "align"):
            additions.append('align="left"')
        if not additions:
            return match.group(0)
        suffix = f" {attributes}" if attributes else ""
        return "<td " + " ".join(additions) + f"{suffix}>"

    body_html = table_pattern.sub(_table_repl, body_html)
    body_html = th_pattern.sub(_th_repl, body_html)
    return td_pattern.sub(_td_repl, body_html)


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
        return _mix_colour(self.foreground, self.background, 0.5)

    def table_header_background(self) -> wx.Colour:
        return _mix_colour(self.background, self.foreground, 0.12)

    def subtle_background(self) -> wx.Colour:
        return _mix_colour(self.background, self.foreground, 0.08)


_RENDER_BUSY_RETRY_LIMIT = 5
_RENDER_RETRY_DELAY_MS = 0


class MarkdownView(wx_html.HtmlWindow):
    """Simple view displaying markdown converted to HTML."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        foreground_colour: wx.Colour,
        background_colour: wx.Colour,
        render_math: bool = False,
    ) -> None:
        super().__init__(
            parent,
            style=wx_html.HW_SCROLLBAR_AUTO,
        )
        self._theme = MarkdownTheme(foreground_colour, background_colour)
        self._markdown: str = ""
        self._render_math = bool(render_math)
        self._pending_markup: str | None = None
        self._pending_render: bool = False
        self._pending_render_attempts: int = 0
        self._render_retry: wx.CallLater | None = None
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
        markup = self._wrap_html(
            _render_markdown(
                markdown_text,
                allow_html=self._render_math,
                render_math=self._render_math,
            )
        )
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
        text = self.ToText()
        if not text.strip():
            return strip_markdown(self._markdown)
        return text

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
            try:
                if self._destroyed:
                    self._pending_markup = None
                    return
                if self._try_render_pending_markup():
                    self._pending_render_attempts = 0
                    return
                if self._pending_markup is None:
                    self._pending_render_attempts = 0
                    return
            finally:
                self._pending_render = False

            self._pending_render_attempts += 1
            if self._pending_render_attempts >= _RENDER_BUSY_RETRY_LIMIT:
                self._pending_render_attempts = _RENDER_BUSY_RETRY_LIMIT
                self._schedule_render_retry()
            else:
                self._schedule_immediate_retry()

        if self._render_retry is not None:
            self._render_retry.Stop()
            self._render_retry = None

        wx.CallAfter(run)

    def _schedule_immediate_retry(self) -> None:
        if self._destroyed or self._pending_markup is None:
            return
        wx.CallAfter(self._request_pending_render)

    def _schedule_render_retry(self) -> None:
        if self._destroyed or self._pending_markup is None:
            return
        if self._render_retry is not None:
            return

        def _trigger() -> None:
            self._render_retry = None
            if self._destroyed:
                self._pending_markup = None
                return
            self._request_pending_render()

        # Allow the event loop to process other handlers before retrying the
        # markdown render again. ``CallLater`` avoids a tight ``CallAfter``
        # loop when the underlying window is not yet ready (for example when
        # tests create controls on hidden parents), which previously led to an
        # endless stream of pending events and a stalled test run.
        self._render_retry = wx.CallLater(_RENDER_RETRY_DELAY_MS, _trigger)

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
            self._pending_render_attempts = 0
            if self._render_retry is not None:
                with contextlib.suppress(Exception):  # pragma: no cover - defensive
                    self._render_retry.Stop()
                self._render_retry = None
            self._render_listeners.clear()
        event.Skip()

    def _wrap_html(self, body_html: str) -> str:
        foreground_hex = _colour_to_hex(self._theme.foreground)
        background_hex = _colour_to_hex(self._theme.background)
        table_border_hex = _colour_to_hex(self._theme.table_border())
        table_header_hex = _colour_to_hex(self._theme.table_header_background())
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
        compatible_body_html = _wx_html_table_compatibility_markup(
            body_html,
            border_hex=table_border_hex,
            header_hex=table_header_hex,
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
            " vertical-align: middle;"
            "}"
            "th {"
            f" background-color: {table_header_hex};"
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
            "img.math-formula-inline {"
            " vertical-align: middle;"
            "}"
            "img.math-formula-block {"
            " display: block;"
            " margin: 8px 0;"
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
            f"{compatible_body_html}"
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
        render_math: bool = False,
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
        self._last_scroller_width: int | None = None
        self._layout_debounce: wx.CallLater | None = None
        self._layout_events_history: list[float] = []

        self._view = MarkdownView(
            scroller,
            foreground_colour=foreground_colour,
            background_colour=background_colour,
            render_math=render_math,
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
        # Some GUI tests interrogate the plain-text value immediately after
        # construction; attempt a synchronous render so ``GetPlainText`` is
        # populated without waiting for deferred callbacks.
        with contextlib.suppress(Exception):
            self._view._try_render_pending_markup()

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
        return self._view.HasSelection() or bool(self.GetPlainText().strip())

    def GetSelectionText(self) -> str:
        text = self._view.GetSelectionText()
        if not text:
            return self.GetPlainText()
        return text

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
        # Only react to width changes and debounce to avoid oscillation
        try:
            size = event.GetSize()
            new_width = int(size.width)
        except Exception:
            new_width = -1
        if self._last_scroller_width is not None and new_width == self._last_scroller_width:
            return
        self._last_scroller_width = new_width

        # Freeze detector: suppress bursts >10 within 2s
        import time
        now = time.time()
        self._layout_events_history = [t for t in self._layout_events_history if now - t < 2.0]
        self._layout_events_history.append(now)
        if len(self._layout_events_history) > 10:
            # Skip scheduling this one; next non-burst event will resync
            return

        # Debounce pending sync
        try:
            if self._layout_debounce is not None:
                self._layout_debounce.Stop()
        except Exception:
            self._layout_debounce = None
        self._layout_debounce = wx.CallLater(120, self._request_layout_sync)

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

        if available_width > 0:
            max(min_width, min(available_width, content_width))
        else:
            pass

        max_visible = self._max_visible_height
        if max_visible <= 0:
            max_visible = content_height
        visible_height = max(min_height, min(content_height, max_visible))

        # Apply only if values actually changed to avoid EVT_SIZE storms
        try:
            current_view_min = self._view.GetMinSize()
        except RuntimeError:
            current_view_min = wx.Size(0, 0)
        desired_view_min = wx.Size(min_width, min_height)
        try:
            if current_view_min != desired_view_min:
                self._view.SetMinSize(desired_view_min)
        except RuntimeError:
            return

        # Scroller: set min/virtual size only if changed; avoid InitialSize
        try:
            current_scroller_min = scroller.GetMinSize()
        except RuntimeError:
            current_scroller_min = wx.Size(0, 0)
        desired_scroller_min = wx.Size(min_width, visible_height)
        try:
            current_virtual = scroller.GetVirtualSize()
        except RuntimeError:
            current_virtual = wx.Size(0, 0)
        desired_virtual = wx.Size(content_width, content_height)
        try:
            if current_scroller_min != desired_scroller_min:
                scroller.SetMinSize(desired_scroller_min)
            if current_virtual != desired_virtual:
                scroller.SetVirtualSize(desired_virtual)
            # Only scroll to top if not already there to avoid triggering work
            try:
                vx, vy = scroller.GetViewStart()
            except RuntimeError:
                vx, vy = (0, 0)
            if (vx, vy) != (0, 0):
                scroller.Scroll(0, 0)
        except RuntimeError:
            return

    def _on_scroller_destroy(self, _event: wx.WindowDestroyEvent) -> None:
        self._scroller = None

    def _on_container_destroy(self, _event: wx.WindowDestroyEvent) -> None:
        self._destroyed = True
        self._scroller = None
