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
    finally:
        frame.Destroy()
