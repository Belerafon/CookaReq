"""SVG templates shared between UI components."""
from __future__ import annotations

from textwrap import dedent


SELECT_ALL_ICON_SVG_TEMPLATE = dedent(
    """
    <svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" fill="none" stroke="{stroke}" stroke-opacity="{stroke_opacity}" stroke-width="1.5" />
      <path d="M6.2 11.7 L9.2 14.7 L13.6 8.6" fill="none" stroke="{stroke}" stroke-opacity="{stroke_opacity}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
      <line x1="14.6" y1="9.4" x2="17.6" y2="9.4" stroke="{stroke}" stroke-opacity="{stroke_opacity}" stroke-width="1.4" stroke-linecap="round" />
      <line x1="14.6" y1="13.0" x2="17.6" y2="13.0" stroke="{stroke}" stroke-opacity="{stroke_opacity}" stroke-width="1.4" stroke-linecap="round" />
      <line x1="14.6" y1="16.6" x2="17.6" y2="16.6" stroke="{stroke}" stroke-opacity="{stroke_opacity}" stroke-width="1.4" stroke-linecap="round" />
    </svg>
    """
)


__all__ = ["SELECT_ALL_ICON_SVG_TEMPLATE"]
