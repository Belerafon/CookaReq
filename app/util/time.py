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


def format_datetime_for_humans(value: datetime.datetime) -> str:
    """Return ``value`` in local time with second precision and timezone.

    The output keeps the ISO timezone offset but uses a space between date and
    time, e.g. ``2026-02-10 10:05:03+03:00``.
    """
    return value.astimezone().isoformat(sep=" ", timespec="seconds")


def normalize_timestamp(value: str | None) -> str:
    """Normalize ``value`` to second precision.

    Empty input returns an empty string. Valid ISO date strings are preserved as is,
    while datetime strings are converted to ``YYYY-MM-DD HH:MM:SS`` format with
    microseconds discarded. Invalid values raise :class:`ValueError`.
    """
    if not value:
        return ""

    if ":" not in value:
        base = value.split(".", 1)[0]
        try:
            datetime.date.fromisoformat(base)
        except ValueError as exc:
            raise ValueError(f"Invalid date: {value}") from exc
        return base

    try:
        dt = datetime.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid datetime: {value}") from exc
    return dt.strftime("%Y-%m-%d %H:%M:%S")
