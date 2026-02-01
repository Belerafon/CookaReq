import pytest

from app.core.model import Link, Priority, Requirement, RequirementType, Status, Verification
from app.core.requirement_tabular_export import render_tabular_html
from app.core.requirement_text_export import render_requirement_cards_txt
from app.ui.requirement_exporter import build_tabular_export


def _make_requirement():
    return Requirement(
        id=7,
        title="Title\tWith Tab",
        statement="Line 1\nLine 2",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="Owner",
        priority=Priority.HIGH,
        source="Source",
        verification=Verification.TEST,
        labels=["alpha", "beta"],
        links=[Link(rid="SYS1", suspect=True)],
        attachments=[],
        doc_prefix="SYS",
        rid="SYS7",
    )


@pytest.mark.unit
def test_render_requirement_cards_txt_formats_multiline_fields():
    headers = ["Title", "Statement"]
    rows = [["A\tB", "Line1\nLine2"]]
    text = render_requirement_cards_txt(headers, rows)
    assert text.splitlines()[0] == "Title: A\tB"
    assert text.splitlines()[1] == "Statement: Line1"
    assert text.splitlines()[2] == "  Line2"


@pytest.mark.unit
def test_render_requirement_cards_txt_omits_empty_fields():
    headers = ["Title", "Owner"]
    rows = [["A", ""]]
    text = render_requirement_cards_txt(headers, rows)
    lines = text.splitlines()
    assert lines == ["Title: A"]


@pytest.mark.unit
def test_render_requirement_cards_txt_uses_placeholder_for_empty_fields():
    headers = ["Title", "Owner"]
    rows = [["A", ""]]
    text = render_requirement_cards_txt(headers, rows, empty_field_placeholder="(not set)")
    lines = text.splitlines()
    assert lines[0] == "Title: A"
    assert lines[1] == "Owner: (not set)"


@pytest.mark.unit
def test_render_requirement_cards_txt_strips_markdown():
    headers = ["Statement"]
    rows = [["See **bold** and [link](https://example.com) and `code`."]]
    text = render_requirement_cards_txt(headers, rows, strip_markdown_text=True)
    assert "bold" in text
    assert "link" in text
    assert "code" in text
    assert "**" not in text


@pytest.mark.unit
def test_render_tabular_html_converts_newlines():
    headers = ["Title", "Statement"]
    rows = [["Hello", "Line1\nLine2"]]
    html = render_tabular_html(headers, rows, title="Export")
    assert "<!DOCTYPE html>" in html
    assert "<h1>Export</h1>" in html
    assert "Line1<br>Line2" in html


@pytest.mark.unit
def test_build_tabular_export_formats_special_fields():
    requirement = _make_requirement()
    headers, rows = build_tabular_export(
        [requirement],
        ["title", "labels", "links", "derived_from", "derived_count", "id"],
        derived_map={"SYS7": [1, 2, 3]},
    )
    assert headers == [
        "Short title",
        "Labels",
        "Links",
        "Derived from",
        "Derived count",
        "Requirement ID (number)",
    ]
    assert rows == [[
        "Title\tWith Tab",
        "alpha, beta",
        "SYS1 ⚠",
        "SYS1 ⚠",
        "3",
        "7",
    ]]
