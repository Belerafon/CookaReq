"""Diagnostics helpers for the GitLab migration shell wrapper."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from subprocess import CompletedProcess
from typing import Iterable, Protocol, Sequence


class CommandRunner(Protocol):
    """Callable that executes ``command`` and returns the outcome."""

    def __call__(self, command: Sequence[str]) -> "CommandResult | CompletedProcess":
        """Execute *command* and return the raw result."""


@dataclass(frozen=True)
class CommandResult:
    """Normalized information about a finished command."""

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    def is_successful(self) -> bool:
        """Return ``True`` when the command exited with code ``0``."""

        return self.returncode == 0


@dataclass(frozen=True)
class SkippedCommand:
    """Placeholder describing a diagnostic command that was not executed."""

    command: tuple[str, ...]
    reason: str


Result = CommandResult | SkippedCommand


@dataclass(frozen=True)
class DiagnosticCommand:
    """Description of a command participating in a diagnostic report."""

    name: str
    command: tuple[str, ...]
    requires_container: bool = False
    description: str | None = None


DEFAULT_COMMANDS: tuple[DiagnosticCommand, ...] = (
    DiagnosticCommand(
        "gitlab_ctl_status",
        ("gitlab-ctl", "status"),
        requires_container=True,
        description="Status of GitLab services inside the container.",
    ),
    DiagnosticCommand(
        "docker_ps",
        ("docker", "ps"),
        requires_container=True,
        description="List of running containers on the host.",
    ),
    DiagnosticCommand(
        "docker_inspect",
        ("docker", "inspect", "gitlab"),
        requires_container=True,
        description="Detailed container state when a GitLab container is available.",
    ),
    DiagnosticCommand(
        "system_memory",
        ("free", "-h"),
        description="Human-readable host memory statistics.",
    ),
    DiagnosticCommand(
        "system_disk",
        ("df", "-h"),
        description="Disk usage overview for all mounted filesystems.",
    ),
)


def run_command(command: Sequence[str]) -> CommandResult:
    """Execute *command* with :mod:`subprocess` and return a result object."""

    normalized = tuple(command)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as exc:  # pragma: no cover - exercised in integration tests
        return CommandResult(normalized, -1, "", str(exc))

    stdout = completed.stdout.strip() if isinstance(completed.stdout, str) else ""
    stderr = completed.stderr.strip() if isinstance(completed.stderr, str) else ""
    return CommandResult(normalized, completed.returncode, stdout, stderr)


def format_command(command: Sequence[str]) -> str:
    """Render *command* as a shell-escaped string suitable for logs."""

    return shlex.join(command)


def format_result(result: Result) -> str:
    """Return a concise human-readable representation of *result*."""

    if isinstance(result, SkippedCommand):
        return f"skipped ({result.reason})"

    parts: list[str] = []
    if result.stdout:
        parts.append(result.stdout)
    if result.stderr:
        parts.append(result.stderr)
    if not parts:
        parts.append(f"exit code {result.returncode}")
    return "\n".join(parts)


class DiagnosticsCollector:
    """Collect system diagnostics with optional container interaction."""

    _SKIP_REASON = "container diagnostics disabled"

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        commands: Iterable[DiagnosticCommand] | None = None,
        allow_container_checks: bool = False,
    ) -> None:
        self._runner: CommandRunner = runner or run_command
        self._commands: tuple[DiagnosticCommand, ...] = (
            tuple(commands) if commands is not None else DEFAULT_COMMANDS
        )
        self._allow_container_checks = allow_container_checks

    # ------------------------------------------------------------------
    def collect(self, *, include_container: bool | None = None) -> dict[str, Result]:
        """Execute configured diagnostics respecting container preferences."""

        allow = (
            self._allow_container_checks
            if include_container is None
            else include_container
        )
        report: dict[str, Result] = {}
        for item in self._commands:
            if item.requires_container and not allow:
                report[item.name] = SkippedCommand(item.command, self._SKIP_REASON)
                continue
            report[item.name] = self._execute(item.command)
        return report

    # ------------------------------------------------------------------
    def _execute(self, command: Sequence[str]) -> CommandResult:
        """Execute *command* and normalise the resulting object."""

        normalized = tuple(command)
        try:
            raw = self._runner(command)
        except Exception as exc:  # pragma: no cover - defensive programming
            return CommandResult(normalized, -1, "", str(exc))
        return self._coerce_result(normalized, raw)

    @staticmethod
    def _coerce_result(
        command: tuple[str, ...],
        raw: CommandResult | CompletedProcess,
    ) -> CommandResult:
        """Convert *raw* command output into :class:`CommandResult`."""

        if isinstance(raw, CommandResult):
            return raw
        if isinstance(raw, CompletedProcess):
            stdout = raw.stdout
            stderr = raw.stderr
            if not isinstance(stdout, str):
                stdout = stdout.decode() if stdout else ""
            if not isinstance(stderr, str):
                stderr = stderr.decode() if stderr else ""
            return CommandResult(command, raw.returncode, stdout.strip(), stderr.strip())
        raise TypeError(
            "Command runner must return CommandResult or subprocess.CompletedProcess",
        )
