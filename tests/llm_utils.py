import os
import wx


def cfg_from_env(app_name: str) -> wx.Config:
    """Return wx.Config initialized with LLM settings from environment."""
    api_key = os.environ.get("OPEN_ROUTER", "")
    app = wx.App()
    cfg = wx.Config(appName=app_name, style=wx.CONFIG_USE_LOCAL_FILE)
    cfg.Write("llm_api_base", "https://openrouter.ai/api/v1")
    # Use the smallest free model that still supports tool calling
    cfg.Write("llm_model", "qwen/qwen3-4b:free")
    cfg.Write("llm_api_key", api_key)
    cfg.Flush()
    app.Destroy()
    return cfg


def cfg_with_mcp(host: str, port: int, base_path: str, token: str, *, app_name: str) -> wx.Config:
    """Return wx.Config with both MCP and LLM settings."""
    cfg = cfg_from_env(app_name)
    cfg.Write("mcp_host", host)
    cfg.WriteInt("mcp_port", port)
    cfg.Write("mcp_base_path", base_path)
    cfg.Write("mcp_token", token)
    cfg.Flush()
    return cfg
