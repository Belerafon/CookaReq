"""Trace-index core subsystem for external evidence artifacts."""

from .builder import build_trace_index
from .cache import (
    CACHE_RELATIVE_PATH,
    TraceIndexCacheRead,
    cache_path,
    read_trace_index_cache,
    read_trace_index_cache_for_config,
    write_trace_index_cache,
)
from .export import (
    render_artifact_matrix_csv,
    render_artifact_matrix_html,
    render_trace_index_report_html,
)
from .config import (
    TraceIndexConfig,
    cache_metadata,
    collect_input_files,
    config_hash,
    input_fingerprint,
    is_index_stale,
)
from .parse_code import CodeParseResult, parse_code_file, parse_code_text
from .parse_results import (
    ResultParseResult,
    normalize_status,
    parse_junit_result_text,
    parse_result_file,
    parse_result_text,
)
from .parse_tests import TestParseResult, parse_test_file, parse_test_text
from .matrix import (
    TraceArtifactMatrix,
    TraceArtifactMatrixCell,
    TraceArtifactMatrixColumn,
    build_artifact_trace_matrix,
)
from .model import (
    GENERATOR,
    GENERATOR_VERSION,
    SCHEMA_VERSION,
    CodeLocation,
    TestCaseRef,
    TestResultRef,
    TestRunRef,
    TraceIndex,
    TraceIssue,
    TraceRequirementRef,
    make_code_location_key,
    make_test_result_key,
    make_test_run_key,
)

__all__ = [
    "GENERATOR",
    "GENERATOR_VERSION",
    "SCHEMA_VERSION",
    "CodeLocation",
    "CACHE_RELATIVE_PATH",
    "CodeParseResult",
    "TestCaseRef",
    "ResultParseResult",
    "render_artifact_matrix_csv",
    "render_artifact_matrix_html",
    "render_trace_index_report_html",
    "TestParseResult",
    "TestResultRef",
    "TestRunRef",
    "TraceIndex",
    "TraceIndexCacheRead",
    "TraceIndexConfig",
    "TraceArtifactMatrix",
    "TraceArtifactMatrixCell",
    "TraceArtifactMatrixColumn",
    "TraceIssue",
    "TraceRequirementRef",
    "build_artifact_trace_matrix",
    "build_trace_index",
    "cache_path",
    "cache_metadata",
    "collect_input_files",
    "config_hash",
    "input_fingerprint",
    "is_index_stale",
    "read_trace_index_cache",
    "read_trace_index_cache_for_config",
    "write_trace_index_cache",
    "parse_code_file",
    "parse_code_text",
    "normalize_status",
    "parse_junit_result_text",
    "parse_result_file",
    "parse_result_text",
    "parse_test_file",
    "parse_test_text",
    "make_code_location_key",
    "make_test_result_key",
    "make_test_run_key",
]
