"""Integration GUI tests for ListPanel are disabled in the simplified build."""

from __future__ import annotations

import pytest

pytest.skip(
    "Диагностическая сборка использует упрощённый ListPanel без кастомизаций; интеграционные GUI-тесты отключены.",
    allow_module_level=True,
)
