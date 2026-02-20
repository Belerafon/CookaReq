import subprocess
import sys

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.quality_lint]


def test_ruff_conformance():
    """Ensure code base complies with ruff rules."""
    cmd = [sys.executable, "-m", "ruff", "check", "app", "tests"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
