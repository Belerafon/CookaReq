from __future__ import annotations

import pytest

from app.core.markdown_utils import strip_markdown

pytestmark = pytest.mark.unit


def test_strip_markdown_converts_tables_to_plain_text() -> None:
    source = (
        "| A | B |\n"
        "|---|---|\n"
        "| 1 | 2 |\n"
        "| 3 | 4 |\n"
    )

    result = strip_markdown(source)

    assert "A | B" in result
    assert "1 | 2" in result
    assert "3 | 4" in result
    assert "---" not in result
