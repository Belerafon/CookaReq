"""GUI regression tests for MarkdownView rendering."""

from __future__ import annotations

import pytest


pytestmark = [pytest.mark.gui]


def _colour_to_hex(colour) -> str:
    return f"#{colour.Red():02x}{colour.Green():02x}{colour.Blue():02x}"


def test_markdown_view_sets_html_body_attributes(wx_app):
    wx = pytest.importorskip("wx")

    background = wx.Colour(210, 238, 215)
    foreground = wx.Colour(24, 48, 30)

    frame = wx.Frame(None)
    try:
        from app.ui.widgets.markdown_view import MarkdownView

        view = MarkdownView(
            frame,
            foreground_colour=foreground,
            background_colour=background,
        )

        html = view._wrap_html("sample text")

        background_hex = _colour_to_hex(background)
        foreground_hex = _colour_to_hex(foreground)

        assert f'bgcolor="{background_hex}"' in html
        assert f'text="{foreground_hex}"' in html
        assert f"background-color: {background_hex};" in html
        assert f"color: {foreground_hex};" in html
        assert "vertical-align: middle;" in html
        assert "th {" in html
    finally:
        frame.Destroy()


def test_markdown_view_injects_table_compatibility_attributes(wx_app):
    wx = pytest.importorskip("wx")

    background = wx.Colour(255, 255, 255)
    foreground = wx.Colour(20, 20, 20)

    frame = wx.Frame(None)
    try:
        from app.ui.widgets.markdown_view import MarkdownView

        view = MarkdownView(
            frame,
            foreground_colour=foreground,
            background_colour=background,
        )

        html = view._wrap_html("<table><thead><tr><th>H</th></tr></thead><tbody><tr><td>V</td></tr></tbody></table>")

        assert 'border="1"' in html
        assert 'bordercolor="#' in html
        assert '<th bgcolor="#' in html
        assert '<td valign="middle" align="left">V</td>' in html
        assert 'font-weight: bold;' in html
    finally:
        frame.Destroy()


def test_markdown_view_render_markdown_supports_single_dollar_formulas() -> None:
    from app.ui.widgets.markdown_view import _render_markdown

    rendered = _render_markdown("Energy: $E = mc^2$", allow_html=True, render_math=True)

    assert "$E = mc^2$" not in rendered
    assert "math-formula-inline" in rendered or "<math" in rendered
