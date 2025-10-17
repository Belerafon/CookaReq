"""Utilities for exposing curated views over user-provided documentation."""

from __future__ import annotations

import codecs
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from charset_normalizer import from_bytes

from ..llm.tokenizer import TokenCountResult, combine_token_counts, count_text_tokens

DEFAULT_MAX_READ_BYTES = 10_240
MAX_ALLOWED_READ_BYTES = 524_288
LARGE_FILE_TOKEN_ESTIMATE_BYTES = 1_048_576
TOKEN_COUNT_SAMPLE_BYTES = 102_400
ENCODING_DETECTION_SAMPLE_BYTES = 1_048_576
_GOOD_UNICODE_CATEGORIES = {
    "Lu",
    "Ll",
    "Lt",
    "Lm",
    "Lo",
    "Nd",
    "Nl",
    "No",
    "Zs",
    "Po",
    "Pc",
    "Pd",
    "Ps",
    "Pe",
    "Pi",
    "Pf",
    "Sc",
    "Sm",
}
_LANGUAGE_ENCODING_PRIORITIES: dict[str, tuple[str, ...]] = {
    "russian": ("utf-8", "utf_8", "cp1251", "koi8_r", "cp866", "cp1125"),
    "ukrainian": ("utf-8", "utf_8", "cp1251", "koi8_r", "cp866"),
    "belarusian": ("utf-8", "utf_8", "cp1251", "koi8_r", "cp866"),
    "bulgarian": ("utf-8", "utf_8", "cp1251", "koi8_r", "cp866"),
    "serbian": ("utf-8", "utf_8", "cp1251", "cp1250", "latin_1"),
    "macedonian": ("utf-8", "utf_8", "cp1251"),
    "english": ("utf-8", "utf_8", "cp1252", "latin_1", "ascii"),
    "german": ("utf-8", "utf_8", "cp1252", "latin_1"),
    "french": ("utf-8", "utf_8", "cp1252", "latin_1"),
    "spanish": ("utf-8", "utf_8", "cp1252", "latin_1"),
    "portuguese": ("utf-8", "utf_8", "cp1252", "latin_1"),
    "italian": ("utf-8", "utf_8", "cp1252", "latin_1"),
    "polish": ("utf-8", "utf_8", "cp1250", "latin_2"),
    "czech": ("utf-8", "utf_8", "cp1250", "latin_2"),
    "slovak": ("utf-8", "utf_8", "cp1250", "latin_2"),
    "hungarian": ("utf-8", "utf_8", "cp1250", "latin_2"),
    "greek": ("utf-8", "utf_8", "cp1253"),
    "hebrew": ("utf-8", "utf_8", "cp1255"),
    "arabic": ("utf-8", "utf_8", "cp1256"),
    "thai": ("utf-8", "utf_8", "cp874"),
}


def normalise_text_encoding(value: str | None) -> str:
    """Return a canonical encoding name, defaulting to UTF-8."""

    if value is None:
        return "utf-8"
    text = str(value).strip()
    if not text:
        return "utf-8"
    try:
        return codecs.lookup(text).name
    except LookupError as exc:  # pragma: no cover - passthrough for callers
        raise LookupError(f"Unknown encoding: {value}") from exc


