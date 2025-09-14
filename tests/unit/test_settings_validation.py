"""Tests for settings validation."""

from __future__ import annotations

import json
import pytest

from app.settings import load_app_settings


def test_invalid_settings_raises(tmp_path):
    file = tmp_path / "settings.json"
    file.write_text(json.dumps({"mcp": {"port": "not-int"}}))
    with pytest.raises(ValueError):
        load_app_settings(file)
