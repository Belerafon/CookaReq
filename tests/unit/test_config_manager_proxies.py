"""Tests for config manager proxies."""

import pytest

from app.columns import default_column_width
from app.config import ConfigManager

pytestmark = pytest.mark.unit


def test_config_manager_column_helpers(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    initial_order = cfg.get_column_order()
    assert initial_order, "expected first run defaults to provide a column order"
    assert len(initial_order) >= 3
    assert initial_order[0] == "id"

    columns = cfg.get_columns()
    physical_fields: list[str] = []
    if "labels" in columns:
        physical_fields.append("labels")
    physical_fields.append("title")
    physical_fields.extend(field for field in columns if field != "labels")
    assert len(physical_fields) >= 3

    expected_width = default_column_width(physical_fields[2])
    assert cfg.get_column_width(2, default=120) == expected_width

    cfg.set_column_width(2, 240)
    cfg.flush()
    assert cfg.get_column_width(2, default=0) == 240

    assert cfg.get_column_order() == initial_order
    cfg.set_column_order(["id", "owner"])
    cfg.flush()
    assert cfg.get_column_order() == ["id", "owner"]

    cfg._raw["col_order"] = "priority,status,,"
    assert cfg.get_column_order() == ["priority", "status"]
