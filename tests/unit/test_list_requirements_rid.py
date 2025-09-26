from app.core.document_store import Document, save_document, save_item
from app.mcp.tools_read import get_requirement, list_requirements


def test_list_requirements_returns_rid(tmp_path):
    doc = Document(prefix="SYS", title="System")
    save_document(tmp_path / "SYS", doc)
    save_item(
        tmp_path / "SYS",
        doc,
        {
            "id": 1,
            "title": "S",
            "statement": "",
            "type": "requirement",
            "status": "draft",
            "owner": "",
            "priority": "medium",
            "source": "",
            "verification": "analysis",
            "labels": [],
            "links": [],
        },
    )
    result = list_requirements(tmp_path)
    assert result["items"][0]["rid"] == "SYS1"


def _create_demo_requirement(tmp_path):
    doc = Document(prefix="SYS", title="System")
    save_document(tmp_path / "SYS", doc)
    data = {
        "id": 1,
        "title": "Telemetry",
        "statement": "Collect data",
        "type": "requirement",
        "status": "approved",
        "owner": "QA",
        "priority": "high",
        "source": "Spec",
        "verification": "analysis",
        "labels": ["telemetry"],
        "links": [],
        "notes": "",
    }
    save_item(tmp_path / "SYS", doc, data)


def test_list_requirements_field_filter(tmp_path):
    _create_demo_requirement(tmp_path)

    result = list_requirements(tmp_path, fields=["title", "status"])

    assert result["items"] == [
        {"rid": "SYS1", "title": "Telemetry", "status": "approved"}
    ]


def test_list_requirements_invalid_fields_returns_full_payload(tmp_path):
    _create_demo_requirement(tmp_path)

    result = list_requirements(tmp_path, fields="title")

    payload = result["items"][0]
    assert "id" in payload and "title" in payload and "status" in payload


def test_get_requirement_field_filter(tmp_path):
    _create_demo_requirement(tmp_path)

    result = get_requirement(tmp_path, "SYS1", fields=["owner", "labels"])

    assert result == {"rid": "SYS1", "owner": "QA", "labels": ["telemetry"]}
