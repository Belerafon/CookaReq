from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.services.user_documents import DEFAULT_MAX_READ_BYTES
from app.ui.main_frame.agent import (
    MainFrameAgentMixin,
    _DocumentsTreeCacheEntry,
    _DocumentsTreeRequest,
)


class _StubPanel:
    """Lightweight stand-in for the agent panel when testing the mixin."""

    def __init__(self, root: Path | None) -> None:
        self._documents_root = root
        self.documents_subdirectory = "docs"
        self._listener = None
        self.notifications = 0

    @property
    def documents_root(self) -> Path | None:
        return self._documents_root

    def set_documents_root_listener(self, callback) -> None:  # pragma: no cover - interface
        self._listener = callback
        if callback is not None:
            callback(self._documents_root)

    def change_root(self, root: Path | None) -> None:
        self._documents_root = root
        if self._listener is not None:
            self._listener(root)

    def on_documents_context_changed(self) -> None:
        self.notifications += 1


class _DummyFrame(MainFrameAgentMixin):
    def __init__(self, root: Path | None) -> None:
        self.agent_panel = _StubPanel(root)
        self.llm_settings = SimpleNamespace(max_context_tokens=256, model="demo")
        self.mcp_settings = SimpleNamespace(documents_max_read_kb=0)
        self._setup_agent_documents_hooks()


def test_documents_cache_invalidated_on_root_change(tmp_path: Path) -> None:
    frame = _DummyFrame(tmp_path / "first")
    request = _DocumentsTreeRequest(
        documents_root=tmp_path / "first",
        max_context_tokens=256,
        token_model="demo",
        max_read_bytes=DEFAULT_MAX_READ_BYTES,
    )
    frame._documents_tree_cache = _DocumentsTreeCacheEntry(
        request=request,
        snapshot={
            "max_context_tokens": request.max_context_tokens,
            "max_read_bytes": request.max_read_bytes,
            "tree_text": "sample",
        },
        built_at=datetime.now(timezone.utc),
    )
    frame._documents_tree_current_request = request

    frame.agent_panel.change_root(tmp_path / "second")

    assert frame._documents_tree_cache is None
    assert frame._documents_tree_error is None
    assert frame._documents_tree_current_request is None

