from pathlib import Path

import pytest

from app.core.trace_index.builder import build_trace_index
from app.core.trace_index.cache import (
    cache_path,
    read_trace_index_cache,
    read_trace_index_cache_for_config,
    write_trace_index_cache,
)
from app.core.trace_index.config import TraceIndexConfig
from app.core.trace_index.model import TraceIndex

FIXTURE_ROOT = Path("tests/fixtures/trace_index_project")


def _fixture_config() -> TraceIndexConfig:
    return TraceIndexConfig.from_conventions(
        FIXTURE_ROOT / "Req",
        project_root=FIXTURE_ROOT,
        exclude_globs=("Vsrc/broken_*",),
    )


@pytest.mark.unit
def test_cache_path_uses_req_cookareq_location() -> None:
    assert cache_path("Req").as_posix() == "Req/.cookareq/trace_index.generated.json"


@pytest.mark.unit
def test_write_and_read_trace_index_cache_round_trips(tmp_path: Path) -> None:
    config = _fixture_config()
    index = build_trace_index(config)
    req_root = tmp_path / "Req"

    path = write_trace_index_cache(index, req_root)
    restored = read_trace_index_cache(path)

    assert path == req_root / ".cookareq" / "trace_index.generated.json"
    assert restored == index
    assert path.read_text(encoding="utf-8").endswith("\n")


@pytest.mark.unit
def test_read_cache_for_config_reports_fresh_cache(tmp_path: Path) -> None:
    req_root = tmp_path / "Req"
    req_root.mkdir()
    source = tmp_path / "Vsrc"
    source.mkdir()
    (source / "demo.c").write_text("/* @covers LLR1 */\n", encoding="utf-8")
    config = TraceIndexConfig.from_conventions(req_root, project_root=tmp_path)
    metadata_index = TraceIndex(
        project_root=config.project_root,
        req_root=config.req_root,
        config_hash=build_trace_index(config).config_hash,
        input_fingerprint=build_trace_index(config).input_fingerprint,
        generated_at_utc="2026-06-25T00:00:00Z",
    )
    write_trace_index_cache(metadata_index, req_root)

    loaded = read_trace_index_cache_for_config(config)

    assert loaded.index == metadata_index
    assert loaded.stale is False
    assert loaded.issues == ()


@pytest.mark.unit
def test_read_cache_for_config_reports_stale_cache_after_input_change(tmp_path: Path) -> None:
    req_root = tmp_path / "Req"
    req_root.mkdir()
    source = tmp_path / "Vsrc"
    source.mkdir()
    source_file = source / "demo.c"
    source_file.write_text("/* @covers LLR1 */\n", encoding="utf-8")
    config = TraceIndexConfig.from_conventions(req_root, project_root=tmp_path)
    index = TraceIndex(
        project_root=config.project_root,
        req_root=config.req_root,
        config_hash=build_trace_index(config).config_hash,
        input_fingerprint=build_trace_index(config).input_fingerprint,
        generated_at_utc="2026-06-25T00:00:00Z",
    )
    write_trace_index_cache(index, req_root)
    source_file.write_text("/* @covers LLR2 */\n", encoding="utf-8")

    loaded = read_trace_index_cache_for_config(config)

    assert loaded.index == index
    assert loaded.stale is True
    assert [issue.code for issue in loaded.issues] == ["STALE_CACHE"]


@pytest.mark.unit
def test_atomic_write_keeps_old_cache_when_replace_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old_index = TraceIndex(
        project_root="old",
        req_root="Req",
        config_hash="old",
        input_fingerprint="old",
        generated_at_utc="2026-06-25T00:00:00Z",
    )
    new_index = TraceIndex(
        project_root="new",
        req_root="Req",
        config_hash="new",
        input_fingerprint="new",
        generated_at_utc="2026-06-25T00:00:00Z",
    )
    req_root = tmp_path / "Req"
    path = write_trace_index_cache(old_index, req_root)

    def fail_replace(src: object, dst: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("app.core.trace_index.cache.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        write_trace_index_cache(new_index, req_root)

    assert read_trace_index_cache(path) == old_index
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.unit
def test_read_cache_for_config_reports_invalid_json(tmp_path: Path) -> None:
    req_root = tmp_path / "Req"
    path = cache_path(req_root)
    path.parent.mkdir(parents=True)
    path.write_text("{invalid json", encoding="utf-8")
    config = TraceIndexConfig.from_conventions(req_root, project_root=tmp_path)

    loaded = read_trace_index_cache_for_config(config)

    assert loaded.index is None
    assert loaded.stale is True
    assert [issue.code for issue in loaded.issues] == ["STALE_CACHE"]
