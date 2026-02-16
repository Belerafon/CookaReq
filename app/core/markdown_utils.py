"""Helpers for normalizing Markdown content."""

from __future__ import annotations

import re

import bleach

__all__ = [
    "MAX_STATEMENT_LENGTH",
    "convert_markdown_math",
    "normalize_escaped_newlines",
    "render_markdown_plain_text",
    "strip_markdown",
    "sanitize_html",
    "validate_markdown",
]

_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_BOLD_ITALIC_RE = re.compile(r"(\*\*|__|\*|_)")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$")
_CODE_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_HTML_TAG_RE = re.compile(r"<\s*/?\s*([A-Za-z][A-Za-z0-9]*)\b([^>]*)>")
_HTML_ATTR_RE = re.compile(
    r'([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(".*?"|\'.*?\'|[^\s"\'<>]+)'
)
_SCHEME_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9+.\-]*):")
_INLINE_FORMULA_RE = re.compile(r"\\\((.+?)\\\)")
_INLINE_DOLLAR_FORMULA_RE = re.compile(r"(?<!\\)\$(?!\$)(.+?)(?<!\\)\$")
_ESCAPED_CRLF_RE = re.compile(r"(?<!\\)\\r\\n")
_ESCAPED_LF_RE = re.compile(r"(?<!\\)\\n")
_ESCAPED_CR_RE = re.compile(r"(?<!\\)\\r")

MAX_STATEMENT_LENGTH = 50_000


def _split_table_row(line: str) -> list[str]:
    raw = line.strip()
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|"):
        raw = raw[:-1]
    return [cell.strip() for cell in raw.split("|")]

_MATHML_TAGS = {
    "math",
    "mrow",
    "mi",
    "mn",
    "mo",
    "mtext",
    "mfrac",
    "msqrt",
    "mroot",
    "msup",
    "msub",
    "msubsup",
    "munder",
    "mover",
    "munderover",
    "mtable",
    "mtr",
    "mtd",
    "mstyle",
    "mspace",
    "mphantom",
    "mfenced",
}

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
} | _MATHML_TAGS
_ALLOWED_ATTRIBUTES = {
    "a": ["href", "title"],
    "img": ["src", "alt", "title", "class"],
    "math": ["xmlns", "display"],
}
_ALLOWED_PROTOCOLS = ["http", "https", "mailto", "file"]
_MARKDOWN_PROTOCOLS = set(_ALLOWED_PROTOCOLS) | {"attachment"}


def strip_markdown(value: str) -> str:
    """Return ``value`` with basic Markdown markers removed."""
    if not value:
        return ""
    value = normalize_escaped_newlines(value)
    lines = value.splitlines()
    output: list[str] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if "|" in line and idx + 1 < len(lines) and _TABLE_SEPARATOR_RE.match(lines[idx + 1]):
            header_cells = _split_table_row(line)
            if header_cells:
                output.append(" | ".join(header_cells))
            idx += 2
            while idx < len(lines):
                row_line = lines[idx]
                if "|" not in row_line:
                    break
                row_cells = _split_table_row(row_line)
                if row_cells:
                    output.append(" | ".join(row_cells))
                idx += 1
            continue
        output.append(line)
        idx += 1
    value = "\n".join(output)
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


def _strip_inline_markdown(value: str) -> str:
    cleaned = _IMAGE_RE.sub(lambda match: match.group(1), value)
    cleaned = _LINK_RE.sub(lambda match: match.group(1), cleaned)
    cleaned = _INLINE_CODE_RE.sub(lambda match: match.group(1), cleaned)
    cleaned = _BOLD_ITALIC_RE.sub("", cleaned)
    return cleaned


def _strip_code_segments(value: str) -> str:
    if not value:
        return ""
    lines: list[str] = []
    in_fence = False
    fence_marker = ""
    for line in value.splitlines():
        match = _CODE_FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            continue
        if in_fence:
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    return _INLINE_CODE_RE.sub("", cleaned)


