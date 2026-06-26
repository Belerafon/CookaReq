"""Trace-index core subsystem for external evidence artifacts."""

from .builder import build_trace_index
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
    "CodeParseResult",
    "TestCaseRef",
    "ResultParseResult",
    "TestParseResult",
    "TestResultRef",
    "TestRunRef",
    "TraceIndex",
    "TraceIndexConfig",
    "TraceIssue",
    "TraceRequirementRef",
    "build_trace_index",
    "cache_metadata",
    "collect_input_files",
    "config_hash",
    "input_fingerprint",
    "is_index_stale",
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
