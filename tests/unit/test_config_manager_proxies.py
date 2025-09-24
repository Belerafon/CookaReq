"""Tests for config manager proxies."""

import pytest

from app.config import ConfigManager

pytestmark = pytest.mark.unit


def test_config_manager_column_helpers(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    assert cfg.get_column_width(2, default=120) == 120
    cfg.set_column_width(2, 240)
    cfg.flush()
    assert cfg.get_column_width(2, default=0) == 240

    assert cfg.get_column_order() == []
    cfg.set_column_order(["id", "owner"])
    cfg.flush()
    assert cfg.get_column_order() == ["id", "owner"]

    cfg._raw["col_order"] = "priority,status,,"
    assert cfg.get_column_order() == ["priority", "status"]
