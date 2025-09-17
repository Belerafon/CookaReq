from app.core.document_store import Document, save_document, save_item
from app.mcp.tools_read import list_requirements


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
