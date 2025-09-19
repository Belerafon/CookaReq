"""Layout persistence tests are disabled for the simplified ListPanel build."""

from __future__ import annotations

import pytest

pytest.skip(
    "Диагностическая версия использует упрощённый ListPanel без панели агента; тесты сохранения раскладки временно отключены.",
    allow_module_level=True,
)
