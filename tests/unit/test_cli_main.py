import subprocess
import sys


def test_python_module_cli_propagates_error_exit_code(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.cli",
            "item",
            "edit",
            str(tmp_path),
            "BAD",
            "--title",
            "x",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1


def test_python_module_cli_returns_zero_on_success(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "doc", "list", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