def _validate_tables(value: str) -> list[str]:
    errors: list[str] = []
    if not value:
        return errors
    lines = value.splitlines()
    in_fence = False
    fence_marker = ""
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        match = _CODE_FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            idx += 1
            continue
        if in_fence:
            idx += 1
            continue
        if "|" in line and idx + 1 < len(lines) and _TABLE_SEPARATOR_RE.match(
            lines[idx + 1]
        ):
            header_cells = _split_table_row(line)
            separator_cells = _split_table_row(lines[idx + 1])
            if not header_cells:
                errors.append("table header row cannot be empty")
                idx += 2
                continue
            if len(separator_cells) != len(header_cells):
                errors.append("table separator column count does not match header")
                idx += 2
                continue
            idx += 2
            row_offset = 1
            while idx < len(lines):
                row_line = lines[idx]
                if "|" not in row_line or _CODE_FENCE_RE.match(row_line):
                    break
                row_cells = _split_table_row(row_line)
                if row_cells and len(row_cells) != len(header_cells):
                    errors.append(
                        "table row {row} has {actual} columns, expected {expected}".format(
                            row=row_offset,
                            actual=len(row_cells),
                            expected=len(header_cells),
                        )
                    )
                idx += 1
                row_offset += 1
            continue
        idx += 1
    return errors


def _validate_scheme(target: str, *, allowed: set[str]) -> str | None:
    match = _SCHEME_RE.match(target or "")
    if not match:
        return None
    scheme = match.group(1).lower()
    if scheme not in allowed:
        return f"disallowed URI scheme: {scheme}"
    return None


def _validate_markdown_links(value: str) -> list[str]:
    errors: list[str] = []
    if not value:
        return errors
    cleaned = _strip_code_segments(value)
    for match in _LINK_RE.finditer(cleaned):
        url = match.group(2).strip()
        issue = _validate_scheme(url, allowed=_MARKDOWN_PROTOCOLS)
        if issue:
            errors.append(f"link target {issue}")
    for match in _IMAGE_RE.finditer(cleaned):
        url = match.group(2).strip()
        issue = _validate_scheme(url, allowed=_MARKDOWN_PROTOCOLS)
        if issue:
            errors.append(f"image source {issue}")
    return errors


def _validate_inline_html(value: str) -> list[str]:
    errors: list[str] = []
    if not value:
        return errors
    cleaned = _strip_code_segments(value)
    for match in _HTML_TAG_RE.finditer(cleaned):
        tag = match.group(1).lower()
        attrs = match.group(2) or ""
        if tag not in _ALLOWED_TAGS:
            errors.append(f"HTML tag <{tag}> is not allowed")
            continue
        if not attrs.strip():
            continue
        allowed_attrs = _ALLOWED_ATTRIBUTES.get(tag, [])
        for attr_match in _HTML_ATTR_RE.finditer(attrs):
            attr_name = attr_match.group(1).lower()
            attr_value = attr_match.group(2).strip().strip('"').strip("'")
            if attr_name.startswith("on"):
                errors.append(f"HTML attribute {attr_name} is not allowed on <{tag}>")
                continue
            if attr_name not in allowed_attrs:
                errors.append(f"HTML attribute {attr_name} is not allowed on <{tag}>")
                continue
            if attr_name in {"href", "src"}:
                issue = _validate_scheme(attr_value, allowed=set(_ALLOWED_PROTOCOLS))
                if issue:
                    errors.append(f"HTML attribute {attr_name} {issue}")
    return errors


def validate_markdown(value: str) -> None:
    """Validate Markdown content and raise ValueError on invalid input."""
    if value is None:
        raise ValueError("statement cannot be null")
    if not isinstance(value, str):
        value = str(value)
    if len(value) > MAX_STATEMENT_LENGTH:
        raise ValueError(
            f"statement exceeds maximum length of {MAX_STATEMENT_LENGTH} characters"
        )
    errors = []
    errors.extend(_validate_tables(value))
    errors.extend(_validate_markdown_links(value))
    errors.extend(_validate_inline_html(value))
    if errors:
        raise ValueError("; ".join(errors))


def _render_ascii_table(rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    widths = [0] * max(len(row) for row in rows)
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))
    border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
    rendered = [border]
    for row in rows:
        padded = [
            cell.ljust(widths[idx]) if idx < len(row) else " " * widths[idx]
            for idx, cell in enumerate(row + [""] * (len(widths) - len(row)))
        ]
        rendered.append("| " + " | ".join(padded) + " |")
        rendered.append(border)
    return rendered


