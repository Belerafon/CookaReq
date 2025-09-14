"""Tests for time utilities."""

import re

import pytest

from app.util.time import local_now_str, normalize_timestamp, utc_now_iso

pytestmark = pytest.mark.unit


def test_utc_now_iso_format():
    value = utc_now_iso()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", value)


def test_local_now_str_format():
    value = local_now_str()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value)


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, ""),
        ("", ""),
        ("2024-01-02T03:04:05.123456+00:00", "2024-01-02 03:04:05"),
        ("2024-01-02T03:04:05.123456", "2024-01-02 03:04:05"),
        ("2024-01-02 03:04:05.123456", "2024-01-02 03:04:05"),
        ("2024-01-02", "2024-01-02"),
    ],
)
def test_normalize_timestamp_valid(raw, expected):
    assert normalize_timestamp(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "2024-13-02T03:04:05",
        "2024-13-02 03:04:05",
        "2024-13-02",
        "2024-02-30",
        "not-a-date",
    ],
)
def test_normalize_timestamp_invalid(raw):
    with pytest.raises(ValueError):
        normalize_timestamp(raw)
