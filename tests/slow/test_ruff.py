import subprocess
import sys
import pytest

pytestmark = pytest.mark.slow

def test_ruff_conformance():
    """Ensure code passes Ruff checks with basic rules."""
    cmd = [sys.executable, "-m", "ruff", "check", "app", "tests"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
