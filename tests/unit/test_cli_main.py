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


def test_cli_main_runs_startup_dependency_check(monkeypatch):
    import argparse

    import importlib

    cli_main = importlib.import_module("app.cli.main")

    calls: list[str] = []

    class DummyParser:
        def parse_args(self, _argv):
            ns = argparse.Namespace()
            ns.settings = None
            ns.func = lambda _args, _ctx: 0
            return ns

    monkeypatch.setattr(cli_main, "configure_logging", lambda: calls.append("logging"))
    monkeypatch.setattr(cli_main, "log_missing_startup_dependencies", lambda: calls.append("deps"))
    monkeypatch.setattr(cli_main, "build_parser", lambda: DummyParser())
    monkeypatch.setattr(cli_main.ApplicationContext, "for_cli", lambda app_name: object())

    assert cli_main.main(["doc", "list", "."]) == 0
    assert calls[:2] == ["logging", "deps"]
