from __future__ import annotations

import json
from pathlib import Path

from app.cli import main
from app.core.store import save
from app.settings import AppSettings


def sample() -> dict:
    return {
        "id": 1,
        "title": "Title",
        "statement": "Statement",
        "type": "requirement",
        "status": "draft",
        "owner": "user",
        "priority": "medium",
        "source": "spec",
        "verification": "analysis",
        "revision": 1,
    }


def test_cli_list(tmp_path, capsys):
    data = sample()
    save(tmp_path, data)
    main(["list", str(tmp_path)])
    captured = capsys.readouterr().out
    assert "1" in captured


def test_cli_show(tmp_path, capsys):
    data = sample()
    save(tmp_path, data)
    main(["show", str(tmp_path), "1"])
    captured = capsys.readouterr().out
    loaded = json.loads(captured)
    assert loaded["id"] == 1


def test_cli_edit(tmp_path, capsys):
    data = sample()
    save(tmp_path, data)
    updated = data | {"title": "New title"}
    src = tmp_path / "src"
    src.mkdir()
    file = src / "upd.json"
    file.write_text(json.dumps(updated))
    main(["edit", str(tmp_path), str(file)])
    capsys.readouterr()
    main(["show", str(tmp_path), "1"])
    captured = capsys.readouterr().out
    loaded = json.loads(captured)
    assert loaded["title"] == "New title"


def test_cli_settings_flag(tmp_path, monkeypatch, capsys):
    req_dir = tmp_path / "reqs"
    req_dir.mkdir()
    data = sample()
    save(req_dir, data)
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}")

    called = {}

    def fake_loader(path):
        called["path"] = path
        return AppSettings()

    from app import cli as cli_mod

    monkeypatch.setattr(cli_mod, "load_app_settings", fake_loader)
    monkeypatch.setattr(cli_mod, "AppSettings", AppSettings)

    main(["--settings", str(settings_file), "list", str(req_dir)])
    capsys.readouterr()
    assert called["path"] == str(settings_file)
