import os
import sys
from pathlib import Path

# Ensure project root is on sys.path for imports
sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest


@pytest.fixture(scope="session", autouse=True)
def _virtual_display():
    # Skip virtual display on Windows or if DISPLAY is set
    if os.name == 'nt' or os.environ.get("DISPLAY"):
        yield
        return
    try:
        from pyvirtualdisplay import Display
    except Exception:
        yield
        return
    display = Display(visible=False, size=(1280, 800))
    display.start()
    try:
        yield
    finally:
        display.stop()
