"""Runtime helpers for ensuring PDF font availability."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from typing import Iterator
from urllib.request import urlopen
from urllib.error import URLError

from importlib import resources
from importlib.resources.abc import Traversable

__all__ = [
    "FontPaths",
    "ensure_font_paths",
    "ensure_cached_fonts",
]


@dataclass(frozen=True)
class _FontSource:
    filename: str
    url: str
    sha256: str


@dataclass(frozen=True)
class FontPaths:
    """Concrete locations for the bundled PDF fonts."""

    regular: Path
    bold: Path


_FONT_SOURCES: dict[str, _FontSource] = {
    "regular": _FontSource(
        filename="NotoSans-Regular.ttf",
        url=(
            "https://github.com/notofonts/noto-fonts/raw/refs/heads/main/"
            "hinted/ttf/NotoSans/NotoSans-Regular.ttf"
        ),
        sha256="b85c38ecea8a7cfb39c24e395a4007474fa5a4fc864f6ee33309eb4948d232d5",
    ),
    "bold": _FontSource(
        filename="NotoSans-Bold.ttf",
        url=(
            "https://github.com/notofonts/noto-fonts/raw/refs/heads/main/"
            "hinted/ttf/NotoSans/NotoSans-Bold.ttf"
        ),
        sha256="c976e4b1b99edc88775377fcc21692ca4bfa46b6d6ca6522bfda505b28ff9d6a",
    ),
}

_CACHE_ENV_VAR = "COOKAREQ_FONT_CACHE_DIR"
_DEFAULT_CACHE = Path(os.getenv("XDG_CACHE_HOME", "")) if os.getenv("XDG_CACHE_HOME") else Path.home() / ".cache"
_DEFAULT_CACHE = _DEFAULT_CACHE / "cookareq" / "fonts"


def _calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _font_cache_dir() -> Path:
    override = os.getenv(_CACHE_ENV_VAR)
    if override:
        return Path(override)
    return _DEFAULT_CACHE


def _download_font(source: _FontSource, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(target.suffix + ".tmp")
    try:
        with urlopen(source.url) as response:  # nosec - trusted upstream
            data = response.read()
    except URLError as exc:  # pragma: no cover - network failures
        raise RuntimeError(f"Failed to download font from {source.url}") from exc
    tmp_path.write_bytes(data)
    actual_digest = hashlib.sha256(data).hexdigest()
    if actual_digest != source.sha256:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(
            "Downloaded font failed integrity check: "
            f"expected {source.sha256}, got {actual_digest}"
        )
    tmp_path.replace(target)


def ensure_cached_fonts() -> FontPaths:
    """Ensure fonts are available on disk and return their paths."""

    cache_dir = _font_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    resolved: dict[str, Path] = {}
    for key, source in _FONT_SOURCES.items():
        path = cache_dir / source.filename
        if path.exists():
            if _calculate_sha256(path) != source.sha256:
                path.unlink()
        if not path.exists():
            _download_font(source, path)
        resolved[key] = path

    return FontPaths(regular=resolved["regular"], bold=resolved["bold"])


def _packaged_font_traversable() -> Traversable | None:
    try:
        package = resources.files(__package__)
    except ModuleNotFoundError:  # pragma: no cover - defensive
        return None
    return package


@contextmanager
def ensure_font_paths() -> Iterator[FontPaths]:
    """Yield filesystem paths for fonts, downloading them when necessary."""

    package = _packaged_font_traversable()
    if package is not None:
        regular = package / _FONT_SOURCES["regular"].filename
        bold = package / _FONT_SOURCES["bold"].filename
        if regular.exists() and bold.exists():
            with ExitStack() as stack:
                yield FontPaths(
                    regular=Path(stack.enter_context(resources.as_file(regular))),
                    bold=Path(stack.enter_context(resources.as_file(bold))),
                )
            return

    cached = ensure_cached_fonts()
    yield cached
