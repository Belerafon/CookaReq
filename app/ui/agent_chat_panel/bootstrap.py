"""Bootstrap helpers for agent chat history stores."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import time

from .debug_logging import emit_history_debug, elapsed_ns, get_history_logger
from .paths import _normalize_history_path, history_path_for_documents

logger = get_history_logger("bootstrap")


SeedKind = Literal["archive", "file"]


@dataclass(frozen=True, slots=True)
class HistoryBootstrapResult:
    """Describe the outcome of preparing a chat history for use."""

    path: Path
    seed_source: Path | None = None
    seed_kind: SeedKind | None = None


def prepare_history_for_directory(
    base_directory: Path | str | None,
) -> HistoryBootstrapResult:
    """Return a ready-to-use history path for *base_directory*.

    When *base_directory* contains a packaged demo history, the archive is
    extracted into the canonical ``.cookareq/agent_chats.sqlite`` location on
    demand. The helper performs the extraction only when the target file is
    missing so repeated invocations remain inexpensive.
    """

    start_ns = time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
    history_path = history_path_for_documents(base_directory)
    emit_history_debug(
        logger,
        "bootstrap.prepare.start",
        base_directory=base_directory,
        history_path=history_path,
    )
    if base_directory is None:
        emit_history_debug(
            logger,
            "bootstrap.prepare.no_base_directory",
            history_path=history_path,
            elapsed_ns=elapsed_ns(start_ns),
        )
        return HistoryBootstrapResult(path=history_path)

    base_path = _normalize_history_path(base_directory)
    if history_path.exists():
        emit_history_debug(
            logger,
            "bootstrap.prepare.existing_history",
            history_path=history_path,
            elapsed_ns=elapsed_ns(start_ns),
        )
        return HistoryBootstrapResult(path=history_path)

    seed = _find_seed_file(base_path)
    if seed is not None:
        emit_history_debug(
            logger,
            "bootstrap.prepare.seed_file.detected",
            seed=seed,
            history_path=history_path,
        )
        try:
            _copy_seed_file(seed, history_path)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to copy seeded chat history from %s to %s", seed, history_path
            )
        else:
            emit_history_debug(
                logger,
                "bootstrap.prepare.seed_file.copied",
                seed=seed,
                history_path=history_path,
                elapsed_ns=elapsed_ns(start_ns),
            )
            return HistoryBootstrapResult(
                path=history_path, seed_source=seed, seed_kind="file"
            )

    archive = _find_seed_archive(base_path)
    if archive is not None:
        emit_history_debug(
            logger,
            "bootstrap.prepare.seed_archive.detected",
            archive=archive,
            history_path=history_path,
        )
        try:
            _extract_seed_archive(archive, history_path)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to extract seeded chat history from %s to %s",
                archive,
                history_path,
            )
        else:
            emit_history_debug(
                logger,
                "bootstrap.prepare.seed_archive.extracted",
                archive=archive,
                history_path=history_path,
                elapsed_ns=elapsed_ns(start_ns),
            )
            return HistoryBootstrapResult(
                path=history_path, seed_source=archive, seed_kind="archive"
            )

    emit_history_debug(
        logger,
        "bootstrap.prepare.no_seed",
        history_path=history_path,
        elapsed_ns=elapsed_ns(start_ns),
    )
    return HistoryBootstrapResult(path=history_path)


def _find_seed_file(base_path: Path) -> Path | None:
    candidates = (
        base_path / "agent_chats.sqlite",
        base_path / ".cookareq" / "agent_chats.sqlite",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _find_seed_archive(base_path: Path) -> Path | None:
    candidates = (
        base_path / "agent_chats.zip",
        base_path / ".cookareq" / "agent_chats.zip",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _copy_seed_file(source: Path, target: Path) -> None:
    emit_history_debug(
        logger,
        "bootstrap.copy_seed.start",
        source=source,
        target=target,
    )
    start_ns = time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
    if source == target:
        emit_history_debug(
            logger,
            "bootstrap.copy_seed.skip_same_path",
            source=source,
            target=target,
            elapsed_ns=elapsed_ns(start_ns),
        )
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", delete=False, dir=str(target.parent), suffix=".tmp"
    ) as handle:
        temp_path = Path(handle.name)
        with source.open("rb") as src:
            shutil.copyfileobj(src, handle)
    os.replace(temp_path, target)
    emit_history_debug(
        logger,
        "bootstrap.copy_seed.finish",
        source=source,
        target=target,
        elapsed_ns=elapsed_ns(start_ns),
    )


def _extract_seed_archive(archive: Path, target: Path) -> None:
    emit_history_debug(
        logger,
        "bootstrap.extract_seed.start",
        archive=archive,
        target=target,
    )
    start_ns = time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as payload:
        member = _resolve_archive_member(payload)
        if member is None:
            raise ValueError(
                f"Archive {archive} does not contain a chat history payload"
            )
        emit_history_debug(
            logger,
            "bootstrap.extract_seed.member_resolved",
            archive=archive,
            target=target,
            member=member,
        )
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, dir=str(target.parent), suffix=".tmp"
        ) as handle:
            temp_path = Path(handle.name)
            with payload.open(member, "r") as stream:
                shutil.copyfileobj(stream, handle)
    os.replace(temp_path, target)
    emit_history_debug(
        logger,
        "bootstrap.extract_seed.finish",
        archive=archive,
        target=target,
        member=member,
        elapsed_ns=elapsed_ns(start_ns),
    )


def _resolve_archive_member(archive: zipfile.ZipFile) -> str | None:
    for name in archive.namelist():
        normalized = name.rstrip("/")
        if not normalized:
            continue
        if Path(normalized).name.endswith(".sqlite"):
            emit_history_debug(
                logger,
                "bootstrap.extract_seed.member_candidate",
                archive=getattr(archive, "filename", None),
                member=name,
            )
            return name
    emit_history_debug(
        logger,
        "bootstrap.extract_seed.member_missing",
        archive=getattr(archive, "filename", None),
    )
    return None


__all__ = [
    "HistoryBootstrapResult",
    "prepare_history_for_directory",
]
