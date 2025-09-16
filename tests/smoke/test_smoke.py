import subprocess
import sys

import pytest

from app.core.document_store import Document, load_document, save_document
from app.core.model import requirement_from_dict, requirement_to_dict


@pytest.mark.smoke
@pytest.mark.unit
def test_requirement_roundtrip() -> None:
    data = {
        "id": 1,
        "title": "Example",
        "statement": "Do something",
        "type": "requirement",
        "status": "draft",
        "owner": "tester",
        "priority": "medium",
        "source": "spec",
        "verification": "analysis",
    }
    req = requirement_from_dict(data)
    assert requirement_to_dict(req)["statement"] == "Do something"


@pytest.mark.smoke
@pytest.mark.unit
def test_document_roundtrip(tmp_path) -> None:
    doc = Document(prefix="TST", title="Test", digits=3)
    doc_dir = tmp_path / doc.prefix
    save_document(doc_dir, doc)
    loaded = load_document(doc_dir)
    assert loaded.prefix == "TST"


@pytest.mark.smoke
@pytest.mark.integration
def test_cli_help() -> None:
    proc = subprocess.run([
        sys.executable,
        "-m",
        "app.cli",
        "--help",
    ], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "doc" in proc.stdout


@pytest.mark.smoke
@pytest.mark.integration
def test_cli_help_does_not_import_agent() -> None:
    script = (
        "import runpy, sys\n"
        "sys.argv=['prog','--help']\n"
        "try:\n"
        "    runpy.run_module('app.cli', run_name='__main__')\n"
        "except SystemExit:\n"
        "    pass\n"
        "print('app.agent' in sys.modules)\n"
    )
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0
    assert proc.stdout.splitlines()[-1] == "False"
