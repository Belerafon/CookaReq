from __future__ import annotations

from pathlib import Path

import pytest

from app.core.requirement_import import (
    RequirementImportConfiguration,
    SequentialIDAllocator,
    TabularDataset,
    build_requirements,
    detect_format,
    TabularFileFormat,
    list_excel_sheets,
    load_csv_dataset,
    load_excel_dataset,
)


def test_detect_format_csv_and_excel(tmp_path: Path) -> None:
    csv_file = tmp_path / "requirements.csv"
    csv_file.write_text("id,title\n1,Sample\n", encoding="utf-8")
    xlsx_file = tmp_path / "requirements.xlsx"
    xlsx_file.touch()
    assert detect_format(csv_file) == TabularFileFormat.CSV
    assert detect_format("requirements.csv") == TabularFileFormat.CSV
    assert detect_format(xlsx_file) == TabularFileFormat.EXCEL
    assert detect_format("requirements.xlsx") == TabularFileFormat.EXCEL


def test_load_csv_dataset(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("id;statement\n1;Do something\n2;Do more\n", encoding="utf-8")
    dataset = load_csv_dataset(path, delimiter=";")
    assert dataset.header == ["id", "statement"]
    assert dataset.row_count(skip_header=True) == 2
    assert dataset.column_names(use_header=True)[0] == "id"


def test_build_requirements_with_auto_ids() -> None:
    dataset = TabularDataset(
        rows=[
            ["id", "statement", "labels"],
            ["", "First requirement", "alpha,beta"],
            [None, "Second requirement", "gamma"],
        ]
    )
    config = RequirementImportConfiguration(
        mapping={"statement": 1, "labels": 2},
        has_header=True,
    )
    allocator = SequentialIDAllocator(start=3, existing={1, 2})
    result = build_requirements(dataset, config, allocator=allocator)
    assert result.issues == []
    assert [req.id for req in result.requirements] == [3, 4]
    assert [req.labels for req in result.requirements] == [["alpha", "beta"], ["gamma"]]


def test_build_requirements_with_enums(tmp_path: Path) -> None:
    dataset = TabularDataset(
        rows=[
            ["statement", "status", "priority", "type", "verification"],
            ["Spec", "approved", "high", "interface", "test"],
        ]
    )
    config = RequirementImportConfiguration(
        mapping={"statement": 0, "status": 1, "priority": 2, "type": 3, "verification": 4},
        has_header=True,
    )
    allocator = SequentialIDAllocator(start=1)
    result = build_requirements(dataset, config, allocator=allocator)
    requirement = result.requirements[0]
    assert requirement.status.value == "approved"
    assert requirement.priority.value == "high"
    assert requirement.type.value == "interface"
    assert requirement.verification.value == "test"


def test_build_requirements_reports_errors() -> None:
    dataset = TabularDataset(
        rows=[
            ["id", "statement"],
            [1, ""],
            [1, "Valid"],
        ]
    )
    config = RequirementImportConfiguration(mapping={"id": 0, "statement": 1}, has_header=True)
    allocator = SequentialIDAllocator(start=1)
    result = build_requirements(dataset, config, allocator=allocator)
    assert len(result.issues) == 1
    assert result.issues[0].row == 1
    assert "statement" in result.issues[0].message
    assert [req.id for req in result.requirements] == [1]


def test_load_excel_dataset(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    Workbook = openpyxl.Workbook

    path = tmp_path / "data.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["statement", "owner"])
    ws.append(["Hello", "Alice"])
    wb.create_sheet("Extra")
    wb.save(path)
    wb.close()

    sheets = list_excel_sheets(path)
    assert "Extra" in sheets

    dataset = load_excel_dataset(path)
    assert dataset.row_count(skip_header=True) == 1
    assert dataset.header == ["statement", "owner"]

