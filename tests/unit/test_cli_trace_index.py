import argparse
import json
import shutil
from pathlib import Path

import pytest

from app.cli import commands

FIXTURE_ROOT = Path("tests/fixtures/trace_index_project")


def _copy_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "trace_index_project"
    shutil.copytree(FIXTURE_ROOT, target)
    return target


def _args(root: Path, command: str, **overrides: object) -> argparse.Namespace:
    defaults = {
        "trace_index_command": command,
        "req_root": str(root / "Req"),
        "project_root": str(root),
        "module": None,
        "source_glob": None,
        "test_glob": None,
        "result_glob": None,
        "exclude_glob": ["Vsrc/broken_*"],
        "fail_on": "high",
        "format": "json",
        "output": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.mark.unit
def test_trace_index_refresh_writes_cache(tmp_path: Path, capsys: pytest.CaptureFixture[str], cli_context) -> None:
    root = _copy_fixture(tmp_path)
    args = _args(root, "refresh")

    exit_code = commands.cmd_trace_index(args, cli_context)

    out = capsys.readouterr().out
    cache_path = root / "Req" / ".cookareq" / "trace_index.generated.json"
    assert exit_code == 0
    assert cache_path.exists()
    assert "Trace index: requirements=2" in out
    assert f"Cache: {cache_path.as_posix()}" in out


@pytest.mark.unit
def test_trace_index_check_returns_zero_without_high_issues(tmp_path: Path, capsys: pytest.CaptureFixture[str], cli_context) -> None:
    root = _copy_fixture(tmp_path)
    args = _args(root, "check")

    exit_code = commands.cmd_trace_index(args, cli_context)

    assert exit_code == 0
    assert "Issues: high=0 warning=0 info=0" in capsys.readouterr().out


@pytest.mark.unit
def test_trace_index_check_returns_nonzero_for_high_issue(tmp_path: Path, capsys: pytest.CaptureFixture[str], cli_context) -> None:
    root = _copy_fixture(tmp_path)
    args = _args(root, "check", exclude_glob=[])

    exit_code = commands.cmd_trace_index(args, cli_context)

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "HIGH INVALID_MARKER" in out


@pytest.mark.unit
def test_trace_index_export_writes_json_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str], cli_context) -> None:
    root = _copy_fixture(tmp_path)
    args = _args(root, "export")

    exit_code = commands.cmd_trace_index(args, cli_context)

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["schema_version"] == 1
    assert payload["requirements"][0]["rid"] == "LLR1"
    assert payload["issues"] == []


@pytest.mark.unit
def test_trace_index_export_writes_json_file(tmp_path: Path, capsys: pytest.CaptureFixture[str], cli_context) -> None:
    root = _copy_fixture(tmp_path)
    output = tmp_path / "out" / "trace_index.json"
    args = _args(root, "export", output=str(output))

    exit_code = commands.cmd_trace_index(args, cli_context)

    assert exit_code == 0
    assert capsys.readouterr().out == ""
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["test_cases"][0]["test_id"] == "ТЕСТ-UT-DEMO-0001"
