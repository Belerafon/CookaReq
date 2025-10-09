import subprocess
import sys

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.quality]


PYDOCSTYLE_TARGETS = [
    "app/core",
    "app/util",
    "app/mcp",
    "app/cli",
    "app/ui/chat_entry.py",
    "app/ui/helpers.py",
    "app/ui/main_frame/settings.py",
    "app/ui/document_tree.py",
    "app/ui/list_panel.py",
    "app/ui/document_dialog.py",
    "app/agent/local_agent.py",
]


def test_pydocstyle_conformance():
    """Ensure docstring conventions are respected on the curated backend scope."""
    cmd = [sys.executable, "-m", "pydocstyle", *PYDOCSTYLE_TARGETS]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
