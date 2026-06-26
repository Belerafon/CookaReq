"""Read/write helpers for generated trace-index JSON cache files."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import TraceIndexConfig, is_index_stale
from .model import TraceIndex, TraceIssue

CACHE_RELATIVE_PATH = Path(".cookareq") / "trace_index.generated.json"


@dataclass(frozen=True)
class TraceIndexCacheRead:
    """Loaded cache payload with stale flag and diagnostics."""

    index: TraceIndex | None
    stale: bool
    issues: tuple[TraceIssue, ...] = ()


def cache_path(req_root: str | Path) -> Path:
    """Return the generated trace-index cache path for a Req root."""
    return Path(req_root) / CACHE_RELATIVE_PATH


def write_trace_index_cache(index: TraceIndex, req_root: str | Path) -> Path:
    """Atomically write ``index`` to ``Req/.cookareq/trace_index.generated.json``."""
    target = cache_path(req_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(index.to_dict(), ensure_ascii=False, indent=2) + "\n"
    fd = -1
    tmp_path: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix="trace_index.", suffix=".tmp", dir=target.parent
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            fd = -1
            tmp_file.write(payload)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_path, target)
    finally:
        if fd != -1:
            os.close(fd)
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
    return target


def read_trace_index_cache(path: str | Path) -> TraceIndex:
    """Read a trace-index cache JSON file."""
    with Path(path).open(encoding="utf-8") as fh:
        data = json.load(fh)
    return TraceIndex.from_dict(data)


def read_trace_index_cache_for_config(config: TraceIndexConfig) -> TraceIndexCacheRead:
    """Read the configured cache and report whether it is stale."""
    path = cache_path(config.req_root)
    try:
        index = read_trace_index_cache(path)
    except OSError as exc:
        return TraceIndexCacheRead(
            index=None,
            stale=True,
            issues=(
                TraceIssue(
                    code="INPUT_FILE_UNREADABLE",
                    severity="high",
                    message=f"Cannot read trace-index cache: {exc}",
                    path=path.as_posix(),
                ),
            ),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return TraceIndexCacheRead(
            index=None,
            stale=True,
            issues=(
                TraceIssue(
                    code="STALE_CACHE",
                    severity="warning",
                    message=f"Trace-index cache is invalid: {exc}",
                    path=path.as_posix(),
                ),
            ),
        )
    stale = is_index_stale(index, config)
    issues = ()
    if stale:
        issues = (
            TraceIssue(
                code="STALE_CACHE",
                severity="warning",
                message="Trace-index cache is stale",
                path=path.as_posix(),
            ),
        )
    return TraceIndexCacheRead(index=index, stale=stale, issues=issues)
