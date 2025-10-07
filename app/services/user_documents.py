"""Service helpers for managing user-provided documentation files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from ..llm.tokenizer import TokenCountResult, combine_token_counts, count_text_tokens

DEFAULT_MAX_READ_BYTES = 10_240
MAX_ALLOWED_READ_BYTES = 524_288


@dataclass(slots=True)
class UserDocumentEntry:
    """Representation of a single filesystem entry within the user tree."""

    name: str
    relative_path: Path
    is_dir: bool
    size_bytes: int | None = None
    token_count: TokenCountResult | None = None
    percent_of_context: float | None = None
    children: list["UserDocumentEntry"] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
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
        if max_bytes is None:
            max_bytes = self.max_read_bytes
        if max_bytes <= 0 or max_bytes > self.max_read_bytes:
            raise ValueError(
                f"max_bytes must be within 1..{self.max_read_bytes}"
            )

        collected: list[str] = []
        consumed = 0
        current_line = 0
        end_line = start_line - 1
        truncated = False
        with file_path.open("r", encoding="utf-8", errors="replace") as stream:
            for raw_line in stream:
                current_line += 1
                if current_line < start_line:
                    continue
                encoded = raw_line.encode("utf-8")
                remaining = max_bytes - consumed
                if remaining <= 0:
                    truncated = True
                    break
                if len(encoded) > remaining:
                    segment = encoded[:remaining].decode("utf-8", errors="ignore")
                    collected.append(f"{current_line:>6}: {segment}")
                    consumed = max_bytes
                    end_line = current_line
                    truncated = True
                    break
                collected.append(f"{current_line:>6}: {raw_line.rstrip('\n')}\n")
                consumed += len(encoded)
                end_line = current_line
            else:
                truncated = False

            # Determine if there is more content after finishing the loop.
            if not truncated:
                remainder = stream.read(1)
                if remainder:
                    truncated = True

        content = "".join(collected)
        return {
            "path": self._relative_path(file_path).as_posix(),
            "start_line": start_line,
            "end_line": end_line,
            "bytes_consumed": consumed,
            "content": content,
            "truncated": truncated,
        }

    # ------------------------------------------------------------------
    def create_file(
        self,
        relative_path: str | Path,
        *,
        content: str = "",
        exist_ok: bool = False,
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
        with target.open(mode, encoding="utf-8") as stream:
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
        text = path.read_text(encoding="utf-8", errors="replace")
        tokens = count_text_tokens(text, model=self.token_model)
        percent = self._percent_of_context(tokens.tokens)
        size = path.stat().st_size
        return UserDocumentEntry(
            name=path.name,
            relative_path=relative,
            is_dir=False,
            size_bytes=size,
            token_count=tokens,
            percent_of_context=percent,
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

