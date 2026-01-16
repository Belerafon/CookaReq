from __future__ import annotations

import pytest

from app.core.model import Priority, Requirement, RequirementType, Status, Verification
from app.core.requirement_import import (
    RequirementImportConfiguration,
    SequentialIDAllocator,
    build_requirements,
    load_csv_dataset,
)
from app.core.requirement_tabular_export import render_tabular_delimited
from app.ui.requirement_exporter import build_tabular_export

pytestmark = pytest.mark.integration


_FIELDS = [
    "id",
    "title",
    "statement",
    "type",
    "status",
    "owner",
    "priority",
    "source",
    "verification",
    "acceptance",
    "conditions",
    "rationale",
    "assumptions",
    "notes",
    "labels",
    "approved_at",
    "modified_at",
]


def _requirements() -> list[Requirement]:
    return [
        Requirement(
            id=1,
            title="Core requirement",
            statement="Line 1\nLine 2, with comma",
            type=RequirementType.REQUIREMENT,
            status=Status.IN_REVIEW,
            owner="Owner A",
            priority=Priority.HIGH,
            source="Spec \"Alpha\"",
            verification=Verification.TEST,
            acceptance="Must pass test",
            conditions="Temp > 5°C",
            rationale="Because we need it",
            assumptions="Assume network",
            notes="Note with tab\tend",
            labels=["core", "ui"],
            approved_at="2024-01-05",
            modified_at="2024-02-01",
            attachments=[],
            links=[],
            doc_prefix="SYS",
            rid="SYS1",
        ),
        Requirement(
            id=2,
            title="Edge requirement",
            statement="Single line",
            type=RequirementType.CONSTRAINT,
            status=Status.DRAFT,
            owner="Owner B",
            priority=Priority.MEDIUM,
            source="Source",
            verification=Verification.ANALYSIS,
            acceptance="Check\nMulti-line",
            conditions="Condition, with comma",
            rationale="Rationale",
            assumptions="Assumption",
            notes="Notes",
            labels=["backend"],
            approved_at="2024-03-10",
            modified_at="2024-03-11",
            attachments=[],
            links=[],
            doc_prefix="SYS",
            rid="SYS2",
        ),
    ]


@pytest.mark.parametrize(
    ("delimiter", "suffix"),
    [(",", ".csv"), ("\t", ".tsv")],
)
def test_export_import_roundtrip_preserves_fields(tmp_path, delimiter, suffix):
    requirements = _requirements()
    headers, rows = build_tabular_export(
        requirements,
        list(_FIELDS),
        header_style="fields",
        value_style="raw",
    )
    content = render_tabular_delimited(headers, rows, delimiter=delimiter)
    export_path = tmp_path / f"requirements{suffix}"
    export_path.write_text(content, encoding="utf-8")

    dataset = load_csv_dataset(export_path, delimiter=delimiter)
    config = RequirementImportConfiguration(
        mapping={field: index for index, field in enumerate(_FIELDS)},
        has_header=True,
    )
    allocator = SequentialIDAllocator(start=1, existing=[])
    result = build_requirements(dataset, config, allocator=allocator)

    assert result.issues == []
    assert result.imported_rows == len(requirements)

    for original, imported in zip(requirements, result.requirements, strict=True):
        assert imported.id == original.id
        assert imported.title == original.title
        assert imported.statement == original.statement
        assert imported.type == original.type
        assert imported.status == original.status
        assert imported.owner == original.owner
        assert imported.priority == original.priority
        assert imported.source == original.source
        assert imported.verification == original.verification
        assert imported.acceptance == original.acceptance
        assert imported.conditions == original.conditions
        assert imported.rationale == original.rationale
        assert imported.assumptions == original.assumptions
        assert imported.notes == original.notes
        assert imported.labels == original.labels
        assert imported.approved_at == original.approved_at
        assert imported.modified_at == original.modified_at
