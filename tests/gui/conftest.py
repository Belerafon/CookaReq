"""Pytest configuration for GUI test suite."""

import pytest

from app.application import ApplicationContext

# Apply the ``gui`` marker to every test in this package so they can be selected
# with ``-m gui`` and handled separately from non-GUI checks.
pytestmark = pytest.mark.gui


@pytest.fixture
def gui_context() -> ApplicationContext:
    """Provide a GUI application context with wx confirmation handlers."""

    pytest.importorskip("wx")
    return ApplicationContext.for_gui()
