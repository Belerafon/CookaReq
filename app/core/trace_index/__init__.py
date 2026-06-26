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
    parse_result_file,
    parse_result_text,
)
from .parse_tests import TestParseResult, parse_test_file, parse_test_text
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
    "TestParseResult",
    "TestResultRef",
    "TestRunRef",
    "TraceIndex",
    "TraceIndexCacheRead",
    "TraceIndexConfig",
    "TraceIssue",
    "TraceRequirementRef",
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
    "parse_result_file",
    "parse_result_text",
    "parse_test_file",
    "parse_test_text",
    "make_code_location_key",
    "make_test_result_key",
    "make_test_run_key",
]
