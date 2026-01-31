"""Helpers for normalizing Markdown content."""

from __future__ import annotations

import re

import bleach

__all__ = ["strip_markdown", "sanitize_html"]

_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_BOLD_ITALIC_RE = re.compile(r"(\*\*|__|\*|_)")

_ALLOWED_TAGS = set(bleach.sanitizer.ALLOWED_TAGS) | {
    "br",
    "hr",
    "p",
    "span",
    "div",
    "pre",
    "code",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "img",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}
_ALLOWED_ATTRIBUTES = {
    "a": ["href", "title"],
    "img": ["src", "alt", "title"],
}
_ALLOWED_PROTOCOLS = ["http", "https", "mailto", "file"]


def strip_markdown(value: str) -> str:
    """Return ``value`` with basic Markdown markers removed."""
    if not value:
        return ""
    value = _IMAGE_RE.sub(lambda match: match.group(1), value)
    value = _LINK_RE.sub(lambda match: match.group(1), value)
    value = _INLINE_CODE_RE.sub(lambda match: match.group(1), value)
    value = _BOLD_ITALIC_RE.sub("", value)
    return value


def sanitize_html(value: str) -> str:
    """Return HTML with unsafe tags/attributes stripped."""
    if not value:
        return ""
    return bleach.clean(
        value,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
    )
