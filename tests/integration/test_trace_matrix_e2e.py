"""End-to-end checks for trace matrix generation on demo requirements."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def _run_trace_json(root: Path, *, rows: str, columns: str, direction: str) -> dict[str, object]:
    command = [
        "python3",
        "-m",
        "app.cli",
        "trace",
        str(root),
        "--rows",
        rows,
        "--columns",
        columns,
        "--direction",
        direction,
        "--format",
        "matrix-json",
    ]
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    stdout = completed.stdout
    payload_start = stdout.find("{")
    assert payload_start >= 0, stdout
    return json.loads(stdout[payload_start:])


@pytest.mark.integration
def test_trace_matrix_e2e_demo_requirements_direction_modes(tmp_path: Path) -> None:
    source = Path("requirements")
    root = tmp_path / "requirements"
    shutil.copytree(source, root)

    child_to_parent = _run_trace_json(
        root,
        rows="HLR",
        columns="SYS",
        direction="child-to-parent",
    )
    parent_to_child = _run_trace_json(
        root,
        rows="SYS",
        columns="HLR",
        direction="parent-to-child",
    )
    mismatched = _run_trace_json(
        root,
        rows="SYS",
        columns="HLR",
        direction="child-to-parent",
    )

    assert child_to_parent["summary"]["linked_pairs"] == 6
    assert parent_to_child["summary"]["linked_pairs"] == 6
    assert mismatched["summary"]["linked_pairs"] == 0
