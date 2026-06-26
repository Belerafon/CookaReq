"""Configuration and fingerprint helpers for trace-index scans."""
from __future__ import annotations

import fnmatch
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .model import GENERATOR_VERSION, SCHEMA_VERSION, TraceIndex

DEFAULT_SOURCE_GLOBS = ("Vsrc/**/*.c", "Vinclude/**/*.h")
DEFAULT_TEST_GLOBS = ("tests/test_*/src/**/*.c",)
DEFAULT_RESULT_GLOBS = ("tests/test_*/Build/test_results.txt",)
DEFAULT_EXCLUDE_GLOBS = ("Build/coverage/**", ".git/**", "**/.cookareq/**")


@dataclass(frozen=True)
class TraceIndexConfig:
    """Configuration describing trace-index input discovery."""

    project_root: str
    req_root: str
    source_globs: tuple[str, ...] = DEFAULT_SOURCE_GLOBS
    test_globs: tuple[str, ...] = DEFAULT_TEST_GLOBS
    result_globs: tuple[str, ...] = DEFAULT_RESULT_GLOBS
    exclude_globs: tuple[str, ...] = DEFAULT_EXCLUDE_GLOBS
    module_filter: str | None = None

    def __post_init__(self) -> None:
        project_root = _normalize_path(self.project_root)
        req_root = _normalize_path(self.req_root)
        object.__setattr__(self, "project_root", project_root)
        object.__setattr__(self, "req_root", req_root)
        object.__setattr__(self, "source_globs", tuple(self.source_globs))
        object.__setattr__(self, "test_globs", tuple(self.test_globs))
        object.__setattr__(self, "result_globs", tuple(self.result_globs))
        object.__setattr__(self, "exclude_globs", tuple(self.exclude_globs))

    @classmethod
    def from_conventions(
        cls,
        req_root: str | Path,
        *,
        project_root: str | Path | None = None,
        source_globs: tuple[str, ...] | None = None,
        test_globs: tuple[str, ...] | None = None,
        result_globs: tuple[str, ...] | None = None,
        exclude_globs: tuple[str, ...] | None = None,
        module_filter: str | None = None,
    ) -> TraceIndexConfig:
        """Build config using project conventions and optional overrides."""
        req_path = Path(req_root)
        project_path = Path(project_root) if project_root is not None else req_path.parent
        return cls(
            project_root=project_path.as_posix(),
            req_root=req_path.as_posix(),
            source_globs=DEFAULT_SOURCE_GLOBS if source_globs is None else source_globs,
            test_globs=DEFAULT_TEST_GLOBS if test_globs is None else test_globs,
            result_globs=DEFAULT_RESULT_GLOBS if result_globs is None else result_globs,
            exclude_globs=DEFAULT_EXCLUDE_GLOBS if exclude_globs is None else exclude_globs,
            module_filter=module_filter,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TraceIndexConfig:
        """Restore a config from JSON-compatible data."""
        return cls(
            project_root=data["project_root"],
            req_root=data["req_root"],
            source_globs=tuple(data.get("source_globs", DEFAULT_SOURCE_GLOBS)),
            test_globs=tuple(data.get("test_globs", DEFAULT_TEST_GLOBS)),
            result_globs=tuple(data.get("result_globs", DEFAULT_RESULT_GLOBS)),
            exclude_globs=tuple(data.get("exclude_globs", DEFAULT_EXCLUDE_GLOBS)),
            module_filter=data.get("module_filter"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-compatible representation."""
        data = asdict(self)
        data["source_globs"] = list(self.source_globs)
        data["test_globs"] = list(self.test_globs)
        data["result_globs"] = list(self.result_globs)
        data["exclude_globs"] = list(self.exclude_globs)
        return data


def config_hash(config: TraceIndexConfig) -> str:
    """Return a deterministic hash for a trace-index config."""
    return _sha256_json(config.to_dict())


def collect_input_files(config: TraceIndexConfig) -> tuple[str, ...]:
    """Return sorted project-relative files matched by configured globs."""
    root = Path(config.project_root)
    matched: set[str] = set()
    for pattern in (*config.source_globs, *config.test_globs, *config.result_globs):
        for path in root.glob(pattern):
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                if not _is_excluded(relative, config.exclude_globs):
                    matched.add(relative)
    req_root = Path(config.req_root)
    if req_root.exists():
        req_base = req_root if req_root.is_absolute() else root / req_root
        for path in req_base.rglob("*.json"):
            if path.is_file():
                try:
                    relative = path.relative_to(root).as_posix()
                except ValueError:
                    relative = path.as_posix()
                if not _is_excluded(relative, config.exclude_globs):
                    matched.add(relative)
    return tuple(sorted(matched))


def input_fingerprint(config: TraceIndexConfig) -> str:
    """Hash matched input file paths and contents for stale detection."""
    root = Path(config.project_root)
    entries = []
    for relative in collect_input_files(config):
        path = root / relative
        try:
            content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            content_hash = "UNREADABLE"
        entries.append({"path": relative, "sha256": content_hash})
    return _sha256_json(
        {
            "schema_version": SCHEMA_VERSION,
            "generator_version": GENERATOR_VERSION,
            "inputs": entries,
        }
    )


def cache_metadata(config: TraceIndexConfig) -> dict[str, str | int]:
    """Build schema/config/fingerprint metadata for a generated cache."""
    return {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "project_root": config.project_root,
        "req_root": config.req_root,
        "config_hash": config_hash(config),
        "input_fingerprint": input_fingerprint(config),
    }


def is_index_stale(index: TraceIndex, config: TraceIndexConfig) -> bool:
    """Return whether an index no longer matches schema, config or inputs."""
    metadata = cache_metadata(config)
    return any(
        (
            index.schema_version != metadata["schema_version"],
            index.generator_version != metadata["generator_version"],
            index.project_root != metadata["project_root"],
            index.req_root != metadata["req_root"],
            index.config_hash != metadata["config_hash"],
            index.input_fingerprint != metadata["input_fingerprint"],
        )
    )


def _is_excluded(relative_path: str, exclude_globs: tuple[str, ...]) -> bool:
    return "/.cookareq/" in f"/{relative_path}" or any(
        fnmatch.fnmatch(relative_path, pattern) for pattern in exclude_globs
    )


def _sha256_json(data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_path(path: str) -> str:
    return Path(path).as_posix()
