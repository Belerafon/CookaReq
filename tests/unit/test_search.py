"""Tests for search."""

import pytest

from app.core.model import (
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
)
from app.core.search import (
    filter_by_labels,
    filter_by_status,
    filter_has_derived,
    filter_is_derived,
    search,
    search_text,
)

pytestmark = pytest.mark.unit


def sample_requirements():
    return [
        Requirement(
            id=1,
            title="Login form",
            statement="System shows login form",
            type=RequirementType.REQUIREMENT,
            status=Status.DRAFT,
            owner="alice",
            priority=Priority.MEDIUM,
            source="spec",
            verification=Verification.ANALYSIS,
            labels=["ui", "auth"],
            notes="Requires username",
            rationale="Secure access",
            assumptions="Users have accounts",
        ),
        Requirement(
            id=2,
            title="Store data",
            statement="System stores data in DB",
            type=RequirementType.REQUIREMENT,
            status=Status.DRAFT,
            owner="bob",
            priority=Priority.MEDIUM,
            source="spec",
            verification=Verification.ANALYSIS,
            labels=["backend"],
        ),
        Requirement(
            id=3,
            title="Export report",
            statement="User can export report",
            type=RequirementType.REQUIREMENT,
            status=Status.DRAFT,
            owner="carol",
            priority=Priority.MEDIUM,
            source="spec",
            verification=Verification.ANALYSIS,
            labels=["ui"],
            links=["2"],
        ),
    ]


def test_filter_by_labels():
    reqs = sample_requirements()
    assert {r.id for r in filter_by_labels(reqs, ["ui"])} == {1, 3}
    assert [r.id for r in filter_by_labels(reqs, ["ui", "auth"])] == [1]


def test_filter_by_labels_any_mode():
    reqs = sample_requirements()
    ids = {r.id for r in filter_by_labels(reqs, ["auth", "backend"], match_all=False)}
    assert ids == {1, 2}


def test_filter_by_labels_empty_returns_all():
    reqs = sample_requirements()
    assert filter_by_labels(reqs, []) == reqs


def test_search_text():
    reqs = sample_requirements()
    found = search_text(reqs, "login", ["title", "notes"])
    assert [r.id for r in found] == [1]
    found = search_text(reqs, "EXPORT", ["title"])
    assert [r.id for r in found] == [3]
    found = search_text(reqs, "secure", ["rationale"])
    assert [r.id for r in found] == [1]
    found = search_text(reqs, "accounts", ["assumptions"])
    assert [r.id for r in found] == [1]


def test_search_text_strips_markdown():
    reqs = [
        Requirement(
            id=10,
            title="Markdown",
            statement="Use **bold** statement",
            type=RequirementType.REQUIREMENT,
            status=Status.DRAFT,
            owner="",
            priority=Priority.MEDIUM,
            source="spec",
            verification=Verification.ANALYSIS,
        ),
    ]
    found = search_text(reqs, "bold", ["statement"])
    assert [r.id for r in found] == [10]


def test_search_text_empty_query_returns_all():
    reqs = sample_requirements()
    assert search_text(reqs, "", ["title"]) == reqs


def test_search_text_no_valid_fields_returns_all():
    reqs = sample_requirements()
    assert search_text(reqs, "login", ["unknown"]) == reqs


def test_combined_search():
    reqs = sample_requirements()
    found = search(reqs, labels=["ui"], query="export", fields=["title"])
    assert [r.id for r in found] == [3]


def test_search_match_any():
    reqs = sample_requirements()
    found = search(reqs, labels=["auth", "backend"], match_all=False)
    assert {r.id for r in found} == {1, 2}


def test_filter_is_and_has_derived():
    reqs = sample_requirements()
    assert [r.id for r in filter_is_derived(reqs)] == [3]
    assert [r.id for r in filter_has_derived(reqs, reqs)] == [2]


def test_search_with_derived_filters():
    reqs = sample_requirements()
    assert [r.id for r in search(reqs, is_derived=True)] == [3]
    assert [r.id for r in search(reqs, has_derived=True)] == [2]


def test_field_queries():
    reqs = sample_requirements()
    found = search(reqs, field_queries={"owner": "alice"})
    assert [r.id for r in found] == [1]
    found = search(reqs, field_queries={"title": "report", "owner": "carol"})
    assert [r.id for r in found] == [3]
    found = search(reqs, field_queries={"rationale": "secure"})
    assert [r.id for r in found] == [1]


def test_filter_by_status_function():
    reqs = sample_requirements()
    reqs[1].status = Status.APPROVED
    filtered = filter_by_status(reqs, "approved")
    assert [r.id for r in filtered] == [2]
    assert filter_by_status(reqs, None) == reqs
