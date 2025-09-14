import subprocess
import sys

import pytest

pytestmark = pytest.mark.slow


def test_vulture_finds_no_dead_code():
    """Ensure repository has no obvious dead code."""
    cmd = [sys.executable, "-m", "vulture", "app", "--min-confidence", "80"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == ""
