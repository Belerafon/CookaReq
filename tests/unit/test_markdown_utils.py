from __future__ import annotations

import pytest

from app.core import markdown_utils
from app.core.markdown_utils import convert_markdown_math, strip_markdown

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


def test_convert_markdown_math_renders_single_dollar_inline_formula(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        markdown_utils,
        "_convert_latex_to_mathml",
        lambda latex, *, display: f"<math display='{display}'><mi>{latex}</mi></math>",
    )

    rendered = convert_markdown_math("Speed is $v = s / t$.")

    assert "<math" in rendered
    assert "$v = s / t$" not in rendered

def test_convert_markdown_math_normalizes_escaped_newlines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        markdown_utils,
        "_convert_latex_to_mathml",
        lambda latex, *, display: f"<math display='{display}'><mi>{latex}</mi></math>",
    )

    rendered = convert_markdown_math(r"\(a+b\)\n\n$$\frac{c}{d}$$")

    assert r"\n\n" not in rendered
    assert "display='inline'" in rendered
    assert "display='block'" in rendered

