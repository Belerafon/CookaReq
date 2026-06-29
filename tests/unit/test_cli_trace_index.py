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
        "view": "index",
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
    assert "Trace index: requirements=12" in out
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
def test_trace_index_export_writes_artifact_matrix_json_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], cli_context
) -> None:
    root = _copy_fixture(tmp_path)
    args = _args(root, "export", view="artifact-matrix")

    exit_code = commands.cmd_trace_index(args, cli_context)

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert set(payload) == {"requirements", "columns", "cells"}
    assert payload["requirements"][0]["rid"] == "LLR1"
    assert any(column["kind"] == "test_result" for column in payload["columns"])
    assert any(
        cell["rid"] == "LLR10"
        and cell["marker"] == "test_result"
        and cell["status"] == "passed"
        for cell in payload["cells"]
    )


@pytest.mark.unit
def test_trace_index_export_writes_artifact_matrix_csv_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], cli_context
) -> None:
    root = _copy_fixture(tmp_path)
    args = _args(root, "export", view="artifact-matrix", format="csv")

    exit_code = commands.cmd_trace_index(args, cli_context)

    out = capsys.readouterr().out
    assert exit_code == 0
    assert out.startswith("Requirement,Title,code:")
    assert "LLR10" in out
    assert "passed" in out


@pytest.mark.unit
def test_trace_index_export_writes_artifact_matrix_html_to_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], cli_context
) -> None:
    root = _copy_fixture(tmp_path)
    output = tmp_path / "out" / "artifact_matrix.html"
    args = _args(
        root,
        "export",
        view="artifact-matrix",
        format="html",
        output=str(output),
    )

    exit_code = commands.cmd_trace_index(args, cli_context)

    assert exit_code == 0
    assert capsys.readouterr().out == ""
    rendered = output.read_text(encoding="utf-8")
    assert "<table>" in rendered
    assert "Trace Index Artifact Matrix" in rendered
    assert "LLR10" in rendered
    assert "passed" in rendered

@pytest.mark.unit
def test_trace_index_export_writes_report_html_to_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], cli_context
) -> None:
    root = _copy_fixture(tmp_path)
    output = tmp_path / "out" / "trace_report.html"
    args = _args(root, "export", view="report", format="html", output=str(output))

    exit_code = commands.cmd_trace_index(args, cli_context)

    assert exit_code == 0
    assert capsys.readouterr().out == ""
    rendered = output.read_text(encoding="utf-8")
    assert "Trace Index Report" in rendered
    assert "Summary" in rendered
    assert "Diagnostics" in rendered
    assert "Artifact Matrix" in rendered
    assert "LLR10" in rendered


@pytest.mark.unit
def test_trace_index_export_rejects_non_html_report_view(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], cli_context
) -> None:
    root = _copy_fixture(tmp_path)
    args = _args(root, "export", view="report", format="json")

    exit_code = commands.cmd_trace_index(args, cli_context)

    assert exit_code == 1
    assert "supports only html" in capsys.readouterr().out

@pytest.mark.unit
def test_trace_index_export_rejects_non_json_index_view(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], cli_context
) -> None:
    root = _copy_fixture(tmp_path)
    args = _args(root, "export", format="csv")

    exit_code = commands.cmd_trace_index(args, cli_context)

    assert exit_code == 1
    assert "supports only json" in capsys.readouterr().out

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


@pytest.mark.unit
def test_trace_index_fixture_contains_v_pid_reg3_pilot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], cli_context
) -> None:
    root = _copy_fixture(tmp_path)
    args = _args(root, "export")

    exit_code = commands.cmd_trace_index(args, cli_context)

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["issues"] == []
    assert any(item["rid"] == "LLR3" for item in payload["requirements"])
    assert any(
        location["path"] == "Vsrc/V_pid_reg3.c" and location["rid"] == "LLR10"
        for location in payload["code_locations"]
    )
    assert any(
        item["test_id"] == "ТЕСТ-UT-V_PID_REG3-0003"
        and item["covers"] == ["LLR8", "LLR9", "LLR10"]
        for item in payload["test_cases"]
    )


@pytest.mark.unit
def test_trace_index_check_fail_on_high_allows_warning_only(tmp_path: Path, capsys: pytest.CaptureFixture[str], cli_context) -> None:
    root = tmp_path / "project"
    _write_minimal_req(root, verification="test")
    args = _args(root, "check", fail_on="high")

    exit_code = commands.cmd_trace_index(args, cli_context)

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "WARNING MISSING_TEST_FOR_LLR" in out


@pytest.mark.unit
def test_trace_index_check_fail_on_warning_rejects_warning_only(tmp_path: Path, capsys: pytest.CaptureFixture[str], cli_context) -> None:
    root = tmp_path / "project"
    _write_minimal_req(root, verification="test")
    args = _args(root, "check", fail_on="warning")

    exit_code = commands.cmd_trace_index(args, cli_context)

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "WARNING MISSING_TEST_FOR_LLR" in out


def _write_minimal_req(root: Path, *, verification: str) -> None:
    items = root / "Req" / "LLR" / "items"
    items.mkdir(parents=True)
    (root / "Req" / "LLR" / "document.json").write_text(
        '{"prefix": "LLR", "title": "Low"}\n', encoding="utf-8"
    )
    (items / "1.json").write_text(
        json.dumps(
            {
                "id": 1,
                "title": "Requirement 1",
                "statement": "Statement",
                "verification": verification,
                "verification_methods": [verification],
                "links": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
