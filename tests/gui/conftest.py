"""Pytest configuration for GUI test suite."""

import pytest

# Apply the ``gui`` marker to every test in this package so they can be selected
# with ``-m gui`` and handled separately from non-GUI checks.
pytestmark = pytest.mark.gui