def render_markdown_plain_text(value: str) -> str:
    """Return a plain-text representation of Markdown, including ASCII tables."""
    if not value:
        return ""
    value = normalize_escaped_newlines(value)
    lines = value.splitlines()
    output: list[str] = []
    idx = 0
    in_fence = False
    fence_marker = ""
    while idx < len(lines):
        line = lines[idx]
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
            idx += 1
            continue
        if in_fence:
            output.append(line)
            idx += 1
            continue
        if "|" in line and idx + 1 < len(lines) and _TABLE_SEPARATOR_RE.match(
            lines[idx + 1]
        ):
            header_cells = [_strip_inline_markdown(cell) for cell in _split_table_row(line)]
            idx += 2
            rows: list[list[str]] = [header_cells]
            while idx < len(lines):
                row_line = lines[idx]
                if "|" not in row_line or _CODE_FENCE_RE.match(row_line):
                    break
                row_cells = [_strip_inline_markdown(cell) for cell in _split_table_row(row_line)]
                if row_cells:
                    rows.append(row_cells)
                idx += 1
            output.extend(_render_ascii_table(rows))
            continue
        output.append(_strip_inline_markdown(line))
        idx += 1
    return "\n".join(output)


def _convert_latex_to_mathml(latex: str, *, display: str) -> str | None:
    try:
        from latex2mathml.converter import convert as latex_to_mathml
    except ImportError:  # pragma: no cover - dependency is optional at runtime
        return None
    try:
        return latex_to_mathml(latex, display=display)
    except Exception:  # pragma: no cover - conversion failures
        return None


def _replace_inline_math(text: str) -> str:
    def _looks_like_formula(candidate: str) -> bool:
        stripped = candidate.strip()
        if not stripped:
            return False
        return any(ch.isalpha() for ch in stripped) or any(
            token in stripped for token in ("\\", "^", "_", "{", "}", "=", "+", "-", "*", "/")
        )

    parts = text.split("`")
    for idx, part in enumerate(parts):
        if idx % 2:
            continue

        def _inline_repl(match: re.Match[str]) -> str:
            latex = match.group(1).strip()
            if not latex:
                return match.group(0)
            mathml = _convert_latex_to_mathml(latex, display="inline")
            return mathml or match.group(0)

        def _inline_dollar_repl(match: re.Match[str]) -> str:
            latex = match.group(1).strip()
            if not _looks_like_formula(latex):
                return match.group(0)
            mathml = _convert_latex_to_mathml(latex, display="inline")
            return mathml or match.group(0)

        converted = _INLINE_FORMULA_RE.sub(_inline_repl, part)
        parts[idx] = _INLINE_DOLLAR_FORMULA_RE.sub(_inline_dollar_repl, converted)
    return "`".join(parts)


def convert_markdown_math(value: str) -> str:
    """Replace LaTeX-style math markers with MathML where possible."""
    if not value or ("\\(" not in value and "$$" not in value and "$" not in value):
        return value
    value = normalize_escaped_newlines(value)
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
                mathml = _convert_latex_to_mathml(latex, display="block")
                rendered = mathml or f"$${latex}$$"
                if after:
                    output.append(f"{rendered}{_replace_inline_math(after)}")
                else:
                    output.append(rendered)
                block_lines = []
                in_block = False
            else:
                block_lines.append(line)
            continue
        if "$$" in line:
            before, _sep, after = line.partition("$$")
            if "$$" in after:
                latex, _sep2, rest = after.partition("$$")
                mathml = _convert_latex_to_mathml(latex.strip(), display="block")
                replacement = mathml or f"$${latex}$$"
                prefix = _replace_inline_math(before)
                suffix = _replace_inline_math(rest)
                output.append(f"{prefix}{replacement}{suffix}")
            else:
                if before:
                    output.append(_replace_inline_math(before))
                block_lines = [after]
                in_block = True
            continue
        output.append(_replace_inline_math(line))

    if in_block:
        output.append("$$" + "\n".join(block_lines))
    return "\n".join(output)


def normalize_escaped_newlines(value: str) -> str:
    """Replace unescaped ``\\n``/``\\r`` sequences with real line breaks."""
    if not value or "\\" not in value:
        return value
    normalized = _ESCAPED_CRLF_RE.sub("\n", value)
    normalized = _ESCAPED_LF_RE.sub("\n", normalized)
    normalized = _ESCAPED_CR_RE.sub("\n", normalized)
    return normalized
