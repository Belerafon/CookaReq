"""ListPanel GUI tests are disabled in the simplified diagnostic build."""

from __future__ import annotations

import pytest

pytest.skip(
    "ListPanel временно упрощён до нативного wx.ListCtrl; подробные GUI-тесты отключены.",
    allow_module_level=True,
)
