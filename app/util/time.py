"""Time-related helpers for CookaReq."""

from __future__ import annotations

import datetime


def utc_now_iso() -> str:
    """Return current UTC time in ISO format without sub-second precision."""
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def local_now_str() -> str:
    """Return local time in ``YYYY-MM-DD HH:MM:SS`` format."""
    return (
        datetime.datetime.now(datetime.UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    )


def normalize_timestamp(value: str | None) -> str:
    """Normalize ``value`` to second precision while preserving date-only strings."""
    if not value:
        return ""
    if ":" not in value:
        return value.split(".", 1)[0]
    try:
        dt = datetime.datetime.fromisoformat(value)
    except ValueError:
        base = value.split(".", 1)[0]
        return base.replace("T", " ")
    return dt.strftime("%Y-%m-%d %H:%M:%S")
