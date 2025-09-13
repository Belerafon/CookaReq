import wx

from app.config import ConfigManager


def test_config_manager_proxy_methods(tmp_path):
    app = wx.App()
    try:
        cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

        assert cfg.ReadInt("number", 5) == 5
        cfg.WriteInt("number", 42)
        cfg.Flush()
        assert cfg.ReadInt("number", 0) == 42

        assert cfg.Read("text", "") == ""
        cfg.Write("text", "hello")
        cfg.Flush()
        assert cfg.Read("text", "") == "hello"

        assert cfg.ReadBool("flag", False) is False
        cfg.WriteBool("flag", True)
        cfg.Flush()
        assert cfg.ReadBool("flag", False) is True
    finally:
        app.Destroy()