def detect_file_encoding(path: Path) -> EncodingDetectionResult:
    """Inspect ``path`` and return the most likely text encoding."""

    fallback = normalise_text_encoding("utf-8")
    try:
        with path.open("rb") as stream:
            sample = stream.read(ENCODING_DETECTION_SAMPLE_BYTES)
    except OSError:
        return EncodingDetectionResult(fallback, None, "fallback")
    if not sample:
        return EncodingDetectionResult(fallback, None, "empty")

    try:
        candidates = list(from_bytes(sample))
    except Exception:  # pragma: no cover - defensive
        return EncodingDetectionResult(fallback, None, "fallback")

    best_encoding: str | None = None
    best_confidence: float | None = None
    best_score = float("-inf")

    for match in candidates:
        encoding_name = getattr(match, "encoding", None)
        if not encoding_name:
            continue
        try:
            normalized = normalise_text_encoding(encoding_name)
        except LookupError:
            continue
        try:
            decoded = sample.decode(normalized, errors="strict")
        except UnicodeDecodeError:
            continue
        total = len(decoded)
        if total == 0:
            continue
        good = 0
        symbols = 0
        controls = 0
        for ch in decoded:
            category = unicodedata.category(ch)
            if category in _GOOD_UNICODE_CATEGORIES:
                good += 1
            elif category.startswith("S"):
                symbols += 1
            elif category.startswith("C"):
                controls += 1
        letter_ratio = good / total
        symbol_ratio = symbols / total
        control_ratio = controls / total
        confidence = getattr(match, "coherence", None)
        if confidence is None:
            percent = getattr(match, "percent_coherence", None)
            if percent is not None:
                confidence = float(percent) / 100.0
        score = (confidence or 0.0) + (letter_ratio * 0.2) - (symbol_ratio * 0.15) - (
            control_ratio * 0.3
        )
        language = getattr(match, "language", None)
        language_bonus = 0.0
        language_key = None
        if isinstance(language, str):
            language_key = language.strip().lower()
            if language_key and language_key != "unknown":
                language_bonus += 0.05
        if language_key:
            preferences = _LANGUAGE_ENCODING_PRIORITIES.get(language_key)
            if preferences:
                try:
                    index = preferences.index(normalized)
                except ValueError:
                    pass
                else:
                    language_bonus += max(len(preferences) - index, 1) * 0.02
        alphabets = getattr(match, "alphabets", None)
        if alphabets and any("Box Drawing" in str(alpha) for alpha in alphabets):
            language_bonus -= 0.05
        score += language_bonus
        if score > best_score:
            best_score = score
            best_encoding = normalized
            best_confidence = confidence

    if best_encoding:
        return EncodingDetectionResult(best_encoding, best_confidence, "detected")
    return EncodingDetectionResult(fallback, None, "fallback")


