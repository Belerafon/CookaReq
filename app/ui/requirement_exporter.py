"""UI helpers for exporting requirement data."""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

from ..core.model import Requirement
from . import locale


def _format_links(requirement: Requirement) -> str:
    links = getattr(requirement, "links", []) or []
    if not links:
        return ""
    formatted: list[str] = []
    for link in links:
        rid = getattr(link, "rid", str(link))
        if getattr(link, "suspect", False):
            formatted.append(f"{rid} ⚠")
        else:
            formatted.append(str(rid))
    return ", ".join(formatted)


def _format_derived_from(requirement: Requirement) -> str:
    links = getattr(requirement, "links", []) or []
    if not links:
        return ""
    link = links[0]
    rid = getattr(link, "rid", str(link))
    if getattr(link, "suspect", False):
        return f"{rid} ⚠"
    return str(rid)


def _format_attachments(requirement: Requirement) -> str:
    attachments = getattr(requirement, "attachments", []) or []
    if not attachments:
        return ""
    return ", ".join(getattr(item, "path", "") for item in attachments)


def _format_labels(requirement: Requirement) -> str:
    labels = getattr(requirement, "labels", []) or []
    if not labels:
        return ""
    return ", ".join(labels)


def _format_value(value: object, field: str, *, use_locale: bool) -> str:
    if value is None:
        return ""
    if isinstance(value, Enum):
        if use_locale:
            return locale.code_to_label(field, value.value)
        return value.value
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def build_tabular_export(
    requirements: Iterable[Requirement],
    fields: list[str],
    *,
    derived_map: dict[str, list[int]] | None = None,
    header_style: str = "labels",
    value_style: str = "display",
) -> tuple[list[str], list[list[str]]]:
    """Build headers and rows for tabular export."""
    if header_style == "fields":
        headers = list(fields)
    else:
        headers = [locale.field_label(field) for field in fields]
    rows: list[list[str]] = []
    derived_map = derived_map or {}
    use_locale = value_style == "display"
    for requirement in requirements:
        row: list[str] = []
        for field in fields:
            if field == "labels":
                row.append(_format_labels(requirement))
                continue
            if field == "links":
                row.append(_format_links(requirement))
                continue
            if field == "derived_from":
                row.append(_format_derived_from(requirement))
                continue
            if field == "derived_count":
                rid = requirement.rid or str(requirement.id)
                row.append(str(len(derived_map.get(rid, []))))
                continue
            if field == "attachments":
                row.append(_format_attachments(requirement))
                continue
            value = getattr(requirement, field, "")
            row.append(_format_value(value, field, use_locale=use_locale))
        rows.append(row)
    return headers, rows
