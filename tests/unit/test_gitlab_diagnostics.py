from __future__ import annotations

from subprocess import CompletedProcess

import pytest

from gitlab_migrate.diagnostics import (
    CommandResult,
    DiagnosticCommand,
    DiagnosticsCollector,
    SkippedCommand,
)


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command: list[str] | tuple[str, ...]) -> CommandResult:
        normalized = tuple(command)
        self.calls.append(normalized)
        return CommandResult(normalized, 0, "ok", "")


@pytest.fixture
def sample_commands() -> list[DiagnosticCommand]:
    return [
        DiagnosticCommand(
            "container_status",
            ("gitlab-ctl", "status"),
            requires_container=True,
        ),
        DiagnosticCommand("host_memory", ("free", "-h")),
    ]


def test_container_checks_disabled_by_default(sample_commands: list[DiagnosticCommand]) -> None:
    runner = RecordingRunner()
    collector = DiagnosticsCollector(runner=runner, commands=sample_commands)

    results = collector.collect()

    assert runner.calls == [("free", "-h")]
    skipped = results["container_status"]
    assert isinstance(skipped, SkippedCommand)
    assert skipped.reason == "container diagnostics disabled"


def test_container_checks_can_be_requested(sample_commands: list[DiagnosticCommand]) -> None:
    runner = RecordingRunner()
    collector = DiagnosticsCollector(runner=runner, commands=sample_commands)

    results = collector.collect(include_container=True)

    assert runner.calls == [
        ("gitlab-ctl", "status"),
        ("free", "-h"),
    ]
    status = results["container_status"]
    assert isinstance(status, CommandResult)
    assert status.is_successful()


def test_default_allowance_can_be_overridden(sample_commands: list[DiagnosticCommand]) -> None:
    runner = RecordingRunner()
    collector = DiagnosticsCollector(
        runner=runner, commands=sample_commands, allow_container_checks=True
    )

    runner.calls.clear()
    collector.collect(include_container=False)
    assert runner.calls == [("free", "-h")]


def test_runner_exception_is_converted_to_result() -> None:
    def broken_runner(command: list[str]) -> CommandResult:  # pragma: no cover - stub
        raise RuntimeError("boom")

    collector = DiagnosticsCollector(
        runner=broken_runner,
        commands=[
            DiagnosticCommand(
                "container_status",
                ("gitlab-ctl", "status"),
                requires_container=True,
            )
        ],
        allow_container_checks=True,
    )

    result = collector.collect()["container_status"]
    assert isinstance(result, CommandResult)
    assert result.returncode == -1
    assert "boom" in result.stderr


def test_completed_process_is_normalised(sample_commands: list[DiagnosticCommand]) -> None:
    def completed_runner(command: list[str]) -> CompletedProcess[str]:
        return CompletedProcess(command, 0, stdout="ready", stderr="")

    collector = DiagnosticsCollector(
        runner=completed_runner,
        commands=sample_commands,
        allow_container_checks=True,
    )

    result = collector.collect()["container_status"]
    assert isinstance(result, CommandResult)
    assert result.stdout == "ready"
