"""Tests for config manager proxies."""

import pytest

from app.config import ConfigManager

pytestmark = pytest.mark.unit


def test_config_manager_proxy_methods(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    assert cfg.read_int("number", 5) == 5
    cfg.write_int("number", 42)
    cfg.flush()
    assert cfg.read_int("number", 0) == 42

    assert cfg.read("text", "") == ""
    cfg.write("text", "hello")
    cfg.flush()
    assert cfg.read("text", "") == "hello"

    assert cfg.read_bool("flag", False) is False
    cfg.write_bool("flag", True)
    cfg.flush()
    assert cfg.read_bool("flag", False) is True
