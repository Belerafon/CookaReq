import json
import os
from pathlib import Path

from app.settings import AppSettings, load_app_settings


def settings_from_env(tmp_path: Path) -> AppSettings:
    """Write LLM settings to a JSON file and load them."""
    api_key = os.environ.get("OPEN_ROUTER", "")
    data = {
        "llm": {
            "api_base": "https://openrouter.ai/api/v1",
            "model": "qwen/qwen3-4b:free",
            "api_key": api_key,
            "timeout": 60,
        }
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data))
    return load_app_settings(path)


def settings_with_mcp(
    host: str,
    port: int,
    base_path: str,
    token: str,
    *,
    tmp_path: Path,
    require_token: bool = False,
    fmt: str = "json",
) -> AppSettings:
    """Return settings for LLM and MCP, persisted to a file.

    ``fmt`` controls the file format (``"json"`` or ``"toml"``).
    """

    api_key = os.environ.get("OPEN_ROUTER", "")
    settings = {
        "llm": {
            "api_base": "https://openrouter.ai/api/v1",
            "model": "qwen/qwen3-4b:free",
            "api_key": api_key,
            "timeout": 60,
        },
        "mcp": {
            "host": host,
            "port": port,
            "base_path": base_path,
            "require_token": require_token,
            "token": token,
        },
    }
    path = tmp_path / ("settings.toml" if fmt == "toml" else "settings.json")
    if fmt == "toml":
        toml = f"""
[llm]
api_base = \"{settings['llm']['api_base']}\"
model = \"{settings['llm']['model']}\"
api_key = \"{settings['llm']['api_key']}\"
timeout = {settings['llm']['timeout']}

[mcp]
host = \"{host}\"
port = {port}
base_path = \"{base_path}\"
require_token = {str(require_token).lower()}
token = \"{token}\"
"""
        path.write_text(toml)
    else:
        path.write_text(json.dumps(settings))
    return load_app_settings(path)
