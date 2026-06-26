"""Build a complete trace index from requirements and external artifacts."""
from __future__ import annotations

from pathlib import Path

from app.core.document_store import load_requirements
from app.core.model import Verification, normalized_verification_methods

from .config import TraceIndexConfig, cache_metadata
from .model import (
    CodeLocation,
    TestCaseRef,
    TestResultRef,
    TestRunRef,
    TraceIndex,
    TraceIssue,
    TraceRequirementRef,
)
from .parse_code import parse_code_file
from .parse_results import parse_result_file
from .parse_tests import parse_test_file


def build_trace_index(config: TraceIndexConfig) -> TraceIndex:
    """Build a deterministic trace index and collect all diagnostics."""
    metadata = cache_metadata(config)
    requirements, raw_requirements, issues = _load_requirement_refs(config)
    requirement_rids = {requirement.rid for requirement in requirements}

    code_locations, code_issues = _parse_code_locations(config)
    test_cases, test_issues = _parse_test_cases(config)
    test_runs, test_results, result_issues = _parse_results(config)
    issues.extend(code_issues)
    issues.extend(test_issues)
    issues.extend(result_issues)

    issues.extend(_validate_code_locations(code_locations, requirement_rids))
    issues.extend(_validate_test_cases(test_cases, requirement_rids))
    issues.extend(_validate_duplicate_test_ids(test_cases))
    issues.extend(_validate_results(test_cases, test_results))
    issues.extend(_validate_missing_tests(raw_requirements, test_cases))

    return TraceIndex(
        project_root=str(metadata["project_root"]),
        req_root=str(metadata["req_root"]),
        config_hash=str(metadata["config_hash"]),
        input_fingerprint=str(metadata["input_fingerprint"]),
        requirements=tuple(sorted(requirements, key=lambda item: item.stable_key)),
        code_locations=tuple(sorted(code_locations, key=lambda item: item.stable_key)),
        test_cases=tuple(sorted(test_cases, key=lambda item: item.stable_key)),
        test_runs=tuple(sorted(test_runs, key=lambda item: item.stable_key)),
        test_results=tuple(sorted(test_results, key=lambda item: item.stable_key)),
        issues=tuple(_sort_issues(issues)),
    )


def _load_requirement_refs(
    config: TraceIndexConfig,
) -> tuple[list[TraceRequirementRef], list[object], list[TraceIssue]]:
    issues: list[TraceIssue] = []
    try:
        requirements = load_requirements(config.req_root)
    except OSError as exc:
        return [], [], [
            TraceIssue(
                code="INPUT_FILE_UNREADABLE",
                severity="high",
                message=f"Cannot read requirements: {exc}",
                path=config.req_root,
            )
        ]
    matched_requirements = [
        requirement
        for requirement in requirements
        if _matches_module(requirement, config.module_filter)
    ]
    refs = [
        TraceRequirementRef(
            rid=requirement.rid,
            title=requirement.title,
            document=requirement.doc_prefix,
        )
        for requirement in matched_requirements
    ]
    return refs, list(matched_requirements), issues


def _parse_code_locations(
    config: TraceIndexConfig,
) -> tuple[list[CodeLocation], list[TraceIssue]]:
    locations: list[CodeLocation] = []
    issues: list[TraceIssue] = []
    for path in _matched_files(config, config.source_globs):
        result = parse_code_file(path, project_root=config.project_root)
        locations.extend(result.code_locations)
        issues.extend(result.issues)
    return locations, issues


def _parse_test_cases(
    config: TraceIndexConfig,
) -> tuple[list[TestCaseRef], list[TraceIssue]]:
    test_cases: list[TestCaseRef] = []
    issues: list[TraceIssue] = []
    for path in _matched_files(config, config.test_globs):
        result = parse_test_file(path, project_root=config.project_root)
        test_cases.extend(result.test_cases)
        issues.extend(result.issues)
    return test_cases, issues


def _parse_results(
    config: TraceIndexConfig,
) -> tuple[list[TestRunRef], list[TestResultRef], list[TraceIssue]]:
    runs: list[TestRunRef] = []
    results: list[TestResultRef] = []
    issues: list[TraceIssue] = []
    seen_runs: set[str] = set()
    for path in _matched_files(config, config.result_globs):
        result = parse_result_file(path, project_root=config.project_root)
        for run in result.test_runs:
            if run.stable_key not in seen_runs:
                seen_runs.add(run.stable_key)
                runs.append(run)
        results.extend(result.test_results)
        issues.extend(result.issues)
    return runs, results, issues


def _matched_files(config: TraceIndexConfig, globs: tuple[str, ...]) -> tuple[Path, ...]:
    root = Path(config.project_root)
    paths: set[Path] = set()
    for pattern in globs:
        for path in root.glob(pattern):
            if path.is_file() and not _is_excluded(path, config):
                paths.add(path)
    return tuple(sorted(paths, key=lambda path: path.as_posix()))


def _is_excluded(path: Path, config: TraceIndexConfig) -> bool:
    root = Path(config.project_root)
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.as_posix()
    from fnmatch import fnmatch

    return any(fnmatch(relative, pattern) for pattern in config.exclude_globs)


