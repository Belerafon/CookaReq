"""Read-only trace-index data model and JSON schema helpers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, ClassVar, Self

SCHEMA_VERSION = 1
GENERATOR = "CookaReq trace-index"
GENERATOR_VERSION = "0.1.0"


def _clean_path(path: str) -> str:
    """Normalize a persisted path to project-relative POSIX form."""
    return str(PurePosixPath(path.replace("\\", "/")))


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class TraceRequirementRef:
    """Requirement snapshot used by the external evidence index."""

    rid: str
    title: str = ""
    document: str = ""
    stable_key: str = ""

    def __post_init__(self) -> None:
        if not self.stable_key:
            object.__setattr__(self, "stable_key", self.rid)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CodeLocation:
    """A source-code marker that claims coverage for one requirement."""

    rid: str
    path: str
    line_start: int
    line_end: int
    marker_text: str
    marker_ordinal: int
    symbol: str | None = None
    stable_key: str = ""

    def __post_init__(self) -> None:
        normalized_path = _clean_path(self.path)
        object.__setattr__(self, "path", normalized_path)
        if not self.stable_key:
            object.__setattr__(
                self,
                "stable_key",
                make_code_location_key(normalized_path, self.rid, self.marker_ordinal),
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TestCaseRef:
    """A test source marker or recognized test-case declaration."""

    test_id: str
    path: str
    line_start: int
    line_end: int
    covers: tuple[str, ...] = ()
    marker_text: str = ""
    stable_key: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _clean_path(self.path))
        object.__setattr__(self, "covers", tuple(self.covers))
        if not self.stable_key:
            object.__setattr__(self, "stable_key", self.test_id)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["covers"] = list(self.covers)
        return result


@dataclass(frozen=True)
class TestRunRef:
    """One parsed test execution run."""

    run_id: str
    result_file: str
    env: str = ""
    date_utc: str = ""
    stable_key: str = ""

    def __post_init__(self) -> None:
        normalized_file = _clean_path(self.result_file)
        object.__setattr__(self, "result_file", normalized_file)
        if not self.stable_key:
            object.__setattr__(
                self, "stable_key", make_test_run_key(self.run_id, normalized_file)
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TestResultRef:
    """Result of one test case within a test run."""

    run_id: str
    test_id: str
    result_file: str
    block_ordinal: int
    raw_status: str
    normalized_status: str
    covers: tuple[str, ...] = ()
    expected: str = ""
    criterion: str = ""
    diagnostics: tuple[str, ...] = ()
    line_start: int | None = None
    line_end: int | None = None
    stable_key: str = ""

    def __post_init__(self) -> None:
        normalized_file = _clean_path(self.result_file)
        object.__setattr__(self, "result_file", normalized_file)
        object.__setattr__(self, "covers", tuple(self.covers))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        if not self.stable_key:
            object.__setattr__(
                self,
                "stable_key",
                make_test_result_key(
                    self.run_id, self.test_id, normalized_file, self.block_ordinal
                ),
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["covers"] = list(self.covers)
        result["diagnostics"] = list(self.diagnostics)
        return result


@dataclass(frozen=True)
class TraceIssue:
    """Stable diagnostic emitted while building the trace index."""

    code: str
    severity: str
    message: str
    path: str = ""
    line: int | None = None
    rid: str | None = None
    test_id: str | None = None

    def __post_init__(self) -> None:
        if self.path:
            object.__setattr__(self, "path", _clean_path(self.path))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TraceIndex:
    """Generated read-only graph of requirements and external evidence."""

    project_root: str
    req_root: str
    config_hash: str
    input_fingerprint: str
    requirements: tuple[TraceRequirementRef, ...] = ()
    code_locations: tuple[CodeLocation, ...] = ()
    test_cases: tuple[TestCaseRef, ...] = ()
    test_runs: tuple[TestRunRef, ...] = ()
    test_results: tuple[TestResultRef, ...] = ()
    issues: tuple[TraceIssue, ...] = ()
    schema_version: int = SCHEMA_VERSION
    generator: str = GENERATOR
    generator_version: str = GENERATOR_VERSION
    generated_at_utc: str = field(default_factory=_utc_now_iso)

    TOP_LEVEL_FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "generator",
        "generator_version",
        "project_root",
        "req_root",
        "config_hash",
        "input_fingerprint",
        "generated_at_utc",
        "requirements",
        "code_locations",
        "test_cases",
        "test_runs",
        "test_results",
        "issues",
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_root", _clean_path(self.project_root))
        object.__setattr__(self, "req_root", _clean_path(self.req_root))
        object.__setattr__(self, "requirements", tuple(self.requirements))
        object.__setattr__(self, "code_locations", tuple(self.code_locations))
        object.__setattr__(self, "test_cases", tuple(self.test_cases))
        object.__setattr__(self, "test_runs", tuple(self.test_runs))
        object.__setattr__(self, "test_results", tuple(self.test_results))
        object.__setattr__(self, "issues", tuple(self.issues))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            schema_version=data["schema_version"],
            generator=data.get("generator", GENERATOR),
            generator_version=data["generator_version"],
            project_root=data["project_root"],
            req_root=data["req_root"],
            config_hash=data["config_hash"],
            input_fingerprint=data["input_fingerprint"],
            generated_at_utc=data["generated_at_utc"],
            requirements=tuple(
                TraceRequirementRef.from_dict(item)
                for item in data.get("requirements", [])
            ),
            code_locations=tuple(
                CodeLocation.from_dict(item) for item in data.get("code_locations", [])
            ),
            test_cases=tuple(
                TestCaseRef.from_dict(item) for item in data.get("test_cases", [])
            ),
            test_runs=tuple(
                TestRunRef.from_dict(item) for item in data.get("test_runs", [])
            ),
            test_results=tuple(
                TestResultRef.from_dict(item) for item in data.get("test_results", [])
            ),
            issues=tuple(TraceIssue.from_dict(item) for item in data.get("issues", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "schema_version": self.schema_version,
            "generator": self.generator,
            "generator_version": self.generator_version,
            "project_root": self.project_root,
            "req_root": self.req_root,
            "config_hash": self.config_hash,
            "input_fingerprint": self.input_fingerprint,
            "generated_at_utc": self.generated_at_utc,
            "requirements": [
                item.to_dict()
                for item in sorted(self.requirements, key=lambda x: x.stable_key)
            ],
            "code_locations": [
                item.to_dict()
                for item in sorted(self.code_locations, key=lambda x: x.stable_key)
            ],
            "test_cases": [
                item.to_dict()
                for item in sorted(self.test_cases, key=lambda x: x.stable_key)
            ],
            "test_runs": [
                item.to_dict()
                for item in sorted(self.test_runs, key=lambda x: x.stable_key)
            ],
            "test_results": [
                item.to_dict()
                for item in sorted(self.test_results, key=lambda x: x.stable_key)
            ],
            "issues": [
                item.to_dict()
                for item in sorted(
                    self.issues,
                    key=lambda x: (
                        x.severity,
                        x.code,
                        x.path,
                        x.line or 0,
                        x.rid or "",
                        x.test_id or "",
                    ),
                )
            ],
        }
        return {
            field_name: data[field_name] for field_name in self.TOP_LEVEL_FIELDS
        }


def make_code_location_key(path: str, rid: str, marker_ordinal: int) -> str:
    """Build a stable key for one code marker, independent of line numbers."""
    return f"{_clean_path(path)}::{rid}::marker-{marker_ordinal:04d}"


def make_test_run_key(run_id: str, result_file: str) -> str:
    """Build a stable key for one test run reference."""
    return f"{run_id}::{_clean_path(result_file)}"


def make_test_result_key(
    run_id: str, test_id: str, result_file: str, block_ordinal: int
) -> str:
    """Build a stable key for one test result block."""
    return (
        f"{run_id}::{test_id}::{_clean_path(result_file)}"
        f"::block-{block_ordinal:04d}"
    )

# Prevent pytest from mistaking domain dataclasses for test containers when
# they are imported into test modules.
TestCaseRef.__test__ = False
TestRunRef.__test__ = False
TestResultRef.__test__ = False
