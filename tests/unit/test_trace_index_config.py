from pathlib import Path

import pytest

from app.core.trace_index.config import (
    DEFAULT_RESULT_GLOBS,
    DEFAULT_SOURCE_GLOBS,
    DEFAULT_TEST_GLOBS,
    TraceIndexConfig,
    cache_metadata,
    collect_input_files,
    config_hash,
    input_fingerprint,
    is_index_stale,
)
from app.core.trace_index.model import TraceIndex

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "trace_index_project"


@pytest.mark.unit
def test_default_config_uses_project_conventions() -> None:
    config = TraceIndexConfig.from_conventions(FIXTURE_ROOT / "Req")

    assert config.project_root == FIXTURE_ROOT.as_posix()
    assert config.req_root == (FIXTURE_ROOT / "Req").as_posix()
    assert config.source_globs == DEFAULT_SOURCE_GLOBS
    assert config.test_globs == DEFAULT_TEST_GLOBS
    assert config.result_globs == DEFAULT_RESULT_GLOBS


@pytest.mark.unit
def test_config_overrides_are_preserved_and_serializable() -> None:
    config = TraceIndexConfig.from_conventions(
        FIXTURE_ROOT / "Req",
        project_root=FIXTURE_ROOT,
        source_globs=("custom/**/*.c",),
        test_globs=("custom_tests/**/*.c",),
        result_globs=("custom_results/*.txt",),
        exclude_globs=("excluded/**",),
        module_filter="demo",
    )

    restored = TraceIndexConfig.from_dict(config.to_dict())

    assert restored == config
    assert restored.source_globs == ("custom/**/*.c",)
    assert restored.module_filter == "demo"


@pytest.mark.unit
def test_config_hash_is_stable_and_changes_on_override() -> None:
    first = TraceIndexConfig.from_conventions(FIXTURE_ROOT / "Req")
    same = TraceIndexConfig.from_dict(first.to_dict())
    changed = TraceIndexConfig.from_conventions(
        FIXTURE_ROOT / "Req", source_globs=("Vsrc/demo.c",)
    )

    assert config_hash(first) == config_hash(same)
    assert config_hash(first) != config_hash(changed)


@pytest.mark.unit
def test_collect_input_files_uses_globs_and_excludes() -> None:
    config = TraceIndexConfig.from_conventions(
        FIXTURE_ROOT / "Req",
        source_globs=("Vsrc/**/*.c",),
        test_globs=("tests/test_*/src/**/*.c",),
        result_globs=("tests/test_*/Build/test_results.txt",),
        exclude_globs=("Vsrc/broken_*",),
    )

    files = collect_input_files(config)

    assert "Vsrc/demo.c" in files
    assert "Vsrc/broken_marker.c" not in files
    assert "tests/test_demo/src/test_demo.c" in files
    assert "tests/test_demo/Build/test_results.txt" in files
    assert "Req/LLR/items/1.json" in files


@pytest.mark.unit
def test_input_fingerprint_changes_when_input_content_changes(tmp_path: Path) -> None:
    (tmp_path / "Req" / "LLR" / "items").mkdir(parents=True)
    item = tmp_path / "Req" / "LLR" / "items" / "1.json"
    item.write_text('{"id": 1}\n', encoding="utf-8")
    source_dir = tmp_path / "Vsrc"
    source_dir.mkdir()
    source = source_dir / "demo.c"
    source.write_text("/* @covers LLR1 */\n", encoding="utf-8")
    config = TraceIndexConfig.from_conventions(tmp_path / "Req", project_root=tmp_path)

    before = input_fingerprint(config)
    source.write_text("/* @covers LLR2 */\n", encoding="utf-8")
    after = input_fingerprint(config)

    assert before != after


@pytest.mark.unit
def test_cache_metadata_contains_required_schema_fields() -> None:
    config = TraceIndexConfig.from_conventions(FIXTURE_ROOT / "Req")
    metadata = cache_metadata(config)

    assert set(metadata) == {
        "schema_version",
        "generator_version",
        "project_root",
        "req_root",
        "config_hash",
        "input_fingerprint",
    }
    assert metadata["config_hash"] == config_hash(config)
    assert metadata["input_fingerprint"] == input_fingerprint(config)


@pytest.mark.unit
def test_is_index_stale_detects_schema_config_and_input_changes(tmp_path: Path) -> None:
    (tmp_path / "Req").mkdir()
    (tmp_path / "Vsrc").mkdir()
    source = tmp_path / "Vsrc" / "demo.c"
    source.write_text("/* @covers LLR1 */\n", encoding="utf-8")
    config = TraceIndexConfig.from_conventions(tmp_path / "Req", project_root=tmp_path)
    metadata = cache_metadata(config)
    index = TraceIndex(
        project_root=str(metadata["project_root"]),
        req_root=str(metadata["req_root"]),
        config_hash=str(metadata["config_hash"]),
        input_fingerprint=str(metadata["input_fingerprint"]),
        generated_at_utc="2026-06-25T00:00:00Z",
    )

    assert is_index_stale(index, config) is False

    changed_config = TraceIndexConfig.from_conventions(
        tmp_path / "Req", project_root=tmp_path, source_globs=("Vsrc/*.h",)
    )
    assert is_index_stale(index, changed_config) is True

    source.write_text("/* @covers LLR2 */\n", encoding="utf-8")
    assert is_index_stale(index, config) is True
