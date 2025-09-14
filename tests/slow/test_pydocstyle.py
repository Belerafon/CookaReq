import subprocess
import sys

def test_pydocstyle_conformance():
    """Ensure docstring conventions are respected."""
    cmd = [sys.executable, "-m", "pydocstyle", "app"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
