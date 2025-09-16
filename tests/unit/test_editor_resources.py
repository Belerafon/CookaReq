"""Tests for requirement editor resource loading."""

import pytest

from app.ui.resources import load_editor_config

pytestmark = pytest.mark.unit


def test_editor_resource_contains_expected_fields():
    config = load_editor_config()
    text_names = [field.name for field in config.text_fields]
    assert text_names[:2] == ["id", "title"]
    assert "statement" in text_names
    grid_names = {field.name for field in config.grid_fields}
    assert {"type", "status", "priority", "verification"}.issubset(grid_names)


def test_editor_resource_help_lookup():
    config = load_editor_config()
    assert "Requirement ID" in config.help_text("id")
    assert "higher-level requirements" in config.help_text("links")
    with pytest.raises(KeyError):
        config.help_text("unknown")


def test_editor_resource_cached():
    first = load_editor_config()
    second = load_editor_config()
    assert first is second
