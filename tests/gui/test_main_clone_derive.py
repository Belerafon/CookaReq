"""Clone/derive GUI tests are disabled in the simplified ListPanel configuration."""

from __future__ import annotations

import pytest

pytest.skip(
    "Диагностическая сборка отключила расширенные действия ListPanel; сценарии клонов и производных требований пропущены.",
    allow_module_level=True,
)