@dataclass(slots=True)
class UserDocumentEntry:
    """Representation of a single filesystem entry within the user tree."""

    name: str
    relative_path: Path
    is_dir: bool
    size_bytes: int | None = None
    token_count: TokenCountResult | None = None
    percent_of_context: float | None = None
    children: list[UserDocumentEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Serialise the entry and its children into primitive structures."""
        payload: dict[str, object] = {
            "name": self.name,
            "path": self.relative_path.as_posix(),
            "type": "directory" if self.is_dir else "file",
        }
        if self.size_bytes is not None:
            payload["size_bytes"] = self.size_bytes
        if self.token_count is not None:
            payload["token_count"] = self.token_count.to_dict()
        if self.percent_of_context is not None:
            payload["percent_of_context"] = self.percent_of_context
        if self.children:
            payload["children"] = [child.to_dict() for child in self.children]
        return payload


@dataclass(slots=True)
class EncodingDetectionResult:
    """Outcome of attempting to determine a file's text encoding."""

    encoding: str
    confidence: float | None
    source: Literal["detected", "fallback", "empty"]


class UserDocumentsService:
    """Manage user documentation files under a dedicated root directory."""

    def __init__(
        self,
        root: Path | str,
        *,
        max_context_tokens: int,
        token_model: str | None = None,
        max_read_bytes: int = DEFAULT_MAX_READ_BYTES,
    ) -> None:
        """Validate configuration and capture the resolved root path."""
        if max_context_tokens <= 0:
            raise ValueError("max_context_tokens must be positive")
        if max_read_bytes <= 0:
            raise ValueError("max_read_bytes must be positive")
        if max_read_bytes > MAX_ALLOWED_READ_BYTES:
            raise ValueError(
                f"max_read_bytes must not exceed {MAX_ALLOWED_READ_BYTES}"
            )
        self.root = Path(root).expanduser().resolve()
        self.max_context_tokens = int(max_context_tokens)
        self.token_model = token_model
        self.max_read_bytes = int(max_read_bytes)

    # ------------------------------------------------------------------
    def list_tree(self) -> dict[str, object]:
        """Return a structured description of the documentation directory."""
        if self.root.exists():
            entry = self._build_directory(self.root, Path("."))
        else:
            entry = UserDocumentEntry(
                name=self.root.name or ".",
                relative_path=Path("."),
                is_dir=True,
            )
        text_tree = self._render_tree(entry)

        return {
            "root": str(self.root),
            "token_model": self.token_model,
            "max_context_tokens": self.max_context_tokens,
            "max_read_bytes": self.max_read_bytes,
            "max_read_kib": self.max_read_bytes // 1024,
            "root_entry": entry.to_dict(),
            "entries": [child.to_dict() for child in entry.children],
            "tree_text": text_tree,
        }

    # ------------------------------------------------------------------
    def read_file(
        self,
        relative_path: str | Path,
        *,
        start_line: int = 1,
        max_bytes: int | None = None,
    ) -> dict[str, object]:
        """Return a chunk of the target file capped at ``max_bytes`` bytes."""
        file_path = self._ensure_file(relative_path)
        if start_line < 1:
            raise ValueError("start_line must be >= 1")

        requested_bytes = (
            self.max_read_bytes if max_bytes is None else int(max_bytes)
        )
        if requested_bytes <= 0:
            raise ValueError("max_bytes must be positive")

        chunk_limit = min(requested_bytes, self.max_read_bytes)
        clamped = chunk_limit < requested_bytes

        detection = detect_file_encoding(file_path)
        encoding = detection.encoding
        collected: list[str] = []
        consumed = 0
        current_line = 0
        end_line = start_line - 1
        truncated = False
        truncated_mid_line = False
        prefix_bytes = 0
        file_size = file_path.stat().st_size

        with file_path.open("r", encoding=encoding, errors="replace") as stream:
            for raw_line in stream:
                current_line += 1
                encoded = raw_line.encode(encoding, errors="replace")
                if current_line < start_line:
                    prefix_bytes += len(encoded)
                    continue
                remaining = chunk_limit - consumed
                if remaining <= 0:
                    truncated = True
                    break
                if len(encoded) > remaining:
                    segment = encoded[:remaining].decode(encoding, errors="ignore")
                    collected.append(f"{current_line:>6}: {segment}")
                    consumed = chunk_limit
                    end_line = current_line
                    truncated = True
                    truncated_mid_line = True
                    break
                collected.append(f"{current_line:>6}: {raw_line.rstrip('\n')}\n")
                consumed += len(encoded)
                end_line = current_line
            else:
                truncated = False

            if not truncated:
                remainder = stream.read(1)
                if remainder:
                    truncated = True

        content = "".join(collected)
        remaining_bytes = max(file_size - prefix_bytes - consumed, 0)

        return {
            "path": self._relative_path(file_path).as_posix(),
            "encoding": encoding,
            "encoding_source": detection.source,
            "encoding_confidence": detection.confidence,
            "start_line": start_line,
            "end_line": end_line,
            "bytes_consumed": consumed,
            "content": content,
            "truncated": truncated,
            "bytes_requested": requested_bytes,
            "chunk_limit_bytes": chunk_limit,
            "clamped_to_limit": clamped,
            "bytes_remaining": remaining_bytes,
            "truncated_mid_line": truncated_mid_line,
        }

    # ------------------------------------------------------------------
    def create_file(
        self,
        relative_path: str | Path,
        *,
        content: str = "",
        exist_ok: bool = False,
        encoding: str | None = None,
    ) -> Path:
        """Create a new file under the documents root with optional content."""
        target = self._resolve_path(relative_path)
        if target.exists():
            if target.is_dir():
                raise IsADirectoryError(f"{target} is a directory")
            if not exist_ok:
                raise FileExistsError(target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
        mode = "w" if exist_ok else "x"
        normalized_encoding = normalise_text_encoding(encoding)
        with target.open(mode, encoding=normalized_encoding) as stream:
            stream.write(content)
        return target

    # ------------------------------------------------------------------
    def delete_file(self, relative_path: str | Path) -> None:
        """Remove a file inside the documents root."""
        target = self._ensure_file(relative_path)
        target.unlink()

    # ------------------------------------------------------------------
    def _build_directory(self, directory: Path, relative: Path) -> UserDocumentEntry:
        entries: list[UserDocumentEntry] = []
        child_results: list[TokenCountResult] = []
        for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if child.is_symlink():
                raise RuntimeError(f"Symlink entries are not supported: {child}")
            child_relative = relative / child.name
            if child.is_dir():
                entry = self._build_directory(child, child_relative)
            else:
                entry = self._build_file(child, child_relative)
            entries.append(entry)
            if entry.token_count is not None:
                child_results.append(entry.token_count)

        aggregate_tokens = combine_token_counts(child_results) if child_results else None
        percent = self._percent_of_context(aggregate_tokens.tokens if aggregate_tokens else None)
        return UserDocumentEntry(
            name=directory.name or ".",
            relative_path=relative,
            is_dir=True,
            token_count=aggregate_tokens,
            percent_of_context=percent,
            children=entries,
        )

    def _build_file(self, path: Path, relative: Path) -> UserDocumentEntry:
        size = path.stat().st_size
        detection = detect_file_encoding(path)
        encoding = detection.encoding
        if size > LARGE_FILE_TOKEN_ESTIMATE_BYTES:
            tokens = self._estimate_tokens_for_large_file(path, size, encoding)
        else:
            text = path.read_text(encoding=encoding, errors="replace")
            tokens = count_text_tokens(text, model=self.token_model)
        percent = self._percent_of_context(tokens.tokens)
        return UserDocumentEntry(
            name=path.name,
            relative_path=relative,
            is_dir=False,
            size_bytes=size,
            token_count=tokens,
            percent_of_context=percent,
        )

    def _estimate_tokens_for_large_file(
        self, path: Path, size: int, encoding: str
    ) -> TokenCountResult:
        sample_size = min(TOKEN_COUNT_SAMPLE_BYTES, size)
        with path.open("rb") as stream:
            sample_bytes = stream.read(sample_size)
        sample_text = sample_bytes.decode(encoding, errors="replace")
        sample_result = count_text_tokens(sample_text, model=self.token_model)
        model = sample_result.model or self.token_model
        reason_parts: list[str] = ["sampled_heuristic"]
        if sample_result.reason:
            reason_parts.append(sample_result.reason)
        reason = "; ".join(reason_parts)
        if sample_size == 0 or sample_result.tokens is None:
            return TokenCountResult.unavailable(model=model, reason=reason)
        ratio = size / sample_size
        estimated_tokens = int(round(sample_result.tokens * ratio))
        return TokenCountResult.approximate_result(
            estimated_tokens,
            model=model,
            reason=reason,
        )

    def _render_tree(self, entry: UserDocumentEntry) -> str:
        if not entry.children:
            suffix = " (empty)" if entry.is_dir else ""
            return f"{self._format_entry(entry)}{suffix}"

        lines = [self._format_entry(entry)]
        for line in self._iter_tree_lines(entry.children, prefix=""):
            lines.append(line)
        return "\n".join(lines)

    def _iter_tree_lines(
        self,
        entries: Iterable[UserDocumentEntry],
        *,
        prefix: str,
    ) -> Iterator[str]:
        entries = list(entries)
        for index, entry in enumerate(entries):
            is_last = index == len(entries) - 1
            connector = "└── " if is_last else "├── "
            current_prefix = prefix + ("    " if is_last else "│   ")
            line = prefix + connector + self._format_entry(entry)
            yield line
            if entry.children:
                yield from self._iter_tree_lines(entry.children, prefix=current_prefix)

    def _format_entry(self, entry: UserDocumentEntry) -> str:
        parts: list[str] = [entry.name or "."]
        if entry.is_dir:
            parts.append("[dir]")
        else:
            parts.append("[file]")
        if entry.size_bytes is not None:
            parts.append(f"{entry.size_bytes} B")
        if entry.token_count is not None and entry.token_count.tokens is not None:
            approx = "~" if entry.token_count.approximate else ""
            parts.append(f"{approx}{entry.token_count.tokens} tokens")
        if entry.percent_of_context is not None:
            parts.append(f"{entry.percent_of_context:.2f}% context")
        return " ".join(parts)

    def _percent_of_context(self, tokens: int | None) -> float | None:
        if tokens is None:
            return None
        return round((tokens / self.max_context_tokens) * 100, 2)

    def _resolve_path(self, relative_path: str | Path) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute():
            candidate = relative
        else:
            candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:  # pragma: no cover - path traversal guard
            raise PermissionError("Attempted to access path outside of documents root") from exc
        return candidate


    def _ensure_file(self, relative_path: str | Path) -> Path:
        path = self._resolve_path(relative_path)
        if not path.exists():
            raise FileNotFoundError(path)
        if path.is_dir():
            raise IsADirectoryError(path)
        return path

    def _relative_path(self, absolute: Path) -> Path:
        return absolute.relative_to(self.root)

