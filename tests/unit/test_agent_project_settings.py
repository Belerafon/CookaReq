import json

from app.ui.agent_chat_panel.project_settings import (
    AgentProjectSettings,
    load_agent_project_settings,
    save_agent_project_settings,
)


def test_agent_project_settings_roundtrip(tmp_path):
    settings_path = tmp_path / "agent_settings.json"

    # missing file -> defaults
    settings = load_agent_project_settings(settings_path)
    assert settings.custom_system_prompt == ""
    assert settings.documents_path == ""

    # corrupted payload -> defaults
    settings_path.write_text("not json", encoding="utf-8")
    settings = load_agent_project_settings(settings_path)
    assert settings.custom_system_prompt == ""
    assert settings.documents_path == ""

    desired = AgentProjectSettings(
        custom_system_prompt="  Keep naming short  ",
        documents_path="  docs/Гайды  ",
    )
    save_agent_project_settings(settings_path, desired)

    loaded = load_agent_project_settings(settings_path)
    assert loaded.custom_system_prompt == "Keep naming short"
    assert loaded.documents_path == "docs/Гайды"


def test_agent_project_settings_loads_version_one_payload(tmp_path):
    settings_path = tmp_path / "agent_settings.json"
    payload = {
        "version": 1,
        "custom_system_prompt": "Legacy prompt",
        "documents_path": 123,
    }
    settings_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_agent_project_settings(settings_path)
    assert loaded.custom_system_prompt == "Legacy prompt"
    assert loaded.documents_path == ""


def test_agent_project_settings_handles_unicode_paths(tmp_path):
    payload = {
        "version": 4,
        "custom_system_prompt": "",
        "documents_path": "  ../документы/Рабочие материалы  ",
    }
    settings_path = tmp_path / "agent_settings.json"
    settings_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_agent_project_settings(settings_path)
    assert loaded.documents_path == "../документы/Рабочие материалы"
