"""Dirty prompt GUI tests are disabled for the simplified ListPanel build."""

from __future__ import annotations

import pytest

pytest.skip(
    "Упрощённый ListPanel не управляет выбором требований и не поддерживает диалоги подтверждения; тесты подсказки о несохранённых изменениях отключены.",
    allow_module_level=True,
)
