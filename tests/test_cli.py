from __future__ import annotations

import json
from pathlib import Path

from app.cli import main
from app.core.store import save


def sample() -> dict:
    return {
        "id": "REQ-1",
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
    assert "REQ-1" in captured


def test_cli_show(tmp_path, capsys):
    data = sample()
    save(tmp_path, data)
    main(["show", str(tmp_path), "REQ-1"])
    captured = capsys.readouterr().out
    loaded = json.loads(captured)
    assert loaded["id"] == "REQ-1"


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
    main(["show", str(tmp_path), "REQ-1"])
    captured = capsys.readouterr().out
    loaded = json.loads(captured)
    assert loaded["title"] == "New title"
