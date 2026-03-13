from __future__ import annotations

import logging

import pytest

from app import runtime_dependencies as module

pytestmark = pytest.mark.unit


def test_log_missing_startup_dependencies_logs_missing_modules(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    missing = {"mathml2omml"}

    monkeypatch.setattr(
        module.importlib.util,
        "find_spec",
        lambda name: None if name in missing else object(),
    )

    caplog.set_level(logging.WARNING, logger="cookareq")
    result = module.log_missing_startup_dependencies()

    assert result == ("mathml2omml",)
    assert "Optional runtime dependencies are missing: mathml2omml. Feature impact:" in caplog.text
    assert "mathml2omml → DOCX formula conversion (MathML → OMML for Word)" in caplog.text


def test_log_missing_startup_dependencies_returns_empty_when_all_available(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(module.importlib.util, "find_spec", lambda _name: object())

    caplog.set_level(logging.DEBUG, logger="cookareq")
    result = module.log_missing_startup_dependencies()

    assert result == ()
    assert "Startup dependency check passed" in caplog.text