def _validate_code_locations(
    code_locations: list[CodeLocation], requirement_rids: set[str]
) -> list[TraceIssue]:
    issues: list[TraceIssue] = []
    for location in code_locations:
        if location.rid not in requirement_rids:
            issues.append(
                TraceIssue(
                    code="UNKNOWN_RID",
                    severity="high",
                    message="Code marker references an unknown requirement",
                    path=location.path,
                    line=location.line_start,
                    rid=location.rid,
                )
            )
    return issues


def _validate_test_cases(
    test_cases: list[TestCaseRef], requirement_rids: set[str]
) -> list[TraceIssue]:
    issues: list[TraceIssue] = []
    for test_case in test_cases:
        for rid in test_case.covers:
            if rid not in requirement_rids:
                issues.append(
                    TraceIssue(
                        code="UNKNOWN_RID",
                        severity="high",
                        message="Test case references an unknown requirement",
                        path=test_case.path,
                        line=test_case.line_start,
                        rid=rid,
                        test_id=test_case.test_id,
                    )
                )
    return issues


def _validate_duplicate_test_ids(test_cases: list[TestCaseRef]) -> list[TraceIssue]:
    by_id: dict[str, list[TestCaseRef]] = {}
    for test_case in test_cases:
        by_id.setdefault(test_case.test_id, []).append(test_case)
    issues: list[TraceIssue] = []
    for test_id, group in by_id.items():
        unique_locations = {(case.path, case.line_start) for case in group}
        if len(unique_locations) > 1:
            first = sorted(group, key=lambda case: (case.path, case.line_start))[0]
            issues.append(
                TraceIssue(
                    code="DUPLICATE_TEST_ID",
                    severity="high",
                    message="Duplicate test_id across test sources",
                    path=first.path,
                    line=first.line_start,
                    test_id=test_id,
                )
            )
    return issues


def _validate_results(
    test_cases: list[TestCaseRef], test_results: list[TestResultRef]
) -> list[TraceIssue]:
    cases_by_id = {test_case.test_id: test_case for test_case in test_cases}
    results_by_test_id: dict[str, list[TestResultRef]] = {}
    issues: list[TraceIssue] = []
    for result in test_results:
        results_by_test_id.setdefault(result.test_id, []).append(result)
        test_case = cases_by_id.get(result.test_id)
        if test_case is None:
            issues.append(
                TraceIssue(
                    code="RESULT_WITHOUT_TEST_CASE",
                    severity="warning",
                    message="Result references a test case that was not found in sources",
                    path=result.result_file,
                    line=result.line_start,
                    test_id=result.test_id,
                )
            )
            continue
        if not result.covers:
            issues.append(
                TraceIssue(
                    code="RESULT_WITHOUT_COVERS",
                    severity="warning",
                    message="Result does not declare requirement coverage",
                    path=result.result_file,
                    line=result.line_start,
                    test_id=result.test_id,
                )
            )
        elif set(result.covers) != set(test_case.covers):
            issues.append(
                TraceIssue(
                    code="COVERAGE_MISMATCH",
                    severity="high",
                    message="Result coverage differs from test source coverage",
                    path=result.result_file,
                    line=result.line_start,
                    test_id=result.test_id,
                )
            )
    for test_case in test_cases:
        if test_results and test_case.test_id not in results_by_test_id:
            issues.append(
                TraceIssue(
                    code="TEST_WITHOUT_RESULT",
                    severity="warning",
                    message="Test case does not have a parsed result",
                    path=test_case.path,
                    line=test_case.line_start,
                    test_id=test_case.test_id,
                )
            )
    return issues


def _validate_missing_tests(
    requirements: list[object], test_cases: list[TestCaseRef]
) -> list[TraceIssue]:
    covered = {rid for test_case in test_cases for rid in test_case.covers}
    issues: list[TraceIssue] = []
    for requirement in requirements:
        rid = str(getattr(requirement, "rid", ""))
        if _requirement_requires_test(requirement) and rid and rid not in covered:
            issues.append(
                TraceIssue(
                    code="MISSING_TEST_FOR_LLR",
                    severity="warning",
                    message="Requirement with test verification has no test case",
                    rid=rid,
                )
            )
    return issues


def _matches_module(requirement: object, module_filter: str | None) -> bool:
    if not module_filter:
        return True
    title = str(getattr(requirement, "title", ""))
    if title.startswith(f"{module_filter}:"):
        return True
    return any(
        str(path).startswith(f"context/modules/{module_filter}/")
        for path in getattr(requirement, "context_docs", [])
    )


def _requirement_requires_test(requirement: object) -> bool:
    return Verification.TEST in normalized_verification_methods(requirement)  # type: ignore[arg-type]


def _sort_issues(issues: list[TraceIssue]) -> list[TraceIssue]:
    return sorted(
        issues,
        key=lambda issue: (
            issue.severity,
            issue.code,
            issue.path,
            issue.line or 0,
            issue.rid or "",
            issue.test_id or "",
        ),
    )
