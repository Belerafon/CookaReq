"""Timestamp formatting helpers for the agent chat panel."""

from __future__ import annotations

import datetime
from typing import Any

from ...i18n import _


def _coerce_datetime(value: Any) -> datetime.datetime | None:
    """Return timezone-aware ``datetime`` extracted from *value*."""

    if isinstance(value, datetime.datetime):
        moment = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            moment = datetime.datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.UTC)
    return moment.astimezone(datetime.UTC)


def format_last_activity(timestamp: str | None) -> str:
    """Return human readable description of last activity time."""

    if not timestamp:
        return _("No activity yet")
    try:
        moment = datetime.datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.UTC)
    local_moment = moment.astimezone()
    now = datetime.datetime.now(local_moment.tzinfo)
    today = now.date()
    date_value = local_moment.date()
    if date_value == today:
        return _("Today {time}").format(time=local_moment.strftime("%H:%M"))
    if date_value == today - datetime.timedelta(days=1):
        return _("Yesterday {time}").format(time=local_moment.strftime("%H:%M"))
    if date_value.year == today.year:
        return local_moment.strftime("%d %b %H:%M")
    return local_moment.strftime("%Y-%m-%d %H:%M:%S")


def format_entry_timestamp(timestamp: str | None) -> str:
    """Return timestamp for transcript entries in local time."""

    if not timestamp:
        return ""
    try:
        moment = datetime.datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.UTC)
    local_moment = moment.astimezone()
    return local_moment.strftime("%Y-%m-%d %H:%M:%S")


def parse_iso_timestamp(value: Any) -> datetime.datetime | None:
    """Return timezone-aware ``datetime`` derived from ISO timestamp."""

    return _coerce_datetime(value)


__all__ = ["format_entry_timestamp", "format_last_activity", "parse_iso_timestamp"]
