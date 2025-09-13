from __future__ import annotations

import json
from pathlib import Path

from app.core.store import save
from app.settings import AppSettings
from app.cli import main


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


def run_cli(argv: list[str]):
    from app.cli import main
    return main(argv)


def test_cli_list(tmp_path, capsys):
    data = sample()
    save(tmp_path, data)
    run_cli(["list", str(tmp_path)])
    captured = capsys.readouterr().out
    assert "1" in captured


def test_cli_list_status_filter(tmp_path, capsys):
    data1 = sample()
    data2 = sample() | {"id": 2, "status": "approved"}
    save(tmp_path, data1)
    save(tmp_path, data2)
    run_cli(["list", str(tmp_path), "--status", "approved"])
    captured = capsys.readouterr().out
    assert "2" in captured
    assert "1" not in captured


def test_cli_show(tmp_path, capsys):
    data = sample()
    save(tmp_path, data)
    run_cli(["show", str(tmp_path), "1"])
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
    run_cli(["edit", str(tmp_path), str(file)])
    capsys.readouterr()
    run_cli(["show", str(tmp_path), "1"])
    captured = capsys.readouterr().out
    loaded = json.loads(captured)
    assert loaded["title"] == "New title"


def test_cli_delete(tmp_path, capsys):
    data = sample()
    save(tmp_path, data)
    main(["delete", str(tmp_path), "1"])
    captured = capsys.readouterr()
    assert "deleted" in captured.out
    assert not (tmp_path / "1.json").exists()


def test_cli_delete_invalid_id(tmp_path, capsys):
    data = sample()
    save(tmp_path, data)
    main(["delete", str(tmp_path), "2"])
    captured = capsys.readouterr()
    assert "not found" in captured.err
    assert (tmp_path / "1.json").exists()


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

    run_cli(["--settings", str(settings_file), "list", str(req_dir)])
    capsys.readouterr()
    assert called["path"] == str(settings_file)


def test_cli_check_uses_agent(tmp_path, monkeypatch, capsys):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}")

    called: dict[str, object] = {}

    class DummyAgent:
        def __init__(self, settings, confirm):
            called["settings"] = settings

        def check_llm(self):
            called["llm"] = True
            return {"status": "ok"}

        def check_tools(self):
            called["mcp"] = True
            return {"status": "ok"}

    from app import cli as cli_mod

    monkeypatch.setattr(cli_mod, "LocalAgent", DummyAgent)

    run_cli(["--settings", str(settings_file), "check"])
    captured = capsys.readouterr().out
    assert called["llm"] and called["mcp"]
    assert "llm" in captured and "mcp" in captured


def test_cli_add_invalid_json(tmp_path, capsys):
    req_dir = tmp_path / "reqs"
    req_dir.mkdir()
    file = tmp_path / "bad.json"
    file.write_text("{")
    run_cli(["add", str(req_dir), str(file)])
    captured = capsys.readouterr().out
    assert "Invalid JSON" in captured
    assert list(req_dir.iterdir()) == []


def test_cli_edit_invalid_json(tmp_path, capsys):
    req_dir = tmp_path / "reqs"
    req_dir.mkdir()
    data = sample()
    save(req_dir, data)
    file = tmp_path / "bad.json"
    file.write_text("{")
    run_cli(["edit", str(req_dir), str(file)])
    captured = capsys.readouterr().out
    assert "Invalid JSON" in captured
    run_cli(["show", str(req_dir), "1"])
    loaded = json.loads(capsys.readouterr().out)
    assert loaded["title"] == data["title"]


def test_cli_add_invalid_data(tmp_path, capsys):
    req_dir = tmp_path / "reqs"
    req_dir.mkdir()
    bad = sample() | {"status": "invalid"}
    file = tmp_path / "bad.json"
    file.write_text(json.dumps(bad))
    run_cli(["add", str(req_dir), str(file)])
    captured = capsys.readouterr().out
    assert "Invalid requirement data" in captured
    assert list(req_dir.iterdir()) == []


def test_cli_edit_invalid_data(tmp_path, capsys):
    req_dir = tmp_path / "reqs"
    req_dir.mkdir()
    data = sample()
    save(req_dir, data)
    bad = data | {"status": "invalid"}
    file = tmp_path / "bad.json"
    file.write_text(json.dumps(bad))
    run_cli(["edit", str(req_dir), str(file)])
    captured = capsys.readouterr().out
    assert "Invalid requirement data" in captured
    run_cli(["show", str(req_dir), "1"])
    loaded = json.loads(capsys.readouterr().out)
    assert loaded["status"] == data["status"]
